"""Fixture shape and the offline backtest the seed refuses to ignore."""

from e2e.data.backtest import expected_outcomes, run_backtest
from e2e.data.fixtures import build_incidents, seeded_incidents


def test_seeded_world_keeps_both_decoys() -> None:
    rows = build_incidents()
    seeded = seeded_incidents(rows)
    assert len(seeded) == 101
    assert sum(1 for row in seeded if row["cluster"] == "D08") == 8
    assert sum(1 for row in seeded if row["cluster"] == "D04") == 4
    assert sum(1 for row in seeded if row["parent"] == "E01") == 3
    assert all(len(row["short_description"]) <= 160 for row in seeded)
    assert all(row["category"] == "software" for row in seeded)
    assert all(row["business_service"] == "" for row in seeded)


def test_backtest_matches_the_approved_outcomes() -> None:
    result = run_backtest()
    assert expected_outcomes(result) == []
    full = result["reports"]["full"]
    assert full["incidents"] == 108
    assert len(full["candidates"]) == 10
    assert full["detection_precision"] == 0.9
