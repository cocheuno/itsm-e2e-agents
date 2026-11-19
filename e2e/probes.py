"""Phase 1 gate probes. Both delete their own records before returning."""

from __future__ import annotations

import re
import time
from typing import Any

from cm_agents.servicenow.client import ServiceNowClient, ServiceNowError
from cm_agents.settings import redact_text

from e2e.data.ground_truth import problem_key
from e2e.errors import WorldError
from e2e.instance import http_failure, open_client
from e2e.paths import repo_root
from e2e.settings import Settings

PROBE = "E2E-PROBE"
STATE_ASSESS = "-4"
STATE_AUTHORIZE = "-3"
STATE_SCHEDULED = "-2"
GROUP = "SYN Store DevOps"
START = "2026-12-20 02:00:00"
END = "2026-12-20 04:00:00"
_SYS_ID = re.compile(r"[0-9a-f]{32}")
_HEADING = "## Known error close code"


def run_authority_probe(settings: Settings) -> None:
    """One normal change, approved by the authority user, with the negative attempts."""
    change_id = ""
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        try:
            authority_id = _user_id(admin, settings.sn_authority_user)
            direct = admin.get_table(
                "sys_user_has_role",
                query=f"user={authority_id}^inherited=false",
                fields=["sys_id"],
                limit=20,
            )
            if direct:
                raise WorldError(f"authority user direct roles={len(direct)}")
            group_id = _group(admin, GROUP)
            change_id = _create_change(admin, settings, group_id)
            assess = _poll_change(admin, change_id, {STATE_ASSESS}, timeout=30)
            if str(assess.get("state") or "") != STATE_ASSESS:
                raise WorldError(f"probe change assess state={assess.get('state')}")
            approval_id = _requested_row(admin, change_id, authority_id)
            _negative_attempts(admin, settings, approval_id)
            _approve(admin, settings, approval_id, change_id, STATE_AUTHORIZE)
            second = _requested_row(admin, change_id, authority_id)
            final = _approve(admin, settings, second, change_id, STATE_SCHEDULED)
            _assert_duties(admin, settings, change_id, authority_id, str(final.get("state") or ""))
        finally:
            if change_id:
                _delete_change(admin, change_id)


def run_known_error_probe(settings: Settings) -> None:
    """Record whether close code Known error sticks on a probe incident. Then delete it."""
    incident_id = ""
    evidence: dict[str, Any] = {
        "parent_write": "none",
        "parent_stuck": False,
        "close_write": "none",
        "close_stuck": False,
        "read_state": "",
        "read_close_code": "",
        "deleted": False,
    }
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        try:
            problem_id = _e01(admin)
            incident_id = _create_probe_incident(settings)
            evidence.update(_link_and_resolve(admin, settings, incident_id, problem_id))
        finally:
            if incident_id:
                evidence["deleted"] = _delete_incident(admin, incident_id)
    _write_discovery(settings, evidence)
    if not evidence["deleted"]:
        raise WorldError("known-error probe incident is still present")
    stuck = "accepted" if evidence["close_stuck"] else "refused"
    print(
        "known error close code:"
        f" parent_stuck={str(evidence['parent_stuck']).lower()}"
        f" close_write={evidence['close_write']}"
        f" close_stuck={str(evidence['close_stuck']).lower()}"
        f" result={stuck}"
    )


def _create_change(admin: ServiceNowClient, settings: Settings, group_id: str) -> str:
    body = {
        "short_description": f"{PROBE} approval",
        "description": f"{PROBE} approval probe",
        "correlation_id": f"{PROBE}-approval",
    }
    with open_client(settings, settings.sn_agent_user, settings.sn_agent_password) as agent:
        try:
            created = agent.request("POST", "/api/sn_chg_rest/change/normal", json=body)
        except ServiceNowError as exc:
            raise http_failure("probe change", exc) from None
        change_id = _change_id(created)
        if not change_id:
            found = agent.get_table(
                "change_request",
                query=f"correlation_id={PROBE}-approval",
                fields=["sys_id"],
                limit=1,
            )
            change_id = str(found[0]["sys_id"]) if found else ""
        if not change_id:
            raise WorldError("probe change was not created")
        try:
            agent.update_record(
                "change_request",
                change_id,
                {
                    "assignment_group": group_id,
                    "start_date": START,
                    "end_date": END,
                },
            )
            agent.request(
                "PATCH",
                f"/api/sn_chg_rest/change/normal/{change_id}",
                json={"state": STATE_ASSESS},
            )
        except ServiceNowError as exc:
            raise http_failure("probe change assess", exc) from None
    return change_id


def _negative_attempts(
    admin: ServiceNowClient,
    settings: Settings,
    approval_id: str,
) -> None:
    actors = (
        ("change", settings.sn_agent_user, settings.sn_agent_password),
        ("incident", settings.sn_incident_user, settings.sn_incident_password),
        ("problem", settings.sn_problem_user, settings.sn_problem_password),
    )
    for label, user_name, password in actors:
        status = _try_approve(settings, user_name, password, approval_id)
        read = admin.get_record("sysapproval_approver", approval_id, fields=["state"])
        state = str(read.get("state") or "")
        print(f"approval negative {label} status={status} state={state}")
        if state != "requested":
            raise WorldError(f"approval negative {label} left state {state or 'empty'}")


def _try_approve(settings: Settings, user_name: str, password: str, approval_id: str) -> str:
    try:
        with open_client(settings, user_name, password) as actor:
            actor.update_record("sysapproval_approver", approval_id, {"state": "approved"})
    except ServiceNowError as exc:
        return str(exc.status_code if exc.status_code is not None else "none")
    return "200"


def _approve(
    admin: ServiceNowClient,
    settings: Settings,
    approval_id: str,
    change_id: str,
    wanted: str,
) -> dict[str, Any]:
    try:
        with open_client(
            settings,
            settings.sn_authority_user,
            settings.sn_authority_password,
        ) as actor:
            actor.update_record("sysapproval_approver", approval_id, {"state": "approved"})
    except ServiceNowError as exc:
        raise http_failure("authority approval", exc) from None
    change = _poll_change(admin, change_id, {wanted}, timeout=40)
    print(f"approval authority wanted={wanted} read={change.get('state')}")
    if str(change.get("state") or "") != wanted:
        raise WorldError(f"probe change stayed at {change.get('state')} after approval")
    return change


def _assert_duties(
    admin: ServiceNowClient,
    settings: Settings,
    change_id: str,
    authority_id: str,
    final_state: str,
) -> None:
    if final_state != STATE_SCHEDULED:
        raise WorldError(f"probe change final state={final_state}")
    change = admin.get_record("change_request", change_id, fields=["sys_created_by", "state"])
    created_by = str(change.get("sys_created_by") or "")
    creator_is_change = created_by == settings.sn_agent_user
    creator_is_authority = created_by == settings.sn_authority_user
    rows = admin.get_table(
        "sysapproval_approver",
        query=f"sysapproval={change_id}",
        fields=["state", "approver"],
        limit=40,
    )
    approved = [row for row in rows if str(row.get("state") or "") == "approved"]
    foreign = [
        row for row in approved if str(row.get("approver") or "") != authority_id
    ]
    print(
        "approval probe:"
        f" scheduled={change.get('state')}"
        f" creator_is_change_user={str(creator_is_change).lower()}"
        f" creator_is_authority={str(creator_is_authority).lower()}"
        f" approved_rows={len(approved)}"
    )
    if not creator_is_change or creator_is_authority:
        raise WorldError("probe change creator check failed")
    if not approved or foreign:
        raise WorldError("probe approval rows were not all approved by the authority user")


def _requested_row(admin: ServiceNowClient, change_id: str, authority_id: str) -> str:
    rows = _poll_rows(
        admin,
        "sysapproval_approver",
        f"sysapproval={change_id}^approver={authority_id}^state=requested",
        ["sys_id", "state"],
    )
    if not rows:
        raise WorldError("no requested approval for the authority user")
    return str(rows[0]["sys_id"])


def _create_probe_incident(settings: Settings) -> str:
    with open_client(settings, settings.sn_incident_user, settings.sn_incident_password) as actor:
        try:
            created = actor.create_record(
                "incident",
                {
                    "short_description": f"{PROBE} known error close",
                    "description": f"{PROBE} known error close code",
                    "correlation_id": f"{PROBE}-known-error",
                    "impact": "3",
                    "urgency": "3",
                },
            )
        except ServiceNowError as exc:
            raise http_failure("known-error probe incident", exc) from None
    return str(created.get("sys_id") or "")


def _link_and_resolve(
    admin: ServiceNowClient,
    settings: Settings,
    incident_id: str,
    problem_id: str,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    with open_client(settings, settings.sn_incident_user, settings.sn_incident_password) as actor:
        evidence["parent_write"] = _patch(
            actor,
            incident_id,
            {"parent": problem_id},
        )
        parent = admin.get_record("incident", incident_id, fields=["parent"])
        evidence["parent_stuck"] = str(parent.get("parent") or "") == problem_id
        evidence["close_write"] = _patch(
            actor,
            incident_id,
            {
                "state": "6",
                "close_code": "Known error",
                "close_notes": f"{PROBE} known error",
            },
        )
    read = admin.get_record("incident", incident_id, fields=["state", "close_code"])
    evidence["read_state"] = str(read.get("state") or "")
    evidence["read_close_code"] = str(read.get("close_code") or "")
    evidence["close_stuck"] = (
        evidence["read_state"] == "6" and evidence["read_close_code"] == "Known error"
    )
    return evidence


def _patch(actor: ServiceNowClient, incident_id: str, body: dict[str, str]) -> str:
    try:
        actor.update_record("incident", incident_id, body)
    except ServiceNowError as exc:
        return str(exc.status_code if exc.status_code is not None else "none")
    return "200"


def _e01(admin: ServiceNowClient) -> str:
    key = problem_key("syn-store-cdn", "log_rotation_stopped")
    rows = admin.get_table(
        "problem",
        query=f"correlation_id={key}",
        fields=["sys_id"],
        limit=1,
    )
    if not rows:
        raise WorldError("E01 problem is absent")
    return str(rows[0]["sys_id"])


def _delete_change(admin: ServiceNowClient, change_id: str) -> None:
    for table, query in (
        ("sysapproval_approver", f"sysapproval={change_id}"),
        ("sysapproval_group", f"parent={change_id}"),
        ("change_task", f"change_request={change_id}^ORparent={change_id}"),
        ("task_ci", f"task={change_id}"),
    ):
        rows = admin.get_table(table, query=query, fields=["sys_id"], limit=40)
        for row in rows:
            _delete_id(admin, table, str(row.get("sys_id") or ""))
    try:
        admin.delete_record("change_request", change_id)
    except ServiceNowError as exc:
        code = exc.status_code if exc.status_code is not None else "none"
        raise WorldError(f"probe change delete failed HTTP {code}") from None
    left = admin.get_table(
        "change_request",
        query=f"sys_id={change_id}",
        fields=["sys_id"],
        limit=1,
    )
    if left:
        raise WorldError("probe change is still present")


def _delete_incident(admin: ServiceNowClient, incident_id: str) -> bool:
    try:
        admin.delete_record("incident", incident_id)
    except ServiceNowError:
        return False
    left = admin.get_table(
        "incident",
        query=f"sys_id={incident_id}",
        fields=["sys_id"],
        limit=1,
    )
    return not left


def _write_discovery(settings: Settings, evidence: dict[str, Any]) -> None:
    stuck = evidence["close_stuck"]
    decision = (
        "The close code was accepted when the incident parent was the seeded E01 problem."
        if stuck
        else (
            "The close code was refused. Historical incidents stay on close code"
            ' "Solution provided".'
        )
    )
    block = "\n".join(
        [
            _HEADING,
            "",
            "Can the incident user resolve an E2E-PROBE incident with close code"
            ' "Known error" when its parent is the seeded E01 problem?',
            "",
            "Calls:",
            "",
            "- `POST /api/now/table/incident` as the incident user, marker `E2E-PROBE`",
            "- `PATCH` parent to the E01 problem",
            "- `PATCH` state `6` and close code `Known error`",
            "- `DELETE` the probe incident",
            "",
            "Evidence:",
            "",
            "```",
            f"parent_write={evidence['parent_write']}",
            f"parent_stuck={str(evidence['parent_stuck']).lower()}",
            f"close_write={evidence['close_write']}",
            f"close_stuck={str(evidence['close_stuck']).lower()}",
            f"read_state={evidence['read_state']}",
            f"read_close_code={evidence['read_close_code']}",
            f"probe_deleted={str(evidence['deleted']).lower()}",
            "```",
            "",
            f"Decision: {decision}",
            "",
        ]
    )
    safe = redact_text(block, settings.secret_values())
    path = repo_root() / "docs" / "DISCOVERY.md"
    existing = path.read_text(encoding="utf-8")
    if _HEADING in existing:
        start = existing.index(_HEADING)
        rest = existing[start + len(_HEADING) :]
        match = re.search(r"\n## ", rest)
        end = start + len(_HEADING) + match.start() if match else len(existing)
        updated = existing[:start].rstrip() + "\n\n" + safe
        if match:
            updated += "\n" + existing[end:].lstrip("\n")
    else:
        updated = existing.rstrip() + "\n\n" + safe
    path.write_text(updated, encoding="utf-8")


def _user_id(admin: ServiceNowClient, user_name: str) -> str:
    rows = admin.get_table(
        "sys_user",
        query=f"user_name={user_name}",
        fields=["sys_id"],
        limit=1,
    )
    if not rows:
        raise WorldError("a service user is absent")
    return str(rows[0]["sys_id"])


def _group(admin: ServiceNowClient, name: str) -> str:
    rows = admin.get_table(
        "sys_user_group",
        query=f"name={name}",
        fields=["sys_id"],
        limit=1,
    )
    if not rows:
        raise WorldError(f"group {name} was not found")
    return str(rows[0]["sys_id"])


def _change_id(payload: dict[str, Any]) -> str:
    result = payload.get("result")
    if isinstance(result, dict):
        value = result.get("sys_id")
        if isinstance(value, dict):
            value = value.get("value")
        if isinstance(value, str) and _SYS_ID.fullmatch(value):
            return value
    return ""


def _poll_change(
    admin: ServiceNowClient,
    change_id: str,
    wanted: set[str],
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while True:
        last = admin.get_record(
            "change_request",
            change_id,
            fields=["state", "approval", "sys_created_by"],
        )
        if str(last.get("state") or "") in wanted or time.monotonic() >= deadline:
            return last
        time.sleep(2)


def _poll_rows(
    admin: ServiceNowClient,
    table: str,
    query: str,
    fields: list[str],
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + 25
    rows: list[dict[str, Any]] = []
    while True:
        rows = admin.get_table(table, query=query, fields=fields, limit=10)
        if rows or time.monotonic() >= deadline:
            return rows
        time.sleep(2)


def _delete_id(admin: ServiceNowClient, table: str, sys_id: str) -> None:
    if len(sys_id) != 32:
        return
    try:
        admin.delete_record(table, sys_id)
    except ServiceNowError as exc:
        if exc.status_code in {403, 404}:
            if exc.status_code == 403:
                raise WorldError(f"probe delete {table} failed HTTP 403") from None
            return
        code = exc.status_code if exc.status_code is not None else "none"
        raise WorldError(f"probe delete {table} failed HTTP {code}") from None
