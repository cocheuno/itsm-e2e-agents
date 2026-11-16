"""The one approved instance change: a Scripted REST endpoint for this build.

Adapted from the pm-agent endpoint. It still evaluates the problem state model, still
requires problem_coordinator for a move, and still writes only the short field list.
It accepts this build's marker, SYN-E2E-, and refuses any other record. Phase 0 installs
it for a probe and removes it. From Phase 1, seed installs it and teardown removes it.
"""

from __future__ import annotations

import json
from typing import Any

from cm_agents.servicenow.client import ServiceNowClient, ServiceNowError

ENDPOINT_NAME = "[SYN-E2E] Problem State"
SERVICE_ID = "syne2e_problem_state"
PROBLEM_TAG = "SYN-E2E-"
ARTICLE_TAG = "SYN-E2E-"
PROBE_TAG = "SYN-E2E-PROBE"
ALLOWED_FIELDS = [
    "cause_notes",
    "workaround",
    "fix_notes",
    "close_notes",
    "resolution_code",
    "assigned_to",
]

_MOVE_SCRIPT = """(function process(request, response) {
    var FIELDS = __FIELDS__;
    var body = request.body.data || {};
    var check = body.check_only === true;
    var gr = new GlideRecord('problem');
    if (!body.sys_id || !gr.get(body.sys_id)) {
        response.setStatus(404);
        return {ok: false, error: 'problem not found'};
    }
    if ((gr.getValue('correlation_id') || '').indexOf('__TAG__') !== 0) {
        response.setStatus(403);
        return {ok: false, error: 'only __TAG__ problems can be moved by this API'};
    }
    if (!gs.hasRole('problem_coordinator')) {
        response.setStatus(403);
        return {ok: false, error: 'caller needs the problem_coordinator role'};
    }
    var fields = body.fields || {};
    for (var k in fields) {
        if (FIELDS.indexOf(k) < 0) {
            response.setStatus(400);
            return {ok: false, error: 'field not allowed: ' + k};
        }
        gr.setValue(k, fields[k]);
    }
    var from = gr.getValue('state'), to = String(body.state);
    var ev = new ProblemModel(gr.prb_model.getRefRecord()).evaluateTransition(gr, to);
    var failed = [];
    for (var i = 0; ev.conditions && i < ev.conditions.length; i++)
        if (!ev.conditions[i].passed) failed.push(ev.conditions[i].condition.name);
    if (!ev.transition_available) {
        response.setStatus(409);
        var reason = 'problem state model refused ' + from + ' -> ' + to;
        reason += failed.length ? ' (failed: ' + failed.join(', ') + ')' : ' (no such transition)';
        return {ok: false, from: from, to: to, error: reason};
    }
    if (check) return {ok: true, from: from, to: to, check_only: true};
    gr.setValue('state', to);
    gr.update();
    var after = new GlideRecord('problem');
    after.get(gr.getUniqueValue());
    var ok = after.getValue('state') === to;
    response.setStatus(ok ? 200 : 409);
    return {ok: ok, from: from, to: to, state: after.getValue('state'),
            error: ok ? '' : 'update did not stick (a business rule aborted it)'};
})(request, response);"""

_PUBLISH_SCRIPT = """(function process(request, response) {
    var body = request.body.data || {};
    var gr = new GlideRecord('kb_knowledge');
    if (!body.sys_id || !gr.get(body.sys_id)) {
        response.setStatus(404);
        return {ok: false, error: 'article not found'};
    }
    if ((gr.getValue('short_description') || '').indexOf('__TAG__') !== 0) {
        response.setStatus(403);
        return {ok: false, error: 'only __TAG__ articles can be published by this API'};
    }
    if (gr.getValue('workflow_state') === 'published')
        return {ok: true, workflow_state: 'published', already: true};
    if (!new KBKnowledge().canPublish(gr)) {
        response.setStatus(409);
        return {ok: false, workflow_state: gr.getValue('workflow_state'),
                error: 'canPublish() is false for this user and article'};
    }
    new global.KnowledgeUIAction().publish(gr);
    var after = new GlideRecord('kb_knowledge');
    after.get(gr.getUniqueValue());
    return {ok: true, workflow_state: after.getValue('workflow_state')};
})(request, response);"""


def move_script() -> str:
    return _MOVE_SCRIPT.replace("__FIELDS__", json.dumps(ALLOWED_FIELDS)).replace(
        "__TAG__",
        PROBLEM_TAG,
    )


def publish_script() -> str:
    return _PUBLISH_SCRIPT.replace("__TAG__", ARTICLE_TAG)


def operations_for(*, problem_state_verified: bool) -> tuple[str, ...]:
    """Install move only when writing problem_state did not reach Closed."""
    if problem_state_verified:
        return ("publish_article",)
    return ("move", "publish_article")


_SPECS = {
    "move": ("/move", move_script, "move one tagged problem one state"),
    "publish_article": ("/publish_article", publish_script, "publish one tagged knowledge article"),
}


def operation_path(base_uri: str, relative: str) -> str:
    return base_uri.rstrip("/") + "/" + relative.lstrip("/")


def install(admin: ServiceNowClient, operations: tuple[str, ...]) -> dict[str, Any]:
    """Create or refresh the endpoint. Returns the base URI and the operations written."""
    definition_id = _definition(admin)
    base = _base_uri(admin, definition_id)
    written = []
    for name in operations:
        relative, script_fn, description = _SPECS[name]
        _operation(admin, definition_id, name, relative, script_fn(), description)
        written.append({"name": name, "path": operation_path(base, relative)})
    _delete_unlisted(admin, definition_id, set(operations))
    return {"base_uri": base, "definition_id": definition_id, "operations": written}


def remove(admin: ServiceNowClient) -> dict[str, int]:
    """Delete the endpoint. Safe when it is already absent."""
    definitions = _definitions(admin)
    operations = 0
    for definition in definitions:
        definition_id = str(definition.get("sys_id") or "")
        for operation in _operations(admin, definition_id):
            _delete(admin, "sys_ws_operation", str(operation.get("sys_id") or ""))
            operations += 1
        _delete(admin, "sys_ws_definition", definition_id)
    return {"definitions": len(definitions), "operations": operations}


def endpoint_counts(admin: ServiceNowClient) -> dict[str, int | None]:
    try:
        definitions = _definitions(admin)
    except ServiceNowError:
        return {"sys_ws_definition": None, "sys_ws_operation": None}
    operations = 0
    try:
        for definition in definitions:
            operations += len(_operations(admin, str(definition.get("sys_id") or "")))
    except ServiceNowError:
        return {"sys_ws_definition": len(definitions), "sys_ws_operation": None}
    return {"sys_ws_definition": len(definitions), "sys_ws_operation": operations}


def post_operation(
    client: ServiceNowClient,
    base_uri: str,
    name: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    relative = _SPECS[name][0]
    path = operation_path(base_uri, relative)
    try:
        payload = client.request("POST", path, json=body)
    except ServiceNowError as exc:
        return {"status": exc.status_code, "result": {}, "error": str(exc)[:300]}
    result = payload.get("result")
    if not isinstance(result, dict):
        result = payload
    return {"status": 200, "result": result, "error": ""}


def _definition(admin: ServiceNowClient) -> str:
    data = {
        "name": ENDPOINT_NAME,
        "service_id": SERVICE_ID,
        "active": "true",
        "short_description": "SYN-E2E endpoint for tagged problem moves and article publish",
    }
    rows = _definitions(admin)
    if rows:
        updated = admin.update_record("sys_ws_definition", str(rows[0]["sys_id"]), data)
        return str(updated.get("sys_id") or rows[0]["sys_id"])
    created = admin.create_record("sys_ws_definition", data)
    return str(created["sys_id"])


def _definitions(admin: ServiceNowClient) -> list[dict[str, Any]]:
    return admin.get_table(
        "sys_ws_definition",
        query=f"service_id={SERVICE_ID}",
        fields=["sys_id", "base_uri", "name"],
        limit=5,
    )


def _base_uri(admin: ServiceNowClient, definition_id: str) -> str:
    row = admin.get_record("sys_ws_definition", definition_id, fields=["base_uri"])
    return str(row.get("base_uri") or "")


def _operation(
    admin: ServiceNowClient,
    definition_id: str,
    name: str,
    relative: str,
    script: str,
    description: str,
) -> None:
    body = {
        "web_service_definition": definition_id,
        "name": name,
        "http_method": "POST",
        "relative_path": relative,
        "operation_script": script,
        "active": "true",
        "requires_authentication": "true",
        "requires_acl_authorization": "false",
        "short_description": description,
    }
    rows = admin.get_table(
        "sys_ws_operation",
        query=f"web_service_definition={definition_id}^name={name}",
        fields=["sys_id"],
        limit=1,
    )
    if rows:
        _save_operation(admin, str(rows[0]["sys_id"]), body, update=True)
        return
    _save_operation(admin, "", body, update=False)


def _save_operation(
    admin: ServiceNowClient,
    sys_id: str,
    body: dict[str, Any],
    *,
    update: bool,
) -> None:
    try:
        if update:
            admin.update_record("sys_ws_operation", sys_id, body)
        else:
            admin.create_record("sys_ws_operation", body)
    except ServiceNowError:
        trimmed = {key: value for key, value in body.items() if key != "requires_acl_authorization"}
        if update:
            admin.update_record("sys_ws_operation", sys_id, trimmed)
        else:
            admin.create_record("sys_ws_operation", trimmed)


def _operations(admin: ServiceNowClient, definition_id: str) -> list[dict[str, Any]]:
    if not definition_id:
        return []
    return admin.get_table(
        "sys_ws_operation",
        query=f"web_service_definition={definition_id}",
        fields=["sys_id", "name"],
        limit=10,
    )


def _delete_unlisted(admin: ServiceNowClient, definition_id: str, keep: set[str]) -> None:
    for operation in _operations(admin, definition_id):
        if str(operation.get("name") or "") in keep:
            continue
        _delete(admin, "sys_ws_operation", str(operation.get("sys_id") or ""))


def _delete(admin: ServiceNowClient, table: str, sys_id: str) -> None:
    if len(sys_id) != 32:
        return
    try:
        admin.delete_record(table, sys_id)
    except ServiceNowError:
        return
