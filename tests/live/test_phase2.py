"""Phase 2 gate. Opt in with pytest tests/live/test_phase2.py -m live."""

from __future__ import annotations

import pytest

from e2e.phase2 import run_phase2
from e2e.settings import load_settings


@pytest.mark.live
def test_phase2_gate() -> None:
    assert run_phase2(load_settings()) == 0
