"""Open a ServiceNow client. Failure text keeps the status code and drops the host."""

from __future__ import annotations

from cm_agents.servicenow.client import PdiAsleepError, ServiceNowClient, ServiceNowError

from e2e.errors import WorldError
from e2e.settings import Settings


def open_client(settings: Settings, user: str, password: str) -> ServiceNowClient:
    return ServiceNowClient(
        settings.sn_instance_url,
        user,
        password,
        secrets=settings.secret_values(),
        timeout=180,
    )


def http_failure(action: str, exc: ServiceNowError) -> WorldError:
    if isinstance(exc, PdiAsleepError):
        return WorldError(f"{action} failed because the instance returned a non-JSON response")
    code = exc.status_code if exc.status_code is not None else "none"
    return WorldError(f"{action} failed HTTP {code}")
