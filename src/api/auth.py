"""Clerk session verification with PostgreSQL-owned roles."""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient

try:
    from clerk_backend_api import AuthenticateRequestOptions, authenticate_request
except ImportError:  # pragma: no cover
    AuthenticateRequestOptions = None  # type: ignore[assignment,misc]
    authenticate_request = None  # type: ignore[assignment]

from fastapi import Depends, HTTPException, Request

from src.config import Settings, get_settings
from src.services.access_control import (
    bootstrap_clerk_organization,
    ensure_driver_profile,
    load_principal,
    resolve_clerk_organization_id,
    sync_clerk_principal,
)
from src.services.case_service import CaseService, get_case_service

logger = logging.getLogger(__name__)

_jwk_clients: dict[str, PyJWKClient] = {}


def _get_jwk_client(jwks_url: str) -> PyJWKClient:
    if jwks_url not in _jwk_clients:
        _jwk_clients[jwks_url] = PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)
    return _jwk_clients[jwks_url]


def _jwks_url_from_publishable_key(key: str) -> str | None:
    try:
        raw = key.strip("'\"").split("_", 2)[-1].rstrip("$")
        padded = raw + "=" * (-len(raw) % 4)
        domain = base64.b64decode(padded).decode("utf-8").rstrip("$")
        return f"https://{domain}/.well-known/jwks.json"
    except Exception:
        return None


def _verify_jwt_with_jwks(token: str, jwks_url: str, settings: Settings) -> dict[str, Any]:
    client = _get_jwk_client(jwks_url)
    signing_key = client.get_signing_key_from_jwt(token)

    from jwt.types import Options

    decode_options: Options = {
        "verify_signature": True,
        "verify_exp": True,
        "verify_aud": bool(settings.clerk_audience),
        "require": ["exp", "iat", "sub"],
    }

    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.clerk_audience or None,
        issuer=settings.clerk_issuer or None,
        options=decode_options,
        leeway=30,
    )

    if settings.clerk_authorized_parties:
        allowed = {p.strip() for p in settings.clerk_authorized_parties.split(",") if p.strip()}
        azp = payload.get("azp")
        if allowed and "*" not in allowed and azp:
            if azp not in allowed:
                raise HTTPException(status_code=401, detail="Unauthorized browser origin")

    return payload


@dataclass(frozen=True)
class Principal:
    id: str
    organization_id: str
    roles: frozenset[str]
    driver_id: str | None = None


# GSM workflow roles (ADR-031): Clerk org keys org:reviewer / org:ops_director / org:marketplace_director.
WORKFLOW_ORG_ROLES = frozenset({"reviewer", "ops_director", "marketplace_director"})


def test_auth_enabled(settings: Settings | None = None) -> bool:
    """Local fixture compatibility is an explicit opt-in, never a hosted fallback."""
    settings = settings or get_settings()
    return settings.app_env == "test" and settings.test_auth_enabled


async def require_principal(
    request: Request,
    settings: Settings = Depends(get_settings),
    service: CaseService = Depends(get_case_service),
) -> Principal | None:
    if test_auth_enabled(settings):
        is_driver_route = "/driver" in request.url.path or request.url.path.startswith("/api/v1/driver")
        x_driver_id = request.headers.get("x-driver-id")
        x_role = request.headers.get("x-role")
        x_principal_id = request.headers.get("x-principal-id")
        x_org_id = request.headers.get("x-organization-id")

        if is_driver_route or x_driver_id or x_role or x_principal_id:
            roles = set()
            if x_role:
                for r in x_role.split(","):
                    if r.strip():
                        roles.add(r.strip().lower())
            elif is_driver_route or x_driver_id:
                roles.add("driver")
            else:
                roles.add("fraud_analyst")

            if "admin" in roles:
                roles.update({"admin", "analyst", "fraud_analyst", "driver"})
            if "fraud_analyst" in roles:
                roles.add("analyst")
            if "analyst" in roles:
                roles.add("fraud_analyst")

            actor_id = x_principal_id or x_driver_id or ("driver-guest" if "driver" in roles else "analyst-dev")

            resolved_driver_id = None
            if "driver" in roles:
                resolved_driver_id = x_driver_id
                if not resolved_driver_id and x_principal_id:
                    try:
                        conn = service._get_db_connection()
                        if conn is not None:
                            try:
                                with conn.cursor() as cur:
                                    cur.execute("SET search_path = app, extensions, public;")
                                    if x_org_id:
                                        cur.execute(
                                            "SELECT id FROM app.drivers WHERE principal_id::text = %s AND organization_id = %s LIMIT 1;",
                                            (x_principal_id, x_org_id),
                                        )
                                    else:
                                        cur.execute(
                                            "SELECT id FROM app.drivers WHERE principal_id::text = %s LIMIT 1;",
                                            (x_principal_id,),
                                        )
                                    d_row = cur.fetchone()
                                    if d_row:
                                        resolved_driver_id = str(d_row["id"] if isinstance(d_row, dict) else d_row[0])
                            finally:
                                conn.close()
                    except Exception:
                        pass

                if not resolved_driver_id:
                    resolved_driver_id = actor_id

            return Principal(
                id=actor_id,
                organization_id=x_org_id or "018f2f4e-0000-7000-8000-000000000001",
                roles=frozenset(roles),
                driver_id=resolved_driver_id,
            )

    authorization = request.headers.get("authorization", "")
    has_bearer = authorization.startswith("Bearer ") and bool(authorization[7:].strip())

    if not has_bearer:
        if test_auth_enabled(settings):
            return None
        raise HTTPException(status_code=401, detail="Clerk session required")

    token = authorization[7:].strip()

    # Determine JWKS URL
    jwks_url: str | None = settings.clerk_jwks_url
    if not jwks_url and settings.clerk_publishable_key:
        jwks_url = _jwks_url_from_publishable_key(settings.clerk_publishable_key)
    if not jwks_url and settings.clerk_issuer:
        jwks_url = f"{settings.clerk_issuer.rstrip('/')}/.well-known/jwks.json"

    # If neither secret key, jwt key, nor jwks_url is available:
    if not (settings.clerk_secret_key or settings.clerk_jwt_key or jwks_url):
        if test_auth_enabled(settings):
            return None
        raise HTTPException(status_code=503, detail="Clerk verification is not configured")

    payload: dict[str, Any] | None = None

    # Priority 1: clerk-backend-api when secret_key or jwt_key configured
    if (
        (settings.clerk_secret_key or settings.clerk_jwt_key)
        and authenticate_request is not None
        and AuthenticateRequestOptions is not None
    ):
        options = AuthenticateRequestOptions(
            secret_key=settings.clerk_secret_key or None,
            jwt_key=settings.clerk_jwt_key or None,
            audience=settings.clerk_audience or None,
            authorized_parties=None,
            accepts_token=["session_token"],
        )
        try:
            state = await asyncio.to_thread(authenticate_request, request, options)
            if state.is_signed_in and state.payload and state.payload.get("sub"):
                payload = state.payload
                if settings.clerk_authorized_parties:
                    allowed = {p.strip() for p in settings.clerk_authorized_parties.split(",") if p.strip()}
                    azp = payload.get("azp")
                    if allowed and "*" not in allowed and azp:
                        if azp not in allowed:
                            raise HTTPException(status_code=401, detail="Unauthorized browser origin")
            else:
                raise HTTPException(status_code=401, detail="Invalid Clerk session")
        except HTTPException:
            raise
        except (ValueError, jwt.InvalidTokenError) as exc:
            raise HTTPException(status_code=401, detail="Invalid Clerk session") from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Clerk verification unavailable") from exc

    # Priority 2: Public JWKS verification via PyJWKClient
    if payload is None and jwks_url:
        try:
            payload = await asyncio.to_thread(_verify_jwt_with_jwks, token, jwks_url, settings)
        except HTTPException:
            if settings.app_env != "test":
                raise
        except Exception as exc:
            logger.debug("JWKS verification error: %s", exc)

    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid Clerk session")

    user_id = str(payload["sub"])
    org_dict = o if isinstance(o := payload.get("o"), dict) else {}
    clerk_org_id = payload.get("org_id") or org_dict.get("id")
    org_role = payload.get("org_role") or org_dict.get("rol")

    # S4-CONTRACT / #409: New JIT grants must come solely from the verified
    # ACTIVE organization role (org_role or compact o.rol), normalized to
    # admin/member/driver aliases.
    # Global payload/public_metadata roleadmin from anotherorg must NOT override org:member or unknown orgrole.
    mapped_role: str | None = None
    if org_role:
        norm_org_role = str(org_role).strip().lower()
        if norm_org_role.startswith("org:"):
            canonical_org_role = norm_org_role[4:].strip()
        else:
            canonical_org_role = norm_org_role

        if canonical_org_role == "admin":
            mapped_role = "admin"
        elif canonical_org_role in ("member", "fraud_analyst", "analyst"):
            mapped_role = "fraud_analyst"
        elif canonical_org_role == "driver":
            mapped_role = "driver"
        elif canonical_org_role in WORKFLOW_ORG_ROLES:
            mapped_role = canonical_org_role
        else:
            mapped_role = None

    display_name = payload.get("name") or payload.get("email") or payload.get("preferred_username") or user_id

    claimed_uuid_org: str | None = None
    if clerk_org_id:
        raw_org_id = str(clerk_org_id)
        if raw_org_id.startswith("org_"):
            # Native Clerk org ids resolve only through an explicit admin link
            # (app.organizations.clerk_organization_id). Unlinked orgs stay denied,
            # except org creators (org:admin), who bootstrap a fresh empty tenant
            # they own — self-serve onboarding without touching other tenants.
            linked_org_id = await asyncio.to_thread(
                resolve_clerk_organization_id, service._get_db_connection, raw_org_id
            )
            if not linked_org_id:
                if (org_role or "") != "org:admin":
                    raise HTTPException(status_code=403, detail="Clerk organization is not provisioned")
                org_name = org_dict.get("nam") or org_dict.get("slg")
                bootstrapped = await asyncio.to_thread(
                    bootstrap_clerk_organization,
                    service._get_db_connection,
                    raw_org_id,
                    org_name,
                    user_id,
                    display_name,
                )
                linked_org_id = bootstrapped["organization_id"]
            claimed_uuid_org = linked_org_id
            try:
                from uuid import UUID as _UUID

                _UUID(str(claimed_uuid_org))
            except (ValueError, AttributeError, TypeError) as exc:
                raise HTTPException(status_code=403, detail="Clerk organization is not provisioned") from exc
        else:
            try:
                from uuid import UUID as _UUID

                claimed_uuid_org = str(_UUID(raw_org_id))
            except (ValueError, AttributeError, TypeError) as exc:
                raise HTTPException(status_code=403, detail="Clerk organization membership required") from exc
    row = await asyncio.to_thread(load_principal, service._get_db_connection, user_id, claimed_uuid_org)
    known_roles = {
        "analyst", "fraud_analyst", "driver", "admin", "demo_operator", "senior_analyst", "member",
        *WORKFLOW_ORG_ROLES,
    }

    # Inactive rows are terminal until an administrator reactivates them.
    if row and row.get("status") not in (None, "active"):
        raise HTTPException(status_code=403, detail="Clerk user has no active assigned role")

    # Defense against privilege escalation:
    # An unknown Clerk subject cannot self-provision privileged roles ('admin') via public_metadata.
    # Privileged roles require a verified Clerk Organization role (org_role) or existing database role.
    if not row and not org_role:
        raw_pm = (
            (payload.get("public_metadata") or {}).get("roles")
            or (payload.get("public_metadata") or {}).get("role")
            or []
        )
        if isinstance(raw_pm, str):
            pm_roles = {raw_pm.strip().lower()}
        elif isinstance(raw_pm, (list, tuple, set)):
            pm_roles = {str(r).strip().lower() for r in raw_pm if r}
        else:
            pm_roles = set()
        if pm_roles.intersection({"admin"}):
            raise HTTPException(status_code=403, detail="Privileged roles cannot be provisioned via metadata")

    # Check a verified UUID organization claim before any JIT write. Existing
    # database grants win over stale Clerk roles; never repair them from JWT.
    if claimed_uuid_org and row and str(row.get("organization_id")) != claimed_uuid_org:
        raise HTTPException(status_code=403, detail="Clerk organization mismatch")

    if not row:
        # S4-CONTRACT #291: unknown identity with no Clerk org_role is denied.
        # No fraud_analyst fallback for new users; JIT sync requires org_role.
        if not org_role or mapped_role is None:
            raise HTTPException(status_code=403, detail="Clerk user has no active assigned role")

        if not claimed_uuid_org:
            raise HTTPException(status_code=403, detail="Clerk organization membership required")

        row = await asyncio.to_thread(
            sync_clerk_principal,
            service._get_db_connection,
            user_id,
            claimed_uuid_org,
            mapped_role,
            display_name,
        )
    else:
        # Existing database principal. Authoritative existing DB grants MUST be preserved.
        # NEVER pass mapped JWT admin/member role into principal/role upsert for an existing driver.
        # An existing driver missing driver_id repairs ONLY its driver profile, preserving
        # existing DB organization, status, and full role set.
        if "driver" in (row.get("roles") or []) and not row.get("driver_id"):
            driver_org_id = str(row["organization_id"])
            await asyncio.to_thread(
                ensure_driver_profile,
                service._get_db_connection,
                str(row["id"]),
                driver_org_id,
                user_id,
                display_name,
            )
            # Reload full trusted principal state from database
            row = await asyncio.to_thread(
                load_principal,
                service._get_db_connection,
                user_id,
                driver_org_id,
            )

    if not row or not row.get("organization_id") or not (set(row.get("roles") or []) & known_roles):
        raise HTTPException(status_code=403, detail="Clerk user has no active assigned role")

    if row.get("status") not in (None, "active"):
        raise HTTPException(status_code=403, detail="Clerk user has no active assigned role")

    # Active org source of truth = Clerk active organization, server-verified
    # per request. A UUID org claim that mismatches the DB principal is a 403.
    # (Clerk-native org_ ids cannot map to a provisioned org; provisioning
    # happens out-of-band via Admin, never via silent default-org collapse.)
    if clerk_org_id and not str(clerk_org_id).startswith("org_"):
        try:
            from uuid import UUID as _UUID

            _UUID(str(clerk_org_id))
            _is_uuid_claim = True
        except (ValueError, AttributeError, TypeError):
            _is_uuid_claim = False
        if _is_uuid_claim and str(row.get("organization_id")) != str(clerk_org_id):
            raise HTTPException(status_code=403, detail="Clerk organization mismatch")

    roles = set(row["roles"]) & known_roles
    if "admin" in roles:
        roles.update({"admin", "analyst", "fraud_analyst", "driver"})
    if "fraud_analyst" in roles:
        roles.add("analyst")
    if "analyst" in roles:
        roles.add("fraud_analyst")
    if "member" in roles:
        roles.update({"fraud_analyst", "analyst"})

    return Principal(
        str(row["id"]),
        str(row["organization_id"]),
        frozenset(roles),
        str(row["driver_id"]) if ("driver" in roles and row.get("driver_id")) else None,
    )


def require_role(principal: Principal | None, *roles: str) -> None:
    if principal is None:
        settings = get_settings()
        if test_auth_enabled(settings):
            return
        raise HTTPException(status_code=401, detail="Authentication required")
    effective_roles = set(principal.roles)
    if "admin" in effective_roles:
        effective_roles.update({"admin", "analyst", "fraud_analyst", "driver"})
    if "senior_analyst" in effective_roles:
        effective_roles.add("analyst")
    if "fraud_analyst" in effective_roles:
        effective_roles.add("analyst")
    if "analyst" in effective_roles:
        effective_roles.add("fraud_analyst")
    if "member" in effective_roles:
        effective_roles.update({"fraud_analyst", "analyst"})

    if not effective_roles.intersection(roles):
        raise HTTPException(status_code=403, detail="Insufficient role permissions")


def require_analyst_identity(principal: Principal | None, analyst_id: str) -> None:
    if principal is None:
        settings = get_settings()
        if test_auth_enabled(settings):
            return
        raise HTTPException(status_code=401, detail="Authentication required")
    if principal.id == analyst_id:
        return
    raise HTTPException(status_code=403, detail="Analyst identity does not match Clerk session")


def require_driver_identity(principal: Principal | None, driver_id: str) -> None:
    """Only the explicitly linked Driver may act as that Driver."""
    if principal is None:
        settings = get_settings()
        if test_auth_enabled(settings):
            return
        raise HTTPException(status_code=401, detail="Authentication required")
    if "driver" in principal.roles and principal.driver_id == driver_id:
        return
    raise HTTPException(status_code=403, detail="Driver identity does not match current session")


get_current_principal = require_principal
