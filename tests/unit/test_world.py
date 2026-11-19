"""Fixture shape and the offline backtest the seed refuses to ignore."""

from e2e.data.backtest import expected_outcomes, run_backtest
from e2e.data.fixtures import build_incidents, change_world, seeded_incidents
from e2e.data.world import category_for_class, history_note_line


def test_seeded_world_keeps_both_decoys() -> None:
    rows = build_incidents()
    seeded = seeded_incidents(rows)
    _changes, ci_index = change_world()
    assert len(seeded) == 101
    assert sum(1 for row in seeded if row["cluster"] == "D08") == 8
    assert sum(1 for row in seeded if row["cluster"] == "D04") == 4
    assert sum(1 for row in seeded if row["parent"] == "E01") == 3
    assert all(len(row["short_description"]) <= 160 for row in seeded)
    assert all(row["business_service"] == "" for row in seeded)
    for row in rows:
        ci_class = ci_index[row["cmdb_ci"]]["ci_class"]
        assert row["category"] == category_for_class(ci_class)
    servers = [
        row for row in rows if ci_index[row["cmdb_ci"]]["ci_class"] == "cmdb_ci_linux_server"
    ]
    assert servers
    assert {row["category"] for row in servers} == {"hardware"}
    applications = [row for row in rows if ci_index[row["cmdb_ci"]]["ci_class"] == "cmdb_ci_appl"]
    assert applications
    assert {row["category"] for row in applications} == {"software"}


def test_history_note_names_the_number_and_the_correlation() -> None:
    line = history_note_line("INC0010001", "E2E-INC-C01-001")
    assert line == "E2E-HISTORY INC0010001 E2E-INC-C01-001"
    assert not line.upper().startswith("SYN")
    raised = False
    try:
        history_note_line("", "E2E-INC-C01-001")
    except ValueError:
        raised = True
    assert raised


def test_backtest_matches_the_approved_outcomes() -> None:
    result = run_backtest()
    assert expected_outcomes(result) == []
    full = result["reports"]["full"]
    assert full["incidents"] == 108
    assert len(full["candidates"]) == 10
    assert full["detection_precision"] == 0.9
