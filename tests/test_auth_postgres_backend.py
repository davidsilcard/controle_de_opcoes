from __future__ import annotations

import datetime as dt

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
        self.schemas: set[str] = {"auth"}

    def execute(self, sql: str, params=()):
        q = " ".join(sql.strip().split()).lower()

        if q.startswith("create table if not exists web_users"):
            return _FakeResult([])
        if q.startswith("alter table web_users add column if not exists"):
            return _FakeResult([])
        if q.startswith("create unique index if not exists idx_web_users_app_schema_unique"):
            return _FakeResult([])
        if q.startswith("create table if not exists web_login_attempts"):
            return _FakeResult([])
        if q.startswith("create index if not exists idx_web_login_attempts_blocked_until"):
            return _FakeResult([])

        if q.startswith("select username, app_schema from web_users order by username asc"):
            rows = [
                {"username": row["username"], "app_schema": row.get("app_schema")}
                for _, row in sorted(self.users.items())
            ]
            return _FakeResult(rows)

        if q.startswith("select id, app_schema from web_users where username = %s limit 1"):
            username = str(params[0])
            row = self.users.get(username)
            if row is None:
                return _FakeResult([])
            return _FakeResult([{"id": row["id"], "app_schema": row.get("app_schema")}])

        if q.startswith("select id, app_schema from web_users where username = %s"):
            username = str(params[0])
            row = self.users.get(username)
            if row is None:
                return _FakeResult([])
            return _FakeResult([{"id": row["id"], "app_schema": row.get("app_schema")}])

        if q.startswith("select username from web_users where app_schema = %s limit 1"):
            schema = str(params[0])
            for row in self.users.values():
                if str(row.get("app_schema") or "") == schema:
                    return _FakeResult([{"username": row["username"]}])
            return _FakeResult([])

        if q.startswith(
            "update web_users set password_hash = %s, app_schema = %s, is_active = true, must_change_password = %s, temp_password_issued_at = %s, updated_at = %s where username = %s"
        ):
            pwd_hash, app_schema, must_change_password, temp_password_issued_at, updated_at, username = params
            row = self.users[str(username)]
            row["password_hash"] = str(pwd_hash)
            row["app_schema"] = str(app_schema)
            row["is_active"] = True
            row["must_change_password"] = bool(must_change_password)
            row["temp_password_issued_at"] = temp_password_issued_at
            row["updated_at"] = updated_at
            return _FakeResult([])

        if q.startswith(
            "update web_users set password_hash = %s, app_schema = %s, is_active = true, must_change_password = false, temp_password_issued_at = null, updated_at = %s where username = %s"
        ):
            pwd_hash, app_schema, updated_at, username = params
            row = self.users[str(username)]
            row["password_hash"] = str(pwd_hash)
            row["app_schema"] = str(app_schema)
            row["is_active"] = True
            row["must_change_password"] = False
            row["temp_password_issued_at"] = None
            row["updated_at"] = updated_at
            return _FakeResult([])

        if q.startswith(
            "update web_users set app_schema = %s, updated_at = %s where username = %s"
        ):
            app_schema, updated_at, username = params
            row = self.users[str(username)]
            row["app_schema"] = str(app_schema)
            row["updated_at"] = updated_at
            return _FakeResult([])

        if q.startswith(
            "insert into web_users ( username, password_hash, app_schema, is_active, must_change_password, temp_password_issued_at, created_at, updated_at ) values"
        ):
            (
                username,
                pwd_hash,
                app_schema,
                must_change_password,
                temp_password_issued_at,
                created_at,
                updated_at,
            ) = params
            self.users[str(username)] = {
                "id": len(self.users) + 1,
                "username": str(username),
                "password_hash": str(pwd_hash),
                "app_schema": str(app_schema),
                "is_active": True,
                "must_change_password": bool(must_change_password),
                "temp_password_issued_at": temp_password_issued_at,
                "created_at": created_at,
                "updated_at": updated_at,
            }
            return _FakeResult([])

        if q.startswith("select username from web_users where is_active = true order by username asc"):
            rows = [
                {"username": name}
                for name, row in sorted(self.users.items())
                if row["is_active"]
            ]
            return _FakeResult(rows)

        if q.startswith("select username from web_users order by username asc"):
            rows = [{"username": name} for name, _row in sorted(self.users.items())]
            return _FakeResult(rows)

        if q.startswith(
            "select username, password_hash, app_schema, is_active, must_change_password, temp_password_issued_at from web_users where username = %s limit 1"
        ):
            username = str(params[0])
            row = self.users.get(username)
            if row is None:
                return _FakeResult([])
            return _FakeResult(
                [
                    {
                        "username": row["username"],
                        "password_hash": row["password_hash"],
                        "app_schema": row.get("app_schema"),
                        "is_active": row["is_active"],
                        "must_change_password": row["must_change_password"],
                        "temp_password_issued_at": row["temp_password_issued_at"],
                    }
                ]
            )

        if "from information_schema.schemata" in q:
            schema = str(params[0])
            if schema in self.schemas:
                return _FakeResult([{"schema_name": schema}])
            return _FakeResult([])

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

    assert conn.users["admin"]["app_schema"] == "admin"
    result = auth.authenticate_login(username="admin", password="SenhaForte123!")
    assert result.user is not None
    assert result.user.app_schema == "admin"
    assert auth.authenticate_user(username="admin", password="SenhaForte123!")
    assert not auth.authenticate_user(username="admin", password="senha-errada")


def test_create_user_assigns_distinct_schema_for_colliding_usernames(monkeypatch) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(auth, "_connect", lambda: conn)

    assert auth.create_user(username="ana.silva", password="SenhaForte123!")
    assert auth.create_user(username="ana_silva", password="SenhaForte123!")

    first_schema = conn.users["ana.silva"]["app_schema"]
    second_schema = conn.users["ana_silva"]["app_schema"]

    assert first_schema == "ana_silva"
    assert second_schema.startswith("ana_silva_")
    assert second_schema != first_schema

    first_login = auth.authenticate_login(username="ana.silva", password="SenhaForte123!")
    second_login = auth.authenticate_login(username="ana_silva", password="SenhaForte123!")
    assert first_login.user is not None
    assert second_login.user is not None
    assert first_login.user.app_schema != second_login.user.app_schema


def test_issue_temporary_password_requires_change_and_allows_final_change(monkeypatch) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(auth, "_connect", lambda: conn)

    temp_password = auth.issue_temporary_password(username="alice")
    assert len(temp_password) >= 10

    auth_result = auth.authenticate_login(username="alice", password=temp_password)
    assert auth_result.user is not None
    assert auth_result.user.must_change_password is True
    assert auth_result.user.app_schema == "alice"

    changed = auth.change_password(username="alice", password="SenhaFinal123!")
    assert changed is True

    authenticated_final = auth.authenticate_login(
        username="alice", password="SenhaFinal123!"
    )
    assert authenticated_final.user is not None
    assert authenticated_final.user.must_change_password is False


def test_temporary_password_expires_after_three_hours(monkeypatch) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(auth, "_connect", lambda: conn)
    monkeypatch.setenv("OPCOES_TEMP_PASSWORD_TTL_SECONDS", "10800")

    temp_password = auth.issue_temporary_password(username="expired_user")
    conn.users["expired_user"]["temp_password_issued_at"] = dt.datetime.now(dt.UTC) - dt.timedelta(hours=4)

    auth_result = auth.authenticate_login(
        username="expired_user", password=temp_password
    )
    assert auth_result.user is None
    assert auth_result.error_code == "temp_password_expired"


def test_migrate_user_app_schemas_assigns_unique_targets_and_clones_legacy(monkeypatch) -> None:
    conn = _FakeConn()
    conn.users = {
        "ana.silva": {
            "id": 1,
            "username": "ana.silva",
            "password_hash": "hash",
            "app_schema": None,
            "is_active": True,
            "must_change_password": False,
            "temp_password_issued_at": None,
        },
        "ana_silva": {
            "id": 2,
            "username": "ana_silva",
            "password_hash": "hash",
            "app_schema": None,
            "is_active": True,
            "must_change_password": False,
            "temp_password_issued_at": None,
        },
    }
    conn.schemas.add("ana_silva")

    clones: list[dict[str, object]] = []
    monkeypatch.setattr(auth, "_connect", lambda: conn)
    monkeypatch.setattr(
        auth,
        "resolve_postgres_target",
        lambda: (type("Target", (), {"dsn": "postgresql://demo"})(), []),
    )
    monkeypatch.setattr(
        auth,
        "clone_postgres_schema",
        lambda **kwargs: clones.append(kwargs),
    )

    report = auth.migrate_user_app_schemas(dry_run=False, clone_legacy_schema=True)

    assert report["updated_users"]
    assert conn.users["ana.silva"]["app_schema"] == "ana_silva"
    assert conn.users["ana_silva"]["app_schema"].startswith("ana_silva_")
    assert len(clones) == 1
    assert clones[0]["source_schema"] == "ana_silva"
    assert clones[0]["target_schema"] == conn.users["ana_silva"]["app_schema"]
