"""Handoff contracts. Catalog plans stay byte for byte."""

import pytest
from pydantic import ValidationError

from e2e.contracts import (
    CASE_ID,
    ChangeOutcome,
    DeploymentFailureLink,
    FixCatalogEntry,
    IncidentProblemHandoff,
    IntakeRequest,
    ProblemChangeHandoff,
    change_idempotency_key,
    intake_request_from_catalog,
    problem_idempotency_key,
    to_intake_dict,
)

_PLAN = "Restart the synthetic worker.\nConfirm the health check."
_BACKOUT = "Start the previous worker build."
_TEST = "Open one synthetic incident and confirm it stays closed."


def _entry(**overrides: object) -> FixCatalogEntry:
    body: dict[str, object] = {
        "mechanism": "disk-full",
        "ci_class": "cmdb_ci_server",
        "title": "Clear the synthetic disk",
        "implementation_plan": _PLAN,
        "backout_plan": _BACKOUT,
        "test_plan": _TEST,
        "deployment_method": "automated",
        "deployment_strategy": "canary",
    }
    body.update(overrides)
    return FixCatalogEntry(**body)  # type: ignore[arg-type]


def _mapped(**overrides: object) -> IntakeRequest:
    args: dict[str, object] = {
        "problem_number": "PRB0001001",
        "confirmed_mechanism": "disk-full",
        "linked_incident_count": 4,
        "ci_name": "syn-app-01",
        "requester": "syn.svc.problem_agent",
        "proposed_start": "2026-12-20 02:00:00",
        "proposed_end": "2026-12-20 04:00:00",
        "recurrence_rate": 0.25,
        "expected_incidents_prevented": 6,
    }
    args.update(overrides)
    return intake_request_from_catalog(_entry(), **args)  # type: ignore[arg-type]


def test_plans_are_copied_without_a_deployment_prefix() -> None:
    request = _mapped()
    assert request.implementation_plan == _PLAN
    assert request.backout_plan == _BACKOUT
    assert request.test_plan == _TEST
    assert not request.implementation_plan.startswith("Deployment method:")


def test_a_catalog_prefix_is_left_unchanged() -> None:
    entry = _entry(implementation_plan="Deployment method: AUTOMATED\n" + _PLAN)
    request = intake_request_from_catalog(
        entry,
        problem_number="PRB0001001",
        confirmed_mechanism="disk-full",
        linked_incident_count=1,
        ci_name="syn-app-01",
        requester="syn.svc.problem_agent",
        proposed_start="2026-12-20 02:00:00",
        proposed_end="2026-12-20 04:00:00",
        recurrence_rate=0.1,
        expected_incidents_prevented=1,
    )
    assert request.implementation_plan == "Deployment method: AUTOMATED\n" + _PLAN


def test_description_has_no_incident_text_parameter() -> None:
    request = _mapped()
    dumped = to_intake_dict(request)
    assert "caller said" not in request.description
    assert dumped["summary"] == "Fix for PRB0001001: Clear the synthetic disk"
    assert dumped["description"] == (
        "Problem PRB0001001. Confirmed mechanism: disk-full. Linked incidents: 4."
    )
    assert dumped["justification"] == (
        "Incidents linked: 4. Recurrence rate: 0.25. Expected incidents prevented: 6."
    )
    assert "incident" not in dumped
    assert "template" not in dumped
    assert "release" not in dumped
    assert "security_flag" not in dumped


def test_path_three_sets_incident_and_standard_sets_template() -> None:
    entry = _entry(standard_template="Add a synthetic disk volume")
    request = intake_request_from_catalog(
        entry,
        problem_number="PRB0001002",
        confirmed_mechanism="disk-full",
        linked_incident_count=2,
        ci_name="syn-app-01",
        requester="syn.svc.problem_agent",
        proposed_start="2026-12-20 02:00:00",
        proposed_end="2026-12-20 04:00:00",
        recurrence_rate=1.0,
        expected_incidents_prevented=2,
        incident_number="INC0001002",
    )
    dumped = to_intake_dict(request)
    assert dumped["incident"] == "INC0001002"
    assert dumped["template"] == "Add a synthetic disk volume"


def test_intake_rejects_release_and_security_flag() -> None:
    request = _mapped()
    with pytest.raises(ValidationError):
        IntakeRequest(**{**request.model_dump(), "release": "REL0001"})
    with pytest.raises(ValidationError):
        IntakeRequest(**{**request.model_dump(), "security_flag": True})


def test_problem_and_change_keys() -> None:
    assert problem_idempotency_key("cluster-a").startswith("SYN-E2E-PRB-")
    assert len(problem_idempotency_key("cluster-a")) == len("SYN-E2E-PRB-") + 16
    handoff = IncidentProblemHandoff(
        cluster_key="cluster-a",
        incident_sys_ids=["a" * 32],
        first_opened="2026-11-01 00:00:00",
        last_opened="2026-11-02 00:00:00",
        cohesion=1.0,
        purity=1.0,
        proposed_impact="2",
        proposed_urgency="2",
        idempotency_key=problem_idempotency_key("cluster-a"),
    )
    assert handoff.idempotency_key == problem_idempotency_key("cluster-a")
    case_id = "E2E-ab12cd34"
    assert CASE_ID.fullmatch(case_id)
    change = ProblemChangeHandoff(
        case_id=case_id,
        attempt=2,
        idempotency_key=change_idempotency_key(case_id, 2),
        request=_mapped(),
    )
    assert change.idempotency_key == "SYN-E2E-E2E-ab12cd34-CHG-2"


def test_bad_case_and_held_reason() -> None:
    with pytest.raises(ValidationError):
        ProblemChangeHandoff(
            case_id="CASE-1",
            attempt=1,
            idempotency_key="SYN-E2E-CASE-1-CHG-1",
            request=_mapped(),
        )
    with pytest.raises(ValidationError):
        ChangeOutcome(
            case_id="E2E-ab12cd34",
            change_sys_id="b" * 32,
            outcome="held",
        )
    held = ChangeOutcome(
        case_id="E2E-ab12cd34",
        change_sys_id="b" * 32,
        outcome="held",
        reason_code="high_risk_not_delegated",
    )
    assert held.reason_code == "high_risk_not_delegated"
    link = DeploymentFailureLink(
        case_id="E2E-ab12cd34",
        change_sys_id="b" * 32,
        incident_sys_id="c" * 32,
        problem_sys_id="d" * 32,
    )
    assert link.problem_sys_id == "d" * 32
