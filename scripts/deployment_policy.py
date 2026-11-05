#!/usr/bin/env python3
"""Shared deployment routing and fail-closed GitHub environment checks."""

import argparse
import json
import os
import re
import subprocess
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

BACKEND_FILES = {
    "Dockerfile",
    "docker-compose.yml",
    "requirements.txt",
    "pyproject.toml",
    "uv.lock",
    "railway.json",
    "railway.toml",
    "scripts/railway_pr.py",
    "scripts/auth_config.py",
    "scripts/deployment_policy.py",
    "scripts/vercel_deploy.sh",
    "scripts/vercel_project.py",
    ".github/workflows/deploy-railway.yml",
    ".github/workflows/deploy-vercel.yml",
}


class NoGitHubRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def next_github_page(link: str) -> str | None:
    if not link:
        return None
    next_pages = []
    for part in link.split(","):
        entry = re.fullmatch(r"\s*<([^<>]+)>\s*;(.*)", part)
        if not entry:
            raise RuntimeError("GitHub API returned invalid pagination links")
        relation = re.search(r'(?:^|;)\s*rel\s*=\s*(?:"([^"]+)"|([^;\s]+))\s*(?=;|$)', entry[2])
        if not relation:
            raise RuntimeError("GitHub API returned invalid pagination links")
        if "next" in (relation[1] or relation[2]).split():
            next_pages.append(entry[1])
    if len(next_pages) > 1:
        raise RuntimeError("GitHub API returned ambiguous pagination links")
    return next_pages[0] if next_pages else None


def trusted_github_page(url: str, original_url: str, repository: str) -> str:
    try:
        parsed = urlsplit(url)
        original = urlsplit(original_url)
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise RuntimeError("Unsafe GitHub API pagination URL") from None
    query = dict(pairs)
    original_query = dict(parse_qsl(original.query))
    endpoint = original.path[len(f"/repos/{repository}") :]
    canonical_path = re.fullmatch(r"/repositories/[1-9][0-9]*" + re.escape(endpoint), parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.github.com"
        or (parsed.path != original.path and not canonical_path)
        or parsed.fragment
        or any(character.isspace() for character in url)
        or len(query) != len(pairs)
        or set(query) != set(original_query) | {"page"}
        or any(query.get(key) != value for key, value in original_query.items())
        or not re.fullmatch(r"[1-9][0-9]*", query.get("page", ""))
    ):
        raise RuntimeError("Unsafe GitHub API pagination URL")
    # GitHub emits canonical /repositories/<id> links. Keep every request on
    # the configured owner/repository route, using only validated page values.
    return f"https://api.github.com{original.path}?{urlencode({**original_query, 'page': query['page']})}"


def github_rest_api(path: str, paginate: bool, repository: str) -> Any:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GitHub REST fallback requires GH_TOKEN or GITHUB_TOKEN")
    if not token.isascii() or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127 for character in token
    ):
        raise RuntimeError("GitHub REST fallback received an invalid token")
    original_url = f"https://api.github.com/repos/{repository}/{path}"
    url: str | None = original_url
    expected_path = urlsplit(original_url).path
    opener = build_opener(NoGitHubRedirect())
    pages: list[Any] = []
    visited: set[str] = set()
    while url:
        try:
            parsed = urlsplit(url)
        except ValueError:
            raise RuntimeError("Unsafe GitHub API pagination URL") from None
        if (
            parsed.scheme != "https"
            or parsed.netloc != "api.github.com"
            or parsed.path != expected_path
            or parsed.fragment
            or any(character.isspace() for character in url)
            or url in visited
            or len(visited) >= 100
        ):
            raise RuntimeError("Unsafe or repeated GitHub API pagination URL")
        visited.add(url)
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with opener.open(request, timeout=30) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"GitHub API request failed (HTTP {response.status})")
                payload = json.load(response)
                link = response.headers.get("Link", "")
        except HTTPError as error:
            status = error.code
            error.close()
            raise RuntimeError(f"GitHub API request failed (HTTP {status})") from None
        except (URLError, OSError):
            raise RuntimeError("GitHub API request failed before confirmation") from None
        except (UnicodeError, json.JSONDecodeError):
            raise RuntimeError("GitHub API returned invalid JSON") from None
        if not paginate:
            return payload
        pages.append(payload)
        next_url = next_github_page(link)
        url = trusted_github_page(next_url, original_url, repository) if next_url else None
    return pages


def github_api(path: str, paginate: bool = False) -> Any:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or any(
        part in {".", ".."} for part in repository.split("/")
    ):
        raise RuntimeError("GITHUB_REPOSITORY must specify an owner/repository")
    command = ["gh", "api", f"repos/{repository}/{path}"]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return github_rest_api(path, paginate, repository)
    return json.loads(result.stdout)


def classify(pr: int) -> dict[str, bool]:
    pages = github_api(f"pulls/{pr}/files?per_page=100", paginate=True)
    paths = {item[key] for page in pages for item in page for key in ("filename", "previous_filename") if key in item}
    backend = any(
        path in BACKEND_FILES
        or (path.startswith("src/") and not path.startswith("src/webapp/"))
        or path.startswith(("migrations/", "db/migrations/"))
        for path in paths
    )
    return {
        "backend": backend,
        "frontend": backend or any(path.startswith("src/webapp/") or path == "vercel.json" for path in paths),
    }


def check_environment(environment: str) -> None:
    payload = github_api(f"environments/{environment}")
    if not any(
        rule.get("type") == "required_reviewers" and rule.get("reviewers")
        for rule in payload.get("protection_rules", [])
    ):
        raise RuntimeError(f"{environment} requires configured GitHub environment reviewers")
    if environment == "production":
        policy = payload.get("deployment_branch_policy") or {}
        if not policy.get("custom_branch_policies") or policy.get("protected_branches"):
            raise RuntimeError("production requires an explicit main-only branch policy")
        pages = github_api(f"environments/{environment}/deployment-branch-policies?per_page=100", paginate=True)
        rules = [rule for page in pages for rule in page.get("branch_policies", [])]
        if len(rules) != 1 or rules[0].get("name") != "main" or rules[0].get("type") != "branch":
            raise RuntimeError("production deployment branch policy must allow only branch main")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["classify", "check-environment"])
    parser.add_argument("--pr", type=int)
    parser.add_argument("--environment", choices=["staging", "production"])
    args = parser.parse_args()
    if args.action == "check-environment":
        if not args.environment:
            parser.error("check-environment requires --environment")
        check_environment(args.environment)
        return
    if not args.pr:
        parser.error("classify requires --pr")
    values = classify(args.pr)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        for key, value in values.items():
            output.write(f"{key}={str(value).lower()}\n")


if __name__ == "__main__":
    main()
