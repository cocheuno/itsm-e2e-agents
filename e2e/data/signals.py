"""Four signal types. Detection thresholds stay in the fork. This module does not read them."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from e2e.data.world import (
    CHANGE_WINDOW_DAYS,
    CI_SPECIFIC,
    KIND_MAP,
    LIFT_AFTER_COUNT,
    LIFT_RATIO,
    LOOKBACK_DAYS,
    PHRASES,
    RATE_MIN_COUNT,
    WEEKDAY_WEEKS,
)

FMT = "%Y-%m-%d %H:%M:%S"


def parse_opened(text: str) -> datetime:
    return datetime.strptime(text, FMT)


def vote_notes(notes: list[str]) -> str:
    """Signal (a). One mechanism, and only when its phrase is in more than half the notes."""
    if not notes:
        return ""
    leaders = []
    for mechanism, phrases in PHRASES.items():
        hits = sum(any(phrase in note.lower() for phrase in phrases) for note in notes)
        if hits / len(notes) > 0.5:
            leaders.append(mechanism)
    if len(leaders) == 1:
        return leaders[0]
    return ""


def vote_schedule(members: list[dict[str, object]], jobs: tuple[dict[str, str], ...] | list) -> str:
    """Signal (b). One weekday across at least three ISO weeks, mapped through the job schedule."""
    if not members:
        return ""
    latest = max(parse_opened(str(row["opened_at"])) for row in members)
    start = latest - timedelta(days=LOOKBACK_DAYS)
    weeks: dict[str, set[str]] = defaultdict(set)
    for row in members:
        moment = parse_opened(str(row["opened_at"]))
        if not start <= moment <= latest:
            continue
        weeks[moment.strftime("%A")].add(moment.strftime("%G-W%V"))
    leaders = [day for day, found in weeks.items() if len(found) >= WEEKDAY_WEEKS]
    if len(leaders) != 1:
        return ""
    ci = str(members[0]["cmdb_ci"])
    mechanisms = {
        job["mechanism"]
        for job in jobs
        if job["ci"] == ci and job["weekday"] == leaders[0]
    }
    if len(mechanisms) == 1:
        return next(iter(mechanisms))
    return ""


def vote_changes(
    members: list[dict[str, object]],
    population: list[dict[str, object]],
    changes: list[dict[str, object]],
    kind_map: dict[str, str] | None = None,
) -> str:
    """Signal (c). Every closed change on the CI in the 14 days before the first incident.

    Kinds come from the world table. Unmapped summaries do not vote. Two mapped
    mechanisms cast no vote. One mapped mechanism votes when the lift holds.
    """
    if not members:
        return ""
    table = KIND_MAP if kind_map is None else kind_map
    ci = str(members[0]["cmdb_ci"])
    first = min(parse_opened(str(row["opened_at"])) for row in members)
    latest = max(parse_opened(str(row["opened_at"])) for row in members)
    mapped: list[tuple[dict[str, object], str]] = []
    for change in changes:
        if str(change.get("cmdb_ci") or "") != ci:
            continue
        if str(change.get("state") or "") != "3":
            continue
        closed_text = str(change.get("closed_at") or "")
        if not closed_text:
            continue
        closed = parse_opened(closed_text)
        if not (first - timedelta(days=CHANGE_WINDOW_DAYS) <= closed < first):
            continue
        mechanism = table.get(str(change.get("short_description") or ""))
        if mechanism:
            mapped.append((change, mechanism))
    names = {mechanism for _change, mechanism in mapped}
    if len(names) != 1:
        return ""
    mechanism = next(iter(names))
    for change, _mechanism in mapped:
        if _lift(change, ci, population, latest):
            return mechanism
    return ""


def _lift(
    change: dict[str, object],
    ci: str,
    population: list[dict[str, object]],
    latest: datetime,
) -> bool:
    closed = parse_opened(str(change["closed_at"]))
    window_start = closed - timedelta(days=LOOKBACK_DAYS)
    before = _between(population, ci, window_start, closed, end_inclusive=False)
    after = _between(population, ci, closed, latest, end_inclusive=True, start_exclusive=True)
    before_rate = len(before) / LOOKBACK_DAYS
    after_days = max((latest - closed).days, 1)
    after_rate = len(after) / after_days
    return len(after) >= LIFT_AFTER_COUNT and after_rate >= LIFT_RATIO * before_rate


def _between(
    population: list[dict[str, object]],
    ci: str,
    start: datetime,
    end: datetime,
    *,
    end_inclusive: bool,
    start_exclusive: bool = False,
) -> list[dict[str, object]]:
    found = []
    for row in population:
        if row.get("parent"):
            continue
        if str(row.get("cmdb_ci") or "") != ci:
            continue
        moment = parse_opened(str(row["opened_at"]))
        if start_exclusive:
            after_start = moment > start
        else:
            after_start = moment >= start
        before_end = moment <= end if end_inclusive else moment < end
        if after_start and before_end:
            found.append(row)
    return found


def rate_supports(
    members: list[dict[str, object]],
    population: list[dict[str, object]],
    ci_index: dict[str, dict[str, str]],
) -> bool:
    """Signal (d). Category rate on this CI against the same class and service.

    No incident text is read. A tie, or a count under twice the busiest sibling,
    does not fire. A CI with no sibling incidents has an infinite lift.
    """
    if not members:
        return False
    ci = str(members[0]["cmdb_ci"])
    category = str(members[0]["category"])
    info = ci_index.get(ci)
    if info is None:
        return False
    latest = max(parse_opened(str(row["opened_at"])) for row in members)
    start = latest - timedelta(days=LOOKBACK_DAYS)
    counts: dict[str, int] = defaultdict(int)
    for row in population:
        if row.get("parent"):
            continue
        if str(row.get("category") or "") != category:
            continue
        moment = parse_opened(str(row["opened_at"]))
        if not start <= moment <= latest:
            continue
        other = str(row.get("cmdb_ci") or "")
        meta = ci_index.get(other)
        if meta is None:
            continue
        if meta["ci_class"] == info["ci_class"] and meta["service"] == info["service"]:
            counts[other] += 1
    mine = counts.get(ci, 0)
    if mine < RATE_MIN_COUNT:
        return False
    sibling_max = max((count for name, count in counts.items() if name != ci), default=0)
    if sibling_max == 0:
        return True
    return mine >= LIFT_RATIO * sibling_max


def signals_for(
    members: list[dict[str, object]],
    population: list[dict[str, object]],
    changes: list[dict[str, object]],
    jobs: tuple[dict[str, str], ...] | list,
    ci_index: dict[str, dict[str, str]],
) -> dict[str, object]:
    """Return a, b, c and whether d fired. (d) is a bool, not a mechanism name."""
    named_a = vote_notes([str(row.get("notes") or "") for row in members])
    named_b = vote_schedule(members, jobs)
    named_c = vote_changes(members, population, changes)
    fired_d = rate_supports(members, population, ci_index)
    decision, mechanism, fired = confirm(named_a, named_b, named_c, fired_d)
    return {
        "a": named_a,
        "b": named_b,
        "c": named_c,
        "d": fired_d,
        "decision": decision,
        "mechanism": mechanism,
        "fired": fired,
    }


def confirm(named_a: str, named_b: str, named_c: str, fired_d: bool) -> tuple[str, str, list[str]]:
    """Confirm when two types support one mechanism and the set is not only (a).

    (d) counts as support only for a CI-specific mechanism, and only when every
    type that names a mechanism names that same one.
    """
    named = {key: value for key, value in (("a", named_a), ("b", named_b), ("c", named_c)) if value}
    names = set(named.values())
    fired = list(named)
    if len(names) > 1:
        if fired_d:
            fired.append("d")
        return "unconfirmed", "", fired
    mechanism = next(iter(names)) if names else ""
    if fired_d and (not mechanism or mechanism in CI_SPECIFIC):
        fired.append("d")
    if not mechanism:
        return "unconfirmed", "", fired
    support = set(fired)
    if len(support) >= 2 and support != {"a"}:
        return "confirmed", mechanism, fired
    return "unconfirmed", "", fired
