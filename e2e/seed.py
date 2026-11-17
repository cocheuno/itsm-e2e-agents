"""Load the e2e world onto the instance that already holds the change seed.

History incidents go through an import set with business rules off. The E01
problem is created by the problem user and moved with the endpoint. A second
seed skips rows that are already present. Publishing the E01 known error can
make a system update turn the first checkout rows active. Those rows are
posted again through the same import set, with business rules still off.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from cm_agents.data.import_time import UTC, parse_utc, to_import_wall
from cm_agents.data.load import IMPORT_ROW, INCIDENT_FIELDS
from cm_agents.data.manifest import add_artifact, add_record, new_manifest, save_manifest
from cm_agents.servicenow.client import ServiceNowClient, ServiceNowError

from e2e.accounts import ensure_service_users
from e2e.counts import format_counts, snapshot
from e2e.data.fixtures import seeded_incidents
from e2e.data.ground_truth import problem_key, write_ground_truth
from e2e.data.history import Ledger
from e2e.data.world import ANCHOR, MARKER, SEED
from e2e.doctor import run_doctor
from e2e.errors import WorldError
from e2e.instance import http_failure, open_client
from e2e.paths import manifest_path
from e2e.settings import Settings
from e2e.state_api import install, operations_for, post_operation

STAGE = "u_syn_e2e_inc_import"
MAP_NAME = "SYN-E2E Incident Import"
# incident_state is not in the change seeder's field list. With business rules
# off, state 6 leaves incident_state at New, and a later rules-on update then
# marks the row active. This seed owns the extra staging column.
FIELDS = INCIDENT_FIELDS + (
    ("category", "string", "40"),
    ("incident_state", "string", "40"),
)
CAUSE = "Log rotation stopped. The log directory filled."
WORKAROUND = "Retry the page. Clear the filled log files at the next maintenance window."
E01_SHORT = "SYN-E2E- Log rotation stopped on syn-store-cdn"
ARTICLE_SHORT = "SYN-E2E- Known error for syn-store-cdn"
DESK = "SYN Service Desk"
# Publishing the E01 known error makes the platform update matching history
# incidents for a few minutes. Wait until that count stays still, then reimport.
_SETTLE_STEP = 15
_SETTLE_QUIET = 45
_SETTLE_LIMIT = 16


def run_seed(settings: Settings) -> int:
    ground = write_ground_truth()
    print("ground truth written")
    seeded = seeded_incidents()
    _check_lengths(seeded)
    ledger = Ledger()
    manifest = _new_manifest()
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        _ensure_import(admin, manifest, ledger)
        ensure_service_users(admin, settings, ledger)
        base_uri = _ensure_endpoint(admin, manifest, ledger)
        problem_id = _ensure_e01(admin, settings, ledger, manifest, base_uri)
        _import_history(admin, settings, manifest, ledger, seeded, problem_id)
        _sweep(admin, settings, manifest, ledger)
        save_manifest(manifest_path(), manifest)
        counts = snapshot(admin)
    print(f"seed: {format_counts(counts)}")
    _expect(counts, ground)
    report = run_doctor(settings)
    print(report.text())
    if not report.ok:
        raise WorldError("doctor failed after seed")
    return 0


def _new_manifest() -> dict[str, Any]:
    manifest = new_manifest(
        SEED,
        {},
        ANCHOR,
        seeded_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
    )
    manifest["documentation"] = []
    manifest["endpoint"] = []
    return manifest


def _check_lengths(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        if len(str(row["short_description"])) > 160:
            raise WorldError(f"{row['correlation_id']} short_description is longer than 160")
        if len(str(row["correlation_id"])) > 80:
            raise WorldError(f"{row['correlation_id']} correlation_id is longer than 80")


def _expect(counts: dict[str, Any], ground: dict[str, Any]) -> None:
    wanted = ground["counts"]
    pairs = (
        ("incidents", "incidents_seeded"),
        ("problems", "problems_seeded"),
        ("articles", "articles_seeded"),
        ("changes", "changes_seeded"),
    )
    for live, key in pairs:
        if counts[live] != wanted[key]:
            raise WorldError(f"count {live}={counts[live]} expected {wanted[key]}")
    if counts["endpoint_definitions"] != 1 or counts["endpoint_operations"] != 2:
        raise WorldError(
            "endpoint"
            f" definitions={counts['endpoint_definitions']}"
            f" operations={counts['endpoint_operations']}"
        )


def _ensure_import(
    admin: ServiceNowClient,
    manifest: dict[str, Any],
    ledger: Ledger,
) -> None:
    table_id, table_name = _ensure_table(admin, manifest, ledger)
    _ensure_columns(admin, manifest, ledger, table_name)
    map_id = _ensure_map(admin, manifest, ledger, table_name)
    _ensure_entries(admin, manifest, ledger, table_name, map_id)
    _keep(manifest, ledger, "staging_tables", "sys_db_object", table_id, table_name)
    save_manifest(manifest_path(), manifest)
    print("import table ready")


def _ensure_table(
    admin: ServiceNowClient,
    manifest: dict[str, Any],
    ledger: Ledger,
) -> tuple[str, str]:
    rows = admin.get_table(
        "sys_db_object",
        query=f"name={STAGE}",
        fields=["sys_id", "name"],
        limit=1,
    )
    if rows:
        return str(rows[0]["sys_id"]), str(rows[0]["name"])
    try:
        created = admin.create_record(
            "sys_db_object",
            {
                "label": MAP_NAME,
                "name": STAGE,
                "super_class": IMPORT_ROW,
                "create_access_controls": "false",
                "create_module": "false",
                "is_extendable": "false",
            },
        )
    except ServiceNowError as exc:
        raise http_failure("import table", exc) from None
    sys_id = str(created.get("sys_id") or "")
    table_name = str(created.get("name") or STAGE)
    _keep(manifest, ledger, "staging_tables", "sys_db_object", sys_id, table_name)
    _record_documentation(admin, manifest, ledger, table_name, "")
    return sys_id, table_name


def _ensure_columns(
    admin: ServiceNowClient,
    manifest: dict[str, Any],
    ledger: Ledger,
    table_name: str,
) -> None:
    existing = {
        str(row.get("element") or "")
        for row in admin.get_table(
            "sys_dictionary",
            query=f"name={table_name}",
            fields=["element"],
            limit=200,
        )
    }
    for element, internal, detail in FIELDS:
        column = f"u_{element}"
        if column in existing:
            continue
        body: dict[str, str] = {
            "name": table_name,
            "element": column,
            "column_label": element,
            "internal_type": internal,
            "active": "true",
        }
        if internal == "reference":
            body["reference"] = detail
        else:
            body["max_length"] = detail
        try:
            created = admin.create_record("sys_dictionary", body)
        except ServiceNowError as exc:
            raise http_failure(f"column {column}", exc) from None
        sys_id = str(created.get("sys_id") or "")
        _keep(manifest, ledger, "dictionary", "sys_dictionary", sys_id, f"{table_name}.{column}")
        _record_documentation(admin, manifest, ledger, table_name, column)


def _ensure_map(
    admin: ServiceNowClient,
    manifest: dict[str, Any],
    ledger: Ledger,
    table_name: str,
) -> str:
    rows = admin.get_table(
        "sys_transform_map",
        query=f"name={MAP_NAME}",
        fields=["sys_id"],
        limit=1,
    )
    if rows:
        map_id = str(rows[0]["sys_id"])
    else:
        try:
            created = admin.create_record(
                "sys_transform_map",
                {
                    "name": MAP_NAME,
                    "source_table": table_name,
                    "target_table": "incident",
                    "active": "true",
                    "run_business_rules": "false",
                    "run_script": "false",
                    "enforce_mandatory_fields": "false",
                    "order": "100",
                },
            )
        except ServiceNowError as exc:
            raise http_failure("transform map", exc) from None
        map_id = str(created.get("sys_id") or "")
        _keep(manifest, ledger, "transform_maps", "sys_transform_map", map_id, MAP_NAME)
    _require_rules_off(admin, map_id)
    return map_id


def _require_rules_off(admin: ServiceNowClient, map_id: str) -> None:
    fields = ["run_business_rules", "run_script", "enforce_mandatory_fields"]
    stored = admin.get_record("sys_transform_map", map_id, fields=fields)
    if all(_is_false(stored.get(field)) for field in fields):
        return
    try:
        admin.update_record(
            "sys_transform_map",
            map_id,
            {field: "false" for field in fields},
        )
    except ServiceNowError as exc:
        raise http_failure("transform map rules", exc) from None
    stored = admin.get_record("sys_transform_map", map_id, fields=fields)
    for field in fields:
        if not _is_false(stored.get(field)):
            raise WorldError(f"transform map {field} is not false")


def _ensure_entries(
    admin: ServiceNowClient,
    manifest: dict[str, Any],
    ledger: Ledger,
    table_name: str,
    map_id: str,
) -> None:
    present = {
        str(row.get("source_field") or "")
        for row in admin.get_table(
            "sys_transform_entry",
            query=f"map={map_id}",
            fields=["source_field"],
            limit=200,
        )
    }
    for element, _internal, _detail in FIELDS:
        source = f"u_{element}"
        if source in present:
            continue
        try:
            created = admin.create_record(
                "sys_transform_entry",
                {
                    "map": map_id,
                    "source_table": table_name,
                    "target_table": "incident",
                    "source_field": source,
                    "target_field": element,
                    "choice_action": "ignore",
                    "use_source_script": "false",
                    "coalesce": "false",
                },
            )
        except ServiceNowError as exc:
            raise http_failure(f"field map {source}", exc) from None
        sys_id = str(created.get("sys_id") or "")
        _keep(manifest, ledger, "field_maps", "sys_transform_entry", sys_id, f"{MAP_NAME}.{source}")


def _ensure_endpoint(
    admin: ServiceNowClient,
    manifest: dict[str, Any],
    ledger: Ledger,
) -> str:
    try:
        installed = install(admin, operations_for(problem_state_verified=False))
    except ServiceNowError as exc:
        raise http_failure("endpoint install", exc) from None
    definition_id = str(installed.get("definition_id") or "")
    _keep(manifest, ledger, "endpoint", "sys_ws_definition", definition_id, "syne2e_problem_state")
    base_uri = str(installed.get("base_uri") or "")
    if not base_uri:
        raise WorldError("endpoint base URI was empty")
    for operation in installed.get("operations") or []:
        print(f"endpoint operation {operation.get('name')}")
    save_manifest(manifest_path(), manifest)
    return base_uri


def _ensure_e01(
    admin: ServiceNowClient,
    settings: Settings,
    ledger: Ledger,
    manifest: dict[str, Any],
    base_uri: str,
) -> str:
    key = problem_key("syn-store-cdn", "log_rotation_stopped")
    rows = admin.get_table(
        "problem",
        query=f"correlation_id={key}",
        fields=["sys_id", "state", "known_error", "primary_known_error_article"],
        limit=2,
    )
    if len(rows) > 1:
        raise WorldError("more than one E01 problem")
    if rows and _e01_ready(admin, rows[0]):
        problem_id = str(rows[0]["sys_id"])
        _keep_record(manifest, ledger, "problem", problem_id, key)
        print("E01 problem: reused")
        return problem_id
    if rows:
        raise WorldError(
            "E01 problem is present but is not the seeded known error. Run e2e teardown."
        )
    ci = _one(admin, "cmdb_ci", "name=syn-store-cdn")
    with open_client(settings, settings.sn_problem_user, settings.sn_problem_password) as actor:
        try:
            created = actor.create_record(
                "problem",
                {
                    "short_description": E01_SHORT,
                    "description": CAUSE,
                    "correlation_id": key,
                    "cmdb_ci": ci,
                },
            )
        except ServiceNowError as exc:
            raise http_failure("E01 problem", exc) from None
        problem_id = str(created.get("sys_id") or "")
        user_id = _user_id(admin, settings.sn_problem_user)
        _move(actor, admin, base_uri, problem_id, "102", {"assigned_to": user_id})
        _move(
            actor,
            admin,
            base_uri,
            problem_id,
            "103",
            {"cause_notes": CAUSE, "workaround": WORKAROUND},
            retry={
                "assigned_to": user_id,
                "cause_notes": CAUSE,
                "workaround": WORKAROUND,
                "fix_notes": CAUSE,
                "close_notes": WORKAROUND,
                "resolution_code": "fix_applied",
            },
        )
        article_id = _publish_known_error(actor, admin, base_uri)
        _mark_known_error(actor, admin, problem_id, article_id)
    _keep_record(manifest, ledger, "problem", problem_id, key)
    _keep_record(manifest, ledger, "kb_knowledge", article_id, ARTICLE_SHORT)
    print("E01 problem: state 103 known error published")
    return problem_id


def _e01_ready(admin: ServiceNowClient, row: dict[str, Any]) -> bool:
    if str(row.get("state") or "") != "103" or not _truthy(row.get("known_error")):
        return False
    article_id = str(row.get("primary_known_error_article") or "")
    if len(article_id) != 32:
        return False
    try:
        article = _read_article(admin, article_id)
    except WorldError:
        return False
    workflow = str(article.get("workflow_state") or "")
    short = str(article.get("short_description") or "")
    return workflow == "published" and short.startswith(MARKER)


def _move(
    actor: ServiceNowClient,
    admin: ServiceNowClient,
    base_uri: str,
    problem_id: str,
    target: str,
    fields: dict[str, str],
    retry: dict[str, str] | None = None,
) -> None:
    state = _move_once(actor, admin, base_uri, problem_id, target, fields)
    if state == target:
        return
    if retry is None:
        raise WorldError(f"E01 move to {target} read {state or 'empty'}")
    state = _move_once(actor, admin, base_uri, problem_id, target, retry)
    if state != target:
        raise WorldError(f"E01 move to {target} read {state or 'empty'}")


def _move_once(
    actor: ServiceNowClient,
    admin: ServiceNowClient,
    base_uri: str,
    problem_id: str,
    target: str,
    fields: dict[str, str],
) -> str:
    response = post_operation(
        actor,
        base_uri,
        "move",
        {"sys_id": problem_id, "state": target, "fields": fields},
    )
    read = admin.get_record("problem", problem_id, fields=["state"])
    state = str(read.get("state") or "")
    print(f"E01 move ->{target} status={response['status']} read={state}")
    if response["status"] == 403:
        raise WorldError(f"E01 move to {target} was refused")
    return state


def _publish_known_error(
    actor: ServiceNowClient,
    admin: ServiceNowClient,
    base_uri: str,
) -> str:
    base_id = _one(admin, "kb_knowledge_base", "title=Known Error^active=true")
    table, article_id = _create_article(actor, base_id)
    _publish(actor, admin, base_uri, article_id)
    if _known_error_link_works(actor, admin, article_id):
        return article_id
    if table != "kb_knowledge":
        raise WorldError("E01 known-error article did not link to the problem")
    _template, template_id = _create_article(actor, base_id, knowledge=False)
    _publish(actor, admin, base_uri, template_id)
    if not _known_error_link_works(actor, admin, template_id):
        raise WorldError("E01 known-error article did not link to the problem")
    _delete_quiet(admin, table, article_id)
    left = admin.get_table(table, query=f"sys_id={article_id}", fields=["sys_id"], limit=1)
    if left:
        raise WorldError("the unused E01 article is still present")
    return template_id


def _create_article(
    actor: ServiceNowClient,
    base_id: str,
    *,
    knowledge: bool = True,
) -> tuple[str, str]:
    if knowledge:
        bodies = [
            (
                "kb_knowledge",
                {
                    "short_description": ARTICLE_SHORT,
                    "kb_knowledge_base": base_id,
                    "text": f"{CAUSE} {WORKAROUND}",
                    "workflow_state": "draft",
                },
            )
        ]
    else:
        bodies = [
            (
                "kb_template_known_error_article",
                {
                    "short_description": ARTICLE_SHORT,
                    "kb_knowledge_base": base_id,
                    "kb_description": CAUSE,
                    "kb_cause": CAUSE,
                    "kb_workaround": WORKAROUND,
                    "workflow_state": "draft",
                },
            )
        ]
    last = "none"
    for table, body in bodies:
        try:
            created = actor.create_record(table, body)
        except ServiceNowError as exc:
            last = str(exc.status_code if exc.status_code is not None else "none")
            continue
        return table, str(created.get("sys_id") or "")
    raise WorldError(f"E01 article was not created HTTP {last}")


def _publish(
    actor: ServiceNowClient,
    admin: ServiceNowClient,
    base_uri: str,
    article_id: str,
) -> None:
    response = post_operation(actor, base_uri, "publish_article", {"sys_id": article_id})
    article = _read_article(admin, article_id)
    workflow = str(article.get("workflow_state") or "")
    print(f"E01 publish status={response['status']} workflow_state={workflow or 'empty'}")
    if workflow != "published":
        raise WorldError(
            f"E01 article workflow_state={workflow or 'empty'} HTTP {response['status']}"
        )


def _known_error_link_works(
    actor: ServiceNowClient,
    admin: ServiceNowClient,
    article_id: str,
) -> bool:
    """The reference field points at kb_template_known_error_article. Probe it on a copy.

    The real link is written on the E01 problem after this returns true. A rejected
    reference leaves the field empty, which this read detects.
    """
    key = f"{MARKER}PROBE-article-link"
    _delete_where(admin, "problem", f"correlation_id={key}")
    try:
        created = actor.create_record(
            "problem",
            {"short_description": key, "correlation_id": key},
        )
    except ServiceNowError as exc:
        raise http_failure("article link probe", exc) from None
    problem_id = str(created.get("sys_id") or "")
    try:
        try:
            actor.update_record(
                "problem",
                problem_id,
                {"primary_known_error_article": article_id},
            )
        except ServiceNowError as exc:
            if exc.status_code in {400, 403}:
                return False
            raise http_failure("article link", exc) from None
        read = admin.get_record(
            "problem",
            problem_id,
            fields=["primary_known_error_article"],
        )
        return str(read.get("primary_known_error_article") or "") == article_id
    finally:
        _delete_quiet(admin, "problem", problem_id)
        left = admin.get_table(
            "problem",
            query=f"sys_id={problem_id}",
            fields=["sys_id"],
            limit=1,
        )
        if left:
            raise WorldError("article link probe problem is still present")


def _mark_known_error(
    actor: ServiceNowClient,
    admin: ServiceNowClient,
    problem_id: str,
    article_id: str,
) -> None:
    try:
        actor.update_record(
            "problem",
            problem_id,
            {"known_error": "true", "primary_known_error_article": article_id},
        )
    except ServiceNowError as exc:
        raise http_failure("E01 known error", exc) from None
    read = admin.get_record(
        "problem",
        problem_id,
        fields=["state", "known_error", "primary_known_error_article"],
    )
    if str(read.get("state") or "") != "103" or not _truthy(read.get("known_error")):
        raise WorldError("E01 problem did not stay at state 103 with known_error")
    if str(read.get("primary_known_error_article") or "") != article_id:
        raise WorldError("E01 primary known error article did not stick")


def _import_history(
    admin: ServiceNowClient,
    settings: Settings,
    manifest: dict[str, Any],
    ledger: Ledger,
    seeded: list[dict[str, Any]],
    problem_id: str,
) -> None:
    caller = _caller(admin, settings)
    group_id = _one(admin, "sys_user_group", f"name={DESK}")
    cis = _cis(admin, {str(row["cmdb_ci"]) for row in seeded})
    existing = {
        str(row.get("correlation_id") or "")
        for row in admin.get_records(
            "incident",
            query="correlation_idSTARTSWITHSYN-E2E-INC",
            fields=["correlation_id"],
            page_size=200,
            max_records=500,
        )
    }
    posted = 0
    for row in seeded:
        correlation = str(row["correlation_id"])
        if correlation in existing:
            continue
        payload = _payload(row, cis=cis, group_id=group_id, caller=caller, problem_id=problem_id)
        _post_one(admin, manifest, ledger, correlation, payload)
        posted += 1
        if posted % 25 == 0:
            print(f"incidents imported {posted}", flush=True)
            save_manifest(manifest_path(), manifest)
    print(f"incidents imported {posted} skipped {len(existing)}", flush=True)
    _repair_history(
        admin,
        manifest,
        ledger,
        seeded,
        cis=cis,
        group_id=group_id,
        caller=caller,
        problem_id=problem_id,
    )
    _verify_history(
        admin,
        settings,
        manifest,
        ledger,
        seeded,
        problem_id,
        cis=cis,
        group_id=group_id,
        caller=caller,
    )
    save_manifest(manifest_path(), manifest)


def _payload(
    row: dict[str, Any],
    *,
    cis: dict[str, str],
    group_id: str,
    caller: str,
    problem_id: str,
) -> dict[str, str]:
    opened = str(row["opened_at"])
    resolved = (parse_utc(opened) + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    values = {
        "short_description": str(row["short_description"]),
        "description": str(row["description"]),
        "state": "6",
        "incident_state": "6",
        "active": "false",
        "impact": "3",
        "urgency": "3",
        "priority": "3",
        "opened_at": to_import_wall(opened),
        "resolved_at": to_import_wall(resolved),
        "close_code": "Solution provided",
        "close_notes": str(row["close_notes"]),
        "assignment_group": group_id,
        "cmdb_ci": cis[str(row["cmdb_ci"])],
        "caller_id": caller,
        "correlation_id": str(row["correlation_id"]),
        "category": "software",
    }
    if row.get("parent") == "E01":
        values["parent"] = problem_id
    return {f"u_{key}": value for key, value in values.items() if value != ""}


def _post_one(
    admin: ServiceNowClient,
    manifest: dict[str, Any],
    ledger: Ledger,
    correlation: str,
    payload: dict[str, str],
) -> None:
    try:
        response = admin.request("POST", f"/api/now/import/{STAGE}", json=payload)
    except ServiceNowError as exc:
        raise http_failure(f"import {correlation}", exc) from None
    results = response.get("result")
    if isinstance(results, dict):
        results = [results]
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise WorldError(f"import {correlation} returned an unexpected result")
    status = str(results[0].get("status") or "")
    if status not in {"inserted", "updated"}:
        raise WorldError(f"import {correlation} status {status or 'failed'}")
    number = str(response.get("import_set") or "")
    if not number:
        return
    sets = admin.get_table(
        "sys_import_set",
        query=f"number={number}",
        fields=["sys_id"],
        limit=1,
    )
    if sets:
        _keep(manifest, ledger, "import_sets", "sys_import_set", str(sets[0]["sys_id"]), number)


def _repair_history(
    admin: ServiceNowClient,
    manifest: dict[str, Any],
    ledger: Ledger,
    seeded: list[dict[str, Any]],
    *,
    cis: dict[str, str],
    group_id: str,
    caller: str,
    problem_id: str,
) -> None:
    """Re-post rows a rules-on update changed, using the import set.

    A Table API write cannot clear active once task reopener has run. The
    import set still can, because its transform map has business rules off.
    Coalesce is on only for these posts, and the finally block turns it off
    even when a post fails.
    """
    for _round in range(3):
        pending = _wait_for_linker(admin, seeded)
        if not pending:
            return
        print(f"incidents reimported {len(pending)}", flush=True)
        entry_id = _correlation_entry(admin)
        try:
            _set_coalesce(admin, entry_id, True)
            for row in pending:
                correlation = str(row["correlation_id"])
                payload = _payload(
                    row,
                    cis=cis,
                    group_id=group_id,
                    caller=caller,
                    problem_id=problem_id,
                )
                _post_one(admin, manifest, ledger, correlation, payload)
        finally:
            _set_coalesce(admin, entry_id, False)


def _wait_for_linker(
    admin: ServiceNowClient,
    seeded: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    last: int | None = None
    stable_for = 0
    pending: list[dict[str, Any]] = []
    for _poll in range(_SETTLE_LIMIT):
        pending = _pending_repairs(admin, seeded)
        count = len(pending)
        if last != count:
            print(f"incidents settling {count}", flush=True)
        last, stable_for, done = _next_settle(last, count, stable_for)
        if done:
            return pending
        time.sleep(_SETTLE_STEP)
    return pending


def _pending_repairs(
    admin: ServiceNowClient,
    seeded: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    stored = _stored_incidents(admin)
    return [
        row
        for row in seeded
        if _needs_reimport(stored.get(str(row["correlation_id"])))
    ]


def _next_settle(previous: int | None, count: int, stable_for: int) -> tuple[int, int, bool]:
    if previous == count:
        stable_for += _SETTLE_STEP
    else:
        stable_for = 0
    return count, stable_for, stable_for >= _SETTLE_QUIET


def _needs_reimport(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    if str(row.get("incident_state") or "") != "6":
        return True
    return not _false(row.get("active"))


def _correlation_entry(admin: ServiceNowClient) -> str:
    rows = admin.get_table(
        "sys_transform_entry",
        query=f"source_table={STAGE}^source_field=u_correlation_id^target_field=correlation_id",
        fields=["sys_id"],
        limit=2,
    )
    if len(rows) != 1 or len(str(rows[0].get("sys_id") or "")) != 32:
        raise WorldError("correlation field map was not found")
    return str(rows[0]["sys_id"])


def _set_coalesce(admin: ServiceNowClient, entry_id: str, enabled: bool) -> None:
    try:
        admin.update_record(
            "sys_transform_entry",
            entry_id,
            {"coalesce": "true" if enabled else "false"},
        )
    except ServiceNowError as exc:
        raise http_failure("correlation coalesce", exc) from None
    stored = admin.get_record("sys_transform_entry", entry_id, fields=["coalesce"])
    if _truthy(stored.get("coalesce")) != enabled:
        raise WorldError("correlation coalesce did not stick")


def _verify_history(
    admin: ServiceNowClient,
    settings: Settings,
    manifest: dict[str, Any],
    ledger: Ledger,
    seeded: list[dict[str, Any]],
    problem_id: str,
    *,
    cis: dict[str, str],
    group_id: str,
    caller: str,
) -> None:
    stored = _stored_incidents(admin)
    _check_rows(seeded, stored, problem_id, repair=False)
    missing = [
        row
        for row in seeded
        if row.get("parent") == "E01"
        and str(stored[str(row["correlation_id"])].get("parent") or "") != problem_id
    ]
    if not missing:
        return
    print(f"C01 parent after import: {len(missing)} empty, setting as the problem user")
    with open_client(settings, settings.sn_problem_user, settings.sn_problem_password) as actor:
        for row in missing:
            incident_id = str(stored[str(row["correlation_id"])]["sys_id"])
            try:
                actor.update_record("incident", incident_id, {"parent": problem_id})
            except ServiceNowError as exc:
                raise http_failure(f"C01 parent {row['correlation_id']}", exc) from None
    # The parent write runs business rules. Put active and incident_state back
    # through the import set before the second read.
    _repair_history(
        admin,
        manifest,
        ledger,
        seeded,
        cis=cis,
        group_id=group_id,
        caller=caller,
        problem_id=problem_id,
    )
    stored = _stored_incidents(admin)
    _check_rows(seeded, stored, problem_id, repair=True)


def _stored_incidents(admin: ServiceNowClient) -> dict[str, dict[str, Any]]:
    rows = admin.get_records(
        "incident",
        query="correlation_idSTARTSWITHSYN-E2E-INC",
        fields=[
            "sys_id",
            "correlation_id",
            "state",
            "incident_state",
            "active",
            "category",
            "business_service",
            "parent",
            "opened_at",
            "close_code",
        ],
        page_size=200,
        max_records=500,
    )
    return {str(row.get("correlation_id") or ""): row for row in rows}


def _check_rows(
    seeded: list[dict[str, Any]],
    stored: dict[str, dict[str, Any]],
    problem_id: str,
    *,
    repair: bool,
) -> None:
    if len(stored) != len(seeded):
        raise WorldError(f"incident count {len(stored)} expected {len(seeded)}")
    for fixture in seeded:
        correlation = str(fixture["correlation_id"])
        row = stored.get(correlation)
        if row is None:
            raise WorldError(f"{correlation} was not stored")
        if str(row.get("state") or "") != "6":
            raise WorldError(f"{correlation} state {row.get('state')}")
        if str(row.get("incident_state") or "") != "6":
            raise WorldError(f"{correlation} incident_state {row.get('incident_state')}")
        if not _false(row.get("active")):
            raise WorldError(f"{correlation} is still active")
        if str(row.get("category") or "") != "software":
            raise WorldError(f"{correlation} category {row.get('category')}")
        if str(row.get("business_service") or "") != "":
            raise WorldError(f"{correlation} business_service was set")
        if str(row.get("close_code") or "") != "Solution provided":
            raise WorldError(f"{correlation} close_code {row.get('close_code')}")
        if str(row.get("opened_at") or "") != fixture["opened_at"]:
            raise WorldError(f"{correlation} opened_at {row.get('opened_at')}")
        parent = str(row.get("parent") or "")
        if fixture.get("parent") == "E01":
            if parent != problem_id and repair:
                raise WorldError(f"{correlation} parent was not the E01 problem")
        elif parent:
            raise WorldError(f"{correlation} parent was set")


def _sweep(
    admin: ServiceNowClient,
    settings: Settings,
    manifest: dict[str, Any],
    ledger: Ledger,
) -> None:
    _sweep_query(admin, manifest, ledger, "sys_db_object", f"name={STAGE}", "staging_tables", STAGE)
    _sweep_query(
        admin,
        manifest,
        ledger,
        "sys_dictionary",
        f"name={STAGE}",
        "dictionary",
        STAGE,
    )
    _sweep_query(
        admin,
        manifest,
        ledger,
        "sys_documentation",
        f"name={STAGE}",
        "documentation",
        STAGE,
    )
    _sweep_query(
        admin,
        manifest,
        ledger,
        "sys_transform_map",
        f"name={MAP_NAME}",
        "transform_maps",
        MAP_NAME,
    )
    _sweep_query(
        admin,
        manifest,
        ledger,
        "sys_transform_entry",
        f"source_table={STAGE}",
        "field_maps",
        MAP_NAME,
    )
    _sweep_query(
        admin,
        manifest,
        ledger,
        "sys_import_set",
        f"table_name={STAGE}",
        "import_sets",
        STAGE,
    )
    _sweep_query(
        admin,
        manifest,
        ledger,
        "sys_ws_definition",
        "service_id=syne2e_problem_state",
        "endpoint",
        "syne2e_problem_state",
    )
    definitions = admin.get_table(
        "sys_ws_definition",
        query="service_id=syne2e_problem_state",
        fields=["sys_id"],
        limit=5,
    )
    for definition in definitions:
        _sweep_query(
            admin,
            manifest,
            ledger,
            "sys_ws_operation",
            f"web_service_definition={definition['sys_id']}",
            "endpoint",
            "operation",
        )
    for label, user_name in (
        ("incident user", settings.sn_incident_user),
        ("problem user", settings.sn_problem_user),
        ("authority user", settings.sn_authority_user),
    ):
        user_id = _user_id(admin, user_name)
        _keep_record(manifest, ledger, "sys_user", user_id, label)
        _sweep_query(
            admin,
            manifest,
            ledger,
            "sys_user_has_role",
            f"user={user_id}",
            "records",
            "role grant",
            record_table="sys_user_has_role",
        )
        _sweep_query(
            admin,
            manifest,
            ledger,
            "sys_user_grmember",
            f"user={user_id}",
            "records",
            "membership",
            record_table="sys_user_grmember",
        )
    _sweep_query(
        admin,
        manifest,
        ledger,
        "problem",
        "correlation_idSTARTSWITHSYN-E2E-PRB",
        "records",
        "problem",
        record_table="problem",
    )
    _sweep_query(
        admin,
        manifest,
        ledger,
        "kb_knowledge",
        "short_descriptionSTARTSWITHSYN-E2E-",
        "records",
        ARTICLE_SHORT,
        record_table="kb_knowledge",
    )
    _sweep_query(
        admin,
        manifest,
        ledger,
        "kb_template_known_error_article",
        "short_descriptionSTARTSWITHSYN-E2E-",
        "records",
        ARTICLE_SHORT,
        record_table="kb_template_known_error_article",
    )
    _sweep_query(
        admin,
        manifest,
        ledger,
        "incident",
        "correlation_idSTARTSWITHSYN-E2E-INC",
        "records",
        "incident",
        record_table="incident",
    )


def _sweep_query(
    admin: ServiceNowClient,
    manifest: dict[str, Any],
    ledger: Ledger,
    table: str,
    query: str,
    bucket: str,
    key: str,
    *,
    record_table: str = "",
) -> None:
    rows = admin.get_records(
        table,
        query=query,
        fields=["sys_id"],
        page_size=200,
        max_records=500,
    )
    for row in rows:
        sys_id = str(row.get("sys_id") or "")
        if record_table or bucket == "records":
            _keep_record(manifest, ledger, record_table or table, sys_id, key)
        else:
            _keep(manifest, ledger, bucket, table, sys_id, key)


def _record_documentation(
    admin: ServiceNowClient,
    manifest: dict[str, Any],
    ledger: Ledger,
    table_name: str,
    element: str,
) -> None:
    if element:
        query = f"name={table_name}^element={element}"
    else:
        query = f"name={table_name}^elementISEMPTY"
    rows = admin.get_table(
        "sys_documentation",
        query=query,
        fields=["sys_id", "element"],
        limit=20,
    )
    for row in rows:
        label = f"{table_name}.{row.get('element') or 'table'}"
        _keep(manifest, ledger, "documentation", "sys_documentation", str(row["sys_id"]), label)


def _keep(
    manifest: dict[str, Any],
    ledger: Ledger,
    bucket: str,
    table: str,
    sys_id: str,
    key: str,
) -> None:
    if len(sys_id) != 32:
        return
    manifest.setdefault(bucket, [])
    add_artifact(manifest, bucket, sys_id.lower(), key)
    ledger.create(table, sys_id, key)


def _keep_record(
    manifest: dict[str, Any],
    ledger: Ledger,
    table: str,
    sys_id: str,
    key: str,
) -> None:
    if len(sys_id) != 32:
        return
    add_record(manifest, table, sys_id.lower(), key)
    ledger.create(table, sys_id, key)


def _caller(admin: ServiceNowClient, settings: Settings) -> str:
    skip = {
        settings.sn_incident_user,
        settings.sn_problem_user,
        settings.sn_authority_user,
    }
    rows = admin.get_records(
        "sys_user",
        query="user_nameSTARTSWITHsyn.^active=true",
        fields=["sys_id", "user_name"],
        page_size=100,
        max_records=200,
    )
    chosen = [row for row in rows if str(row.get("user_name") or "") not in skip]
    chosen.sort(key=lambda row: str(row.get("user_name") or ""))
    if not chosen:
        raise WorldError("no active syn. caller")
    return str(chosen[0]["sys_id"])


def _cis(admin: ServiceNowClient, names: set[str]) -> dict[str, str]:
    found = {}
    for name in sorted(names):
        found[name] = _one(admin, "cmdb_ci", f"name={name}")
    return found


def _one(admin: ServiceNowClient, table: str, query: str) -> str:
    rows = admin.get_table(table, query=query, fields=["sys_id"], limit=1)
    if not rows:
        raise WorldError(f"{table} row was not found")
    return str(rows[0]["sys_id"])


def _user_id(admin: ServiceNowClient, user_name: str) -> str:
    return _one(admin, "sys_user", f"user_name={user_name}")


def _read_article(admin: ServiceNowClient, article_id: str) -> dict[str, Any]:
    last: ServiceNowError | None = None
    for table in ("kb_knowledge", "kb_template_known_error_article"):
        try:
            return admin.get_record(
                table,
                article_id,
                fields=["workflow_state", "short_description"],
            )
        except ServiceNowError as exc:
            last = exc
            if exc.status_code == 404:
                continue
            raise http_failure("E01 article read", exc) from None
    raise http_failure("E01 article read", last or ServiceNowError("missing", 404))


def _delete_where(admin: ServiceNowClient, table: str, query: str) -> None:
    rows = admin.get_table(table, query=query, fields=["sys_id"], limit=20)
    for row in rows:
        _delete_quiet(admin, table, str(row.get("sys_id") or ""))


def _delete_quiet(admin: ServiceNowClient, table: str, sys_id: str) -> None:
    if len(sys_id) != 32:
        return
    try:
        admin.delete_record(table, sys_id)
    except ServiceNowError:
        return


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "t", "yes"}


def _false(value: object) -> bool:
    return str(value).strip().lower() in {"false", "0", "f", "no"}


def _is_false(value: object) -> bool:
    return _false(value)
