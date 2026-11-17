"""Phase 2 decisions that do not touch the instance."""

from datetime import datetime

from cm_agents.data.import_time import UTC

from e2e.data.arrivals import due_arrivals, e01_arrival
from e2e.data.fixtures import build_incidents, seeded_incidents
from e2e.simulator.resolver import outcome_for


def test_e01_arrival_stays_out_of_the_seed_and_the_backtest_population():
    arrival = e01_arrival()
    correlations = {row["correlation_id"] for row in build_incidents()}
    assert arrival["correlation_id"] not in correlations
    assert len(seeded_incidents()) == 101


def test_the_pinned_clock_delivers_five_e02_arrivals_and_e01():
    moment = datetime(2026, 10, 24, 16, 0, tzinfo=UTC)
    rows = due_arrivals(moment)
    assert sum(row["scenario"] == "E02" for row in rows) == 5
    assert sum(row["scenario"] == "E01" for row in rows) == 1
    early = due_arrivals(datetime(2026, 10, 20, 9, 0, tzinfo=UTC))
    assert early == []
    one = due_arrivals(datetime(2026, 10, 20, 16, 0, tzinfo=UTC))
    assert [row["scenario"] for row in one] == ["E02"]


def test_the_resolver_resolves_and_does_not_hold():
    row = next(
        item for item in build_incidents() if item["scenario"] == "E02" and not item["history"]
    )
    outcome = outcome_for(row)
    assert outcome["state"] == "6"
    assert outcome["close_code"] == "Solution provided"
    assert "hold_reason" not in outcome
    assert outcome["close_notes"]
