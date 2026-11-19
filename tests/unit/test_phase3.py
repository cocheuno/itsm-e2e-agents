"""Offline Phase 3 rules. The live gate is tests/live/test_phase3.py."""

from __future__ import annotations

import pytest

from e2e.contracts import change_idempotency_key
from e2e.data.catalog import for_mechanism_class
from e2e.data.ground_truth import problem_key
from e2e.data.world import HOLD_EMERGENCY, HOLD_FIX_FAILED, HOLD_HIGH_RISK, MARKER
from e2e.phase3_e02 import (
    POLICY_LIMIT,
    accept_mechanism,
    case_id_for,
    checkout_candidates,
    hold_for_change,
    next_fix,
)


def test_the_graph_root_is_the_sibling_change_repo() -> None:
    import cm_agents.audit as audit
    import cm_agents.deploy.simulator as simulator
    import cm_agents.enablement.policy as policy
    import cm_agents.graphs.runner as runner
    import cm_agents.servicenow.changes as changes
    import cm_agents.settings as cm_settings

    from e2e.paths import repo_root
    from e2e.phase3_e02 import _bind_change_repo

    bound = _bind_change_repo()
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
    from e2e.phase3_e02 import _safe_detail

    detail = _safe_detail(
        FileNotFoundError(r"C:\Users\someone\data\synthetic\fixtures.json")
    )
    assert "Users" not in detail
    assert "someone" not in detail
    assert "fixtures.json" not in detail


def test_authorization_resume_is_not_an_empty_map() -> None:
    from e2e.phase3_e02 import AUTH_RESUME

    assert AUTH_RESUME == {"continue": "true"}
    assert AUTH_RESUME


def test_approval_query_is_the_authority_users_row() -> None:
    from e2e.phase3_e02 import approval_query

    query = approval_query("a" * 32, "b" * 32)
    assert query == f"sysapproval={'a' * 32}^state=requested^approver={'b' * 32}"


def test_a_finished_thread_is_forgotten_without_touching_other_threads(tmp_path) -> None:
    import json
    import sqlite3

    from e2e.phase3_e02 import forget_thread_memory

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
    assert POLICY_LIMIT == 2


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
    assert accept_mechanism("log_rotation_stopped", "syn-store-checkout")
    assert not accept_mechanism("checkout_saturation", "syn-store-checkout")
    assert not accept_mechanism("log_rotation_stopped", "syn-store-web")
