"""Count incident updates outside a run's own records.

Seeds and live scenarios call this with the window of their own run. A
non-zero count means something else on the instance was written while the
run was in progress. `sys_updated_on` is the instance clock. The start is
the newest incident stamp from before the run, and the comparison is strict
so a row that already held that stamp is not counted.
"""

from __future__ import annotations

from cm_agents.servicenow.client import ServiceNowClient, ServiceNowError

from e2e.data.world import MARKER
from e2e.errors import WorldError
from e2e.instance import http_failure
from e2e.scenario_records import require_thread_id

_PAGE = 200


def e2e_incident_ids(client: ServiceNowClient) -> set[str]:
    """sys_ids of this run's own incidents. Other updates in the window are not allowed."""
    try:
        rows = client.get_records(
            "incident",
            query=f"correlation_idSTARTSWITH{MARKER}INC",
            fields=["sys_id"],
            page_size=200,
            max_records=500,
        )
    except ServiceNowError as exc:
        raise http_failure("e2e incidents", exc) from None
    return {str(row.get("sys_id") or "") for row in rows if row.get("sys_id")}


def deployment_incident_ids(client: ServiceNowClient, thread_ids: set[str]) -> set[str]:
    """The incident a failed deployment opens uses the scenario's own thread id.

    That row is inside the run. Other incidents updated in the window are not.
    """
    found: set[str] = set()
    for thread_id in thread_ids:
        query = f"correlation_id={require_thread_id(thread_id)}"
        try:
            rows = client.get_records(
                "incident",
                query=query,
                fields=["sys_id"],
                page_size=20,
                max_records=20,
            )
        except ServiceNowError as exc:
            raise http_failure("deployment incident", exc) from None
        found.update(str(row.get("sys_id") or "") for row in rows if row.get("sys_id"))
    return found


def latest_incident_stamp(client: ServiceNowClient) -> str:
    try:
        rows = client.get_table(
            "incident",
            query="ORDERBYDESCsys_updated_on",
            fields=["sys_updated_on"],
            limit=1,
        )
    except ServiceNowError as exc:
        raise http_failure("incident stamp", exc) from None
    if not rows:
        return ""
    return str(rows[0].get("sys_updated_on") or "")


def count_updated_outside(
    client: ServiceNowClient,
    *,
    start: str,
    end: str,
    allowed: set[str],
) -> int:
    """Incidents updated in `(start, end]` whose sys_id is not in `allowed`."""
    if not end:
        return 0
    query = f"sys_updated_on<={end}"
    if start:
        query = f"sys_updated_on>{start}^{query}"
    found = 0
    offset = 0
    while offset <= 20000:
        try:
            page = client.get_table(
                "incident",
                query=query,
                fields=["sys_id"],
                limit=_PAGE,
                offset=offset,
            )
        except ServiceNowError as exc:
            raise http_failure("outside incident updates", exc) from None
        for row in page:
            sys_id = str(row.get("sys_id") or "")
            if sys_id and sys_id not in allowed:
                found += 1
        if len(page) < _PAGE:
            return found
        offset += _PAGE
    raise WorldError("outside incident updates exceeded the page limit")


def assert_run_quiet(
    client: ServiceNowClient,
    start: str,
    allowed: set[str],
) -> int:
    end = latest_incident_stamp(client)
    found = count_updated_outside(client, start=start, end=end, allowed=allowed)
    if found:
        raise WorldError(f"incidents updated outside this run={found}")
    return found
