# Discovery

Phase 0 probes for the end-to-end workflow. API paths are relative to the instance. Secrets and the instance host are omitted. Probe rows use the SYN-PROBE marker and are deleted before the command returns.

## Email gate

glide.email.smtp.active is false and no active email account exists.

## Dictionary

- `incident.u_caused_by`: [{'internal_type': 'reference', 'reference': 'change_request', 'read_only': 'false', 'active': 'true'}]
- `incident.problem_id`: []
- `incident.rfc`: []
- `task.problem_id`: []
- `problem.rfc`: [{'internal_type': 'reference', 'reference': 'change_request', 'read_only': 'false', 'active': 'true'}]
- `problem.state`: []
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
  "roles": [],
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
  "number": "CHG0047166"
}
```

Decision: **verified**. The probe user, without admin, approved its own rows at Assess and Authorize. The change reached Scheduled.

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
  "parent": "04fc1b1ac328d390aef2be1d0501318c",
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
  "returned": "fcfc1b1ac328d390aef2be1d050131f5",
  "read_back": "fcfc1b1ac328d390aef2be1d050131f5",
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

Decision: **partial**. The Table API moved some states and stopped. The endpoint was not installed.

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
    "sys_id": "12fcdb1ac328d390aef2be1d05013140"
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

Decision: **approved-fallback**. The problem user did not publish the article through the Table API. The approved fallback is publish_article. It is not installed.

## roles

What is the smallest role set for each new user, found one role at a time?

Calls:

- `role grants recorded on the probe that first returned HTTP 403`

Evidence:

```
{
  "incident": [],
  "problem": [
    "problem_coordinator"
  ],
  "knowledge": [],
  "authority": []
}
```

Decision: **failed**. Duty roles were added only after HTTP 403. snc_basic_auth_api_access was added only when login failed. admin was not granted.

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

## Section 8

- `incident.u_caused_by`: verified. Re-read on this PDI.
- `incident.problem_id`: absent. Use incident.parent.
- `non-admin approval`: verified. Scripted approval is not a fallback.
- `incident.parent`: verified. Custom field fallback is not approved.
- `problem.rfc`: verified. Fallback is a work note plus change.parent.
- `problem.state Table API`: partial. A partial walk is not the approved fallback. The endpoint was not installed.
- `Known Error publish`: approved-fallback. publish_article is the approved fallback and is not installed.
- `least roles`: failed. One role at a time. admin was not granted.
- `choice values`: verified. Read from sys_choice.

## Follow-up reads

These reads ran after `e2e discover` returned. They did not install an endpoint. The diagnostic problem used the SYN-PROBE marker and was deleted. A leftover query on `problem.short_descriptionSTARTSWITHSYN-PROBE` returned 0 rows.

The General problem model (`prb_model` sys_id `b58c327fb70c021041c2feb0be11a90e`, name General) has six states and twelve `sttrm_state_transition` rows. `from_state` and `to_state` reference `sttrm_state`. Conditions on `sttrm_transition_condition` for those transitions:

- New to Assess: `assigned_toISNOTEMPTY`
- Assess to Root Cause Analysis: no condition row
- Root Cause Analysis to Fix in Progress: `cause_notesISNOTEMPTY^fix_notesISNOTEMPTY`
- Root Cause Analysis to Resolved: `cause_notesISNOTEMPTY^close_notesISNOTEMPTY`
- Assess to Closed, Root Cause Analysis to Closed, and Fix in Progress to Closed: `resolution_code` conditions, with `close_notes` or `duplicate_of` on some branches

`sys_dictionary` for `problem.resolution_code` is `read_only=true`. `problem.cause_notes`, `problem.fix_notes`, and `problem.workaround` are writable html fields and are not mandatory.

An admin Table API write then confirmed the stuck edge is not a missing role. With `assigned_to` set, New (101) moved to Assess (102). The next write, `state=103`, returned 102 and read back 102. A second write that also sent `cause_notes` and `workaround` stayed on 102. The diagnostic problem was deleted.

The role decision in this file is **failed** because the state probe is partial. The grants themselves were: incident none, problem `problem_coordinator` after HTTP 403, knowledge none because publish returned HTTP 200, authority none beyond the two group memberships.
