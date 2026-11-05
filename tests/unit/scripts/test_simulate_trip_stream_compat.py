"""The staging smoke test runs this script with the self-hosted runner's Python.

`deploy-staging` executes `python3 scripts/simulate_trip_stream.py` outside the
uv-pinned interpreter, and those runners are still on Python 3.10, so the script
must stay importable there. On 2026-10-15 a `from datetime import UTC` crash was
hidden behind `|| true` while staging was reported healthy.
"""

import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path("scripts/simulate_trip_stream.py")


def test_source_avoids_python311_only_datetime_utc_import():
    assert "from datetime import UTC" not in SCRIPT.read_text(), (
        "datetime.UTC needs Python 3.11; the deployment runners ship 3.10"
    )


def test_module_imports_without_datetime_utc():
    subprocess.run(
        [sys.executable, "-c", "import scripts.simulate_trip_stream"],
        check=True,
        cwd=pathlib.Path.cwd(),
    )
