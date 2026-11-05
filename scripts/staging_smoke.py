#!/usr/bin/env python3
"""Read-only staging contracts; this does not exercise a synthetic trip lifecycle."""

import argparse
import json
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class StagingSmokeError(RuntimeError):
    """The deployed staging API did not satisfy its public contract."""


def _get_json(url: str) -> tuple[int, dict[str, object]]:
    try:
        try:
            response = urlopen(Request(url, headers={"Accept": "application/json"}), timeout=10)
        except HTTPError as error:
            # A 401 is the expected account-settings response, including its body.
            response = error
        with response:
            status = response.status
            payload = json.load(response)
    except (OSError, ValueError) as error:
        raise StagingSmokeError(f"{url}: request or JSON failed: {error}") from error
    if not isinstance(payload, dict):
        raise StagingSmokeError(f"{url}: expected a JSON object")
    return status, payload


def run_smoke(api_url: str) -> None:
    """Check readiness and session enforcement without credentials or mutations."""
    base = api_url.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise StagingSmokeError("Staging API URL must be an absolute HTTP(S) URL")

    for attempt in range(12):
        try:
            status, health = _get_json(f"{base}/health")
            if (
                status != 200
                or health.get("status") != "ok"
                or health.get("database") != "connected"
                or health.get("env") != "staging"
            ):
                raise StagingSmokeError("Health requires HTTP 200, status=ok, database=connected, env=staging")
            break
        except StagingSmokeError as error:
            if attempt == 11:
                raise StagingSmokeError(f"Staging health contract failed after 12 attempts: {error}") from error
            time.sleep(5)

    status, account = _get_json(f"{base}/api/v1/account/settings")
    if status != 401 or account.get("detail") != "Clerk session required":
        raise StagingSmokeError(
            "Account settings requires HTTP 401 with detail='Clerk session required' "
            f"without credentials; received HTTP {status}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True, help="Staging backend base URL")
    args = parser.parse_args()
    try:
        run_smoke(args.api_url)
    except StagingSmokeError as error:
        print(f"Staging smoke failed: {error}", file=sys.stderr)
        return 1
    print("Staging read-only contract smoke passed; synthetic trip lifecycle not exercised.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
