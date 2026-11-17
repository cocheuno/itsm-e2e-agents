"""Offline backtest. Imports the fork's detect() and does not change its thresholds."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

from e2e.data.fixtures import build_incidents, change_world, detection_population
from e2e.data.signals import parse_opened, signals_for
from e2e.data.world import ANCHOR, JOB_SCHEDULE


def _load_detect():
    """Import the fork. detect() does not call ServiceNow. Stub a missing dotenv."""
    import types

    if "dotenv" not in sys.modules:
        try:
            import dotenv  # noqa: F401
        except ModuleNotFoundError:
            stub = types.ModuleType("dotenv")
            stub.load_dotenv = lambda *args, **kwargs: False  # type: ignore[attr-defined]
            sys.modules["dotenv"] = stub
    fork = Path(__file__).resolve().parents[2].parent / "pm-agent-e2e"
    if not fork.is_dir():
        raise RuntimeError(f"pm-agent-e2e is not at {fork}")
    path = str(fork)
    if path not in sys.path:
        sys.path.insert(0, path)
    from detection_agent import detect, max_in_window

    import config

    return config, detect, max_in_window


def run_backtest() -> dict[str, Any]:
    """Score the full world, the history, and the four-of-five arrival cut."""
    config, detect, max_in_window = _load_detect()
    incidents = build_incidents()
    changes, ci_index = change_world(ANCHOR)
    slices = {
        "history": detection_population(incidents, history_only=True),
        "four_of_five": detection_population(incidents, partial_arrivals=True),
        "full": detection_population(incidents),
    }
    reports = {}
    for label, population in slices.items():
        reports[label] = _score(label, population, incidents, changes, ci_index, detect)
    history_peaks = {}
    for cluster in ("C02", "C07"):
        times = [
            parse_opened(row["opened_at"])
            for row in incidents
            if row["cluster"] == cluster and row["history"]
        ]
        history_peaks[cluster] = {
            "n": len(times),
            "peak": max_in_window(times, config.DETECT_WINDOW_DAYS),
        }
    return {
        "thresholds": {
            "min": config.DETECT_MIN_INCIDENTS,
            "window": config.DETECT_WINDOW_DAYS,
            "cohesion_high": config.CONF_HIGH_COHESION,
            "cohesion_medium": config.CONF_MEDIUM_COHESION,
            "purity_high": config.CONF_HIGH_PURITY,
            "method": config.DETECT_METHOD,
        },
        "reports": reports,
        "history_peaks": history_peaks,
        "incident_count": len(incidents),
        "seeded_count": sum(1 for row in incidents if row["history"]),
    }


def _score(label, population, incidents, changes, ci_index, detect) -> dict[str, Any]:
    payload = []
    for row in population:
        payload.append(
            {
                "sys_id": row["sys_id"],
                "number": row["correlation_id"],
                "short_description": row["short_description"],
                "opened_at": row["opened_at"],
                "cmdb_ci": row["cmdb_ci"],
                "business_service": "",
                "category": row["category"],
                "subcategory": "",
                "priority": row["priority"],
                "caller_id": row["caller_id"],
                "assignment_group": row["assignment_group"],
                "state": row["state"],
            }
        )
    names = {row["cmdb_ci"]: row["cmdb_ci"] for row in payload}
    found = detect(payload, names)
    by_id = {row["sys_id"]: row for row in population}
    candidates = []
    for candidate in found:
        groups: Counter[str] = Counter()
        for incident in candidate["incidents"]:
            groups[by_id[incident["sys_id"]]["cluster"]] += 1
        candidates.append(
            {
                "id": candidate["id"],
                "ci": candidate.get("cmdb_ci") or "",
                "confidence": candidate["confidence"],
                "cohesion": candidate["cohesion"],
                "purity": candidate["purity"],
                "peak": candidate["peak_14d"],
                "count": candidate["incident_count"],
                "groups": dict(groups),
            }
        )
    clusters = sorted({row["cluster"] for row in population})
    rows = []
    for cluster in clusters:
        planted = [row for row in population if row["cluster"] == cluster]
        planted_ids = {row["sys_id"] for row in planted}
        best = None
        overlap: set[str] = set()
        for candidate in found:
            ids = {incident["sys_id"] for incident in candidate["incidents"]}
            shared = planted_ids & ids
            if len(shared) > len(overlap):
                best = candidate
                overlap = shared
        recall = len(overlap) / len(planted_ids) if planted_ids else 0.0
        counted = best["incident_count"] if best else 0
        precision = len(overlap) / counted if counted else 0.0
        confidence = best["confidence"] if best and overlap else "none"
        present_ids = {row["sys_id"] for row in population}
        signal_members = [
            row for row in incidents if row["cluster"] == cluster and row["sys_id"] in present_ids
        ]
        voted = signals_for(signal_members, population, changes, JOB_SCHEDULE, ci_index)
        rows.append(
            {
                "cluster": cluster,
                "ci": planted[0]["cmdb_ci"] if planted else "",
                "confidence": confidence,
                "recall": round(recall, 2),
                "precision": round(precision, 2),
                "opens_problem": confidence == "High",
                "cohesion": best["cohesion"] if best and overlap else None,
                "purity": best["purity"] if best and overlap else None,
                "peak": best["peak_14d"] if best and overlap else 0,
                "count": best["incident_count"] if best and overlap else 0,
                "a": voted["a"],
                "b": voted["b"],
                "c": voted["c"],
                "d": voted["d"],
                "decision": voted["decision"],
                "mechanism": voted["mechanism"],
                "fired": voted["fired"],
            }
        )
    high = [row for row in rows if row["opens_problem"]]
    true_positive = [
        row
        for row in high
        if row["cluster"] not in {"D08", "D04"} and not str(row["cluster"]).startswith("noise")
    ]
    false_positive = [row for row in high if row["cluster"] == "D08"]
    precision = len(true_positive) / len(high) if high else 0.0
    return {
        "label": label,
        "incidents": len(population),
        "candidates": candidates,
        "clusters": rows,
        "detection_precision": round(precision, 4),
        "true_positives": [row["cluster"] for row in true_positive],
        "false_positives": [row["cluster"] for row in false_positive],
    }


def format_report(result: dict[str, Any]) -> str:
    rendered = " ".join(f"{key}={value}" for key, value in result["thresholds"].items())
    lines = [f"thresholds {rendered}"]
    for label in ("history", "four_of_five", "full"):
        report = result["reports"][label]
        lines.append(
            f"== {label} incidents={report['incidents']} candidates={len(report['candidates'])} "
            f"detection_precision={report['detection_precision']} =="
        )
        for candidate in report["candidates"]:
            lines.append(
                "candidate {id} ci={ci} confidence={confidence} cohesion={cohesion} "
                "purity={purity} peak={peak} count={count} groups={groups}".format(**candidate)
            )
        for row in report["clusters"]:
            lines.append(
                f"{row['cluster']} ci={row['ci']} confidence={row['confidence']} "
                f"recall={row['recall']:.2f} precision={row['precision']:.2f} "
                f"opens_problem={row['opens_problem']} "
                f"signals a={row['a'] or '-'} b={row['b'] or '-'} c={row['c'] or '-'} "
                f"d={row['d']} fired={','.join(row['fired']) or '-'} "
                f"decision={row['decision']} {row['mechanism']}"
            )
    for cluster, peak in result["history_peaks"].items():
        lines.append(f"{cluster} history_peak {peak['peak']} n {peak['n']}")
    return "\n".join(lines)


def expected_outcomes(result: dict[str, Any]) -> list[str]:
    """Empty when the full world matches the approved confirmations. Otherwise the misses."""
    full = {row["cluster"]: row for row in result["reports"]["full"]["clusters"]}
    history = {row["cluster"]: row for row in result["reports"]["history"]["clusters"]}
    partial = {row["cluster"]: row for row in result["reports"]["four_of_five"]["clusters"]}
    problems: list[str] = []
    confirmed = ("C02", "C04", "C05", "C06", "C07", "C12a", "C12b", "C12c")
    for cluster in confirmed:
        row = full.get(cluster)
        if row is None or row["decision"] != "confirmed" or not row["opens_problem"]:
            seen = None if row is None else (row["decision"], row["opens_problem"])
            problems.append(f"{cluster} full outcome {seen}")
    c11 = full.get("C11")
    if c11 is None or c11["decision"] != "unconfirmed" or not c11["opens_problem"]:
        problems.append(f"C11 full outcome {c11}")
    decoy = full.get("D08")
    decoy_bad = (
        decoy is None
        or not decoy["opens_problem"]
        or decoy["decision"] != "unconfirmed"
        or decoy["fired"]
    )
    if decoy_bad:
        problems.append(f"D08 full outcome {decoy}")
    burst = full.get("D04")
    if burst is None or burst["opens_problem"] or burst["confidence"] != "none":
        problems.append(f"D04 full outcome {burst}")
    for cluster in ("C02", "C07"):
        if history.get(cluster, {}).get("opens_problem"):
            problems.append(f"{cluster} history opened a problem")
        if partial.get(cluster, {}).get("opens_problem"):
            problems.append(f"{cluster} four-of-five opened a problem")
        peak = result["history_peaks"][cluster]
        if peak["peak"] != 2 or peak["n"] != 3:
            problems.append(f"{cluster} history peak {peak}")
    for row in full.values():
        if str(row["cluster"]).startswith("noise") and row["opens_problem"]:
            problems.append(f"{row['cluster']} noise opened a problem")
    thresholds = result["thresholds"]
    threshold_changed = (
        thresholds["min"] != 5
        or thresholds["cohesion_high"] != 0.3
        or thresholds["method"] != "centroid"
    )
    if threshold_changed:
        problems.append(f"thresholds changed {thresholds}")
    return problems


def main() -> int:
    result = run_backtest()
    print(format_report(result))
    problems = expected_outcomes(result)
    if problems:
        print("STOP")
        for problem in problems:
            print(problem)
        return 1
    print("outcomes match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
