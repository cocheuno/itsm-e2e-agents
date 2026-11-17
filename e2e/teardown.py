"""Remove only the e2e layer. The change seed, its settings, and update xml stay."""

from __future__ import annotations

from cm_agents.servicenow.client import ServiceNowClient, ServiceNowError

from e2e.accounts import delete_service_users
from e2e.counts import format_counts, snapshot
from e2e.data.history import Ledger
from e2e.errors import WorldError
from e2e.instance import http_failure, open_client
from e2e.paths import manifest_path
from e2e.settings import Settings
from e2e.state_api import endpoint_counts, remove

STAGE = "u_syn_e2e_inc_import"
MAP_NAME = "SYN-E2E Incident Import"
MARKER = "SYN-E2E-"


def run_teardown(settings: Settings) -> int:
    ledger = Ledger()
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        _clear_parents(admin, settings)
        _delete_records(admin, ledger)
        _remove_endpoint(admin, ledger)
        _remove_import(admin, ledger)
        delete_service_users(admin, settings, ledger)
        if manifest_path().is_file():
            manifest_path().unlink()
        counts = snapshot(admin)
        _users_gone(admin, settings)
    print(f"teardown: {format_counts(counts)}")
    if any(counts[key] not in {0, None} for key in counts):
        raise WorldError(f"teardown left rows: {format_counts(counts)}")
    return 0


def _clear_parents(admin: ServiceNowClient, settings: Settings) -> None:
    rows = admin.get_records(
        "incident",
        query=f"correlation_idSTARTSWITH{MARKER}^parentISNOTEMPTY",
        fields=["sys_id"],
        page_size=200,
        max_records=500,
    )
    if not rows:
        return
    users = admin.get_table(
        "sys_user",
        query=f"user_name={settings.sn_problem_user}",
        fields=["sys_id"],
        limit=1,
    )
    if not users:
        raise WorldError("incidents still have a parent and the problem user is absent")
    with open_client(settings, settings.sn_problem_user, settings.sn_problem_password) as actor:
        for row in rows:
            incident_id = str(row.get("sys_id") or "")
            try:
                actor.update_record("incident", incident_id, {"parent": ""})
            except ServiceNowError as exc:
                raise http_failure("clear parent", exc) from None
    left = admin.get_records(
        "incident",
        query=f"correlation_idSTARTSWITH{MARKER}^parentISNOTEMPTY",
        fields=["sys_id"],
        page_size=50,
        max_records=50,
    )
    if left:
        raise WorldError(f"parent clear left {len(left)} incidents")


def _delete_records(admin: ServiceNowClient, ledger: Ledger) -> None:
    text = f"short_descriptionSTARTSWITH{MARKER}"
    correlation = f"correlation_idSTARTSWITH{MARKER}"
    _delete_query(admin, ledger, "incident", f"{text}^OR{correlation}", "incident")
    _delete_query(admin, ledger, "problem", f"{text}^OR{correlation}", "problem")
    for table in ("kb_knowledge", "kb_template_known_error_article"):
        _delete_query(admin, ledger, table, text, "article")
    changes = admin.get_records(
        "change_request",
        query=f"{text}^OR{correlation}",
        fields=["sys_id", "state"],
        page_size=50,
        max_records=50,
    )
    for change in changes:
        change_id = str(change.get("sys_id") or "")
        for table, query, name in (
            ("sysapproval_approver", f"sysapproval={change_id}", "approval"),
            ("sysapproval_group", f"parent={change_id}", "approval group"),
            ("change_task", f"change_request={change_id}^ORparent={change_id}", "change task"),
            ("task_ci", f"task={change_id}", "task ci"),
        ):
            _delete_query(admin, ledger, table, query, name)
        state = str(change.get("state") or "")
        ledger.delete("change_request", change_id, "change")
        try:
            admin.delete_record("change_request", change_id)
        except ServiceNowError as exc:
            code = exc.status_code if exc.status_code is not None else "none"
            raise WorldError(f"change delete failed HTTP {code} state={state}") from None


def _remove_endpoint(admin: ServiceNowClient, ledger: Ledger) -> None:
    definitions = admin.get_table(
        "sys_ws_definition",
        query="service_id=syne2e_problem_state",
        fields=["sys_id"],
        limit=5,
    )
    operations = []
    for definition in definitions:
        operations.extend(
            admin.get_table(
                "sys_ws_operation",
                query=f"web_service_definition={definition['sys_id']}",
                fields=["sys_id"],
                limit=10,
            )
        )
    try:
        remove(admin)
    except ServiceNowError as exc:
        raise http_failure("endpoint remove", exc) from None
    counts = endpoint_counts(admin)
    if counts["sys_ws_definition"] or counts["sys_ws_operation"]:
        raise WorldError(
            "endpoint remains"
            f" definitions={counts['sys_ws_definition']}"
            f" operations={counts['sys_ws_operation']}"
        )
    for row in operations:
        ledger.delete("sys_ws_operation", str(row.get("sys_id") or ""), "operation")
    for row in definitions:
        ledger.delete("sys_ws_definition", str(row.get("sys_id") or ""), "syne2e_problem_state")


def _remove_import(admin: ServiceNowClient, ledger: Ledger) -> None:
    _delete_stage_rows(admin, ledger)
    _delete_query(admin, ledger, "sys_import_set", f"table_name={STAGE}", "import set")
    if _count(admin, "sys_import_set", f"table_name={STAGE}"):
        raise WorldError("import sets remain")
    _delete_query(admin, ledger, "sys_transform_entry", f"source_table={STAGE}", "field map")
    _delete_query(admin, ledger, "sys_transform_map", f"name={MAP_NAME}", "transform map")
    _delete_query(admin, ledger, "sys_db_object", f"name={STAGE}", "staging table")
    if _count(admin, "sys_db_object", f"name={STAGE}"):
        raise WorldError("staging table remains")
    _delete_query(admin, ledger, "sys_dictionary", f"name={STAGE}", "dictionary", strict=False)
    _delete_query(
        admin,
        ledger,
        "sys_documentation",
        f"name={STAGE}",
        "documentation",
        strict=False,
    )
    dictionary = _count(admin, "sys_dictionary", f"name={STAGE}")
    if dictionary:
        raise WorldError(f"dictionary rows left={dictionary}")
    documentation = _count(admin, "sys_documentation", f"name={STAGE}")
    if documentation:
        raise WorldError(f"documentation rows left={documentation}")


def _delete_stage_rows(admin: ServiceNowClient, ledger: Ledger) -> None:
    try:
        rows = admin.get_records(
            STAGE,
            query="sys_idISNOTEMPTY",
            fields=["sys_id"],
            page_size=200,
            max_records=500,
        )
    except ServiceNowError as exc:
        if exc.status_code in {400, 404}:
            return
        raise http_failure("staging rows", exc) from None
    for row in rows:
        sys_id = str(row.get("sys_id") or "")
        ledger.delete(STAGE, sys_id, "staging row")
        _delete_id(admin, STAGE, sys_id, strict=True)


def _delete_query(
    admin: ServiceNowClient,
    ledger: Ledger,
    table: str,
    query: str,
    name: str,
    *,
    strict: bool = True,
) -> None:
    try:
        rows = admin.get_records(
            table,
            query=query,
            fields=["sys_id"],
            page_size=200,
            max_records=500,
        )
    except ServiceNowError as exc:
        if exc.status_code == 404:
            return
        raise http_failure(f"query {name}", exc) from None
    for row in rows:
        sys_id = str(row.get("sys_id") or "")
        ledger.delete(table, sys_id, name)
        _delete_id(admin, table, sys_id, strict=strict)


def _delete_id(admin: ServiceNowClient, table: str, sys_id: str, *, strict: bool) -> None:
    if len(sys_id) != 32:
        return
    try:
        admin.delete_record(table, sys_id)
    except ServiceNowError as exc:
        if not strict and exc.status_code in {403, 404}:
            return
        if exc.status_code == 404:
            return
        code = exc.status_code if exc.status_code is not None else "none"
        raise WorldError(f"delete {table} failed HTTP {code}") from None


def _users_gone(admin: ServiceNowClient, settings: Settings) -> None:
    for user_name in (
        settings.sn_incident_user,
        settings.sn_problem_user,
        settings.sn_authority_user,
    ):
        if _count(admin, "sys_user", f"user_name={user_name}"):
            raise WorldError("a service user is still present")


def _count(admin: ServiceNowClient, table: str, query: str) -> int:
    try:
        return admin.count(table, query)
    except ServiceNowError as exc:
        if exc.status_code == 404:
            return 0
        raise http_failure(f"count {table}", exc) from None
