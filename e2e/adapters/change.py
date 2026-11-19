"""Change graph adapter. The change repository is not edited.

Approvals in this phase are a helper: the authority user approves only the
row requested for that user. An empty resume dict does not resume this graph.
"""

from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from cm_agents.clock import pin
from cm_agents.data.import_time import parse_utc
from cm_agents.graphs.runner import resume_change, start_change
from cm_agents.servicenow.changes import STATE_CLOSED, move_state, update_fields
from cm_agents.servicenow.client import ServiceNowError
from cm_agents.settings import load_settings as load_graph_settings

from e2e.adapters.incident import ref
from e2e.adapters.problem import note, read_problem, set_rfc
from e2e.contracts import FixCatalogEntry, intake_request_from_catalog, to_intake_dict
from e2e.errors import WorldError
from e2e.instance import http_failure, open_client
from e2e.paths import repo_root
from e2e.settings import Settings

GRAPH_RUN = "e2e-case"
# An empty dict is an interrupt-id map in this LangGraph build, so the graph
# would stay on the current interrupt. The change CLI sends this instead.
AUTH_RESUME = {"continue": "true"}
CHANGE_FIELDS = [
    "sys_id",
    "number",
    "state",
    "type",
    "risk",
    "close_code",
    "closed_at",
    "start_date",
    "end_date",
    "correlation_id",
    "implementation_plan",
    "backout_plan",
    "test_plan",
]


def approval_query(change_id: str, user_id: str) -> str:
    """The requested approval row that belongs to this user."""
    return f"sysapproval={change_id}^state=requested^approver={user_id}"


def safe_detail(exc: Exception) -> str:
    text = str(exc)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\b[0-9a-f]{32}\b", "", text)
    text = re.sub(r"[A-Za-z]:\\[^\s'\"]+", "", text)
    text = re.sub(r"/(?:Users|home)/\S+", "", text)
    text = " ".join(text.split())
    return text[:180]


def forget_thread_memory(change_repo: Path, thread_id: str) -> None:
    """Drop one finished thread's checkpoint and deploy replay.

    The harness deletes the change, then the next run reuses the thread id.
    LangGraph keeps the old review, so a new change is reported closed while
    it is still Scheduled. Other threads in those files stay.
    """
    _forget_checkpoint(change_repo / "var" / "checkpoints.sqlite", thread_id)
    _forget_sim(change_repo / "var" / "sim_state.json", thread_id)


def bind_change_repo() -> Path:
    """Point the installed cm_agents copy at the sibling change repository.

    The e2e environment installs cm_agents as a copy. Its repo_root walks
    parents for the first pyproject.toml and lands in this repository, so the
    graph would read fixtures, policy, checkpoints, and audit from the wrong
    tree. Modules that imported the name keep their own binding, so each
    loaded module is updated. Later imports see the replaced function.
    """
    import cm_agents.settings as cm_settings

    change = repo_root().parent / "ChangeManagementAgent"
    if not (change / "pyproject.toml").is_file():
        raise WorldError("change repository was not found")
    if not (change / "data" / "synthetic" / "fixtures.json").is_file():
        raise WorldError("change fixtures were not found")

    def bound() -> Path:
        return change

    for name, module in list(sys_modules()):
        if module is None:
            continue
        if name != "cm_agents" and not name.startswith("cm_agents."):
            continue
        if callable(getattr(module, "repo_root", None)):
            module.repo_root = bound
    cm_settings.repo_root = bound
    return change


def run_change(
    settings: Settings,
    writer: Any,
    threads: list[str],
    *,
    thread_id: str,
    problem_id: str,
    problem_number: str,
    catalog: FixCatalogEntry,
    linked: int,
    ci_name: str,
    requester: str,
    proposed_start: str,
    proposed_end: str,
    requested_at: str,
    clock: str,
) -> dict[str, Any]:
    """Run one normal change to Closed. High-risk and emergency changes are held."""
    threads.append(thread_id)
    os.environ["CM_AGENTS_RUN"] = GRAPH_RUN
    bind_change_repo()
    graph_settings = load_graph_settings()
    if graph_settings.sn_instance_url != settings.sn_instance_url:
        raise WorldError("change settings do not match this instance")
    request = to_intake_dict(
        intake_request_from_catalog(
            catalog,
            problem_number=problem_number,
            confirmed_mechanism=catalog.mechanism,
            linked_incident_count=linked,
            ci_name=ci_name,
            requester=requester,
            proposed_start=proposed_start,
            proposed_end=proposed_end,
            recurrence_rate=0.0,
            expected_incidents_prevented=linked,
        )
    )
    request["simulated_now"] = requested_at
    with open_client(
        settings, settings.sn_agent_user, settings.sn_agent_password
    ) as agent, open_client(
        settings, settings.sn_authority_user, settings.sn_authority_password
    ) as authority:
        existing = _find_change(agent, thread_id)
        if existing is None:
            forget_thread_memory(bind_change_repo(), thread_id)
            print("case graph memory cleared")
            started = _graph_call(start_change, graph_settings, request, thread_id)
            _repin(clock)
            if started["interrupt"] != "authorization" or started["step"] != "assess":
                raise WorldError(f"change stopped at {started['interrupt']} {started['step']}")
            existing = _find_change(agent, thread_id)
        if existing is None:
            raise WorldError("change was not created")
        print(
            "case window "
            f"{existing.get('start_date') or 'empty'} {existing.get('end_date') or 'empty'}"
        )
        from e2e.case_graph import hold_for_change

        hold = hold_for_change(str(existing.get("type") or ""), str(existing.get("risk") or ""))
        if hold:
            note(writer, problem_id, f"Hold {hold}.")
            raise WorldError(f"change held {hold}")
        _assert_plans(existing, catalog)
        change_id = str(existing["sys_id"])
        set_rfc(writer, problem_id, change_id)
        number = str(existing.get("number") or "")
        note(writer, problem_id, f"Change {number}. Thread {thread_id}.")
        if str(existing.get("state") or "") == "3":
            return existing
        _approve(authority, agent, change_id, "-3", settings.sn_authority_user)
        resumed = _graph_call(resume_change, graph_settings, thread_id, AUTH_RESUME)
        _repin(clock)
        if resumed["interrupt"] != "authorization" or resumed["step"] != "authorize":
            print(f"case live state={_change_state(agent, change_id)}")
            raise WorldError(f"change stopped at {resumed['interrupt']} {resumed['step']}")
        _approve(authority, agent, change_id, "-2", settings.sn_authority_user)
        ready = _graph_call(resume_change, graph_settings, thread_id, AUTH_RESUME)
        _repin(clock)
        if ready["interrupt"] != "go_no_go":
            print(f"case live state={_change_state(agent, change_id)}")
            raise WorldError(f"change stopped at {ready['interrupt']} {ready['step']}")
        current = _find_change(agent, thread_id)
        if current is None:
            raise WorldError("change disappeared before go")
        go_now = _go_now(current)
        closed = _graph_call(
            resume_change,
            graph_settings,
            thread_id,
            {
                "decision": "go",
                "by": "incident authority",
                "reason": "the window is approved",
                "simulated_now": go_now,
            },
        )
        _repin(clock)
        if closed["interrupt"] != "none" or closed["state"] != "3":
            raise WorldError(f"change stopped at {closed['interrupt']} state {closed['state']}")
        final, state, close_code = _closed_change(agent, thread_id)
        print(f"case readback state={state or 'empty'} close_code={close_code or 'empty'}")
        if state != "3" or close_code != "successful":
            raise WorldError("change did not close successful")
        _assert_plans(final, catalog)
        if ref(read_problem(writer, problem_id).get("rfc")) != change_id:
            raise WorldError("problem rfc did not read back")
        print("case plans=match rfc=set")
        return final


def graph_usage() -> dict[str, int]:
    from cm_agents.audit import audit_path, summarize

    summary = summarize(run=GRAPH_RUN)
    latency = 0
    path = audit_path()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("run") != GRAPH_RUN or not row.get("model"):
                continue
            latency += int(row.get("latency_ms") or 0)
    return {
        "calls": int(summary["calls"]),
        "tokens": int(summary["tokens"]),
        "latency_ms": latency,
    }


def sys_modules():
    import sys

    return list(sys.modules.items())


def _repin(clock: str) -> None:
    if clock:
        pin(parse_utc(clock))


def _forget_checkpoint(path: Path, thread_id: str) -> None:
    if not path.is_file():
        return
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))


def _forget_sim(path: Path, thread_id: str) -> None:
    if not path.is_file():
        return
    state = json.loads(path.read_text(encoding="utf-8"))
    threads = dict(state.get("threads") or {})
    if thread_id not in threads:
        return
    threads.pop(thread_id, None)
    state["threads"] = threads
    path.write_text(json.dumps(state), encoding="utf-8")


def _graph_call(fn: Any, *args: Any) -> dict[str, str]:
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            code = fn(*args)
    except Exception as exc:
        print(f"change graph status=none type={type(exc).__name__} {safe_detail(exc)}")
        raise WorldError("change graph failed") from None
    parsed = {"interrupt": "", "step": "", "state": "", "change": ""}
    for line in buffer.getvalue().splitlines():
        for key in parsed:
            prefix = f"{key}: "
            if line.startswith(prefix):
                parsed[key] = line[len(prefix) :].strip()
    print(
        "case interrupt="
        f"{parsed['interrupt']} step={parsed['step']} "
        f"state={parsed['state']} change={parsed['change']}"
    )
    if code != 0:
        raise WorldError(f"change graph stopped at step {parsed['step'] or 'unknown'}")
    return parsed


def _find_change(agent: Any, thread_id: str) -> dict[str, Any] | None:
    try:
        rows = agent.get_table(
            "change_request",
            query=f"correlation_id={thread_id}",
            fields=CHANGE_FIELDS,
            limit=2,
        )
    except ServiceNowError as exc:
        raise http_failure("change read", exc) from None
    if len(rows) > 1:
        raise WorldError("more than one change uses the thread id")
    return rows[0] if rows else None


def _assert_plans(record: dict[str, Any], catalog: FixCatalogEntry) -> None:
    for field in ("implementation_plan", "backout_plan", "test_plan"):
        stored = str(record.get(field) or "")
        expected = str(getattr(catalog, field))
        if stored != expected:
            raise WorldError(f"plan field {field} does not match the catalog")


def _go_now(record: dict[str, Any]) -> str:
    text = stamp_field(record.get("start_date"))
    if not text:
        raise WorldError("change start was empty")
    start = parse_utc(text)
    from datetime import timedelta

    return (start + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")


def stamp_field(value: object) -> str:
    from e2e.adapters.incident import stamp

    return stamp(value)


def _closed_change(agent: Any, thread_id: str) -> tuple[dict[str, Any], str, str]:
    found = _await_close(agent, thread_id, 8)
    if found is not None:
        return found
    current = _find_change(agent, thread_id)
    if current is None:
        raise WorldError("change disappeared after close")
    print(
        "case close reverted state="
        f"{current.get('state') or 'empty'} close_code={current.get('close_code') or 'empty'}"
    )
    _reclose(agent, str(current.get("sys_id") or ""))
    print("case close reasserted")
    found = _await_close(agent, thread_id, 10)
    if found is not None:
        return found
    final = _find_change(agent, thread_id)
    if final is None:
        raise WorldError("change disappeared after close")
    return final, str(final.get("state") or ""), str(final.get("close_code") or "")


def _reclose(agent: Any, change_id: str) -> None:
    """Walk Scheduled, Implement, Review, then Closed.

    Close code is refused while the record is still Scheduled.
    """
    state = _change_state(agent, change_id)
    try:
        if state == "-2":
            state = str(move_state(agent, "normal", change_id, "-1").get("state") or "")
            print(f"case reclose state={state or 'empty'}")
        if state == "-1":
            state = str(move_state(agent, "normal", change_id, "0").get("state") or "")
            print(f"case reclose state={state or 'empty'}")
        if state == "0":
            update_fields(agent, change_id, {"close_code": "successful"})
            state = str(move_state(agent, "normal", change_id, STATE_CLOSED).get("state") or "")
            print(f"case reclose state={state or 'empty'}")
    except ServiceNowError as exc:
        raise http_failure("change close", exc) from None


def _await_close(
    agent: Any, thread_id: str, seconds: float
) -> tuple[dict[str, Any], str, str] | None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        final = _find_change(agent, thread_id)
        if final is None:
            raise WorldError("change disappeared after close")
        state = str(final.get("state") or "")
        close_code = str(final.get("close_code") or "")
        if state == "3" and close_code == "successful":
            time.sleep(3)
            again = _find_change(agent, thread_id)
            if again is None:
                raise WorldError("change disappeared after close")
            if str(again.get("state") or "") == "3" and str(again.get("close_code") or "") == (
                "successful"
            ):
                return again, "3", "successful"
        time.sleep(2)
    return None


def _authority_id(authority: Any, user_name: str) -> str:
    try:
        rows = authority.get_table(
            "sys_user",
            query=f"user_name={user_name}",
            fields=["sys_id"],
            limit=2,
        )
    except ServiceNowError as exc:
        raise http_failure("authority user", exc) from None
    if len(rows) != 1:
        raise WorldError("authority user was not readable")
    user_id = str(rows[0].get("sys_id") or "")
    if len(user_id) != 32:
        raise WorldError("authority user was not readable")
    return user_id


def _approve(
    authority: Any,
    agent: Any,
    change_id: str,
    until_state: str,
    user_name: str,
) -> None:
    user_id = _authority_id(authority, user_name)
    deadline = time.time() + 180
    approver_id = ""
    query = approval_query(change_id, user_id)
    while time.time() < deadline and not approver_id:
        try:
            rows = authority.get_table(
                "sysapproval_approver",
                query=query,
                fields=["sys_id", "state"],
                limit=5,
            )
        except ServiceNowError as exc:
            raise http_failure("approval", exc) from None
        if len(rows) > 1:
            raise WorldError("more than one requested approver for the authority user")
        if rows:
            approver_id = str(rows[0].get("sys_id") or "")
            break
        time.sleep(2)
    if not approver_id:
        raise WorldError("change has no requested approver")
    try:
        authority.update_record("sysapproval_approver", approver_id, {"state": "approved"})
    except ServiceNowError as exc:
        raise http_failure("approval", exc) from None
    print("case approved one")
    while time.time() < deadline:
        state = _change_state(agent, change_id)
        print(f"case approval state={state}")
        if state == until_state:
            time.sleep(3)
            confirmed = _change_state(agent, change_id)
            print(f"case approval confirmed={confirmed}")
            if confirmed == until_state:
                return
        elif _requested_for_user(authority, change_id, user_id):
            try:
                rows = authority.get_table(
                    "sysapproval_approver",
                    query=query,
                    fields=["sys_id"],
                    limit=2,
                )
            except ServiceNowError as exc:
                raise http_failure("approval", exc) from None
            if len(rows) == 1:
                try:
                    authority.update_record(
                        "sysapproval_approver",
                        str(rows[0].get("sys_id") or ""),
                        {"state": "approved"},
                    )
                except ServiceNowError as exc:
                    raise http_failure("approval", exc) from None
                print("case approved one")
        time.sleep(2)
    raise WorldError(f"change did not reach state {until_state}")


def _change_state(agent: Any, change_id: str) -> str:
    try:
        record = agent.get_record("change_request", change_id, fields=["state", "approval"])
    except ServiceNowError as exc:
        raise http_failure("change state", exc) from None
    return str(record.get("state") or "")


def _requested_for_user(authority: Any, change_id: str, user_id: str) -> bool:
    try:
        rows = authority.get_table(
            "sysapproval_approver",
            query=approval_query(change_id, user_id),
            fields=["sys_id"],
            limit=2,
        )
    except ServiceNowError as exc:
        raise http_failure("approval", exc) from None
    return len(rows) == 1
