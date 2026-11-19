# Phase 3

The Phase 3 gate passed (`pytest tests/live/test_phase3.py -m live`, exit 0, 120.86s). One scenario ran: E02. The change thread was deleted before the test returned. This commit is local on `grok-build`. It was not pushed. The change repository was not modified. The incident repository commit is local on `e2e-incident`. `main` there was not moved, and nothing was pushed.

## What the gate showed

The checkout problem and its known-error article already existed and were reused. Detection before the fifth arrival opened nothing. After the fifth, confidence was High and the peak was 5. The root-cause helper proposed `log_rotation_stopped`. Signal (a) fired. Signals (b) and (c) did not. Signal (d) was false.

| Check | Result |
|---|---|
| Before the fifth | 0 checkout candidates |
| Confidence / peak | High / 5 |
| RCA | 5 Whys, clue share 1.0, last business day 0 |
| Signals | a=`log_rotation_stopped`, b empty, c empty, d false |
| Arrivals linked | 5, state 6, parent set |
| History notes | 3 |
| Article | KB0010020, published, source the checkout problem, CI `syn-store-checkout` |
| Problem | PRB0040060, correlation `E2E-PRB-256ec3a2c108b8f7`, ended Closed (107) |
| Plans | implementation, backout, and test plans matched the catalog |
| `problem.rfc` | set and read back while the change existed |
| Recurrence in 14 days | 0 |
| Guard | 0 outside updates |
| Persistent counts after | incidents=107 problems=2 articles=2 changes=0 endpoint 1/2 |

The same persistent counts were read before the run. E01 is still PRB0040059 and KB0010019. The five restored arrivals were not triaged again. Priority was not written.

The requested window was 2026-11-11 01:00–03:00. The change repository's scheduler stored 2026-11-08 03:00:00 through 2026-11-08 05:00:00. Its audit line says maintenance inside, conflicts none, moved because of a blackout. The requested constants were not changed. Go used the stored start plus 30 minutes.

The authority user approved only the requested approval row whose approver is that user. Assess stayed at Authorize (`-3`). Authorize stayed at Scheduled (`-2`). Risk was 4 and the type was normal, so the hold did not fire. The deployment was verified. The independent read-back after the graph was state 3 and close code `successful`.

The problem then moved 103 → 104 → 106 → 107, each HTTP 200. Close notes start with `Recurrence in 14 days: 0.` The harness then deleted the change. `changes=0` after the test. No change number is kept here.

## How to follow the case

The case id is `E2E-256ec3a2`. That is `E2E-` plus the first 8 hex digits of the digest in the problem correlation `E2E-PRB-256ec3a2c108b8f7`.

The change thread id is `SYN-E2E-E2E-256ec3a2-CHG-1`. While the change existed, ServiceNow showed it in two places:

- `problem.rfc` pointed at the change.
- The problem work note was `Change {number}. Thread SYN-E2E-E2E-256ec3a2-CHG-1.`

Deleting the change clears `rfc`. The work note remains on the problem. The correlation id on the problem is the persistent key. The thread id is only the change's `correlation_id`, and it is gone once the harness deletes that change.

## Tokens

This repository's root-cause call, temperature 0, against the xAI chat endpoint: prompt 1523, completion 38, latency 8778 ms.

The passing change-graph run wrote three audit rows: plan quality 2002 tokens / 4697 ms, CAB brief 3853 / 20656 ms, close notes 1781 / 5573 ms. That is 3 calls, 7636 tokens, 30926 ms. The gate's printed graph total (6 calls, 15095 tokens, 84586 ms) is every row tagged `e2e-phase3` in the change repository's audit, including one earlier attempt that reached the same three calls.

## Fork

`pm-agent-e2e` was not edited. E02 calls `detection_agent.detect` and the pure functions `clue_share`, `choose_method`, and `_last_business_day`, plus this repository's signal table. It does not call `gather()`, the fork's seeder, the fork's state endpoint, or `knowledge_agent`. The fork's offline unittest was already 17 passed. It was not run again.

## PMSYNTH

The comparison ran after E02 and did not fail the gate. The incident user read 200 `PMSYNTH` incidents. CI precision 0.571, recall 1.000, 7 candidates, 4 expected. Incident precision 0.687, recall 1.000. Candidates: mail-01 High peak 9 count 26, payroll-app-01 High peak 7 count 14, db-prod-01 High peak 7 count 16, vpn-gw-01 High peak 8 count 15, core-sw-01 High peak 6 count 14, crmdb High peak 5 count 9, sp-web-01 High peak 5 count 5.

## PDI facts this phase recorded

The five checkout arrivals keep the platform insert time `2026-11-19 15:30`. A later update read back that same time. Recurrence does not use that stored value. It uses the fixture `opened_at` joined by correlation id, so the October history is not counted after the simulated close. This run's recurrence was 0. Where that overlay disagrees with the stored column, the overlay is the clock.

An empty resume dict does not advance this LangGraph checkpoint. The resume value is the change CLI's `{"continue": "true"}`.

`task_ci` is not deleted directly. The change model returns HTTP 403 for that delete. Deleting the change removes those rows.

A Closed problem (107) rejects `work_notes` and `rfc` for the problem user (HTTP 403). The problem user also reads journal rows back empty, so a note is written only while the problem is open. This run wrote the notes at state 103.

The problem state model allowed a move from 107 back to 103 through the existing `syne2e` move operation. That was a one-time recovery so a later attempt could set `rfc`. The passing run did not move backward.

A finished checkpoint for the same thread id made an earlier attempt print state 3 while the new change was still Scheduled, with an empty close code. The harness now deletes that thread's checkpoint and its deploy-simulator entry before `start_change`, and leaves every other thread. This run cleared that memory, and the read-back was state 3, close code `successful`. The second close walk was not used.

The change repository's clean-up deletes a `SYN-` correlation. Do not run a `cm-agents` scenario while an end-to-end scenario is in progress.

## Tests

This repository, with `%LOCALAPPDATA%\venvs\itsm-e2e-agents`:

```
ruff check e2e tests
All checks passed!

pytest -q
64 passed in 37.31s
```

`tests/live` is not in that default run. The live gate above is the one that calls ServiceNow.

The change repository was not modified. Its last offline run, from before this phase, was 174 passed and 14 deselected. It was not run again. HEAD remains `811e8fd6e4969ebabedd48aa37e593fe8b24b281`.

The incident repository, on `e2e-incident`, with `%LOCALAPPDATA%\venvs\itscm-451z-agent` and `PYTHONPATH=src`:

```
ruff check src tests
All checks passed!

pytest -q
110 passed, 2 skipped
```
