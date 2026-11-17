"""Arrivals the seed does not load. The simulated clock decides which ones are due."""

from __future__ import annotations

from datetime import datetime

from cm_agents.data.import_time import UTC

from e2e.data.fixtures import build_incidents

E01_SHORT = (
    "Shoppers see a timeout when the application cannot write "
    "because there is no rotation of logs"
)
E01_DESCRIPTION = (
    "Larkspur Outfitters incident. Log rotation stopped. The log directory filled."
)
E01_OPENED = "2026-10-24 15:30:00"


def e01_arrival() -> dict[str, str]:
    """One new incident for the seeded CDN known error. It is not in the seed."""
    return {
        "correlation_id": "SYN-E2E-INC-E01-ARR-001",
        "cmdb_ci": "syn-store-cdn",
        "short_description": E01_SHORT,
        "description": E01_DESCRIPTION,
        "opened_at": E01_OPENED,
        "scenario": "E01",
        "impact": "3",
        "urgency": "3",
        "close_code": "",
        "close_notes": "",
        "notes": "",
    }


def due_arrivals(moment: datetime) -> list[dict]:
    """E02 rows, then the E01 arrival, whose opened time is at or before the clock."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    due: list[dict] = []
    for row in build_incidents():
        if row["history"] or row["scenario"] != "E02":
            continue
        if _opened(str(row["opened_at"])) <= moment:
            due.append(row)
    arrival = e01_arrival()
    if _opened(arrival["opened_at"]) <= moment:
        due.append(arrival)
    due.sort(key=lambda row: (str(row["opened_at"]), str(row["correlation_id"])))
    return due


def _opened(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
