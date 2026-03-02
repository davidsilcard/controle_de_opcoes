from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from .storage import CSV_FIELDS, _ensure_parent


def default_checkpoint_db_path(output_csv: Path) -> Path:
    return output_csv.with_suffix(".checkpoint.json")


@dataclass(frozen=True)
class CheckpointState:
    processed_symbols: List[str]
    snapshot_rows: List[Dict[str, str]]
    snapshot_date: Optional[str]


class ScrapeCheckpointStore:
    """Checkpoint do scraper por arquivo JSON local (sem banco adicional)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        _ensure_parent(self.path)
        self._state: Dict[str, Any] = {"sessions": {}}
        self._load()

    def close(self) -> None:
        return None

    def prepare(
        self,
        *,
        output_csv: Path,
        target_symbols: Sequence[str],
        symbols_signature: str,
    ) -> CheckpointState:
        output_resolved = str(output_csv.resolve())
        session_id = _session_id(output_resolved)
        now = _now_iso()
        symbols = _normalize_symbols(target_symbols)
        symbols_json = json.dumps(symbols, ensure_ascii=False, separators=(",", ":"))

        sessions = self._state.setdefault("sessions", {})
        session = sessions.get(session_id)
        changed = False
        if not isinstance(session, dict):
            session = None

        if session is None:
            sessions[session_id] = {
                "session_id": session_id,
                "output_csv": output_resolved,
                "symbols_signature": symbols_signature,
                "symbols_json": symbols_json,
                "snapshot_date": None,
                "last_symbol": None,
                "created_at": now,
                "updated_at": now,
                "symbols_state": {
                    symbol: {
                        "status": "pending",
                        "attempts": 0,
                        "row_count": 0,
                        "last_error": None,
                        "updated_at": now,
                    }
                    for symbol in symbols
                },
                "rows": {},
            }
            changed = True
            session = sessions[session_id]
        else:
            if session.get("output_csv") != output_resolved:
                raise RuntimeError("Checkpoint session inconsistente com output_csv.")
            changed = self._reconcile_symbols(
                session=session,
                target_symbols=symbols,
                symbols_signature=symbols_signature,
                symbols_json=symbols_json,
                updated_at=now,
            )

        if changed:
            self._save()

        symbols_state = session.get("symbols_state", {})
        processed_symbols = [
            symbol
            for symbol in symbols
            if str((symbols_state.get(symbol) or {}).get("status") or "").lower() == "done"
        ]
        snapshot_rows = self._load_rows(session=session, target_symbols=symbols)
        snapshot_date = session.get("snapshot_date")
        return CheckpointState(
            processed_symbols=processed_symbols,
            snapshot_rows=snapshot_rows,
            snapshot_date=str(snapshot_date) if snapshot_date else None,
        )

    def mark_symbol_running(self, *, output_csv: Path, symbol: str) -> None:
        session = self._require_session(output_csv=output_csv)
        now = _now_iso()
        symbols_state = session.setdefault("symbols_state", {})
        item = symbols_state.setdefault(
            symbol,
            {"status": "pending", "attempts": 0, "row_count": 0, "last_error": None, "updated_at": now},
        )
        item["status"] = "running"
        item["attempts"] = int(item.get("attempts") or 0) + 1
        item["updated_at"] = now
        session["last_symbol"] = symbol
        session["updated_at"] = now
        self._save()

    def mark_symbol_failed(self, *, output_csv: Path, symbol: str, error: str) -> None:
        session = self._require_session(output_csv=output_csv)
        now = _now_iso()
        symbols_state = session.setdefault("symbols_state", {})
        item = symbols_state.setdefault(
            symbol,
            {"status": "pending", "attempts": 0, "row_count": 0, "last_error": None, "updated_at": now},
        )
        item["status"] = "failed"
        item["last_error"] = (error or "").strip()[:1500]
        item["updated_at"] = now
        session["last_symbol"] = symbol
        session["updated_at"] = now
        self._save()

    def mark_symbol_success(
        self,
        *,
        output_csv: Path,
        symbol: str,
        rows: Sequence[Dict[str, str]],
        snapshot_date: Optional[str],
    ) -> None:
        session = self._require_session(output_csv=output_csv)
        now = _now_iso()
        clean_rows = _normalize_rows(rows)

        rows_by_symbol = session.setdefault("rows", {})
        symbol_rows: Dict[str, Dict[str, str]] = {}
        for row in clean_rows:
            ticker = (row.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            symbol_rows[ticker] = row
        rows_by_symbol[symbol] = symbol_rows

        symbols_state = session.setdefault("symbols_state", {})
        item = symbols_state.setdefault(
            symbol,
            {"status": "pending", "attempts": 0, "row_count": 0, "last_error": None, "updated_at": now},
        )
        item["status"] = "done"
        item["row_count"] = len(clean_rows)
        item["last_error"] = None
        item["updated_at"] = now

        current_snapshot = session.get("snapshot_date")
        session["snapshot_date"] = _max_iso_date(
            str(current_snapshot) if current_snapshot else None, snapshot_date
        )
        session["last_symbol"] = symbol
        session["updated_at"] = now
        self._save()

    def status_counts(self, *, output_csv: Path, target_symbols: Sequence[str]) -> Dict[str, int]:
        session = self._require_session(output_csv=output_csv, create_if_missing=False)
        target_set = set(_normalize_symbols(target_symbols))
        counts = {"done": 0, "failed": 0, "running": 0, "pending": 0, "total": len(target_set)}
        if session is None:
            counts["pending"] = counts["total"]
            return counts

        symbols_state = session.get("symbols_state", {})
        for symbol in target_set:
            item = symbols_state.get(symbol) or {}
            status = str(item.get("status") or "pending").lower()
            if status not in {"done", "failed", "running", "pending"}:
                status = "pending"
            counts[status] += 1
        return counts

    def is_complete(self, *, output_csv: Path, target_symbols: Sequence[str]) -> bool:
        counts = self.status_counts(output_csv=output_csv, target_symbols=target_symbols)
        return counts["total"] > 0 and counts["done"] == counts["total"]

    def clear(self, *, output_csv: Path) -> None:
        session_id = _session_id(str(output_csv.resolve()))
        sessions = self._state.setdefault("sessions", {})
        if session_id in sessions:
            sessions.pop(session_id, None)
            self._save()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(parsed, dict) and isinstance(parsed.get("sessions"), dict):
            self._state = parsed

    def _save(self) -> None:
        payload = json.dumps(self._state, ensure_ascii=False, separators=(",", ":"))
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(self.path)

    def _require_session(
        self,
        *,
        output_csv: Path,
        create_if_missing: bool = True,
    ) -> Optional[Dict[str, Any]]:
        session_id = _session_id(str(output_csv.resolve()))
        sessions = self._state.setdefault("sessions", {})
        session = sessions.get(session_id)
        if isinstance(session, dict):
            return session
        if not create_if_missing:
            return None
        now = _now_iso()
        session = {
            "session_id": session_id,
            "output_csv": str(output_csv.resolve()),
            "symbols_signature": "",
            "symbols_json": "[]",
            "snapshot_date": None,
            "last_symbol": None,
            "created_at": now,
            "updated_at": now,
            "symbols_state": {},
            "rows": {},
        }
        sessions[session_id] = session
        return session

    def _reconcile_symbols(
        self,
        *,
        session: Dict[str, Any],
        target_symbols: Sequence[str],
        symbols_signature: str,
        symbols_json: str,
        updated_at: str,
    ) -> bool:
        changed = False
        target_set = set(target_symbols)
        symbols_state = session.setdefault("symbols_state", {})
        rows_by_symbol = session.setdefault("rows", {})

        for symbol in list(symbols_state.keys()):
            if symbol not in target_set:
                symbols_state.pop(symbol, None)
                changed = True
        for symbol in list(rows_by_symbol.keys()):
            if symbol not in target_set:
                rows_by_symbol.pop(symbol, None)
                changed = True
        for symbol in target_symbols:
            if symbol not in symbols_state:
                symbols_state[symbol] = {
                    "status": "pending",
                    "attempts": 0,
                    "row_count": 0,
                    "last_error": None,
                    "updated_at": updated_at,
                }
                changed = True

        if session.get("symbols_signature") != symbols_signature:
            session["symbols_signature"] = symbols_signature
            changed = True
        if session.get("symbols_json") != symbols_json:
            session["symbols_json"] = symbols_json
            changed = True
        if changed:
            session["updated_at"] = updated_at
        return changed

    def _load_rows(self, *, session: Dict[str, Any], target_symbols: Sequence[str]) -> List[Dict[str, str]]:
        rows_by_symbol = session.get("rows", {})
        rows: List[Dict[str, str]] = []
        for symbol in target_symbols:
            symbol_rows = rows_by_symbol.get(symbol)
            if not isinstance(symbol_rows, dict):
                continue
            for ticker in sorted(symbol_rows.keys()):
                parsed = symbol_rows.get(ticker)
                if not isinstance(parsed, dict):
                    continue
                row = {field: str(parsed.get(field) or "") for field in CSV_FIELDS}
                rows.append(row)
        return rows


def _session_id(output_csv_resolved: str) -> str:
    return hashlib.sha1(output_csv_resolved.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _normalize_symbols(symbols: Sequence[str]) -> List[str]:
    normalized: List[str] = []
    seen: Set[str] = set()
    for raw in symbols:
        symbol = (raw or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _normalize_rows(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for row in rows:
        clean = {field: str(row.get(field) or "") for field in CSV_FIELDS}
        normalized.append(clean)
    return normalized


def _max_iso_date(current: Optional[str], candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return current
    if not current:
        return candidate
    try:
        current_dt = dt.date.fromisoformat(current)
        candidate_dt = dt.date.fromisoformat(candidate)
    except ValueError:
        return current
    return max(current_dt, candidate_dt).isoformat()


__all__ = ["CheckpointState", "ScrapeCheckpointStore", "default_checkpoint_db_path"]
