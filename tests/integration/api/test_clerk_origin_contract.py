"""Production Clerk JWT contract tests.

These tests deliberately use a real RS256 token and the real JWT verifier.  The
JWKS network boundary is the only stub, so an origin allowlist regression cannot
be hidden by mocking authentication.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from scripts.auth_config import authorized_parties_for
from src.api.auth import _verify_jwt_with_jwks
from src.api.routes import router
from src.config import Settings, get_settings
from src.services.case_service import get_case_service


class _SigningKey:
    def __init__(self, key):
        self.key = key


class _JwkClient:
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, _token):
        return _SigningKey(self.key)


@pytest.fixture
def rsa_keys():
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _token(private_key, **claims):
    now = datetime.now(UTC)
    payload = {
        "sub": "user_clerk_contract",
        "azp": "https://p-063.vercel.app",
        "iss": "https://clerk.example.test",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        **claims,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "contract-key"})


def test_default_verification_accepts_current_dev_frontend(rsa_keys, monkeypatch):
    """The deployed dev hostname must survive exact azp validation without overrides."""
    private_key, public_key = rsa_keys
    monkeypatch.delenv("CLERK_AUTHORIZED_PARTIES", raising=False)
    monkeypatch.delenv("clerk_authorized_parties", raising=False)
    token = _token(private_key, azp="https://p-063-dev.vercel.app")
    settings = Settings(_env_file=None, clerk_issuer="https://clerk.example.test")
    with patch("src.api.auth._get_jwk_client", return_value=_JwkClient(public_key)):
        payload = _verify_jwt_with_jwks(token, settings.clerk_jwks_url, settings)
    assert payload["azp"] == "https://p-063-dev.vercel.app"


@pytest.mark.parametrize(
    ("environment", "browser_origin"),
    [
        ("production", "https://p-063.vercel.app"),
        ("dev", "https://p-063-dev.vercel.app"),
        ("dev", "https://dev.p-063.vercel.app"),
        ("staging", "https://p-063-staging.vercel.app"),
        ("staging", "https://staging.p-063.vercel.app"),
    ],
)
def test_real_rs256_clerk_token_accepts_each_deployed_browser_origin(rsa_keys, environment, browser_origin):
    private_key, public_key = rsa_keys
    token = _token(private_key, azp=browser_origin)
    settings = Settings(
        app_env="production",
        clerk_issuer="https://clerk.example.test",
        clerk_authorized_parties=authorized_parties_for(environment),
        _env_file=None,
        clerk_secret_key="",
        clerk_jwt_key="",
        clerk_jwks_url="https://clerk.example.test/.well-known/jwks.json",
    )

    with patch("src.api.auth._get_jwk_client", return_value=_JwkClient(public_key)):
        payload = _verify_jwt_with_jwks(token, "https://clerk.example.test/.well-known/jwks.json", settings)

    assert payload["sub"] == "user_clerk_contract"
    assert payload["azp"] == browser_origin


@pytest.mark.parametrize(
    "untrusted_origin",
    [
        "https://p-063.vercel.app.attacker.example",
        "https://attacker.vercel.app",
    ],
)
def test_real_rs256_clerk_token_rejects_untrusted_origin(rsa_keys, untrusted_origin):
    private_key, public_key = rsa_keys
    token = _token(private_key, azp=untrusted_origin)
    settings = Settings(
        app_env="production",
        clerk_issuer="https://clerk.example.test",
        clerk_authorized_parties=authorized_parties_for("production"),
        _env_file=None,
        clerk_secret_key="",
        clerk_jwt_key="",
        clerk_jwks_url="https://clerk.example.test/.well-known/jwks.json",
    )

    with patch("src.api.auth._get_jwk_client", return_value=_JwkClient(public_key)):
        with pytest.raises(HTTPException, match="Unauthorized browser origin"):
            _verify_jwt_with_jwks(token, "https://clerk.example.test/.well-known/jwks.json", settings)


def test_real_rs256_clerk_token_rejects_forged_signature(rsa_keys):
    private_key, public_key = rsa_keys
    from cryptography.hazmat.primitives.asymmetric import rsa

    forged_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _token(forged_key)
    settings = Settings(
        app_env="production",
        clerk_issuer="https://clerk.example.test",
        clerk_authorized_parties=authorized_parties_for("production"),
        _env_file=None,
        clerk_secret_key="",
        clerk_jwt_key="",
        clerk_jwks_url="https://clerk.example.test/.well-known/jwks.json",
    )
    with patch("src.api.auth._get_jwk_client", return_value=_JwkClient(public_key)):
        with pytest.raises(jwt.InvalidSignatureError):
            _verify_jwt_with_jwks(token, "https://clerk.example.test/.well-known/jwks.json", settings)


@pytest.mark.parametrize(
    "claims",
    [
        {"exp": int((datetime.now(UTC) - timedelta(minutes=5)).timestamp())},
        {"iss": "https://another-clerk.example.test"},
    ],
)
def test_real_rs256_clerk_token_rejects_expired_or_wrong_issuer(rsa_keys, claims):
    private_key, public_key = rsa_keys
    token = _token(private_key, **claims)
    settings = Settings(
        app_env="production",
        clerk_issuer="https://clerk.example.test",
        clerk_authorized_parties=authorized_parties_for("production"),
        _env_file=None,
        clerk_secret_key="",
        clerk_jwt_key="",
        clerk_jwks_url="https://clerk.example.test/.well-known/jwks.json",
    )

    with patch("src.api.auth._get_jwk_client", return_value=_JwkClient(public_key)):
        with pytest.raises((jwt.InvalidTokenError, HTTPException)):
            _verify_jwt_with_jwks(token, "https://clerk.example.test/.well-known/jwks.json", settings)


async def test_authenticated_me_and_cases_use_real_verified_token(rsa_keys):
    private_key, public_key = rsa_keys
    token = _token(private_key)

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _query, params):
            assert params == ("user_clerk_contract",)

        def fetchone(self):
            return {"id": "principal-contract", "organization_id": "org-contract", "roles": ["analyst"]}

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    class FakeService:
        def _get_db_connection(self):
            return FakeConnection()

        async def list_cases(self, **_kwargs):
            return {"items": [], "total": 0, "limit": 50, "offset": 0}

        def get_principal_display_name(self, identifier):
            return "Contract User" if identifier == "principal-contract" else None

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="production",
        clerk_issuer="https://clerk.example.test",
        clerk_authorized_parties=authorized_parties_for("production"),
        _env_file=None,
        clerk_secret_key="",
        clerk_jwt_key="",
        clerk_jwks_url="https://clerk.example.test/.well-known/jwks.json",
    )
    app.dependency_overrides[get_case_service] = FakeService
    with patch("src.api.auth._get_jwk_client", return_value=_JwkClient(public_key)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {token}"}
            me = await client.get("/api/v1/me", headers=headers)
            cases = await client.get("/api/v1/cases", headers=headers)

    assert me.status_code == 200
    assert me.json()["id"] == "principal-contract"
    assert cases.status_code == 200
