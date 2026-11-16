"""Pinned sibling commits."""

from pathlib import Path

import pytest

from e2e.pins import PinsError, load_pins, pin_mismatches


def test_live_checkouts_match_pins() -> None:
    assert pin_mismatches() == []


def test_missing_sibling_name(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "pins.json").write_text(
        '{"ChangeManagementAgent": "abc"}\n',
        encoding="utf-8",
    )
    with pytest.raises(PinsError, match="itscm-451z-agent"):
        load_pins(tmp_path)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PinsError, match="config/pins.json"):
        load_pins(tmp_path)
