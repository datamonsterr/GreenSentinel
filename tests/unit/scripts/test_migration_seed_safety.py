from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.migrate_postgres as migrator

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent


def test_workflows_no_implicit_mock_seed():
    """Ensure no workflow has implicit mock seed executions or misleading labels."""
    workflows = sorted((ROOT_DIR / ".github" / "workflows").glob("*.yml"))
    assert workflows, "no workflows found"
    for workflow_path in workflows:
        content = workflow_path.read_text(encoding="utf-8")
        assert "seed_driver_mock_supabase.py" not in content, (
            f"seed_driver_mock_supabase.py found in {workflow_path.name}"
        )
        assert "Small Model & Mock Setup" not in content, (
            f"Misleading 'Small Model & Mock Setup' label found in {workflow_path.name}"
        )


def test_default_migration_never_invokes_seed_or_enrich():
    """Default migration invocation must be schema-only and never call seed or enrichment routines."""
    mock_conn = MagicMock()
    with (
        patch.object(migrator, "get_target_connection", return_value=mock_conn),
        patch.object(migrator, "apply_migrations") as mock_apply,
        patch.object(migrator, "seed_database_from_json") as mock_seed,
        patch.object(migrator, "run_enrichment_data") as mock_enrich,
        patch.object(migrator, "verify_database") as mock_verify,
        patch("sys.argv", ["migrate_postgres.py"]),
    ):
        migrator.main()

        mock_apply.assert_called_once()
        mock_seed.assert_not_called()
        mock_enrich.assert_not_called()
        mock_verify.assert_called_once()


def test_explicit_seed_flag_invokes_seed_and_enrich():
    """When explicitly opted in via --seed on local DB, seed and enrichment routines are executed."""
    mock_conn = MagicMock()
    with (
        patch.object(migrator, "get_target_connection", return_value=mock_conn),
        patch.object(migrator, "apply_migrations") as mock_apply,
        patch.object(migrator, "seed_database_from_json") as mock_seed,
        patch.object(migrator, "run_enrichment_data") as mock_enrich,
        patch.object(migrator, "run_preview_enrichment_data") as mock_preview_enrich,
        patch.object(migrator, "verify_database") as mock_verify,
        patch(
            "sys.argv",
            ["migrate_postgres.py", "--seed", "--database-url", "postgresql://postgres:pass@localhost:5432/postgres"],
        ),
    ):
        migrator.main()

        mock_apply.assert_called_once()
        mock_seed.assert_called_once()
        mock_enrich.assert_called_once()
        mock_preview_enrich.assert_called_once()
        mock_verify.assert_called_once()


def test_seed_refused_on_shared_or_prod_without_auth_config():
    """Seeding fixtures to shared, staging, or production database without scoped auth config must be refused."""
    remote_urls = [
        "postgresql://postgres:secret@railway.app:5432/railway",
        "postgresql://postgres:secret@monorail.proxy.rlwy.net:12345/railway",
        "postgresql://postgres:secret@greensentinel-prod-db:5432/postgres",
        "postgresql://postgres:secret@production-db.internal:5432/postgres",
    ]
    for url in remote_urls:
        mock_conn = MagicMock()
        with (
            patch.object(migrator, "get_target_connection", return_value=mock_conn),
            patch("sys.argv", ["migrate_postgres.py", "--seed", "--database-url", url]),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                migrator.main()
            assert "Refusing to seed fixtures" in str(exc_info.value)


def test_seed_allowed_on_remote_with_explicit_authorization():
    """Seeding fixtures to remote/shared DB is permitted when --allow-remote-seed is explicitly passed."""
    mock_conn = MagicMock()
    with (
        patch.object(migrator, "get_target_connection", return_value=mock_conn),
        patch.object(migrator, "apply_migrations") as mock_apply,
        patch.object(migrator, "seed_database_from_json") as mock_seed,
        patch.object(migrator, "run_enrichment_data") as mock_enrich,
        patch.object(migrator, "run_preview_enrichment_data") as mock_preview_enrich,
        patch.object(migrator, "verify_database") as mock_verify,
        patch(
            "sys.argv",
            [
                "migrate_postgres.py",
                "--seed",
                "--allow-remote-seed",
                "--database-url",
                "postgresql://postgres:secret@railway.app:5432/railway",
            ],
        ),
    ):
        migrator.main()

        mock_apply.assert_called_once()
        mock_seed.assert_called_once()
        mock_enrich.assert_called_once()
        mock_preview_enrich.assert_called_once()
        mock_verify.assert_called_once()


def test_postgis_public_schema_accepted_and_sets_search_path():
    """PostGIS in 'public' is accepted, sets session search_path without commit or catalog mutation."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mock_cursor.fetchone.return_value = ("public",)

    migrator.ensure_extensions_postgis(mock_conn)

    # Must never call commit inside helper
    mock_conn.commit.assert_not_called()

    queries = [str(call[0][0]) for call in mock_cursor.execute.call_args_list]
    assert any("SET search_path = app, public, extensions;" in q for q in queries)
    for q in queries:
        assert "DROP EXTENSION" not in q, f"Executed prohibited DROP EXTENSION query: {q}"
        assert "CASCADE" not in q, f"Executed prohibited CASCADE query: {q}"
        assert "UPDATE pg_extension" not in q, f"Executed prohibited catalog update query: {q}"
        assert "ALTER EXTENSION" not in q, f"Executed prohibited ALTER EXTENSION query: {q}"


def test_postgis_extensions_schema_accepted_and_sets_search_path():
    """PostGIS in 'extensions' is accepted, sets session search_path without commit or catalog mutation."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mock_cursor.fetchone.return_value = ("extensions",)

    migrator.ensure_extensions_postgis(mock_conn)

    mock_conn.commit.assert_not_called()

    queries = [str(call[0][0]) for call in mock_cursor.execute.call_args_list]
    assert any("SET search_path = app, extensions, public;" in q for q in queries)
    for q in queries:
        assert "DROP EXTENSION" not in q, f"Executed prohibited DROP EXTENSION query: {q}"
        assert "CASCADE" not in q, f"Executed prohibited CASCADE query: {q}"
        assert "UPDATE pg_extension" not in q, f"Executed prohibited catalog update query: {q}"
        assert "ALTER EXTENSION" not in q, f"Executed prohibited ALTER EXTENSION query: {q}"


def test_unexpected_postgis_schema_fails_closed():
    """Unexpected PostGIS geography schema must fail closed and never DROP/CASCADE or update pg_catalog."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mock_cursor.fetchone.return_value = ("unapproved_custom_schema",)

    with pytest.raises(RuntimeError) as exc_info:
        migrator.ensure_extensions_postgis(mock_conn)

    assert "mismatch" in str(exc_info.value).lower()
    assert "expected 'extensions' or 'public'" in str(exc_info.value).lower()
    mock_conn.commit.assert_not_called()

    for call in mock_cursor.execute.call_args_list:
        query = str(call[0][0])
        assert "DROP EXTENSION" not in query, f"Executed prohibited query: {query}"
        assert "CASCADE" not in query, f"Executed prohibited CASCADE query: {query}"
        assert "UPDATE pg_extension" not in query, f"Executed prohibited query: {query}"


def test_missing_postgis_on_remote_fails_closed():
    """Missing PostGIS on remote/production target must fail closed without creating/dropping extensions."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mock_cursor.fetchone.return_value = None

    with pytest.raises(RuntimeError) as exc_info:
        migrator.ensure_extensions_postgis(
            mock_conn, target_url="postgresql://postgres:secret@railway.app:5432/railway"
        )

    assert "automatic extension installation/dropping on live hosts is prohibited" in str(exc_info.value)
    mock_conn.commit.assert_not_called()


def test_missing_postgis_on_local_creates_in_extensions_without_commit():
    """Missing PostGIS on local isolated target creates extension in extensions schema without committing."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mock_cursor.fetchone.return_value = None

    migrator.ensure_extensions_postgis(mock_conn, target_url="postgresql://postgres:pass@127.0.0.1:5432/postgres")

    mock_conn.commit.assert_not_called()

    queries = [str(call[0][0]) for call in mock_cursor.execute.call_args_list]
    assert any("CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA extensions;" in q for q in queries)
    assert any("SET search_path = app, extensions, public;" in q for q in queries)
    for q in queries:
        assert "DROP EXTENSION" not in q, f"Executed prohibited query: {q}"
        assert "CASCADE" not in q, f"Executed prohibited CASCADE query: {q}"
        assert "UPDATE pg_extension" not in q, f"Executed prohibited query: {q}"


def test_no_migration_creates_reserved_keyword_columns():
    """Assert no migration on this branch creates a column named with a reserved SQL keyword."""
    import re

    reserved_keywords = {"order", "user", "group", "select", "from", "where", "limit", "offset"}
    migrations_dir = ROOT_DIR / "db" / "migrations"
    assert migrations_dir.exists(), "db/migrations must exist"

    violations: list[tuple[str, str, str]] = []
    create_table_re = re.compile(
        r"create\s+table(?:\s+if\s+not\s+exists)?\s+([^\(]+)\((.*?)\);",
        re.IGNORECASE | re.DOTALL,
    )
    add_col_re = re.compile(
        r"alter\s+table\s+[^\s]+\s+add\s+column(?:\s+if\s+not\s+exists)?\s+[\"'\s]*([a-zA-Z0-9_]+)[\"'\s]*",
        re.IGNORECASE,
    )

    for sql_file in sorted(migrations_dir.glob("*.sql")):
        content = sql_file.read_text(encoding="utf-8")
        clean_lines = [line.split("--")[0] for line in content.splitlines()]
        clean_sql = "\n".join(clean_lines)

        for match in create_table_re.finditer(clean_sql):
            tbl_name = match.group(1).strip()
            body = match.group(2)
            for col_def in body.split(","):
                tokens = col_def.strip().split()
                if not tokens:
                    continue
                first = tokens[0].strip("\"'`")
                if first.upper() in ("CONSTRAINT", "PRIMARY", "FOREIGN", "UNIQUE", "CHECK"):
                    continue
                if first.lower() in reserved_keywords:
                    violations.append((sql_file.name, tbl_name, first))

        for match in add_col_re.finditer(clean_sql):
            col_name = match.group(1).lower()
            if col_name in reserved_keywords:
                violations.append((sql_file.name, "ALTER TABLE", col_name))

    assert not violations, f"Migrations contain reserved keyword columns: {violations}"
