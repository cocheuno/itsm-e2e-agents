"""Phase 0 probes. Every SYN-PROBE row is deleted before this command returns."""

from __future__ import annotations

import re
import secrets
import time
from typing import Any

from cm_agents.discover import evaluate_outbound_email
from cm_agents.servicenow.client import ServiceNowClient, ServiceNowError
from cm_agents.settings import redact_text

from e2e.settings import Settings, repo_root

MARKER = "SYN-PROBE"
APPROVER_USER = "syn.probe.approver"
INCIDENT_USER = "syn.probe.incident"
PROBLEM_USER = "syn.probe.problem"
PROBE_USERS = (APPROVER_USER, INCIDENT_USER, PROBLEM_USER)
_SYS_ID = re.compile(r"^[0-9a-f]{32}$")
STATE_ASSESS = "-4"
STATE_AUTHORIZE = "-3"
STATE_SCHEDULED = "-2"

INCIDENT_LADDER = ("sn_incident_write", "itil")
PROBLEM_LADDER = ("problem_coordinator", "itil")
KNOWLEDGE_LADDER = ("knowledge", "sn_km_contribute", "knowledge_admin")
AUTHORITY_LADDER = ("approver_user", "sn_change_read", "itil")


def run_discover(settings: Settings) -> int:
    evidence: dict[str, Any] = {"probes": {}}
    secret_bag = list(settings.secret_values())
    failed = False
    with ServiceNowClient(
        settings.sn_instance_url,
        settings.sn_admin_user,
        settings.sn_admin_password,
        secrets=secret_bag,
    ) as admin:
        allowed, email = _email_gate(admin)
        evidence["email"] = email
        print(email["line"])
        if not allowed:
            _write(evidence, secret_bag)
            return 2
        try:
            _cleanup(admin)
            evidence["dictionary"] = _dictionary(admin)
            evidence["choices"] = _choices(admin)
            _print_choices(evidence["choices"])
            passwords = {name: _password() for name in PROBE_USERS}
            for password in passwords.values():
                secret_bag.append(password)
                admin._secrets.append(password)
            users = _create_users(admin, settings, passwords, secret_bag)
            evidence["users"] = {name: {"sys_id": row["sys_id"]} for name, row in users.items()}
            evidence["probes"]["approval"] = _approval_probe(
                admin, settings, users, passwords, secret_bag
            )
            evidence["probes"]["parent"] = _parent_probe(
                admin, settings, users, passwords, secret_bag, evidence["choices"]
            )
            evidence["probes"]["rfc"] = _rfc_probe(
                admin, settings, users, passwords, secret_bag
            )
            evidence["probes"]["states"] = _state_probe(
                admin, settings, users, passwords, secret_bag, evidence["choices"]
            )
            evidence["probes"]["knowledge"] = _knowledge_probe(
                admin, settings, users, passwords, secret_bag
            )
            evidence["probes"]["roles"] = _role_summary(users, evidence["probes"])
        except Exception as exc:
            failed = True
            evidence["error"] = redact_text(f"{type(exc).__name__}: {exc}", secret_bag)[:500]
            print(f"discovery probe failed: {type(exc).__name__}")
        finally:
            _cleanup(admin)
            evidence["residue"] = _residue(admin)
            _print_residue(evidence["residue"])
            _write(evidence, secret_bag)
    dirty = any(item.get("count") != 0 for item in evidence.get("residue", []))
    blocked = _gate_blocked(evidence)
    if failed or dirty or blocked:
        return 1
    return 0


def _gate_blocked(evidence: dict[str, Any]) -> bool:
    probes = evidence.get("probes") or {}
    approval = probes.get("approval") or {}
    if approval.get("decision") != "verified":
        print("approval design: STOP")
        return True
    for name in ("parent", "rfc", "states", "knowledge", "roles"):
        decision = (probes.get(name) or {}).get("decision")
        if decision not in {"verified", "approved-fallback"}:
            print(f"{name}: not verified")
            return True
    if not evidence.get("choices"):
        return True
    return False


def _email_gate(client: ServiceNowClient) -> tuple[bool, dict[str, Any]]:
    try:
        rows = client.get_table(
            "sys_properties",
            query="nameINglide.email.smtp.active,glide.email.read.active",
            fields=["name", "value"],
            limit=10,
        )
        properties = {str(row.get("name")): str(row.get("value") or "") for row in rows}
    except ServiceNowError as exc:
        return False, {
            "line": "email: properties could not be read. SYN-PROBE was not created.",
            "status": exc.status_code,
        }
    try:
        accounts = client.get_table(
            "sys_email_account",
            query="active=true",
            fields=["sys_id"],
            limit=20,
        )
        active: int | None = len(accounts)
    except ServiceNowError as exc:
        return False, {
            "line": "email: account query failed. SYN-PROBE was not created.",
            "status": exc.status_code,
        }
    allowed, reason = evaluate_outbound_email(properties, active)
    return allowed, {
        "line": reason,
        "properties": properties,
        "active_email_accounts": active,
        "proceed": allowed,
    }


def _password() -> str:
    return "Aa1!" + secrets.token_urlsafe(18)


def _create_users(
    admin: ServiceNowClient,
    settings: Settings,
    passwords: dict[str, str],
    secret_bag: list[str],
) -> dict[str, dict[str, Any]]:
    users: dict[str, dict[str, Any]] = {}
    for name in PROBE_USERS:
        created = admin.create_record(
            "sys_user",
            {
                "user_name": name,
                "first_name": MARKER,
                "last_name": "Probe",
                "email": f"{name}@example.com",
                "user_password": passwords[name],
                "password_needs_reset": "false",
                "web_service_access_only": "true",
                "time_zone": "UTC",
                "active": "true",
            },
            input_display_value=True,
        )
        sys_id = str(created.get("sys_id") or "")
        login = _login_status(settings, name, passwords[name], secret_bag)
        if login != "ok" and sys_id:
            _reset_password(admin, sys_id, passwords[name])
            login = _login_status(settings, name, passwords[name], secret_bag)
        granted: list[str] = []
        if login != "ok" and sys_id:
            basic = _grant(admin, sys_id, "snc_basic_auth_api_access")
            if basic.get("ok"):
                granted.append("snc_basic_auth_api_access")
                print("role snc_basic_auth_api_access granted")
                login = _login_status(settings, name, passwords[name], secret_bag)
        print(f"probe user {name}: login={login}")
        users[name] = {"sys_id": sys_id, "login": login, "granted": granted}
    return users


def _reset_password(admin: ServiceNowClient, user_id: str, password: str) -> None:
    try:
        admin.update_record(
            "sys_user",
            user_id,
            {"user_password": password, "password_needs_reset": "false"},
            input_display_value=True,
        )
    except ServiceNowError:
        return


def _login_status(
    settings: Settings,
    username: str,
    password: str,
    secret_bag: list[str],
) -> str:
    try:
        with _as_user(settings, username, password, secret_bag) as client:
            client.request("GET", "/api/now/ui/user/current")
    except ServiceNowError as exc:
        return f"failed HTTP {exc.status_code}"
    return "ok"


def _as_user(
    settings: Settings,
    username: str,
    password: str,
    secret_bag: list[str],
) -> ServiceNowClient:
    return ServiceNowClient(
        settings.sn_instance_url,
        username,
        password,
        secrets=[*secret_bag, password],
    )


def _grant(admin: ServiceNowClient, user_id: str, role_name: str) -> dict[str, Any]:
    rows = admin.get_table(
        "sys_user_role",
        query=f"name={role_name}",
        fields=["sys_id", "name"],
        limit=1,
    )
    if not rows:
        return {"role": role_name, "ok": False, "error": "role was not found"}
    role_id = rows[0].get("sys_id")
    try:
        link = admin.create_record(
            "sys_user_has_role",
            {"user": user_id, "role": role_id, "inherited": "false"},
        )
    except ServiceNowError:
        try:
            link = admin.create_record(
                "sys_user_has_role",
                {"user": user_id, "role": role_id},
            )
        except ServiceNowError as exc:
            return {"role": role_name, "ok": False, "status": exc.status_code}
    return {"role": role_name, "ok": True, "sys_id": link.get("sys_id")}


def _add_role(
    admin: ServiceNowClient,
    user: dict[str, Any],
    ladder: tuple[str, ...],
) -> str | None:
    granted: list[str] = user["granted"]
    for role in ladder:
        if role in granted:
            continue
        result = _grant(admin, str(user["sys_id"]), role)
        user.setdefault("grants", []).append(
            {key: value for key, value in result.items() if key != "sys_id"}
        )
        if result.get("ok"):
            granted.append(role)
            print(f"role {role} granted")
            return role
    return None


def _ensure(
    admin: ServiceNowClient,
    user: dict[str, Any],
    ladder: tuple[str, ...],
    operation,
) -> dict[str, Any]:
    """Run operation. On HTTP 403, add the next role and retry once per role."""
    result = operation()
    while result.get("status") == 403:
        added = _add_role(admin, user, ladder)
        if added is None:
            break
        result = operation()
        result["role_added"] = added
    result["roles"] = list(user["granted"])
    return result


def _approval_probe(
    admin: ServiceNowClient,
    settings: Settings,
    users: dict[str, dict[str, Any]],
    passwords: dict[str, str],
    secret_bag: list[str],
) -> dict[str, Any]:
    question = (
        "Can a non-admin group member approve a normal change through the Table API "
        "so it advances through Assess and Authorize?"
    )
    user = users[APPROVER_USER]
    calls: list[str] = []
    groups = {
        "Change Management": _named_group(admin, "Change Management"),
        "CAB Approval": _named_group(admin, "CAB Approval"),
    }
    memberships = []
    for name, group_id in groups.items():
        if not group_id:
            continue
        link = admin.create_record(
            "sys_user_grmember",
            {"user": user["sys_id"], "group": group_id},
        )
        memberships.append({"group": name, "sys_id": link.get("sys_id")})
        calls.append(f"POST /api/now/table/sys_user_grmember group={name}")
    agent_body = {
        "short_description": f"{MARKER} approval",
        "description": f"{MARKER} approval probe",
        "correlation_id": f"{MARKER}-approval",
    }
    with _as_user(
        settings, settings.sn_agent_user, settings.sn_agent_password, secret_bag
    ) as agent:
        created = agent.request("POST", "/api/sn_chg_rest/change/normal", json=agent_body)
        calls.append("POST /api/sn_chg_rest/change/normal as the change user")
        change_id = _change_id(created)
        if not change_id:
            found = agent.get_table(
                "change_request",
                query=f"correlation_id={MARKER}-approval",
                fields=["sys_id"],
                limit=1,
            )
            change_id = str(found[0]["sys_id"]) if found else ""
        if not change_id:
            return _result(question, calls, {"created": False}, "failed", "change was not created")
        if groups["Change Management"]:
            agent.update_record(
                "change_request",
                change_id,
                {
                    "assignment_group": groups["Change Management"],
                    "start_date": "2026-12-20 02:00:00",
                    "end_date": "2026-12-20 04:00:00",
                },
            )
            calls.append("PATCH change_request assignment_group, start_date, end_date")
        agent.request(
            "PATCH",
            f"/api/sn_chg_rest/change/normal/{change_id}",
            json={"state": STATE_ASSESS},
        )
        calls.append("PATCH /api/sn_chg_rest/change/normal/{sys_id} state=-4")
    assess = _poll_change(admin, change_id, {STATE_ASSESS}, timeout=30)
    first = _approve_step(
        admin, settings, user, passwords, secret_bag, change_id, STATE_AUTHORIZE, calls
    )
    second = None
    if first.get("change_state") == STATE_AUTHORIZE:
        second = _approve_step(
            admin, settings, user, passwords, secret_bag, change_id, STATE_SCHEDULED, calls
        )
    final = admin.get_record(
        "change_request",
        change_id,
        fields=["state", "approval", "number"],
    )
    evidence = {
        "groups": {name: bool(group_id) for name, group_id in groups.items()},
        "memberships": len(memberships),
        "roles": list(user["granted"]),
        "assess_state": assess.get("state"),
        "first": _trim_step(first),
        "second": _trim_step(second) if second else None,
        "final_state": final.get("state"),
        "final_approval": final.get("approval"),
        "number": final.get("number"),
    }
    verified = (
        str(assess.get("state")) == STATE_ASSESS
        and first.get("change_state") == STATE_AUTHORIZE
        and second is not None
        and second.get("change_state") == STATE_SCHEDULED
        and "admin" not in user["granted"]
    )
    decision = "verified" if verified else "failed"
    print(
        "approval:"
        f" assess={assess.get('state')} authorize={first.get('change_state')}"
        f" scheduled={None if second is None else second.get('change_state')}"
        f" roles={','.join(user['granted']) or 'none'}"
    )
    return _result(question, calls, evidence, decision, _approval_reason(verified, evidence))


def _approve_step(
    admin: ServiceNowClient,
    settings: Settings,
    user: dict[str, Any],
    passwords: dict[str, str],
    secret_bag: list[str],
    change_id: str,
    wanted: str,
    calls: list[str],
) -> dict[str, Any]:
    rows = _poll_rows(
        admin,
        "sysapproval_approver",
        f"sysapproval={change_id}^approver={user['sys_id']}^state=requested",
        ["sys_id", "state", "approver"],
    )
    others = admin.get_table(
        "sysapproval_approver",
        query=f"sysapproval={change_id}^state=requested",
        fields=["sys_id"],
        limit=40,
    )
    if not rows:
        current = admin.get_record("change_request", change_id, fields=["state", "approval"])
        return {
            "probe_rows": 0,
            "requested_rows": len(others),
            "write_status": None,
            "row_state": None,
            "change_state": current.get("state"),
        }

    def write() -> dict[str, Any]:
        try:
            with _as_user(
                settings, APPROVER_USER, passwords[APPROVER_USER], secret_bag
            ) as actor:
                actor.update_record(
                    "sysapproval_approver",
                    str(rows[0]["sys_id"]),
                    {"state": "approved"},
                )
                calls.append("PATCH sysapproval_approver state=approved as the probe user")
                readback = actor.get_record(
                    "sysapproval_approver",
                    str(rows[0]["sys_id"]),
                    fields=["state"],
                )
            return {"ok": True, "status": 200, "row_state": readback.get("state")}
        except ServiceNowError as exc:
            return {"ok": False, "status": exc.status_code, "row_state": None}

    written = _ensure(admin, user, AUTHORITY_LADDER, write)
    change = _poll_change(admin, change_id, {wanted}, timeout=40)
    return {
        "probe_rows": len(rows),
        "requested_rows": len(others),
        "write_status": written.get("status"),
        "row_state": written.get("row_state"),
        "change_state": change.get("state"),
        "roles": list(user["granted"]),
    }


def _trim_step(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "probe_rows": step.get("probe_rows"),
        "requested_rows": step.get("requested_rows"),
        "write_status": step.get("write_status"),
        "row_state": step.get("row_state"),
        "change_state": step.get("change_state"),
        "roles": step.get("roles"),
    }


def _approval_reason(verified: bool, evidence: dict[str, Any]) -> str:
    if verified:
        return (
            "The probe user, without admin, approved its own rows at Assess and Authorize. "
            "The change reached Scheduled."
        )
    return (
        "A non-admin group member did not advance the change through Assess and Authorize. "
        "The approval design stops here."
    )


def _parent_probe(
    admin: ServiceNowClient,
    settings: Settings,
    users: dict[str, dict[str, Any]],
    passwords: dict[str, str],
    secret_bag: list[str],
    choices: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    question = (
        "Does incident.parent point at a problem, read back, "
        "and list that incident on the problem?"
    )
    calls = ["POST /api/now/table/incident", "POST /api/now/table/problem", "PATCH incident parent"]
    incident_user = users[INCIDENT_USER]
    problem_user = users[PROBLEM_USER]
    incident_id = _insert_with_ladder(
        admin,
        settings,
        incident_user,
        passwords[INCIDENT_USER],
        secret_bag,
        INCIDENT_LADDER,
        "incident",
        {
            "short_description": f"{MARKER} parent",
            "description": f"{MARKER} parent probe",
            "correlation_id": f"{MARKER}-parent",
            "caller_id": incident_user["sys_id"],
            "impact": "2",
            "urgency": "2",
        },
    )
    problem_id = _insert_with_ladder(
        admin,
        settings,
        problem_user,
        passwords[PROBLEM_USER],
        secret_bag,
        PROBLEM_LADDER,
        "problem",
        {
            "short_description": f"{MARKER} parent",
            "description": f"{MARKER} parent probe",
            "correlation_id": f"{MARKER}-parent",
        },
    )
    if not incident_id or not problem_id:
        print("parent: records were not created")
        return _result(
            question,
            calls,
            {
                "incident": bool(incident_id),
                "problem": bool(problem_id),
                "incident_roles": list(incident_user["granted"]),
                "problem_roles": list(problem_user["granted"]),
            },
            "failed",
            "The parent probe could not create both records.",
        )

    def link() -> dict[str, Any]:
        try:
            with _as_user(
                settings, PROBLEM_USER, passwords[PROBLEM_USER], secret_bag
            ) as actor:
                actor.update_record("incident", incident_id, {"parent": problem_id})
            return {"ok": True, "status": 200}
        except ServiceNowError as exc:
            return {"ok": False, "status": exc.status_code}

    written = _ensure(admin, problem_user, PROBLEM_LADDER, link)
    readback = admin.get_record("incident", incident_id, fields=["parent", "number", "state"])
    visible = admin.get_table(
        "incident",
        query=f"parent={problem_id}",
        fields=["sys_id"],
        limit=5,
    )
    problem_read = _read_count(
        settings,
        PROBLEM_USER,
        passwords[PROBLEM_USER],
        secret_bag,
        "incident",
        f"parent={problem_id}",
    )
    linked = str(readback.get("parent") or "") == problem_id and any(
        str(row.get("sys_id")) == incident_id for row in visible
    )
    evidence = {
        "write_status": written.get("status"),
        "parent": readback.get("parent"),
        "listed": len(visible),
        "problem_user_sees": problem_read,
        "incident_roles": list(incident_user["granted"]),
        "problem_roles": list(problem_user["granted"]),
        "close_codes_loaded": len(choices.get("incident.close_code") or []),
    }
    decision = "verified" if linked else "failed"
    print(f"parent: linked={linked} status={written.get('status')} listed={len(visible)}")
    reason = (
        "incident.parent read back as the problem, and the parent query returned the incident."
        if linked
        else "incident.parent did not read back. A custom reference field is not approved."
    )
    return _result(question, calls, evidence, decision, reason)


def _rfc_probe(
    admin: ServiceNowClient,
    settings: Settings,
    users: dict[str, dict[str, Any]],
    passwords: dict[str, str],
    secret_bag: list[str],
) -> dict[str, Any]:
    question = "Can the problem user set problem.rfc and read it back?"
    calls = [
        "POST /api/sn_chg_rest/change/normal as the change user",
        "PATCH /api/now/table/problem/{sys_id} rfc",
    ]
    problem_user = users[PROBLEM_USER]
    problem_id = _insert_with_ladder(
        admin,
        settings,
        problem_user,
        passwords[PROBLEM_USER],
        secret_bag,
        PROBLEM_LADDER,
        "problem",
        {
            "short_description": f"{MARKER} rfc",
            "description": f"{MARKER} rfc probe",
            "correlation_id": f"{MARKER}-rfc",
        },
    )
    with _as_user(
        settings, settings.sn_agent_user, settings.sn_agent_password, secret_bag
    ) as agent:
        created = agent.request(
            "POST",
            "/api/sn_chg_rest/change/normal",
            json={
                "short_description": f"{MARKER} rfc",
                "description": f"{MARKER} rfc probe",
                "correlation_id": f"{MARKER}-rfc",
            },
        )
    change_id = _change_id(created)
    if not problem_id or not change_id:
        print("rfc: records were not created")
        return _result(
            question,
            calls,
            {"created": False},
            "failed",
            "The rfc probe could not create both records.",
        )

    def write() -> dict[str, Any]:
        try:
            with _as_user(settings, PROBLEM_USER, passwords[PROBLEM_USER], secret_bag) as actor:
                updated = actor.update_record("problem", problem_id, {"rfc": change_id})
            return {"ok": True, "status": 200, "returned": updated.get("rfc")}
        except ServiceNowError as exc:
            return {"ok": False, "status": exc.status_code, "returned": None}

    written = _ensure(admin, problem_user, PROBLEM_LADDER, write)
    readback = admin.get_record("problem", problem_id, fields=["rfc", "number"])
    stuck = str(readback.get("rfc") or "") != change_id
    evidence = {
        "write_status": written.get("status"),
        "returned": written.get("returned"),
        "read_back": readback.get("rfc"),
        "stuck": stuck,
        "dictionary": _dictionary(admin).get("problem.rfc"),
        "roles": list(problem_user["granted"]),
    }
    if not stuck:
        decision = "verified"
        reason = "problem.rfc read back as the probe change."
    else:
        decision = "approved-fallback"
        reason = (
            "problem.rfc did not keep the change. The architecture fallback is a work note "
            "plus change.parent. No new field was created."
        )
    print(f"rfc: stuck={stuck} status={written.get('status')}")
    return _result(question, calls, evidence, decision, reason)


def _state_probe(
    admin: ServiceNowClient,
    settings: Settings,
    users: dict[str, dict[str, Any]],
    passwords: dict[str, str],
    secret_bag: list[str],
    choices: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    question = "Can the problem user move a probe problem through its states with the Table API?"
    calls = [
        "GET sys_dictionary name=problem^element=state",
        "PATCH /api/now/table/problem/{sys_id} state",
    ]
    problem_user = users[PROBLEM_USER]
    problem_id = _insert_with_ladder(
        admin,
        settings,
        problem_user,
        passwords[PROBLEM_USER],
        secret_bag,
        PROBLEM_LADDER,
        "problem",
        {
            "short_description": f"{MARKER} states",
            "description": f"{MARKER} state probe",
            "correlation_id": f"{MARKER}-states",
        },
    )
    if not problem_id:
        print("problem.state: problem was not created")
        return _result(
            question,
            calls,
            {"created": False},
            "failed",
            "The state probe could not create a problem.",
        )
    current = admin.get_record("problem", problem_id, fields=["state", "prb_model", "number"])
    model_id = str(current.get("prb_model") or "")
    transitions = _transitions(admin, model_id)
    start = str(current.get("state") or "")
    path = _path_from(start, transitions)
    if not path:
        assess = _active_value(choices.get("problem.state") or [], "Assess")
        if assess and assess != start:
            path = [assess]
            calls.append("no transition rows; one Assess attempt")
    attempts = []
    for target in path:
        attempt = _move_state(
            admin, settings, problem_user, passwords, secret_bag, problem_id, target
        )
        attempts.append(attempt)
        if attempt.get("after") != target:
            break
    moved = [row["after"] for row in attempts if row.get("after") == row.get("requested")]
    fully = bool(path) and len(moved) == len(path)
    if fully and transitions:
        decision = "verified"
        reason = "The Table API moved the probe problem along each model edge that was read."
    elif fully:
        decision = "verified"
        reason = (
            "No model edges were read. One Table API move to Assess stuck. "
            "Later states were not attempted."
        )
    elif attempts and not moved:
        decision = "approved-fallback"
        reason = (
            "The Table API did not move the problem through its states. "
            "The approved fallback is pm-agent's Scripted REST endpoint. It is not installed."
        )
    elif attempts:
        decision = "partial"
        reason = "The Table API moved some states and stopped. The endpoint was not installed."
    else:
        decision = "failed"
        reason = "No problem state transition was found to attempt."
    evidence = {
        "dictionary": _dictionary(admin).get("problem.state"),
        "start": start,
        "model": model_id,
        "transition_rows": len(transitions),
        "path": path,
        "attempts": attempts,
        "roles": list(problem_user["granted"]),
    }
    last = attempts[-1] if attempts else {}
    print(
        "problem.state:"
        f" path={len(path)} moved={len(moved)} last_status={last.get('status')}"
        f" {last.get('before')}->{last.get('requested')} read={last.get('after')}"
    )
    return _result(question, calls, evidence, decision, reason)


def _move_state(
    admin: ServiceNowClient,
    settings: Settings,
    user: dict[str, Any],
    passwords: dict[str, str],
    secret_bag: list[str],
    problem_id: str,
    target: str,
) -> dict[str, Any]:
    before = str(
        admin.get_record("problem", problem_id, fields=["state"]).get("state") or ""
    )

    def write() -> dict[str, Any]:
        try:
            with _as_user(settings, PROBLEM_USER, passwords[PROBLEM_USER], secret_bag) as actor:
                updated = actor.update_record("problem", problem_id, {"state": target})
            return {"ok": True, "status": 200, "returned": updated.get("state")}
        except ServiceNowError as exc:
            return {"ok": False, "status": exc.status_code, "returned": None}

    written = _ensure(admin, user, PROBLEM_LADDER, write)
    after = str(admin.get_record("problem", problem_id, fields=["state"]).get("state") or "")
    assignee_status = None
    if after != target and written.get("status") == 200:
        try:
            with _as_user(settings, PROBLEM_USER, passwords[PROBLEM_USER], secret_bag) as actor:
                updated = actor.update_record(
                    "problem",
                    problem_id,
                    {"state": target, "assigned_to": user["sys_id"]},
                )
            assignee_status = 200
            written = {**written, "returned": updated.get("state")}
        except ServiceNowError as exc:
            assignee_status = exc.status_code
        after = str(admin.get_record("problem", problem_id, fields=["state"]).get("state") or "")
    return {
        "before": before,
        "requested": target,
        "returned": written.get("returned"),
        "after": after,
        "status": written.get("status"),
        "assignee_retry": assignee_status,
        "role_added": written.get("role_added"),
    }


def _knowledge_probe(
    admin: ServiceNowClient,
    settings: Settings,
    users: dict[str, dict[str, Any]],
    passwords: dict[str, str],
    secret_bag: list[str],
) -> dict[str, Any]:
    question = "Can the problem user create and publish a Known Error article?"
    calls = [
        "GET kb_knowledge_base title=Known Error",
        "POST knowledge article as the problem user",
        "PATCH workflow_state=published",
    ]
    bases = admin.get_table(
        "kb_knowledge_base",
        query="title=Known Error^active=true",
        fields=["sys_id", "title"],
        limit=5,
    )
    if not bases:
        print("knowledge: Known Error base was not found")
        return _result(
            question,
            calls,
            {"base": False},
            "approved-fallback",
            "The Known Error base was not readable. publish_article was not installed.",
        )
    base_id = str(bases[0]["sys_id"])
    user = users[PROBLEM_USER]
    created = _create_article(
        admin, settings, user, passwords, secret_bag, base_id
    )
    article_id = str(created.get("sys_id") or "")
    published = None
    if article_id:

        def publish() -> dict[str, Any]:
            try:
                with _as_user(
                    settings, PROBLEM_USER, passwords[PROBLEM_USER], secret_bag
                ) as actor:
                    updated = actor.update_record(
                        "kb_knowledge",
                        article_id,
                        {"workflow_state": "published"},
                    )
                return {"ok": True, "status": 200, "returned": updated.get("workflow_state")}
            except ServiceNowError as exc:
                return {"ok": False, "status": exc.status_code, "returned": None}

        published = _ensure(admin, user, KNOWLEDGE_LADDER, publish)
        readback = admin.get_record(
            "kb_knowledge",
            article_id,
            fields=["workflow_state", "published", "number"],
        )
    else:
        readback = {}
    workflow = str(readback.get("workflow_state") or "")
    ok = workflow == "published" or str(readback.get("published") or "").lower() == "true"
    evidence = {
        "base_count": len(bases),
        "create": {
            key: created.get(key) for key in ("status", "table", "sys_id") if key in created
        },
        "publish_status": None if published is None else published.get("status"),
        "returned_workflow": None if published is None else published.get("returned"),
        "workflow_state": workflow,
        "published": readback.get("published"),
        "roles": list(user["granted"]),
    }
    if ok:
        decision = "verified"
        reason = "The problem user published the probe article."
    else:
        decision = "approved-fallback"
        reason = (
            "The problem user did not publish the article through the Table API. "
            "The approved fallback is publish_article. It is not installed."
        )
    print(f"knowledge: workflow_state={workflow or 'none'} status={evidence['publish_status']}")
    return _result(question, calls, evidence, decision, reason)


def _create_article(
    admin: ServiceNowClient,
    settings: Settings,
    user: dict[str, Any],
    passwords: dict[str, str],
    secret_bag: list[str],
    base_id: str,
) -> dict[str, Any]:
    bodies = [
        (
            "kb_knowledge",
            {
                "short_description": f"{MARKER} known error",
                "kb_knowledge_base": base_id,
                "text": f"{MARKER} cause and workaround.",
                "workflow_state": "draft",
            },
        ),
        (
            "kb_template_known_error_article",
            {
                "short_description": f"{MARKER} known error",
                "kb_knowledge_base": base_id,
                "kb_description": f"{MARKER} description",
                "kb_cause": f"{MARKER} cause",
                "kb_workaround": f"{MARKER} workaround",
                "workflow_state": "draft",
            },
        ),
    ]

    def attempt(table: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            with _as_user(settings, PROBLEM_USER, passwords[PROBLEM_USER], secret_bag) as actor:
                record = actor.create_record(table, body)
            return {"ok": True, "status": 200, "table": table, "sys_id": record.get("sys_id")}
        except ServiceNowError as exc:
            return {"ok": False, "status": exc.status_code, "table": table, "sys_id": ""}

    last: dict[str, Any] = {"ok": False, "status": None, "table": "", "sys_id": ""}
    for table, body in bodies:
        last = _ensure(
            admin,
            user,
            (*PROBLEM_LADDER, *KNOWLEDGE_LADDER),
            lambda table=table, body=body: attempt(table, body),
        )
        if last.get("ok") and last.get("sys_id"):
            return last
    return last


def _role_summary(
    users: dict[str, dict[str, Any]],
    probes: dict[str, Any],
) -> dict[str, Any]:
    problem_granted = list(users[PROBLEM_USER]["granted"])
    evidence = {
        "incident": list(users[INCIDENT_USER]["granted"]),
        "problem": [role for role in problem_granted if role not in KNOWLEDGE_LADDER],
        "knowledge": [role for role in problem_granted if role in KNOWLEDGE_LADDER],
        "authority": list(users[APPROVER_USER]["granted"]),
    }
    duties = ("approval", "parent", "rfc", "states", "knowledge")
    duties_ok = all(
        (probes.get(name) or {}).get("decision") in {"verified", "approved-fallback"}
        for name in duties
    )
    print(
        "roles:"
        f" authority={evidence['authority']} problem={evidence['problem']}"
        f" knowledge={evidence['knowledge']} incident={evidence['incident']}"
    )
    return _result(
        "What is the smallest role set for each new user, found one role at a time?",
        ["role grants recorded on the probe that first returned HTTP 403"],
        evidence,
        "verified" if duties_ok else "failed",
        "Duty roles were added only after HTTP 403. "
        "snc_basic_auth_api_access was added only when login failed. admin was not granted.",
    )


def _insert_with_ladder(
    admin: ServiceNowClient,
    settings: Settings,
    user: dict[str, Any],
    password: str,
    secret_bag: list[str],
    ladder: tuple[str, ...],
    table: str,
    body: dict[str, Any],
) -> str:
    username = PROBLEM_USER if table == "problem" else INCIDENT_USER

    def insert() -> dict[str, Any]:
        try:
            with _as_user(settings, username, password, secret_bag) as actor:
                record = actor.create_record(table, body)
            return {"ok": True, "status": 200, "sys_id": record.get("sys_id")}
        except ServiceNowError as exc:
            return {"ok": False, "status": exc.status_code, "sys_id": ""}

    result = _ensure(admin, user, ladder, insert)
    return str(result.get("sys_id") or "")


def _read_count(
    settings: Settings,
    username: str,
    password: str,
    secret_bag: list[str],
    table: str,
    query: str,
) -> int | None:
    try:
        with _as_user(settings, username, password, secret_bag) as actor:
            rows = actor.get_table(table, query=query, fields=["sys_id"], limit=5)
    except ServiceNowError:
        return None
    return len(rows)


def _transitions(admin: ServiceNowClient, model_id: str) -> list[dict[str, str]]:
    """Edges on the problem's state model.

    `prb_model` extends `sttrm_model`. States live on `sttrm_state.sttrm_model`.
    Transitions point at those rows through `from_state` and `to_state`.
    """
    if not model_id:
        return []
    try:
        states = admin.get_table(
            "sttrm_state",
            query=f"sttrm_model={model_id}",
            fields=["sys_id", "state_value"],
            limit=40,
        )
    except ServiceNowError:
        return []
    values = {
        str(row.get("sys_id") or ""): str(row.get("state_value") or "")
        for row in states
        if row.get("sys_id") and row.get("state_value")
    }
    if not values:
        return []
    try:
        rows = admin.get_table(
            "sttrm_state_transition",
            query="from_stateIN" + ",".join(values),
            fields=["from_state", "to_state", "name"],
            limit=40,
        )
    except ServiceNowError:
        return []
    resolved = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        source = values.get(str(row.get("from_state") or ""))
        target = values.get(str(row.get("to_state") or ""))
        if not source or not target:
            continue
        edge = (source, target)
        if edge in seen:
            continue
        seen.add(edge)
        resolved.append({"from": source, "to": target})
    return resolved


def _path_from(start: str, transitions: list[dict[str, str]]) -> list[str]:
    """One walk from `start`. Prefer the next higher state value over a jump or a return."""
    by_source: dict[str, list[str]] = {}
    for row in transitions:
        by_source.setdefault(row["from"], []).append(row["to"])
    path: list[str] = []
    seen = {start}
    current = start
    while current in by_source and len(path) < 8:
        options = [item for item in by_source[current] if item not in seen]
        if not options:
            break
        nxt = min(options, key=lambda item: _edge_rank(current, item))
        path.append(nxt)
        seen.add(nxt)
        current = nxt
    return path


def _edge_rank(current: str, target: str) -> tuple[int, int, str]:
    try:
        current_n = int(current)
        target_n = int(target)
    except ValueError:
        return (1, 0, target)
    if target_n > current_n:
        return (0, target_n, target)
    return (1, target_n, target)


def _dictionary(admin: ServiceNowClient) -> dict[str, Any]:
    found = {}
    for table, element in (
        ("incident", "u_caused_by"),
        ("incident", "problem_id"),
        ("incident", "rfc"),
        ("task", "problem_id"),
        ("problem", "rfc"),
        ("problem", "state"),
        ("task", "state"),
        ("task", "parent"),
    ):
        try:
            rows = admin.get_table(
                "sys_dictionary",
                query=f"name={table}^element={element}",
                fields=["name", "element", "internal_type", "reference", "read_only", "active"],
                limit=3,
            )
        except ServiceNowError as exc:
            found[f"{table}.{element}"] = {"error": exc.status_code}
            continue
        found[f"{table}.{element}"] = [
            {
                "internal_type": row.get("internal_type"),
                "reference": row.get("reference"),
                "read_only": row.get("read_only"),
                "active": row.get("active"),
            }
            for row in rows
        ]
    return found


def _choices(admin: ServiceNowClient) -> dict[str, list[dict[str, Any]]]:
    found = {}
    for table, element in (
        ("incident", "state"),
        ("incident", "close_code"),
        ("problem", "state"),
        ("problem", "resolution_code"),
        ("problem", "close_code"),
    ):
        query = f"name={table}^element={element}^language=en"
        try:
            rows = admin.get_table(
                "sys_choice",
                query=query,
                fields=["value", "label", "inactive"],
                limit=80,
            )
        except ServiceNowError:
            rows = []
        if not rows:
            try:
                rows = admin.get_table(
                    "sys_choice",
                    query=f"name={table}^element={element}",
                    fields=["value", "label", "inactive"],
                    limit=80,
                )
            except ServiceNowError:
                rows = []
        found[f"{table}.{element}"] = [
            {
                "value": row.get("value"),
                "label": row.get("label"),
                "inactive": row.get("inactive"),
            }
            for row in rows
        ]
    return found


def _print_choices(choices: dict[str, list[dict[str, Any]]]) -> None:
    for name, rows in choices.items():
        active = [
            f"{row['value']}={row['label']}"
            for row in rows
            if str(row.get("inactive")).lower() not in {"true", "1"}
        ]
        print(f"choices {name}: {', '.join(active) if active else 'none'}")


def _active_value(rows: list[dict[str, Any]], label: str) -> str | None:
    for row in rows:
        if str(row.get("inactive")).lower() in {"true", "1"}:
            continue
        if str(row.get("label") or "").lower() == label.lower():
            return str(row.get("value"))
    return None


def _named_group(client: ServiceNowClient, name: str) -> str:
    rows = client.get_table(
        "sys_user_group",
        query=f"name={name}",
        fields=["sys_id"],
        limit=1,
    )
    return str(rows[0]["sys_id"]) if rows else ""


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
    client: ServiceNowClient,
    change_id: str,
    wanted: set[str],
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while True:
        last = client.get_record(
            "change_request",
            change_id,
            fields=["state", "approval", "number"],
        )
        if str(last.get("state") or "") in wanted or time.monotonic() >= deadline:
            return last
        time.sleep(2)


def _poll_rows(
    client: ServiceNowClient,
    table: str,
    query: str,
    fields: list[str],
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + 25
    rows: list[dict[str, Any]] = []
    while True:
        rows = client.get_table(table, query=query, fields=fields, limit=10)
        if rows or time.monotonic() >= deadline:
            return rows
        time.sleep(2)


def _result(
    question: str,
    calls: list[str],
    evidence: dict[str, Any],
    decision: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "question": question,
        "calls": calls,
        "evidence": evidence,
        "decision": decision,
        "reason": reason,
    }


def _cleanup(client: ServiceNowClient) -> None:
    for table, query in (
        ("kb_template_known_error_article", f"short_descriptionSTARTSWITH{MARKER}"),
        ("kb_knowledge", f"short_descriptionSTARTSWITH{MARKER}"),
        ("incident", f"short_descriptionSTARTSWITH{MARKER}^ORcorrelation_idSTARTSWITH{MARKER}"),
        ("problem", f"short_descriptionSTARTSWITH{MARKER}^ORcorrelation_idSTARTSWITH{MARKER}"),
    ):
        _delete_where(client, table, query)
    changes = _safe_rows(
        client,
        "change_request",
        f"short_descriptionSTARTSWITH{MARKER}^ORcorrelation_idSTARTSWITH{MARKER}",
        ["sys_id"],
    )
    for change in changes:
        change_id = str(change.get("sys_id") or "")
        if not change_id:
            continue
        _delete_where(client, "sysapproval_approver", f"sysapproval={change_id}")
        _delete_where(client, "sysapproval_group", f"parent={change_id}")
        _delete_where(client, "change_task", f"change_request={change_id}^ORparent={change_id}")
        _delete_where(client, "task_ci", f"task={change_id}")
        _delete_where(client, "conflict", f"change={change_id}^ORconflicting_change={change_id}")
        _delete_id(client, "change_request", change_id)
    users = _safe_rows(
        client,
        "sys_user",
        f"first_name={MARKER}^ORuser_nameSTARTSWITHsyn.probe.",
        ["sys_id"],
    )
    for user in users:
        user_id = str(user.get("sys_id") or "")
        if not user_id:
            continue
        _delete_where(client, "sys_user_grmember", f"user={user_id}")
        _delete_where(client, "sys_user_has_role", f"user={user_id}^inherited=false")
        _delete_id(client, "sys_user", user_id)


def _residue(client: ServiceNowClient) -> list[dict[str, Any]]:
    text = f"short_descriptionSTARTSWITH{MARKER}"
    correlation = f"correlation_idSTARTSWITH{MARKER}"
    queries = [
        ("change_request", f"{text}^OR{correlation}"),
        ("change_task", f"{text}^ORchange_request.short_descriptionSTARTSWITH{MARKER}"),
        ("incident", f"{text}^OR{correlation}"),
        ("problem", f"{text}^OR{correlation}"),
        ("kb_knowledge", f"short_descriptionSTARTSWITH{MARKER}"),
        ("task_ci", f"task.short_descriptionSTARTSWITH{MARKER}"),
        ("sysapproval_approver", f"sysapproval.short_descriptionSTARTSWITH{MARKER}"),
        ("sysapproval_group", f"parent.short_descriptionSTARTSWITH{MARKER}"),
        ("sys_user", f"first_name={MARKER}^ORuser_nameSTARTSWITHsyn.probe."),
        ("sys_user_grmember", "user.first_name=SYN-PROBE"),
        ("sys_user_has_role", "user.first_name=SYN-PROBE^inherited=false"),
    ]
    results = []
    for table, query in queries:
        try:
            rows = client.get_table(table, query=query, fields=["sys_id"], limit=20)
        except ServiceNowError as exc:
            results.append({"table": table, "count": None, "status": exc.status_code})
            continue
        results.append({"table": table, "count": len(rows)})
    return results


def _print_residue(rows: list[dict[str, Any]]) -> None:
    print("SYN-PROBE residue:")
    for row in rows:
        if row.get("count") is None:
            print(f"  {row['table']}: error HTTP {row.get('status')}")
        else:
            print(f"  {row['table']}: {row['count']}")


def _safe_rows(
    client: ServiceNowClient,
    table: str,
    query: str,
    fields: list[str],
) -> list[dict[str, Any]]:
    try:
        return client.get_table(table, query=query, fields=fields, limit=50)
    except ServiceNowError:
        return []


def _delete_where(client: ServiceNowClient, table: str, query: str) -> None:
    for row in _safe_rows(client, table, query, ["sys_id"]):
        _delete_id(client, table, str(row.get("sys_id") or ""))


def _delete_id(client: ServiceNowClient, table: str, sys_id: str) -> None:
    if not _SYS_ID.fullmatch(sys_id):
        return
    try:
        client.delete_record(table, sys_id)
    except ServiceNowError:
        return


def _write(evidence: dict[str, Any], secret_bag: list[str]) -> None:
    path = repo_root() / "docs" / "DISCOVERY.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = redact_text(render_discovery(evidence), secret_bag)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path.name}")


def render_discovery(evidence: dict[str, Any]) -> str:
    lines = [
        "# Discovery",
        "",
        "Phase 0 probes for the end-to-end workflow. API paths are relative to the instance. "
        "Secrets and the instance host are omitted. Probe rows use the SYN-PROBE marker and "
        "are deleted before the command returns.",
        "",
        "## Email gate",
        "",
        str((evidence.get("email") or {}).get("line") or "not run"),
        "",
    ]
    dictionary = evidence.get("dictionary") or {}
    lines.extend(["## Dictionary", ""])
    for name, rows in dictionary.items():
        lines.append(f"- `{name}`: {rows}")
    lines.append("")
    lines.extend(["## Choice values", ""])
    for name, rows in (evidence.get("choices") or {}).items():
        shown = ", ".join(
            f"`{row.get('value')}` {row.get('label')}"
            + (" inactive" if str(row.get("inactive")).lower() in {"true", "1"} else "")
            for row in rows
        )
        lines.append(f"- `{name}`: {shown or 'no rows'}")
    lines.append("")
    for key in ("approval", "parent", "rfc", "states", "knowledge", "roles"):
        probe = (evidence.get("probes") or {}).get(key)
        if not probe:
            continue
        lines.extend(
            [
                f"## {key}",
                "",
                probe["question"],
                "",
                "Calls:",
                "",
            ]
        )
        for call in probe.get("calls") or []:
            lines.append(f"- `{call}`")
        lines.extend(["", "Evidence:", "", "```", _dump(probe.get("evidence")), "```", ""])
        lines.append(f"Decision: **{probe.get('decision')}**. {probe.get('reason')}")
        lines.append("")
    if evidence.get("error"):
        lines.extend(["## Error", "", str(evidence["error"]), ""])
    lines.extend(["## Residue", ""])
    for row in evidence.get("residue") or []:
        lines.append(f"- `{row.get('table')}`: {row.get('count')}")
    lines.extend(["", "## Section 8", ""])
    lines.extend(_section_lines(evidence))
    lines.append("")
    return "\n".join(lines)


def _state_note(decision: object) -> str:
    if decision == "approved-fallback":
        return "Scripted REST is the approved fallback and is not installed."
    if decision == "partial":
        return "A partial walk is not the approved fallback. The endpoint was not installed."
    return "Recorded from the Table API walk."


def _section_lines(evidence: dict[str, Any]) -> list[str]:
    probes = evidence.get("probes") or {}
    dictionary = evidence.get("dictionary") or {}
    caused = dictionary.get("incident.u_caused_by")
    problem_id = dictionary.get("incident.problem_id")
    rows = [
        (
            "incident.u_caused_by",
            "verified" if isinstance(caused, list) and caused else "not read",
            "Re-read on this PDI.",
        ),
        (
            "incident.problem_id",
            "absent" if problem_id == [] else "see dictionary",
            "Use incident.parent.",
        ),
        (
            "non-admin approval",
            (probes.get("approval") or {}).get("decision", "not run"),
            "Scripted approval is not a fallback.",
        ),
        (
            "incident.parent",
            (probes.get("parent") or {}).get("decision", "not run"),
            "Custom field fallback is not approved.",
        ),
        (
            "problem.rfc",
            (probes.get("rfc") or {}).get("decision", "not run"),
            "Fallback is a work note plus change.parent.",
        ),
        (
            "problem.state Table API",
            (probes.get("states") or {}).get("decision", "not run"),
            _state_note((probes.get("states") or {}).get("decision")),
        ),
        (
            "Known Error publish",
            (probes.get("knowledge") or {}).get("decision", "not run"),
            "publish_article is the approved fallback and is not installed.",
        ),
        (
            "least roles",
            (probes.get("roles") or {}).get("decision", "not run"),
            "One role at a time. admin was not granted.",
        ),
        (
            "choice values",
            "verified" if evidence.get("choices") else "not run",
            "Read from sys_choice.",
        ),
    ]
    return [f"- `{name}`: {status}. {note}" for name, status, note in rows]


def _dump(value: object) -> str:
    import json

    return json.dumps(value, indent=2, default=str)
