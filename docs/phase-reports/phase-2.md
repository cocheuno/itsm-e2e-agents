# Phase 2

The Phase 2 gate passed (`e2e phase2`, exit 0). The world is left seeded, with the six arrivals resolved. This commit is local on `grok-build`. It was not pushed. The incident repository commit is local on `e2e-incident`. `main` there was not moved, and nothing was pushed.

## What the gate showed

The clock was pinned at 2026-10-24 16:00 UTC. That delivers the five E02 arrivals and the separate E01 arrival. The E01 arrival is not in the seed or the backtest population. Detection did not run. No E07 arrival was delivered.

| Tick | Arrivals | Created | Triaged | Known error | Restored | Skipped | Outside updates | Harmful |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| First | 6 | 6 | 6 | 1 | 5 | 0 | 0 | 0 |
| Second | 6 | 0 | 0 | 0 | 0 | 12 | 0 | 0 |

The second tick did not change `sys_updated_on` on those six incidents.

| Record | Result |
|---|---|
| `INC0012786` | E01. Resolved, category `software`, priority 4, close code `Workaround provided`, parent set to the seeded problem. Close notes: `[agent] Workaround provided. Article KB0010018. Problem PRB0040058.` |
| `INC0012781`–`INC0012785` | E02. Resolved, category `software`, priority 4, close code `Solution provided`, parent empty |

`phase 2 before: incidents=101 problems=1 articles=1 changes=0 endpoint_definitions=1 endpoint_operations=2`

`phase 2 after: incidents=107 problems=1 articles=1 changes=0 endpoint_definitions=1 endpoint_operations=2`

`e2e doctor` printed `pins: match`, `change seed: SYN-CHG-=1500 SYN-INC-=164 syn-ci=296`, `problem close would resolve: 0 script=Update Incident when Problem closes query=state=3^hold_reason=3`, and `doctor: ok`. The gate then printed `phase 2: pass`.

Priority was not written. Impact 3 and urgency 3 were written, and the platform lookup read back as 4. The course matrix still maps that pair to 5. The eval harness still scores `sla.priority`.

## Decisions

Category comes from the CI-class table. `cmdb_ci_appl` is `software`. `cmdb_ci_linux_server` is `hardware`. The committed model is not called. ADR 0006 records that the model scored 0.5 on the arrival fixtures.

The known-error match reads `kb_knowledge.source` and `cmdb_ci`. The article must be published, start with `SYN-E2E-`, and point at a problem whose `known_error` is true and whose workaround is non-empty. Term-count cosine must clear the fixture midpoint. The E01 pair scores 0.5. A printer decoy scores 0.318, which is above 0.20, so the threshold is that midpoint. It was fixed before the live tick. Markup is stripped before the count. The seeded article body is the plain fixture text.

On a match the comment is the problem workaround, `parent` is that problem, and the close code is `Workaround provided`. Close notes name the article number and the problem number. `Known error` is not sent. The problem's primary known-error article field is not written. The gate read it and it was empty. No `m2m_kb_task` row is inserted.

The incident user can read `sys_user_group` (HTTP 200, one row for the store group) and cannot see `kb_knowledge` or `problem` (HTTP 200, zero rows). Admin sees the one article and the one problem. The tick reads those two tables as admin and writes the incident as the incident user.

Incident text did not reach an LLM. Similarity is local. The category rule ignores incident text. The resolver's close notes come from the fixture row. `config.load()` now allows an empty `ANTHROPIC_API_KEY` (`os.getenv("ANTHROPIC_API_KEY", "")`). The tick does not call `load()`. `AGENT_MODE` stays `dry_run` unless the tick passes `live=True` into `bind_writes`. ADR 0010 records that change.

The resolver sets state 6 with the seeded close code and close notes. It has no On Hold state and no hold reason.

Every executed write goes through the registry at `execute_with_approval`. The approver is `incident authority`. The approval is the rule's exact arguments and is spent once. A mismatched `apply_known_error` approval is refused and counted harmful. The real runs had `harmful_action_count` 0. `add_comment` stays `propose` and is not used to execute.

The update guard ran on both ticks. Allowed ids were the arrivals that tick created or updated. The outside count was 0 both times.

## Packaging

The distribution name is `itscm-451z-agent`. The import name is `agent`. Before `uv sync`, `find_spec("agent")` in the e2e environment was absent. After the install, `agent`, `cm_agents`, and `e2e` import as three modules. The name `agent` would collide with a third-party distribution of that name in the same environment. It does not collide with the change package or this package.

The wheel lists `packages = ["src/agent"]` and rewrites that directory to `agent`. The orchestrator depends on it with `editable = true` and a relative path. `uv.lock` records that relative path. The incident environment was not `uv sync`ed, so its scikit-learn pin stayed. Incident tests used that environment's Python with `PYTHONPATH=src` for the harness.

## Tests

Incident repository, on `e2e-incident`, with `%LOCALAPPDATA%\venvs\itscm-451z-agent`:

```
ruff check .
All checks passed!

pytest -q
110 passed, 2 skipped in 64.21s

python -m eval.harness --rung auto --fixtures
classification_accuracy 1.0
priority_sla_agreement 1.0
routing_accuracy 1.0
harmful_action_count 0
```

This repository, with `%LOCALAPPDATA%\venvs\itsm-e2e-agents`:

```
ruff check e2e tests
All checks passed!

pytest -q
40 passed in 22.06s
```

`../ChangeManagementAgent` was not edited. `pytest -m "not live"` reported 174 passed, 14 deselected, in 311.81s. No live scenario was run.

`../pm-agent-e2e` was not edited. `python -m unittest discover tests` ran 17 tests, OK. `../pm-agent` was not used.

## Git

| Repository | Branch | `git log -1` |
|---|---|---|
| `../itscm-451z-agent` | `main` | `c5cc1856ff1d9d4440185f7a12fc753493507369` Merge pull request #34 from cocheuno/lecture-itsm-agents-analytics |
| `../itscm-451z-agent` | `e2e-incident` | `fbf53d264a970d2b65c7aff05078e7008c1378b0` Add the end-to-end incident workflow on e2e-incident. |
| this repository | `grok-build` | this commit |
| `../ChangeManagementAgent` | unchanged | clean working tree |
| `../pm-agent-e2e` | `e2e` | `5a8c995c3c9a92221716859f5ca17fe1e5c2ec04`, clean, no upstream |

Nothing was pushed.
