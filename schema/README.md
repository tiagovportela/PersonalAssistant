# Store schema (Phase 1 draft)

[`schema.sql`](schema.sql) is the SQLite schema for the layer's store, covering what Phase 1 needs: Git, the Claude Code index, claims, session notes, links, confidential labels, retention, the audit trail and keyword search. [`test_schema.py`](test_schema.py) checks the rules the database enforces by itself (`python3 -I test_schema.py`, 22 checks, standard library only).

## How the brief maps to tables

| Brief (§6–§10) | Tables |
|---|---|
| Allowlists, collector status, missed and duplicated events | `sources` (`enabled` is the allowlist), `collector_runs` (seen / inserted / changed / unchanged / gone per pass) |
| Project, rule-based links across sources (FR4) | `projects`, `project_aliases` (local paths, and where each project lives online); commits' `refs` in `payload` |
| Allowlist for online sources | `connectors`: on or off per connector, with a free-text scope |
| ActivityEvent, WorkSession | `events`. Sessions and focus spans are events with `ended_at`. |
| Artifact, WorkItem | `artifacts` (a Notion task is `kind = 'work_item'`). Online ones are references only. |
| Evidence: a local record, or a link/ID plus when it was read | `evidence` → an event, or an artifact with `read_at` and `source_version` |
| KnowledgeClaim and versions, SessionNote | `claims`, `claim_versions`, `claim_evidence`. A session note is a claim with `type = 'session_note'`. |
| Relationships, contradictions | `links` (`contradicts`, `supersedes`, `duplicates`, `part_of`, `related`) |
| Confidential label | `labels` |
| Retention, audit trail | `retention`, `audit_log` |
| Keyword search | `events_fts`, `claims_fts`, `artifacts_fts` (FTS5) |

Not in the brief's entity list but needed: `collector_runs` for metrics. **Deferred to Phase 3:** `meetings`, `recordings` and `transcript_segments`, plus a `transcript_segment_id` column on `evidence`. People get a table only if commitments need more than an email or handle in `owner`.

## Decisions in this draft

- **Natural keys make re-reads safe.** An event's id comes from the source (`git:commit:<sha>`), and the collectors always write with `UPSERT_EVENT` in [`service/store.py`](../service/store.py), which `test_schema.py` also checks. An identical re-read changes nothing. A changed one (an amended commit, a session that grew) updates the row and sets `changed_at`. `content_hash` tells the two apart, and the counts go into `collector_runs`.
- **Times are UTC, workdays are local.** Each event stores its UTC offset, and `local_day` is computed from both. A commit at 23:30 UTC in summer belongs to the next Lisbon workday.
- **Claim versions are append-only.** A correction and a status change both add a version; triggers reject edits and gaps in numbering. A claim's state is its latest version (`current_claims`). `supersedes` links one claim to another that replaced it, such as a reversed decision. A newer version of the same claim isn't a supersession.
- **Only I can verify.** A `supported` version must have `changed_by = 'me'`, enforced by a CHECK. The service sets `'me'` only when the change comes through the approval-gated `set_claim_status` tool or the frontend.
- **One place decides what Claude sees.** Read tools query only `events_for_claude` and `claims_for_claude`. These drop disallowed sources, retracted claims, and anything labelled confidential directly, through its project or source, or through a claim's evidence. That makes the "no leaks" check in the MVP definition testable in one spot.
- **Expired evidence leaves a trace.** When an event is deleted, its evidence rows stay with `event_id` cleared and `expired_at` set, so Claude can say a confirmed claim's evidence has expired.
- **Search folds accents.** `remove_diacritics 2` lets "decisao" match "decisão", which matters for Portuguese notes. Every claim version is indexed, and search joins `current_claims`, so old text never matches.
- **Stable row ids.** Tables behind search have an `INTEGER PRIMARY KEY seq`, because SQLite may renumber implicit rowids on `VACUUM`, which would break the search index.

## Left to the service code

The schema can't enforce these on its own:
- **Evidence for every claim** about completed work, decisions, commitments and deadlines.
- **One session note per day.**
- **Copying evidence links** forward to a new claim version.
- **Deletion only through the frontend.** There's no SQL-level notion of who is calling.
- **Contradictions are never overwritten silently:** the new claim gets a `contradicts` link and both are shown.
- **Retention cleanup**, using `retention.days` per source kind or claim category.
- **Writing to `audit_log`** for every collect, change and delete.
- **`PRAGMA foreign_keys = ON`** on every connection.

## Event ids and types (Phase 1)

| Type | Id | Notes |
|---|---|---|
| `git.commit` | `git:commit:<sha>` | Author time and offset come from Git. Same sha in two clones is one event. |
| `git.merge` | `git:merge:<sha>` | Commits with more than one parent. |
| `git.push` | `git:push:<repo id>:<branch>:<sha>` | Inferred when the remote-tracking ref moves to include local commits. |
| `git.snapshot` | `git:snapshot:<repo id>:<observed_at>` | Branch, head, ahead/behind and uncommitted-change counts. Written only when they differ from the last snapshot. |
| `claude_code.session` | `claude_code:session:<session uuid>` | `payload_ref` is the session file. Gets `gone_at` when Claude Code deletes the file. |

| `firefox.visit` | `firefox:visit:<place guid>:<visit time µs>` | Phase 4. `payload`: `url` (cleaned), `site`, `how` (link, typed, bookmark, redirect). Stable across Firefox rebuilding its database. Gets `gone_at` when I delete the visit in Firefox. |
| `app.focus` | `app:focus:<start unix time>` | Phase 4. One continuous span on one window, not one per 10-second sample; `title` is the window title (redacted) in mode titles; `payload`: `app`, `seconds`. The open span is written as it stands and grows under the same id. |
| `app.active` / `app.idle` | `app:active:<start>` / `app:idle:<start>` | Phase 4. Active time with no window details (mode time, or no extension), and idle time, which starts at the last input. |

Phase 3 will add `meeting.recording` and `notes.file`.

Schema 5 (Phase 4) adds `settings` (`app_usage.mode`), and indexes a visit's address and a span's app for search.

Schema 6 records the type on each claim version, since I can change it in the frontend; `claims.type` keeps the type Claude first proposed (`current_claims.proposed_type`), which the metrics judge Claude's proposals by.

## Decided (2 Nov 2026)

1. **Projects:** one project per allowlisted repository, created automatically with a `repo_path` alias. I rename projects and edit their aliases in the frontend. Claude adds online aliases (GitHub, Notion, Drive, Gmail, Chat, calendar) through `add_project_alias`, and only I remove them.
2. **Session notes:** one per project per workday, keyed by `(project_id, about_day)`. Saving again for the same pair adds a version instead of a second note. This is service code, because both fields live on versions.
3. **Unconfirmed claims older than 3 months are deleted**, as the brief says. `retention.unconfirmed_claim` sets the period, and the deletion goes into `audit_log`.
