"""Offline scores of arrivals, noise, and decoys against the seeded article.

The cutoff is the fixture midpoint. Same-CI is applied before the score in
the match. This table shows both, and it does not read the instance.
"""

from __future__ import annotations

from agent.workflow.known_error import SIMILARITY_MIN, match_known_error, similarity

from e2e.data.arrivals import e01_arrival
from e2e.data.fixtures import build_incidents
from e2e.seed import ARTICLE_SHORT, CAUSE, WORKAROUND

ARTICLE_CI = "syn-store-cdn"
ARTICLE_TEXT = f"{CAUSE} {WORKAROUND}"
SCORED = f"{ARTICLE_SHORT} {ARTICLE_TEXT}"


def _rows() -> list[dict]:
    arrivals = [row for row in build_incidents() if not row["history"]]
    arrivals.append(e01_arrival())
    noise = [row for row in build_incidents() if str(row["cluster"]).startswith("noise-")]
    decoys = [row for row in build_incidents() if row["cluster"] == "D08"]
    labelled = [("arrival", row) for row in arrivals]
    labelled.extend(("noise", row) for row in noise)
    labelled.extend(("decoy", row) for row in decoys)
    table = []
    for kind, row in labelled:
        incident_text = f"{row['short_description']} {row.get('description', '')}"
        score = similarity(incident_text, SCORED)
        same_ci = row["cmdb_ci"] == ARTICLE_CI
        table.append(
            {
                "kind": kind,
                "cluster": str(row.get("cluster") or row.get("scenario") or ""),
                "ci": row["cmdb_ci"],
                "score": score,
                "same_ci": same_ci,
                "kept": same_ci and score >= SIMILARITY_MIN,
            }
        )
    return table


def test_same_ci_keeps_only_the_e01_arrival() -> None:
    table = _rows()
    assert any(row["kind"] == "decoy" for row in table)
    assert any(row["kind"] == "noise" for row in table)
    kept = [row for row in table if row["kept"]]
    assert len(kept) == 1
    assert kept[0]["kind"] == "arrival"
    assert kept[0]["ci"] == ARTICLE_CI
    assert kept[0]["score"] >= SIMILARITY_MIN
    rejected = [row for row in table if not row["same_ci"]]
    assert rejected
    assert all(not row["kept"] for row in rejected)
    # The checkout arrivals share the log-rotation words. The CI rejects them
    # even when the score clears the cutoff.
    above = [row for row in rejected if row["score"] >= SIMILARITY_MIN]
    highest = max(row["score"] for row in rejected)
    assert above, f"highest other score {highest:.4f} sits under {SIMILARITY_MIN:.4f}"


def test_match_applies_same_ci_before_the_score() -> None:
    article = {
        "number": "KB0000001",
        "short_description": ARTICLE_SHORT,
        "text": ARTICLE_TEXT,
        "source": "problem-1",
        "cmdb_ci": ARTICLE_CI,
        "workflow_state": "published",
    }
    problems = {
        "problem-1": {
            "number": "PRB0000001",
            "known_error": "true",
            "workaround": WORKAROUND,
        }
    }
    arrival = e01_arrival()
    found = match_known_error(arrival, [article], problems)
    assert found is not None
    assert found["score"] >= SIMILARITY_MIN
    other = dict(arrival)
    other["cmdb_ci"] = "syn-store-checkout"
    assert match_known_error(other, [article], problems) is None
