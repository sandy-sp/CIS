from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, MutableMapping


_DEFAULT_PATH = Path("data/activity_log.json")
_MAX_ENTRIES = 250


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class ActivityLogStore:
    def __init__(self, path: Path = _DEFAULT_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_entries(self, limit: int | None = None) -> list[dict[str, Any]]:
        payload = self._read()
        entries = [
            entry for entry in payload.get("entries", [])
            if isinstance(entry, dict) and entry.get("message")
        ]
        ordered = sorted(entries, key=lambda item: item.get("timestamp", ""), reverse=True)
        return ordered[:limit] if limit else ordered

    def append_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        payload = self._read()
        entries = [
            item for item in payload.get("entries", [])
            if isinstance(item, dict)
        ]
        entry_copy = {
            "timestamp": entry.get("timestamp") or _utcnow_iso(),
            "source": str(entry.get("source", "") or "app"),
            "level": str(entry.get("level", "") or "info"),
            "message": str(entry.get("message", "") or ""),
            "details": str(entry.get("details", "") or ""),
        }
        entries.append(entry_copy)
        self._write({"entries": entries[-_MAX_ENTRIES:]})
        return entry_copy

    def clear(self) -> None:
        self._write({"entries": []})

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"entries": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"entries": []}
        if not isinstance(data, dict):
            return {"entries": []}
        entries = data.get("entries", [])
        if not isinstance(entries, list):
            return {"entries": []}
        return {"entries": entries}

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def ensure_activity_state(session_state: MutableMapping[str, Any]) -> None:
    if not isinstance(session_state.get("activity_markers"), dict):
        session_state["activity_markers"] = {}


def activity_marker_changed(
    session_state: MutableMapping[str, Any],
    key: str,
    value: Any,
) -> bool:
    ensure_activity_state(session_state)
    markers = session_state["activity_markers"]
    if markers.get(key) == value:
        return False
    markers[key] = value
    return True


def log_activity(
    session_state: MutableMapping[str, Any],
    source: str,
    message: str,
    *,
    level: str = "info",
    details: str = "",
    store: ActivityLogStore | None = None,
) -> dict[str, Any]:
    ensure_activity_state(session_state)
    activity_store = store or ActivityLogStore()
    entry = activity_store.append_entry({
        "source": source,
        "level": level,
        "message": message,
        "details": details,
    })
    session_state["activity_last_entry"] = entry
    return entry
