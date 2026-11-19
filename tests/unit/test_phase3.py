"""Offline Phase 3 rules. The live gate is tests/live/test_phase3.py."""

from __future__ import annotations

import pytest

from e2e.adapters.change import (
    AUTH_RESUME,
    approval_query,
    bind_change_repo,
    forget_thread_memory,
    safe_detail,
)
from e2e.case_graph import case_id_for, hold_for_change, next_fix
from e2e.contracts import change_idempotency_key, problem_idempotency_key
from e2e.data.catalog import for_mechanism_class
from e2e.data.ground_truth import problem_key
from e2e.data.world import HOLD_EMERGENCY, HOLD_FIX_FAILED, HOLD_HIGH_RISK, MARKER
from e2e.scenario_e02 import OVERLAY
from tests.helpers.decisions import accept_planted_cause


def test_the_graph_root_is_the_sibling_change_repo() -> None:
    import cm_agents.audit as audit
    import cm_agents.deploy.simulator as simulator
    import cm_agents.enablement.policy as policy
    import cm_agents.graphs.runner as runner
    import cm_agents.servicenow.changes as changes
    import cm_agents.settings as cm_settings

    from e2e.paths import repo_root

    bound = bind_change_repo()
    assert bound.name == "ChangeManagementAgent"
    assert bound != repo_root()
    assert runner.repo_root() == bound
    assert cm_settings.repo_root() == bound
    assert audit.repo_root() == bound
    assert policy.repo_root() == bound
    assert simulator.repo_root() == bound
    assert changes.repo_root() == bound
    assert (bound / "data" / "synthetic" / "fixtures.json").is_file()
    assert (bound / "config" / "policy.yaml").is_file()


def test_graph_errors_drop_local_paths() -> None:
    detail = safe_detail(
        FileNotFoundError(r"C:\Users\someone\data\synthetic\fixtures.json")
    )
    assert "Users" not in detail
    assert "someone" not in detail
    assert "fixtures.json" not in detail


def test_authorization_resume_is_not_an_empty_map() -> None:
    assert AUTH_RESUME == {"continue": "true"}
    assert AUTH_RESUME


def test_approval_query_is_the_authority_users_row() -> None:
    query = approval_query("a" * 32, "b" * 32)
    assert query == f"sysapproval={'a' * 32}^state=requested^approver={'b' * 32}"


def test_a_finished_thread_is_forgotten_without_touching_other_threads(tmp_path) -> None:
    import json
    import sqlite3

    var = tmp_path / "var"
    var.mkdir()
    own = "SYN-E2E-E2E-256ec3a2-CHG-1"
    other = "SYN-S01-ebb2c040"
    sim = var / "sim_state.json"
    sim.write_text(
        json.dumps(
            {
                "versions": {"syn-store-checkout|PROD": "keep"},
                "threads": {
                    own: {"kind": "deploy", "outcome": "verified"},
                    other: {"kind": "deploy", "outcome": "verified"},
                },
            }
        ),
        encoding="utf-8",
    )
    db = var / "checkpoints.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE checkpoints (thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT)"
        )
        conn.execute(
            "CREATE TABLE writes (thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT)"
        )
        conn.execute("INSERT INTO checkpoints VALUES (?, '', 'a')", (own,))
        conn.execute("INSERT INTO checkpoints VALUES (?, '', 'b')", (other,))
        conn.execute("INSERT INTO writes VALUES (?, '', 'a')", (own,))
        conn.execute("INSERT INTO writes VALUES (?, '', 'b')", (other,))
    forget_thread_memory(tmp_path, own)
    stored = json.loads(sim.read_text(encoding="utf-8"))
    assert own not in stored["threads"]
    assert other in stored["threads"]
    assert stored["versions"]["syn-store-checkout|PROD"] == "keep"
    with sqlite3.connect(db) as conn:
        left = [row[0] for row in conn.execute("SELECT thread_id FROM checkpoints")]
        writes = [row[0] for row in conn.execute("SELECT thread_id FROM writes")]
    assert left == [other]
    assert writes == [other]


def test_a_body_error_survives_a_delete_error() -> None:
    from e2e.errors import WorldError
    from e2e.scenarios import execute_scenario

    def body() -> None:
        raise WorldError("approval failed HTTP 403")

    def deleter(ids: list[str]) -> None:
        raise WorldError("delete affected service failed HTTP 403")

    with pytest.raises(WorldError, match="approval failed HTTP 403"):
        execute_scenario(body, [], deleter)


def test_before_the_fifth_opens_nothing() -> None:
    assert checkout_candidates(include_fifth=False) == []


def test_the_fifth_opens_one_checkout_candidate() -> None:
    found = checkout_candidates(include_fifth=True)
    assert len(found) == 1
    assert found[0]["peak_14d"] >= 5
    assert found[0]["cmdb_ci"] == "syn-store-checkout"


def test_a_failed_catalog_entry_is_not_resubmitted() -> None:
    mechanism = "connection_pool_exhausted"
    ci_class = "cmdb_ci_appl"
    assert len(for_mechanism_class(mechanism, ci_class)) == 1
    failed = {(mechanism, ci_class)}
    assert next_fix(mechanism, ci_class, failed) == HOLD_FIX_FAILED
    assert next_fix(mechanism, ci_class, set()) == ""
    assert OVERLAY.attempt_limit == 2


def test_high_risk_and_emergency_are_held() -> None:
    assert hold_for_change("emergency", "4") == HOLD_EMERGENCY
    assert hold_for_change("Emergency", "4") == HOLD_EMERGENCY
    assert hold_for_change("normal", "1") == HOLD_HIGH_RISK
    assert hold_for_change("normal", "2") == HOLD_HIGH_RISK
    assert hold_for_change("normal", "3") == ""
    assert hold_for_change("normal", "4") == ""


def test_case_id_ties_the_problem_key_to_the_thread() -> None:
    key = problem_key("syn-store-checkout", "log_rotation_stopped")
    case_id = case_id_for(key)
    thread = change_idempotency_key(case_id, 1)
    assert key.startswith(f"{MARKER}PRB-")
    assert not key.upper().startswith("SYN")
    assert thread == f"SYN-E2E-{case_id}-CHG-1"
    assert case_id[4:] == key.split("-")[-1][:8]


def test_the_helper_accepts_the_checkout_ground_truth() -> None:
    assert accept_planted_cause("log_rotation_stopped", "syn-store-checkout", scenario="E02")
    assert not accept_planted_cause("checkout_saturation", "syn-store-checkout", scenario="E02")
    assert not accept_planted_cause("log_rotation_stopped", "syn-store-web", scenario="E02")


def test_the_detected_key_is_the_ci_and_category() -> None:
    from e2e.data.fixtures import change_world
    from e2e.data.world import category_for_class

    _changes, ci_index = change_world()
    ci_class = ci_index["syn-store-checkout"]["ci_class"]
    category = category_for_class(ci_class)
    detected = problem_idempotency_key(f"syn-store-checkout|{category}")
    planted = problem_key("syn-store-checkout", "log_rotation_stopped")
    assert detected != planted
    assert detected.startswith(f"{MARKER}PRB-")
    assert case_id_for(detected)[4:] == detected.split("-")[-1][:8]


def test_cluster_signals_match_the_backtest() -> None:
    from e2e.adapters.incident import cluster_signals
    from e2e.data.backtest import run_backtest
    from e2e.data.fixtures import build_incidents

    shaped = []
    for row in build_incidents():
        if not row["history"] and row["cluster"] != "C02":
            continue
        shaped.append(
            {
                "sys_id": row["correlation_id"],
                "number": row["correlation_id"],
                "opened_at": row["opened_at"],
                "cmdb_ci": row["cmdb_ci"],
                "category": row["category"],
                "close_notes": row["notes"],
                "description": row["description"],
                "parent": row.get("parent") or "",
                "short_description": row["short_description"],
                "correlation_id": row["correlation_id"],
                "state": row["state"],
            }
        )
    names = {row["cmdb_ci"]: row["cmdb_ci"] for row in shaped}
    checkout = next(row for row in shaped if row["cmdb_ci"] == "syn-store-checkout")
    signal = cluster_signals(
        shaped,
        names,
        ci_name="syn-store-checkout",
        category=str(checkout["category"]),
    )
    expected = next(
        row for row in run_backtest()["reports"]["full"]["clusters"] if row["cluster"] == "C02"
    )
    assert signal["a"] == expected["a"] == "log_rotation_stopped"
    assert signal["b"] == expected["b"] == "log_rotation_stopped"
    assert signal["c"] == expected["c"] == "log_rotation_stopped"
    assert signal["d"] is False
    assert signal["d"] == expected["d"]
    assert signal["fired"] == expected["fired"]
    assert signal["decision"] == expected["decision"] == "confirmed"
    assert signal["mechanism"] == expected["mechanism"]


def test_runtime_modules_do_not_import_ground_truth() -> None:
    import ast
    import re
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    modules = [
        repo / "e2e" / "case_graph.py",
        repo / "e2e" / "tick.py",
        repo / "e2e" / "pmsynth.py",
        repo / "e2e" / "cli.py",
        repo / "e2e" / "scenarios.py",
        repo / "e2e" / "simulator" / "deliver.py",
        repo / "e2e" / "simulator" / "registry.py",
        repo / "e2e" / "simulator" / "resolver.py",
    ]
    modules.extend((repo / "e2e" / "adapters").glob("*.py"))
    banned_names = {"ground_truth", "CLUSTERS"}
    date = re.compile(r"\d{4}-\d{2}-\d{2}")
    named = {
        repo / "e2e" / "case_graph.py",
        repo / "e2e" / "tick.py",
        repo / "e2e" / "pmsynth.py",
        repo / "e2e" / "simulator" / "registry.py",
        repo / "e2e" / "simulator" / "resolver.py",
        repo / "e2e" / "simulator" / "deliver.py",
    }
    offenders: list[str] = []
    for path in modules:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported = {alias.name for alias in node.names}
                if "ground_truth" in module or imported & banned_names or "CLUSTERS" in module:
                    offenders.append(f"{path.name}: import")
            if isinstance(node, ast.Name) and node.id in banned_names:
                offenders.append(f"{path.name}: {node.id}")
        if path in named or path.parent.name == "adapters":
            if "syn-store-checkout" in text or re.search(r"\bE0\d\b", text) or date.search(text):
                offenders.append(f"{path.name}: scenario literal")
    assert offenders == []


def checkout_candidates(*, include_fifth: bool) -> list[dict]:
    """Offline detect on checkout rows. The fifth arrival is 2026-10-24."""
    from e2e.adapters.incident import detect_row, load_detect
    from e2e.data.fixtures import build_incidents

    ci = "syn-store-checkout"
    payload = []
    for row in build_incidents():
        if row["cmdb_ci"] != ci:
            continue
        if not include_fifth and str(row["opened_at"]) >= "2026-10-24":
            continue
        payload.append(detect_row(row, ci=ci))
    found = load_detect()(payload, {ci: ci})
    return [row for row in found if row.get("cmdb_ci") == ci]
