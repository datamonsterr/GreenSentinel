import os
import subprocess
import sys

import pytest

from scripts.auth_config import authorized_parties_for, validate_authorized_parties


def test_authorized_parties_are_explicit_per_environment():
    assert authorized_parties_for("production") == (
        "https://green-sentinel.vercel.app,https://greensentinel.vercel.app"
    )
    assert authorized_parties_for("dev") == (
        "https://green-sentinel-dev.vercel.app,https://dev.green-sentinel.vercel.app,https://dev-green-sentinel.vercel.app,http://localhost:3000,http://127.0.0.1:3000,http://localhost:3100,http://127.0.0.1:3100"
    )
    assert authorized_parties_for("staging") == (
        "https://green-sentinel-staging.vercel.app,https://staging.green-sentinel.vercel.app,https://staging-green-sentinel.vercel.app"
    )


def test_explicit_override_is_trimmed_and_validated():
    assert (
        authorized_parties_for(
            "production", " https://green-sentinel.vercel.app,https://greensentinel.vercel.app,https://custom.example "
        )
        == "https://green-sentinel.vercel.app,https://greensentinel.vercel.app,https://custom.example"
    )
    validate_authorized_parties("https://custom.example")


@pytest.mark.parametrize("value", ["", "https://*.vercel.app", "foo.example", "https://foo.example/path"])
def test_invalid_or_missing_origins_fail_closed(value):
    with pytest.raises(ValueError):
        validate_authorized_parties(value)


def test_preview_uses_known_dev_origins_and_never_dynamic_vercel_domain():
    assert authorized_parties_for("pr-105") == authorized_parties_for("dev")


def test_preview_can_add_one_exact_deployed_vercel_origin():
    value = authorized_parties_for("pr-105", extra_origins=("https://green-sentinel-git-fix-auth.vercel.app",))
    assert value.endswith("https://green-sentinel-git-fix-auth.vercel.app")


def test_direct_railway_pr_cli_has_no_package_path_requirement():
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "scripts/railway_pr.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0


def test_override_must_keep_both_production_aliases():
    with pytest.raises(ValueError):
        authorized_parties_for("production", "https://greensentinel.vercel.app")
