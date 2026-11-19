"""The phase gates are pytest tests. Scenarios delete their thread on failure."""

from __future__ import annotations

import pytest

from e2e.cli import main
from e2e.errors import WorldError
from e2e.scenarios import execute_scenario, scenario_names


def test_run_requires_until_idle() -> None:
    with pytest.raises(SystemExit) as caught:
        main(["run"])
    assert caught.value.code == 2


def test_gate_and_phase2_are_not_commands() -> None:
    for command in ("gate", "phase2"):
        with pytest.raises(SystemExit) as caught:
            main([command])
        assert caught.value.code == 2


def test_scenario_names() -> None:
    assert scenario_names("E01") == ["E01"]
    assert scenario_names("E12") == ["E12"]
    assert scenario_names("all")[0] == "E01"
    assert scenario_names("all")[-1] == "E12"
    assert len(scenario_names("all")) == 12
    with pytest.raises(WorldError):
        scenario_names("S01")


def test_a_failed_scenario_still_hands_its_thread_to_cleanup() -> None:
    threads = ["SYN-E2E-E2E-ab12cd34-CHG-1"]
    seen: list[str] = []

    def body() -> None:
        raise WorldError("failed")

    def deleter(ids: list[str]) -> None:
        seen.extend(ids)

    with pytest.raises(WorldError, match="failed"):
        execute_scenario(body, threads, deleter)
    assert seen == ["SYN-E2E-E2E-ab12cd34-CHG-1"]
