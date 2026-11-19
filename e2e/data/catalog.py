"""Fix catalog. Plans are copied byte for byte. There is no second row for a failed entry."""

from __future__ import annotations

BACKOUT = (
    "1. Stop the service.\n"
    "2. Restore the previous build.\n"
    "Trigger: the health check fails. Backout duration: 20 minutes."
)
TEST_PLAN = (
    "1. Call the health endpoint.\n"
    "Success criteria: HTTP 200 and error rate under 1 percent."
)
STANDARD_TEMPLATE = "SYN Standard restart application service"
STANDARD_IMPLEMENTATION = "1. Stop the service. 2. Start the service."
STANDARD_BACKOUT = "Start the service again from the previous build."
STANDARD_TEST = "The health endpoint returns HTTP 200."


def _normal(owner: str, step: str) -> str:
    return (
        "Deployment method: AUTOMATED\n"
        f"1. Owner: {owner}. {step}\n"
        "2. Reload the service and record the result."
    )


def entries() -> tuple[dict[str, object], ...]:
    """One row per mechanism and CI class that has a plan. Order is stable."""
    return (
        {
            "mechanism": "log_rotation_stopped",
            "ci_class": "cmdb_ci_appl",
            "ci": "syn-store-checkout",
            "owner": "SYN Store DevOps",
            "deployment_method": "automated",
            "deployment_strategy": "big bang",
            "change_type": "normal",
            "standard_template": None,
            "title": "Fix log rotation on syn-store-checkout",
            "implementation_plan": _normal(
                "SYN Store DevOps",
                "Rotate the application logs on syn-store-checkout and remove the filled files.",
            ),
            "backout_plan": BACKOUT,
            "test_plan": TEST_PLAN,
            "scenario": "E02",
        },
        {
            "mechanism": "log_rotation_stopped",
            "ci_class": "cmdb_ci_appl",
            "ci": "syn-hr-benefits",
            "owner": "SYN Platform Ops",
            "deployment_method": "automated",
            "deployment_strategy": "big bang",
            "change_type": "normal",
            "standard_template": None,
            "title": "Fix log rotation on syn-hr-benefits",
            "implementation_plan": _normal(
                "SYN Platform Ops",
                "Rotate the application logs on syn-hr-benefits and remove the filled files.",
            ),
            "backout_plan": BACKOUT,
            "test_plan": TEST_PLAN,
            "scenario": "E12",
        },
        {
            "mechanism": "stale_feature_flag",
            "ci_class": "cmdb_ci_appl",
            "ci": "syn-hr-recruiting",
            "owner": "SYN Platform Ops",
            "deployment_method": "automated",
            "deployment_strategy": "big bang",
            "change_type": "normal",
            "standard_template": None,
            "title": "Reload the feature flag snapshot on syn-hr-recruiting",
            "implementation_plan": _normal(
                "SYN Platform Ops",
                "Reload the feature flag snapshot on syn-hr-recruiting.",
            ),
            "backout_plan": BACKOUT,
            "test_plan": TEST_PLAN,
            "scenario": "E12",
        },
        {
            "mechanism": "service_account_key_stale",
            "ci_class": "cmdb_ci_appl",
            "ci": "syn-hr-payroll",
            "owner": "SYN Platform Ops",
            "deployment_method": "automated",
            "deployment_strategy": "canary",
            "change_type": "normal",
            "standard_template": None,
            "title": "Rotate the service account key on syn-hr-payroll",
            "implementation_plan": _normal(
                "SYN Platform Ops",
                "Rotate the service account key used by the batch on syn-hr-payroll.",
            ),
            "backout_plan": BACKOUT,
            "test_plan": TEST_PLAN,
            "scenario": "E12",
        },
        {
            "mechanism": "log_rotation_stopped",
            "ci_class": "cmdb_ci_linux_server",
            "ci": "syn-prd-lx-073",
            "owner": "SYN Fulfillment DevOps",
            "deployment_method": "automated",
            "deployment_strategy": "big bang",
            "change_type": "normal",
            "standard_template": None,
            "title": "Fix log rotation on syn-prd-lx-073",
            "implementation_plan": _normal(
                "SYN Fulfillment DevOps",
                "Rotate the application logs on syn-prd-lx-073 and remove the filled files.",
            ),
            "backout_plan": BACKOUT,
            "test_plan": TEST_PLAN,
            "scenario": "E07",
        },
        {
            "mechanism": "connection_pool_exhausted",
            "ci_class": "cmdb_ci_appl",
            "ci": "syn-ful-inventory",
            "owner": "SYN Fulfillment DevOps",
            "deployment_method": "automated",
            "deployment_strategy": "canary",
            "change_type": "normal",
            "standard_template": None,
            "title": "Recycle the connection pool on syn-ful-inventory",
            "implementation_plan": _normal(
                "SYN Fulfillment DevOps",
                "Recycle the connection pool on syn-ful-inventory and release the locks.",
            ),
            "backout_plan": BACKOUT,
            "test_plan": TEST_PLAN,
            "scenario": "E05",
            "alternate_for_mechanism_class": False,
        },
        {
            "mechanism": "worker_not_restarted",
            "ci_class": "cmdb_ci_linux_server",
            "ci": "syn-stg-lx-001",
            "owner": "SYN Store DevOps",
            "deployment_method": "automated",
            "deployment_strategy": "big bang",
            "change_type": "standard",
            "standard_template": STANDARD_TEMPLATE,
            "title": "Restart the application service on syn-stg-lx-001",
            "implementation_plan": STANDARD_IMPLEMENTATION,
            "backout_plan": STANDARD_BACKOUT,
            "test_plan": STANDARD_TEST,
            "scenario": "E04",
        },
        {
            "mechanism": "checkout_saturation",
            "ci_class": "cmdb_ci_appl",
            "ci": "syn-store-web",
            "owner": "SYN Store DevOps",
            "deployment_method": "automated",
            "deployment_strategy": "big bang",
            "change_type": "emergency",
            "standard_template": None,
            "title": "Drain the checkout queue on syn-store-web",
            "implementation_plan": _normal(
                "SYN Store DevOps",
                "Drain the checkout queue on syn-store-web and restart the web tier.",
            ),
            "backout_plan": BACKOUT,
            "test_plan": TEST_PLAN,
            "scenario": "E03",
        },
    )


def for_mechanism_class(mechanism: str, ci_class: str) -> list[dict[str, object]]:
    return [
        row
        for row in entries()
        if row["mechanism"] == mechanism and row["ci_class"] == ci_class
    ]


def for_detected(mechanism: str, ci_class: str, ci: str) -> dict[str, object] | None:
    """The one catalog row for this mechanism, class, and CI name."""
    found = [
        row
        for row in for_mechanism_class(mechanism, ci_class)
        if row["ci"] == ci
    ]
    if len(found) != 1:
        return None
    return found[0]


def known_error_text(mechanism: str) -> tuple[str, str]:
    """Cause and workaround copied into the known-error article.

    An empty pair means this mechanism has no article text yet.
    """
    if mechanism == "log_rotation_stopped":
        return (
            "Log rotation stopped. The log directory filled.",
            "Retry the page. Clear the filled log files at the next maintenance window.",
        )
    return "", ""
