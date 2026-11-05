#!/usr/bin/env python3
"""
Railway Ephemeral Preview Environment Manager for Pull Requests.

Usage:
    python3 scripts/railway_pr.py setup --pr <PR_NUMBER>
    python3 scripts/railway_pr.py cleanup --pr <PR_NUMBER>
    python3 scripts/railway_pr.py get-url --pr <PR_NUMBER>
    python3 scripts/railway_pr.py wait-provisioning --pr <PR_NUMBER> --head-sha <SHA>
"""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

try:  # Supports both repo-module imports and direct `python scripts/railway_pr.py`.
    from scripts.auth_config import authorized_parties_for
except ModuleNotFoundError:  # pragma: no cover - exercised by direct CLI invocation
    from auth_config import authorized_parties_for

DEFAULT_PROJECT_ID = "c49458fb-d741-468f-a3ed-d35b96788f68"
DEFAULT_SERVICE_ID = "d83b1b1b-ffb9-4565-ad7f-8284bb2403a9"
DEFAULT_DEV_ENV_ID = "e0d4551b-ff56-4f0f-9dd0-ef3c74af31cb"
DEFAULT_DEV_URL = "https://p063-backend-dev.up.railway.app"
RAILWAY_WORKFLOW = "deploy-railway.yml"
DEFAULT_PROVISIONING_TIMEOUT = 15 * 60
DEFAULT_PROVISIONING_POLL = 10
_GRAPHQL_ERROR_CODES = {
    "BAD_USER_INPUT",
    "FORBIDDEN",
    "GRAPHQL_PARSE_FAILED",
    "GRAPHQL_VALIDATION_FAILED",
    "INTERNAL_SERVER_ERROR",
    "INVALID_ARGUMENT",
    "NOT_FOUND",
    "UNAUTHENTICATED",
    "UNAUTHORIZED",
}
_SENSITIVE_NAME = ("key", "token", "password", "secret", "credential")
_RATE_LIMIT_PATTERN = re.compile(r"(?i)(rate[\s-]?limit(?:ed)?|ratelimited|too many requests|HTTP\s*429)")
_TRANSIENT_PATTERN = re.compile(
    r"(?i)(rate[\s-]?limit(?:ed)?|ratelimited|too many requests|HTTP\s*429|HTTP\s*5\d\d|timed[\s-]?out|connection)"
)
_RETRY_AFTER_PATTERN = re.compile(
    r"(?i)try again in about\s+(\d+(?:\.\d+)?)\s*(seconds?|minutes?)",
)


def _calculate_retry_delay(text: str, attempt: int) -> int:
    match = _RETRY_AFTER_PATTERN.search(text)
    if match:
        val = float(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith("minute"):
            val *= 60
        return int(min(val, 120))
    base = 15 * (2 ** (attempt - 1))
    return int(min(base, 120))


def _sanitize_deployment_logs(output: str) -> str:
    """Keep deployment diagnostics useful without exposing credentials."""
    import re

    result = output or "(no deployment logs returned)"
    secrets = [
        value
        for name, value in os.environ.items()
        if (any(part in name.lower() for part in _SENSITIVE_NAME) or name.endswith("DATABASE_URL")) and value
    ]
    for secret in sorted(set(secrets), key=len, reverse=True):
        result = result.replace(secret, "[REDACTED]")
    result = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)([^/@\s]+):([^/@\s]+)@", r"\1[REDACTED]@", result)
    result = re.sub(
        r"(?i)([A-Z][A-Z0-9_]*(?:KEY|TOKEN|PASSWORD|SECRET|CREDENTIAL)[A-Z0-9_]*)\s*[=:]\s*[^\s]+",
        r"\1=[REDACTED]",
        result,
    )
    return result[-12000:]


def _deployment_failure_logs(deployment_id: str, service_id: str, project_id: str, env_name: str) -> str:
    """Best-effort bounded Railway build/deployment diagnostics."""
    sections = []
    for log_type in ("--build", "--deployment"):
        try:
            result = subprocess.run(
                [
                    "railway",
                    "logs",
                    deployment_id,
                    log_type,
                    "--lines",
                    "100",
                    "--service",
                    service_id,
                    "--project",
                    project_id,
                    "--environment",
                    env_name,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            detail = _sanitize_deployment_logs(result.stdout or result.stderr)
        except Exception as exc:  # Diagnostics must never replace the deployment failure.
            detail = f"(unable to retrieve logs: {type(exc).__name__})"
        sections.append(f"{log_type}:\n{detail}")
    return "\n".join(sections)


def preview_failure_diagnostics(service_id: str, project_id: str, env_name: str) -> str:
    """Best-effort bounded logs for the latest preview deployment."""
    try:
        result = subprocess.run(
            [
                "railway",
                "logs",
                "--deployment",
                "--lines",
                "100",
                "--service",
                service_id,
                "--project",
                project_id,
                "--environment",
                env_name,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return _sanitize_deployment_logs(result.stdout or result.stderr)
    except Exception as exc:  # Diagnostics must never replace the health failure.
        return f"(unable to retrieve preview logs: {type(exc).__name__})"


def prepare_preview_schema(service_id: str, project_id: str, env_name: str, pr_number: int, head_sha: str) -> None:
    """Apply schema migrations inside the isolated, deployed preview service."""
    if env_name != f"pr-{pr_number}" or not head_sha:
        raise RuntimeError("preview schema preparation requires a matching pr-* environment and head SHA")
    command = [
        "railway",
        "ssh",
        "--project",
        project_id,
        "--service",
        service_id,
        "--environment",
        env_name,
        "--",
        "python",
        "-m",
        "scripts.prepare_preview_database",
        "--pr",
        str(pr_number),
        "--head-sha",
        head_sha,
    ]
    try:
        with tempfile.TemporaryDirectory(prefix="p063-railway-ssh-") as temp_home:
            ssh_dir = os.path.join(temp_home, ".ssh")
            os.makedirs(ssh_dir, mode=0o700)
            key_path = os.path.join(ssh_dir, "id_ed25519")
            config_path = os.path.join(ssh_dir, "config")
            with open(config_path, "w", encoding="utf-8") as ssh_config:
                ssh_config.write(
                    "Host *\n"
                    "    StrictHostKeyChecking accept-new\n"
                    f'    UserKnownHostsFile "{os.path.join(ssh_dir, "known_hosts")}"\n'
                )
            # OpenSSH resolves ~/.ssh through the OS account, not HOME on Unix.
            # Railway invokes `ssh` via PATH; explicitly pass our isolated config.
            ssh_binary = shutil.which("ssh")
            if not ssh_binary:
                raise RuntimeError("OpenSSH is required for preview schema preparation")
            bin_dir = os.path.join(temp_home, "bin")
            os.makedirs(bin_dir, mode=0o700)
            wrapper_path = os.path.join(bin_dir, "ssh")
            with open(wrapper_path, "w", encoding="utf-8", newline="\n") as wrapper:
                wrapper.write(f'#!/bin/sh\nexec {shlex.quote(ssh_binary)} -F {shlex.quote(config_path)} "$@"\n')
            os.chmod(wrapper_path, 0o700)
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", key_path],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            fingerprint_result = subprocess.run(
                ["ssh-keygen", "-lf", f"{key_path}.pub"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            fingerprint = (fingerprint_result.stdout or "").split()[1]
            key_name = f"p063-pr-{pr_number}-{os.path.basename(temp_home)[-12:]}"
            subprocess.run(
                ["railway", "ssh", "keys", "add", "--key", f"{key_path}.pub", "--name", key_name],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "HOME": temp_home},
            )
            try:
                result = subprocess.run(
                    ["railway", "ssh", "--identity-file", key_path, *command[2:]],
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env={
                        **os.environ,
                        "HOME": temp_home,
                        "PATH": bin_dir + os.pathsep + os.environ.get("PATH", ""),
                    },
                )
            finally:
                try:
                    cleanup = subprocess.run(
                        ["railway", "ssh", "keys", "remove", fingerprint],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env={**os.environ, "HOME": temp_home},
                    )
                    if cleanup.returncode:
                        print("Warning: temporary Railway SSH key removal failed.")
                except Exception:
                    print("Warning: temporary Railway SSH key removal failed.")
    except Exception as exc:
        raise RuntimeError(f"preview schema preparation failed: {type(exc).__name__}") from exc
    if result.returncode != 0:
        detail = _sanitize_deployment_logs(result.stderr or result.stdout)
        raise RuntimeError(f"preview schema preparation failed: {detail}")
    print(_sanitize_deployment_logs(result.stdout or "Preview schema prepared."))


def _scalar_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [item for child in value.values() for item in _scalar_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in _scalar_values(child)]
    return [str(value)] if isinstance(value, (str, int, float, bool)) else []


def _clean_error_message(message: str, variables: dict[str, Any] | None = None) -> str:
    secrets = _scalar_values(variables or {})
    for name, value in os.environ.items():
        if any(part in name.lower() for part in _SENSITIVE_NAME) and value:
            secrets.append(value)

    result = message
    for secret in sorted(set(secrets), key=len, reverse=True):
        result = result.replace(secret, "[REDACTED]")
    result = re.sub(r"https?://[^\s?]+\?[^\s]+", "[REDACTED_URL]", result)
    result = re.sub(
        r"(?i)(key|token|password|secret|credential)\s*[=:]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        result,
    )
    result = result.replace("\r", " ").replace("\n", " ").strip()
    return result[:240]


def _sanitize_graphql_errors(
    stdout: str,
    variables: dict[str, Any] | None = None,
    stderr: str = "",
) -> str:
    try:
        payload = json.loads(stdout)
    except (TypeError, json.JSONDecodeError):
        snippet = _clean_error_message(f"{stdout}{stderr}", variables)
        return f"Railway API returned a non-JSON error response: {snippet}"
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if not isinstance(errors, list) or not errors or not all(isinstance(error, dict) for error in errors):
        return "Railway API returned an unexpected error response"

    details: list[str] = []
    for error in errors:
        code = error.get("extensions", {}).get("code") if isinstance(error.get("extensions"), dict) else None
        safe_code = code if isinstance(code, str) and code in _GRAPHQL_ERROR_CODES else "UNKNOWN"
        message = error.get("message")
        if isinstance(message, str) and message:
            details.append(f"{safe_code}: {_clean_error_message(message, variables)}")
        else:
            details.append(safe_code)
    return f"Railway API returned {len(errors)} GraphQL error(s): {'; '.join(details)}"


def run_railway_api(
    query: str,
    variables: dict[str, Any] | None = None,
    sleep: Callable[[float], Any] = time.sleep,
) -> dict[str, Any]:
    """Execute a GraphQL query/mutation via Railway CLI."""
    cmd = ["railway", "api", query]
    if variables:
        cmd.extend(["--variables", json.dumps(variables)])

    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            try:
                return json.loads(res.stdout)
            except json.JSONDecodeError as err:
                raise RuntimeError(f"Failed to parse railway api response: {res.stdout}") from err

        combined_output = f"{res.stdout}{res.stderr}".strip()
        is_json_response = False
        if res.stdout.strip():
            try:
                json.loads(res.stdout)
                is_json_response = True
            except (TypeError, json.JSONDecodeError):
                is_json_response = False

        is_env_create = query.strip().lower().startswith("mutation") and "environmentCreate" in query
        if is_env_create:
            is_transient = not is_json_response and bool(_RATE_LIMIT_PATTERN.search(combined_output))
        else:
            is_transient = not is_json_response and bool(_TRANSIENT_PATTERN.search(combined_output))

        if is_transient and attempt < max_attempts:
            delay = _calculate_retry_delay(combined_output, attempt)
            sanitized = _clean_error_message(f"{res.stdout}{res.stderr}", variables)
            print(
                f"[!] Railway API transient error (attempt {attempt}/{max_attempts}): {sanitized}; retrying in {delay}s",
                file=sys.stderr,
            )
            sleep(delay)
            continue

        if res.stdout.strip():
            raise RuntimeError(_sanitize_graphql_errors(res.stdout, variables, stderr=res.stderr))
        raise RuntimeError("Railway API request failed")

    raise RuntimeError("Railway API request failed")


def get_environments(project_id: str) -> list[dict[str, Any]]:
    """List all environments in a Railway project."""
    query = """
    query getEnvironments($projectId: String!) {
      project(id: $projectId) {
        environments {
          edges {
            node {
              id
              name
              isEphemeral
            }
          }
        }
      }
    }
    """
    data = run_railway_api(query, {"projectId": project_id})
    edges = data.get("data", {}).get("project", {}).get("environments", {}).get("edges", [])
    return [edge["node"] for edge in edges if "node" in edge]


def create_pr_environment(project_id: str, pr_number: int, source_env_id: str) -> dict[str, Any]:
    """Create an ephemeral environment duplicated from dev."""
    env_name = f"pr-{pr_number}"
    query = """
    mutation createEnv($input: EnvironmentCreateInput!) {
      environmentCreate(input: $input) {
        id
        name
      }
    }
    """
    variables = {
        "input": {
            "projectId": project_id,
            "name": env_name,
            "sourceEnvironmentId": source_env_id,
            "ephemeral": True,
        }
    }
    data = run_railway_api(query, variables)
    env_data = data.get("data", {}).get("environmentCreate")
    if not env_data:
        raise RuntimeError(f"Failed to create environment: {data}")
    return env_data


def delete_environment_by_id(env_id: str) -> bool:
    """Delete an environment by its Railway ID."""
    query = """
    mutation deleteEnv($id: String!) {
      environmentDelete(id: $id)
    }
    """
    data = run_railway_api(query, {"id": env_id})
    return bool(data.get("data", {}).get("environmentDelete", False))


def get_service_domain(service_name_or_id: str, env_name: str) -> str | None:
    """Retrieve existing domain for a service in the target environment."""
    res = subprocess.run(
        [
            "railway",
            "domain",
            "list",
            "--service",
            service_name_or_id,
            "--environment",
            env_name,
            *(["--project", os.environ["RAILWAY_PROJECT_ID"]] if os.environ.get("RAILWAY_PROJECT_ID") else []),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0 and res.stdout.strip():
        try:
            data = json.loads(res.stdout)
            domains = data.get("domains", [])
            if domains and isinstance(domains, list):
                return domains[0].get("domain")
        except Exception:
            pass
    return None


def create_service_domain(service_id: str, env_id: str) -> str:
    """Generate a Railway-provided domain for the service in the environment."""
    query = """
    mutation createDomain($input: ServiceDomainCreateInput!) {
      serviceDomainCreate(input: $input) {
        id
        domain
      }
    }
    """
    variables = {
        "input": {
            "environmentId": env_id,
            "serviceId": service_id,
        }
    }
    data = run_railway_api(query, variables)
    domain_info = data.get("data", {}).get("serviceDomainCreate")
    if not domain_info or not domain_info.get("domain"):
        raise RuntimeError(f"Failed to create service domain: {data}")
    return domain_info["domain"]


def set_service_variable(service_id: str, project_id: str, env_name: str, key: str, value: str) -> bool:
    """Set an environment variable for a service on Railway."""
    cmd = [
        "railway",
        "variable",
        "set",
        f"{key}={value}",
        "--service",
        service_id,
        "--project",
        project_id,
        "--environment",
        env_name,
        "--skip-deploys",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[WARN] railway variable set failed: {res.stderr.strip() or res.stdout.strip()}", file=sys.stderr)
        return False
    return True


def find_json_field(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if value.get(key):
            return value[key]
        children = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return None
    for child in children:
        found = find_json_field(child, key)
        if found:
            return found
    return None


def deployment_status(value: Any, deployment_id: str) -> str | None:
    if isinstance(value, dict):
        if value.get("id") == deployment_id or value.get("deploymentId") == deployment_id:
            return value.get("status")
        children = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return None
    for child in children:
        found = deployment_status(child, deployment_id)
        if found:
            return found
    return None


def deploy_service(service_id: str, project_id: str, env_name: str, pr_number: int) -> None:
    """Deploy service container to the PR environment."""
    cmd = [
        "railway",
        "up",
        "--service",
        service_id,
        "--project",
        project_id,
        "--environment",
        env_name,
        "--detach",
        "--json",
        "-m",
        f"CI/CD: PR Preview #{pr_number}",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        raise RuntimeError("Railway upload failed")
    deployment_id = None
    for line in res.stdout.splitlines():
        try:
            deployment_id = find_json_field(json.loads(line), "deploymentId") or deployment_id
        except json.JSONDecodeError:
            continue
    if not deployment_id:
        raise RuntimeError("Railway upload did not return a deployment ID")
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        # `deployment list` flakes (non-zero exit) under fleet load; retry a
        # few times before treating it as fatal so one blip cannot fail setup.
        result = None
        for attempt in range(4):
            try:
                result = subprocess.run(
                    [
                        "railway",
                        "deployment",
                        "list",
                        "--service",
                        service_id,
                        "--project",
                        project_id,
                        "--environment",
                        env_name,
                        "--json",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=30,
                )
                break
            except subprocess.CalledProcessError as exc:
                if attempt == 3:
                    detail = (exc.stderr or exc.stdout or "").strip()[:200]
                    raise RuntimeError(f"Railway deployment list failed: {detail}") from exc
                time.sleep(5)
        assert result is not None
        status = deployment_status(json.loads(result.stdout), deployment_id)
        if status == "SUCCESS":
            return
        if status and status not in {"INITIALIZING", "QUEUED", "BUILDING", "DEPLOYING", "WAITING"}:
            diagnostics = _deployment_failure_logs(deployment_id, service_id, project_id, env_name)
            raise RuntimeError(
                f"Railway deployment {deployment_id} ended in {status}\nDeployment diagnostics:\n{diagnostics}"
            )
        time.sleep(5)
    raise RuntimeError(f"Railway deployment {deployment_id} timed out")


def wait_for_health(url: str, timeout_seconds: int = 60) -> bool:
    """Poll health endpoint until healthy or timeout."""
    health_url = f"{url.rstrip('/')}/health"
    start = time.time()
    while time.time() - start < timeout_seconds:
        try:
            with urllib.request.urlopen(health_url, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(4)
    return False


def get_railway_workflow_runs(pr_number: int, head_sha: str) -> list[dict[str, Any]]:
    """Read workflow metadata with authenticated CLI or runner-token REST."""
    endpoint = (
        f"repos/AI20K-Build-Phase-Cohort-4/P-063/actions/workflows/{RAILWAY_WORKFLOW}"
        f"/runs?event=pull_request&head_sha={head_sha}&per_page=20"
    )
    try:
        result = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise RuntimeError("GitHub CLI or GH_TOKEN is required to read workflow metadata") from None
        request = urllib.request.Request(
            f"https://api.github.com/{endpoint}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "P-063-preview-ci",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response).get("workflow_runs", [])
    if result.returncode != 0:
        raise RuntimeError(f"gh api failed: {result.stderr.strip() or result.stdout.strip()}")
    try:
        return json.loads(result.stdout).get("workflow_runs", [])
    except json.JSONDecodeError as err:
        raise RuntimeError(f"Failed to parse gh api response: {result.stdout}") from err


def wait_for_provisioning(
    pr_number: int,
    head_sha: str,
    timeout_seconds: int = DEFAULT_PROVISIONING_TIMEOUT,
    poll_seconds: int = DEFAULT_PROVISIONING_POLL,
    get_runs: Callable[[int, str], list[dict[str, Any]]] = get_railway_workflow_runs,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Wait for the exact PR/head Railway workflow to finish provisioning."""
    deadline = clock() + timeout_seconds
    while clock() < deadline:
        matching = [
            run
            for run in get_runs(pr_number, head_sha)
            if run.get("head_sha") == head_sha
            and any(pr.get("number") == pr_number for pr in run.get("pull_requests", []))
        ]
        matching.sort(key=lambda run: run.get("created_at", ""), reverse=True)
        if matching:
            run = matching[0]
            status = run.get("status")
            conclusion = run.get("conclusion")
            if status == "completed":
                if conclusion == "success":
                    return
                raise RuntimeError(
                    f"Railway provisioning workflow {run.get('id', 'unknown')} ended in {conclusion or 'failure'}"
                )
        sleep(min(poll_seconds, max(0, deadline - clock())))
    raise RuntimeError(f"Railway provisioning workflow timed out for PR {pr_number} at {head_sha}")


def setup_pr(
    pr_number: int,
    project_id: str,
    service_id: str,
    source_env_id: str,
    head_sha: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    env_name = f"pr-{pr_number}"
    print(f"[*] Setting up preview environment '{env_name}' on Railway...")

    envs = get_environments(project_id)
    target_env = next((e for e in envs if e.get("name") == env_name), None)

    if not target_env:
        print(f"[*] Environment '{env_name}' not found. Creating ephemeral environment duplicated from dev...")
        try:
            target_env = create_pr_environment(project_id, pr_number, source_env_id)
            print(f"[+] Created environment: {target_env['id']} ({env_name})")
        except RuntimeError as err:
            print(f"[WARN] Failed to create environment: {err}", file=sys.stderr)
            if "already exists" in str(err).lower():
                envs = get_environments(project_id)
                target_env = next((e for e in envs if e.get("name") == env_name), None)
            if not target_env:
                for _ in range(6):
                    sleep(10)
                    envs = get_environments(project_id)
                    target_env = next((e for e in envs if e.get("name") == env_name), None)
                    if target_env:
                        break
            if target_env:
                print(f"[+] Adopted environment created despite API error: {target_env['id']}")
            else:
                raise
    else:
        print(f"[+] Found existing environment: {target_env['id']} ({env_name})")

    env_id = target_env["id"]

    domain = get_service_domain(service_id, env_name)
    if not domain:
        print(f"[*] Generating domain for service in environment '{env_name}'...")
        try:
            domain = create_service_domain(service_id, env_id)
            print(f"[+] Generated domain: {domain}")
        except Exception as e:
            print(f"[WARN] Failed to create domain via GraphQL: {e}. Polling for domain...", file=sys.stderr)
            for _ in range(4):
                time.sleep(2)
                domain = get_service_domain(service_id, env_name)
                if domain:
                    print(f"[+] Found domain after retry: {domain}")
                    break

    if not domain:
        domain = f"p063-backend-{env_name}.up.railway.app"

    # Preview environments must resolve their own Postgres service reference.
    # Never copy DEV_DATABASE_URL: that silently points previews at shared dev data.
    preview_db_url = "${{Postgres.DATABASE_URL}}"
    print(f"[*] Binding preview DATABASE_URL to the Postgres service in '{env_name}'...")
    if not set_service_variable(service_id, project_id, env_name, "DATABASE_URL", preview_db_url):
        raise RuntimeError("failed to configure preview DATABASE_URL")

    # Start with declared dev origins. The frontend workflow adds its exact
    # Vercel deployment origin after the scoped backend is ready.
    authorized_parties = authorized_parties_for(env_name, os.environ.get("CLERK_AUTHORIZED_PARTIES"))
    if not set_service_variable(service_id, project_id, env_name, "CLERK_AUTHORIZED_PARTIES", authorized_parties):
        raise RuntimeError("failed to configure Clerk authorized parties for preview")

    if head_sha and not set_service_variable(service_id, project_id, env_name, "P063_PREVIEW_HEAD_SHA", head_sha):
        raise RuntimeError("failed to record preview head SHA")
    preview_url = f"https://{domain}"
    print(f"[*] Deploying backend service to '{env_name}'...")
    deploy_service(service_id, project_id, env_name, pr_number)
    if head_sha:
        prepare_preview_schema(service_id, project_id, env_name, pr_number, head_sha)

    print(f"[*] Preview service deployed: {preview_url}")

    # Set GitHub Actions output if in GHA
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"railway_url={preview_url}\n")
            f.write(f"railway_env={env_name}\n")
            f.write(f"railway_domain={domain}\n")

    print(
        json.dumps(
            {
                "status": "success",
                "environment": env_name,
                "environment_id": env_id,
                "domain": domain,
                "url": preview_url,
            },
            indent=2,
        )
    )


def cleanup_pr(pr_number: int, project_id: str) -> None:
    env_name = f"pr-{pr_number}"
    print(f"[*] Cleaning up ephemeral environment '{env_name}'...")
    envs = get_environments(project_id)
    target_env = next((e for e in envs if e.get("name") == env_name), None)

    if not target_env:
        print(f"[OK] Environment '{env_name}' does not exist or was already deleted.")
        return

    if not target_env.get("isEphemeral"):
        raise RuntimeError("refusing to delete a non-ephemeral environment")
    env_id = target_env["id"]
    print(f"[*] Deleting environment '{env_name}' ({env_id})...")
    deleted = delete_environment_by_id(env_id)
    if not deleted:
        raise RuntimeError(f"failed to delete ephemeral environment {env_name}")
    print(f"[+] Environment '{env_name}' successfully removed.")


def get_url(
    pr_number: int, project_id: str, service_id: str, require_preview: bool = False, head_sha: str | None = None
) -> None:
    env_name = f"pr-{pr_number}"
    if head_sha:
        result = subprocess.run(
            [
                "railway",
                "variable",
                "list",
                "--project",
                project_id,
                "--service",
                service_id,
                "--environment",
                env_name,
                "--json",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        if json.loads(result.stdout).get("P063_PREVIEW_HEAD_SHA") != head_sha:
            raise RuntimeError("Railway preview head does not match requested head")
    domain = get_service_domain(service_id, env_name)
    if domain:
        url = f"https://{domain}"
    else:
        if require_preview:
            raise RuntimeError(f"preview Railway domain for pr-{pr_number} is not provisioned")
        url = DEFAULT_DEV_URL
    print(url)


def main():
    parser = argparse.ArgumentParser(description="Railway PR Environment Manager")
    parser.add_argument("action", choices=["setup", "cleanup", "get-url", "wait-provisioning"])
    parser.add_argument("--pr", type=int, required=True, help="Pull Request number")
    parser.add_argument("--project-id", default=os.getenv("RAILWAY_PROJECT_ID", DEFAULT_PROJECT_ID))
    parser.add_argument(
        "--service-id", default=os.getenv("RAILWAY_DEV_SERVICE_ID", os.getenv("RAILWAY_SERVICE_ID", DEFAULT_SERVICE_ID))
    )
    parser.add_argument("--source-env-id", default=os.getenv("RAILWAY_DEV_ENVIRONMENT_ID", DEFAULT_DEV_ENV_ID))
    parser.add_argument("--require-preview", action="store_true")
    parser.add_argument("--head-sha", help="Exact pull request head SHA for workflow synchronization")

    args = parser.parse_args()

    if args.action == "setup":
        setup_pr(args.pr, args.project_id, args.service_id, args.source_env_id, args.head_sha)
    elif args.action == "cleanup":
        cleanup_pr(args.pr, args.project_id)
    elif args.action == "get-url":
        get_url(args.pr, args.project_id, args.service_id, args.require_preview, args.head_sha)
    elif args.action == "wait-provisioning":
        if not args.head_sha:
            parser.error("wait-provisioning requires --head-sha")
        wait_for_provisioning(args.pr, args.head_sha)


if __name__ == "__main__":
    main()
