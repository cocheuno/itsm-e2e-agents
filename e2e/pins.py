"""Exact commits of the three sibling checkouts. Path sources do not pin them."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from e2e.settings import repo_root

SIBLINGS = (
    "ChangeManagementAgent",
    "itscm-451z-agent",
    "pm-agent-e2e",
)
# The pin records the imported main commit. These branches may move ahead of it.
# ChangeManagementAgent stays on the pinned commit.
_AHEAD_OK = {
    "itscm-451z-agent": "e2e-incident",
    "pm-agent-e2e": "e2e",
}


class PinsError(RuntimeError):
    """A sibling checkout is not the commit this phase imported."""


def pins_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / "config" / "pins.json"


def load_pins(root: Path | None = None) -> dict[str, str]:
    path = pins_path(root)
    if not path.is_file():
        raise PinsError("config/pins.json is missing")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise PinsError("config/pins.json must be an object")
    pins = {str(key): str(value) for key, value in loaded.items()}
    missing = [name for name in SIBLINGS if not pins.get(name)]
    if missing:
        raise PinsError("config/pins.json is missing " + ", ".join(missing))
    return pins


def sibling_heads(root: Path | None = None) -> dict[str, str]:
    parent = (root or repo_root()).parent
    heads: dict[str, str] = {}
    for name in SIBLINGS:
        path = parent / name
        if not path.is_dir():
            raise PinsError(f"sibling folder {name} is missing")
        completed = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise PinsError(f"could not read HEAD for {name}")
        heads[name] = completed.stdout.strip()
    return heads


def pin_mismatches(root: Path | None = None) -> list[str]:
    pins = load_pins(root)
    heads = sibling_heads(root)
    parent = (root or repo_root()).parent
    lines = []
    for name in SIBLINGS:
        if pins[name] == heads[name]:
            continue
        branch = _AHEAD_OK.get(name)
        if branch and _branch_is(parent / name, branch) and _contains(parent / name, pins[name]):
            continue
        lines.append(f"{name} pinned {pins[name]} checkout {heads[name]}")
    return lines


def _branch_is(path: Path, branch: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0 and completed.stdout.strip() == branch


def _contains(path: Path, commit: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(path), "merge-base", "--is-ancestor", commit, "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0
