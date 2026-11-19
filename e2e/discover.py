"""Phase 0 probes. Every SYN-PROBE row is deleted before this command returns."""

from __future__ import annotations

import re
import secrets
import time
from typing import Any

from cm_agents.discover import evaluate_outbound_email
from cm_agents.servicenow.client import ServiceNowClient, ServiceNowError
from cm_agents.settings import redact_text

from e2e import state_api
from e2e.settings import Settings, repo_root

MARKER = "SYN-PROBE"
ENDPOINT_MARKER = state_api.PROBE_TAG
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
            evidence["probes"]["problem_state"] = _problem_state_probe(
                admin,
                settings,
                users,
                passwords,
                secret_bag,
                evidence["dictionary"],
                evidence["choices"],
            )
            evidence["probes"]["endpoint"] = _endpoint_probe(
                admin,
                settings,
                users,
                passwords,
                secret_bag,
                evidence["probes"]["problem_state"],
                evidence["choices"],
            )
            evidence["probes"]["incident_writes"] = _incident_write_probe(
                admin, settings, users, passwords, secret_bag, evidence["choices"]
            )
            evidence["probes"]["problem_writes"] = _problem_write_probe(
                admin,
                settings,
                users,
                passwords,
                secret_bag,
                _article_id(evidence),
            )
            evidence["probes"]["roles"] = _role_summary(users, evidence["probes"])
        except Exception as exc:
            failed = True
            evidence["error"] = redact_text(f"{type(exc).__name__}: {exc}", secret_bag)[:500]
            print(f"discovery probe failed: {type(exc).__name__}")
        finally:
            _cleanup(admin)
            evidence["residue"] = _residue(admin)
            _mark_endpoint_removed(evidence)
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
    for name in ("parent", "rfc"):
        decision = (probes.get(name) or {}).get("decision")
        if decision not in {"verified", "approved-fallback"}:
            print(f"{name}: not verified")
            return True
    if not _states_resolved(probes):
        print("states: not verified")
        return True
    if not _publish_resolved(probes):
        print("knowledge: not verified")
        return True
    for name in ("incident_writes", "problem_writes", "roles"):
        decision = (probes.get(name) or {}).get("decision")
        if decision not in {"verified", "approved-fallback"}:
            print(f"{name}: not verified")
            return True
    if not evidence.get("choices"):
        return True
    return False


def _states_resolved(probes: dict[str, Any]) -> bool:
    """A partial Table API walk does not pass. problem_state or the move operation must."""
    if (probes.get("problem_state") or {}).get("decision") == "verified":
        return True
    move = ((probes.get("endpoint") or {}).get("evidence") or {}).get("move") or {}
    return move.get("decision") == "verified"


def _publish_resolved(probes: dict[str, Any]) -> bool:
    if (probes.get("knowledge") or {}).get("decision") == "verified":
        return True
    publish = ((probes.get("endpoint") or {}).get("evidence") or {}).get("publish") or {}
    return publish.get("decision") == "verified"


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


def _ensure_progress(
    admin: ServiceNowClient,
    user: dict[str, Any],
    ladder: tuple[str, ...],
    operation,
) -> dict[str, Any]:
    """Add the next role after HTTP 403, or after HTTP 200 that did not stick.

    A business-rule abort is not a missing role. The caller records it and tries
    another payload before this loop grants anything.
    """
    result = operation()
    while not result.get("business_rule") and (
        result.get("status") == 403 or result.get("stuck")
    ):
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
    user_row = admin.get_record(
        "sys_user",
        str(user["sys_id"]),
        fields=["web_service_access_only", "active"],
    )
    direct_rows = admin.get_table(
        "sys_user_has_role",
        query=f"user={user['sys_id']}^inherited=false",
        fields=["sys_id"],
        limit=20,
    )
    named_roles = _safe_rows(
        admin,
        "sys_user_has_role",
        f"user={user['sys_id']}^inherited=false",
        ["role.name"],
    )
    named_groups = _safe_rows(
        admin,
        "sys_user_grmember",
        f"user={user['sys_id']}",
        ["group.name"],
    )
    membership_names = [
        str(row.get("group.name") or "") for row in named_groups if row.get("group.name")
    ]
    if not membership_names:
        membership_names = [name for name, group_id in groups.items() if group_id]
    evidence = {
        "groups": {name: bool(group_id) for name, group_id in groups.items()},
        "memberships": len(memberships),
        "membership_names": membership_names,
        "roles": list(user["granted"]),
        "direct_roles": [
            str(row.get("role.name") or "") for row in named_roles if row.get("role.name")
        ],
        "direct_role_count": len(direct_rows),
        "web_service_access_only": user_row.get("web_service_access_only"),
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
        f" direct={evidence['direct_role_count']}"
        f" web_service_access_only={evidence['web_service_access_only']}"
        f" groups={','.join(evidence['membership_names']) or 'none'}"
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
        names = ", ".join(evidence.get("membership_names") or []) or "none"
        direct = evidence.get("direct_role_count")
        wsao = evidence.get("web_service_access_only")
        return (
            "The approval probe user had no direct role "
            f"(direct_role_count={direct}). "
            "The probe inserted Change Management and CAB Approval. "
            f"sys_user_grmember read back: {names}. "
            f"web_service_access_only={wsao}. "
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
            "The endpoint probe is a separate row."
        )
    elif attempts:
        decision = "partial"
        reason = (
            "The Table API moved some states and stopped. "
            "A partial walk is not the approved fallback."
        )
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
            "publish_article is the approved fallback. The endpoint probe records it."
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
    marker: str = MARKER,
) -> dict[str, Any]:
    bodies = [
        (
            "kb_knowledge",
            {
                "short_description": f"{marker} known error",
                "kb_knowledge_base": base_id,
                "text": f"{MARKER} cause and workaround.",
                "workflow_state": "draft",
            },
        ),
        (
            "kb_template_known_error_article",
            {
                "short_description": f"{marker} known error",
                "kb_knowledge_base": base_id,
                "kb_description": f"{marker} description",
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


def _problem_state_fields(target: str, user_id: str, *, full: bool) -> dict[str, str]:
    """Fields the happy-path edge into `target` requires. A full retry adds the close set."""
    note = f"{MARKER} notes"
    if full:
        return {
            "assigned_to": user_id,
            "cause_notes": note,
            "fix_notes": note,
            "close_notes": note,
            "resolution_code": "fix_applied",
        }
    if target == "102":
        return {"assigned_to": user_id}
    if target == "104":
        return {"cause_notes": note, "fix_notes": note}
    return {}


def _read_problem(admin: ServiceNowClient, problem_id: str) -> dict[str, str]:
    row = admin.get_record("problem", problem_id, fields=["state", "problem_state", "prb_model"])
    return {
        "state": str(row.get("state") or ""),
        "problem_state": str(row.get("problem_state") or ""),
        "prb_model": str(row.get("prb_model") or ""),
    }


def _patch_as(
    settings: Settings,
    username: str,
    password: str,
    secret_bag: list[str],
    table: str,
    sys_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    try:
        with _as_user(settings, username, password, secret_bag) as actor:
            updated = actor.update_record(table, sys_id, body)
        return {"ok": True, "status": 200, "returned": updated}
    except ServiceNowError as exc:
        return {"ok": False, "status": exc.status_code, "returned": {}, "error": str(exc)[:300]}


def _problem_state_probe(
    admin: ServiceNowClient,
    settings: Settings,
    users: dict[str, dict[str, Any]],
    passwords: dict[str, str],
    secret_bag: list[str],
    dictionary: dict[str, Any],
    choices: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    question = (
        "Does writing problem_state, with the fields each state requires, "
        "move state through every state to Closed?"
    )
    calls = [
        "GET sys_dictionary name=problem^element=problem_state",
        "PATCH /api/now/table/problem/{sys_id} problem_state",
        "GET /api/now/table/problem/{sys_id} state",
    ]
    row = dictionary.get("problem.problem_state")
    present = isinstance(row, list) and bool(row)
    if not present:
        print("problem_state: field absent")
        return _result(
            question,
            calls,
            {"dictionary": row},
            "absent",
            "problem.problem_state is not on this table. Both endpoint operations are approved.",
        )
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
            "short_description": f"{MARKER} problem_state",
            "description": f"{MARKER} problem_state probe",
            "correlation_id": f"{MARKER}-problem-state",
        },
    )
    if not problem_id:
        print("problem_state: problem was not created")
        return _result(
            question,
            calls,
            {"dictionary": row, "created": False},
            "failed",
            "The problem_state probe could not create a problem.",
        )
    current = _read_problem(admin, problem_id)
    transitions = _transitions(admin, current["prb_model"])
    path = _path_from(current["state"], transitions)
    closed = _active_value(choices.get("problem.state") or [], "Closed") or "107"
    attempts = _walk_problem_state(
        admin,
        settings,
        problem_user,
        passwords,
        secret_bag,
        problem_id,
        path,
    )
    moved = [item["requested"] for item in attempts if item.get("after") == item.get("requested")]
    reached = bool(path) and len(moved) == len(path) and str(moved[-1]) == str(closed)
    evidence = {
        "dictionary": row,
        "start": current["state"],
        "path": path,
        "closed": closed,
        "attempts": attempts,
        "roles": list(problem_user["granted"]),
    }
    if reached:
        decision = "verified"
        reason = "Writing problem_state moved state through every state to Closed."
    elif attempts:
        decision = "failed"
        reason = (
            "Writing problem_state did not move state through every state to Closed. "
            "Both endpoint operations are approved."
        )
    else:
        decision = "failed"
        reason = "No problem state path was found to attempt with problem_state."
    print(f"problem_state: present path={len(path)} moved={len(moved)} decision={decision}")
    return _result(question, calls, evidence, decision, reason)


def _walk_problem_state(
    admin: ServiceNowClient,
    settings: Settings,
    user: dict[str, Any],
    passwords: dict[str, str],
    secret_bag: list[str],
    problem_id: str,
    path: list[str],
) -> list[dict[str, Any]]:
    attempts = []
    for target in path:
        attempt = _write_problem_state(
            admin, settings, user, passwords, secret_bag, problem_id, target, full=False
        )
        if attempt.get("after") != target and attempt.get("status") == 200:
            retry = _write_problem_state(
                admin, settings, user, passwords, secret_bag, problem_id, target, full=True
            )
            attempt["retry"] = retry
            attempt["after"] = retry.get("after")
            attempt["read_problem_state"] = retry.get("read_problem_state")
        attempts.append(attempt)
        print(
            "problem_state write:"
            f" {attempt.get('before')}->{target} status={attempt.get('status')}"
            f" read_state={attempt.get('after')}"
            f" read_problem_state={attempt.get('read_problem_state')}"
        )
        if attempt.get("after") != target:
            break
    return attempts


def _write_problem_state(
    admin: ServiceNowClient,
    settings: Settings,
    user: dict[str, Any],
    passwords: dict[str, str],
    secret_bag: list[str],
    problem_id: str,
    target: str,
    *,
    full: bool,
) -> dict[str, Any]:
    before = _read_problem(admin, problem_id)["state"]
    fields = _problem_state_fields(target, str(user["sys_id"]), full=full)
    body = {"problem_state": target, **fields}

    def write() -> dict[str, Any]:
        written = _patch_as(
            settings,
            PROBLEM_USER,
            passwords[PROBLEM_USER],
            secret_bag,
            "problem",
            problem_id,
            body,
        )
        returned = written.get("returned") or {}
        return {
            "ok": written.get("status") == 200,
            "status": written.get("status"),
            "returned_state": returned.get("state"),
            "returned_problem_state": returned.get("problem_state"),
            "error": written.get("error"),
        }

    written = _ensure(admin, user, PROBLEM_LADDER, write)
    read = _read_problem(admin, problem_id)
    return {
        "before": before,
        "requested": target,
        "fields": sorted(fields),
        "full": full,
        "status": written.get("status"),
        "returned_state": written.get("returned_state"),
        "returned_problem_state": written.get("returned_problem_state"),
        "after": read["state"],
        "read_problem_state": read["problem_state"],
        "error": redact_text(str(written.get("error") or ""), secret_bag)[:300],
        "role_added": written.get("role_added"),
    }


def _endpoint_probe(
    admin: ServiceNowClient,
    settings: Settings,
    users: dict[str, dict[str, Any]],
    passwords: dict[str, str],
    secret_bag: list[str],
    problem_state: dict[str, Any],
    choices: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    question = (
        "Can the problem user finish the state walk and publish a Known Error "
        "through the temporary endpoint?"
    )
    calls = [
        "POST sys_ws_definition service_id=syne2e_problem_state",
        "POST the installed operation as the problem user",
        "DELETE sys_ws_operation and sys_ws_definition in cleanup",
    ]
    verified = problem_state.get("decision") == "verified"
    operations = state_api.operations_for(problem_state_verified=verified)
    print(f"endpoint install: operations={','.join(operations)}")
    try:
        installed = state_api.install(admin, operations)
    except ServiceNowError as exc:
        print(f"endpoint install: HTTP {exc.status_code}")
        return _result(
            question,
            calls,
            {
                "operations": list(operations),
                "install_status": exc.status_code,
                "removed": False,
            },
            "failed",
            "The endpoint was not installed. Cleanup still removes it if a row was created.",
        )
    base_uri = str(installed.get("base_uri") or "")
    evidence: dict[str, Any] = {
        "operations": [row["name"] for row in installed.get("operations") or []],
        "base_uri_present": bool(base_uri),
        "install_status": 200,
        "removed": False,
    }
    if "move" in operations:
        evidence["move"] = _endpoint_move(
            admin, settings, users, passwords, secret_bag, base_uri, choices
        )
    else:
        evidence["move"] = {
            "decision": "skipped",
            "reason": "problem_state moved every state to Closed.",
        }
    evidence["publish"] = _endpoint_publish(
        admin, settings, users, passwords, secret_bag, base_uri
    )
    move_ok = evidence["move"].get("decision") in {"verified", "skipped"}
    publish_ok = evidence["publish"].get("decision") == "verified"
    decision = "verified" if move_ok and publish_ok and base_uri else "failed"
    reason = (
        "The problem user finished the installed operations. "
        "Cleanup removes the endpoint before the phase ends."
        if decision == "verified"
        else "An installed operation did not finish for the problem user."
    )
    print(
        "endpoint:"
        f" move={evidence['move'].get('decision')}"
        f" publish={evidence['publish'].get('decision')}"
    )
    return _result(question, calls, evidence, decision, reason)


def _endpoint_move(
    admin: ServiceNowClient,
    settings: Settings,
    users: dict[str, dict[str, Any]],
    passwords: dict[str, str],
    secret_bag: list[str],
    base_uri: str,
    choices: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
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
            "short_description": f"{ENDPOINT_MARKER} move",
            "description": f"{ENDPOINT_MARKER} move probe",
            "correlation_id": f"{ENDPOINT_MARKER}-move",
        },
    )
    if not problem_id or not base_uri:
        return {"decision": "failed", "created": bool(problem_id), "attempts": []}
    current = _read_problem(admin, problem_id)
    path = _path_from(current["state"], _transitions(admin, current["prb_model"]))
    closed = _active_value(choices.get("problem.state") or [], "Closed") or "107"
    attempts = []
    for target in path:
        attempt = _endpoint_move_target(
            admin,
            settings,
            problem_user,
            passwords,
            secret_bag,
            base_uri,
            problem_id,
            target,
            full=False,
        )
        if attempt.get("after") != target and attempt.get("status") != 403:
            retry = _endpoint_move_target(
                admin,
                settings,
                problem_user,
                passwords,
                secret_bag,
                base_uri,
                problem_id,
                target,
                full=True,
            )
            attempt["retry"] = retry
            attempt["after"] = retry.get("after")
        attempts.append(attempt)
        print(
            "endpoint move:"
            f" {attempt.get('before')}->{target} status={attempt.get('status')}"
            f" read_state={attempt.get('after')}"
        )
        if attempt.get("after") != target:
            break
    moved = [item["requested"] for item in attempts if item.get("after") == item.get("requested")]
    reached = bool(path) and len(moved) == len(path) and str(moved[-1]) == str(closed)
    return {
        "decision": "verified" if reached else "failed",
        "start": current["state"],
        "path": path,
        "closed": closed,
        "attempts": attempts,
        "roles": list(problem_user["granted"]),
    }


def _endpoint_move_target(
    admin: ServiceNowClient,
    settings: Settings,
    user: dict[str, Any],
    passwords: dict[str, str],
    secret_bag: list[str],
    base_uri: str,
    problem_id: str,
    target: str,
    *,
    full: bool,
) -> dict[str, Any]:
    before = _read_problem(admin, problem_id)["state"]
    fields = _problem_state_fields(target, str(user["sys_id"]), full=full)

    def write() -> dict[str, Any]:
        try:
            with _as_user(settings, PROBLEM_USER, passwords[PROBLEM_USER], secret_bag) as actor:
                response = state_api.post_operation(
                    actor,
                    base_uri,
                    "move",
                    {"sys_id": problem_id, "state": target, "fields": fields},
                )
        except ServiceNowError as exc:
            response = {"status": exc.status_code, "result": {}, "error": str(exc)[:300]}
        result = response.get("result") or {}
        return {
            "ok": response.get("status") != 403,
            "status": response.get("status"),
            "returned_state": result.get("state"),
            "script_ok": result.get("ok"),
            "error": redact_text(
                str(response.get("error") or result.get("error") or ""),
                secret_bag,
            )[:300],
        }

    written = _ensure(admin, user, PROBLEM_LADDER, write)
    after = _read_problem(admin, problem_id)["state"]
    return {
        "before": before,
        "requested": target,
        "fields": sorted(fields),
        "full": full,
        "status": written.get("status"),
        "returned_state": written.get("returned_state"),
        "script_ok": written.get("script_ok"),
        "after": after,
        "error": written.get("error"),
        "role_added": written.get("role_added"),
    }


def _endpoint_publish(
    admin: ServiceNowClient,
    settings: Settings,
    users: dict[str, dict[str, Any]],
    passwords: dict[str, str],
    secret_bag: list[str],
    base_uri: str,
) -> dict[str, Any]:
    bases = admin.get_table(
        "kb_knowledge_base",
        query="title=Known Error^active=true",
        fields=["sys_id"],
        limit=1,
    )
    if not bases or not base_uri:
        return {"decision": "failed", "reason": "Known Error base or base URI was missing"}
    problem_user = users[PROBLEM_USER]
    created = _create_article(
        admin,
        settings,
        problem_user,
        passwords,
        secret_bag,
        str(bases[0]["sys_id"]),
        marker=ENDPOINT_MARKER,
    )
    article_id = str(created.get("sys_id") or "")
    if not article_id:
        return {"decision": "failed", "create_status": created.get("status"), "sys_id": ""}
    attempts = []
    workflow = ""
    while True:
        try:
            with _as_user(settings, PROBLEM_USER, passwords[PROBLEM_USER], secret_bag) as actor:
                response = state_api.post_operation(
                    actor,
                    base_uri,
                    "publish_article",
                    {"sys_id": article_id},
                )
        except ServiceNowError as exc:
            response = {"status": exc.status_code, "result": {}, "error": str(exc)[:300]}
        read = admin.get_record(
            "kb_knowledge",
            article_id,
            fields=["workflow_state", "published", "short_description"],
        )
        workflow = str(read.get("workflow_state") or "")
        result = response.get("result") or {}
        attempts.append(
            {
                "status": response.get("status"),
                "script_state": result.get("workflow_state"),
                "script_ok": result.get("ok"),
                "error": redact_text(
                    str(response.get("error") or result.get("error") or ""),
                    secret_bag,
                )[:300],
                "workflow_state": workflow,
                "roles": list(problem_user["granted"]),
            }
        )
        print(f"endpoint publish: status={response.get('status')} workflow_state={workflow}")
        if workflow == "published":
            break
        if response.get("status") not in {403, 409, 200}:
            break
        added = _add_role(admin, problem_user, KNOWLEDGE_LADDER)
        if added is None:
            break
    return {
        "decision": "verified" if workflow == "published" else "failed",
        "sys_id": article_id,
        "create_status": created.get("status"),
        "workflow_state": workflow,
        "attempts": attempts,
        "roles": list(problem_user["granted"]),
    }


def _incident_write_probe(
    admin: ServiceNowClient,
    settings: Settings,
    users: dict[str, dict[str, Any]],
    passwords: dict[str, str],
    secret_bag: list[str],
    choices: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    question = (
        "What smallest role set lets the incident user update an incident "
        "it did not create: category, priority inputs, assignment group, "
        "parent, a comment, and resolve with a close code?"
    )
    calls = [
        "POST /api/now/table/incident as admin",
        "PATCH category, impact, urgency, assignment_group, parent, comments, state",
    ]
    incident_user = users[INCIDENT_USER]
    group_id = _named_group(admin, "Service Desk")
    try:
        problem = admin.create_record(
            "problem",
            {
                "short_description": f"{MARKER} incident-writes",
                "correlation_id": f"{MARKER}-incident-writes",
            },
        )
        incident = admin.create_record(
            "incident",
            {
                "short_description": f"{MARKER} incident-writes",
                "description": f"{MARKER} created by admin",
                "correlation_id": f"{MARKER}-incident-writes",
                "caller_id": incident_user["sys_id"],
                "impact": "3",
                "urgency": "3",
            },
        )
    except ServiceNowError as exc:
        print(f"incident_writes: create HTTP {exc.status_code}")
        return _result(
            question,
            calls,
            {"status": exc.status_code},
            "failed",
            "Admin could not create the incident-write probe records.",
        )
    problem_id = str(problem.get("sys_id") or "")
    incident_id = str(incident.get("sys_id") or "")
    close_code = _active_value(choices.get("incident.close_code") or [], "Known error")
    close_code = close_code or "Known error"
    alternate_code = _active_value(choices.get("incident.close_code") or [], "Solution provided")
    alternate_code = alternate_code or "Solution provided"
    resolved = _active_value(choices.get("incident.state") or [], "Resolved") or "6"
    in_progress = _active_value(choices.get("incident.state") or [], "In Progress") or "2"
    roles_before = list(incident_user["granted"])
    steps = [
        _incident_step(
            admin,
            settings,
            incident_user,
            passwords,
            secret_bag,
            incident_id,
            "category",
            {"category": "software"},
            ["category"],
        ),
        _incident_step(
            admin,
            settings,
            incident_user,
            passwords,
            secret_bag,
            incident_id,
            "priority_inputs",
            {"impact": "2", "urgency": "2"},
            ["impact", "urgency", "priority"],
            expect={"impact": "2", "urgency": "2"},
            retry_body={"urgency": "2"},
        ),
        _incident_step(
            admin,
            settings,
            incident_user,
            passwords,
            secret_bag,
            incident_id,
            "assignment_group",
            {"assignment_group": group_id},
            ["assignment_group"],
            expect={"assignment_group": group_id} if group_id else None,
            blocked=not group_id,
        ),
        _incident_step(
            admin,
            settings,
            incident_user,
            passwords,
            secret_bag,
            incident_id,
            "work_notes",
            {"work_notes": f"{MARKER} assign"},
            ["work_notes"],
            journal="work_notes",
        ),
        _incident_step(
            admin,
            settings,
            incident_user,
            passwords,
            secret_bag,
            incident_id,
            "parent",
            {"parent": problem_id},
            ["parent"],
            expect={"parent": problem_id},
        ),
        _incident_step(
            admin,
            settings,
            incident_user,
            passwords,
            secret_bag,
            incident_id,
            "comment",
            {"comments": f"{MARKER} comment"},
            ["comments"],
            journal="comments",
        ),
        _incident_resolve_step(
            admin,
            settings,
            incident_user,
            passwords,
            secret_bag,
            incident_id,
            resolved,
            in_progress,
            close_code,
            alternate_code,
        ),
    ]
    resolve = steps[-1]
    if resolve.get("stuck"):
        shadow = _try_incident_state(
            admin,
            settings,
            passwords,
            secret_bag,
            incident_id,
            resolved,
            in_progress,
            close_code,
        )
        resolve["incident_state"] = shadow
        if shadow.get("stuck") is False:
            resolve["stuck"] = False
            resolve["via_incident_state"] = True
        else:
            resolve["admin_state"] = _admin_incident_state(
                admin, incident_id, resolved, in_progress, close_code
            )
    stuck = [step["name"] for step in steps if step.get("stuck")]
    roles_after = list(incident_user["granted"])
    evidence = {
        "created_by": "admin",
        "service_desk": bool(group_id),
        "steps": steps,
        "roles_before": roles_before,
        "roles_added": [role for role in roles_after if role not in roles_before],
        "roles": roles_after,
    }
    decision = "verified" if not stuck else "failed"
    print(f"incident_writes: stuck={stuck or 'none'} roles={evidence['roles']}")
    reason = (
        "Each incident-workflow write on an incident this user did not create read back. "
        "The next role was added only after HTTP 403 or a write that did not stick."
        if decision == "verified"
        else (
            "One or more incident-workflow writes did not read back "
            "after the incident role ladder."
        )
    )
    return _result(question, calls, evidence, decision, reason)


def _incident_step(
    admin: ServiceNowClient,
    settings: Settings,
    user: dict[str, Any],
    passwords: dict[str, str],
    secret_bag: list[str],
    incident_id: str,
    name: str,
    body: dict[str, Any],
    read_fields: list[str],
    expect: dict[str, str] | None = None,
    journal: str | None = None,
    blocked: bool = False,
    retry_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if blocked or (expect is not None and any(value == "" for value in expect.values())):
        return {"name": name, "stuck": True, "status": None, "error": "required target was missing"}
    expected = expect if expect is not None else {key: str(value) for key, value in body.items()}

    def write() -> dict[str, Any]:
        written = _patch_as(
            settings,
            INCIDENT_USER,
            passwords[INCIDENT_USER],
            secret_bag,
            "incident",
            incident_id,
            body,
        )
        if written.get("status") != 200:
            return {
                "ok": False,
                "status": written.get("status"),
                "stuck": True,
                "error": written.get("error"),
            }
        read = admin.get_record("incident", incident_id, fields=read_fields)
        if retry_body and _fields_stuck(read, expected):
            second = _patch_as(
                settings,
                INCIDENT_USER,
                passwords[INCIDENT_USER],
                secret_bag,
                "incident",
                incident_id,
                retry_body,
            )
            if second.get("status") == 403:
                return {"ok": False, "status": 403, "stuck": True, "error": second.get("error")}
            read = admin.get_record("incident", incident_id, fields=read_fields)
        journal_hit = None
        if journal:
            text = str(body.get(journal) or "")
            journal_hit = _journal_has(admin, "incident", incident_id, journal, text)
            record_hit = text in str(read.get(journal) or "")
            stuck = not (journal_hit.get("ok") or record_hit)
        else:
            stuck = any(
                str(read.get(key) or "") != str(wanted) for key, wanted in expected.items()
            )
        return {
            "ok": True,
            "status": 200,
            "stuck": stuck,
            "read": {key: read.get(key) for key in read_fields},
            "journal": journal_hit,
        }

    written = _ensure_progress(admin, user, INCIDENT_LADDER, write)
    return {
        "name": name,
        "status": written.get("status"),
        "stuck": bool(written.get("stuck", written.get("status") != 200)),
        "read": written.get("read"),
        "journal": written.get("journal"),
        "role_added": written.get("role_added"),
        "roles": list(user["granted"]),
        "error": redact_text(str(written.get("error") or ""), secret_bag)[:300],
    }


def _incident_resolve_step(
    admin: ServiceNowClient,
    settings: Settings,
    user: dict[str, Any],
    passwords: dict[str, str],
    secret_bag: list[str],
    incident_id: str,
    resolved: str,
    in_progress: str,
    close_code: str,
    alternate_code: str,
) -> dict[str, Any]:
    note = f"{MARKER} resolve"

    def attempt(code: str) -> dict[str, Any]:
        body = {"state": resolved, "close_code": code, "close_notes": note}
        first = _patch_as(
            settings,
            INCIDENT_USER,
            passwords[INCIDENT_USER],
            secret_bag,
            "incident",
            incident_id,
            body,
        )
        if first.get("status") == 403:
            error = str(first.get("error") or "")
            return {
                "ok": False,
                "status": 403,
                "stuck": True,
                "business_rule": "Business Rule" in error,
                "error": error,
                "close_code": code,
            }
        read = admin.get_record(
            "incident", incident_id, fields=["state", "close_code", "close_notes"]
        )
        via_in_progress = False
        status = first.get("status")
        if str(read.get("state") or "") != resolved and status == 200:
            via_in_progress = True
            middle = _patch_as(
                settings,
                INCIDENT_USER,
                passwords[INCIDENT_USER],
                secret_bag,
                "incident",
                incident_id,
                {"state": in_progress},
            )
            if middle.get("status") == 403:
                error = str(middle.get("error") or "")
                return {
                    "ok": False,
                    "status": 403,
                    "stuck": True,
                    "business_rule": "Business Rule" in error,
                    "via_in_progress": True,
                    "error": error,
                    "close_code": code,
                }
            second = _patch_as(
                settings,
                INCIDENT_USER,
                passwords[INCIDENT_USER],
                secret_bag,
                "incident",
                incident_id,
                body,
            )
            status = second.get("status")
            if status == 403:
                error = str(second.get("error") or "")
                return {
                    "ok": False,
                    "status": 403,
                    "stuck": True,
                    "business_rule": "Business Rule" in error,
                    "via_in_progress": True,
                    "error": error,
                    "close_code": code,
                }
            read = admin.get_record(
                "incident", incident_id, fields=["state", "close_code", "close_notes"]
            )
        state_ok = str(read.get("state") or "") == resolved
        code_ok = str(read.get("close_code") or "") == code
        return {
            "ok": status == 200 and state_ok and code_ok,
            "status": status,
            "stuck": not (state_ok and code_ok),
            "via_in_progress": via_in_progress,
            "close_code": code,
            "read": {
                "state": read.get("state"),
                "close_code": read.get("close_code"),
                "close_notes": read.get("close_notes"),
            },
        }

    def write() -> dict[str, Any]:
        primary = attempt(close_code)
        if not primary.get("business_rule"):
            return primary
        admin_status = _admin_close_status(admin, incident_id, resolved, close_code, note)
        alternate = attempt(alternate_code)
        alternate["known_error"] = {
            "close_code": close_code,
            "status": primary.get("status"),
            "business_rule": True,
            "admin_status": admin_status,
            "error": redact_text(str(primary.get("error") or ""), secret_bag)[:300],
        }
        return alternate

    written = _ensure_progress(admin, user, INCIDENT_LADDER, write)
    return {
        "name": "resolve",
        "status": written.get("status"),
        "stuck": bool(written.get("stuck", written.get("status") != 200)),
        "via_in_progress": written.get("via_in_progress"),
        "read": written.get("read"),
        "close_code": written.get("close_code") or close_code,
        "known_error": written.get("known_error"),
        "role_added": written.get("role_added"),
        "roles": list(user["granted"]),
        "error": redact_text(str(written.get("error") or ""), secret_bag)[:300],
    }


def _fields_stuck(read: dict[str, Any], expected: dict[str, str]) -> bool:
    return any(str(read.get(key) or "") != str(wanted) for key, wanted in expected.items())


def _try_incident_state(
    admin: ServiceNowClient,
    settings: Settings,
    passwords: dict[str, str],
    secret_bag: list[str],
    incident_id: str,
    resolved: str,
    in_progress: str,
    close_code: str,
) -> dict[str, Any]:
    rows = _safe_rows(
        admin,
        "sys_dictionary",
        "name=incident^element=incident_state",
        ["internal_type", "read_only", "active"],
    )
    if not rows:
        return {"present": False}
    note = f"{MARKER} resolve"
    body = {"incident_state": resolved, "close_code": close_code, "close_notes": note}
    written = _patch_as(
        settings,
        INCIDENT_USER,
        passwords[INCIDENT_USER],
        secret_bag,
        "incident",
        incident_id,
        body,
    )
    read = admin.get_record(
        "incident",
        incident_id,
        fields=["state", "incident_state", "close_code"],
    )
    if str(read.get("state") or "") != resolved and written.get("status") == 200:
        _patch_as(
            settings,
            INCIDENT_USER,
            passwords[INCIDENT_USER],
            secret_bag,
            "incident",
            incident_id,
            {"incident_state": in_progress},
        )
        written = _patch_as(
            settings,
            INCIDENT_USER,
            passwords[INCIDENT_USER],
            secret_bag,
            "incident",
            incident_id,
            body,
        )
        read = admin.get_record(
            "incident",
            incident_id,
            fields=["state", "incident_state", "close_code"],
        )
    return {
        "present": True,
        "dictionary": rows,
        "status": written.get("status"),
        "read": {
            "state": read.get("state"),
            "incident_state": read.get("incident_state"),
            "close_code": read.get("close_code"),
        },
        "stuck": str(read.get("state") or "") != resolved,
    }


def _admin_close_status(
    admin: ServiceNowClient,
    incident_id: str,
    resolved: str,
    close_code: str,
    note: str,
) -> int | None:
    """Same Known error write as admin. A business-rule 403 is not a missing role."""
    try:
        admin.update_record(
            "incident",
            incident_id,
            {"state": resolved, "close_code": close_code, "close_notes": note},
        )
    except ServiceNowError as exc:
        return exc.status_code
    return 200


def _admin_incident_state(
    admin: ServiceNowClient,
    incident_id: str,
    resolved: str,
    in_progress: str,
    close_code: str,
) -> dict[str, Any]:
    """Show whether admin can move state. This does not grant the probe user a role."""
    note = f"{MARKER} resolve"
    try:
        admin.update_record("incident", incident_id, {"state": in_progress})
        mid = admin.get_record("incident", incident_id, fields=["state"])
        admin.update_record(
            "incident",
            incident_id,
            {"state": resolved, "close_code": close_code, "close_notes": note},
        )
        final = admin.get_record("incident", incident_id, fields=["state", "close_code"])
    except ServiceNowError as exc:
        return {"status": exc.status_code}
    return {
        "status": 200,
        "after_in_progress": mid.get("state"),
        "after_resolved": final.get("state"),
        "close_code": final.get("close_code"),
    }


def _journal_has(
    admin: ServiceNowClient,
    table: str,
    sys_id: str,
    element: str,
    text: str,
) -> dict[str, Any]:
    try:
        rows = admin.get_table(
            "sys_journal_field",
            query=f"name={table}^element_id={sys_id}^element={element}",
            fields=["value"],
            limit=10,
        )
    except ServiceNowError as exc:
        return {"ok": False, "status": exc.status_code}
    return {
        "ok": any(text in str(row.get("value") or "") for row in rows),
        "status": 200,
        "rows": len(rows),
    }


def _problem_write_probe(
    admin: ServiceNowClient,
    settings: Settings,
    users: dict[str, dict[str, Any]],
    passwords: dict[str, str],
    secret_bag: list[str],
    article_id: str,
) -> dict[str, Any]:
    question = (
        "What smallest role set lets the problem user set known_error "
        "and the incident parent?"
    )
    calls = [
        "PATCH problem known_error",
        "PATCH incident parent and work_notes as the problem user",
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
            "short_description": f"{MARKER} problem-writes",
            "correlation_id": f"{MARKER}-problem-writes",
        },
    )
    try:
        incident = admin.create_record(
            "incident",
            {
                "short_description": f"{MARKER} problem-writes",
                "description": f"{MARKER} created by admin",
                "correlation_id": f"{MARKER}-problem-writes",
                "caller_id": users[INCIDENT_USER]["sys_id"],
            },
        )
    except ServiceNowError as exc:
        incident = {"sys_id": "", "status": exc.status_code}
    incident_id = str(incident.get("sys_id") or "")
    roles_before = list(problem_user["granted"])
    if not problem_id or not incident_id:
        print("problem_writes: records were not created")
        return _result(
            question,
            calls,
            {"problem": bool(problem_id), "incident": bool(incident_id)},
            "failed",
            "The problem-write probe could not create both records.",
        )
    steps = [
        _problem_step(
            admin,
            settings,
            problem_user,
            passwords,
            secret_bag,
            "problem",
            problem_id,
            "known_error",
            {"known_error": "true"},
            ["known_error"],
            true_fields=("known_error",),
        ),
        _problem_step(
            admin,
            settings,
            problem_user,
            passwords,
            secret_bag,
            "incident",
            incident_id,
            "parent",
            {"parent": problem_id},
            ["parent"],
            expect={"parent": problem_id},
        ),
        _problem_step(
            admin,
            settings,
            problem_user,
            passwords,
            secret_bag,
            "incident",
            incident_id,
            "work_notes",
            {"work_notes": f"{MARKER} workaround"},
            ["work_notes"],
            journal="work_notes",
        ),
    ]
    stuck = [step["name"] for step in steps if step.get("stuck")]
    roles_after = list(problem_user["granted"])
    evidence = {
        "article": bool(article_id),
        "steps": steps,
        "roles_before": roles_before,
        "roles_added": [role for role in roles_after if role not in roles_before],
        "roles": roles_after,
        "knowledge_roles": [role for role in roles_after if role in KNOWLEDGE_LADDER],
    }
    decision = "verified" if not stuck else "failed"
    print(f"problem_writes: stuck={stuck or 'none'} roles={evidence['roles']}")
    reason = (
        "The known_error flag and the incident link read back. "
        "The next problem role was added only after HTTP 403."
        if decision == "verified"
        else "A known-error or incident-link write did not read back."
    )
    return _result(question, calls, evidence, decision, reason)


def _problem_step(
    admin: ServiceNowClient,
    settings: Settings,
    user: dict[str, Any],
    passwords: dict[str, str],
    secret_bag: list[str],
    table: str,
    sys_id: str,
    name: str,
    body: dict[str, Any],
    read_fields: list[str],
    expect: dict[str, str] | None = None,
    journal: str | None = None,
    true_fields: tuple[str, ...] = (),
    blocked: bool = False,
) -> dict[str, Any]:
    if blocked:
        return {"name": name, "stuck": True, "status": None, "error": "article was missing"}

    def write() -> dict[str, Any]:
        written = _patch_as(
            settings,
            PROBLEM_USER,
            passwords[PROBLEM_USER],
            secret_bag,
            table,
            sys_id,
            body,
        )
        if written.get("status") != 200:
            return {
                "ok": False,
                "status": written.get("status"),
                "stuck": True,
                "error": written.get("error"),
            }
        read = admin.get_record(table, sys_id, fields=read_fields)
        journal_hit = None
        if journal:
            text = str(body.get(journal) or "")
            journal_hit = _journal_has(admin, table, sys_id, journal, text)
            stuck = not (journal_hit.get("ok") or text in str(read.get(journal) or ""))
        elif true_fields:
            stuck = any(
                str(read.get(key) or "").lower() not in {"true", "1"} for key in true_fields
            )
        else:
            wanted = expect or {key: str(value) for key, value in body.items()}
            stuck = any(str(read.get(key) or "") != str(value) for key, value in wanted.items())
        return {
            "ok": True,
            "status": 200,
            "stuck": stuck,
            "read": {key: read.get(key) for key in read_fields},
            "journal": journal_hit,
        }

    written = _ensure(admin, user, PROBLEM_LADDER, write)
    return {
        "name": name,
        "table": table,
        "status": written.get("status"),
        "stuck": bool(written.get("stuck", written.get("status") != 200)),
        "read": written.get("read"),
        "journal": written.get("journal"),
        "role_added": written.get("role_added"),
        "roles": list(user["granted"]),
        "error": redact_text(str(written.get("error") or ""), secret_bag)[:300],
    }


def _article_id(evidence: dict[str, Any]) -> str:
    endpoint = ((evidence.get("probes") or {}).get("endpoint") or {}).get("evidence") or {}
    publish = endpoint.get("publish") or {}
    if publish.get("sys_id"):
        return str(publish["sys_id"])
    knowledge = ((evidence.get("probes") or {}).get("knowledge") or {}).get("evidence") or {}
    return str((knowledge.get("create") or {}).get("sys_id") or "")


def _mark_endpoint_removed(evidence: dict[str, Any]) -> None:
    probe = (evidence.get("probes") or {}).get("endpoint")
    if not probe:
        return
    counts = {row.get("table"): row.get("count") for row in evidence.get("residue") or []}
    gone = counts.get("sys_ws_definition") == 0 and counts.get("sys_ws_operation") == 0
    probe.setdefault("evidence", {})["removed"] = gone


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
    duties = ("approval", "parent", "rfc", "incident_writes", "problem_writes")
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
        "Duty roles were added one at a time after HTTP 403, "
        "or after an incident write returned 200 and did not stick. "
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
        ("incident", "state"),
        ("incident", "incident_state"),
        ("task", "problem_id"),
        ("problem", "rfc"),
        ("problem", "state"),
        ("problem", "problem_state"),
        ("problem", "resolution_code"),
        ("problem", "known_error"),
        ("problem", "primary_known_error_article"),
        ("problem", "cause_notes"),
        ("problem", "fix_notes"),
        ("problem", "close_notes"),
        ("problem", "workaround"),
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
    try:
        state_api.remove(client)
    except ServiceNowError:
        pass
    for marker in (MARKER, ENDPOINT_MARKER):
        for table, query in (
            ("kb_template_known_error_article", f"short_descriptionSTARTSWITH{marker}"),
            ("kb_knowledge", f"short_descriptionSTARTSWITH{marker}"),
            ("incident", f"short_descriptionSTARTSWITH{marker}^ORcorrelation_idSTARTSWITH{marker}"),
            ("problem", f"short_descriptionSTARTSWITH{marker}^ORcorrelation_idSTARTSWITH{marker}"),
        ):
            _delete_where(client, table, query)
        _delete_where(client, "sys_journal_field", f"valueLIKE{marker}")
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
    for marker, label in ((ENDPOINT_MARKER, ENDPOINT_MARKER),):
        for table, query in (
            ("problem", f"correlation_idSTARTSWITH{marker}^ORshort_descriptionSTARTSWITH{marker}"),
            ("incident", f"correlation_idSTARTSWITH{marker}^ORshort_descriptionSTARTSWITH{marker}"),
            ("kb_knowledge", f"short_descriptionSTARTSWITH{marker}"),
        ):
            name = f"{table} {label}"
            try:
                rows = client.get_table(table, query=query, fields=["sys_id"], limit=20)
            except ServiceNowError as exc:
                results.append(
                    {
                        "table": name,
                        "query": query,
                        "count": None,
                        "status": exc.status_code,
                    }
                )
                continue
            results.append({"table": name, "query": query, "count": len(rows)})
    counts = state_api.endpoint_counts(client)
    definition_query = f"service_id={state_api.SERVICE_ID}"
    operation_query = f"web_service_definition.service_id={state_api.SERVICE_ID}"
    results.append(
        {
            "table": "sys_ws_definition",
            "query": definition_query,
            "count": counts["sys_ws_definition"],
        }
    )
    results.append(
        {
            "table": "sys_ws_operation",
            "query": operation_query,
            "count": counts["sys_ws_operation"],
        }
    )
    return results


def _print_residue(rows: list[dict[str, Any]]) -> None:
    print("SYN-PROBE residue:")
    for row in rows:
        query = f" query={row['query']}" if row.get("query") else ""
        if row.get("count") is None:
            print(f"  {row['table']}: error HTTP {row.get('status')}{query}")
        else:
            print(f"  {row['table']}: {row['count']}{query}")


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
    for key in (
        "approval",
        "parent",
        "rfc",
        "states",
        "knowledge",
        "problem_state",
        "endpoint",
        "incident_writes",
        "problem_writes",
        "roles",
    ):
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
        return "The Table API moved no state. The endpoint result is a separate row."
    if decision == "partial":
        return "A partial walk is not the approved fallback. The endpoint result is a separate row."
    return "Recorded from the Table API walk."


def _publish_note(probes: dict[str, Any]) -> str:
    endpoint = (probes.get("endpoint") or {}).get("evidence") or {}
    publish = endpoint.get("publish") or {}
    if publish.get("decision") == "verified" and endpoint.get("removed"):
        return "Table API publish stayed draft. publish_article was probed and then removed."
    if publish.get("decision") == "verified":
        return "Table API publish stayed draft. publish_article was probed."
    if (probes.get("knowledge") or {}).get("decision") == "verified":
        return "The problem user published through the Table API."
    return "Table API publish did not stick. The endpoint probe records publish_article."


def _endpoint_note(probes: dict[str, Any]) -> str:
    endpoint = (probes.get("endpoint") or {}).get("evidence") or {}
    operations = endpoint.get("operations") or []
    names = ", ".join(str(name) for name in operations) if operations else "none"
    if endpoint.get("removed"):
        return f"Installed operations: {names}. The residue query shows the endpoint is gone."
    if operations:
        return f"Installed operations: {names}. Removal is not confirmed."
    return "The endpoint probe records which operations were installed and then removed."


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
            _publish_note(probes),
        ),
        (
            "problem.problem_state",
            (probes.get("problem_state") or {}).get("decision", "not run"),
            "Writes problem_state and reads state back.",
        ),
        (
            "endpoint",
            (probes.get("endpoint") or {}).get("decision", "not run"),
            _endpoint_note(probes),
        ),
        (
            "incident writes",
            (probes.get("incident_writes") or {}).get("decision", "not run"),
            "One role at a time on an incident this user did not create.",
        ),
        (
            "problem writes",
            (probes.get("problem_writes") or {}).get("decision", "not run"),
            "Known error fields and the incident link, one role at a time.",
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
