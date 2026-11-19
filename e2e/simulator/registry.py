"""Correlations the world simulator has delivered in this process.

The case graph reads the set. It does not insert incidents.
"""

from __future__ import annotations

_delivered: set[str] = set()
_rows: dict[str, dict] = {}


def note(correlation: str, row: dict | None = None) -> None:
    if not correlation:
        return
    _delivered.add(correlation)
    if row is not None:
        _rows[correlation] = dict(row)


def delivered() -> frozenset[str]:
    return frozenset(_delivered)


def row_for(correlation: str) -> dict | None:
    stored = _rows.get(correlation)
    if stored is None:
        return None
    return dict(stored)


def clear() -> None:
    _delivered.clear()
    _rows.clear()
