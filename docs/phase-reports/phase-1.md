# Phase 1

The Phase 1 gate passed (`e2e gate`, exit 0). The world is left seeded. This commit is local on `grok-build`. It was not pushed.

## Fork and settings

`git -C ..\pm-agent-e2e remote -v`

```
origin	https://github.com/cocheuno/pm-agent.git (fetch)
origin	https://github.com/cocheuno/pm-agent.git (push)
```

`git -C ..\pm-agent-e2e rev-parse HEAD` is `5a8c995c3c9a92221716859f5ca17fe1e5c2ec04`. The local branch is `e2e`, with no upstream. There is no `evebrin/pm-agent` remote. `../pm-agent` was not read or changed. The fork's `state_api.py` was not run and was not edited. Detection thresholds were not changed.

All thirteen `.env` names are present and non-empty. The URL matched `^https://dev\d+\.service-now\.com$` and its length is 33. Values are not printed here.

Before the gate, each of the three service passwords was checked without printing it. Each contains `!`, each length is 20, and no two are equal. This gate's logins succeeded without granting `snc_basic_auth_api_access`.

## Python and pins

`uv run python -V` reported `Python 3.13.2`. uv used the environment at `%LOCALAPPDATA%\venvs\itsm-e2e-agents`. No `.venv` was created inside a repository.

| Checkout | Pinned commit |
|---|---|
| ChangeManagementAgent | `811e8fd6e4969ebabedd48aa37e593fe8b24b281` |
| itscm-451z-agent | `c5cc1856ff1d9d4440185f7a12fc753493507369` |
| pm-agent-e2e | `5a8c995c3c9a92221716859f5ca17fe1e5c2ec04` |

`e2e doctor` printed `pins: match`.

## Files changed

Only this repository changed. `../pm-agent-e2e` is clean, so it has no commit. `../itscm-451z-agent` and `../ChangeManagementAgent` were not modified. `../pm-agent` was not used.

Modified:

- `.env.example`
- `docs/ASSUMPTIONS.md`
- `docs/DISCOVERY.md`
- `docs/architecture/END_TO_END_ITSM.md`
- `e2e/cli.py`

Added:

- `e2e/accounts.py`, `e2e/counts.py`, `e2e/errors.py`, `e2e/gate.py`, `e2e/instance.py`, `e2e/paths.py`, `e2e/probes.py`, `e2e/seed.py`, `e2e/teardown.py`, `e2e/update_xml.py`
- `e2e/data/` (`world.py`, `signals.py`, `fixtures.py`, `catalog.py`, `backtest.py`, `ground_truth.py`, `history.py`)
- `tests/unit/test_world.py`, `tests/unit/test_update_xml.py`, `tests/unit/test_seed.py`
- `docs/phase-reports/phase-1.md`

`data/synthetic/` stays gitignored. The manifest, ground truth, and config history are not in the commit.

With `UV_PROJECT_ENVIRONMENT` set to `%LOCALAPPDATA%\venvs\itsm-e2e-agents`:

```
uv run ruff check e2e tests
All checks passed!

uv run pytest -q
34 passed in 2.57s
```

## Cross-repository proposal

`pyproject.toml` depends on `cm-agents` with `[tool.uv.sources] cm-agents = { path = "../ChangeManagementAgent" }`. Phase 2 adds `../itscm-451z-agent` after packaging on `e2e-incident`. Phase 3 adds `../pm-agent-e2e` after a minimal `pyproject.toml` on branch `e2e`. Path sources do not pin commits, so `config/pins.json` is the pin and doctor checks it. Nothing uses an absolute path or a user name.

## Offline backtest

`python -m e2e.data.backtest` printed `outcomes match`. Thresholds stayed `min=5`, `window=14`, `cohesion_high=0.3`, `cohesion_medium=0.2`, `purity_high=0.6`, `method=centroid`.

Full world: 108 incidents, 10 candidates, detection precision 0.9. The eight-ticket decoy is the only detection false positive. The four-ticket burst and the noise open nothing.

| Cluster | CI | Confidence | Cohesion | Opens | Fired | Decision |
|---|---|---|---|---|---|---|
| C02 | syn-store-checkout | High | 0.49 | yes | a, b, c `log_rotation_stopped`; d false | confirmed |
| C04 | syn-stg-lx-001 | High | 0.61 | yes | a, b `worker_not_restarted`; d true | confirmed |
| C05 | syn-ful-inventory | High | 0.64 | yes | a, b `connection_pool_exhausted`; d true | confirmed |
| C06 | syn-pay-fraud | High | 0.56 | yes | a, b `cache_not_cleared`; d false | confirmed |
| C07 | syn-prd-lx-073 | High | 0.54 | yes | a, b `log_rotation_stopped`; d true | confirmed |
| C11 | syn-store-catalog | High | 0.7 | yes | a `worker_not_restarted`, b `weekend_batch_lock`; d false | unconfirmed |
| C12a | syn-hr-benefits | High | 0.53 | yes | a, b `log_rotation_stopped`; d false | confirmed |
| C12b | syn-hr-payroll | High | 0.7 | yes | a, b, c `service_account_key_stale`; d false | confirmed |
| C12c | syn-hr-recruiting | High | 0.62 | yes | a, b, c `stale_feature_flag`; d false | confirmed |
| D04 | syn-pay-gateway | none | | no | | unconfirmed |
| D08 | syn-pay-recon | High | 0.38 | yes | none | unconfirmed |
| noise | eight CIs | none | | no | | unconfirmed |

D08 is the expected detection false positive: a problem would be opened, zero signal types fire, and the case is held `rca_unconfirmed`. `noise-syn-hr-time` does not open. Signal (c) alone is `stale_feature_flag`. See Deviations.

History slice: 98 incidents, 8 candidates, precision 0.875. C02 and C07 do not open (`history_peak` 2, n 3). On that slice C11 has d true. The full world is the one that matters, and there C11 has d false.

`four_of_five`: 106 incidents, 8 candidates, precision 0.875. It also does not open C02 or C07.

## Architecture edits

These are the edits in `docs/architecture/END_TO_END_ITSM.md` for the other repository. Detection-trigger, circuit-breaker, and kill-switch lines were not changed.

Path 5, old:

```
Verification fails → rollback → new incident linked to the change → the same problem is reopened, attempt counter incremented | Second attempt succeeds, or held (`fix_attempts_exhausted`)
```

Path 5, new:

```
Verification fails → rollback → new incident with `u_caused_by` linked to the same problem → the problem is reopened. Error control does not resubmit a catalog entry that already failed for this problem | When another catalog entry matches the mechanism and CI class, a later attempt can use it. When none does, the case is held (`fix_failed_no_alternative`). The policy limit stays at two attempts
```

Path 6, old:

```
A cluster below threshold opens nothing; a confirmed problem with no catalog fix, or whose fix scores too risky, stays a known error | Known error published, no change
```

Path 6, new:

```
A burst below the count of 5 opens nothing. An eight-ticket decoy with dissimilar causes can score High under the unmodified detection rule: a problem is opened and zero signal types fire. A confirmed problem with no catalog fix, or whose fix scores too risky, stays a known error | The four-ticket burst opens nothing. The eight-ticket decoy is held (`rca_unconfirmed`), with no known error and no change, and ground truth records it as an expected detection false positive. Detection precision is reported as measured. A confirmed problem with no catalog entry ends as a known error
```

Section 6.4, Path 5 loop, old:

```
ends at `fix_attempts_exhausted` after two attempts.
```

Section 6.4, Path 5 loop, new:

```
a failed fix rolls back, links the caused-by incident, and reopens the problem. Error control does not resubmit a catalog entry that already failed for this problem. When no other catalog entry matches the mechanism and CI class, the case is held (`fix_failed_no_alternative`). The policy limit stays at two attempts.
```

Section 9.1, incident streams, old:

```
one decoy burst
```

Section 9.1, incident streams, new:

```
an eight-ticket decoy with dissimilar causes, a four-ticket burst below the count of 5, and noise that must not cluster.
```

E05, old:

```
Rollback, incident with `u_caused_by`, same problem reopened, second attempt or `fix_attempts_exhausted`
```

E05, new:

```
Unsuccessful close code, verified rollback, caused-by incident with `u_caused_by` on the same problem, problem reopened, hold `fix_failed_no_alternative`, exactly one change
```

E06, old:

```
Decoy opens no problem; a problem with no catalog entry ends as a known error
```

E06, new:

```
The four-ticket burst opens nothing. The eight-ticket decoy becomes a High candidate, a problem is opened, zero signal types fire, and the case is held (`rca_unconfirmed`) with no known error and no change. Ground truth records that decoy as an expected detection false positive, and detection precision is reported as measured. A confirmed problem with no catalog entry ends as a known error
```

Section 10, phase 1 gate, old:

```
`teardown → seed` twice; counts match ground truth; customer-update check shows no new type
```

Section 10, phase 1 gate, new:

```
`teardown → seed` twice; counts match ground truth; customer-update check shows no orphan; `endpoint` is the approved new category
```

## Gate

Command, from this repository, with `UV_PROJECT_ENVIRONMENT` set to `%LOCALAPPDATA%\venvs\itsm-e2e-agents`:

```
uv run e2e gate
```

Exit 0. The opening teardown cleared the partial seed from the earlier attempt. Counts after seed 1, seed 2, and the reseed without teardown were the same:

```
incidents=101 problems=1 articles=1 changes=0 endpoint_definitions=1 endpoint_operations=2
```

The change seed stayed `SYN-CHG-=1500`, `SYN-INC-=164`, `syn-ci=296`.

Seed 1 reimported 44 incidents after the active count settled at 44. Seed 2 reimported 8. The reseed imported 0, skipped 101, and reimported none. The C01 parent fallback did not run. E01 was created on the fresh seeds and reused on the reseed. `publish_article` read `workflow_state=published`.

Authority probe:

```
approval negative change status=403 state=requested
approval negative incident status=404 state=requested
approval negative problem status=200 state=requested
approval authority wanted=-3 read=-3
approval authority wanted=-2 read=-2
approval probe: scheduled=-2 creator_is_change_user=true creator_is_authority=false approved_rows=2
```

The authority user has no direct role. The probe would have stopped if that count were not zero. The probe change was deleted.

Known-error probe, also written under `## Known error close code` in `docs/DISCOVERY.md`:

```
known error close code: parent_stuck=true close_write=403 close_stuck=false result=refused
gate probe residue: {'incidents': 0, 'problems': 0, 'changes': 0, 'articles': 0}
```

Customer updates:

```
update_xml rows=1237
update_xml hand_made=3
update_xml approved=2
update_xml endpoint=27
update_xml manifest=1202
update_xml platform=3
update_xml orphan=0
```

Both approved names are present: `change.conflict.ci_maint_sched` and `Global Infrastructure condition`. The endpoint category is `syne2e_problem_state`. The 27 endpoint rows include customer updates from earlier installs whose records were removed. The live count is one definition and two operations. Created-by on the printed rows was `admin`.

`e2e doctor` (exit 0):

```
pins: match
admin login: ok
instance build: glide.buildname and glide.buildtag were not found; glide.war=glide-australia-02-11-2026__patch3-05-25-2026_06-12-2026_1106.zip
email: off
change seed: SYN-CHG-=1500 SYN-INC-=164 syn-ci=296
change agent login: ok
incident user login: ok
problem user login: ok
authority user login: ok
doctor: ok
```

`cm-agents doctor` exited 0. Its login line was redacted. `python -m pytest -m live tests/live/test_s09.py -q` from ChangeManagementAgent:

```
1 passed in 50.16s
```

The gate then printed `gate: pass`.

## Deviations

- `noise-syn-hr-time` gets signal (c) `stale_feature_flag` and no other signal. It does not open a candidate. The mapped in-window change is `SYN-CHG-0108` on `syn-hr-time`, closed `2026-10-13 17:00:00`, summary `SYN reload feature flag snapshot`. Other closed changes on that CI in the window are unmapped. This is a measured side effect, not a detection bug.
- Publishing the E01 known error makes the platform add a known-error work note on matching history incidents and set `active` true and priority 4. A Table API write does not clear `active` after that. The seed sends `incident_state` 6, waits until the active count stays still, and posts those rows again through the import set with business rules off. The work notes stay. Detection reads `short_description`.
- On this PDI a password with no special character is accepted on create (HTTP 200) and then fails login with HTTP 401. `glide.enable.password_policy` is true. The same note is in `docs/DISCOVERY.md` and `.env.example`.
- Close code `Known error` is still refused (HTTP 403) when the probe incident's parent is the seeded E01 problem. The probe incident was created and deleted. History stays on `Solution provided` and state Resolved (6).
- The problem user's negative approval returned HTTP 200. The approval row stayed `requested`, which is what the probe requires.
- `snc_basic_auth_api_access` was not granted.

## Open questions

The problem user's approval write returned HTTP 200 and did not change the row. The change user received HTTP 403. The incident user received HTTP 404. All three left the row `requested`.

Close code `Known error` stays refused for an incident whose parent is the seeded known-error problem. Phase 0 recorded the same 403 without that parent.

Three customer updates are platform rows, not seed records: `glide.db.instant_alter.enabled` (written when tables were created, `2026-10-21`), `taxonomy.category.new_content_job_last_run` (updated `2026-11-15 08:00:50`), and `Service-Desk Password Reset for Local ServiceNow` (updated `2026-11-16 08:00:42`). They are classified `platform` so the orphan count can stay 0. They are not the two approved settings.

## Risks

- The known-error update keeps marking incidents active for a few minutes after import, then stops. The seed waits until that count is unchanged for 45 seconds, then reimports. A later wave would leave rows active and the next seed's check would fail.
- Change-seed and `SYN-PROBE` customer updates whose sys_ids were not kept are classified as manifest by name. A new row that uses those names would not be an orphan. Any other new name still is.
- Reimported incidents can keep the platform work note. Later phases that read work notes will see it.
- The C01 parent fallback did not run on this gate. It remains in the seed for an import that leaves those parents empty.
- E05 is in ground truth. The runner that performs the failed fix is Phase 5. The circuit breaker is not built in this phase. No `var/autonomy.json` and no `var/sim_state.json` were created.
