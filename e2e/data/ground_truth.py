"""Ground truth built from the fixtures and the offline backtest. Not a ServiceNow table."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from e2e.data.backtest import expected_outcomes, run_backtest
from e2e.data.catalog import entries
from e2e.data.fixtures import build_incidents, change_world, seeded_incidents
from e2e.data.world import (
    ANCHOR,
    CI_SPECIFIC,
    HOLD_FIX_FAILED,
    HOLD_RCA_UNCONFIRMED,
    JOB_SCHEDULE,
    KIND_MAP,
    MARKER,
    SEED,
    category_for_class,
)
from e2e.paths import ground_truth_path


def problem_key(ci: str, mechanism: str) -> str:
    _changes, ci_index = change_world()
    info = ci_index.get(ci)
    if info is None:
        raise RuntimeError(f"{ci} is not in the change-world CI index")
    category = category_for_class(info["ci_class"])
    if not category:
        raise RuntimeError(f"{ci} class {info['ci_class']} has no category")
    digest = hashlib.sha256(f"{ci}|{category}|{mechanism}".encode()).hexdigest()[:16]
    return f"{MARKER}PRB-{digest}"


def build_ground_truth() -> dict[str, Any]:
    incidents = build_incidents()
    seeded = seeded_incidents(incidents)
    backtest = run_backtest()
    problems = expected_outcomes(backtest)
    if problems:
        detail = "; ".join(problems)
        raise RuntimeError(f"offline backtest stopped the seed: {detail}")
    full = backtest["reports"]["full"]
    return {
        "seed": SEED,
        "anchor": ANCHOR,
        "marker": MARKER,
        "job_schedule": [dict(row) for row in JOB_SCHEDULE],
        "kind_map": dict(KIND_MAP),
        "ci_specific_mechanisms": sorted(CI_SPECIFIC),
        "catalog": [dict(row) for row in entries()],
        "counts": {
            "incidents_seeded": len(seeded),
            "incidents_full": len(incidents),
            "problems_seeded": 1,
            "articles_seeded": 1,
            "changes_seeded": 0,
        },
        "e01_problem": problem_key("syn-store-cdn", "log_rotation_stopped"),
        "clusters": full["clusters"],
        "candidates": full["candidates"],
        "detection_precision": full["detection_precision"],
        "true_positives": full["true_positives"],
        "false_positives": full["false_positives"],
        "history_peaks": backtest["history_peaks"],
        "thresholds": backtest["thresholds"],
        "holds": {
            "D08": HOLD_RCA_UNCONFIRMED,
            "C11": HOLD_RCA_UNCONFIRMED,
            "E05": HOLD_FIX_FAILED,
        },
    }


def write_ground_truth() -> dict[str, Any]:
    payload = build_ground_truth()
    path = ground_truth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload
