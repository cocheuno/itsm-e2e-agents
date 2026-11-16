# Phase 0

The Phase 0 gate passed on the final `e2e discover` (exit 0). `e2e doctor` exited 0. Every SYN-PROBE count was 0, every `SYN-E2E-PROBE` count was 0, and the Scripted REST endpoint was gone. The earlier discover in this repository, before this review, exited 1 because the Table API state walk was partial. That partial result is still true. This run is the one the gate uses.

## Fork and settings

`git -C ..\pm-agent-e2e remote -v`

```
origin	https://github.com/cocheuno/pm-agent.git (fetch)
origin	https://github.com/cocheuno/pm-agent.git (push)
```

`git -C ..\pm-agent-e2e rev-parse HEAD` is `5a8c995c3c9a92221716859f5ca17fe1e5c2ec04`. The local branch is `e2e`, with no upstream. There is no `evebrin/pm-agent` remote. `../pm-agent` was not read or changed for this build. The fork's `state_api.py` was not run and was not edited. This repository has its own adapted copy.

All thirteen `.env` names are present and non-empty. None are missing: `SN_INSTANCE_URL`, `SN_ADMIN_USER`, `SN_ADMIN_PASSWORD`, `SN_AGENT_USER`, `SN_AGENT_PASSWORD`, `SN_INCIDENT_USER`, `SN_INCIDENT_PASSWORD`, `SN_PROBLEM_USER`, `SN_PROBLEM_PASSWORD`, `SN_AUTHORITY_USER`, `SN_AUTHORITY_PASSWORD`, `XAI_API_KEY`, `XAI_MODEL`. The URL matched `^https://dev\d+\.service-now\.com$` and its length is 33. Values are not printed here.

## Python and pins

`uv run python -V` reported `Python 3.13.2`. uv used `C:\Users\caronet\AppData\Local\Programs\Python\Python313\python.exe` and the environment at `%LOCALAPPDATA%\venvs\itsm-e2e-agents`. No `.venv` was created inside a repository.

| Checkout | Pinned commit |
|---|---|
| ChangeManagementAgent | `811e8fd6e4969ebabedd48aa37e593fe8b24b281` |
| itscm-451z-agent | `c5cc1856ff1d9d4440185f7a12fc753493507369` |
| pm-agent-e2e | `5a8c995c3c9a92221716859f5ca17fe1e5c2ec04` |

`e2e doctor` printed `pins: match`.

## Files changed

Only this repository changed. `../pm-agent-e2e` has no file changes, so it has no commit. `../itscm-451z-agent` and `../ChangeManagementAgent` were not modified. `../pm-agent` was not used.

This phase adds `e2e/state_api.py` and extends discovery, the gate, `docs/DISCOVERY.md`, `docs/ASSUMPTIONS.md`, and this report.

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

### `e2e discover` (exit 0)

Printed results from the passing run:

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
approval: assess=-4 authorize=-3 scheduled=-2 roles=none direct=0 web_service_access_only=true groups=Conditional Script Writer,Change Management,CAB Approval
role problem_coordinator granted
parent: linked=True status=200 listed=1
rfc: stuck=False status=200
problem.state: path=5 moved=1 last_status=200 102->103 read=102
knowledge: workflow_state=draft status=200
problem_state write: 101->102 status=200 read_state=102 read_problem_state=102
problem_state write: 102->103 status=200 read_state=102 read_problem_state=102
problem_state: present path=5 moved=1 decision=failed
endpoint install: operations=move,publish_article
endpoint move: 101->102 status=200 read_state=102
endpoint move: 102->103 status=200 read_state=103
endpoint move: 103->104 status=200 read_state=104
endpoint move: 104->106 status=409 read_state=106
endpoint move: 106->107 status=200 read_state=107
endpoint publish: status=200 workflow_state=published
endpoint: move=verified publish=verified
role sn_incident_write granted
incident_writes: stuck=none roles=['sn_incident_write']
problem_writes: stuck=none roles=['problem_coordinator']
roles: authority=[] problem=['problem_coordinator'] knowledge=[] incident=['sn_incident_write']
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
  problem SYN-E2E-PROBE: 0 query=correlation_idSTARTSWITHSYN-E2E-PROBE^ORshort_descriptionSTARTSWITHSYN-E2E-PROBE
  incident SYN-E2E-PROBE: 0 query=correlation_idSTARTSWITHSYN-E2E-PROBE^ORshort_descriptionSTARTSWITHSYN-E2E-PROBE
  kb_knowledge SYN-E2E-PROBE: 0 query=short_descriptionSTARTSWITHSYN-E2E-PROBE
  sys_ws_definition: 0 query=service_id=syne2e_problem_state
  sys_ws_operation: 0 query=web_service_definition.service_id=syne2e_problem_state
wrote DISCOVERY.md
```

`problem.problem_state` is present (integer, active, not read-only). The problem user wrote it. New to Assess read back state `102`. Assess to Root Cause Analysis returned HTTP 200 and read back state `102` and `problem_state` `102`, including the retry that also sent `assigned_to`, `cause_notes`, `fix_notes`, `close_notes`, and `resolution_code`. Both operations were installed after that result.

The move operation then read state `102`, `103`, `104`, `106`, and `107`. The `104` to `106` call returned HTTP 409 with no extra fields. The retry sent the fuller field set, returned HTTP 200, and read back `106`. `publish_article` returned HTTP 200 and the article read back `workflow_state=published`. Cleanup deleted both operations and the definition. The queries above are the proof that nothing remains.

The approval user had `direct_role_count=0` and `web_service_access_only=true`. The probe inserted Change Management and CAB Approval. The membership query also returned Conditional Script Writer.

Incident create needed no role. On an incident that user did not create, category, assignment group, parent, and a comment stuck with no role. Impact and urgency stuck after `sn_incident_write`. Work notes stuck with that role. Close code `Known error` returned HTTP 403 for that user and for admin, aborted by business rule `Check if Known error article required`. Close code `Solution provided` then read back state `6` with only `sn_incident_write`. `itil` was not granted.

The problem user's known-error fields, article reference, incident parent, and incident work note stuck with `problem_coordinator`. No knowledge role was added.

### This repository

With `UV_PROJECT_ENVIRONMENT` set to `%LOCALAPPDATA%\venvs\itsm-e2e-agents`:

```
uv run ruff check e2e tests
All checks passed!

uv run pytest -q --tb=short
25 passed in 1.60s
```

### ChangeManagementAgent

From `../ChangeManagementAgent`, with `UV_PROJECT_ENVIRONMENT` set to `%LOCALAPPDATA%\venvs\ChangeManagementAgent`:

```
uv run pytest -m "not live" -q --tb=line
174 passed, 14 deselected in 55.71s
```

### itscm-451z-agent

From `../itscm-451z-agent`, with Python from `%LOCALAPPDATA%\venvs\itscm-451z-agent`:

```
python -m pytest -q --tb=line
98 passed, 5 skipped, 7 warnings in 10.85s
```

### pm-agent-e2e

From `../pm-agent-e2e`, with Python from `%LOCALAPPDATA%\venvs\pm-agent-e2e`:

```
python -m unittest discover tests
Ran 17 tests in 0.037s
OK
```

The in-repo `.venv` under `../pm-agent` was not used. These three suites do not import this repository. They were run in this session and their trees were not edited.

## Section 8

| Row | Decision |
|---|---|
| `incident.u_caused_by` | verified. Reference to `change_request`, not read-only. |
| `incident.problem_id` | absent |
| non-admin approval | verified. No direct role. `web_service_access_only=true`. Change reached Scheduled (`-2`). |
| `incident.parent` | verified |
| `problem.rfc` | verified |
| `problem.state` Table API | **partial**. New to Assess stuck with `assigned_to`. Assess to Root Cause Analysis read back 102. |
| `problem.problem_state` | **failed**. The field exists. Writing it did not move Assess to Root Cause Analysis. |
| endpoint | **verified**. `move` and `publish_article` were installed, used by the problem user, and removed. |
| Known Error publish | **approved-fallback** for the Table API. `publish_article` published the tagged article and was then removed. |
| incident writes | verified. `sn_incident_write` on an incident this user did not create. |
| problem writes | verified. `problem_coordinator`. |
| least roles | verified. Incident `sn_incident_write`. Problem `problem_coordinator`. Knowledge none. Authority none. |
| choice values | verified. `problem.close_code` has no rows. |

## Deviations

- The pm-agent sibling in this build is `../pm-agent-e2e`, not `../pm-agent`.
- Settings are the thirteen names above.
- The imported change commit is `811e8fd`, later than the architecture's `9450f95`.
- The first discover run queried `sttrm_state_transition` with `from` and `to`. Those columns are `from_state` and `to_state`. The walk recorded above uses the real columns.
- A partial Table API state walk is not the approved fallback. The approved change is the adapted endpoint, installed by the probe and removed before this phase ended.
- Catalog plans are copied byte for byte. `cm_agents` still prepends `Deployment method:` unless the catalog text already starts with that line. That is a Phase 3 constraint. ChangeManagementAgent was not edited.
- Two discover runs in this review exited 1. The first stopped on the incident writes that returned HTTP 200 and did not stick. The second granted `itil` because close code `Known error` returned HTTP 403. That 403 is the business rule, and admin received it too. The passing run does not grant `itil`. It resolves with `Solution provided`.

## Open question

The approval user's membership query listed Conditional Script Writer in addition to the two groups the probe inserted. No direct role was required for the approval.

## Risks

- Close code `Known error` does not resolve an incident on this PDI unless the business rule is satisfied. `Solution provided` does.
- `problem.resolution_code` is read-only through the Table API. The endpoint can set it. The Fix in Progress to Resolved hop needed that fuller field set.
- A fix-catalog plan that does not already start with `Deployment method:` will be rewritten by change intake.
- Path dependencies follow whatever commit is checked out. Doctor compares that commit with `config/pins.json`.
- From Phase 1, seed must install this endpoint and teardown must remove it. Those commands are not implemented in this phase. The endpoint is not installed now.
