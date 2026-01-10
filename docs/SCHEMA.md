# Issue Schema (Informal)

This document describes the fields currently used by issue records. The code treats
issues as plain dicts and does not enforce a strict schema. Missing fields can still
cause some commands to error, so this is the canonical reference.

## Storage

- File backend: `.issues/<id>.yaml` (config: `ISSUE_DIR`)
- Git backend: `<id>.yaml` on the `issues` branch (config: `ISSUE_BRANCH`, `ISSUE_REMOTE`)

## Core Fields

Merge column applies to the git backend 3-way merge. The file backend does not
merge; last write wins.

| Field        | Type                  | Notes                                         | Merge     |
| ------------ | --------------------- | --------------------------------------------- | --------- |
| id           | string                | UUIDv7 hex, 32 chars, used as filename        | immutable |
| title        | string                | Short summary                                 | scalar    |
| status       | string                | Workflow state (see below)                    | scalar    |
| owner        | string                | Issue owner                                   | scalar    |
| priority     | int                   | Higher = more important                       | scalar    |
| alias        | string or null         | Short stable name, should be unique           | scalar    |
| reviewers    | list of string         | Reviewers for approval                        | union     |
| approved_by  | list of string         | Reviewers who approved current stage          | union     |
| cc           | list of string         | Watchers                                     | union     |
| labels       | list of string         | Tags                                          | union     |
| attention    | list of string         | Whose turn it is                              | union     |
| created      | string (ISO 8601 UTC)  | Creation timestamp                            | immutable |
| updated      | string (ISO 8601 UTC)  | Last update timestamp                         | timestamp |
| blocked_by   | list of string         | Issue IDs that block this issue               | union     |
| blocks       | list of string         | Issue IDs this issue blocks                   | union     |
| comments     | list of comment object | See comment object below                      | comments  |
| due          | dict of string->string | State->date (YYYY-MM-DD) for Gantt view       | dict      |
| assignee     | string or null         | Kanban: current worker                        | scalar    |
| block_reason | string or null         | Kanban: external blocker reason               | scalar    |

Notes:
- `blocked_by` and `blocks` store issue IDs, not numeric issue numbers.
- `attention` drives inbox/outbox views and is set by workflow transitions.
- `created`/`updated` are set by save operations (`now()` uses UTC + `Z` suffix).
- Additional fields are allowed and preserved; unknown fields merge as `scalar`.

### Comment Object

Each comment is a dict with:
- `author`: string
- `time`: ISO 8601 UTC string
- `text`: string

## Workflow and Status Values

Active workflow is chosen by `ISSUE_WORKFLOW` (default: `issue`).

### issue
- `draft -> review -> approved -> done`
- terminal: `done`, `abandoned`

### kanban
- `backlog -> ready -> in_progress -> blocked -> done`
- terminal: `done`, `wontfix`

Workflow-specific fields:
- `reviewers` and `approved_by` are used in `issue` workflow.
- `assignee` and `block_reason` are used in `kanban`.
- `due` is used by Gantt views across workflows.

## Sample Issues (YAML)

### `issue` Workflow Example

```yaml
id: 018f1e4e6c2a7c44b1f9b6b2c1b93d8a
title: "Add CSV export"
status: "review"
owner: "alice"
priority: 2
alias: "csv-export"
reviewers: ["bob", "carol"]
approved_by: ["bob"]
cc: ["dave"]
labels: ["feature", "export"]
attention: ["carol"]
created: "2024-05-02T18:12:34Z"
updated: "2024-05-03T09:41:02Z"
blocked_by: []
blocks: []
comments:
  - author: "bob"
    time: "2024-05-03T09:40:00Z"
    text: "Looks good, just add tests."
due:
  review: "2024-05-05"
  done: "2024-05-10"
```

### `kanban` Workflow Example

```yaml
id: 018f1e4e6c2a7c44b1f9b6b2c1b93d8b
title: "Reduce CI flakiness"
status: "blocked"
owner: "dana"
priority: 1
assignee: "eli"
block_reason: "Waiting on new test runner images"
labels: ["infra", "stability"]
attention: ["dana"]
created: "2024-05-01T10:05:00Z"
updated: "2024-05-04T15:22:11Z"
blocked_by: []
blocks: []
comments:
  - author: "eli"
    time: "2024-05-04T15:20:00Z"
    text: "Blocked until images are published."
```

## Merge Semantics (Git Backend)

The git backend performs a 3-way merge between base, remote, and local YAML.
Per-field merge kinds:

- `immutable`: keep base/remote value (for IDs and creation timestamps).
- `timestamp`: choose the latest timestamp (for `updated`).
- `scalar`: if both sides changed differently, prompt in TTY; non-TTY aborts.
- `union`: list union with add/remove relative to base; preserves order by taking
  base items first, then remote additions, then local additions.
- `comments`: dedupe by (`author`, `time`), then sort by time.
- `dict`: per-key 3-way merge; conflicts prompt like scalar.

Unknown fields default to `scalar` merge behavior.
