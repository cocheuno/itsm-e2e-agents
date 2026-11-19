"""Rows that exist only while an end-to-end scenario is running.

cm_agents requires a thread id that starts with SYN-. That id is the change's
correlation_id and the correlation_id of the incident a failed deployment
opens. Persistent incidents, problems, and articles use E2E- and are not
these ids. Every scenario deletes its thread ids before it returns, on pass
and on failure.
"""

from __future__ import annotations

import re

from cm_agents.servicenow.client import ServiceNowClient, ServiceNowError

from e2e.errors import WorldError
from e2e.instance import http_failure

# Case id is E2E- plus 8 hex. Attempt starts at 1.
THREAD_ID = re.compile(r"^SYN-E2E-E2E-[0-9a-f]{8}-CHG-[1-9][0-9]*$")
_SEED_PREFIXES = ("SYN-CHG-", "SYN-OPEN-", "SYN-REL-", "SYN-INC-")
# task_ci delete is aborted by the change model. Deleting the change removes it.
_CHANGE_CHILDREN = (
    ("sysapproval_approver", "sysapproval={change_id}", "approval"),
    ("sysapproval_group", "parent={change_id}", "approval group"),
    ("change_task", "change_request={change_id}^ORparent={change_id}", "change task"),
    ("task_cmdb_ci_service", "task={change_id}", "affected service"),
    ("conflict", "change={change_id}^ORconflicting_change={change_id}", "conflict"),
)


def require_thread_id(thread_id: str) -> str:
    """Accept only a scenario change thread. Reject seed prefixes and E2E- rows."""
    text = thread_id.strip()
    folded = text.upper()
    if folded.startswith(_SEED_PREFIXES):
        raise WorldError("thread id uses a change-seed prefix")
    if not THREAD_ID.fullmatch(text):
        raise WorldError("thread id must be SYN-E2E-<case>-CHG-<attempt>")
    return text


def thread_query(thread_id: str) -> str:
    """Exact correlation match. STARTSWITH would also hit other SYN- rows."""
    return f"correlation_id={require_thread_id(thread_id)}"


def delete_unkept(admin: ServiceNowClient, table: str, query: str, keep: set[str]) -> int:
    """Delete rows in `query` whose sys_id is not in the seeded set."""
    try:
        found = admin.get_records(
            table,
            query=query,
            fields=["sys_id"],
            page_size=200,
            max_records=500,
        )
    except ServiceNowError as exc:
        if exc.status_code == 404 or (table == "conflict" and exc.status_code == 400):
            return 0
        raise http_failure(f"query {table}", exc) from None
    removed = 0
    for row in found:
        sys_id = str(row.get("sys_id") or "")
        if len(sys_id) != 32 or sys_id in keep:
            continue
        try:
            admin.delete_record(table, sys_id)
        except ServiceNowError as exc:
            if exc.status_code == 404:
                continue
            code = exc.status_code if exc.status_code is not None else "none"
            raise WorldError(f"delete {table} failed HTTP {code}") from None
        removed += 1
    return removed


def delete_scenario_threads(admin: ServiceNowClient, thread_ids: list[str]) -> None:
    """Delete the change and the deployment incident for each thread id."""
    for thread_id in thread_ids:
        query = thread_query(thread_id)
        _delete_matching(admin, "incident", query, "deployment incident")
        changes = _rows(admin, "change_request", query, ["sys_id", "state"])
        for change in changes:
            change_id = str(change.get("sys_id") or "")
            if len(change_id) != 32:
                continue
            for table, child_query, name in _CHANGE_CHILDREN:
                _delete_matching(admin, table, child_query.format(change_id=change_id), name)
            state = str(change.get("state") or "")
            try:
                admin.delete_record("change_request", change_id)
            except ServiceNowError as exc:
                code = exc.status_code if exc.status_code is not None else "none"
                raise WorldError(f"change delete failed HTTP {code} state={state}") from None
            left = _rows(admin, "task_ci", f"task={change_id}", ["sys_id"])
            if left:
                raise WorldError(f"task ci left={len(left)}")


def _rows(
    admin: ServiceNowClient,
    table: str,
    query: str,
    fields: list[str],
) -> list[dict]:
    try:
        return admin.get_records(
            table,
            query=query,
            fields=fields,
            page_size=50,
            max_records=50,
        )
    except ServiceNowError as exc:
        if exc.status_code == 404 or (table == "conflict" and exc.status_code == 400):
            return []
        raise http_failure(f"query {table}", exc) from None


def _delete_matching(admin: ServiceNowClient, table: str, query: str, name: str) -> None:
    for row in _rows(admin, table, query, ["sys_id"]):
        sys_id = str(row.get("sys_id") or "")
        if len(sys_id) != 32:
            continue
        try:
            admin.delete_record(table, sys_id)
        except ServiceNowError as exc:
            if exc.status_code == 404:
                continue
            code = exc.status_code if exc.status_code is not None else "none"
            raise WorldError(f"delete {name} failed HTTP {code}") from None
