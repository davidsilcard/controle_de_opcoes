from __future__ import annotations

from opcoes.change_history import ensure_change_history, set_change_context


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self):
        self.queries: list[tuple[str, tuple[object, ...]]] = []
        self.committed = False

    def execute(self, query: str, params=()):
        self.queries.append((query, tuple(params)))
        if "to_regclass" in query:
            return _Result({"name": "positions"})
        return _Result()

    def commit(self) -> None:
        self.committed = True


def test_ensure_change_history_creates_append_only_audit_triggers() -> None:
    conn = _FakeConn()

    ensure_change_history(conn, commit=True)

    sql = "\n".join(query for query, _params in conn.queries)
    assert "CREATE TABLE IF NOT EXISTS record_history" in sql
    assert "record_history_positions_trigger" in sql
    assert "record_history_ledger_trigger" in sql
    assert "BEFORE UPDATE OR DELETE ON record_history" in sql
    assert conn.committed is True


def test_change_context_is_limited_and_stored_in_database_session() -> None:
    conn = _FakeConn()

    set_change_context(conn, actor="david", reason="cadastro duplicado")

    assert conn.queries[-2][1] == ("david",)
    assert conn.queries[-1][1] == ("cadastro duplicado",)
