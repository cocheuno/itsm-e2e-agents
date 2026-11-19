"""Run-time modules must not construct a client with the admin credentials."""

from __future__ import annotations

from pathlib import Path

_BANNED = ("sn_admin_user", "sn_admin_password")


def _files(root: Path) -> list[Path]:
    found: list[Path] = []
    if not root.exists():
        return found
    if root.is_file():
        return [root]
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        found.append(path)
    return found


def test_runtime_modules_do_not_open_an_admin_client() -> None:
    repo = Path(__file__).resolve().parents[2]
    roots = [
        repo / "e2e" / "tick.py",
        repo / "e2e" / "case_graph.py",
        repo / "e2e" / "pmsynth.py",
        repo / "e2e" / "adapters",
        repo / "e2e" / "simulator" / "resolver.py",
        repo / "e2e" / "simulator" / "registry.py",
        repo.parent / "itscm-451z-agent" / "src" / "agent" / "workflow" / "authority.py",
    ]
    offenders: list[str] = []
    seen = False
    for root in roots:
        for path in _files(root):
            seen = True
            text = path.read_text(encoding="utf-8")
            if any(token in text for token in _BANNED):
                offenders.append(str(path))
    assert seen
    assert offenders == []


def test_the_world_simulator_is_listed_apart_from_the_agents() -> None:
    """Delivering an arrival may use the admin import path. Agents may not."""
    repo = Path(__file__).resolve().parents[2]
    path = repo / "e2e" / "simulator" / "deliver.py"
    text = path.read_text(encoding="utf-8")
    assert "sn_admin_user" in text
    assert "sn_admin_password" in text
    assert "import_opened_incident" in text
    banned = [
        repo / "e2e" / "tick.py",
        repo / "e2e" / "case_graph.py",
        repo / "e2e" / "adapters",
        repo / "e2e" / "simulator" / "resolver.py",
        repo / "e2e" / "simulator" / "registry.py",
    ]
    for root in banned:
        for item in _files(root):
            assert "import_opened_incident" not in item.read_text(encoding="utf-8")
