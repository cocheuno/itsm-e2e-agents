# Phase 0

The Phase 0 gate did not pass. `e2e doctor` exited 0. `e2e discover` exited 1 because the problem state walk is **partial**. Every SYN-PROBE residue count was 0. The Scripted REST endpoint was not installed. This commit records the scaffold, the probes, and that result.

## Fork and settings

`git -C ..\pm-agent-e2e remote -v`

```
origin	https://github.com/cocheuno/pm-agent.git (fetch)
origin	https://github.com/cocheuno/pm-agent.git (push)
```

`git -C ..\pm-agent-e2e rev-parse HEAD` is `5a8c995c3c9a92221716859f5ca17fe1e5c2ec04`. The local branch is `e2e`, with no upstream. There is no `evebrin/pm-agent` remote. `../pm-agent` was not read or changed for this build.

All thirteen `.env` names are present and non-empty. None are missing: `SN_INSTANCE_URL`, `SN_ADMIN_USER`, `SN_ADMIN_PASSWORD`, `SN_AGENT_USER`, `SN_AGENT_PASSWORD`, `SN_INCIDENT_USER`, `SN_INCIDENT_PASSWORD`, `SN_PROBLEM_USER`, `SN_PROBLEM_PASSWORD`, `SN_AUTHORITY_USER`, `SN_AUTHORITY_PASSWORD`, `XAI_API_KEY`, `XAI_MODEL`. The URL matched `^https://dev\d+\.service-now\.com$` and its length is 33. Values are not printed here.

## Python and pins

`uv run python -V` reported `Python 3.13.2`. uv used `C:\Users\caronet\AppData\Local\Programs\Python\Python313\python.exe` and created the environment at `%LOCALAPPDATA%\venvs\itsm-e2e-agents`. No `.venv` was created inside a repository.

| Checkout | Pinned commit |
|---|---|
| ChangeManagementAgent | `811e8fd6e4969ebabedd48aa37e593fe8b24b281` |
| itscm-451z-agent | `c5cc1856ff1d9d4440185f7a12fc753493507369` |
| pm-agent-e2e | `5a8c995c3c9a92221716859f5ca17fe1e5c2ec04` |

`e2e doctor` printed `pins: match`.

## Files changed

Only this repository changed. `../pm-agent-e2e` has no file changes, so it has no commit. `../itscm-451z-agent` and `../ChangeManagementAgent` were not modified. `../pm-agent` was not used.

This commit adds the package `e2e` (`doctor`, `discover`, settings, pins, contracts, CLI), `tests/unit`, `config/pins.json`, `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore`, `docs/DISCOVERY.md`, `docs/ASSUMPTIONS.md`, and this report. The architecture and the prompts were already in the working tree and are included.

## Cross-repository proposal

`pyproject.toml` depends on `cm-agents` with `[tool.uv.sources] cm-agents = { path = "../ChangeManagementAgent" }`. Phase 2 adds `../itscm-451z-agent` after packaging on `e2e-incident`. Phase 3 adds `../pm-agent-e2e` after a minimal `pyproject.toml` on branch `e2e`. Path sources do not pin commits, so `config/pins.json` is the pin and doctor checks it. Nothing uses an absolute path or a user name.

## Gate

### `e2e doctor` (exit 0)

```
pins: match
admin login: ok
instance build: glide.buildname and glide.buildtag were not found; glide.war=glide-australia-02-11-2026__patch3-05-25-2026_06-12-2026_1106.zip
email: off
change seed: SYN-CHG-=1500 SYN-INC-=164 syn-ci=296
change agent login: ok
incident user: absent
problem user: absent
authority user: absent
doctor: ok
```

The three Phase 1 users are absent. That does not fail doctor.

### `e2e discover` (exit 1)

The second run used the General model's real edges (`sttrm_state.sttrm_model`, transitions on `from_state` / `to_state`). Printed results:

```
glide.email.smtp.active is false and no active email account exists.
choices incident.state: 1=New, 2=In Progress, 3=On Hold, 6=Resolved, 7=Closed, 8=Canceled
choices incident.close_code: Resolved by request, No resolution provided, Solution provided, Resolved by caller, Workaround provided, Duplicate, Resolved by change, User error, Known error, Resolved by problem
choices problem.state: 101=New, 103=Root Cause Analysis, 107=Closed, 102=Assess, 106=Resolved, 104=Fix in Progress
choices problem.resolution_code: canceled=Canceled, duplicate=Duplicate, fix_applied=Fix Applied, risk_accepted=Risk Accepted
choices problem.close_code: none
probe user syn.probe.approver: login=ok
probe user syn.probe.incident: login=ok
probe user syn.probe.problem: login=ok
approval: assess=-4 authorize=-3 scheduled=-2 roles=none
role problem_coordinator granted
parent: linked=True status=200 listed=1
rfc: stuck=False status=200
problem.state: path=5 moved=1 last_status=200 102->103 read=102
knowledge: workflow_state=draft status=200
roles: authority=[] problem=['problem_coordinator'] knowledge=[] incident=[]
SYN-PROBE residue:
  change_request: 0
  change_task: 0
  incident: 0
  problem: 0
  kb_knowledge: 0
  task_ci: 0
  sysapproval_approver: 0
  sysapproval_group: 0
  sys_user: 0
  sys_user_grmember: 0
  sys_user_has_role: 0
wrote DISCOVERY.md
states: not verified
```

Problem create returned HTTP 403, then succeeded after `problem_coordinator`. Assess to Root Cause Analysis returned HTTP 200 and read back 102. The client log for the rest of the run is HTTP 200 or 201, plus one HTTP 404 while deleting a group membership that was already gone. Trimmed evidence is in `docs/DISCOVERY.md`.

A follow-up, after discover had deleted its rows, moved one admin-owned SYN-PROBE problem. New to Assess stuck when `assigned_to` was set. Assess to Root Cause Analysis stayed on 102, including a write that also sent `cause_notes` and `workaround`. The problem was deleted. A leftover query returned 0.

### This repository

With `UV_PROJECT_ENVIRONMENT` set to `%LOCALAPPDATA%\venvs\itsm-e2e-agents`:

```
uv run ruff check e2e tests
All checks passed!

uv run pytest -q --tb=short
22 passed in 2.54s
```

### ChangeManagementAgent

From `../ChangeManagementAgent`, with `UV_PROJECT_ENVIRONMENT` set to `%LOCALAPPDATA%\venvs\ChangeManagementAgent`:

```
uv run pytest -m "not live" -q --tb=line
174 passed, 14 deselected in 60.38s
```

### itscm-451z-agent

From `../itscm-451z-agent`, with Python from `%LOCALAPPDATA%\venvs\itscm-451z-agent` after `pip install -r requirements.txt` into that environment:

```
python -m pytest -q --tb=line
98 passed, 5 skipped, 7 warnings in 23.24s
```

### pm-agent-e2e

From `../pm-agent-e2e`, with Python from `%LOCALAPPDATA%\venvs\pm-agent-e2e`:

```
python -m unittest discover tests
Ran 17 tests in 0.043s
OK
```

The in-repo `.venv` under `../pm-agent` was not used.

## Section 8

| Row | Decision |
|---|---|
| `incident.u_caused_by` | verified. Reference to `change_request`, not read-only. |
| `incident.problem_id` | absent |
| non-admin approval | verified. No direct role. Change reached Scheduled (`-2`). |
| `incident.parent` | verified |
| `problem.rfc` | verified |
| `problem.state` Table API | **partial**. New (101) to Assess (102) stuck with `assigned_to`. Assess (102) to Root Cause Analysis (103) did not, including as admin. |
| Known Error publish | **approved-fallback**. Create succeeded. Publish stayed `draft`. |
| least roles | The discover decision is **failed** because the state probe is partial. The observed grants are incident none, problem `problem_coordinator`, knowledge none, authority none. |
| choice values | verified. `problem.close_code` has no rows. |

## Deviations

- The pm-agent sibling in this build is `../pm-agent-e2e`, not `../pm-agent`.
- Settings are the thirteen names above.
- The imported change commit is `811e8fd`, later than the architecture's `9450f95`.
- The first discover run queried `sttrm_state_transition` with `from` and `to`. Those columns are `from_state` and `to_state`. That run only attempted Assess. The second run walked the model and is the one recorded above.
- The generated Section 8 line for a partial state walk said the Scripted REST fallback was approved. The code and `docs/DISCOVERY.md` now say a partial walk is not that fallback. The evidence JSON is from the second run.
- Catalog plans are copied byte for byte. `cm_agents` still prepends `Deployment method:` unless the catalog text already starts with that line. That is a Phase 3 constraint. ChangeManagementAgent was not edited.

## Open question

The Table API moves New to Assess when `assigned_to` is in the same write. It does not move Assess to Root Cause Analysis. Admin could not move that edge either. Because one edge stuck and the next did not, the decision is partial, not the approved Scripted REST fallback.

Separately, Known Error publish returned HTTP 200 and stayed `draft`. That row's approved fallback is `publish_article` on the same endpoint. It was not installed. No knowledge role was added, because the response was not HTTP 403.

Should the pm-agent Scripted REST endpoint be installed so later problem states can move and so a Known Error article can be published? It will not be installed unless you say yes.

## Risks

- `problem.resolution_code` is read-only. Close edges that were read depend on it. Those edges were not attempted.
- Incident resolve and close were not probed. The empty incident role set is only proved for create.
- A fix-catalog plan that does not already start with `Deployment method:` will be rewritten by change intake.
- Path dependencies follow whatever commit is checked out. Doctor compares that commit with `config/pins.json`.
