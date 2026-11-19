"""Live counts for the e2e layer. Change-seed markers are not included."""

from __future__ import annotations

from typing import Any

from cm_agents.servicenow.client import ServiceNowClient

from e2e.data.world import MARKER
from e2e.state_api import endpoint_counts

INCIDENTS = f"correlation_idSTARTSWITH{MARKER}INC"
PROBLEMS = f"correlation_idSTARTSWITH{MARKER}PRB"
# Scenario changes use a SYN-E2E- thread id. Persistent rows do not.
CHANGES = "correlation_idSTARTSWITHSYN-E2E-^ORshort_descriptionSTARTSWITHSYN-E2E-"
ARTICLES = f"short_descriptionSTARTSWITH{MARKER}"
PROBES = (
    f"correlation_idSTARTSWITH{MARKER}PROBE^ORshort_descriptionSTARTSWITH{MARKER}PROBE"
)


def snapshot(admin: ServiceNowClient) -> dict[str, int | None]:
    endpoint = endpoint_counts(admin)
    return {
        "incidents": admin.count("incident", INCIDENTS),
        "problems": admin.count("problem", PROBLEMS),
        "articles": _article_count(admin),
        "changes": admin.count("change_request", CHANGES),
        "endpoint_definitions": endpoint["sys_ws_definition"],
        "endpoint_operations": endpoint["sys_ws_operation"],
    }


def probe_residue(admin: ServiceNowClient) -> dict[str, int]:
    return {
        "incidents": admin.count("incident", PROBES),
        "problems": admin.count("problem", PROBES),
        "changes": admin.count("change_request", PROBES),
        "articles": admin.count("kb_knowledge", f"short_descriptionSTARTSWITH{MARKER}PROBE"),
    }


def format_counts(counts: dict[str, Any]) -> str:
    return (
        f"incidents={counts['incidents']} problems={counts['problems']} "
        f"articles={counts['articles']} changes={counts['changes']} "
        f"endpoint_definitions={counts['endpoint_definitions']} "
        f"endpoint_operations={counts['endpoint_operations']}"
    )


def _article_count(admin: ServiceNowClient) -> int:
    knowledge = _ids(admin, "kb_knowledge", ARTICLES)
    templates = _ids(admin, "kb_template_known_error_article", ARTICLES)
    return len(knowledge | templates)


def _ids(admin: ServiceNowClient, table: str, query: str) -> set[str]:
    rows = admin.get_records(
        table,
        query=query,
        fields=["sys_id"],
        page_size=100,
        max_records=200,
    )
    return {str(row.get("sys_id") or "") for row in rows if row.get("sys_id")}
