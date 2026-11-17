"""Customer-update check for this repository and the change seed.

Approved settings win, then an endpoint row whose text names syne2e_problem_state,
then a manifest or history sys_id, then the two hand-made admin changes.
A change-seed or deleted-probe name is manifest when its sys_id was not kept.
Three platform rows that a table create or a scheduled job rewrites are platform.
Anything else is an orphan. Payloads are not printed.
"""

from __future__ import annotations

import re
from typing import Any

from cm_agents.data.manifest import load_manifest
from cm_agents.data.update_xml import (
    APPROVED,
    BUILD_SINCE,
    CAUSED_BY,
    ROLE_GRANT,
    UpdateXmlError,
    manifest_ids,
    update_xml_query,
)
from cm_agents.servicenow.client import ServiceNowClient
from cm_agents.settings import repo_root as change_root

from e2e.data.history import known_sys_ids
from e2e.errors import WorldError
from e2e.instance import open_client
from e2e.paths import manifest_path
from e2e.settings import Settings

_HEX = re.compile(r"[0-9a-f]{32}")
_PAGE = 200
_CAP = 5000
_ENDPOINT = "syne2e_problem_state"
# Customer updates for the change seed and for deleted probes stay on the
# instance after the record is gone. The change history does not hold those
# older sys_ids. The marker is the name, not a new approval.
_CHANGE_MARKERS = (
    "u_syn_chg_import",
    "u_syn_inc_import",
    "u_syn_task",
    "u_syn_e2e",
    "syn change import",
    "syn incident import",
    "syn task ci import",
    "syn standard",
    "syn-probe",
    "syn probe",
    "syn-e2e",
)
# Platform rows a scheduled job or a table create rewrites. They are not the
# two approved settings.
_PLATFORM = {
    "glide.db.instant_alter.enabled": "table create sets instant alter",
    "taxonomy.category.new_content_job_last_run": "scheduled taxonomy cursor",
    "service-desk password reset for local servicenow": "scheduled password-reset process",
}


def classify_text(
    text: str,
    known: set[str],
    endpoint_ids: set[str] | None = None,
) -> tuple[str, str] | None:
    """Approved, then endpoint, then manifest, then hand-made."""
    lowered = text.lower()
    ids = set(_HEX.findall(lowered))
    approved = [APPROVED[item] for item in sorted(ids) if item in APPROVED]
    if approved:
        return "approved", "; ".join(approved)
    if _ENDPOINT in lowered or (endpoint_ids and ids & endpoint_ids):
        return "endpoint", _ENDPOINT
    matched = sorted(ids & known)
    if matched:
        return "manifest", matched[0]
    label = _hand_made_label(lowered)
    if label:
        return "hand_made", label
    if any(marker in lowered for marker in _CHANGE_MARKERS):
        return "manifest", "change seed"
    for name, label in _PLATFORM.items():
        if name in lowered:
            return "platform", label
    return None


def known_ids(
    change_manifest: dict[str, Any] | None,
    e2e_manifest: dict[str, Any] | None,
) -> set[str]:
    found: set[str] = set()
    if change_manifest is not None:
        found |= manifest_ids(change_manifest)
    if e2e_manifest is not None:
        found |= manifest_ids(e2e_manifest)
        for bucket in ("documentation", "endpoint"):
            _collect(found, e2e_manifest.get(bucket))
    found |= known_sys_ids()
    return found


def report_update_xml(settings: Settings) -> dict[str, Any]:
    change_manifest = load_manifest(change_root() / "data" / "synthetic" / "manifest.json")
    if change_manifest is None:
        raise WorldError("change manifest is missing")
    e2e_manifest = load_manifest(manifest_path())
    if e2e_manifest is None:
        raise WorldError("e2e manifest is missing")
    known = known_ids(change_manifest, e2e_manifest)
    endpoints = _bucket_ids(e2e_manifest, "endpoint")
    users = [
        settings.sn_admin_user,
        settings.sn_agent_user,
        settings.sn_incident_user,
        settings.sn_problem_user,
        settings.sn_authority_user,
    ]
    try:
        query = update_xml_query(users, BUILD_SINCE)
    except UpdateXmlError as exc:
        raise WorldError(str(exc)) from None
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        rows = _pages(admin, query)
        classified = _classify_pages(admin, rows, known, endpoints)
    counts = {
        "hand_made": 0,
        "approved": 0,
        "endpoint": 0,
        "manifest": 0,
        "platform": 0,
        "orphan": 0,
    }
    approved_details: list[str] = []
    orphans: list[dict[str, str]] = []
    for kind, detail, row in classified:
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "approved":
            approved_details.append(detail)
        if kind == "orphan":
            orphans.append(
                {
                    "name": str(row.get("name") or ""),
                    "target": str(row.get("target_name") or ""),
                    "sys_id": str(row.get("sys_id") or ""),
                }
            )
    print(f"update_xml rows={len(classified)}", flush=True)
    for kind in ("hand_made", "approved", "endpoint", "manifest", "platform", "orphan"):
        print(f"update_xml {kind}={counts[kind]}", flush=True)
    labels = {
        settings.sn_admin_user: "admin",
        settings.sn_agent_user: "change",
        settings.sn_incident_user: "incident",
        settings.sn_problem_user: "problem",
        settings.sn_authority_user: "authority",
    }
    for kind, detail, row in classified:
        if kind == "manifest":
            continue
        created_by = str(row.get("sys_created_by") or "")
        print(
            f"update_xml {kind} by={labels.get(created_by, 'other')}"
            f" name={row.get('name') or ''} target={row.get('target_name') or ''}"
            f" sys_id={row.get('sys_id') or ''} detail={detail}",
            flush=True,
        )
    return {"counts": counts, "approved": approved_details, "orphans": orphans}


def _hand_made_label(lowered: str) -> str | None:
    if "snc_basic_auth_api_access" in lowered:
        return ROLE_GRANT
    if (
        "u_syn_" in lowered
        or "syn incident import" in lowered
        or "syn change import" in lowered
        or "syn-e2e incident import" in lowered
    ):
        return None
    if "u_caused_by" in lowered and "incident" in lowered:
        return CAUSED_BY
    return None


def _collect(found: set[str], rows: object) -> None:
    if not isinstance(rows, list):
        return
    for row in rows:
        if isinstance(row, dict) and row.get("sys_id"):
            found.add(str(row["sys_id"]).lower())


def _pages(admin: ServiceNowClient, query: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    fields = ["sys_id", "name", "target_name", "sys_created_by", "action"]
    while len(rows) < _CAP:
        page = admin.get_table(
            "sys_update_xml",
            query=query,
            fields=fields,
            limit=_PAGE,
            offset=offset,
        )
        rows.extend(page)
        if len(page) < _PAGE:
            return rows
        offset += _PAGE
    raise WorldError(f"more than {_CAP} sys_update_xml rows")


def _classify_pages(
    admin: ServiceNowClient,
    rows: list[dict[str, Any]],
    known: set[str],
    endpoint_ids: set[str],
) -> list[tuple[str, str, dict[str, Any]]]:
    classified = []
    for row in rows:
        kind, detail = _classify_row(row, known, endpoint_ids=endpoint_ids)
        visible = f"{row.get('name') or ''}\n{row.get('target_name') or ''}".lower()
        needs_payload = kind == "orphan" or (_endpoint_hint(visible) and kind != "endpoint")
        if needs_payload and kind != "approved":
            payload = _payload(admin, str(row.get("sys_id") or ""))
            kind, detail = _classify_row(row, known, payload, endpoint_ids=endpoint_ids)
        classified.append((kind, detail, row))
    return classified


def _endpoint_hint(visible: str) -> bool:
    return any(token in visible for token in ("syn-e2e", "syne2e", "problem state", "sys_ws"))


def _bucket_ids(manifest: dict[str, Any], bucket: str) -> set[str]:
    found: set[str] = set()
    _collect(found, manifest.get(bucket))
    return found


def _classify_row(
    row: dict[str, Any],
    known: set[str],
    payload: str = "",
    *,
    endpoint_ids: set[str] | None = None,
) -> tuple[str, str]:
    visible = f"{row.get('name') or ''}\n{row.get('target_name') or ''}"
    text = f"{visible}\n{payload}" if payload else visible
    found = classify_text(text, known, endpoint_ids)
    if found is None:
        return "orphan", ""
    return found


def _payload(admin: ServiceNowClient, sys_id: str) -> str:
    if not sys_id:
        return ""
    stored = admin.get_record("sys_update_xml", sys_id, fields=["payload"])
    return str(stored.get("payload") or "")
