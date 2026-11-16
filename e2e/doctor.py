"""Read-only check: instance, email, the logins that exist, and the change seed."""

from __future__ import annotations

from dataclasses import dataclass

from cm_agents.discover import evaluate_outbound_email
from cm_agents.servicenow.client import ServiceNowClient, ServiceNowError

from e2e.pins import PinsError, pin_mismatches
from e2e.settings import Settings

BUILD_QUERY = "nameINglide.buildname,glide.buildtag,glide.war"
BUILD_FALLBACK_QUERY = "nameSTARTSWITHglide.build^ORname=glide.war"
_LOGIN_FIELDS = (
    ("change agent", "sn_agent_user", "sn_agent_password"),
    ("incident user", "sn_incident_user", "sn_incident_password"),
    ("problem user", "sn_problem_user", "sn_problem_password"),
    ("authority user", "sn_authority_user", "sn_authority_password"),
)


@dataclass
class DoctorReport:
    lines: list[str]
    ok: bool

    def text(self) -> str:
        return "\n".join(self.lines)


def doctor_ok(
    *,
    admin_ok: bool,
    email_ok: bool,
    agent_login: str,
    seed_changes: int,
    pins_ok: bool,
    present_users_ok: bool = True,
) -> bool:
    """The three Phase 1 users may be absent. A user that exists must log in."""
    return (
        admin_ok
        and email_ok
        and agent_login == "ok"
        and seed_changes > 0
        and pins_ok
        and present_users_ok
    )


def run_doctor(settings: Settings) -> DoctorReport:
    lines: list[str] = []
    pins_ok = _pins(lines)
    admin_ok = False
    email_ok = False
    seed_changes = 0
    agent_login = "not checked"
    present_users_ok = True
    with ServiceNowClient(
        settings.sn_instance_url,
        settings.sn_admin_user,
        settings.sn_admin_password,
        secrets=settings.secret_values(),
    ) as admin:
        try:
            admin.request("GET", "/api/now/ui/user/current")
            build_rows = _build_properties(admin)
        except ServiceNowError as exc:
            if exc.status_code in (401, 403):
                lines.append("admin login: failed")
                return DoctorReport(lines, ok=False)
            raise
        admin_ok = True
        lines.append("admin login: ok")
        lines.append(_build_line(build_rows))
        email_ok, email_line = _email(admin)
        lines.append(email_line)
        seed_changes, seed_incidents, seed_cis = _seed_counts(admin)
        lines.append(
            "change seed:"
            f" SYN-CHG-={seed_changes} SYN-INC-={seed_incidents} syn-ci={seed_cis}"
        )
        for label, user_attr, _password_attr in _LOGIN_FIELDS:
            user_name = getattr(settings, user_attr)
            rows = admin.get_table(
                "sys_user",
                query=f"user_name={user_name}",
                fields=["sys_id", "active"],
                limit=1,
            )
            if not rows:
                lines.append(f"{label}: absent")
                if label == "change agent":
                    agent_login = "absent"
                continue
            status = _login(settings, user_attr, _password_attr)
            lines.append(f"{label} login: {status}")
            if label == "change agent":
                agent_login = status
            elif status != "ok":
                present_users_ok = False
    ok = doctor_ok(
        admin_ok=admin_ok,
        email_ok=email_ok,
        agent_login=agent_login,
        seed_changes=seed_changes,
        pins_ok=pins_ok,
        present_users_ok=present_users_ok,
    )
    lines.append("doctor: ok" if ok else "doctor: failed")
    return DoctorReport(lines, ok=ok)


def _pins(lines: list[str]) -> bool:
    try:
        mismatches = pin_mismatches()
    except PinsError as exc:
        lines.append(f"pins: {exc}")
        return False
    if mismatches:
        for line in mismatches:
            lines.append(f"pins: {line}")
        return False
    lines.append("pins: match")
    return True


def _login(settings: Settings, user_attr: str, password_attr: str) -> str:
    try:
        with ServiceNowClient(
            settings.sn_instance_url,
            getattr(settings, user_attr),
            getattr(settings, password_attr),
            secrets=settings.secret_values(),
        ) as client:
            client.request("GET", "/api/now/ui/user/current")
    except ServiceNowError as exc:
        if exc.status_code in (401, 403):
            return f"failed HTTP {exc.status_code}"
        raise
    return "ok"


def _email(client: ServiceNowClient) -> tuple[bool, str]:
    try:
        rows = client.get_table(
            "sys_properties",
            query="nameINglide.email.smtp.active,glide.email.read.active",
            fields=["name", "value"],
            limit=10,
        )
    except ServiceNowError:
        return False, "email: properties could not be read"
    properties = {str(row.get("name")): str(row.get("value") or "") for row in rows}
    try:
        accounts = client.get_table(
            "sys_email_account",
            query="active=true",
            fields=["sys_id"],
            limit=20,
        )
        active = len(accounts)
    except ServiceNowError:
        return False, "email: account query failed"
    allowed, reason = evaluate_outbound_email(properties, active)
    if allowed:
        return True, "email: off"
    return False, f"email: blocked ({reason})"


def _seed_counts(client: ServiceNowClient) -> tuple[int, int, int]:
    changes = client.count("change_request", "correlation_idSTARTSWITHSYN-CHG-")
    incidents = client.count("incident", "correlation_idSTARTSWITHSYN-INC-")
    cis = client.count("cmdb_ci", "nameSTARTSWITHsyn-")
    return changes, incidents, cis


def _build_properties(client: ServiceNowClient) -> list[dict[str, object]]:
    rows = client.get_table(
        "sys_properties",
        query=BUILD_QUERY,
        fields=["name", "value"],
        limit=10,
    )
    if rows:
        return rows
    return client.get_table(
        "sys_properties",
        query=BUILD_FALLBACK_QUERY,
        fields=["name", "value"],
        limit=20,
    )


def _build_line(rows: list[dict[str, object]]) -> str:
    values = {str(row.get("name")): str(row.get("value") or "") for row in rows}
    name = values.get("glide.buildname")
    tag = values.get("glide.buildtag")
    if name or tag:
        return f"instance build: {name or 'unknown'} ({tag or 'unknown'})"
    war = values.get("glide.war")
    if war:
        return (
            "instance build: glide.buildname and glide.buildtag were not found; "
            f"glide.war={war}"
        )
    return "instance build: not found"
