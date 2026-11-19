"""Phase 3 decision helpers. The case graph receives them. It does not import them."""

from __future__ import annotations

from e2e.data.world import CLUSTERS


def accept_planted_cause(proposed: str, ci: str, *, scenario: str) -> bool:
    """Accept a cause only when it is the planted mechanism for that scenario and CI."""
    matches = [
        cluster
        for cluster in CLUSTERS
        if cluster["ci"] == ci and cluster["scenario"] == scenario
    ]
    if len(matches) != 1 or not proposed:
        return False
    return proposed == matches[0]["mechanism"]
