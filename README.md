# issue - CLI Issue Tracker

> **Note:** This is a public, open-source version of the issue tracker.

Lightweight issue tracking with pluggable review workflows.
States: `draft` → `review` → `approved` → `done` (issue workflow)

Tracks whose turn it is via an attention set (inspired by Google Critique).

## Install

```bash
uv tool install -e .

# optional: alias for convenience
alias i=issue
```

## Quickstart

```bash
# Check your todos (inbox) and what reviews you're waiting on (outbox)
issue
# Create a task, with alex as a reviewer
issue new "Implement feature X" -r alex
# Owner: submit for review
# We check if you're an owner or reviewer against your user@email.tld in git
issue review 1
# Reviewer: give feedback, pass attention back to issue owner
issue comment 1 "Needs error handling"
# Owner: respond to feedback, pass attention back to all reviewers
issue comment 1 "thanks! done."
# Reviewer: approve (all listed reviewers must approve)
issue approve 1
# Mark done
issue done 1
```

## Aliases

Issues can have aliases for stable references (instead of `issue pick`):

```bash
issue new "Feature X" -a featurex    # create with alias
issue edit 1 -a featurex             # add alias to existing issue
issue show featurex                  # reference by alias
issue comment featurex "looks good"  # works in all commands
```

## Commands

All commands support shortest unique prefix (e.g., `i c` for `issue comment`).

| Command  | Description                              |
|----------|------------------------------------------|
| new      | Create issue (`$EDITOR` if no title)     |
| show     | Show issue details + approval status     |
| list     | List issues with filters                 |
| edit     | Edit issue (`$EDITOR` if no flags)       |
| comment  | Add comment (`$EDITOR` if no text)       |
| review   | Submit for review (draft→review)         |
| approve  | Approve issue (review→approved)          |
| done     | Mark complete (approved→done)            |
| abandon  | Abandon issue                            |
| inbox    | Issues needing your action               |
| outbox   | Your issues waiting on others            |
| pick     | fzf picker, outputs issue number         |
| tui      | Interactive terminal UI                  |

Running `issue` without a command shows inbox + outbox summary.

## Examples

```bash
issue                              # inbox/outbox summary
issue new "Fix the bug"            # create issue
issue new                          # create via $EDITOR
issue show 1                       # show issue #1 with approval status
issue comment 1 "LGTM"             # comment
issue comment                      # comment on first inbox issue via $EDITOR
issue review 1                     # submit for review
issue approve 1                    # reviewer approves
issue done 1                       # mark complete
issue list --status review         # list issues in review
issue show $(issue pick)           # fzf select then show
issue show $(i p)                  # same, shortened
issue tui                          # interactive terminal UI
```

## Multiple Reviewers

When multiple reviewers are assigned, all must approve to advance:
- `show` displays: `approved: bob (1/2)` and `pending: carol`
- `list` displays: `[1/2]` indicator for partial approvals

## Edit Flags

```
-a ALIAS    alias (stable short name, e.g. "myfeature")
-s STATUS   status (draft/review/approved/done/abandoned)
-o OWNER    owner
-t TITLE    title
-p PRIORITY priority (higher = more important)
-r USERS    add reviewers
-l LABELS   add labels
-D          mark done
-X          mark abandoned
```

## Query DSL

The `list` command and TUI search (`/`) support a query DSL:

```bash
i list "owner:alice status:review"  # field:value matching
i list "owner:alice -label:wontfix" # negation with -
i list "bug"                        # full-text search
i list "owner:alice bug"            # combine field and text
```

### Supported Fields

| Field     | Matches                          |
|-----------|----------------------------------|
| owner     | Issue owner                      |
| status    | Issue status                     |
| alias     | Issue alias                      |
| label     | Any label                        |
| reviewer  | Any reviewer                     |
| cc        | Any CC'd user                    |
| attention | Any user in attention set        |
| blocks    | Issue number this blocks         |
| blocked   | Issue number blocking this       |

### Query Syntax

- `field:value` - match field (substring, case-insensitive)
- `-term` - negation (exclude matches)
- `text` - full-text search across all fields
- Multiple terms are ANDed together

## Alternative Workflows

Set `ISSUE_WORKFLOW` env var:
- `issue` (default): draft → review → approved → done
- `kanban`: backlog → ready → in_progress → done

## Schema

See `docs/SCHEMA.md` for the informal issue field schema and git merge semantics.
