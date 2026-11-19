"""E02. Arrivals, the policy overlay, the Phase 3 helper, and the assertions.

The case graph does the work. This module is the only place that names the
scenario, the CI, and the requested window.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from cm_agents.clock import pin
from cm_agents.data.import_time import parse_utc
from cm_agents.servicenow.client import ServiceNowError

from e2e.case_graph import Hooks, PolicyOverlay, clear_hooks, configure, last_result
from e2e.counts import ARTICLES, CHANGES, INCIDENTS, PROBLEMS, format_counts, snapshot
from e2e.data.backtest import run_backtest
from e2e.data.fixtures import build_incidents
from e2e.data.world import MARKER
from e2e.errors import WorldError
from e2e.guard import assert_run_quiet, deployment_incident_ids, latest_incident_stamp
from e2e.instance import http_failure, open_client
from e2e.paths import repo_root
from e2e.scenario_records import delete_scenario_threads, delete_unkept
from e2e.settings import Settings
from e2e.simulator.deliver import delete_staging, deliver_arrivals
from e2e.simulator.registry import clear as clear_delivered
from e2e.state_api import endpoint_base
from e2e.tick import run_tick, run_until_idle

CI = "syn-store-checkout"
SEEDED = {"incidents": 101, "problems": 1, "articles": 1, "changes": 0}
OVERLAY = PolicyOverlay(
    verify_days=14,
    attempt_limit=2,
    proposed_start="2026-11-11 01:00:00",
    proposed_end="2026-11-11 03:00:00",
    requested_at="2026-10-29 16:00:00",
    clock="",
    requester="SYN Service Desk",
)
_TABLES = (
    ("incident", INCIDENTS),
    ("problem", PROBLEMS),
    ("kb_knowledge", ARTICLES),
    ("kb_template_known_error_article", ARTICLES),
    ("change_request", CHANGES),
)


def run(settings: Settings, threads: list[str]) -> None:
    """Start from the seeded world, prove detection, then remove this case's rows."""
    clear_hooks()
    clear_delivered()
    keep: dict[str, set[str]] | None = None
    correlations: list[str] = []
    caught: BaseException | None = None
    try:
        _require_seeded(settings, "before")
        keep = _snapshot(settings)
        _execute(settings, threads, correlations)
    except BaseException as exc:
        caught = exc
    try:
        if keep is not None:
            _cleanup(settings, threads, keep, correlations)
            _require_seeded(settings, "after")
    except BaseException as exc:
        if caught is None:
            caught = exc
        elif isinstance(exc, WorldError):
            print(f"scenario cleanup failed {exc}")
        else:
            print(f"scenario cleanup failed {type(exc).__name__}")
    finally:
        pin(None)
        clear_hooks()
        clear_delivered()
    if caught is not None:
        raise caught


def _execute(settings: Settings, threads: list[str], correlations: list[str]) -> None:
    arrivals = _arrivals()
    correlations.extend(str(row["correlation_id"]) for row in arrivals)
    history = _history_count()
    stamp = _stamp(settings)
    base_uri = _base_uri(settings)
    fourth = arrivals[3]
    fifth = arrivals[4]
    deliver_arrivals(settings, arrivals[:4])
    pin(parse_utc(str(fourth["opened_at"])))
    run_tick(settings)
    early, problems = _checkout_problems(settings)
    print(f"E02 before fifth checkout_problems={early} problems={problems}")
    if early != 0 or problems != SEEDED["problems"]:
        raise WorldError(
            f"a checkout problem opened before the fifth arrival "
            f"checkout={early} problems={problems}"
        )
    deliver_arrivals(settings, arrivals[4:])
    pin(parse_utc(str(fifth["opened_at"])))
    run_tick(settings)
    late, problems = _checkout_problems(settings)
    print(f"E02 after fifth checkout_problems={late} problems={problems}")
    if late != 1 or problems != SEEDED["problems"] + 1:
        raise WorldError(
            f"checkout problems after the fifth={late} problems={problems}"
        )
    overlay = PolicyOverlay(
        verify_days=OVERLAY.verify_days,
        attempt_limit=OVERLAY.attempt_limit,
        proposed_start=OVERLAY.proposed_start,
        proposed_end=OVERLAY.proposed_end,
        requested_at=OVERLAY.requested_at,
        clock=str(fifth["opened_at"]),
        requester=OVERLAY.requester,
    )
    configure(
        Hooks(
            accept_cause=_accept,
            overlay=overlay,
            base_uri=base_uri,
            threads=threads,
            check_signals=_check_signals,
        )
    )
    run_until_idle(settings)
    result = last_result()
    _assert_result(result, linked=len(arrivals), history=history)
    _assert_times(settings, arrivals, str(result["problem_correlation"]))
    allowed = _arrival_ids(settings, correlations)
    with open_client(settings, settings.sn_incident_user, settings.sn_incident_password) as reader:
        allowed.update(deployment_incident_ids(reader, set(threads)))
        outside = assert_run_quiet(reader, stamp, allowed)
    print(f"E02 guard={outside}")
    print(
        "E02 problem="
        f"{result['problem_number']} article={result['article_number']} "
        f"recurrence={result['recurrence']} linked={result['linked']} "
        f"history={result['history']} confidence={result['confidence']} peak={result['peak']}"
    )
    _write_proof(result)


def _accept(proposed: str, ci: str) -> bool:
    root = str(repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    from tests.helpers.decisions import accept_planted_cause

    return accept_planted_cause(proposed, ci, scenario="E02")


def _check_signals(signal: dict[str, Any]) -> None:
    expected = _backtest_row()
    keys = ("a", "b", "c", "d", "fired", "decision", "mechanism")
    live = {key: signal[key] for key in keys}
    wanted = {key: expected[key] for key in keys}
    if live != wanted:
        raise WorldError(
            "live signals differ from the backtest "
            f"{_signal_text(live)} backtest {_signal_text(wanted)}"
        )
    print("E02 signals match the backtest")


def _assert_result(result: dict[str, Any], *, linked: int, history: int) -> None:
    expected = _backtest_row()
    if result.get("confidence") != "High" or result.get("peak") != expected["peak"]:
        raise WorldError(
            f"confidence={result.get('confidence')} peak={result.get('peak')} "
            f"backtest peak={expected['peak']}"
        )
    if result.get("linked") != linked or result.get("history") != history:
        raise WorldError(
            f"linked={result.get('linked')} history={result.get('history')} "
            f"expected {linked} and {history}"
        )
    if not result.get("plans_match") or not result.get("rfc_set"):
        raise WorldError("plans or rfc were not read back while the change existed")
    if result.get("problem_state") != "107":
        raise WorldError(f"problem_state={result.get('problem_state')}")
    if result.get("recurrence") != 0:
        raise WorldError(f"recurrence={result.get('recurrence')}")
    if not result.get("article_number") or not result.get("problem_number"):
        raise WorldError("article or problem number was empty")


def _assert_times(settings: Settings, arrivals: list[dict[str, Any]], key: str) -> None:
    with open_client(settings, settings.sn_incident_user, settings.sn_incident_password) as reader:
        problem_id = _problem_id(reader, key)
        for row in arrivals:
            correlation = str(row["correlation_id"])
            stored = _one_incident(reader, correlation)
            opened = str(stored.get("opened_at") or "")[:19]
            expected = str(row["opened_at"])[:19]
            if opened != expected:
                raise WorldError(f"stored opened_at {opened or 'empty'} expected {expected}")
            parent = stored.get("parent")
            parent_id = parent.get("value") if isinstance(parent, dict) else str(parent or "")
            if parent_id != problem_id:
                raise WorldError("arrival parent was not the checkout problem")


def _arrivals() -> list[dict[str, Any]]:
    rows = [
        row
        for row in build_incidents()
        if row["scenario"] == "E02" and not row["history"] and row["cmdb_ci"] == CI
    ]
    rows.sort(key=lambda row: (str(row["opened_at"]), str(row["correlation_id"])))
    if len(rows) != 5:
        raise WorldError(f"E02 arrivals={len(rows)} expected 5")
    return rows


def _history_count() -> int:
    found = [
        row
        for row in build_incidents()
        if row["scenario"] == "E02" and row["history"] and row["cmdb_ci"] == CI
    ]
    if len(found) != 3:
        raise WorldError(f"E02 history={len(found)} expected 3")
    return len(found)


def _backtest_row() -> dict[str, Any]:
    clusters = run_backtest()["reports"]["full"]["clusters"]
    found = [row for row in clusters if row["cluster"] == "C02"]
    if len(found) != 1:
        raise WorldError("backtest C02 row was not singular")
    return found[0]


def _signal_text(row: dict[str, Any]) -> str:
    fired = ",".join(row["fired"]) if row["fired"] else "-"
    return (
        f"a={row['a'] or '-'} b={row['b'] or '-'} c={row['c'] or '-'} "
        f"d={row['d']} fired={fired} decision={row['decision']} {row['mechanism']}"
    )


def _require_seeded(settings: Settings, when: str) -> None:
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        counts = snapshot(admin)
    for key, value in SEEDED.items():
        if counts[key] != value:
            raise WorldError(f"seeded state required {when} {format_counts(counts)}")
    print(f"E02 {when} {format_counts(counts)}")


def _snapshot(settings: Settings) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        for table, query in _TABLES:
            found[f"{table}:{query}"] = _ids(admin, table, query)
    return found


def _cleanup(
    settings: Settings,
    threads: list[str],
    keep: dict[str, set[str]],
    correlations: list[str],
) -> None:
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        if threads:
            delete_scenario_threads(admin, list(threads))
        for table, query in (
            ("change_request", CHANGES),
            ("incident", INCIDENTS),
            ("kb_knowledge", ARTICLES),
            ("kb_template_known_error_article", ARTICLES),
            ("problem", PROBLEMS),
        ):
            delete_unkept(admin, table, query, keep[f"{table}:{query}"])
    delete_staging(settings, correlations)


def _checkout_problems(settings: Settings) -> tuple[int, int]:
    with open_client(settings, settings.sn_incident_user, settings.sn_incident_password) as reader:
        ci_id = _ci_id(reader)
        try:
            rows = reader.get_records(
                "problem",
                query=f"correlation_idSTARTSWITH{MARKER}PRB^cmdb_ci={ci_id}",
                fields=["sys_id"],
                page_size=20,
                max_records=20,
            )
        except ServiceNowError as exc:
            raise http_failure("checkout problems", exc) from None
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        totals = snapshot(admin)["problems"]
    return len(rows), int(totals or 0)


def _ci_id(reader: Any) -> str:
    try:
        rows = reader.get_table("cmdb_ci", query=f"name={CI}", fields=["sys_id"], limit=2)
    except ServiceNowError as exc:
        raise http_failure("checkout CI", exc) from None
    if len(rows) != 1 or len(str(rows[0].get("sys_id") or "")) != 32:
        raise WorldError(f"checkout CI rows={len(rows)}")
    return str(rows[0]["sys_id"])


def _base_uri(settings: Settings) -> str:
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        base = endpoint_base(admin)
    if not base:
        raise WorldError("problem endpoint was not installed")
    return base


def _stamp(settings: Settings) -> str:
    with open_client(settings, settings.sn_incident_user, settings.sn_incident_password) as reader:
        return latest_incident_stamp(reader)


def _problem_id(reader: Any, key: str) -> str:
    try:
        rows = reader.get_table(
            "problem",
            query=f"correlation_id={key}",
            fields=["sys_id"],
            limit=2,
        )
    except ServiceNowError as exc:
        raise http_failure("problem", exc) from None
    if len(rows) != 1:
        raise WorldError(f"problems for the case={len(rows)}")
    return str(rows[0].get("sys_id") or "")


def _one_incident(reader: Any, correlation: str) -> dict[str, Any]:
    try:
        rows = reader.get_table(
            "incident",
            query=f"correlation_id={correlation}",
            fields=["opened_at", "parent"],
            limit=2,
        )
    except ServiceNowError as exc:
        raise http_failure("arrival", exc) from None
    if len(rows) != 1:
        raise WorldError(f"arrivals stored={len(rows)} expected 1")
    return rows[0]


def _arrival_ids(settings: Settings, correlations: list[str]) -> set[str]:
    if not correlations:
        return set()
    with open_client(settings, settings.sn_incident_user, settings.sn_incident_password) as reader:
        try:
            rows = reader.get_records(
                "incident",
                query="correlation_idIN" + ",".join(correlations),
                fields=["sys_id"],
                page_size=20,
                max_records=20,
            )
        except ServiceNowError as exc:
            raise http_failure("arrival ids", exc) from None
    return {str(row.get("sys_id") or "") for row in rows if row.get("sys_id")}


def _ids(admin: Any, table: str, query: str) -> set[str]:
    try:
        rows = admin.get_records(
            table,
            query=query,
            fields=["sys_id"],
            page_size=200,
            max_records=500,
        )
    except ServiceNowError as exc:
        if exc.status_code == 404:
            return set()
        raise http_failure(f"query {table}", exc) from None
    return {str(row.get("sys_id") or "") for row in rows if row.get("sys_id")}


def _write_proof(result: dict[str, Any]) -> None:
    folder = repo_root() / "var" / "phase3"
    folder.mkdir(parents=True, exist_ok=True)
    kept = {
        "signals": result.get("signals"),
        "confidence": result.get("confidence"),
        "peak": result.get("peak"),
        "linked": result.get("linked"),
        "history": result.get("history"),
        "recurrence": result.get("recurrence"),
        "problem_number": result.get("problem_number"),
        "article_number": result.get("article_number"),
        "problem_correlation": result.get("problem_correlation"),
        "case_id": result.get("case_id"),
        "problem_state": result.get("problem_state"),
        "plans_match": result.get("plans_match"),
        "rfc_set": result.get("rfc_set"),
        "start_date": result.get("start_date"),
        "end_date": result.get("end_date"),
        "llm": result.get("llm"),
        "graph": result.get("graph"),
        "clue_share": result.get("clue_share"),
        "rca_method": result.get("rca_method"),
        "last_business_day": result.get("last_business_day"),
        "proposed": result.get("proposed"),
    }
    (folder / "proof.json").write_text(json.dumps(kept, indent=2), encoding="utf-8")
