"""Incident reads for detection, signals, and links. Times come from ServiceNow."""

from __future__ import annotations

import sys
import types
from datetime import timedelta
from pathlib import Path
from typing import Any

from cm_agents.data.import_time import parse_utc
from cm_agents.servicenow.client import ServiceNowError

from e2e.data.fixtures import change_world
from e2e.data.signals import parse_opened, signals_for
from e2e.data.world import JOB_SCHEDULE, LOOKBACK_DAYS, MARKER
from e2e.errors import WorldError
from e2e.instance import http_failure

INCIDENT_FIELDS = [
    "sys_id",
    "number",
    "short_description",
    "description",
    "opened_at",
    "cmdb_ci",
    "category",
    "priority",
    "caller_id",
    "assignment_group",
    "state",
    "correlation_id",
    "close_notes",
    "parent",
]


def stamp(value: object) -> str:
    """The stored timestamp, or empty when the value is not a clock reading."""
    text = str(value or "").strip()
    if len(text) >= 19:
        text = text[:19]
    if len(text) != 19:
        return ""
    try:
        parse_utc(text)
    except ValueError:
        return ""
    return text


def ref(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("value") or "")
    return str(value or "")


def load_incidents(reader: Any) -> list[dict[str, Any]]:
    try:
        return reader.get_records(
            "incident",
            query=f"correlation_idSTARTSWITH{MARKER}INC",
            fields=INCIDENT_FIELDS,
            page_size=200,
            max_records=500,
        )
    except ServiceNowError as exc:
        raise http_failure("e2e incidents", exc) from None


def ci_names(reader: Any, ids: set[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    usable = [item for item in ids if len(item) == 32]
    for offset in range(0, len(usable), 40):
        chunk = usable[offset : offset + 40]
        try:
            rows = reader.get_table(
                "cmdb_ci",
                query="sys_idIN" + ",".join(chunk),
                fields=["sys_id", "name"],
                limit=len(chunk),
            )
        except ServiceNowError as exc:
            raise http_failure("ci names", exc) from None
        for row in rows:
            names[str(row.get("sys_id") or "")] = str(row.get("name") or "")
    return names


def detect_row(row: dict[str, Any], *, ci: str) -> dict[str, Any]:
    return {
        "sys_id": str(row.get("sys_id") or row.get("correlation_id") or ""),
        "number": str(row.get("number") or ""),
        "short_description": str(row.get("short_description") or ""),
        "opened_at": stamp(row.get("opened_at")),
        "cmdb_ci": ci,
        "business_service": "",
        "category": str(row.get("category") or ""),
        "subcategory": "",
        "priority": str(row.get("priority") or "4"),
        "caller_id": str(row.get("caller_id") or ""),
        "assignment_group": str(row.get("assignment_group") or ""),
        "state": str(row.get("state") or ""),
    }


def load_detect() -> Any:
    """The fork's detect(). gather() and run() are not called."""
    if "dotenv" not in sys.modules:
        try:
            import dotenv  # noqa: F401
        except ModuleNotFoundError:
            stub = types.ModuleType("dotenv")
            stub.load_dotenv = lambda *args, **kwargs: False  # type: ignore[attr-type]
            sys.modules["dotenv"] = stub
    fork = Path(__file__).resolve().parents[2].parent / "pm-agent-e2e"
    if not fork.is_dir():
        raise WorldError("pm-agent-e2e was not found")
    path = str(fork)
    if path not in sys.path:
        sys.path.insert(0, path)
    from detection_agent import detect

    return detect


def evidence_functions() -> tuple[Any, Any, Any]:
    """Pure evidence functions. gather() is not called."""
    load_detect()
    from rca_agent import _last_business_day, choose_method, clue_share

    return clue_share, choose_method, _last_business_day


def note_text(row: dict[str, Any]) -> str:
    close = str(row.get("close_notes") or "").strip()
    if close:
        return close
    return str(row.get("description") or "")


def signal_row(row: dict[str, Any], ci_name: str) -> dict[str, Any]:
    parent = ref(row.get("parent"))
    return {
        "cmdb_ci": ci_name,
        "opened_at": stamp(row.get("opened_at")),
        "notes": note_text(row),
        "category": str(row.get("category") or ""),
        "parent": parent,
        "number": str(row.get("number") or ""),
        "short_description": str(row.get("short_description") or ""),
    }


def cluster_signals(
    rows: list[dict[str, Any]],
    names: dict[str, str],
    *,
    ci_name: str,
    category: str,
) -> dict[str, Any]:
    """Signals for one CI and category over the lookback, from stored opened_at.

    Members are the history and the arrivals on that CI and category whose
    stored open time falls in the lookback of the latest one. The population
    is every loaded incident. Changes come from the change-world generator.
    """
    changes, ci_index = change_world()
    prepared: list[tuple[dict[str, Any], dict[str, Any]]] = []
    latest = ""
    for row in rows:
        opened = stamp(row.get("opened_at"))
        if not opened:
            continue
        ci_id = str(row.get("cmdb_ci") or "")
        name = names.get(ci_id, "")
        if not name:
            continue
        shaped = signal_row(row, name)
        prepared.append((row, shaped))
        if name == ci_name and shaped["category"] == category and opened > latest:
            latest = opened
    if not latest:
        raise WorldError("cluster has no stored open time")
    start = parse_opened(latest) - timedelta(days=LOOKBACK_DAYS)
    end = parse_opened(latest)
    members = []
    member_rows = []
    population = []
    for row, shaped in prepared:
        if not shaped["opened_at"]:
            continue
        population.append(shaped)
        if shaped["cmdb_ci"] != ci_name or shaped["category"] != category:
            continue
        moment = parse_opened(str(shaped["opened_at"]))
        if start <= moment <= end:
            members.append(shaped)
            member_rows.append(row)
    signal = signals_for(members, population, changes, JOB_SCHEDULE, ci_index)
    clue, choose, last_day = evidence_functions()
    evidence = {
        "incidents": [
            {
                "number": str(shaped.get("number") or ""),
                "notes": [str(shaped.get("notes") or "")],
                "cmdb_ci": ci_name,
                "subcategory": "",
            }
            for shaped in members
        ]
    }
    _term, share = clue(evidence)
    method, _reason = choose(evidence)
    month_end = 0
    for shaped in members:
        opened = str(shaped.get("opened_at") or "")
        if opened and last_day(parse_opened(opened).date()):
            month_end += 1
    signal["clue_share"] = round(share, 3)
    signal["method"] = method
    signal["last_business_day"] = month_end
    signal["members"] = member_rows
    return signal
