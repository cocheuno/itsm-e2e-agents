"""Byte-stable incident fixtures for seed 42. The same seed and anchor rebuild the same rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cm_agents.data.generate import generate, parse_anchor

from e2e.data.world import (
    ANCHOR,
    BURST_NOTES,
    BURST_SUMMARIES,
    CLUSTERS,
    DECOY_NOTES,
    DECOY_SUMMARIES,
    MARKER,
    NOISE_CIS,
    NOISE_DAYS,
    NOISE_SUMMARIES,
    PHRASES,
    SEED,
    category_for_class,
)

INJECT = f"{MARKER}INJECT"


def note_for(mechanism: str, summary: str) -> str:
    phrase = PHRASES[mechanism][0]
    return (
        "Caller says the service is slow and the page times out for some users. "
        f"Workaround tried: retried the page. Cause note: {phrase}. {summary}"
    )


def build_incidents() -> list[dict[str, Any]]:
    """Every planted incident, including arrivals that seed does not load."""
    _changes, ci_index = change_world()
    rows: list[dict[str, Any]] = []
    number = 1

    def add(row: dict[str, Any]) -> None:
        nonlocal number
        row["number"] = number
        rows.append(row)
        number += 1

    for cluster in CLUSTERS:
        days = cluster["days"]
        summaries = cluster["summaries"]
        assert isinstance(days, tuple)
        assert isinstance(summaries, tuple)
        history_count = int(cluster["history_count"])
        mechanism = str(cluster["mechanism"])
        for offset, day in enumerate(days):
            arrival = offset >= history_count
            description = f"Larkspur Outfitters incident. {summaries[offset]}"
            if cluster["id"] == "C07" and offset == len(days) - 1:
                description = f"{description} {INJECT}"
            add(
                _row(
                    cluster=str(cluster["id"]),
                    ci=str(cluster["ci"]),
                    day=str(day),
                    hour=15,
                    summary=str(summaries[offset]),
                    description=description,
                    notes=note_for(mechanism, str(summaries[offset])),
                    mechanism=mechanism,
                    parent=str(cluster.get("parent") or ""),
                    history=not arrival,
                    scenario=str(cluster["scenario"]),
                    ci_index=ci_index,
                )
            )
    for offset, summary in enumerate(DECOY_SUMMARIES):
        add(
            _row(
                cluster="D08",
                ci="syn-pay-recon",
                day="2026-10-20",
                hour=10 + offset,
                summary=summary,
                description=summary,
                notes=DECOY_NOTES[offset],
                mechanism="",
                parent="",
                history=True,
                scenario="E06",
                ci_index=ci_index,
            )
        )
    for offset, summary in enumerate(BURST_SUMMARIES):
        add(
            _row(
                cluster="D04",
                ci="syn-pay-gateway",
                day="2026-10-20",
                hour=10 + offset,
                summary=summary,
                description=summary,
                notes=BURST_NOTES[offset],
                mechanism="",
                parent="",
                history=True,
                scenario="E06",
                ci_index=ci_index,
            )
        )
    for noise_index, ci in enumerate(NOISE_CIS):
        for day_index, day in enumerate(NOISE_DAYS):
            summary = NOISE_SUMMARIES[noise_index * 3 + day_index]
            add(
                _row(
                    cluster=f"noise-{ci}",
                    ci=ci,
                    day=day,
                    hour=11,
                    summary=summary,
                    description=summary,
                    notes=f"Desk note: {summary}. No recurring cause was written down.",
                    mechanism="",
                    parent="",
                    history=True,
                    scenario="",
                    ci_index=ci_index,
                )
            )
    for index, row in enumerate(rows, start=1):
        row["correlation_id"] = f"{MARKER}INC-{row['cluster']}-{index:03d}"
        row["sys_id"] = row["correlation_id"]
    return rows


def _row(
    *,
    cluster: str,
    ci: str,
    day: str,
    hour: int,
    summary: str,
    description: str,
    notes: str,
    mechanism: str,
    parent: str,
    history: bool,
    scenario: str,
    ci_index: dict[str, dict[str, str]],
) -> dict[str, Any]:
    opened = f"{day} {hour:02d}:00:00"
    info = ci_index.get(ci)
    if info is None:
        raise ValueError(f"{ci} is not in the change-world CI index")
    category = category_for_class(info["ci_class"])
    if not category:
        raise ValueError(f"{ci} class {info['ci_class']} has no category")
    return {
        "cluster": cluster,
        "cmdb_ci": ci,
        "short_description": summary,
        "description": description,
        "notes": notes,
        "close_notes": notes,
        "mechanism": mechanism,
        "parent": parent,
        "history": history,
        "scenario": scenario,
        "opened_at": opened,
        "category": category,
        "business_service": "",
        "state": "6",
        "close_code": "Solution provided",
        "impact": "3",
        "urgency": "3",
        "priority": "3",
        "caller_id": "caller",
        "assignment_group": "SYN Service Desk",
    }


def change_world(anchor: str = ANCHOR) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    """Closed changes and the CI class/service index from the change repository's generator."""
    fixtures = generate(SEED, parse_anchor(anchor))
    changes = [
        {
            "key": str(row.get("key") or ""),
            "cmdb_ci": str(row["cmdb_ci"]),
            "ci_class": str(row["ci_class"]),
            "state": str(row["state"]),
            "closed_at": str(row["closed_at"]),
            "short_description": str(row["short_description"]),
            "service": str(row.get("service") or ""),
        }
        for row in fixtures["changes"]
        if str(row.get("state") or "") == "3" and row.get("closed_at")
    ]
    ci_index = {
        str(row["name"]): {
            "ci_class": str(row["ci_class"]),
            "service": str(row["service"]),
            "environment": str(row.get("environment") or ""),
        }
        for row in fixtures["cis"]
    }
    return changes, ci_index


def seeded_incidents(rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    source = build_incidents() if rows is None else rows
    return [row for row in source if row["history"]]


def detection_population(
    rows: list[dict[str, Any]],
    *,
    history_only: bool = False,
    partial_arrivals: bool = False,
) -> list[dict[str, Any]]:
    """Incidents detection may open a problem from. Parented rows stay out.

    partial_arrivals keeps C02 and C07 arrivals before 2026-10-24, four of the five.
    """
    chosen = []
    for row in rows:
        if row.get("parent"):
            continue
        if history_only and not row["history"]:
            continue
        if partial_arrivals and not row["history"]:
            if row["cluster"] not in {"C02", "C07"}:
                continue
            opened = datetime.strptime(str(row["opened_at"]), "%Y-%m-%d %H:%M:%S")
            if opened >= datetime(2026, 10, 24):
                continue
        chosen.append(row)
    return chosen
