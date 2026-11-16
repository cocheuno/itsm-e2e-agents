"""Handoff contracts. The LLM does not fill these. Code does."""

from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION: Literal["1"] = "1"
CASE_ID = re.compile(r"^E2E-[0-9a-f]{8}$")
DeploymentMethod = Literal["automated", "manual"]
DeploymentStrategy = Literal[
    "canary",
    "blue/green",
    "blue_green",
    "rolling",
    "big bang",
    "big_bang",
]


class IncidentProblemHandoff(BaseModel):
    """Detection output. Incident text is not a field on this contract."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = CONTRACT_VERSION
    cluster_key: str = Field(min_length=1)
    incident_sys_ids: list[str] = Field(min_length=1)
    first_opened: str
    last_opened: str
    cohesion: float
    purity: float
    proposed_impact: str
    proposed_urgency: str
    major_incident: bool = False
    idempotency_key: str

    @model_validator(mode="after")
    def _key_matches_cluster(self) -> IncidentProblemHandoff:
        expected = problem_idempotency_key(self.cluster_key)
        if self.idempotency_key != expected:
            raise ValueError("idempotency_key does not match the cluster key")
        return self


class FixCatalogEntry(BaseModel):
    """One planted mechanism and CI class. Plans are copied byte for byte."""

    model_config = ConfigDict(extra="forbid")

    mechanism: str = Field(min_length=1)
    ci_class: str = Field(min_length=1)
    title: str = Field(min_length=1)
    implementation_plan: str = Field(min_length=1)
    backout_plan: str = Field(min_length=1)
    test_plan: str = Field(min_length=1)
    deployment_method: DeploymentMethod
    deployment_strategy: DeploymentStrategy
    standard_template: str | None = None


class IntakeRequest(BaseModel):
    """The mapping `run_intake` accepts. `release` and `security_flag` are absent."""

    model_config = ConfigDict(extra="forbid")

    requester: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    description: str = Field(min_length=1)
    cis: list[str] = Field(min_length=1)
    justification: str = Field(min_length=1)
    implementation_plan: str
    backout_plan: str
    test_plan: str
    deployment_method: DeploymentMethod
    deployment_strategy: DeploymentStrategy
    proposed_start: str = Field(min_length=1)
    proposed_end: str = Field(min_length=1)
    incident: str | None = None
    template: str | None = None


class ProblemChangeHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = CONTRACT_VERSION
    case_id: str
    attempt: int = Field(ge=1)
    idempotency_key: str
    request: IntakeRequest

    @model_validator(mode="after")
    def _ids(self) -> ProblemChangeHandoff:
        if CASE_ID.fullmatch(self.case_id) is None:
            raise ValueError("case_id must look like E2E- plus 8 hex characters")
        expected = change_idempotency_key(self.case_id, self.attempt)
        if self.idempotency_key != expected:
            raise ValueError("idempotency_key does not match the case and attempt")
        return self


class ChangeOutcome(BaseModel):
    """What the change result does to the problem. Wording is not an input."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = CONTRACT_VERSION
    case_id: str
    change_sys_id: str
    outcome: Literal["successful", "unsuccessful", "rejected", "held"]
    reason_code: str | None = None

    @model_validator(mode="after")
    def _held_has_reason(self) -> ChangeOutcome:
        if CASE_ID.fullmatch(self.case_id) is None:
            raise ValueError("case_id must look like E2E- plus 8 hex characters")
        if self.outcome == "held" and not self.reason_code:
            raise ValueError("a held outcome needs a reason code")
        return self


class DeploymentFailureLink(BaseModel):
    """A failed deployment incident joins the problem that owns the change."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = CONTRACT_VERSION
    case_id: str
    change_sys_id: str
    incident_sys_id: str
    problem_sys_id: str

    @model_validator(mode="after")
    def _case(self) -> DeploymentFailureLink:
        if CASE_ID.fullmatch(self.case_id) is None:
            raise ValueError("case_id must look like E2E- plus 8 hex characters")
        return self


def problem_idempotency_key(cluster_key: str) -> str:
    digest = hashlib.sha256(cluster_key.encode("utf-8")).hexdigest()[:16]
    return f"SYN-E2E-PRB-{digest}"


def change_idempotency_key(case_id: str, attempt: int) -> str:
    return f"SYN-E2E-{case_id}-CHG-{attempt}"


def intake_request_from_catalog(
    entry: FixCatalogEntry,
    *,
    problem_number: str,
    confirmed_mechanism: str,
    linked_incident_count: int,
    ci_name: str,
    requester: str,
    proposed_start: str,
    proposed_end: str,
    recurrence_rate: float,
    expected_incidents_prevented: int,
    incident_number: str | None = None,
) -> IntakeRequest:
    """Field-by-field map from a fix catalog entry to the intake request.

    The three plan fields are the catalog strings, unchanged. Incident text is
    not a parameter. `run_intake` leaves an implementation plan alone when it
    already starts with ``Deployment method:``. Catalog text has to satisfy
    that if the authority later hashes the stored change field.
    """
    summary = f"Fix for {problem_number}: {entry.title}"
    description = (
        f"Problem {problem_number}. Confirmed mechanism: {confirmed_mechanism}. "
        f"Linked incidents: {linked_incident_count}."
    )
    justification = (
        f"Incidents linked: {linked_incident_count}. "
        f"Recurrence rate: {recurrence_rate}. "
        f"Expected incidents prevented: {expected_incidents_prevented}."
    )
    return IntakeRequest(
        requester=requester,
        summary=summary,
        description=description,
        cis=[ci_name],
        justification=justification,
        implementation_plan=entry.implementation_plan,
        backout_plan=entry.backout_plan,
        test_plan=entry.test_plan,
        deployment_method=entry.deployment_method,
        deployment_strategy=entry.deployment_strategy,
        proposed_start=proposed_start,
        proposed_end=proposed_end,
        incident=incident_number,
        template=entry.standard_template,
    )


def to_intake_dict(request: IntakeRequest) -> dict[str, object]:
    """The dict passed to `run_intake`. Empty optional fields stay off the wire."""
    return request.model_dump(exclude_none=True)
