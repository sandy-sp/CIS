from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_DEFAULT_PATH = Path("data/index_registry.json")


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


class IndexRegistry:
    def __init__(self, path: Path = _DEFAULT_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_targets(self) -> list[dict[str, Any]]:
        payload = self._read()
        targets = payload.get("targets", [])
        return sorted(
            [target for target in targets if target.get("target_id")],
            key=lambda item: _parse_iso(item.get("indexed_at", "")),
            reverse=True,
        )

    def get_target(self, target_id: str) -> dict[str, Any] | None:
        for target in self.list_targets():
            if target.get("target_id") == target_id:
                return target
        return None

    def save_target(self, target: dict[str, Any]) -> dict[str, Any]:
        payload = self._read()
        targets = {
            item["target_id"]: item
            for item in payload.get("targets", [])
            if item.get("target_id")
        }
        target_copy = dict(target)
        target_copy["indexed_at"] = target_copy.get("indexed_at") or _utcnow_iso()
        targets[target_copy["target_id"]] = target_copy
        self._write({"targets": list(targets.values())})
        return target_copy

    def remove_target(self, target_id: str) -> None:
        self.remove_targets([target_id])

    def remove_targets(self, target_ids: list[str]) -> int:
        target_id_set = {target_id for target_id in target_ids if target_id}
        if not target_id_set:
            return 0
        payload = self._read()
        existing_targets = payload.get("targets", [])
        targets = [
            item for item in existing_targets
            if item.get("target_id") not in target_id_set
        ]
        removed = len(existing_targets) - len(targets)
        if removed:
            self._write({"targets": targets})
        return removed

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"targets": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"targets": []}
        if not isinstance(data, dict):
            return {"targets": []}
        targets = data.get("targets", [])
        if not isinstance(targets, list):
            return {"targets": []}
        return {"targets": targets}

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
