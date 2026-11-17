"""Append-only config history for this repository.

The change repository's recorder writes beside its own pyproject. This one
writes data/synthetic/config_history.jsonl here, and it keeps every sys_id
this seed creates so a later customer-update row still classifies.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from cm_agents.data.import_time import UTC

from e2e.paths import history_path

_SYS_ID = re.compile(r"[0-9a-f]{32}")


def record(action: str, table: str, sys_id: str, name: str) -> None:
    if action not in {"create", "delete"}:
        raise ValueError(f"config history action must be create or delete, not {action}")
    if not _SYS_ID.fullmatch(sys_id):
        return
    payload = {
        "action": action,
        "table": table,
        "sys_id": sys_id.lower(),
        "name": name,
        "time": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
    }
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


class Ledger:
    """Create lines are written once per sys_id. Delete lines are always appended."""

    def __init__(self) -> None:
        self.known = known_sys_ids()

    def create(self, table: str, sys_id: str, name: str) -> None:
        if not _SYS_ID.fullmatch(sys_id):
            return
        lowered = sys_id.lower()
        if lowered in self.known:
            return
        record("create", table, lowered, name)
        self.known.add(lowered)

    def delete(self, table: str, sys_id: str, name: str) -> None:
        if not _SYS_ID.fullmatch(sys_id):
            return
        lowered = sys_id.lower()
        record("delete", table, lowered, name)
        self.known.add(lowered)


def known_sys_ids() -> set[str]:
    path = history_path()
    if not path.is_file():
        return set()
    found: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue
        sys_id = str(row.get("sys_id") or "")
        if _SYS_ID.fullmatch(sys_id):
            found.add(sys_id.lower())
    return found
