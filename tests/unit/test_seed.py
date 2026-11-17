"""History payload and the reimport decision. No instance calls."""

from e2e.seed import _needs_reimport, _next_settle, _payload


def test_history_payload_resolves_incident_state_and_sets_parent_only_for_e01() -> None:
    row = {
        "opened_at": "2026-10-06 15:00:00",
        "short_description": "SYN-E2E- checkout logs stopped",
        "description": "The checkout log directory filled.",
        "close_notes": "Cleared at the next window.",
        "cmdb_ci": "syn-store-checkout",
        "correlation_id": "SYN-E2E-INC-C02-001",
        "parent": "",
        "category": "software",
    }
    payload = _payload(
        row,
        cis={"syn-store-checkout": "a" * 32},
        group_id="b" * 32,
        caller="c" * 32,
        problem_id="d" * 32,
    )
    assert payload["u_state"] == "6"
    assert payload["u_incident_state"] == "6"
    assert payload["u_active"] == "false"
    assert payload["u_category"] == "software"
    assert "u_parent" not in payload
    assert "u_closed_at" not in payload
    row["category"] = "hardware"
    hardware = _payload(
        row,
        cis={"syn-store-checkout": "a" * 32},
        group_id="b" * 32,
        caller="c" * 32,
        problem_id="d" * 32,
    )
    assert hardware["u_category"] == "hardware"
    row["category"] = "software"

    row["parent"] = "E01"
    linked = _payload(
        row,
        cis={"syn-store-checkout": "a" * 32},
        group_id="b" * 32,
        caller="c" * 32,
        problem_id="d" * 32,
    )
    assert linked["u_parent"] == "d" * 32


def test_settle_waits_until_the_active_count_stays_still() -> None:
    count, stable, done = _next_settle(None, 6, 0)
    assert (count, stable, done) == (6, 0, False)
    count, stable, done = _next_settle(6, 6, 0)
    assert (count, stable, done) == (6, 15, False)
    count, stable, done = _next_settle(6, 6, 15)
    assert (count, stable, done) == (6, 30, False)
    count, stable, done = _next_settle(6, 6, 30)
    assert (count, stable, done) == (6, 45, True)
    count, stable, done = _next_settle(6, 10, 30)
    assert (count, stable, done) == (10, 0, False)


def test_reimport_is_only_for_active_or_new_incident_state() -> None:
    assert _needs_reimport(None) is False
    assert _needs_reimport({"active": "false", "incident_state": "6"}) is False
    assert _needs_reimport({"active": "0", "incident_state": "6"}) is False
    assert _needs_reimport({"active": "true", "incident_state": "6"}) is True
    assert _needs_reimport({"active": "false", "incident_state": "1"}) is True
