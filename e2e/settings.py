"""Load connection settings from .env. Never log or persist the values."""

from __future__ import annotations

from pathlib import Path

from cm_agents.settings import SettingsError, assert_pdi_url, parse_env_text, redact_text
from pydantic import BaseModel, ConfigDict, Field

REQUIRED_KEYS: tuple[str, ...] = (
    "SN_INSTANCE_URL",
    "SN_ADMIN_USER",
    "SN_ADMIN_PASSWORD",
    "SN_AGENT_USER",
    "SN_AGENT_PASSWORD",
    "SN_INCIDENT_USER",
    "SN_INCIDENT_PASSWORD",
    "SN_PROBLEM_USER",
    "SN_PROBLEM_PASSWORD",
    "SN_AUTHORITY_USER",
    "SN_AUTHORITY_PASSWORD",
    "XAI_API_KEY",
    "XAI_MODEL",
)

_ENV_FIELDS = {
    "SN_INSTANCE_URL": "sn_instance_url",
    "SN_ADMIN_USER": "sn_admin_user",
    "SN_ADMIN_PASSWORD": "sn_admin_password",
    "SN_AGENT_USER": "sn_agent_user",
    "SN_AGENT_PASSWORD": "sn_agent_password",
    "SN_INCIDENT_USER": "sn_incident_user",
    "SN_INCIDENT_PASSWORD": "sn_incident_password",
    "SN_PROBLEM_USER": "sn_problem_user",
    "SN_PROBLEM_PASSWORD": "sn_problem_password",
    "SN_AUTHORITY_USER": "sn_authority_user",
    "SN_AUTHORITY_PASSWORD": "sn_authority_password",
    "XAI_API_KEY": "xai_api_key",
    "XAI_MODEL": "xai_model",
}


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sn_instance_url: str = Field(repr=False)
    sn_admin_user: str = Field(repr=False)
    sn_admin_password: str = Field(repr=False)
    sn_agent_user: str = Field(repr=False)
    sn_agent_password: str = Field(repr=False)
    sn_incident_user: str = Field(repr=False)
    sn_incident_password: str = Field(repr=False)
    sn_problem_user: str = Field(repr=False)
    sn_problem_password: str = Field(repr=False)
    sn_authority_user: str = Field(repr=False)
    sn_authority_password: str = Field(repr=False)
    xai_api_key: str = Field(repr=False)
    xai_model: str = Field(repr=False)

    def secret_values(self) -> list[str]:
        """Values that must never appear in logs, errors, or committed files."""
        return [
            self.sn_admin_password,
            self.sn_agent_password,
            self.sn_incident_password,
            self.sn_problem_password,
            self.sn_authority_password,
            self.xai_api_key,
        ]


def repo_root() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "e2e").is_dir():
            return candidate
    return Path.cwd()


def load_settings(path: Path | None = None) -> Settings:
    env_path = path if path is not None else repo_root() / ".env"
    if not env_path.is_file():
        names = ", ".join(REQUIRED_KEYS)
        raise SettingsError(f"Missing or empty required setting: {names}")
    text = env_path.read_text(encoding="utf-8-sig")
    values = parse_env_text(text)
    missing = [key for key in REQUIRED_KEYS if values.get(key, "") == ""]
    if missing:
        raise SettingsError("Missing or empty required setting: " + ", ".join(missing))
    assert_pdi_url(values["SN_INSTANCE_URL"])
    mapped = {_ENV_FIELDS[key]: values[key] for key in REQUIRED_KEYS}
    return Settings(**mapped)


__all__ = [
    "REQUIRED_KEYS",
    "Settings",
    "SettingsError",
    "load_settings",
    "redact_text",
    "repo_root",
]
