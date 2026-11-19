"""Persistent rows use E2E-. A cm_agents thread id stays SYN-E2E-<case>-CHG-<attempt>."""

from __future__ import annotations

import hashlib

from e2e.contracts import change_idempotency_key, problem_idempotency_key
from e2e.counts import ARTICLES, CHANGES, INCIDENTS, PROBLEMS
from e2e.data.ground_truth import problem_key
from e2e.data.world import HISTORY_NOTE, MARKER, history_note_line
from e2e.errors import WorldError
from e2e.scenario_records import _CHANGE_CHILDREN, THREAD_ID, require_thread_id, thread_query
from e2e.state_api import ARTICLE_TAG, PROBLEM_TAG, move_script, publish_script
from e2e.teardown import LEGACY_INCIDENTS, LEGACY_PROBLEMS


def test_persistent_marker_does_not_start_with_syn() -> None:
    assert MARKER == "E2E-"
    assert HISTORY_NOTE == "E2E-HISTORY"
    assert not MARKER.upper().startswith("SYN")
    assert not HISTORY_NOTE.upper().startswith("SYN")
    assert PROBLEM_TAG == "E2E-"
    assert ARTICLE_TAG == "E2E-"
    assert "SYN-E2E-" not in move_script()
    assert "SYN-E2E-" not in publish_script()


def test_problem_digest_is_unchanged_when_the_prefix_changes() -> None:
    digest = hashlib.sha256(b"syn-store-cdn|software|log_rotation_stopped").hexdigest()[:16]
    assert digest == "841def279ed25e56"
    assert problem_key("syn-store-cdn", "log_rotation_stopped") == f"E2E-PRB-{digest}"
    assert problem_idempotency_key("syn-store-cdn|software|log_rotation_stopped") == (
        f"E2E-PRB-{digest}"
    )


def test_change_thread_id_keeps_the_syn_prefix() -> None:
    thread_id = change_idempotency_key("E2E-ab12cd34", 2)
    assert thread_id == "SYN-E2E-E2E-ab12cd34-CHG-2"
    assert THREAD_ID.fullmatch(thread_id)
    assert thread_query(thread_id) == f"correlation_id={thread_id}"
    line = history_note_line("INC0010001", "E2E-INC-C01-001")
    assert thread_id not in line
    assert "SYN" not in line


def test_scenario_delete_does_not_delete_task_ci_directly() -> None:
    tables = [table for table, _query, _name in _CHANGE_CHILDREN]
    assert "task_ci" not in tables
    assert "change_request" not in tables
    assert "sysapproval_approver" in tables


def test_thread_id_rejects_seed_prefixes_and_persistent_ids() -> None:
    refused = (
        "SYN-CHG-0108",
        "SYN-OPEN-0001",
        "SYN-REL-0001",
        "SYN-INC-0001",
        "syn-inc-0001",
        "E2E-INC-C01-001",
        "E2E-PRB-841def279ed25e56",
        "SYN-E2E-INC-C01-001",
        "SYN-E2E-PRB-841def279ed25e56",
        "SYN-E2E-PROBE",
        "SYN-" + "ab" * 6,
    )
    for thread_id in refused:
        try:
            require_thread_id(thread_id)
        except WorldError:
            continue
        raise AssertionError(thread_id)


def test_counts_split_persistent_rows_from_thread_ids() -> None:
    assert INCIDENTS == "correlation_idSTARTSWITHE2E-INC"
    assert PROBLEMS == "correlation_idSTARTSWITHE2E-PRB"
    assert ARTICLES == "short_descriptionSTARTSWITHE2E-"
    assert "SYN" not in INCIDENTS
    assert "SYN" not in PROBLEMS
    assert "SYN" not in ARTICLES
    assert CHANGES.startswith("correlation_idSTARTSWITHSYN-E2E-")
    assert "SYN-CHG-" not in LEGACY_INCIDENTS
    assert "SYN-INC-" not in LEGACY_INCIDENTS
    assert "CHG-" not in LEGACY_INCIDENTS
    assert "CHG-" not in LEGACY_PROBLEMS
