"""Problem, known-error article, and journal writes. The problem user calls them."""

from __future__ import annotations

from typing import Any

from cm_agents.servicenow.client import ServiceNowError

from e2e.adapters.incident import ref
from e2e.data.catalog import known_error_text
from e2e.data.world import MARKER, history_note_line
from e2e.errors import WorldError
from e2e.instance import http_failure
from e2e.state_api import post_operation

PROBLEM_FIELDS = [
    "sys_id",
    "number",
    "state",
    "known_error",
    "rfc",
    "correlation_id",
    "opened_by",
    "close_notes",
    "primary_known_error_article",
    "cmdb_ci",
    "short_description",
]


def article_short(ci_name: str) -> str:
    return f"{MARKER} Known error for {ci_name}"


def ensure_problem(
    writer: Any,
    key: str,
    *,
    ci_name: str,
    category: str,
) -> tuple[bool, dict[str, Any]]:
    """Return the problem for this cluster key, creating it when it is absent."""
    try:
        rows = writer.get_table(
            "problem",
            query=f"correlation_id={key}",
            fields=PROBLEM_FIELDS,
            limit=2,
        )
    except ServiceNowError as exc:
        raise http_failure("problem", exc) from None
    if len(rows) > 1:
        raise WorldError("more than one problem uses the cluster key")
    if rows:
        return False, rows[0]
    ci_id = _one(writer, "cmdb_ci", f"name={ci_name}")
    try:
        created = writer.create_record(
            "problem",
            {
                "short_description": f"{MARKER} {ci_name} {category}",
                "correlation_id": key,
                "cmdb_ci": ci_id,
            },
        )
    except ServiceNowError as exc:
        raise http_failure("problem", exc) from None
    problem_id = str(created.get("sys_id") or "")
    if len(problem_id) != 32:
        raise WorldError("problem was not created")
    return True, read_problem(writer, problem_id)


def read_problem(writer: Any, problem_id: str) -> dict[str, Any]:
    try:
        return writer.get_record("problem", problem_id, fields=PROBLEM_FIELDS)
    except ServiceNowError as exc:
        raise http_failure("problem", exc) from None


def problem_state(writer: Any, problem_id: str) -> str:
    return str(read_problem(writer, problem_id).get("state") or "")


def ensure_article(
    writer: Any,
    base_uri: str,
    problem_id: str,
    problem: dict[str, Any],
    *,
    ci_name: str,
    mechanism: str,
) -> str:
    """Publish the known-error article. The primary article field stays empty."""
    cause, workaround = known_error_text(mechanism)
    if not cause or not workaround:
        raise WorldError("known error text was empty")
    state = str(problem.get("state") or "")
    if state not in {"103", "104", "106", "107"}:
        assigned = ref(problem.get("opened_by"))
        if not assigned:
            assigned = ref(read_problem(writer, problem_id).get("opened_by"))
        if not assigned:
            raise WorldError("problem opener was empty")
        _move_to(writer, base_uri, problem_id, "102", {"assigned_to": assigned})
        _move_to(
            writer,
            base_uri,
            problem_id,
            "103",
            {"cause_notes": cause, "workaround": workaround},
            retry={
                "assigned_to": assigned,
                "cause_notes": cause,
                "workaround": workaround,
                "fix_notes": cause,
                "close_notes": workaround,
                "resolution_code": "fix_applied",
            },
        )
    short = article_short(ci_name)
    article = _find_article(writer, problem_id, short)
    ci_id = _one(writer, "cmdb_ci", f"name={ci_name}")
    if article is None:
        try:
            created = writer.create_record(
                "kb_knowledge",
                {
                    "short_description": short,
                    "kb_knowledge_base": _knowledge_base(writer),
                    "text": f"{cause} {workaround}",
                    "workflow_state": "draft",
                    "source": problem_id,
                    "cmdb_ci": ci_id,
                },
            )
        except ServiceNowError as exc:
            raise http_failure("article", exc) from None
        article_id = str(created.get("sys_id") or "")
        if len(article_id) != 32:
            raise WorldError("article was not created")
        article = _read_article(writer, article_id)
    article_id = str(article.get("sys_id") or "")
    if str(article.get("workflow_state") or "") != "published":
        _publish(writer, base_uri, article_id)
        article = _read_article(writer, article_id)
    if str(article.get("workflow_state") or "") != "published":
        raise WorldError("article did not publish")
    if str(article.get("source") or "") != problem_id:
        raise WorldError("article source was not the problem")
    if ref(article.get("cmdb_ci")) != ci_id:
        raise WorldError("article CI was not the cluster CI")
    number = str(article.get("number") or "")
    if not number:
        raise WorldError("article number was empty")
    current = read_problem(writer, problem_id)
    if str(current.get("primary_known_error_article") or ""):
        raise WorldError("known error article field was set")
    if not _truthy(current.get("known_error")):
        try:
            writer.update_record("problem", problem_id, {"known_error": "true"})
        except ServiceNowError as exc:
            raise http_failure("known error", exc) from None
        current = read_problem(writer, problem_id)
        if not _truthy(current.get("known_error")):
            raise WorldError("known error did not stick")
        if str(current.get("primary_known_error_article") or ""):
            raise WorldError("known error article field was set")
    note(writer, problem_id, f"Known error article {number}")
    print(f"case article={number}")
    return number


def link_arrivals(
    writer: Any,
    problem_id: str,
    rows: list[dict[str, Any]],
    *,
    delivered: frozenset[str],
) -> int:
    """Parent-link the delivered arrivals. Closed history is not linked here."""
    linked = 0
    for row in rows:
        if str(row.get("correlation_id") or "") not in delivered:
            continue
        if str(row.get("state") or "") != "6":
            continue
        incident_id = str(row.get("sys_id") or "")
        if ref(row.get("parent")) == problem_id:
            linked += 1
            continue
        try:
            writer.update_record("incident", incident_id, {"parent": problem_id})
            updated = writer.get_record("incident", incident_id, fields=["parent"])
        except ServiceNowError as exc:
            raise http_failure("arrival parent", exc) from None
        if ref(updated.get("parent")) != problem_id:
            raise WorldError("arrival parent did not stick")
        linked += 1
    return linked


def note_history(
    writer: Any,
    problem_id: str,
    rows: list[dict[str, Any]],
    *,
    delivered: frozenset[str],
) -> int:
    journal = _journal(writer, problem_id)
    noted = 0
    for row in rows:
        if str(row.get("correlation_id") or "") in delivered:
            continue
        line = history_note_line(
            str(row.get("number") or ""),
            str(row.get("correlation_id") or ""),
        )
        if line in journal:
            noted += 1
            continue
        journal = note(writer, problem_id, line, current=journal)
        noted += 1
    return noted


def note(writer: Any, problem_id: str, line: str, current: str | None = None) -> str:
    journal = _journal(writer, problem_id) if current is None else current
    if line in journal:
        return journal
    try:
        writer.update_record("problem", problem_id, {"work_notes": line})
    except ServiceNowError as exc:
        if exc.status_code == 403 and problem_state(writer, problem_id) == "107":
            return journal
        raise http_failure("problem note", exc) from None
    return journal + "\n" + line


def set_rfc(writer: Any, problem_id: str, change_id: str) -> None:
    current = ref(read_problem(writer, problem_id).get("rfc"))
    if current == change_id:
        return
    try:
        writer.update_record("problem", problem_id, {"rfc": change_id})
    except ServiceNowError as exc:
        raise http_failure("problem rfc", exc) from None
    if ref(read_problem(writer, problem_id).get("rfc")) != change_id:
        raise WorldError("problem rfc did not stick")


def close_problem(
    writer: Any,
    base_uri: str,
    problem_id: str,
    *,
    verify_days: int,
    recurrence: int,
    linked: int,
    history_count: int,
    mechanism: str,
) -> str:
    cause, _workaround = known_error_text(mechanism)
    notes = (
        f"Recurrence in {verify_days} days: {recurrence}. "
        f"Arrivals linked: {linked}. History listed: {history_count}."
    )
    fields = {
        "fix_notes": cause,
        "close_notes": notes,
        "resolution_code": "fix_applied",
    }
    state = problem_state(writer, problem_id)
    if state != "107":
        note(writer, problem_id, notes)
    if state == "103":
        state = _move_to(
            writer,
            base_uri,
            problem_id,
            "104",
            {"fix_notes": cause, "close_notes": notes},
            retry=fields,
        )
    if state == "104":
        state = _move_to(writer, base_uri, problem_id, "106", fields)
    if state == "106":
        state = _move_to(writer, base_uri, problem_id, "107", fields)
    if state != "107":
        raise WorldError(f"problem closed as state {state or 'empty'}")
    stored = str(read_problem(writer, problem_id).get("close_notes") or "")
    if not stored.startswith(f"Recurrence in {verify_days} days: {recurrence}."):
        raise WorldError("close notes do not name the recurrence")
    return state


def _move_to(
    writer: Any,
    base_uri: str,
    problem_id: str,
    target: str,
    fields: dict[str, str],
    retry: dict[str, str] | None = None,
) -> str:
    state, status = _move_once(writer, base_uri, problem_id, target, fields)
    if state == target:
        return state
    if retry is None:
        raise WorldError(f"move to {target} read {state or 'empty'} HTTP {status}")
    state, status = _move_once(writer, base_uri, problem_id, target, retry)
    if state != target:
        raise WorldError(f"move to {target} read {state or 'empty'} HTTP {status}")
    return state


def _move_once(
    writer: Any,
    base_uri: str,
    problem_id: str,
    target: str,
    fields: dict[str, str],
) -> tuple[str, int]:
    response = post_operation(
        writer,
        base_uri,
        "move",
        {"sys_id": problem_id, "state": target, "fields": fields},
    )
    state = problem_state(writer, problem_id)
    status = int(response["status"])
    print(f"case move ->{target} status={status} read={state or 'empty'}")
    if status == 403:
        raise WorldError(f"move to {target} was refused")
    return state, status


def _publish(writer: Any, base_uri: str, article_id: str) -> None:
    response = post_operation(writer, base_uri, "publish_article", {"sys_id": article_id})
    status = int(response["status"])
    print(f"case publish status={status}")
    if status == 403:
        raise WorldError("article publish was refused")


def _journal(writer: Any, problem_id: str) -> str:
    try:
        rows = writer.get_table(
            "sys_journal_field",
            query=f"name=problem^element=work_notes^element_id={problem_id}",
            fields=["value"],
            limit=80,
        )
    except ServiceNowError as exc:
        raise http_failure("problem journal", exc) from None
    return "\n".join(str(row.get("value") or "") for row in rows)


def _knowledge_base(writer: Any) -> str:
    try:
        rows = writer.get_table(
            "kb_knowledge_base",
            query="title=Known Error^active=true",
            fields=["sys_id"],
            limit=1,
        )
    except ServiceNowError as exc:
        rows = []
        if exc.status_code not in {400, 403}:
            raise http_failure("knowledge base", exc) from None
    if rows:
        return str(rows[0].get("sys_id") or "")
    try:
        articles = writer.get_table(
            "kb_knowledge",
            query=f"short_descriptionSTARTSWITH{MARKER}^workflow_state=published",
            fields=["kb_knowledge_base"],
            limit=1,
        )
    except ServiceNowError as exc:
        raise http_failure("knowledge base", exc) from None
    if not articles:
        raise WorldError("known error knowledge base was not readable")
    base_id = ref(articles[0].get("kb_knowledge_base"))
    if len(base_id) != 32:
        raise WorldError("known error knowledge base was not readable")
    return base_id


def _find_article(writer: Any, problem_id: str, short: str) -> dict[str, Any] | None:
    try:
        rows = writer.get_table(
            "kb_knowledge",
            query=f"source={problem_id}^short_description={short}",
            fields=["sys_id", "number", "workflow_state", "source", "cmdb_ci"],
            limit=2,
        )
    except ServiceNowError as exc:
        raise http_failure("article", exc) from None
    if len(rows) > 1:
        raise WorldError("more than one article uses the problem")
    return rows[0] if rows else None


def _read_article(writer: Any, article_id: str) -> dict[str, Any]:
    try:
        return writer.get_record(
            "kb_knowledge",
            article_id,
            fields=["sys_id", "number", "workflow_state", "source", "cmdb_ci"],
        )
    except ServiceNowError as exc:
        raise http_failure("article", exc) from None


def _one(writer: Any, table: str, query: str) -> str:
    try:
        rows = writer.get_table(table, query=query, fields=["sys_id"], limit=2)
    except ServiceNowError as exc:
        raise http_failure(table, exc) from None
    if len(rows) != 1:
        raise WorldError(f"{table} lookup returned {len(rows)}")
    return str(rows[0].get("sys_id") or "")


def _truthy(value: object) -> bool:
    return str(value or "").lower() in {"1", "true", "yes"}
