"""Railway IaC contract: single authoring file owns project resources."""

import pathlib
import re


def test_iac_file_exists_and_is_typescript():
    p = pathlib.Path(".railway/railway.ts")
    assert p.exists(), "missing .railway/railway.ts (TS is GA; py/go are beta)"


def test_iac_defines_managed_resources():
    src = pathlib.Path(".railway/railway.ts").read_text()
    assert "defineRailway" in src
    assert "service(" in src  # greensentinel-backend
    assert "postgis/postgis" in src
    assert "redis(" in src
    assert "DATABASE_URL" in src
    assert "REDIS_URL" in src


def test_iac_has_no_uuids_no_generated_domains_no_secrets():
    src = pathlib.Path(".railway/railway.ts").read_text()
    assert not re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        src,
        re.I,
    ), "no Railway UUIDs in source"
    assert "up.railway.app" not in src, "no generated domains in source"
    assert "RAILWAY_API_TOKEN" not in src, "no API tokens in source"


def test_iac_preserves_backend_model_env():
    src = pathlib.Path(".railway/railway.ts").read_text()
    assert "LLM_MODEL: preserve()" in src, "IaC must preserve backend LLM_MODEL runtime variable"
    assert "OPENROUTER_MODEL: preserve()" in src
