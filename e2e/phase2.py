"""Phase 2 gate. Two ticks on the simulated clock, then the end state."""

from __future__ import annotations

from datetime import datetime

from cm_agents.clock import pin
from cm_agents.data.import_time import UTC
from cm_agents.servicenow.client import ServiceNowError

from e2e.counts import format_counts, snapshot
from e2e.doctor import run_doctor
from e2e.errors import WorldError
from e2e.instance import http_failure, open_client
from e2e.settings import Settings
from e2e.tick import run_tick

# E02's last arrival is 2026-10-24 15:00. E01's arrival is 15:30 the same day.
PHASE2_CLOCK = datetime(2026, 10, 24, 16, 0, 0, tzinfo=UTC)


def run_phase2(settings: Settings) -> int:
    pin(PHASE2_CLOCK)
    try:
        with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
            before = snapshot(admin)
        first = run_tick(settings)
        second = run_tick(settings)
        with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
            after = snapshot(admin)
            _article_field_empty(admin)
        _expect(before, after, first, second)
    finally:
        pin(None)
    report = run_doctor(settings)
    print(report.text())
    if not report.ok:
        raise WorldError("doctor failed after phase 2")
    print("phase 2: pass")
    return 0


def _expect(before: dict, after: dict, first: dict, second: dict) -> None:
    if first["outside"] != 0 or second["outside"] != 0:
        raise WorldError("incidents updated outside this run")
    if first["harmful"] != 0 or second["harmful"] != 0:
        raise WorldError("harmful_action_count is not 0")
    if second["created"] or second["triaged"] or second["known_error"] or second["restored"]:
        raise WorldError("the second tick wrote an incident")
    first_stamp = [row["sys_updated_on"] for row in first["rows"]]
    second_stamp = [row["sys_updated_on"] for row in second["rows"]]
    if first_stamp != second_stamp:
        raise WorldError("the second tick changed an arrival")
    if after["problems"] != before["problems"] or after["problems"] != 1:
        raise WorldError("phase 2 changed the problem count")
    if after["changes"] != before["changes"] or after["changes"] != 0:
        raise WorldError("phase 2 changed the change count")
    if after["articles"] != before["articles"] or after["articles"] != 1:
        raise WorldError("phase 2 changed the article count")
    grown = int(after["incidents"] or 0) - int(before["incidents"] or 0)
    if grown != first["created"]:
        raise WorldError("arrival creates and the incident count disagree")
    rows = second["rows"]
    e01 = [row for row in rows if row["scenario"] == "E01"]
    e02 = [row for row in rows if row["scenario"] == "E02"]
    if len(e01) != 1 or len(e02) != 5:
        raise WorldError("phase 2 did not handle one E01 arrival and five E02 arrivals")
    _expect_e01(e01[0])
    for row in e02:
        _expect_e02(row)
    print(f"phase 2 before: {format_counts(before)}")
    print(f"phase 2 after: {format_counts(after)}")


def _expect_e01(row: dict) -> None:
    if row["state"] != "6" or row["close_code"] != "Workaround provided":
        raise WorldError("E01 arrival was not resolved with Workaround provided")
    if not row["parent_ok"]:
        raise WorldError("E01 arrival is not linked to the seeded problem")
    if not row["priority_ok"]:
        raise WorldError(f"E01 arrival priority read back as {row['priority']}")
    if not row["category_ok"] or not row["group_ok"]:
        raise WorldError(f"E01 arrival triage did not stick category={row['category']}")
    if not row["comment_ok"] or not row["close_notes_ok"] or not row["work_note_ok"]:
        raise WorldError("E01 arrival is missing the workaround note")
    print(f"E01 {row['number']} resolved category={row['category']} priority={row['priority']}")


def _expect_e02(row: dict) -> None:
    if row["state"] != "6" or row["close_code"] != "Solution provided":
        raise WorldError("an E02 arrival was not restored")
    if row["parent_set"]:
        raise WorldError("an E02 arrival was linked to a problem")
    if not row["priority_ok"]:
        raise WorldError(f"an E02 arrival priority read back as {row['priority']}")
    if not row["category_ok"] or not row["group_ok"]:
        raise WorldError(f"an E02 arrival triage did not stick category={row['category']}")
    if not row["work_note_ok"]:
        raise WorldError("an E02 arrival is missing the authority work note")
    print(f"E02 {row['number']} restored category={row['category']} priority={row['priority']}")


def _article_field_empty(admin) -> None:
    try:
        rows = admin.get_table(
            "problem",
            query="correlation_idSTARTSWITHSYN-E2E-PRB",
            fields=["primary_known_error_article"],
            limit=5,
        )
    except ServiceNowError as exc:
        raise http_failure("known-error field", exc) from None
    for row in rows:
        if str(row.get("primary_known_error_article") or ""):
            raise WorldError("E01 known error article field was set")
