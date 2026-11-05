import sys
from pathlib import Path

import pytest

from tests.support.repo import REPO_ROOT

# Ensure skills scripts are importable
DESIGN_SYSTEM_DIR = REPO_ROOT / ".agents" / "jev_skills" / "ui-ux-pro-max" / "scripts"
sys.path.insert(0, str(DESIGN_SYSTEM_DIR))


def test_design_system_validate_output_dir_safe(tmp_path: Path):
    from design_system import validate_output_dir

    # Resolves within base directory
    safe_subdir = "my_custom_design_dir"
    resolved = validate_output_dir(safe_subdir, allowed_base=tmp_path)
    assert resolved == (tmp_path / safe_subdir).resolve()


def test_design_system_validate_output_dir_traversal_blocked(tmp_path: Path):
    from design_system import validate_output_dir

    # Directory traversal out of allowed base
    with pytest.raises(ValueError, match="Security: output_dir .* attempts path traversal"):
        validate_output_dir("../../../etc", allowed_base=tmp_path)


def test_design_system_validate_output_dir_sensitive_system_dir():
    from design_system import validate_output_dir

    # Absolute system directory blocked
    with pytest.raises(ValueError, match="Security:.*"):
        validate_output_dir("/etc/secrets")


def test_design_system_validate_output_dir_unc_and_root_blocked():
    from design_system import validate_output_dir

    # UNC paths blocked
    with pytest.raises(ValueError, match="Security: UNC network paths are prohibited"):
        validate_output_dir(r"\\192.168.1.1\share\evil")

    # Root filesystem anchor blocked
    with pytest.raises(ValueError, match="Security:.*"):
        validate_output_dir("/")


def test_design_system_validate_output_dir_symlink_escape_blocked(tmp_path: Path):
    from design_system import validate_output_dir

    # Create a directory inside tmp_path, and a symlink inside it pointing outside
    base_dir = tmp_path / "sandbox"
    base_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    symlink_path = base_dir / "symlink_to_outside"
    symlink_path.symlink_to(outside_dir)

    # validate_output_dir must detect that symlink resolves outside base_dir
    with pytest.raises(ValueError, match="Security: output_dir .* attempts path traversal"):
        validate_output_dir(symlink_path, allowed_base=base_dir)


def test_design_system_write_persisted_file_atomic(tmp_path: Path):
    from design_system import _write_persisted_file

    target_file = tmp_path / "TEST_MASTER.md"
    content_initial = "# Initial Content"
    content_updated = "# Updated Content"

    # Initial write with force=False succeeds
    _write_persisted_file(target_file, content_initial, force=False)
    assert target_file.read_text(encoding="utf-8") == content_initial

    # Second write with force=False raises FileExistsError atomically
    with pytest.raises(FileExistsError):
        _write_persisted_file(target_file, content_updated, force=False)

    # Overwrite with force=True succeeds atomically
    _write_persisted_file(target_file, content_updated, force=True)
    assert target_file.read_text(encoding="utf-8") == content_updated


def test_design_system_persist_concurrency_no_partial_pages_dir(tmp_path: Path):
    from design_system import persist_design_system

    # Create existing MASTER.md to simulate prior persistence
    project_dir = tmp_path / "design-system" / "test-project"
    project_dir.mkdir(parents=True)
    master_file = project_dir / "MASTER.md"
    master_file.write_text("# Existing Master", encoding="utf-8")

    pages_dir = project_dir / "pages"
    assert not pages_dir.exists()

    # Call persist_design_system with force=False and page="dashboard"
    result = persist_design_system(
        {"project_name": "test-project"},
        page="dashboard",
        output_dir=tmp_path,
        allowed_base=tmp_path,
        force=False,
    )

    # Must abort cleanly without creating pages directory
    assert result["status"] == "skipped_exists"
    assert not pages_dir.exists()


def test_design_system_safe_slug_reserved_names():
    from design_system import safe_slug

    assert safe_slug("con") == "safe-con"
    assert safe_slug("PRN") == "safe-prn"
    assert safe_slug("NUL") == "safe-nul"
    assert safe_slug("..") == "default"
    assert safe_slug(".") == "default"
    assert safe_slug("pages") == "safe-pages"
    assert safe_slug("master") == "safe-master"
    assert safe_slug("../../../etc") == "etc"
    assert safe_slug("___") == "default"


def test_design_system_write_persisted_file_refuses_symlink_and_dir(tmp_path: Path):
    from design_system import _write_persisted_file

    # Refuse writing to directory
    target_dir = tmp_path / "sub_directory"
    target_dir.mkdir()
    with pytest.raises(IsADirectoryError, match="Security: target path is a directory"):
        _write_persisted_file(target_dir, "content", force=False)
    with pytest.raises(IsADirectoryError, match="Security: target path is a directory"):
        _write_persisted_file(target_dir, "content", force=True)

    # Refuse writing to symlink
    target_file = tmp_path / "target_real.txt"
    target_file.write_text("real content", encoding="utf-8")
    symlink_file = tmp_path / "symlink_alias.txt"
    symlink_file.symlink_to(target_file)

    with pytest.raises(ValueError, match="Security: refusing to write to symlink"):
        _write_persisted_file(symlink_file, "exploit", force=False)
    with pytest.raises(ValueError, match="Security: refusing to write to symlink"):
        _write_persisted_file(symlink_file, "exploit", force=True)
