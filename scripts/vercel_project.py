#!/usr/bin/env python3
"""Verify and alias Vercel deployments using project-scoped REST endpoints."""

import argparse
import ipaddress
import json
import math
import os
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


class VercelError(Exception):
    """A deployment failure safe to display without API bodies or credentials."""


class VercelHTTPError(VercelError):
    def __init__(self, status: int) -> None:
        self.status = status
        reason = "authentication or authorization failed" if status in {401, 403} else "request failed"
        super().__init__(f"Vercel API {reason} (HTTP {status})")


class VercelTransportError(VercelError):
    """A bounded retry is safe for reads after this transport failure."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def domain_name(value: str | None) -> str:
    if not value or len(value) > 253 or "." not in value:
        raise VercelError("Invalid alias domain")
    domain = value.lower()
    if any(not DNS_LABEL.fullmatch(label) for label in domain.split(".")):
        raise VercelError("Invalid alias domain")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        return domain
    raise VercelError("Invalid alias domain")


def deployment_hostname(reference: str | None) -> str:
    if not reference or any(character.isspace() for character in reference):
        raise VercelError("Invalid Vercel deployment URL")
    try:
        parsed = urlsplit(reference if "://" in reference else f"https://{reference}")
    except ValueError:
        raise VercelError("Invalid Vercel deployment URL") from None
    hostname = parsed.hostname
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.netloc.lower() != hostname
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not hostname.endswith(".vercel.app")
    ):
        raise VercelError("Invalid Vercel deployment URL")
    try:
        return domain_name(hostname)
    except VercelError:
        raise VercelError("Invalid Vercel deployment URL") from None


def api_request(
    opener: OpenerDirector,
    settings: Mapping[str, str],
    path: str,
    timeout: float,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"https://api.vercel.com{path}?{urlencode({'teamId': settings['VERCEL_ORG_ID']})}"
    headers = {"Authorization": f"Bearer {settings['VERCEL_TOKEN']}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, headers=headers, data=json.dumps(body).encode() if body is not None else None)
    try:
        with opener.open(request, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                raise VercelHTTPError(response.status)
            data = response.read(1024 * 1024 + 1)
    except HTTPError as error:
        status = error.code
        error.close()
        raise VercelHTTPError(status) from None
    except (URLError, OSError):
        raise VercelTransportError("Vercel API request failed before confirmation") from None
    if len(data) > 1024 * 1024:
        raise VercelError("Vercel API returned an oversized response")
    try:
        payload = json.loads(data)
    except (UnicodeError, json.JSONDecodeError):
        raise VercelError("Vercel API returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise VercelError("Vercel API returned an invalid response object")
    return payload


def wait_for_deployment(
    opener: OpenerDirector,
    settings: Mapping[str, str],
    hostname: str,
    timeout: float,
    interval: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    deadline = clock() + timeout
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise VercelError("Timed out waiting for Vercel deployment to become READY")
        try:
            payload = api_request(opener, settings, f"/v13/deployments/{hostname}", min(30, remaining))
        except VercelHTTPError as error:
            if error.status != 429 and not 500 <= error.status < 600:
                raise
            sleep(min(interval, max(0, deadline - clock())))
            continue
        except VercelTransportError:
            sleep(min(interval, max(0, deadline - clock())))
            continue
        if clock() >= deadline:
            raise VercelError("Timed out waiting for Vercel deployment to become READY")
        project_ids = [payload["projectId"]] if "projectId" in payload else []
        project = payload.get("project")
        if isinstance(project, dict) and "id" in project:
            project_ids.append(project["id"])
        if not project_ids or any(project_id != settings["VERCEL_PROJECT_ID"] for project_id in project_ids):
            raise VercelError("Vercel deployment project does not match VERCEL_PROJECT_ID")
        deployment_id = payload.get("id")
        if not isinstance(deployment_id, str) or not IDENTIFIER.fullmatch(deployment_id):
            raise VercelError("Vercel deployment has no valid deployment ID")
        if "url" in payload and payload["url"] != hostname:
            raise VercelError("Vercel deployment URL does not match requested deployment")
        state = payload.get("readyState")
        if not isinstance(state, str):
            raise VercelError("Vercel deployment has no valid readyState")
        if state in {"ERROR", "CANCELED", "BLOCKED"}:
            raise VercelError(f"Vercel deployment entered {state}")
        if state not in {"READY", "QUEUED", "BUILDING", "INITIALIZING"}:
            raise VercelError("Vercel deployment has no valid readyState")
        if state == "READY":
            return payload
        sleep(min(interval, max(0, deadline - clock())))


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    opener: OpenerDirector | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "wait", "alias"])
    parser.add_argument("deployment", nargs="?")
    parser.add_argument("domain", nargs="?")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--poll-interval", type=float, default=5)
    args = parser.parse_args(argv)
    settings = os.environ if environ is None else environ
    for name in ("VERCEL_TOKEN", "VERCEL_ORG_ID", "VERCEL_PROJECT_ID"):
        if not settings.get(name):
            print(f"Error: Missing {name}", file=sys.stderr)
            return 1
        value = settings[name]
        if (
            not value.isascii()
            or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)
            or (name != "VERCEL_TOKEN" and not IDENTIFIER.fullmatch(value))
        ):
            print(f"Error: Invalid {name}", file=sys.stderr)
            return 1
    link = Path(".vercel/project.json")
    if link.exists():
        try:
            project = json.loads(link.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError):
            print("Error: Cannot read valid .vercel/project.json", file=sys.stderr)
            return 1
        if (
            not isinstance(project, dict)
            or project.get("orgId") != settings["VERCEL_ORG_ID"]
            or project.get("projectId") != settings["VERCEL_PROJECT_ID"]
        ):
            print("Error: .vercel/project.json does not match configured owner/project", file=sys.stderr)
            return 1
    client = opener or build_opener(NoRedirect())
    try:
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise VercelError("Deployment timeout must be finite and positive")
        if not math.isfinite(args.poll_interval) or args.poll_interval <= 0:
            raise VercelError("Poll interval must be finite and positive")
        hostname = deployment_hostname(args.deployment) if args.action != "check" else ""
        domain = domain_name(args.domain) if args.action == "alias" else ""
        if args.action == "check":
            payload = api_request(client, settings, f"/v9/projects/{settings['VERCEL_PROJECT_ID']}", 30)
            if payload.get("id") != settings["VERCEL_PROJECT_ID"]:
                raise VercelError("Vercel project does not match VERCEL_PROJECT_ID")
            if "accountId" in payload and payload["accountId"] != settings["VERCEL_ORG_ID"]:
                raise VercelError("Vercel owner does not match VERCEL_ORG_ID")
        else:
            deployment = wait_for_deployment(client, settings, hostname, args.timeout, args.poll_interval, clock, sleep)
            if args.action == "alias":
                path = f"/v2/deployments/{deployment['id']}/aliases"
                try:
                    alias = api_request(client, settings, path, 30, {"alias": domain})
                except VercelHTTPError as error:
                    if error.status != 409:
                        raise
                    aliases = api_request(client, settings, path, 30).get("aliases")
                    if not isinstance(aliases, list) or not any(
                        isinstance(item, dict) and item.get("alias") == domain for item in aliases
                    ):
                        raise VercelError("Vercel alias conflict: requested deployment does not own alias") from None
                else:
                    if alias.get("alias") != domain:
                        raise VercelError("Vercel API did not confirm the requested alias")
    except VercelError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
