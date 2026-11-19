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

## The one approved instance change

The Scripted REST endpoint in `e2e/state_api.py` is the one approved instance change. It evaluates the problem state model, requires `problem_coordinator` for a move, and writes only `cause_notes`, `workaround`, `fix_notes`, `close_notes`, `resolution_code`, and `assigned_to`. It accepts `correlation_id` or `short_description` values that start with `E2E-`. It refuses every other record, including `PMSYNTH`.

The known-error cutoff was set from two labelled pairs before any live tick. The same-CI condition does most of the work.

Do not run a `cm-agents` scenario while an end-to-end scenario is in progress, because its clean-up would delete that scenario's change.

Phase 0 installed it as admin for the probe and removed it before the phase ended. From Phase 1, `e2e seed` installs it, records it in the manifest and the config history, and `e2e teardown` removes it.

The probe installed both operations because writing `problem_state` did not reach Closed. `move` walked a `SYN-E2E-PROBE` problem through 102, 103, 104, 106, and 107. `publish_article` published one tagged Known Error article. The residue queries then showed `sys_ws_definition` 0 for `service_id=syne2e_problem_state` and `sys_ws_operation` 0 for `web_service_definition.service_id=syne2e_problem_state`.

## Role sets from the probes

Grants were added one role at a time. `snc_basic_auth_api_access` is reserved for a probe user who cannot log in. That role was not needed. `admin` was not granted. `sn_change_write` was not granted.

- Incident create succeeded with no direct role.
- On an incident this user did not create, category, assignment group, parent, and a comment stuck with no role. Impact and urgency did not both stick until `sn_incident_write`. Work notes then stuck with that same role. `itil` was not required.
- Resolve with close code `Known error` returned HTTP 403 for the incident user and for admin. The business rule is `Check if Known error article required`. The same user, still with only `sn_incident_write`, resolved the incident to state `6` with close code `Solution provided`.
- Reading the published known-error article and the problem it points at needed one more role. `problem_task_analyst` is that role. `itil` was not added. The tick uses the incident user for those reads. Admin is not used at run time.
- Problem create, `incident.parent`, `problem.rfc`, known error, `primary_known_error_article`, and the incident link (parent plus a work note) succeeded with `problem_coordinator`. `itil` was not added.
- Table API article publish returned HTTP 200 and stayed `draft`, so `knowledge`, `sn_km_contribute`, and `knowledge_admin` were not added. `publish_article` published the tagged article with `problem_coordinator` only.
- The authority probe had no direct role (`direct_role_count=0`) and `web_service_access_only=true`. The probe inserted Change Management and CAB Approval. The membership read-back also listed Conditional Script Writer. `approver_user`, `sn_change_read`, and `itil` were not added.

## Problem state

`problem.state` has no `sys_dictionary` row. `task.state` is an integer and is not read-only. `problem.problem_state` exists on `problem`: integer, active, not read-only.

The Table API `state` walk is **partial**. New to Assess stuck when `assigned_to` was in the same write. Assess to Root Cause Analysis returned HTTP 200 and read back 102.

Writing `problem_state` instead of `state` had the same result. New to Assess read back state 102 and `problem_state` 102. Assess to Root Cause Analysis returned HTTP 200 with state 102 and `problem_state` 102, including a retry that sent `assigned_to`, `cause_notes`, `fix_notes`, `close_notes`, and `resolution_code`. That walk is **failed**. It is why both endpoint operations were installed for the probe.

`problem.resolution_code` is read-only through the Table API. The endpoint's allow-list still sets it. The move from Fix in Progress to Resolved returned HTTP 409 with no extra fields, then HTTP 200 after the fuller field set, and state read back 106. Resolved to Closed then read back 107 with no extra fields.

## Known Error publish

An active knowledge base titled Known Error exists. The problem user created a `kb_knowledge` article. `PATCH workflow_state=published` returned HTTP 200 and the body stayed `draft`. Decision for that Table API write: **approved-fallback**.

`publish_article` then returned HTTP 200 and the article read back `published`. The endpoint was removed before the phase ended.

## Links

`incident.u_caused_by` references `change_request` and is not read-only. `incident.problem_id` is absent. `incident.state` has no dictionary row on `incident`. `incident.incident_state` is an integer and is not read-only; the resolve that stuck wrote `state`, not `incident_state`. `incident.parent` read back as the problem. `problem.rfc` read back as the change. No custom field was created.

## Catalog text

`intake_request_from_catalog` copies `implementation_plan`, `backout_plan`, and `test_plan` byte for byte and does not prepend `Deployment method:`. `cm_agents` intake adds that line unless the text already starts with it. Catalog entries have to satisfy that themselves if a later phase compares the stored change field. ChangeManagementAgent is not edited for this.

## Approval

A non-admin probe user approved its own `sysapproval_approver` rows through the Table API. The normal change moved from Assess (`-4`) to Authorize (`-3`) to Scheduled (`-2`). The user had no direct role and `web_service_access_only=true`. Scripted approval is not a fallback.

## Detection grouping

End-to-end incidents leave `business_service` empty so detection groups by CI. The fork also groups by `business_service` when that field is non-empty. The change still takes its service from the existing CI row in the change fixtures.

## Fix plans

The fix catalog supplies every plan. The agents do not write a free-form implementation plan, backout plan, or test plan.
