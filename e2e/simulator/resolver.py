"""Restore an arrival the known-error match did not take.

The outcome is the fixture's close code and close notes. This simulator
does not set On Hold and does not set a hold reason.
"""

from __future__ import annotations

STATE_RESOLVED = "6"
DEFAULT_CODE = "Solution provided"


def outcome_for(row: dict) -> dict[str, str]:
    """The seeded resolve. The state is Resolved and there is no hold reason."""
    code = str(row.get("close_code") or DEFAULT_CODE)
    notes = str(row.get("close_notes") or row.get("notes") or "")
    if code.lower() == "known error":
        raise ValueError("the resolver does not use close code Known error")
    if not notes:
        raise ValueError("a seeded outcome needs close notes")
    return {"state": STATE_RESOLVED, "close_code": code, "close_notes": notes}
