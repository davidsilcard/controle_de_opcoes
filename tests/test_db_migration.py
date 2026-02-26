import sqlite3
import sys
from pathlib import Path

from opcoes import cli
from opcoes.db_health import PostgresTarget
from opcoes.db_migration import (
    SourceDatabase,
    inspect_sqlite_tables,
    migrate_sqlite_sources_to_postgres,
    resolve_user_source_databases,
    sanitize_schema_name,
)


def _create_sqlite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE sample (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                score REAL DEFAULT 0
            )
            """
        )
        conn.execute("INSERT INTO sample (name, score) VALUES ('A', 1.5)")
        conn.execute("INSERT INTO sample (name, score) VALUES ('B', 2.0)")
        conn.commit()
    finally:
        conn.close()


def test_sanitize_schema_name() -> None:
    assert sanitize_schema_name("Admin.User") == "admin_user"
    assert sanitize_schema_name("  123 abc  ") == "u_123_abc"
    assert sanitize_schema_name("") == "public"


def test_resolve_user_source_databases_with_source_dir(tmp_path: Path) -> None:
    src_dir = tmp_path / "sqlite"
    main = src_dir / "opcoes_snapshots.db"
    iv = src_dir / "iv_history.db"
    flow = src_dir / "flow_history.db"
    _create_sqlite(main)
    _create_sqlite(iv)
    _create_sqlite(flow)

    sources = resolve_user_source_databases(
        username="admin",
        source_dir=src_dir,
        include_aux=True,
    )

    assert [s.label for s in sources] == ["main", "iv_history", "flow_history"]
    assert sources[0].path == main
    assert sources[1].path == iv
    assert sources[2].path == flow


def test_inspect_sqlite_tables(tmp_path: Path) -> None:
    path = tmp_path / "sample.db"
    _create_sqlite(path)

    tables = inspect_sqlite_tables(path)

    assert len(tables) == 1
    table = tables[0]
    assert table.name == "sample"
    assert table.row_count == 2
    assert [c.name for c in table.columns] == ["id", "name", "score"]
    assert any(c.pk_ordinal == 1 for c in table.columns)


def test_migrate_sqlite_sources_to_postgres_dry_run(
    monkeypatch, tmp_path: Path
) -> None:
    path = tmp_path / "sample.db"
    _create_sqlite(path)

    monkeypatch.setattr(
        "opcoes.db_migration.resolve_postgres_target",
        lambda: (
            PostgresTarget(
                dsn="postgresql://user:pwd@host:5432/db",
                redacted_dsn="postgresql://user:***@host:5432/db",
                source="DATABASE_URL",
                host="host",
                port=5432,
            ),
            [],
        ),
    )

    report = migrate_sqlite_sources_to_postgres(
        schema="admin",
        sources=[SourceDatabase(label="main", path=path, required=True)],
        dry_run=True,
    )

    assert report["dry_run"] is True
    assert report["schema"] == "admin"
    assert report["rows_copied"] == 0
    assert report["tables"][0]["name"] == "sample"
    assert report["tables"][0]["rows"] == 2


def test_cli_db_migrate_dry_run(monkeypatch, capsys, tmp_path: Path) -> None:
    src = tmp_path / "opcoes_snapshots.db"
    _create_sqlite(src)

    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(
        cli,
        "resolve_user_source_databases",
        lambda **kwargs: [SourceDatabase(label="main", path=src, required=True)],
    )
    monkeypatch.setattr(
        cli,
        "migrate_sqlite_sources_to_postgres",
        lambda **kwargs: {
            "postgres_target": "postgresql://user:***@host:5432/db",
            "dry_run": True,
            "tables": [{"source": "main", "name": "sample", "rows": 2}],
            "rows_copied": 0,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["opcoes", "db", "migrate", "--username", "admin", "--dry-run"],
    )

    cli.main()
    out = capsys.readouterr().out
    assert "Schema destino: admin" in out
    assert "Dry-run concluído" in out


def test_cli_db_verify_ok(monkeypatch, capsys, tmp_path: Path) -> None:
    src = tmp_path / "opcoes_snapshots.db"
    _create_sqlite(src)

    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(
        cli,
        "resolve_user_source_databases",
        lambda **kwargs: [SourceDatabase(label="main", path=src, required=True)],
    )
    monkeypatch.setattr(
        cli,
        "verify_sqlite_sources_in_postgres",
        lambda **kwargs: {
            "postgres_target": "postgresql://user:***@host:5432/db",
            "tables": [
                {
                    "source": "main",
                    "table": "sample",
                    "sqlite_rows": 2,
                    "postgres_rows": 2,
                    "status": "ok",
                }
            ],
            "ok": True,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["opcoes", "db", "verify", "--username", "admin"],
    )

    cli.main()
    out = capsys.readouterr().out
    assert "Schema alvo: admin" in out
    assert "Verificação concluída: contagens consistentes." in out


def test_cli_db_verify_mismatch(monkeypatch, tmp_path: Path) -> None:
    src = tmp_path / "opcoes_snapshots.db"
    _create_sqlite(src)

    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(
        cli,
        "resolve_user_source_databases",
        lambda **kwargs: [SourceDatabase(label="main", path=src, required=True)],
    )
    monkeypatch.setattr(
        cli,
        "verify_sqlite_sources_in_postgres",
        lambda **kwargs: {
            "postgres_target": "postgresql://user:***@host:5432/db",
            "tables": [
                {
                    "source": "main",
                    "table": "sample",
                    "sqlite_rows": 2,
                    "postgres_rows": 1,
                    "status": "count_mismatch",
                }
            ],
            "ok": False,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["opcoes", "db", "verify", "--username", "admin"],
    )

    try:
        cli.main()
    except SystemExit:
        return
    raise AssertionError("Era esperado SystemExit com mismatch de verificação.")
