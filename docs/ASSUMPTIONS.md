# Assumptions

Phase 0 recorded these on this PDI. Later phases use them until a newer probe replaces them.

## Settings

The orchestrator reads thirteen names from `.env`: `SN_INSTANCE_URL`, `SN_ADMIN_USER`, `SN_ADMIN_PASSWORD`, `SN_AGENT_USER`, `SN_AGENT_PASSWORD`, `SN_INCIDENT_USER`, `SN_INCIDENT_PASSWORD`, `SN_PROBLEM_USER`, `SN_PROBLEM_PASSWORD`, `SN_AUTHORITY_USER`, `SN_AUTHORITY_PASSWORD`, `XAI_API_KEY`, and `XAI_MODEL`. Values are not committed and are not logged. The instance URL must match `^https://dev\d+\.service-now\.com$`.

## Interpreter and pins

`uv` selected CPython 3.13.2 for this repository. `requires-python` stays `>=3.12`. The three sibling checkouts are pinned in `config/pins.json` because a uv path source does not pin a commit. `e2e doctor` fails when a checkout differs. The imported ChangeManagementAgent commit is `811e8fd6e4969ebabedd48aa37e593fe8b24b281`, which is later than the architecture's `9450f95`.

## Where the fork lives

The master prompt's pm-agent sibling is `../pm-agent-e2e`. Its origin is `https://github.com/cocheuno/pm-agent.git`. Work stays on the local branch `e2e`. `../pm-agent` is not used. `evebrin/pm-agent` is not a push remote.

## Cross-repository layout

Phase 0 depends on `cm-agents` by path: `../ChangeManagementAgent`. Phase 2 adds `../itscm-451z-agent` after that repository is packaged on `e2e-incident`. Phase 3 adds `../pm-agent-e2e` after a minimal `pyproject.toml` lands on `e2e`. No absolute paths.

## Role sets from the probes

Grants were added only after HTTP 403, except that `snc_basic_auth_api_access` is reserved for a probe user who cannot log in. That role was not needed. `admin` was not granted.

- Incident create succeeded with no direct role. Resolve and close were not probed. A later 403 can add `sn_incident_write`, then `itil` only if the write is still 403.
- Problem create, `incident.parent`, `problem.rfc`, the New to Assess move, and Known Error create succeeded with `problem_coordinator`.
- Knowledge publish returned HTTP 200 and did not stick, so `knowledge`, `sn_km_contribute`, and `knowledge_admin` were not added.
- The authority probe approved with no direct role. Membership in Change Management and CAB Approval, looked up by name, was enough. `approver_user`, `sn_change_read`, and `itil` were not added. `sn_change_write` was not granted.

## Problem state

`problem.state` has no `sys_dictionary` row. `task.state` is an integer and is not read-only. The General model requires `assigned_to` on New to Assess. That move stuck only when `assigned_to` was in the same Table API write.

Assess to Root Cause Analysis has no condition row. The Table API did not move it. Admin could not move it either, with or without `cause_notes` and `workaround`. The walk stopped there, so the decision is **partial**. That is not the approved Scripted REST fallback. The endpoint is not installed.

Later edges, not attempted, require `cause_notes` and `fix_notes` to enter Fix in Progress, and `cause_notes` and `close_notes` to enter Resolved from Root Cause Analysis. `problem.resolution_code` is read-only. The close edges that were read depend on `resolution_code`.

## Known Error publish

An active knowledge base titled Known Error exists. The problem user created a `kb_knowledge` article. `PATCH workflow_state=published` returned HTTP 200 and the body stayed `draft`. Decision: **approved-fallback**. `publish_article` is not installed.

## Links

`incident.u_caused_by` references `change_request` and is not read-only. `incident.problem_id` is absent. `incident.parent` read back as the problem. `problem.rfc` read back as the change. No custom field was created.

## Catalog text

`intake_request_from_catalog` copies `implementation_plan`, `backout_plan`, and `test_plan` byte for byte and does not prepend `Deployment method:`. `cm_agents` intake adds that line unless the text already starts with it. Catalog entries have to satisfy that themselves if a later phase compares the stored change field. ChangeManagementAgent is not edited for this.

## Approval

A non-admin probe user approved its own `sysapproval_approver` rows through the Table API. The normal change moved from Assess (`-4`) to Authorize (`-3`) to Scheduled (`-2`). Scripted approval is not a fallback.
