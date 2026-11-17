# Discovery

Phase 0 probes for the end-to-end workflow. API paths are relative to the instance. Secrets and the instance host are omitted. Probe rows use the SYN-PROBE marker and are deleted before the command returns.

## Email gate

glide.email.smtp.active is false and no active email account exists.

## Dictionary

- `incident.u_caused_by`: [{'internal_type': 'reference', 'reference': 'change_request', 'read_only': 'false', 'active': 'true'}]
- `incident.problem_id`: []
- `incident.rfc`: []
- `incident.state`: []
- `incident.incident_state`: [{'internal_type': 'integer', 'reference': '', 'read_only': 'false', 'active': 'true'}]
- `task.problem_id`: []
- `problem.rfc`: [{'internal_type': 'reference', 'reference': 'change_request', 'read_only': 'false', 'active': 'true'}]
- `problem.state`: []
- `problem.problem_state`: [{'internal_type': 'integer', 'reference': '', 'read_only': 'false', 'active': 'true'}]
- `problem.resolution_code`: [{'internal_type': 'choice', 'reference': '', 'read_only': 'true', 'active': 'true'}]
- `problem.known_error`: [{'internal_type': 'boolean', 'reference': '', 'read_only': 'false', 'active': 'true'}]
- `problem.primary_known_error_article`: [{'internal_type': 'reference', 'reference': 'kb_template_known_error_article', 'read_only': 'false', 'active': 'true'}]
- `problem.cause_notes`: [{'internal_type': 'html', 'reference': '', 'read_only': 'false', 'active': 'true'}]
- `problem.fix_notes`: [{'internal_type': 'html', 'reference': '', 'read_only': 'false', 'active': 'true'}]
- `problem.close_notes`: []
- `problem.workaround`: [{'internal_type': 'html', 'reference': '', 'read_only': 'false', 'active': 'true'}]
- `task.state`: [{'internal_type': 'integer', 'reference': '', 'read_only': 'false', 'active': 'true'}]
- `task.parent`: [{'internal_type': 'reference', 'reference': 'task', 'read_only': 'false', 'active': 'true'}]

## Choice values

- `incident.state`: `1` New, `2` In Progress, `3` On Hold, `6` Resolved, `7` Closed, `8` Canceled
- `incident.close_code`: `Resolved by request` Resolved by request, `No resolution provided` No resolution provided, `Solution provided` Solution provided, `Resolved by caller` Resolved by caller, `Workaround provided` Workaround provided, `Duplicate` Duplicate, `Resolved by change` Resolved by change, `User error` User error, `Known error` Known error, `Resolved by problem` Resolved by problem
- `problem.state`: `101` New, `103` Root Cause Analysis, `107` Closed, `102` Assess, `106` Resolved, `104` Fix in Progress
- `problem.resolution_code`: `canceled` Canceled, `duplicate` Duplicate, `fix_applied` Fix Applied, `risk_accepted` Risk Accepted
- `problem.close_code`: no rows

## approval

Can a non-admin group member approve a normal change through the Table API so it advances through Assess and Authorize?

Calls:

- `POST /api/now/table/sys_user_grmember group=Change Management`
- `POST /api/now/table/sys_user_grmember group=CAB Approval`
- `POST /api/sn_chg_rest/change/normal as the change user`
- `PATCH change_request assignment_group, start_date, end_date`
- `PATCH /api/sn_chg_rest/change/normal/{sys_id} state=-4`
- `PATCH sysapproval_approver state=approved as the probe user`
- `PATCH sysapproval_approver state=approved as the probe user`

Evidence:

```
{
  "groups": {
    "Change Management": true,
    "CAB Approval": true
  },
  "memberships": 2,
  "membership_names": [
    "Conditional Script Writer",
    "Change Management",
    "CAB Approval"
  ],
  "roles": [],
  "direct_roles": [],
  "direct_role_count": 0,
  "web_service_access_only": "true",
  "assess_state": "-4",
  "first": {
    "probe_rows": 1,
    "requested_rows": 6,
    "write_status": 200,
    "row_state": "approved",
    "change_state": "-3",
    "roles": []
  },
  "second": {
    "probe_rows": 1,
    "requested_rows": 12,
    "write_status": 200,
    "row_state": "approved",
    "change_state": "-2",
    "roles": []
  },
  "final_state": "-2",
  "final_approval": "approved",
  "number": "CHG0047172"
}
```

Decision: **verified**. The approval probe user had no direct role (direct_role_count=0). The probe inserted Change Management and CAB Approval. sys_user_grmember read back: Conditional Script Writer, Change Management, CAB Approval. web_service_access_only=true. The change reached Scheduled.

## parent

Does incident.parent point at a problem, read back, and list that incident on the problem?

Calls:

- `POST /api/now/table/incident`
- `POST /api/now/table/problem`
- `PATCH incident parent`

Evidence:

```
{
  "write_status": 200,
  "parent": "1356ef16c3a8d390aef2be1d0501310d",
  "listed": 1,
  "problem_user_sees": 1,
  "incident_roles": [],
  "problem_roles": [
    "problem_coordinator"
  ],
  "close_codes_loaded": 10
}
```

Decision: **verified**. incident.parent read back as the problem, and the parent query returned the incident.

## rfc

Can the problem user set problem.rfc and read it back?

Calls:

- `POST /api/sn_chg_rest/change/normal as the change user`
- `PATCH /api/now/table/problem/{sys_id} rfc`

Evidence:

```
{
  "write_status": 200,
  "returned": "b756ef16c3a8d390aef2be1d05013151",
  "read_back": "b756ef16c3a8d390aef2be1d05013151",
  "stuck": false,
  "dictionary": [
    {
      "internal_type": "reference",
      "reference": "change_request",
      "read_only": "false",
      "active": "true"
    }
  ],
  "roles": [
    "problem_coordinator"
  ]
}
```

Decision: **verified**. problem.rfc read back as the probe change.

## states

Can the problem user move a probe problem through its states with the Table API?

Calls:

- `GET sys_dictionary name=problem^element=state`
- `PATCH /api/now/table/problem/{sys_id} state`

Evidence:

```
{
  "dictionary": [],
  "start": "101",
  "model": "b58c327fb70c021041c2feb0be11a90e",
  "transition_rows": 12,
  "path": [
    "102",
    "103",
    "104",
    "106",
    "107"
  ],
  "attempts": [
    {
      "before": "101",
      "requested": "102",
      "returned": "102",
      "after": "102",
      "status": 200,
      "assignee_retry": 200,
      "role_added": null
    },
    {
      "before": "102",
      "requested": "103",
      "returned": "102",
      "after": "102",
      "status": 200,
      "assignee_retry": 200,
      "role_added": null
    }
  ],
  "roles": [
    "problem_coordinator"
  ]
}
```

Decision: **partial**. The Table API moved some states and stopped. A partial walk is not the approved fallback.

## knowledge

Can the problem user create and publish a Known Error article?

Calls:

- `GET kb_knowledge_base title=Known Error`
- `POST knowledge article as the problem user`
- `PATCH workflow_state=published`

Evidence:

```
{
  "base_count": 1,
  "create": {
    "status": 200,
    "table": "kb_knowledge",
    "sys_id": "02666356c3a8d390aef2be1d0501315a"
  },
  "publish_status": 200,
  "returned_workflow": "draft",
  "workflow_state": "draft",
  "published": "",
  "roles": [
    "problem_coordinator"
  ]
}
```

Decision: **approved-fallback**. The problem user did not publish the article through the Table API. publish_article is the approved fallback. The endpoint probe records it.

## problem_state

Does writing problem_state, with the fields each state requires, move state through every state to Closed?

Calls:

- `GET sys_dictionary name=problem^element=problem_state`
- `PATCH /api/now/table/problem/{sys_id} problem_state`
- `GET /api/now/table/problem/{sys_id} state`

Evidence:

```
{
  "dictionary": [
    {
      "internal_type": "integer",
      "reference": "",
      "read_only": "false",
      "active": "true"
    }
  ],
  "start": "101",
  "path": [
    "102",
    "103",
    "104",
    "106",
    "107"
  ],
  "closed": "107",
  "attempts": [
    {
      "before": "101",
      "requested": "102",
      "fields": [
        "assigned_to"
      ],
      "full": false,
      "status": 200,
      "returned_state": "102",
      "returned_problem_state": "102",
      "after": "102",
      "read_problem_state": "102",
      "error": "",
      "role_added": null
    },
    {
      "before": "102",
      "requested": "103",
      "fields": [],
      "full": false,
      "status": 200,
      "returned_state": "102",
      "returned_problem_state": "102",
      "after": "102",
      "read_problem_state": "102",
      "error": "",
      "role_added": null,
      "retry": {
        "before": "102",
        "requested": "103",
        "fields": [
          "assigned_to",
          "cause_notes",
          "close_notes",
          "fix_notes",
          "resolution_code"
        ],
        "full": true,
        "status": 200,
        "returned_state": "102",
        "returned_problem_state": "102",
        "after": "102",
        "read_problem_state": "102",
        "error": "",
        "role_added": null
      }
    }
  ],
  "roles": [
    "problem_coordinator"
  ]
}
```

Decision: **failed**. Writing problem_state did not move state through every state to Closed. Both endpoint operations are approved.

## endpoint

Can the problem user finish the state walk and publish a Known Error through the temporary endpoint?

Calls:

- `POST sys_ws_definition service_id=syne2e_problem_state`
- `POST the installed operation as the problem user`
- `DELETE sys_ws_operation and sys_ws_definition in cleanup`

Evidence:

```
{
  "operations": [
    "move",
    "publish_article"
  ],
  "base_uri_present": true,
  "install_status": 200,
  "removed": true,
  "move": {
    "decision": "verified",
    "start": "101",
    "path": [
      "102",
      "103",
      "104",
      "106",
      "107"
    ],
    "closed": "107",
    "attempts": [
      {
        "before": "101",
        "requested": "102",
        "fields": [
          "assigned_to"
        ],
        "full": false,
        "status": 200,
        "returned_state": "102",
        "script_ok": true,
        "after": "102",
        "error": "",
        "role_added": null
      },
      {
        "before": "102",
        "requested": "103",
        "fields": [],
        "full": false,
        "status": 200,
        "returned_state": "103",
        "script_ok": true,
        "after": "103",
        "error": "",
        "role_added": null
      },
      {
        "before": "103",
        "requested": "104",
        "fields": [
          "cause_notes",
          "fix_notes"
        ],
        "full": false,
        "status": 200,
        "returned_state": "104",
        "script_ok": true,
        "after": "104",
        "error": "",
        "role_added": null
      },
      {
        "before": "104",
        "requested": "106",
        "fields": [],
        "full": false,
        "status": 409,
        "returned_state": null,
        "script_ok": null,
        "after": "106",
        "error": "ServiceNow returned HTTP 409",
        "role_added": null,
        "retry": {
          "before": "104",
          "requested": "106",
          "fields": [
            "assigned_to",
            "cause_notes",
            "close_notes",
            "fix_notes",
            "resolution_code"
          ],
          "full": true,
          "status": 200,
          "returned_state": "106",
          "script_ok": true,
          "after": "106",
          "error": "",
          "role_added": null
        }
      },
      {
        "before": "106",
        "requested": "107",
        "fields": [],
        "full": false,
        "status": 200,
        "returned_state": "107",
        "script_ok": true,
        "after": "107",
        "error": "",
        "role_added": null
      }
    ],
    "roles": [
      "problem_coordinator"
    ]
  },
  "publish": {
    "decision": "verified",
    "sys_id": "22766756c3a8d390aef2be1d050131d4",
    "create_status": 200,
    "workflow_state": "published",
    "attempts": [
      {
        "status": 200,
        "script_state": "published",
        "script_ok": true,
        "error": "",
        "workflow_state": "published",
        "roles": [
          "problem_coordinator"
        ]
      }
    ],
    "roles": [
      "problem_coordinator"
    ]
  }
}
```

Decision: **verified**. The problem user finished the installed operations. Cleanup removes the endpoint before the phase ends.

## incident_writes

What smallest role set lets the incident user update an incident it did not create: category, priority inputs, assignment group, parent, a comment, and resolve with a close code?

Calls:

- `POST /api/now/table/incident as admin`
- `PATCH category, impact, urgency, assignment_group, parent, comments, state`

Evidence:

```
{
  "created_by": "admin",
  "service_desk": true,
  "steps": [
    {
      "name": "category",
      "status": 200,
      "stuck": false,
      "read": {
        "category": "software"
      },
      "journal": null,
      "role_added": null,
      "roles": [],
      "error": ""
    },
    {
      "name": "priority_inputs",
      "status": 200,
      "stuck": false,
      "read": {
        "impact": "2",
        "urgency": "2",
        "priority": "3"
      },
      "journal": null,
      "role_added": "sn_incident_write",
      "roles": [
        "sn_incident_write"
      ],
      "error": ""
    },
    {
      "name": "assignment_group",
      "status": 200,
      "stuck": false,
      "read": {
        "assignment_group": "d625dccec0a8016700a222a0f7900d06"
      },
      "journal": null,
      "role_added": null,
      "roles": [
        "sn_incident_write"
      ],
      "error": ""
    },
    {
      "name": "work_notes",
      "status": 200,
      "stuck": false,
      "read": {
        "work_notes": ""
      },
      "journal": {
        "ok": true,
        "status": 200,
        "rows": 1
      },
      "role_added": null,
      "roles": [
        "sn_incident_write"
      ],
      "error": ""
    },
    {
      "name": "parent",
      "status": 200,
      "stuck": false,
      "read": {
        "parent": "8b76e716c3a8d390aef2be1d050131d3"
      },
      "journal": null,
      "role_added": null,
      "roles": [
        "sn_incident_write"
      ],
      "error": ""
    },
    {
      "name": "comment",
      "status": 200,
      "stuck": false,
      "read": {
        "comments": ""
      },
      "journal": {
        "ok": true,
        "status": 200,
        "rows": 1
      },
      "role_added": null,
      "roles": [
        "sn_incident_write"
      ],
      "error": ""
    },
    {
      "name": "resolve",
      "status": 200,
      "stuck": false,
      "via_in_progress": false,
      "read": {
        "state": "6",
        "close_code": "Solution provided",
        "close_notes": "SYN-PROBE resolve"
      },
      "close_code": "Solution provided",
      "known_error": {
        "close_code": "Known error",
        "status": 403,
        "business_rule": true,
        "admin_status": 403,
        "error": "ServiceNow returned HTTP 403: Operation Failed Operation against file 'incident' was aborted by Business Rule 'Check if Known error article required^cb76e716c3a8d390aef2be1d050131da'. Business Rule Stack:Check if Known error article required"
      },
      "role_added": null,
      "roles": [
        "sn_incident_write"
      ],
      "error": ""
    }
  ],
  "roles_before": [],
  "roles_added": [
    "sn_incident_write"
  ],
  "roles": [
    "sn_incident_write"
  ]
}
```

Decision: **verified**. Each incident-workflow write on an incident this user did not create read back. The next role was added only after HTTP 403 or a write that did not stick.

## problem_writes

What smallest role set lets the problem user set known_error, primary_known_error_article, and the incident link?

Calls:

- `PATCH problem known_error and primary_known_error_article`
- `PATCH incident parent and work_notes as the problem user`

Evidence:

```
{
  "article": true,
  "steps": [
    {
      "name": "known_error",
      "table": "problem",
      "status": 200,
      "stuck": false,
      "read": {
        "known_error": "true"
      },
      "journal": null,
      "role_added": null,
      "roles": [
        "problem_coordinator"
      ],
      "error": ""
    },
    {
      "name": "primary_known_error_article",
      "table": "problem",
      "status": 200,
      "stuck": false,
      "read": {
        "primary_known_error_article": "22766756c3a8d390aef2be1d050131d4"
      },
      "journal": null,
      "role_added": null,
      "roles": [
        "problem_coordinator"
      ],
      "error": ""
    },
    {
      "name": "parent",
      "table": "incident",
      "status": 200,
      "stuck": false,
      "read": {
        "parent": "bd86ab56c3a8d390aef2be1d0501310f"
      },
      "journal": null,
      "role_added": null,
      "roles": [
        "problem_coordinator"
      ],
      "error": ""
    },
    {
      "name": "work_notes",
      "table": "incident",
      "status": 200,
      "stuck": false,
      "read": {
        "work_notes": ""
      },
      "journal": {
        "ok": true,
        "status": 200,
        "rows": 1
      },
      "role_added": null,
      "roles": [
        "problem_coordinator"
      ],
      "error": ""
    }
  ],
  "roles_before": [
    "problem_coordinator"
  ],
  "roles_added": [],
  "roles": [
    "problem_coordinator"
  ],
  "knowledge_roles": []
}
```

Decision: **verified**. Known-error fields and the incident link read back. The next problem role was added only after HTTP 403.

## roles

What is the smallest role set for each new user, found one role at a time?

Calls:

- `role grants recorded on the probe that first returned HTTP 403`

Evidence:

```
{
  "incident": [
    "sn_incident_write"
  ],
  "problem": [
    "problem_coordinator"
  ],
  "knowledge": [],
  "authority": []
}
```

Decision: **verified**. Duty roles were added one at a time after HTTP 403, or after an incident write returned 200 and did not stick. snc_basic_auth_api_access was added only when login failed. admin was not granted.

## Residue

- `change_request`: 0
- `change_task`: 0
- `incident`: 0
- `problem`: 0
- `kb_knowledge`: 0
- `task_ci`: 0
- `sysapproval_approver`: 0
- `sysapproval_group`: 0
- `sys_user`: 0
- `sys_user_grmember`: 0
- `sys_user_has_role`: 0
- `problem SYN-E2E-PROBE`: 0
- `incident SYN-E2E-PROBE`: 0
- `kb_knowledge SYN-E2E-PROBE`: 0
- `sys_ws_definition`: 0
- `sys_ws_operation`: 0

## Section 8

- `incident.u_caused_by`: verified. Re-read on this PDI.
- `incident.problem_id`: absent. Use incident.parent.
- `non-admin approval`: verified. Scripted approval is not a fallback.
- `incident.parent`: verified. Custom field fallback is not approved.
- `problem.rfc`: verified. Fallback is a work note plus change.parent.
- `problem.state Table API`: partial. A partial walk is not the approved fallback. The endpoint result is a separate row.
- `Known Error publish`: approved-fallback. Table API publish stayed draft. publish_article was probed and then removed.
- `problem.problem_state`: failed. Writes problem_state and reads state back.
- `endpoint`: verified. Installed operations: move, publish_article. The residue query shows the endpoint is gone.
- `incident writes`: verified. One role at a time on an incident this user did not create.
- `problem writes`: verified. Known error fields and the incident link, one role at a time.
- `least roles`: verified. One role at a time. admin was not granted.
- `choice values`: verified. Read from sys_choice.

## Resolved and Closed parent

Can the problem user set and clear `incident.parent` on a Resolved incident, and on a Closed incident? Will this instance auto-close a Resolved incident, and so will history loaded as Resolved become Closed?

The configured problem user was absent. The probe created `syn.probe.parentlink` with `problem_coordinator` only, used that user for the parent writes, and deleted the user. Admin set the incident state. Admin did not write `parent`.

Calls:

- `POST /api/now/table/incident` and `POST /api/now/table/problem`, marker `SYN-E2E-PROBE`
- `PATCH` state `6`, then state `7`, close code `Solution provided`, as admin
- `PATCH incident.parent` set and clear, as the problem user

Evidence:

```
resolved_set_write=200
resolved_set_stuck=true
resolved_state=6
resolved_clear_write=200
resolved_clear_stuck=true
closed_set_write=200
closed_set_stuck=false
closed_state=7
closed_clear_write=200
closed_clear_stuck=true
property glide.ui.autoclose.time=7
property com.snc.incident.autoclose.basedon.resolved_at=true
business_rule incident autoclose: active, when=after, insert=false, update=false, delete=false, query=false
sysauto_script autoclose=0
residue_incident=0
residue_problem=0
residue_sys_user=0
```

The business rule defines `autoCloseIncidents()`. It reads `glide.ui.autoclose.time`, and because `com.snc.incident.autoclose.basedon.resolved_at` is true it closes Resolved incidents whose `resolved_at` is older than that many days. Every action flag on the rule is false, so an insert or an update does not run it. The rule is called by the scheduled trigger `Autoclose Incidents`. That trigger is hourly. A search of `sysauto_script` does not find it. After the passing gate it closed the 101 seeded incidents. See "Known-error work note after publish" and "Closed parent on the seeded history".

Decision: **verified** for Resolved, on the probe that was still Resolved. The problem user set and cleared `parent`, the value stuck, and the state stayed `6`. The same set on a Closed incident returned HTTP 200 and the parent read back empty. The later Closed probe, run as the configured problem user, had the same result. History was loaded as Resolved. It is Closed now. The runtime link for a Closed incident is in "Closed parent on the seeded history".

## Password policy

Does this PDI accept a new user's password that has no special character?

Calls:

- `POST /api/now/table/sys_user` with `sysparm_input_display_value=true`, `web_service_access_only=true`, and `password_needs_reset=false`
- `GET /api/now/ui/user/current` as that user
- `GET sys_properties` for `glide.enable.password_policy` and `glide.record.enforce_password_policy_all`
- Delete the throwaway user

Evidence:

```
glide.enable.password_policy=true
glide.record.enforce_password_policy_all=true
alphanumeric length 19: create HTTP 200, login HTTP 401, password_needs_reset=false, locked_out=false
alphanumeric length 24: create HTTP 200, login HTTP 401
password containing ! or - or _: login ok at lengths 8, 11, 19, 24, and 28
password_policy table: denied to the Table API by the web service access policy
throwaway residue=0
```

The configured service passwords had no special character. Create returned HTTP 200, and login returned HTTP 401. Granting `snc_basic_auth_api_access` did not change that 401. A throwaway user with no role logged in when the password contained a special character.

Decision: **verified**. On this PDI a password without a special character is accepted on create (HTTP 200) and then fails login with HTTP 401. `glide.enable.password_policy` is true. Service passwords need a special character. `!`, `-`, and `_` were accepted.

## Known error close code

Can the incident user resolve a SYN-E2E-PROBE incident with close code "Known error" when its parent is the seeded E01 problem?

Calls:

- `POST /api/now/table/incident` as the incident user, marker `SYN-E2E-PROBE`
- `PATCH` parent to the E01 problem
- `PATCH` state `6` and close code `Known error`
- `DELETE` the probe incident

Evidence:

```
parent_write=200
parent_stuck=true
close_write=403
close_stuck=false
read_state=1
read_close_code=
probe_deleted=true
```

Decision: The close code was refused. Historical incidents stay on close code "Solution provided".

## Known-error work note after publish

What marks a seeded history incident active after `e2e seed` publishes the E01 known error?

Calls, read only, after the passing Phase 1 gate:

- `GET sysevent_script_action` name `Show primary KE article in Inc worknotes`
- `GET sys_script` name `Raise an event when Primary KE changes`
- `GET sys_script` names `task reopener`, `mark closed`, and `incident autoclose`
- `GET sys_trigger` name `Autoclose Incidents`
- `GET sys_dictionary` element `problem_id`
- `GET sys_ws_operation` for the live `publish_article` and `move` scripts
- `GET sys_journal_field` and `sys_audit` for the seeded incidents
- `GET dl_u_priority` for impact 3 and urgency 3
- `GET sysevent` name `problem.ke_associated` on 2026-11-17

Evidence:

```
publish_article mentions incident: false
move mentions incident: false
problem_id dictionary rows: 0
syslog: Invalid query detected [Unknown field problem_id in table incident]
business rule: Raise an event when Primary KE changes
  table=problem when=after insert=true update=true order=100
  filter=primary_known_error_articleVALCHANGES
  queues event problem.ke_associated
script action: Show primary KE article in Inc worknotes
  event=problem.ke_associated active=true
  queries incident.problem_id, writes a work note, calls update()
task reopener: table=task when=before order=901 active=true
  condition=new TaskStateUtil(current).runTaskReopener()
  sets active=true
mark closed: table=task when=before order=800
  condition=new TaskStateUtil(current).runMarkClosed()
  sets active=false
priority lookup impact=3 urgency=3 -> priority 4
```

The live endpoint scripts do not query `incident`. The seed does not set history incidents active. Setting `problem.primary_known_error_article` is what queues the event. On this PDI `incident` has no `problem_id` field, so the script action's query is invalid. The platform logged that and the query returned the incidents that already existed, not the incidents linked to the problem. `problem_id` is empty on all 101 seeded incidents, and the three C01 rows are the only ones with `parent` set. None of those three received the work note.

The passing gate's last seed created the E01 problem at 2026-11-17 15:10:30. One `problem.ke_associated` event for that problem was processed at 15:10:34. Eight seeded incidents already existed, created at 15:10:33 and 15:10:34:

```
SYN-E2E-INC-C02-001
SYN-E2E-INC-C02-002
SYN-E2E-INC-C02-003
SYN-E2E-INC-C07-009
SYN-E2E-INC-C07-010
SYN-E2E-INC-C07-011
SYN-E2E-INC-C12c-017
SYN-E2E-INC-C12c-018
```

Each received one work note, created by `system`, between 15:10:36 and 15:10:43. The note says a Known Error article was created against the E01 problem. The same update set `active` from false to true and `priority` from 3 to 4. `state` stayed 6. Audit of `SYN-E2E-INC-C02-001` shows those field changes and no `problem_id` change. The other 93 seeded incidents were inserted after the query, from 15:10:35 through 15:10:48, and did not get the note.

The same window wrote that work note on 439 incidents, not only the eight. The rest were already on the instance, including the change seed. The seed's settle counter watches only `SYN-E2E-INC-` rows, so it printed 8.

Seed 1 of that gate printed a climb of 9, then 31, then 44, and reimported 44. Those rows were deleted by the next teardown, so their numbers are not on the instance. Twelve `problem.ke_associated` events were queued on 2026-11-17, one pair for each time the seed set the article field. The query is a snapshot. It updates the rows it found, then stops. A larger count means the event ran later in that import.

The reseed did not change `primary_known_error_article`, so the business rule did not queue another event. The seed waits until its active count is unchanged for 45 seconds, then posts those rows again through the import set with business rules off. That puts `active` back to false and `incident_state` back to 6. Nothing in this path runs again until the article field changes. The count stayed 0.

This fires again on any insert or update that changes `problem.primary_known_error_article`. On this PDI the query is not limited to incidents linked to that problem. The write has been removed from `_mark_known_error`, `_known_error_link_works`, and the Phase 0 probe in `e2e/discover.py`. Those paths still read the field and refuse to continue when it is set. A unit test fails if any module in this repository writes it. The replacement link is in "Known-error link without the article field".

A second job closed the seeded rows later. Business rule `incident autoclose` is active and its insert, update, query, and delete flags are all false, so a record write does not run it. Scheduled trigger `Autoclose Incidents` does. `glide.ui.autoclose.time` is 7 and `com.snc.incident.autoclose.basedon.resolved_at` is true. The seeded `resolved_at` values are in August through October 2026. At 15:18:21 the job set `state` and `incident_state` from 6 to 7 and filled `closed_at`. All 101 seeded incidents are now Closed. That job is not the work-note update. It will close a Resolved incident again once `resolved_at` is at least seven days old.

Decision: **verified**. The work-note update is the out-of-box script action `Show primary KE article in Inc worknotes`, queued by `Raise an event when Primary KE changes`. `task reopener` is what sets `active` true on that update. The endpoint and the seed do not contain that loop. The seed's write of `primary_known_error_article` is what queues the event.

## Known-error blast

Read only, from `sysevent`, `sys_journal_field`, and `sys_audit`, for every processed `problem.ke_associated` since this project started. Groups are the correlation prefix: `SYN-INC-` is the change seed, `SYN-E2E-` is this project, and every other prefix is neither project. The neither rows that still exist are 200 with prefix `PMSYNTH` and 67 with an empty correlation.

Fifteen events were queued. Nine were processed. Six on 2026-11-17 are `state=error`, each one second before a processed event, and the problem on those error rows is gone. They are the article-link probe problems, deleted before the event ran. They did not add a second wave of notes. The only processed event whose problem is still on the instance is the surviving E01 problem, correlation `SYN-E2E-PRB-841def279ed25e56`, number `PRB0040050`.

Each processed event wrote the Known Error article work note. One incident that already had a parent also received a second system note in that same window, and the journal text `Work note copied from Parent Incident` occurs nine times, once per wave. All 3896 notes were created by `system`. Every noted incident is still present.

| Processed | Notes | Unique incidents | change-seed | end-to-end | neither |
|---|---:|---:|---:|---:|---:|
| 2026-11-16 22:18:54 | 432 | 431 | 164 | 0 | 267 |
| 2026-11-16 22:24:25 | 432 | 431 | 164 | 0 | 267 |
| 2026-11-16 22:28:25 | 432 | 431 | 164 | 0 | 267 |
| 2026-11-17 14:15:55 | 432 | 431 | 164 | 0 | 267 |
| 2026-11-17 14:40:24 | 432 | 431 | 164 | 0 | 267 |
| 2026-11-17 14:49:04 | 432 | 431 | 164 | 0 | 267 |
| 2026-11-17 14:52:34 | 432 | 431 | 164 | 0 | 267 |
| 2026-11-17 15:06:34 | 432 | 431 | 164 | 0 | 267 |
| 2026-11-17 15:10:34 | 440 | 439 | 164 | 8 | 267 |

Notes still on the instance: neither 2412, change-seed 1476, end-to-end 8.

The first wave is the one that changed fields other than the work note. Later waves added the work note on the same 431 incidents. Active and priority changes in the later windows belong to end-to-end rows that the next teardown deleted, plus the eight survivors of the last seed. Those deleted rows are not in the counts below.

Change seed, first wave, from `sys_audit`:

- `state` 7 → 2 on 144 incidents. `incident_state` has no audit row on those updates.
- `active` 0 → 1 on 158 incidents. That is the 144 above plus 14 whose `state` stayed 6.
- The other 6 change-seed incidents were already `state` 1 and `active` true. They received the work note only.
- `activity_due` was filled on 10 rows and cleared on the next wave.
- `priority` did not change.

Neither project, first wave:

- `priority` 5 → 4 on 17 incidents.
- `company` empty → a reference on 10 incidents.
- `escalation` 3 → 0 on 10 incidents.
- `activity_due` moved on 17 incidents and was cleared on the next wave.

End-to-end, last wave, the eight correlations listed above:

- `active` 0 → 1, `priority` 3 → 4, `state` stayed 6.
- `calendar_duration`, `business_duration`, `calendar_stc`, and `business_stc` were filled.
- The seed's rules-off reimport put `active` back to false and `priority` back to 3. At 15:18:21 `Autoclose Incidents` set all 101 seeded rows from `state` 6 to 7 and set `priority` 3 → 4 again. Today those eight are Closed, `active` false, `priority` 4, with one system work note each.

Today, `active=true` while Resolved (`state` 6) or Closed (`state` 7):

- change-seed: 14, all `state` 6, `priority` 3. None are Closed and still active.
- neither: 1, empty correlation, `state` 6, `incident_state` 6, `priority` 4, close code `Resolved by problem`. See "Other problem writes" for how it got there.
- end-to-end: 0. All 101 are `state` 7 and `active` false.

The change repository's open-incident query is `active=true^priorityIN1,2`, then the CI name has to belong to that service's fixtures. Today 105 incidents match the query. 84 are change-seed and newly match because `active` flipped to true while `priority` was already 1 or 2:

| Service | Newly matching | Already matching |
|---|---:|---:|
| SYN Payments | 28 | 0 |
| SYN HR Portal | 28 | 0 |
| SYN Online Store | 28 | 0 |
| SYN Order Fulfillment | 0 | 0 |
| CI outside the change world | 0 | 21 |

The 21 are neither-project incidents. They have no `active` or `priority` audit since 2026-11-16 21:00. End-to-end rows are `priority` 4, so none match.

Change-seed rows today, all `incident_state` 1 and `active` true. The walker audit did not change `incident_state`:

| state | incident_state | priority | count |
|---|---|---|---:|
| 2 | 1 | 1 | 10 |
| 2 | 1 | 2 | 74 |
| 2 | 1 | 3 | 60 |
| 1 | 1 | 4 | 6 |
| 6 | 1 | 3 | 14 |

## Other problem writes

Business rules, script actions, and flows on `problem` that reference `incident.problem_id` or update incidents:

| Name | Where | Active | When it runs |
|---|---|---|---|
| Raise an event when Primary KE changes | business rule on `problem` | yes | insert and update, filter `primary_known_error_articleVALCHANGES`, queues `problem.ke_associated` |
| Show primary KE article in Inc worknotes | script action | yes | `problem.ke_associated`. Queries `incident.problem_id`, writes the work note, calls `update()` |
| Update Incident when Problem closes | script action | yes | `problem.state_change`. Queries `problem_id`, `state` Awaiting Problem, and `hold_reason` 3. Updates only when `resolution_code` is `fix_applied` or `risk_accepted` |
| Copy Prb workaround to Inc comments | script action | yes | `communicate.workaround` |
| Copy Prb workaround to Inc work notes | script action | yes | `communicate.workaround` |
| Copy Prb fix to Inc work notes | script action | yes | `communicate.fix` |
| SNC - ITIL - Update Related Incidents | business rule on `problem` | yes | update, condition `current.problem_state.changesTo(4)`. Queries active incidents by `problem_id` and calls `update()` |
| SNC - ITIL - Close Related | business rule on `problem` | no | `problem_state` changes to 4 |
| SNC - ITIL - Resolve Related Incidents | business rule on `problem` | no | `problem_state` changes to 4 |
| Link attached KE article to the Problem | business rule on `m2m_kb_task` | yes | insert, when the task is a problem and the article class is `kb_template_known_error_article`. Sets `problem.primary_known_error_article` and calls `update()` |
| Update incident from known error | business rule on `m2m_kb_task` | yes | the task is an incident and the article class is the template. Writes `incident.problem_id` |
| Update Source Task of KE article | business rule on `problem` | yes | only when `primary_known_error_article` is already set and the article's `source` is empty |

A second `SNC - ITIL - Close Related` row is active on `global` with every action flag false. Three flows are active and returned no trigger row from `sys_hub_trigger_instance`: `Link problem to mulitple incidents`, `[Non-ML] Link problem as parent`, and `Link problem to task`. `Inbound Email Flow Example: logging a problem` is inactive. The probe below created, updated, and moved a problem, and the incident count in each window was zero, so those flows did not walk `incident` on these writes.

`communicate.workaround` and `communicate.fix` have zero events since 2026-11-16. Journal text since then has zero rows for `Workaround shared`, `Fix shared`, `Proposed/Planned fix`, `closed based on closure`, and `resolved based on closure`. Writing `workaround`, `fix_notes`, and `known_error` through the Table API did not queue those events. The historical state moves did not either.

`Update Incident when Problem closes` did run once. At 2026-11-16 22:18:34, during a `problem.state_change` from the Phase 0 walk, one incident was resolved. `state` and `incident_state` went from 3 to 6, `hold_reason` from 3 to empty, `priority` from 5 to 4, close code from empty to `Resolved by problem`, and the close notes say the related problem `PRB0040020` closed. The correlation is empty. `active` has no audit change, so it was already true while the incident was On Hold. That is the one neither-project incident that is active and Resolved today. The extra query terms limited the script to incidents awaiting a problem. The invalid `problem_id` term did not make it update every incident. Today `state=3^hold_reason=3` matches 0 incidents. Six incidents are On Hold with a different hold reason.

`SNC - ITIL - Update Related Incidents` did not mass-update incidents. Its condition is `problem_state` changing to 4. On this PDI the walked values are 101, 102, 103, 104, 106, and 107.

Setting `known_error`, writing `workaround`, and the endpoint state walk, including Resolved and Closed, are covered by the probe in the next section. The only broad incident update this project caused is `problem.ke_associated`.

## Known-error link without the article field

The article's own `source` field is a reference to `task`, so it can point at the problem. `kb_knowledge.cmdb_ci` is a reference to `cmdb_ci`. The Phase 2 match reads a published `kb_knowledge` row whose `short_description` starts with `SYN-E2E-`, whose `cmdb_ci` is the incident's CI, and whose `source` is a problem with `known_error` true. A work note on the problem names the article number. The note is the readable name. The join is `source` plus `cmdb_ci`.

The knowledge-to-task link is the wrong write on this PDI. `Link attached KE article to the Problem` runs on insert of `m2m_kb_task` when the article class is `kb_template_known_error_article`, sets `primary_known_error_article`, and calls `update()`. That queues the walker. The probe did not insert that row. `task_rel_task` is not on this instance.

The probe used one `SYN-E2E-PROBE` problem and one `SYN-E2E-PROBE` article, as the problem user, then deleted both. `primary_known_error_article` was read after every write and stayed empty. The count of incidents whose `sys_updated_on` moved in the wait after the write was zero. Events named `problem.ke_associated`, `communicate.workaround`, and `communicate.fix` were zero.

| Write | Result | Incidents updated |
|---|---|---:|
| Create the problem | state 101 | 0 |
| Work note | accepted | 0 |
| `known_error` true | stayed true | 0 |
| `cause_notes` | accepted | 0 |
| `workaround` on the problem | accepted | 0 |
| `fix_notes` | accepted | 0 |
| `close_notes` | accepted | 0 |
| `problem.rfc` to an existing change | the change `sys_updated_on` stayed put | 0 |
| `kb_knowledge` with `source` = the problem and `cmdb_ci` = `syn-store-cdn` | both values stuck, draft | 0 |
| `publish_article` | HTTP 200, `workflow_state` published, `source` and `cmdb_ci` stayed | 0 |
| Work note naming the article number | accepted | 0 |
| Endpoint move 102, 103, 104 | read back 102, 103, 104 | 0 |
| Endpoint move 106 with `resolution_code` `fix_applied` | read back 106, `problem_state` 106 | 0 |
| Endpoint move 107 with the same resolution code | read back 107, `problem_state` 107 | 0 |

The platform queued its own events on these writes: `problem.inserted`, `problem.updated`, `problem.assigned`, `problem.state_change`, `metric.update`, `text_index`, `notification_engine.process`, `ci.notification.for.task`, and `sn_actsub.create_activity`. `problem.state_change` was processed on the state moves, including 106 and 107 with `fix_applied`. The incident count after each of those moves was zero. Move 104 needs `fix_notes` and `close_notes`. Move 106 and 107 need `resolution_code` `fix_applied` as well. A 104 → 106 request without those fields returned HTTP 409 and left the state at 104.

Residue after delete: probe problems 0, probe incidents 0, probe articles 0.

## Repair proposal

Not executed. The user decides.

The restore that sticks is the same path the seed already uses: an import or a Glide update with business rules off, coalesce on the correlation id, writing `active` and `state` from that row's `sys_audit` old values. A Table API PATCH of `active` does not stick. `task reopener` sets `active` true on the update, and a rules-on update of impact 3 and urgency 3 sets `priority` to 4.

Work notes: leave them, and record that they are system notes from `Show primary KE article in Inc worknotes`. Deleting `sys_journal_field` rows would hide the evidence and would still leave `sys_audit`. A full recreate drops the notes because the incidents are new rows.

Change seed, 164 incidents:

- 144: put `state` back to 7 and `active` back to false. `priority` was not changed by the walker.
- 14: leave `state` 6 and put `active` back to false.
- 6: `state` 1 and `priority` 4 were already that way. Leave the fields. The work note is the only change.
- `incident_state` is 1 on all 164 and the walker did not audit it. The change seed's own check compares `state` and `active`. Leave `incident_state` alone on the targeted restore.

A full `cm-agents` teardown and seed would delete these 164 incidents and create them again, so `state`, `active`, and the notes would match a fresh change seed. It would also rebuild the change world. It would not touch the 267 neither-project incidents, the one incident the close script resolved, or the eight end-to-end work notes. The targeted restore is the smaller change. Teardown stays unrun.

Neither project, 267 incidents. 200 use correlation prefix `PMSYNTH`. 67 have an empty correlation. They are not this project's rows and not the change seed. What I would touch, only if you say so, with business rules off, from each row's own audit:

- 17 incidents: `priority` back to 5.
- 10 incidents: `company` back to empty.
- 10 incidents: `escalation` back to 3.
- The one empty-correlation incident that is active and Resolved: `state` and `incident_state` back to 3, `hold_reason` back to 3, `priority` back to 5, and clear `close_code`, `close_notes`, `resolved_at`, and `resolved_by`.
- Leave every work note.

End-to-end: leave the 101 Closed. The eight work notes stay. `priority` 4 on the 101 is the autoclose update, and a rules-on write of the seeded impact and urgency returns 4 again. A rules-off import could put `priority` back to 3. I would leave it until you ask.

## Closed parent on the seeded history

The 101 history incidents are Closed. `Autoclose Incidents` did that at 2026-11-17 15:18:21. Three of them still have `parent` set. Those are the C01 rows the import wrote with business rules off. The import link survived the close.

Condition 8(b), again, as the configured problem user, on a new `SYN-E2E-PROBE` incident that admin closed first:

```
admin state 6: HTTP 200
admin state 7: HTTP 200
before: state 7, incident_state 7, active false
parent set: HTTP 200, read back empty, state stayed 7, active stayed false
parent clear: HTTP 200, read back empty, state stayed 7
probe deleted
```

The problem user cannot put `parent` on a Closed incident. The value does not stick. `task_rel_task` is absent from `sys_db_object`, and no similar table name is present. The only dictionary reference pair found for `parent` or `child` toward `task` is `task.parent` itself.

The runtime link for Closed history is a work note on the problem, written by the problem user, one line per incident:

```
SYN-E2E-HISTORY <incident number> <correlation id>
```

The probe's work-note write updated zero incidents and did not queue `problem.ke_associated`. The seed writes that note for the three C01 incidents after the import, as the problem user, and skips a line that is already in the journal. An open arrival still gets `incident.parent`. The three C01 parents the rules-off import stored stay. Reports read `incident.parent` when it is filled, and they read `sys_journal_field` on the problem for the `SYN-E2E-HISTORY` prefix when the incident is Closed and `parent` is empty. The correlation id in the note is the key back to the incident. The incident number is there so a person reading the problem can follow it.

## Category by CI class

The committed model `category-v0.2` scored 0.5 on the 10 arrival fixtures. Five were wrong. Three of the wrong answers were above 0.99 confidence: C02-004 Network 0.9997, C02-005 Network 0.9993, C02-007 Network 0.9931. C02-006 was Database at 0.4183 and C02-008 was Network at 0.3413. The five correct rows were the C07 arrivals, labeled Software. This is a finding. An ADR records it when branch `e2e-incident` exists. The model is not used for the decision. A constant is not used either.

The rule is a table keyed by CI class, kept as world data. The end-to-end fixtures use two classes. The values are the incident category choices on this PDI.

| CI class | Category | Fixtures |
|---|---|---|
| `cmdb_ci_appl` | `software` | syn-ful-inventory, syn-ful-warehouse, syn-hr-benefits, syn-hr-payroll, syn-hr-portal, syn-hr-recruiting, syn-hr-time, syn-pay-auth, syn-pay-fraud, syn-pay-gateway, syn-pay-ledger, syn-pay-recon, syn-store-cart, syn-store-catalog, syn-store-cdn, syn-store-checkout, syn-store-search, syn-store-session |
| `cmdb_ci_linux_server` | `hardware` | syn-prd-lx-073, syn-stg-lx-001 |

A class that is not in the table is not given a category. The arrival fixtures are five `cmdb_ci_appl` rows, which return `software`, and five `cmdb_ci_linux_server` rows, which return `hardware`. History rows now take the category from this same table. The offline backtest was rerun after that change.

## Repair

### Change-seed tool

Ran `cm-agents seed --seed 42 --anchor 2026-10-27` from the change repository. No file in that repository was edited. Exit code 1. The command reused the loaded world: anchor `2026-10-27`, users ready 40, CIs ready 300, memberships created 0, relationships created 0, task CI created 0, three import sets already processed, and no empty change or incident numbers. It then stopped with `field check failed (302)`. Those 302 differences are `state` and `active` (144 state, 158 active). It did not print `teardown first`. It did not update the incidents. The owner's seed detects a difference and refuses. It does not correct an incident that is already loaded. No teardown was run.

### Field restore

The owner's seed left the differences, so the one-off helper `tests/helpers/restore_audited_incident_fields.py` restored them. It is not part of the product. It is not collected by pytest. For each incident that received a system work note containing `Known Error` at or after 2026-11-16 22:18:00, it read `sys_audit` and took the earliest old value of each changed field in that window. Journal fields and system metadata were skipped. It wrote those values back through an import set whose transform map has business rules, scripts, and mandatory fields off, coalescing on the incident number, including empty values. A canary row whose `active` was going back to false was checked before the rest. The staging table was removed afterward. A second dry run planned zero rows.

The helper refused to run unless the noted incidents were exactly 164 change-seed, 267 neither-project, 8 end-to-end, and 0 other. It also refused unless exactly one incident matched the close-script exception: neither project, empty correlation, close code `Resolved by problem`, audit `state` 3 to 6, audit `hold_reason` 3 to empty. That incident was not in the restore plan.

| Group | Rows restored | Fields |
|---|---:|---|
| change-seed | 158 | `active` 158, `state` 144, `activity_due` 10 |
| neither | 38 | `activity_due` 17, `company` 10, `escalation` 10, `priority` 17 |
| end-to-end | 8 | `state` 8, `incident_state` 8, `priority` 8, `business_duration` 8, `business_stc` 8, `calendar_duration` 8, `calendar_stc` 8, `closed_at` 7 |

The six change-seed incidents that were already New and active were not in the plan. The 93 end-to-end incidents that autoclose had already closed, and that the walker had not noted, were not in the plan.

### Work notes left in place

| Group | System work notes |
|---|---:|
| change-seed | 1476 |
| neither | 2412 |
| end-to-end | 8 |
| other | 0 |

Noted incidents stayed 439. The incident count did not change.

### Close script

The script that resolved the On Hold incident is the script action `Update Incident when Problem closes`. It runs on `problem.state_change`. Its incident query is `problem_id` equal to the problem, `state` equal to Awaiting Problem, and `hold_reason` equal to 3. `incident.problem_id` does not exist, so that term is ignored. The terms that apply are state 3 and hold reason 3. When `resolution_code` is `fix_applied` it updates the incident to Resolved. When `resolution_code` is `risk_accepted` it writes a work note. With no other incidents in that query, closing a problem in Phase 3 resolves no incident on this instance. Six incidents are On Hold with a different hold reason, and this script does not select them. The resolver simulator does not put an incident On Hold.

`e2e doctor` now counts `state=3^hold_reason=3` and fails when that count is not zero. It prints the script name and the query.

### Category backtest

History categories are generated from the CI-class table above. The offline backtest was rerun with the fork's detection unchanged.

| CI class | Category |
|---|---|
| `cmdb_ci_appl` | `software` |
| `cmdb_ci_linux_server` | `hardware` |

The full slice was 108 incidents, 10 candidates, detection precision 0.9. The history slice and the four-of-five slice still withhold C02 and C07. D04 opens nothing. D08 remains the expected false positive. The command printed `outcomes match`. No confirmation or detection outcome changed.

### Verification

Read after the restore, and again after the scenarios:

| Check | Result |
|---|---|
| Incidents active while state is 6 or 7 | 1. Before the first wave this was 0. The one row is the close-script exception: empty correlation, close code `Resolved by problem`, state 6, active true. It was not restored. |
| `active=true^priorityIN1,2` | 21, all with an empty correlation |
| `state=3^hold_reason=3` | 0 |
| Change-seed incidents | 164 |
| Change-seed changes | 1500 |

The first `cm-agents scenario run S06` exited 1. It created the release and four members, then `GET /api/now/table/conflict` failed before a response after its retries. That is a transport failure. The runner leaves scenario rows when a scenario fails. Those five changes, and only those, were deleted with the change repository's own child-delete helpers, limited to correlation prefix `SYN-S06-`. Seed changes, seed incidents, and the 101 end-to-end incidents were unchanged by that delete. No file in the change repository was edited.

The retry `cm-agents scenario run S06` passed. Pytest reported 1 passed in 470.02s. The release closed with close code successful. On a pass the runner deletes every `SYN-` change and incident whose correlation is not `SYN-CHG-`, `SYN-OPEN-`, `SYN-REL-`, or `SYN-INC-`. That query includes `SYN-E2E-`. The cleanup removed the 5 scenario changes and the 101 end-to-end incidents, then reported both remaining counts as 0. The eight end-to-end system notes left with those incidents. The change-seed and neither-project notes stayed: 3888 system Known Error notes, which is 1476 plus 2412. The two incident checks above were the same after that cleanup.

`cm-agents scenario run S09` passed. Pytest reported 1 passed in 75.94s. Its cleanup found 0 scenario changes and 0 scenario incidents. `git status` in the change repository was clean after both passes.

`cm-agents doctor` exited 0. Admin login was ok. The last line was `agent user: present`.

`e2e doctor` exited 0. It printed `problem close would resolve: 0 script=Update Incident when Problem closes query=state=3^hold_reason=3`, and `doctor: ok`.

### Reseed and the link check

The approved reseed is `e2e gate`. The first attempt stopped during seed 1 after it had created the E01 problem, moved it to state 103, posted the article, and published it (`workflow_state=published`). It then raised `E01 known-error article did not link to the problem`. The checker read only `workflow_state` and `short_description`, so `source` and `cmdb_ci` compared empty. The article already stored both. `primary_known_error_article` was not set, and it was not patched. The read now includes `source` and `cmdb_ci`. A failed check names which of published, source, CI, and an empty article field failed, and it does not print an identifier.

The next gate's first teardown deleted that partial problem and article. Seed 1 and seed 2 each imported 101, skipped 0, settled with 0 incidents still being reopened, wrote three history lines, and printed `outside incident updates=0`. The reseed reused the E01 problem, imported 0, skipped 101, printed `history note: reused`, and printed `outside incident updates=0`. Counts after each were 101 incidents, 1 problem, 1 article, 0 changes, 1 endpoint definition, and 2 operations. The change seed stayed at 1500 changes and 164 incidents. The gate guard printed `gate outside incident updates=0`. `e2e doctor` printed the close-script count 0 and `doctor: ok`. `cm-agents doctor` exited 0 and ended with `agent user: present`. S09, run as pytest, passed: 1 passed in 29.09s. That path does not call the scenario cleanup that deletes `SYN-E2E-` incidents. The gate printed `gate: pass`. The world was left seeded.
