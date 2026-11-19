"""Read-only detection over PMSYNTH incidents. This is a report, not a gate.

The same detect() rule runs. Nothing is written. Existing parent links are ignored
because detect() does not read parent. A failure here must not fail the scenario.
"""

from __future__ import annotations

import json
from typing import Any

from cm_agents.servicenow.client import ServiceNowError

from e2e.adapters.incident import ci_names as _ci_names
from e2e.adapters.incident import detect_row as _detect_row
from e2e.adapters.incident import load_detect as _fork
from e2e.adapters.incident import stamp as _stamp
from e2e.errors import WorldError
from e2e.instance import http_failure, open_client
from e2e.paths import repo_root
from e2e.settings import Settings

_ANSWER = "20261105-201823_answer_key.json"
_FIELDS = [
    "sys_id",
    "number",
    "short_description",
    "opened_at",
    "cmdb_ci",
    "category",
    "priority",
    "caller_id",
    "assignment_group",
    "state",
    "correlation_id",
]


def report_pmsynth(settings: Settings) -> dict[str, Any]:
    """Print candidate counts, confidence, and precision and recall. No writes."""
    with open_client(settings, settings.sn_incident_user, settings.sn_incident_password) as reader:
        rows = _load(reader)
        print(f"pmsynth incidents={len(rows)}")
        if not rows:
            return {"incidents": 0}
        names = _ci_names(reader, {str(row.get("cmdb_ci") or "") for row in rows})
    payload = []
    id_to_name: dict[str, str] = {}
    for row in rows:
        if not _stamp(row.get("opened_at")):
            continue
        ci_id = str(row.get("cmdb_ci") or "")
        name = names.get(ci_id, "")
        if not name:
            continue
        id_to_name[ci_id] = name
        payload.append(_detect_row(row, ci=ci_id))
    found = _fork()(payload, id_to_name)
    expected = _expected()
    predicted_cis: set[str] = set()
    predicted_numbers: set[str] = set()
    candidates = []
    for candidate in found:
        ci_id = str(candidate.get("cmdb_ci") or "")
        name = id_to_name.get(ci_id, "")
        predicted_cis.add(name)
        numbers = [str(item.get("number") or "") for item in candidate.get("incidents") or []]
        predicted_numbers.update(numbers)
        row = {
            "ci": name,
            "confidence": candidate.get("confidence"),
            "peak": candidate.get("peak_14d"),
            "count": candidate.get("incident_count"),
        }
        candidates.append(row)
        print(
            "pmsynth candidate "
            f"ci={name} confidence={row['confidence']} peak={row['peak']} count={row['count']}"
        )
    ci_precision, ci_recall = _ratio(predicted_cis, expected["cis"])
    number_precision, number_recall = _ratio(predicted_numbers, expected["numbers"])
    print(
        "pmsynth ci "
        f"precision={ci_precision:.3f} recall={ci_recall:.3f} "
        f"candidates={len(candidates)} expected={len(expected['cis'])}"
    )
    print(
        "pmsynth incidents "
        f"precision={number_precision:.3f} recall={number_recall:.3f}"
    )
    report = {
        "incidents": len(rows),
        "candidates": candidates,
        "ci_precision": round(ci_precision, 3),
        "ci_recall": round(ci_recall, 3),
        "incident_precision": round(number_precision, 3),
        "incident_recall": round(number_recall, 3),
    }
    path = repo_root() / "var" / "phase3" / "pmsynth.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _load(reader: Any) -> list[dict[str, Any]]:
    for query in (
        "correlation_idSTARTSWITHPMSYNTH",
        "short_descriptionSTARTSWITHPMSYNTH",
    ):
        try:
            rows = reader.get_records(
                "incident",
                query=query,
                fields=_FIELDS,
                page_size=200,
                max_records=500,
            )
        except ServiceNowError as exc:
            raise http_failure("pmsynth incidents", exc) from None
        if rows:
            return rows
    return []


def _expected() -> dict[str, set[str]]:
    path = repo_root().parent / "pm-agent" / "runs" / _ANSWER
    if not path.is_file():
        raise WorldError("pmsynth answer key was not readable")
    payload = json.loads(path.read_text(encoding="utf-8"))
    cis: set[str] = set()
    numbers: set[str] = set()
    for pattern in payload.get("patterns", {}).values():
        if not pattern.get("expect_problem"):
            continue
        cis.add(str(pattern.get("ci") or ""))
        numbers.update(str(number) for number in pattern.get("incidents") or [])
    cis.discard("")
    numbers.discard("")
    return {"cis": cis, "numbers": numbers}


def _ratio(predicted: set[str], expected: set[str]) -> tuple[float, float]:
    if not predicted and not expected:
        return 1.0, 1.0
    overlap = predicted & expected
    precision = len(overlap) / len(predicted) if predicted else 0.0
    recall = len(overlap) / len(expected) if expected else 0.0
    return precision, recall
