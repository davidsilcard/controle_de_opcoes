from __future__ import annotations

import datetime as dt
import sqlite3

from werkzeug.security import generate_password_hash

from opcoes import auth


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        if not self._rows:
            return None
        return self._rows[0]

    def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def __init__(self):
        self.users: dict[str, dict] = {}

    def execute(self, sql: str, params=()):
        q = " ".join(sql.strip().split()).lower()

        if q.startswith("create table if not exists"):
            return _FakeResult([])

        if q.startswith("select id from web_users where username = %s limit 1"):
            username = str(params[0])
            row = self.users.get(username)
            if row is None:
                return _FakeResult([])
            return _FakeResult([{"id": row["id"]}])

        if q.startswith("select id from web_users where username = %s"):
            username = str(params[0])
            row = self.users.get(username)
            if row is None:
                return _FakeResult([])
            return _FakeResult([{"id": row["id"]}])

        if q.startswith("update web_users set password_hash = %s, is_active = true, updated_at = %s where username = %s"):
            pwd_hash, updated_at, username = params
            row = self.users[str(username)]
            row["password_hash"] = str(pwd_hash)
            row["is_active"] = True
            row["updated_at"] = updated_at
            return _FakeResult([])

        if q.startswith("update web_users set password_hash = %s, is_active = %s, updated_at = %s where username = %s"):
            pwd_hash, is_active, updated_at, username = params
            row = self.users[str(username)]
            row["password_hash"] = str(pwd_hash)
            row["is_active"] = bool(is_active)
            row["updated_at"] = updated_at
            return _FakeResult([])

        if q.startswith("insert into web_users (username, password_hash, is_active, created_at, updated_at) values"):
            if len(params) == 4:
                username, pwd_hash, created_at, updated_at = params
                is_active = True
            else:
                username, pwd_hash, is_active, created_at, updated_at = params
            self.users[str(username)] = {
                "id": len(self.users) + 1,
                "username": str(username),
                "password_hash": str(pwd_hash),
                "is_active": bool(is_active),
                "created_at": created_at,
                "updated_at": updated_at,
            }
            return _FakeResult([])

        if q.startswith("select username from web_users where is_active = true order by username asc"):
            rows = [{"username": name} for name, row in sorted(self.users.items()) if row["is_active"]]
            return _FakeResult(rows)

        if q.startswith("select username from web_users order by username asc"):
            rows = [{"username": name} for name, _row in sorted(self.users.items())]
            return _FakeResult(rows)

        if q.startswith("select password_hash, is_active from web_users where username = %s limit 1"):
            username = str(params[0])
            row = self.users.get(username)
            if row is None:
                return _FakeResult([])
            return _FakeResult(
                [{"password_hash": row["password_hash"], "is_active": row["is_active"]}]
            )

        raise AssertionError(f"SQL inesperado: {sql}")

    def commit(self):
        return None

    def close(self):
        return None


def test_create_list_and_authenticate_users(monkeypatch) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(auth, "_connect", lambda: conn)

    created = auth.create_user(username="admin", password="SenhaForte123!")
    assert created is True
    assert auth.list_users() == ["admin"]

    assert auth.authenticate_user(username="admin", password="SenhaForte123!")
    assert not auth.authenticate_user(username="admin", password="senha-errada")


def test_migrate_auth_from_legacy_sqlite(monkeypatch, tmp_path) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(auth, "_connect", lambda: conn)

    legacy_path = tmp_path / "auth.db"
    legacy = sqlite3.connect(legacy_path)
    try:
        legacy.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        legacy.execute(
            """
            INSERT INTO users (username, password_hash, is_active, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            """,
            ("admin", generate_password_hash("SenhaForte123!"), now, now),
        )
        legacy.commit()
    finally:
        legacy.close()

    report = auth.migrate_auth_from_legacy_sqlite(source_db=legacy_path)
    assert report["status"] == "ok"
    assert report["inserted"] == 1
    assert report["skipped_invalid"] == 0
    assert auth.authenticate_user(username="admin", password="SenhaForte123!")
