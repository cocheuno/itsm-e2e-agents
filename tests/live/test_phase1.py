"""Phase 1 gate. Opt in with pytest tests/live -m live. This file is not the default suite."""

from __future__ import annotations

import pytest

from e2e.gate import run_gate
from e2e.settings import load_settings


@pytest.mark.live
def test_phase1_gate() -> None:
    assert run_gate(load_settings()) == 0
