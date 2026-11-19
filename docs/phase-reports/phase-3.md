# Phase 3

The Phase 3 gate passed (`pytest tests/live/test_phase3.py -m live`, exit 0, 258.84s). E02 ran twice in that process. Each run started from the seeded counts and returned to them. The harness deleted the change before each run returned. This commit is local on `grok-build`. It was not pushed. The change repository was not modified and remains at `811e8fd`. The incident repository and `pm-agent-e2e` were not modified.

## What the gate showed

Both runs did the same work. Four arrivals, one tick, and no new problem. The fifth arrival, one tick, and exactly one new problem for that CI. Confidence was High and the peak was 5. Total problems went from 1 to 2, then back to 1 when the run removed its problem.

The problem key is the hash of the detected CI and category, `E2E-PRB-42866cd126560fab`. The case id is `E2E-42866cd1`. Signals were computed from the ServiceNow cluster in the lookback, history and arrivals together. They matched the offline backtest: a, b, and c were `log_rotation_stopped`, d was false, and the decision was confirmed.

| Check | Each run |
|---|---|
| Counts before and after | incidents=101 problems=1 articles=1 changes=0 endpoint 1/2 |
| Before the fifth | 0 problems on the checkout CI, 1 problem in total |
| After the fifth | 1 problem on the checkout CI, 2 problems in total |
| Confidence / peak | High / 5 |
| Signals | a, b, c `log_rotation_stopped`; d false; fired a, b, c |
| RCA | 5 Whys, clue share 1.0, last business day 0 |
| Proposed mechanism | `log_rotation_stopped` |
| Root-cause tokens | prompt 1622, completion 53 |
| Arrivals linked | 5 |
| History notes | 3 |
| Recurrence in 14 days | 0, from stored `opened_at` |
| Guard | 0 outside updates |
| Plans | matched the catalog while the change existed |
| `problem.rfc` | set and read back while the change existed |
| Problem close | 103, then 104, 106, 107, each HTTP 200 |

The first run's problem was PRB0040062 and its article was KB0010022. The second run's problem was PRB0040063 and its article was KB0010023. Both articles were published. The scenario then deleted the arrivals, the article, the problem, and the change. Those numbers are not left on the instance.

The import set stored the fixture `opened_at` on every arrival. The parent update did not replace it. Recurrence, counted from that stored column, was 0.

The requested window was 2026-11-11 01:00–03:00. Both runs stored 2026-11-08 03:00:00 through 2026-11-08 05:00:00. The requested constants were not changed. Go used the stored start plus 30 minutes.

The authority user approved only the requested approval row whose approver is that user. Assess stayed at Authorize (`-3`). Authorize stayed at Scheduled (`-2`). Risk was 4 and the type was normal, so the hold did not fire. The read-back was state 3 and close code `successful`. An empty resume dict does not advance this graph. The resume value is `{"continue": "true"}`.

Close notes start with `Recurrence in 14 days: 0.` The harness then deleted the change. `changes=0` after each run.

## How to follow the case

The case id is `E2E-` plus the first 8 hex digits of the problem correlation. While the change existed, ServiceNow showed it in two places:

- `problem.rfc` pointed at the change.
- The problem work note was `Change {number}. Thread {thread id}.`

Deleting the change clears `rfc`. The scenario also deletes the problem, so that work note does not remain after the run. The seeded problem and the seeded article are the ones left behind.

## Tokens

Each root-cause call used temperature 0. Both calls were prompt 1622 and completion 53. The second call's latency was 5945 ms.

The change graph tag for this gate is `e2e-case`. The first run wrote three audit rows: plan quality 2046 tokens / 4433 ms, CAB brief 3803 / 20761 ms, close notes 1675 / 3446 ms. That is 3 calls, 7524 tokens, 28640 ms. The second run wrote three more: plan quality 1987 / 4391 ms, CAB brief 4340 / 28935 ms, close notes 1668 / 2836 ms. The printed total after the second run, 6 calls, 15519 tokens, 64802 ms, is both runs.

## Fork

`pm-agent-e2e` was not edited. The case calls `detection_agent.detect` and the pure functions `clue_share`, `choose_method`, and `_last_business_day`, plus this repository's signal table. It does not call `gather()`. The fork's offline unittest was `Ran 17 tests in 0.086s` and `OK`.

## Change repository

The offline suite, from that repository's own environment, was `174 passed, 14 deselected` in 140.57s. HEAD stayed `811e8fd`. No file there was edited.

With the end-to-end layer loaded and no end-to-end scenario running, `cm-agents scenario run S01` from the change repository passed: 1 passed in 38.95s, state 3, close code `successful`. End-to-end counts were the same before and after: incidents=101 problems=1 articles=1 changes=0, endpoint 1 definition and 2 operations. Its own cleanup left 0 scenario changes and 0 scenario incidents.

## PMSYNTH

The comparison ran after the second E02 and did not fail the gate. The incident user read 200 `PMSYNTH` incidents. CI precision 0.571, recall 1.000, 7 candidates, 4 expected. Incident precision 0.687, recall 1.000. Candidates: mail-01 High peak 9 count 26, payroll-app-01 High peak 7 count 14, db-prod-01 High peak 7 count 16, vpn-gw-01 High peak 8 count 15, core-sw-01 High peak 6 count 14, crmdb High peak 5 count 9, sp-web-01 High peak 5 count 5. The three false candidates are core-sw-01, crmdb, and sp-web-01.

## Tests

This repository, with `%LOCALAPPDATA%\venvs\itsm-e2e-agents`:

```
ruff check e2e tests
All checks passed!

pytest -q
69 passed in 26.60s
```

Run-time modules do not import ground truth or the planted-cluster table. The Phase 3 accept decision lives in `tests/helpers/decisions.py` and is passed into the case graph. `e2e/simulator/deliver.py` is the world simulator and is the delivery module allowed to use the admin import path.
