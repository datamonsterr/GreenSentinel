#!/usr/bin/env python3
"""Build and validate the explicit Clerk authorized-party allow-list.

This list is deployment configuration. It deliberately does not accept wildcard
or arbitrary Vercel domains because Clerk's ``azp`` claim is origin-sensitive.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from urllib.parse import urlsplit

FIRST_PARTY_ORIGINS = {
    "production": ("https://p-063.vercel.app", "https://p063.vercel.app"),
    "staging": (
        "https://p-063-staging.vercel.app",
        "https://staging.p-063.vercel.app",
        "https://staging-p-063.vercel.app",
    ),
    "dev": (
        "https://p-063-dev.vercel.app",
        "https://dev.p-063.vercel.app",
        "https://dev-p-063.vercel.app",
    ),
}
LOCAL_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
DEV_LOCAL_ORIGINS = (*LOCAL_ORIGINS, "http://localhost:3100", "http://127.0.0.1:3100")


def validate_authorized_parties(value: str) -> None:
    origins = tuple(part.strip() for part in value.split(",") if part.strip())
    if not origins:
        raise ValueError("at least one Clerk authorized party is required")
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError(f"invalid authorized party origin: {origin}")
        if parsed.path or parsed.query or parsed.fragment or "*" in origin:
            raise ValueError(f"authorized party must be an exact origin: {origin}")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError(f"HTTP authorized parties are limited to localhost: {origin}")


def authorized_parties_for(environment: str, override: str | None = None, extra_origins: tuple[str, ...] = ()) -> str:
    key = environment.lower().strip()
    if override is not None and override.strip():
        value = ",".join(part.strip() for part in override.split(",") if part.strip())
        if key in FIRST_PARTY_ORIGINS and not set(FIRST_PARTY_ORIGINS[key]).issubset(value.split(",")):
            raise ValueError(f"override for {key} must include all declared first-party frontend origins")
    else:
        base = FIRST_PARTY_ORIGINS.get(key, FIRST_PARTY_ORIGINS["dev"] if key.startswith("pr-") else ())
        local = DEV_LOCAL_ORIGINS if key == "dev" or key.startswith("pr-") else ()
        value = ",".join((*base, *local))
    if extra_origins:
        value = ",".join((*value.split(","), *(origin.strip() for origin in extra_origins)))
    validate_authorized_parties(value)
    return value


def merged_railway_origins(
    environment: str,
    project: str,
    service: str,
    target: str,
    override: str | None = None,
    extra_origins: tuple[str, ...] = (),
) -> str:
    """Read only in memory; never print unrelated Railway variables or secrets."""
    result = subprocess.run(
        ["railway", "variable", "list", "--project", project, "--service", service, "--environment", target, "--json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError("failed to read existing Railway authorized parties")
    existing = json.loads(result.stdout).get("CLERK_AUTHORIZED_PARTIES", "")
    base = authorized_parties_for(environment, override, extra_origins)
    merged = ",".join(dict.fromkeys(part.strip() for part in (base + "," + existing).split(",") if part.strip()))
    validate_authorized_parties(merged)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("environment")
    parser.add_argument("--override", default=None)
    parser.add_argument("--extra-origin", action="append", default=[])
    parser.add_argument("--merge-railway", action="store_true")
    parser.add_argument("--project")
    parser.add_argument("--service")
    parser.add_argument("--target")
    args = parser.parse_args()
    if args.merge_railway:
        if not all((args.project, args.service, args.target)):
            parser.error("--merge-railway requires --project, --service and --target")
        print(
            merged_railway_origins(
                args.environment, args.project, args.service, args.target, args.override, tuple(args.extra_origin)
            )
        )
    else:
        print(authorized_parties_for(args.environment, args.override, tuple(args.extra_origin)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
