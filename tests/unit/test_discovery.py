"""Discovery report and gate, without calling the instance."""

from e2e.discover import _gate_blocked, _path_from, render_discovery


def _probe(decision: str) -> dict[str, object]:
    return {
        "question": "A probe question?",
        "calls": ["GET /api/now/table/sys_choice"],
        "evidence": {"status": 200},
        "decision": decision,
        "reason": "Recorded from the read-back.",
    }


def _evidence(**decisions: str) -> dict[str, object]:
    names = ("approval", "parent", "rfc", "states", "knowledge", "roles")
    probes = {name: _probe(decisions.get(name, "verified")) for name in names}
    return {
        "email": {"line": "glide.email.smtp.active is false and no active email account exists."},
        "dictionary": {"incident.u_caused_by": [{"internal_type": "reference"}]},
        "choices": {"incident.state": [{"value": "1", "label": "New", "inactive": "false"}]},
        "probes": probes,
    }


def test_gate_accepts_verified_and_approved_fallback() -> None:
    evidence = _evidence(
        rfc="approved-fallback",
        states="approved-fallback",
        knowledge="approved-fallback",
    )
    assert _gate_blocked(evidence) is False


def test_gate_stops_on_approval_failure_and_partial_states() -> None:
    assert _gate_blocked(_evidence(approval="failed")) is True
    assert _gate_blocked(_evidence(states="partial")) is True
    assert _gate_blocked(_evidence(parent="failed")) is True
    bare = _evidence()
    bare["choices"] = {}
    assert _gate_blocked(bare) is True


def test_path_prefers_the_next_higher_state() -> None:
    edges = [
        {"from": "101", "to": "102"},
        {"from": "102", "to": "107"},
        {"from": "102", "to": "103"},
        {"from": "103", "to": "107"},
        {"from": "103", "to": "104"},
        {"from": "104", "to": "103"},
        {"from": "104", "to": "106"},
        {"from": "106", "to": "107"},
        {"from": "107", "to": "103"},
    ]
    assert _path_from("101", edges) == ["102", "103", "104", "106", "107"]


def test_partial_state_is_not_an_approved_fallback() -> None:
    text = render_discovery(_evidence(states="partial"))
    state_line = next(line for line in text.splitlines() if "problem.state Table API" in line)
    assert "A partial walk is not the approved fallback." in state_line
    assert "approved fallback and is not installed" not in state_line


def test_render_names_the_decision_and_omits_a_host() -> None:
    text = render_discovery(_evidence())
    assert "Decision: **verified**." in text
    assert "## Section 8" in text
    assert "service-now.com" not in text
    assert "Authorization" not in text
