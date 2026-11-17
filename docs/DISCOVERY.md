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

The business rule defines `autoCloseIncidents()`. It reads `glide.ui.autoclose.time`, and because `com.snc.incident.autoclose.basedon.resolved_at` is true it would close Resolved incidents whose `resolved_at` is older than that many days. Every action flag on the rule is false, so an insert or an update does not run it. No scheduled job on this instance calls it. The job "Autoclose Incidents" is absent.

Decision: **verified** for Resolved. The problem user set and cleared `parent`, the value stuck, and the state stayed `6`. The same set on a Closed incident returned HTTP 200 and did not stick. History is loaded as Resolved with close code `Solution provided`. A problem opened from a cluster links that history, including the clear at cleanup, as the problem user. Closed incidents are not used for that link. History loaded as Resolved stays Resolved while the closer stays unwired. No custom parent field.

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
