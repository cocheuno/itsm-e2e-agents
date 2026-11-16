"""Settings load from a file. Error text names keys and omits values."""

from pathlib import Path

import pytest

from e2e.settings import REQUIRED_KEYS, SettingsError, load_settings

_URL = "https://dev12345.service-now.com"


def _env(tmp_path: Path, **overrides: str) -> Path:
    values = {key: f"value-for-{key}" for key in REQUIRED_KEYS}
    values["SN_INSTANCE_URL"] = _URL
    values.update(overrides)
    path = tmp_path / ".env"
    path.write_text("\n".join(f"{key}={values[key]}" for key in REQUIRED_KEYS), encoding="utf-8")
    return path


def test_thirteen_names_are_required() -> None:
    assert len(REQUIRED_KEYS) == 13
    assert REQUIRED_KEYS[:1] == ("SN_INSTANCE_URL",)
    assert "XAI_API_KEY" in REQUIRED_KEYS
    assert "XAI_MODEL" in REQUIRED_KEYS
    assert "SN_AUTHORITY_PASSWORD" in REQUIRED_KEYS


def test_missing_key_reports_the_name_only(tmp_path: Path) -> None:
    path = _env(tmp_path, SN_ADMIN_PASSWORD="", SN_PROBLEM_USER="")
    with pytest.raises(SettingsError) as caught:
        load_settings(path)
    message = str(caught.value)
    assert "SN_ADMIN_PASSWORD" in message
    assert "SN_PROBLEM_USER" in message
    assert "value-for-" not in message
    assert _URL not in message


def test_bad_url_does_not_echo_the_value(tmp_path: Path) -> None:
    path = _env(tmp_path, SN_INSTANCE_URL="https://example.invalid")
    with pytest.raises(SettingsError) as caught:
        load_settings(path)
    message = str(caught.value)
    assert message == "SN_INSTANCE_URL is not a Personal Developer Instance URL"
    assert "example.invalid" not in message


def test_loaded_settings_hide_values_in_repr(tmp_path: Path) -> None:
    settings = load_settings(_env(tmp_path))
    text = repr(settings)
    assert "value-for-" not in text
    assert _URL not in text
    secrets = settings.secret_values()
    assert "value-for-SN_ADMIN_PASSWORD" in secrets
    assert "value-for-XAI_API_KEY" in secrets
    assert "value-for-SN_ADMIN_USER" not in secrets
    assert "value-for-XAI_MODEL" not in secrets
