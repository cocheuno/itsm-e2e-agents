"""Phase 3 gate. Opt in with pytest tests/live/test_phase3.py -m live."""

from __future__ import annotations

import logging

import pytest

from e2e.cli import configure_logging
from e2e.pmsynth import report_pmsynth
from e2e.scenarios import run_scenarios
from e2e.settings import load_settings


@pytest.mark.live
def test_phase3_e02() -> None:
    settings = load_settings()
    configure_logging(settings.secret_values())
    logging.getLogger("cm_agents").setLevel(logging.WARNING)
    assert run_scenarios(settings, "E02") == 0
    assert run_scenarios(settings, "E02") == 0
    try:
        report_pmsynth(settings)
    except Exception:
        print("pmsynth skipped")
