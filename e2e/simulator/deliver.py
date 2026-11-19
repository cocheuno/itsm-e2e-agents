"""Deliver arrivals through the seed import set.

This is the simulated world, not an agent. The import map has business rules
off, so the simulated opened_at is what ServiceNow stores. resolved_at is the
platform clock. The autoclose job uses that clock and would close a resolved_at
from the fixture window before the case can link the incident.
"""

from __future__ import annotations

from datetime import UTC, datetime

from cm_agents.servicenow.client import ServiceNowError

from e2e.adapters.incident import ref
from e2e.errors import WorldError
from e2e.instance import http_failure, open_client
from e2e.seed import STAGE, _correlation_entry, _set_coalesce, import_opened_incident
from e2e.settings import Settings
from e2e.simulator.registry import delivered, note, row_for


def deliver_arrivals(settings: Settings, rows: list[dict]) -> None:
    """Import each row and require the stored opened_at to equal the row."""
    resolved = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        for row in rows:
            correlation = str(row["correlation_id"])
            import_opened_incident(admin, settings, row, resolved_at=resolved)
            stored = _opened(admin, correlation)
            expected = str(row["opened_at"])
            if stored != expected:
                raise WorldError(
                    f"import stored opened_at {stored or 'empty'} expected {expected}"
                )
            note(correlation, row)
            print(f"delivered {correlation} opened_at={stored}")


def preserve_opened_at(settings: Settings, problem_id: str) -> None:
    """Re-import a delivered row when a later write replaced its opened_at.

    Coalesce is on only for those posts. The problem link is sent with the
    same import so the repair does not clear the parent.
    """
    correlations = [item for item in delivered() if row_for(item) is not None]
    if not correlations:
        return
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        drifted = []
        for correlation in correlations:
            fixture = row_for(correlation)
            if fixture is None:
                continue
            stored = _opened(admin, correlation)
            expected = str(fixture["opened_at"])[:19]
            if stored != expected:
                drifted.append(fixture)
        if not drifted:
            return
        resolved = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        entry_id = _correlation_entry(admin)
        try:
            _set_coalesce(admin, entry_id, True)
            for fixture in drifted:
                import_opened_incident(
                    admin,
                    settings,
                    fixture,
                    resolved_at=resolved,
                    parent_id=problem_id,
                )
        finally:
            _set_coalesce(admin, entry_id, False)
        for fixture in drifted:
            correlation = str(fixture["correlation_id"])
            stored, parent = _opened_parent(admin, correlation)
            expected = str(fixture["opened_at"])[:19]
            if stored != expected:
                raise WorldError(
                    f"import stored opened_at {stored or 'empty'} expected {expected}"
                )
            if problem_id and parent != problem_id:
                raise WorldError("arrival parent did not stick after import")
        print(f"repaired opened_at rows={len(drifted)}")


def delete_staging(settings: Settings, correlations: list[str]) -> None:
    """Remove staging rows for correlations this scenario imported."""
    if not correlations:
        return
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        for correlation in correlations:
            try:
                rows = admin.get_table(
                    STAGE,
                    query=f"u_correlation_id={correlation}",
                    fields=["sys_id"],
                    limit=5,
                )
            except ServiceNowError as exc:
                raise http_failure("staging lookup", exc) from None
            for row in rows:
                sys_id = str(row.get("sys_id") or "")
                if len(sys_id) != 32:
                    continue
                admin.delete_record(STAGE, sys_id)


def _opened(admin, correlation: str) -> str:
    opened, _parent = _opened_parent(admin, correlation)
    return opened


def _opened_parent(admin, correlation: str) -> tuple[str, str]:
    rows = admin.get_table(
        "incident",
        query=f"correlation_id={correlation}",
        fields=["opened_at", "parent"],
        limit=2,
    )
    if len(rows) != 1:
        raise WorldError(f"imported incidents={len(rows)} expected 1")
    opened = str(rows[0].get("opened_at") or "")[:19]
    return opened, ref(rows[0].get("parent"))
