"""One end-to-end tick: deliver due arrivals, triage them, then match or restore.

Incident text is scored locally. It is not sent to an LLM. The incident user
reads and writes. Admin is not used. The phase 2 helper reads the journal.
"""

from __future__ import annotations

from typing import Any

from agent.approvals import ApprovalQueue
from agent.audit import AuditLog
from agent.servicenow.client import ServiceNowClient as IncidentClient
from agent.servicenow.client import ServiceNowError as IncidentHTTPError
from agent.tools.errors import ApprovalRefused, ToolError
from agent.tools.registry import Registry
from agent.tools.writes import bind_writes
from agent.workflow.authority import (
    known_error_decision,
    restore_decision,
    run_approved,
    triage_decision,
)
from agent.workflow.known_error import match_known_error
from agent.workflow.triage import category_for_class, priority_on_this_pdi
from cm_agents.clock import now as clock_now
from cm_agents.data.generate import SERVICE_BY_NAME
from cm_agents.servicenow.client import ServiceNowError

from e2e.data.arrivals import due_arrivals
from e2e.data.fixtures import change_world
from e2e.data.world import CATEGORY_BY_CI_CLASS, MARKER
from e2e.errors import WorldError
from e2e.guard import assert_run_quiet, latest_incident_stamp
from e2e.instance import http_failure, open_client
from e2e.paths import repo_root
from e2e.settings import Settings
from e2e.simulator.resolver import outcome_for

_FIELDS = [
    "sys_id",
    "number",
    "state",
    "category",
    "impact",
    "urgency",
    "priority",
    "assignment_group",
    "parent",
    "close_code",
    "close_notes",
    "cmdb_ci",
    "short_description",
    "description",
    "correlation_id",
    "sys_updated_on",
]


def run_tick(settings: Settings) -> dict[str, Any]:
    """Handle arrivals that are due on the simulated clock. A second call writes nothing."""
    planned = due_arrivals(clock_now())
    folder = repo_root() / "var" / "phase2"
    folder.mkdir(parents=True, exist_ok=True)
    registry = Registry(ApprovalQueue(folder / "approvals.jsonl"))
    audit = AuditLog(folder / "audit.jsonl")
    before = len(audit.read())
    incident_client = IncidentClient(
        settings.sn_instance_url,
        settings.sn_incident_user,
        settings.sn_incident_password,
        timeout=180,
    )
    bind_writes(registry, incident_client, live=True)
    _changes, ci_index = change_world()
    created = triaged = matched = restored = skipped = 0
    handled: list[dict[str, Any]] = []
    with open_client(
        settings, settings.sn_incident_user, settings.sn_incident_password
    ) as client:
        started = latest_incident_stamp(client)
        allowed: set[str] = set()
        caller = _caller(client)
        articles, problems = _known_errors(client)
        for row in planned:
            outcome = _handle(
                client,
                registry,
                audit,
                row,
                caller=caller,
                ci_index=ci_index,
                articles=articles,
                problems=problems,
                allowed=allowed,
            )
            created += int(outcome["created"])
            triaged += int(outcome["triaged"])
            matched += int(outcome["matched"])
            restored += int(outcome["restored"])
            skipped += int(outcome["skipped"])
            handled.append(outcome["row"])
        outside = assert_run_quiet(client, started, allowed)
    fresh = audit.read()[before:]
    harmful = sum(1 for entry in fresh if entry.get("harmful"))
    print(
        f"tick arrivals={len(planned)} created={created} triaged={triaged} "
        f"known_error={matched} restored={restored} skipped={skipped} "
        f"outside incident updates={outside} harmful={harmful}"
    )
    return {
        "arrivals": len(planned),
        "created": created,
        "triaged": triaged,
        "known_error": matched,
        "restored": restored,
        "skipped": skipped,
        "outside": outside,
        "harmful": harmful,
        "rows": handled,
    }


def _handle(
    client,
    registry,
    audit,
    row: dict,
    *,
    caller: str,
    ci_index: dict[str, dict[str, str]],
    articles: list[dict],
    problems: dict[str, dict],
    allowed: set[str],
) -> dict[str, Any]:
    correlation = str(row["correlation_id"])
    ci_name = str(row["cmdb_ci"])
    info = ci_index.get(ci_name)
    if info is None:
        raise WorldError("arrival CI is not in the change world")
    category = category_for_class(info["ci_class"], CATEGORY_BY_CI_CLASS)
    if not category:
        raise WorldError("arrival CI class has no category")
    service = SERVICE_BY_NAME.get(info["service"])
    if service is None:
        raise WorldError("arrival CI service has no group")
    group_name = str(service["group"])
    group_id = _one(client, "sys_user_group", f"name={group_name}")
    ci_id = _one(client, "cmdb_ci", f"name={ci_name}")
    created = False
    current = _find(client, correlation)
    if current is None:
        current = _create(client, row, caller=caller, ci_id=ci_id)
        created = True
    sys_id = str(current["sys_id"])
    allowed.add(sys_id)
    triaged = matched = restored = skipped = 0
    if _triage_done(current, category, group_id):
        skipped += 1
    else:
        decision = triage_decision(sys_id, category, "3", "3", group_name)
        _execute(registry, audit, decision)
        triaged += 1
        current = _read(client, sys_id)
    incident = {
        "cmdb_ci": _ref(current.get("cmdb_ci")),
        "short_description": str(current.get("short_description") or ""),
        "description": str(current.get("description") or ""),
    }
    found = match_known_error(incident, articles, problems)
    if found is not None:
        if _known_done(current, str(found["problem"].get("sys_id") or "")):
            skipped += 1
        else:
            problem = found["problem"]
            article = found["article"]
            decision = known_error_decision(
                sys_id,
                str(problem.get("sys_id") or ""),
                str(problem.get("workaround") or ""),
                str(article.get("number") or ""),
                str(problem.get("number") or ""),
            )
            _execute(registry, audit, decision)
            matched += 1
            current = _read(client, sys_id)
    else:
        try:
            outcome = outcome_for(row)
        except ValueError as exc:
            raise WorldError(str(exc)) from None
        if _restore_done(current, outcome["close_code"]):
            skipped += 1
        else:
            decision = restore_decision(sys_id, outcome["close_code"], outcome["close_notes"])
            _execute(registry, audit, decision)
            restored += 1
            current = _read(client, sys_id)
    checked = _check_row(
        current,
        category=category,
        group_id=group_id,
        scenario=str(row["scenario"]),
        found=found,
    )
    return {
        "created": created,
        "triaged": triaged,
        "matched": matched,
        "restored": restored,
        "skipped": skipped,
        "row": checked,
    }


def _execute(registry, audit, decision: dict) -> None:
    tool = decision["tool"]
    try:
        result = run_approved(registry, audit, decision)
    except ToolError as exc:
        raise WorldError(_refused(tool, exc)) from None
    except ApprovalRefused:
        raise WorldError(f"{tool} was refused") from None
    except IncidentHTTPError as exc:
        raise WorldError(f"{tool} was refused HTTP {_http_status(exc)}") from None
    except ServiceNowError as exc:
        raise http_failure(tool, exc) from None
    if result.get("status") == "rejected":
        raise WorldError(f"{decision['tool']} was rejected by the incident authority")
    if result.get("dry_run"):
        raise WorldError(f"{decision['tool']} stayed a dry run")


def _triage_done(row: dict, category: str, group_id: str) -> bool:
    return (
        _ref(row.get("category")) == category
        and _ref(row.get("impact")) == "3"
        and _ref(row.get("urgency")) == "3"
        and _ref(row.get("assignment_group")) == group_id
    )


def _known_done(row: dict, problem_id: str) -> bool:
    return (
        _ref(row.get("state")) == "6"
        and _ref(row.get("close_code")) == "Workaround provided"
        and _ref(row.get("parent")) == problem_id
    )


def _restore_done(row: dict, close_code: str) -> bool:
    return _ref(row.get("state")) == "6" and _ref(row.get("close_code")) == close_code


def _check_row(
    row: dict,
    *,
    category: str,
    group_id: str,
    scenario: str,
    found: dict | None,
) -> dict[str, Any]:
    expected_priority = str(priority_on_this_pdi(3, 3))
    # The journal is hidden from this user. The phase 2 helper reads it.
    comment_ok = None
    notes_ok = True
    parent_ok = True
    state = _ref(row.get("state"))
    category_value = _ref(row.get("category"))
    priority = _ref(row.get("priority"))
    close_code = _ref(row.get("close_code"))
    parent = _ref(row.get("parent"))
    if found is not None:
        article_number = str(found["article"].get("number") or "")
        problem_number = str(found["problem"].get("number") or "")
        close_notes = str(row.get("close_notes") or "")
        notes_ok = article_number in close_notes and problem_number in close_notes
        parent_ok = parent == str(found["problem"].get("sys_id") or "")
    work_ok = None
    return {
        "number": str(row.get("number") or ""),
        "correlation_id": str(row.get("correlation_id") or ""),
        "scenario": scenario,
        "state": state,
        "category": category_value,
        "priority": priority,
        "close_code": close_code,
        "parent_set": bool(parent),
        "parent_ok": parent_ok,
        "category_ok": category_value == category,
        "group_ok": _ref(row.get("assignment_group")) == group_id,
        "priority_ok": priority == expected_priority,
        "comment_ok": comment_ok,
        "close_notes_ok": notes_ok,
        "work_note_ok": work_ok,
        "sys_updated_on": str(row.get("sys_updated_on") or ""),
    }


def _known_errors(client) -> tuple[list[dict], dict[str, dict]]:
    try:
        articles = client.get_records(
            "kb_knowledge",
            query=f"workflow_state=published^short_descriptionSTARTSWITH{MARKER}",
            fields=[
                "sys_id",
                "number",
                "short_description",
                "text",
                "source",
                "cmdb_ci",
                "workflow_state",
            ],
            page_size=50,
            max_records=20,
        )
    except ServiceNowError as exc:
        raise http_failure("known-error articles", exc) from None
    problems: dict[str, dict] = {}
    for article in articles:
        article["cmdb_ci"] = _ref(article.get("cmdb_ci"))
        source = _ref(article.get("source"))
        article["source"] = source
        if not source or source in problems:
            continue
        try:
            problem = client.get_record(
                "problem",
                source,
                fields=["sys_id", "number", "known_error", "workaround"],
            )
        except ServiceNowError as exc:
            raise http_failure("known-error problem", exc) from None
        problems[source] = problem
    return articles, problems


def _find(client, correlation: str) -> dict | None:
    try:
        rows = client.get_table(
            "incident",
            query=f"correlation_id={correlation}",
            fields=_FIELDS,
            limit=2,
        )
    except ServiceNowError as exc:
        raise http_failure("arrival lookup", exc) from None
    if len(rows) > 1:
        raise WorldError("more than one arrival shares a correlation id")
    return rows[0] if rows else None


def _read(client, sys_id: str) -> dict:
    try:
        return client.get_record("incident", sys_id, fields=_FIELDS)
    except ServiceNowError as exc:
        raise http_failure("arrival read", exc) from None


def _create(client, row: dict, *, caller: str, ci_id: str) -> dict:
    payload = {
        "short_description": str(row["short_description"]),
        "description": str(row["description"]),
        "correlation_id": str(row["correlation_id"]),
        "cmdb_ci": ci_id,
        "caller_id": caller,
        "impact": "3",
        "urgency": "3",
        "state": "1",
        "opened_at": str(row["opened_at"]),
    }
    try:
        created = client.create_record("incident", payload)
    except ServiceNowError as exc:
        if exc.status_code != 400:
            raise http_failure("arrival create", exc) from None
        payload.pop("opened_at")
        try:
            created = client.create_record("incident", payload)
        except ServiceNowError as again:
            raise http_failure("arrival create", again) from None
        print("opened_at omitted")
    sys_id = str(created.get("sys_id") or "")
    if len(sys_id) != 32:
        raise WorldError("arrival was not created")
    return _read(client, sys_id)


def _ref(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("value") or "")
    return str(value or "")


def _refused(tool: str, exc: BaseException) -> str:
    text = str(exc)
    marker = "HTTP "
    if marker not in text:
        return f"{tool} was refused"
    token = text.split(marker, 1)[1].split()[0].strip(":")
    if not token.isdigit():
        return f"{tool} was refused"
    return f"{tool} was refused HTTP {token}"


def _http_status(exc: BaseException) -> str:
    text = str(exc)
    marker = " -> "
    if marker not in text:
        return "none"
    return text.split(marker, 1)[1].split(":", 1)[0].strip() or "none"


def _caller(client) -> str:
    """The caller already stored on a seeded incident. sys_user is not required."""
    try:
        rows = client.get_table(
            "incident",
            query=f"correlation_idSTARTSWITH{MARKER}INC^caller_idISNOTEMPTY",
            fields=["caller_id"],
            limit=1,
        )
    except ServiceNowError as exc:
        raise http_failure("caller", exc) from None
    if not rows:
        raise WorldError("no seeded caller")
    caller = _ref(rows[0].get("caller_id"))
    if len(caller) != 32:
        raise WorldError("no seeded caller")
    return caller


def _one(client, table: str, query: str) -> str:
    try:
        rows = client.get_table(table, query=query, fields=["sys_id"], limit=1)
    except ServiceNowError as exc:
        raise http_failure(table, exc) from None
    if not rows:
        raise WorldError(f"{table} row was not found")
    return str(rows[0]["sys_id"])


