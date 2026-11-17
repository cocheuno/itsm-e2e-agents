"""Phase 1 gate. Leaves the world seeded. Does not push."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from cm_agents.data.update_xml import APPROVED
from cm_agents.settings import redact_text

from e2e.counts import format_counts, probe_residue, snapshot
from e2e.doctor import run_doctor
from e2e.errors import WorldError
from e2e.guard import assert_run_quiet, e2e_incident_ids, latest_incident_stamp
from e2e.instance import open_client
from e2e.paths import repo_root
from e2e.probes import run_authority_probe, run_known_error_probe
from e2e.seed import run_seed
from e2e.settings import Settings
from e2e.teardown import run_teardown
from e2e.update_xml import report_update_xml

_URL = re.compile(r"https://dev\d+\.service-now\.com", re.IGNORECASE)


def run_gate(settings: Settings) -> int:
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        started = latest_incident_stamp(admin)
    print("gate: teardown")
    run_teardown(settings)
    absent = _counts(settings)
    if absent["endpoint_definitions"] not in {0, None}:
        raise WorldError("endpoint still present after teardown")
    print("gate: seed 1")
    run_seed(settings)
    first = _counts(settings)
    print(f"gate seed 1: {format_counts(first)}")
    print("gate: teardown")
    run_teardown(settings)
    print("gate: seed 2")
    run_seed(settings)
    second = _counts(settings)
    print(f"gate seed 2: {format_counts(second)}")
    if second != first:
        raise WorldError("the two seeds produced different counts")
    print("gate: reseed without teardown")
    run_seed(settings)
    third = _counts(settings)
    print(f"gate reseed: {format_counts(third)}")
    if third != second:
        raise WorldError("reseed without teardown changed the counts")
    print("gate: authority probe")
    run_authority_probe(settings)
    print("gate: known error probe")
    run_known_error_probe(settings)
    residue = _residue(settings)
    print(f"gate probe residue: {residue}")
    if any(residue.values()):
        raise WorldError("probe records are still present")
    after = _counts(settings)
    if after != third:
        raise WorldError("counts changed after the probes")
    print("gate: customer updates")
    updates = report_update_xml(settings)
    _require_updates(updates)
    print("gate: e2e doctor")
    report = run_doctor(settings)
    print(report.text())
    if not report.ok:
        raise WorldError("e2e doctor failed")
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        outside = assert_run_quiet(admin, started, e2e_incident_ids(admin))
    print(f"gate outside incident updates={outside}")
    print("gate: cm-agents doctor")
    _change(settings, ["-m", "cm_agents.cli", "doctor"], timeout=300)
    print("gate: S09")
    _change(settings, ["-m", "pytest", "-m", "live", "tests/live/test_s09.py", "-q"], timeout=1200)
    print("gate: pass")
    return 0


def _counts(settings: Settings) -> dict[str, int | None]:
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        return snapshot(admin)


def _residue(settings: Settings) -> dict[str, int]:
    with open_client(settings, settings.sn_admin_user, settings.sn_admin_password) as admin:
        return probe_residue(admin)


def _require_updates(updates: dict[str, object]) -> None:
    counts = updates["counts"]
    if not isinstance(counts, dict):
        raise WorldError("customer-update report was empty")
    if counts.get("orphan"):
        raise WorldError(f"customer-update orphans={counts['orphan']}")
    if not counts.get("endpoint"):
        raise WorldError("customer-update endpoint category was absent")
    details = updates.get("approved")
    if not isinstance(details, list):
        details = []
    joined = " ".join(str(item) for item in details)
    for name in APPROVED.values():
        if name not in joined:
            raise WorldError(f"approved setting was not classified: {name}")


def _change(settings: Settings, args: list[str], *, timeout: int) -> None:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise WorldError("LOCALAPPDATA is not set")
    python = Path(local) / "venvs" / "ChangeManagementAgent" / "Scripts" / "python.exe"
    if not python.is_file():
        raise WorldError("the change repository virtualenv is missing")
    repo = repo_root().parent / "ChangeManagementAgent"
    if not (repo / "pyproject.toml").is_file():
        raise WorldError("ChangeManagementAgent is not beside this repository")
    completed = subprocess.run(
        [str(python), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    print(_redact(settings, completed.stdout))
    if completed.stderr:
        print(_redact(settings, completed.stderr))
    if completed.returncode != 0:
        raise WorldError(f"change command failed with exit {completed.returncode}")


def _redact(settings: Settings, text: str) -> str:
    names = [
        settings.sn_admin_user,
        settings.sn_agent_user,
        settings.sn_incident_user,
        settings.sn_problem_user,
        settings.sn_authority_user,
    ]
    cleaned = redact_text(text, [*settings.secret_values(), *names])
    return _URL.sub("[instance]", cleaned)
