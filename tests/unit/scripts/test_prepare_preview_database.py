import pytest


def _env(monkeypatch, **values):
    monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_rejects_wrong_preview_environment_before_connecting(monkeypatch):
    from scripts import prepare_preview_database as module

    _env(monkeypatch, RAILWAY_ENVIRONMENT_NAME="dev", P063_PREVIEW_HEAD_SHA="sha")
    monkeypatch.setenv("DATABASE_URL", "postgresql://preview")
    monkeypatch.setattr(module, "get_target_connection", pytest.fail)
    with pytest.raises(RuntimeError, match=r"matching pr-\* environment"):
        module.prepare_preview_database(340, "sha")


def test_rejects_wrong_head_before_connecting(monkeypatch):
    from scripts import prepare_preview_database as module

    _env(monkeypatch, RAILWAY_ENVIRONMENT_NAME="pr-340", P063_PREVIEW_HEAD_SHA="other")
    monkeypatch.setenv("DATABASE_URL", "postgresql://preview")
    monkeypatch.setattr(module, "get_target_connection", pytest.fail)
    with pytest.raises(RuntimeError, match="matching preview head SHA"):
        module.prepare_preview_database(340, "sha")


def test_rejects_missing_database_url_before_connecting(monkeypatch):
    from scripts import prepare_preview_database as module

    _env(monkeypatch, RAILWAY_ENVIRONMENT_NAME="pr-340", P063_PREVIEW_HEAD_SHA="sha")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(module, "get_target_connection", pytest.fail)
    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        module.prepare_preview_database(340, "sha")


def test_rejects_conflicting_migration_override_before_connecting(monkeypatch):
    from scripts import prepare_preview_database as module

    _env(
        monkeypatch,
        RAILWAY_ENVIRONMENT_NAME="pr-340",
        P063_PREVIEW_HEAD_SHA="sha",
        DATABASE_URL="postgresql://preview",
        TARGET_DATABASE_URL="postgresql://other",
    )
    monkeypatch.setattr(module, "get_target_connection", pytest.fail)
    with pytest.raises(RuntimeError, match="TARGET_DATABASE_URL conflicts"):
        module.prepare_preview_database(340, "sha")


def test_allowed_path_migrates_verifies_and_closes(monkeypatch):
    from scripts import prepare_preview_database as module

    _env(
        monkeypatch,
        RAILWAY_ENVIRONMENT_NAME="pr-340",
        P063_PREVIEW_HEAD_SHA="sha",
        DATABASE_URL="postgresql://preview",
    )

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, query):
            assert query == "SELECT to_regclass('app.trips');"

        def fetchone(self):
            return ("app.trips",)

    class Connection:
        closed = False

        def cursor(self):
            return Cursor()

        def close(self):
            self.closed = True

    connection = Connection()
    calls = []
    monkeypatch.setattr(module, "get_target_connection", lambda value: calls.append(value) or connection)
    monkeypatch.setattr(module, "apply_migrations", lambda value: calls.append(("migrate", value)))

    module.prepare_preview_database(340, "sha")

    assert calls == ["postgresql://preview", ("migrate", connection)]
    assert connection.closed


def test_connection_closes_when_migration_fails(monkeypatch):
    from scripts import prepare_preview_database as module

    _env(
        monkeypatch,
        RAILWAY_ENVIRONMENT_NAME="pr-340",
        P063_PREVIEW_HEAD_SHA="sha",
        DATABASE_URL="postgresql://preview",
    )

    class Connection:
        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(module, "get_target_connection", lambda _value: connection)
    monkeypatch.setattr(module, "apply_migrations", lambda _value: (_ for _ in ()).throw(RuntimeError("failed")))

    with pytest.raises(RuntimeError, match="failed"):
        module.prepare_preview_database(340, "sha")
    assert connection.closed
