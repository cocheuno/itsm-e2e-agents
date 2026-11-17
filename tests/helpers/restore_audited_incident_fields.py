"""One-off restore of incident fields changed after 2026-11-16 22:18.

Not part of the product. The import map has business rules, transform scripts
other than this restore, and mandatory-field checks off. System work notes
are left in place. The On Hold incident that the close script resolved is
not updated.

Coalesce is the incident number. An empty correlation cannot coalesce, and
coalesce on sys_id is not reliable on an import set. The number is never
printed.

Run from the repository root:

    uv run python tests/helpers/restore_audited_incident_fields.py --dry-run
    uv run python tests/helpers/restore_audited_incident_fields.py
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections import Counter, defaultdict
from typing import Any

from cm_agents.data.load import IMPORT_ROW
from cm_agents.servicenow.client import ServiceNowClient, ServiceNowError

from e2e.cli import configure_logging
from e2e.errors import WorldError
from e2e.instance import http_failure, open_client
from e2e.settings import load_settings

STAGE = "u_syn_e2e_audit_restore"
MAP_NAME = "SYN-E2E Audit Restore"
AUDIT_FROM = "2026-11-16 22:18:00"
NOTE_MARK = "Known Error"
FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
SKIP_FIELDS = frozenset(
    {
        "work_notes",
        "comments",
        "comments_and_work_notes",
        "sys_mod_count",
        "sys_updated_on",
        "sys_updated_by",
        "sys_created_on",
        "sys_created_by",
        "sys_id",
        "number",
        "sys_class_name",
    }
)
_BOOL_WORDS = {
    "0": "false",
    "1": "true",
    "false": "false",
    "true": "true",
    "no": "false",
    "yes": "true",
}
_PAGE = 200
_BATCH = 40

RESTORE_SCRIPT = """(function runTransformScript(source, map, log, target) {
  target.setWorkflow(false);
  var raw = source.getValue('u_payload');
  if (!raw) {
    return;
  }
  var data = JSON.parse(raw);
  for (var name in data) {
    if (!data.hasOwnProperty(name)) {
      continue;
    }
    var value = data[name];
    target.setValue(name, value == null ? '' : (value + ''));
  }
})(source, map, log, target);
"""


def norm(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"null", "none"}:
        return ""
    return text


def canon(field: str, value: object) -> str:
    text = norm(value)
    if field == "active":
        return _BOOL_WORDS.get(text.lower(), text)
    return text


def group_of(correlation: str) -> str:
    if correlation.startswith("SYN-INC-"):
        return "change-seed"
    if correlation.startswith("SYN-E2E-"):
        return "e2e"
    if correlation.startswith("PMSYNTH") or correlation == "":
        return "neither"
    return "other"


def earliest_values(audits: list[dict[str, Any]]) -> dict[str, str]:
    """First old value of each field. `audits` must be oldest first."""
    found: dict[str, str] = {}
    for row in audits:
        field = norm(row.get("fieldname"))
        if field in SKIP_FIELDS or field in found or not FIELD_NAME.fullmatch(field):
            continue
        found[field] = canon(field, row.get("oldvalue"))
    return found


def plan_changes(current: dict[str, Any], desired: dict[str, str]) -> dict[str, str]:
    updates: dict[str, str] = {}
    for field, old in desired.items():
        if field in SKIP_FIELDS or not FIELD_NAME.fullmatch(field):
            continue
        want = canon(field, old)
        have = canon(field, current.get(field))
        if have != want:
            updates[field] = want
    return updates


def is_close_script_victim(identity: dict[str, str], marks: set[str]) -> bool:
    return (
        identity["group"] == "neither"
        and identity["correlation"] == ""
        and identity["close_code"] == "Resolved by problem"
        and "state_3_to_6" in marks
        and "hold_cleared" in marks
    )


def note_marks(row: dict[str, Any]) -> set[str]:
    marks: set[str] = set()
    field = norm(row.get("fieldname"))
    old = norm(row.get("oldvalue"))
    new = norm(row.get("newvalue"))
    if field == "state" and old == "3" and new == "6":
        marks.add("state_3_to_6")
    if field == "hold_reason" and old == "3" and new == "":
        marks.add("hold_cleared")
    return marks


def _self_check() -> None:
    audits = [
        {"fieldname": "state", "oldvalue": "7", "newvalue": "2"},
        {"fieldname": "state", "oldvalue": "2", "newvalue": "7"},
        {"fieldname": "active", "oldvalue": "0", "newvalue": "1"},
        {"fieldname": "work_notes", "oldvalue": "", "newvalue": "note"},
        {"fieldname": "company", "oldvalue": "", "newvalue": "abc"},
    ]
    desired = earliest_values(audits)
    if desired != {"state": "7", "active": "false", "company": ""}:
        raise WorldError("self-check earliest values failed")
    current = {"state": "2", "active": "true", "company": "abc"}
    if plan_changes(current, desired) != {"state": "7", "active": "false", "company": ""}:
        raise WorldError("self-check plan failed")
    if plan_changes({"state": "7", "active": "false", "company": ""}, desired) != {}:
        raise WorldError("self-check idempotent plan failed")
    victim = {
        "group": "neither",
        "correlation": "",
        "close_code": "Resolved by problem",
    }
    marks = note_marks({"fieldname": "state", "oldvalue": "3", "newvalue": "6"})
    marks |= note_marks({"fieldname": "hold_reason", "oldvalue": "3", "newvalue": ""})
    if not is_close_script_victim(victim, marks):
        raise WorldError("self-check exception match failed")
    if is_close_script_victim({**victim, "correlation": "PMSYNTH1"}, marks):
        raise WorldError("self-check exception scope failed")


def _pages(
    client: ServiceNowClient,
    table: str,
    query: str,
    fields: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset <= 20000:
        try:
            page = client.get_table(
                table,
                query=query,
                fields=fields,
                limit=_PAGE,
                offset=offset,
            )
        except ServiceNowError as exc:
            raise http_failure(f"read {table}", exc) from None
        rows.extend(page)
        if len(page) < _PAGE:
            return rows
        offset += _PAGE
    raise WorldError(f"read {table} exceeded the page limit")


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _noted_ids(client: ServiceNowClient) -> list[str]:
    query = (
        "name=incident^element=work_notes^sys_created_by=system"
        f"^sys_created_on>={AUDIT_FROM}^valueLIKE{NOTE_MARK}"
    )
    rows = _pages(client, "sys_journal_field", query, ["element_id"])
    found: list[str] = []
    seen: set[str] = set()
    for row in rows:
        element_id = norm(row.get("element_id"))
        if len(element_id) != 32 or element_id in seen:
            continue
        seen.add(element_id)
        found.append(element_id)
    return found


def _identities(
    client: ServiceNowClient,
    sys_ids: list[str],
) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    fields = ["sys_id", "number", "correlation_id", "close_code", "state", "active"]
    for batch in _chunks(sys_ids, _BATCH):
        query = "sys_idIN" + ",".join(batch)
        for row in _pages(client, "incident", query, fields):
            sys_id = norm(row.get("sys_id"))
            correlation = norm(row.get("correlation_id"))
            found[sys_id] = {
                "number": norm(row.get("number")),
                "correlation": correlation,
                "close_code": norm(row.get("close_code")),
                "state": norm(row.get("state")),
                "active": canon("active", row.get("active")),
                "group": group_of(correlation),
            }
    return found


def _audits(
    client: ServiceNowClient,
    sys_ids: list[str],
) -> tuple[dict[str, dict[str, str]], dict[str, set[str]]]:
    desired: dict[str, dict[str, str]] = defaultdict(dict)
    marks: dict[str, set[str]] = defaultdict(set)
    fields = ["documentkey", "fieldname", "oldvalue", "newvalue", "sys_created_on"]
    for index, batch in enumerate(_chunks(sys_ids, _BATCH), start=1):
        query = (
            "tablename=incident^documentkeyIN"
            + ",".join(batch)
            + f"^sys_created_on>={AUDIT_FROM}^ORDERBYsys_created_on"
        )
        print(f"audits batch {index}", flush=True)
        for row in _pages(client, "sys_audit", query, fields):
            sys_id = norm(row.get("documentkey"))
            field = norm(row.get("fieldname"))
            marks[sys_id] |= note_marks(row)
            if field in SKIP_FIELDS or not FIELD_NAME.fullmatch(field):
                continue
            if field not in desired[sys_id]:
                desired[sys_id][field] = canon(field, row.get("oldvalue"))
    return desired, marks


def _current_fields(
    client: ServiceNowClient,
    sys_ids: list[str],
    field_names: list[str],
) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    columns = ["sys_id", *field_names]
    for batch in _chunks(sys_ids, _BATCH):
        query = "sys_idIN" + ",".join(batch)
        for row in _pages(client, "incident", query, columns):
            found[norm(row.get("sys_id"))] = row
    return found


def _build_plans(
    identities: dict[str, dict[str, str]],
    desired: dict[str, dict[str, str]],
    marks: dict[str, set[str]],
    current: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    victims = [
        sys_id
        for sys_id, identity in identities.items()
        if is_close_script_victim(identity, marks.get(sys_id, set()))
    ]
    if len(victims) != 1:
        raise WorldError(f"close-script exception count is {len(victims)}")
    plans: dict[str, dict[str, str]] = {}
    groups: dict[str, str] = {}
    for sys_id, identity in identities.items():
        if sys_id in victims:
            continue
        if identity["group"] == "other":
            continue
        updates = plan_changes(current.get(sys_id, {}), desired.get(sys_id, {}))
        if not updates:
            continue
        plans[sys_id] = updates
        groups[sys_id] = identity["group"]
    return plans, {victims[0]: identities[victims[0]]["group"]}


def _summarize(
    identities: dict[str, dict[str, str]],
    plans: dict[str, dict[str, str]],
    victim: str,
) -> None:
    noted: Counter[str] = Counter(row["group"] for row in identities.values())
    print(
        "noted"
        f" change-seed={noted['change-seed']}"
        f" neither={noted['neither']}"
        f" e2e={noted['e2e']}"
        f" other={noted['other']}",
        flush=True,
    )
    if noted["other"]:
        raise WorldError("noted incidents include a correlation outside the three groups")
    if noted["change-seed"] != 164 or noted["neither"] != 267 or noted["e2e"] != 8:
        raise WorldError("noted incident counts are not 164, 267, and 8")
    identity = identities[victim]
    print(
        "exception skipped"
        f" group={identity['group']}"
        f" correlation=empty"
        f" state={identity['state']}"
        f" active={identity['active']}"
        " close_code=Resolved by problem",
        flush=True,
    )
    field_counts: Counter[tuple[str, str]] = Counter()
    row_counts: Counter[str] = Counter()
    for sys_id, updates in plans.items():
        group = identities[sys_id]["group"]
        row_counts[group] += 1
        for field in updates:
            field_counts[(group, field)] += 1
    for group in ("change-seed", "neither", "e2e"):
        print(f"restore rows {group}={row_counts[group]}", flush=True)
    for (group, field), count in sorted(field_counts.items()):
        print(f"restore field {group} {field}={count}", flush=True)


def _require_scope(noted: Counter[str]) -> None:
    if noted["change-seed"] != 164 or noted["neither"] != 267 or noted["e2e"] != 8:
        raise WorldError("refusing to write because the noted counts changed")
    if noted["other"]:
        raise WorldError("refusing to write because an unexpected correlation was noted")


def _install_stage(client: ServiceNowClient) -> dict[str, str]:
    _remove_stage(client)
    try:
        created = client.create_record(
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
    table_id = norm(created.get("sys_id"))
    table_name = norm(created.get("name")) or STAGE
    for element, length in (("number", "40"), ("payload", "4000")):
        try:
            client.create_record(
                "sys_dictionary",
                {
                    "name": table_name,
                    "element": f"u_{element}",
                    "column_label": element,
                    "internal_type": "string",
                    "max_length": length,
                    "active": "true",
                },
            )
        except ServiceNowError as exc:
            raise http_failure(f"column {element}", exc) from None
    try:
        transform = client.create_record(
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
    map_id = norm(transform.get("sys_id"))
    stored = client.get_record(
        "sys_transform_map",
        map_id,
        fields=["run_business_rules", "run_script", "enforce_mandatory_fields"],
    )
    for field in ("run_business_rules", "run_script", "enforce_mandatory_fields"):
        if norm(stored.get(field)).lower() not in {"false", "0", "no"}:
            raise WorldError(f"transform map {field} is not false")
    try:
        client.create_record(
            "sys_transform_entry",
            {
                "map": map_id,
                "source_table": table_name,
                "target_table": "incident",
                "source_field": "u_number",
                "target_field": "number",
                "choice_action": "ignore",
                "use_source_script": "false",
                "coalesce": "true",
            },
        )
        client.create_record(
            "sys_transform_script",
            {
                "map": map_id,
                "when": "onBefore",
                "active": "true",
                "order": "100",
                "script": RESTORE_SCRIPT,
            },
        )
    except ServiceNowError as exc:
        raise http_failure("transform script", exc) from None
    return {"table_id": table_id, "table_name": table_name, "map_id": map_id}


def _remove_stage(client: ServiceNowClient) -> None:
    """Drop the one-off import table. Dictionary deletes return 403 until the table is gone."""
    tables = client.get_table(
        "sys_db_object",
        query=f"name={STAGE}",
        fields=["sys_id", "name"],
        limit=2,
    )
    maps = client.get_table(
        "sys_transform_map",
        query=f"name={MAP_NAME}",
        fields=["sys_id"],
        limit=5,
    )
    for transform in maps:
        map_id = norm(transform.get("sys_id"))
        for table in ("sys_transform_script", "sys_transform_entry"):
            for row in _pages(client, table, f"map={map_id}", ["sys_id"]):
                _delete(client, table, norm(row.get("sys_id")))
        _delete(client, "sys_transform_map", map_id)
    table_name = STAGE
    if tables:
        table_name = norm(tables[0].get("name")) or STAGE
        try:
            staged = _pages(client, table_name, "sys_idISNOTEMPTY", ["sys_id", "sys_import_set"])
        except WorldError:
            staged = []
        import_sets = {norm(row.get("sys_import_set")) for row in staged}
        for row in staged:
            _delete(client, table_name, norm(row.get("sys_id")))
        for import_set in import_sets:
            if len(import_set) == 32:
                _delete(client, "sys_import_set", import_set)
    for row in _pages(client, "sys_import_set", f"table_name={table_name}", ["sys_id"]):
        _delete(client, "sys_import_set", norm(row.get("sys_id")))
    for row in tables:
        _delete(client, "sys_db_object", norm(row.get("sys_id")))
    for table in ("sys_dictionary", "sys_documentation"):
        for row in _pages(client, table, f"name={table_name}", ["sys_id"]):
            _delete(client, table, norm(row.get("sys_id")), strict=False)
    left_table = client.count("sys_db_object", f"name={STAGE}")
    left_dict = client.count("sys_dictionary", f"name={STAGE}")
    left_doc = client.count("sys_documentation", f"name={STAGE}")
    left_map = client.count("sys_transform_map", f"name={MAP_NAME}")
    if left_table or left_dict or left_doc or left_map:
        raise WorldError(
            "restore import remains"
            f" table={left_table} dictionary={left_dict}"
            f" documentation={left_doc} map={left_map}"
        )


def _delete(
    client: ServiceNowClient,
    table: str,
    sys_id: str,
    *,
    strict: bool = True,
) -> None:
    if len(sys_id) != 32:
        return
    try:
        client.delete_record(table, sys_id)
    except ServiceNowError as exc:
        if not strict and exc.status_code in {403, 404}:
            return
        if exc.status_code == 404:
            return
        raise http_failure(f"delete {table}", exc) from None


def _post_one(
    client: ServiceNowClient,
    table_name: str,
    number: str,
    updates: dict[str, str],
) -> str:
    payload = {"u_number": number, "u_payload": json.dumps(updates, separators=(",", ":"))}
    try:
        response = client.request("POST", f"/api/now/import/{table_name}", json=payload)
    except ServiceNowError as exc:
        raise http_failure("import", exc) from None
    results = response.get("result")
    if isinstance(results, dict):
        results = [results]
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise WorldError("import returned an unexpected result")
    status = norm(results[0].get("status"))
    if status != "updated":
        raise WorldError(f"import status {status or 'failed'}")
    target = norm(results[0].get("sys_id"))
    if len(target) != 32:
        raise WorldError("import did not name the target")
    return target


def _apply(
    client: ServiceNowClient,
    table_name: str,
    identities: dict[str, dict[str, str]],
    plans: dict[str, dict[str, str]],
) -> None:
    ordered = sorted(
        plans,
        key=lambda sys_id: (
            0 if plans[sys_id].get("active") == "false" else 1,
            identities[sys_id]["group"],
        ),
    )
    checked = False
    for index, sys_id in enumerate(ordered, start=1):
        identity = identities[sys_id]
        target = _post_one(client, table_name, identity["number"], plans[sys_id])
        if target != sys_id:
            raise WorldError("import updated a different incident")
        if not checked:
            _verify_rows(client, {sys_id: plans[sys_id]})
            checked = True
            print("canary verified", flush=True)
        if index % 25 == 0:
            print(f"imported {index}", flush=True)
    print(f"imported {len(ordered)}", flush=True)


def _verify_rows(client: ServiceNowClient, plans: dict[str, dict[str, str]]) -> None:
    fields = sorted({field for updates in plans.values() for field in updates})
    current = _current_fields(client, list(plans), fields)
    bad: Counter[str] = Counter()
    for sys_id, updates in plans.items():
        row = current.get(sys_id, {})
        for field, want in updates.items():
            if canon(field, row.get(field)) != canon(field, want):
                bad[field] += 1
    if bad:
        detail = " ".join(f"{field}={count}" for field, count in sorted(bad.items()))
        raise WorldError(f"verify failed {detail}")


def _note_counts(client: ServiceNowClient, identities: dict[str, dict[str, str]]) -> None:
    by_group: dict[str, list[str]] = defaultdict(list)
    for sys_id, identity in identities.items():
        by_group[identity["group"]].append(sys_id)
    counts: Counter[str] = Counter()
    for group, sys_ids in by_group.items():
        for batch in _chunks(sys_ids, _BATCH):
            query = (
                "name=incident^element=work_notes^sys_created_by=system"
                f"^sys_created_on>={AUDIT_FROM}^element_idIN" + ",".join(batch)
            )
            try:
                counts[group] += client.count("sys_journal_field", query)
            except ServiceNowError as exc:
                raise http_failure("count notes", exc) from None
    print(
        "notes"
        f" change-seed={counts['change-seed']}"
        f" neither={counts['neither']}"
        f" e2e={counts['e2e']}",
        flush=True,
    )


def _query_counts(client: ServiceNowClient) -> None:
    try:
        active_closed = client.count("incident", "active=true^stateIN6,7")
        hot = client.count("incident", "active=true^priorityIN1,2")
        hot_change = client.count(
            "incident",
            "active=true^priorityIN1,2^correlation_idSTARTSWITHSYN-INC-",
        )
        hot_e2e = client.count(
            "incident",
            "active=true^priorityIN1,2^correlation_idSTARTSWITHSYN-E2E-",
        )
        hot_pm = client.count(
            "incident",
            "active=true^priorityIN1,2^correlation_idSTARTSWITHPMSYNTH",
        )
        hot_empty = client.count(
            "incident",
            "active=true^priorityIN1,2^correlation_idISEMPTY",
        )
    except ServiceNowError as exc:
        raise http_failure("count incidents", exc) from None
    print(f"active while resolved or closed={active_closed}", flush=True)
    print(f"open priority 1 or 2={hot}", flush=True)
    print(
        "open priority by correlation"
        f" change-seed={hot_change}"
        f" e2e={hot_e2e}"
        f" pmsynth={hot_pm}"
        f" empty={hot_empty}",
        flush=True,
    )
    if active_closed > 50:
        return
    rows = _pages(
        client,
        "incident",
        "active=true^stateIN6,7",
        ["correlation_id", "state", "close_code"],
    )
    buckets: Counter[str] = Counter()
    for row in rows:
        buckets[group_of(norm(row.get("correlation_id")))] += 1
    print(
        "active resolved groups"
        f" change-seed={buckets['change-seed']}"
        f" neither={buckets['neither']}"
        f" e2e={buckets['e2e']}"
        f" other={buckets['other']}",
        flush=True,
    )


def run(dry_run: bool) -> int:
    _self_check()
    settings = load_settings()
    configure_logging(settings.secret_values())
    logging.getLogger().setLevel(logging.WARNING)
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        print("before", flush=True)
        _query_counts(admin)
        sys_ids = _noted_ids(admin)
        print(f"noted incidents={len(sys_ids)}", flush=True)
        identities = _identities(admin, sys_ids)
        if len(identities) != len(sys_ids):
            raise WorldError("a noted incident is no longer present")
        desired, marks = _audits(admin, sys_ids)
        field_names = sorted({field for row in desired.values() for field in row})
        current = _current_fields(admin, sys_ids, field_names)
        plans, victims = _build_plans(identities, desired, marks, current)
        victim = next(iter(victims))
        _summarize(identities, plans, victim)
        _note_counts(admin, identities)
        if dry_run:
            print("dry-run no writes", flush=True)
            return 0
        noted = Counter(row["group"] for row in identities.values())
        _require_scope(noted)
        before = admin.count("incident", "sys_idISNOTEMPTY")
        print("installing restore import", flush=True)
        stage: dict[str, str] = {}
        try:
            stage = _install_stage(admin)
            _apply(admin, stage["table_name"], identities, plans)
            _verify_rows(admin, plans)
            print("verify ok", flush=True)
        finally:
            print("removing restore import", flush=True)
            _remove_stage(admin)
            left = admin.get_table(
                "sys_db_object",
                query=f"name={STAGE}",
                fields=["sys_id"],
                limit=1,
            )
            if left:
                raise WorldError("restore import table is still present")
            print("restore import removed", flush=True)
        after = admin.count("incident", "sys_idISNOTEMPTY")
        if before != after:
            raise WorldError(f"incident count changed by {after - before}")
        print(f"incident count unchanged={after}", flush=True)
        kept = admin.get_record(
            "incident",
            victim,
            fields=["state", "active", "close_code", "correlation_id"],
        )
        if norm(kept.get("close_code")) != "Resolved by problem":
            raise WorldError("exception close code changed")
        if canon("active", kept.get("active")) != "true" or norm(kept.get("state")) != "6":
            raise WorldError("exception state changed")
        print("exception still resolved", flush=True)
        print("after", flush=True)
        _query_counts(admin)
        _note_counts(admin, identities)
    return 0


def _cleanup() -> int:
    settings = load_settings()
    configure_logging(settings.secret_values())
    logging.getLogger().setLevel(logging.WARNING)
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        _remove_stage(admin)
    print("restore import removed", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args not in ([], ["--dry-run"], ["--cleanup"]):
        print(
            "usage: restore_audited_incident_fields.py [--dry-run|--cleanup]",
            file=sys.stderr,
        )
        return 2
    try:
        if args == ["--cleanup"]:
            return _cleanup()
        return run(dry_run=args == ["--dry-run"])
    except WorldError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ServiceNowError as exc:
        code = exc.status_code if exc.status_code is not None else "none"
        print(f"request failed HTTP {code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
