"""End-to-end scenarios. Each one deletes its change thread before it returns.

The thread id is SYN-E2E-<case>-CHG-<attempt>. Persistent E2E- rows are not
deleted here. A failure takes the same path as a pass.
"""

from __future__ import annotations

from collections.abc import Callable

from e2e.errors import WorldError
from e2e.instance import open_client
from e2e.scenario_records import delete_scenario_threads
from e2e.settings import Settings

SCENARIOS = tuple(f"E{index:02d}" for index in range(1, 13))


def scenario_names(name: str) -> list[str]:
    if name == "all":
        return list(SCENARIOS)
    if name not in SCENARIOS:
        raise WorldError("scenario must be E01 through E12, or all")
    return [name]


def execute_scenario(
    body: Callable[[], None],
    threads: list[str],
    deleter: Callable[[list[str]], None],
) -> None:
    """Run one scenario and always hand its thread ids to the deleter.

    A delete failure still runs. When the body already failed, that error is
    the one that propagates. The delete failure is printed as a status line.
    """
    caught: BaseException | None = None
    try:
        body()
    except BaseException as exc:
        caught = exc
    try:
        deleter(list(threads))
    except BaseException as exc:
        if caught is None:
            raise
        if isinstance(exc, WorldError):
            print(f"scenario delete failed {exc}")
        else:
            print(f"scenario delete failed {type(exc).__name__}")
    if caught is not None:
        raise caught


def run_scenarios(settings: Settings, name: str) -> int:
    for scenario in scenario_names(name):
        threads: list[str] = []
        execute_scenario(
            lambda scenario=scenario, threads=threads: _run_one(settings, scenario, threads),
            threads,
            lambda ids: _delete(settings, ids),
        )
    return 0


def _run_one(settings: Settings, name: str, threads: list[str]) -> None:
    """The scenario body appends each thread id it creates to `threads`."""
    if name != "E02":
        raise WorldError(f"{name} is not implemented")
    from e2e.phase3_e02 import run_e02
    from e2e.state_api import endpoint_base

    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        base = endpoint_base(admin)
    if not base:
        raise WorldError("endpoint base uri was empty")
    run_e02(settings, threads, base)


def _delete(settings: Settings, thread_ids: list[str]) -> None:
    if not thread_ids:
        return
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        delete_scenario_threads(admin, thread_ids)
