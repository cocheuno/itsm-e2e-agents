"""The three service users. Passwords come from settings and are not printed."""

from __future__ import annotations

from cm_agents.servicenow.client import ServiceNowClient, ServiceNowError

from e2e.data.history import Ledger
from e2e.errors import WorldError
from e2e.settings import Settings

AUTHORITY_GROUPS = (
    "CAB Approval",
    "Change Management",
    "SYN Store DevOps",
    "SYN Payments DevOps",
    "SYN Fulfillment DevOps",
    "SYN Platform Ops",
)


class AccountError(WorldError):
    """A service user could not be created or could not log in."""


def ensure_service_users(
    admin: ServiceNowClient,
    settings: Settings,
    ledger: Ledger,
) -> dict[str, str]:
    """Create the three users when they are absent. Return label to sys_id."""
    specs = (
        (
            "incident",
            settings.sn_incident_user,
            settings.sn_incident_password,
            ("sn_incident_write", "problem_task_analyst"),
        ),
        (
            "problem",
            settings.sn_problem_user,
            settings.sn_problem_password,
            ("problem_coordinator",),
        ),
        ("authority", settings.sn_authority_user, settings.sn_authority_password, ()),
    )
    ids: dict[str, str] = {}
    for label, user_name, password, roles in specs:
        sys_id = _ensure_user(admin, user_name, password, label)
        ledger.create("sys_user", sys_id, f"{label} user")
        for role in roles:
            role_id = _ensure_role(admin, sys_id, role)
            ledger.create("sys_user_has_role", role_id, role)
        if label == "authority":
            for group in AUTHORITY_GROUPS:
                member_id = _ensure_member(admin, sys_id, group)
                ledger.create("sys_user_grmember", member_id, group)
        if _login(settings, user_name, password) != "ok":
            _reset_password(admin, sys_id, password)
        if _login(settings, user_name, password) != "ok":
            basic_id = _ensure_role(admin, sys_id, "snc_basic_auth_api_access")
            ledger.create("sys_user_has_role", basic_id, "snc_basic_auth_api_access")
            print("role snc_basic_auth_api_access granted")
        _record_links(admin, ledger, sys_id)
        if _login(settings, user_name, password) != "ok":
            raise AccountError(f"{label} user login failed")
        ids[label] = sys_id
        print(f"{label} user: login ok")
    return ids


def delete_service_users(
    admin: ServiceNowClient,
    settings: Settings,
    ledger: Ledger,
) -> None:
    """Remove only the three orchestrator users. Seeded syn.* users stay."""
    labels = {
        settings.sn_incident_user: "incident user",
        settings.sn_problem_user: "problem user",
        settings.sn_authority_user: "authority user",
    }
    for user_name, label in labels.items():
        rows = admin.get_table(
            "sys_user",
            query=f"user_name={user_name}",
            fields=["sys_id"],
            limit=2,
        )
        for row in rows:
            sys_id = str(row.get("sys_id") or "")
            _delete_where(admin, ledger, "sys_user_grmember", f"user={sys_id}", "membership")
            _delete_where(admin, ledger, "sys_user_has_role", f"user={sys_id}", "role grant")
            ledger.delete("sys_user", sys_id, label)
            _delete(admin, "sys_user", sys_id)
        left = admin.get_table(
            "sys_user",
            query=f"user_name={user_name}",
            fields=["sys_id"],
            limit=1,
        )
        if left:
            raise AccountError("a service user is still present")


def _ensure_user(admin: ServiceNowClient, user_name: str, password: str, label: str) -> str:
    rows = admin.get_table(
        "sys_user",
        query=f"user_name={user_name}",
        fields=["sys_id"],
        limit=1,
    )
    if rows:
        sys_id = str(rows[0]["sys_id"])
        admin.update_record(
            "sys_user",
            sys_id,
            {
                "active": "true",
                "locked_out": "false",
                "password_needs_reset": "false",
                "web_service_access_only": "true",
                "user_password": password,
            },
            input_display_value=True,
        )
        return sys_id
    created = admin.create_record(
        "sys_user",
        {
            "user_name": user_name,
            "first_name": "SYN-E2E",
            "last_name": label,
            "email": f"syn-e2e-{label}@example.com",
            "user_password": password,
            "password_needs_reset": "false",
            "web_service_access_only": "true",
            "time_zone": "UTC",
            "active": "true",
        },
        input_display_value=True,
    )
    return str(created.get("sys_id") or "")


def _ensure_role(admin: ServiceNowClient, user_id: str, role_name: str) -> str:
    roles = admin.get_table(
        "sys_user_role",
        query=f"name={role_name}",
        fields=["sys_id"],
        limit=1,
    )
    if not roles:
        raise AccountError(f"role {role_name} was not found")
    role_id = str(roles[0]["sys_id"])
    existing = admin.get_table(
        "sys_user_has_role",
        query=f"user={user_id}^role={role_id}",
        fields=["sys_id"],
        limit=1,
    )
    if existing:
        return str(existing[0]["sys_id"])
    try:
        created = admin.create_record(
            "sys_user_has_role",
            {"user": user_id, "role": role_id, "inherited": "false"},
        )
    except ServiceNowError:
        created = admin.create_record("sys_user_has_role", {"user": user_id, "role": role_id})
    return str(created.get("sys_id") or "")


def _ensure_member(admin: ServiceNowClient, user_id: str, group_name: str) -> str:
    group_id = _group(admin, group_name)
    if not group_id:
        raise AccountError(f"group {group_name} was not found")
    existing = admin.get_table(
        "sys_user_grmember",
        query=f"user={user_id}^group={group_id}",
        fields=["sys_id"],
        limit=1,
    )
    if existing:
        return str(existing[0]["sys_id"])
    created = admin.create_record("sys_user_grmember", {"user": user_id, "group": group_id})
    return str(created.get("sys_id") or "")


def _group(admin: ServiceNowClient, name: str) -> str:
    rows = admin.get_table(
        "sys_user_group",
        query=f"name={name}",
        fields=["sys_id"],
        limit=1,
    )
    return str(rows[0]["sys_id"]) if rows else ""


def _reset_password(admin: ServiceNowClient, user_id: str, password: str) -> None:
    admin.update_record(
        "sys_user",
        user_id,
        {
            "user_password": password,
            "password_needs_reset": "false",
            "locked_out": "false",
            "active": "true",
        },
        input_display_value=True,
    )


def _login(settings: Settings, user_name: str, password: str) -> str:
    try:
        with ServiceNowClient(
            settings.sn_instance_url,
            user_name,
            password,
            secrets=settings.secret_values(),
        ) as client:
            client.request("GET", "/api/now/ui/user/current")
    except ServiceNowError as exc:
        if exc.status_code in (401, 403):
            return f"failed HTTP {exc.status_code}"
        raise
    return "ok"


def _record_links(admin: ServiceNowClient, ledger: Ledger, user_id: str) -> None:
    """Record every role and membership row, including ones the platform added."""
    for table, name in (
        ("sys_user_has_role", "role grant"),
        ("sys_user_grmember", "membership"),
    ):
        rows = admin.get_table(table, query=f"user={user_id}", fields=["sys_id"], limit=50)
        for row in rows:
            ledger.create(table, str(row.get("sys_id") or ""), name)


def _delete_where(
    admin: ServiceNowClient,
    ledger: Ledger,
    table: str,
    query: str,
    name: str,
) -> None:
    rows = admin.get_records(table, query=query, fields=["sys_id"], page_size=50, max_records=200)
    for row in rows:
        sys_id = str(row.get("sys_id") or "")
        ledger.delete(table, sys_id, name)
        _delete(admin, table, sys_id)


def _delete(admin: ServiceNowClient, table: str, sys_id: str) -> None:
    if len(sys_id) != 32:
        return
    try:
        admin.delete_record(table, sys_id)
    except ServiceNowError:
        return
