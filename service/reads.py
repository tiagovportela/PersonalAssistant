"""The read tools: what Claude sees of the store.

Every query goes through the *_for_claude views, so disabled sources,
confidential items and retracted claims never appear. Result shapes follow
contracts/README.md. Each function takes an open connection and the validated
arguments, and returns a dict; handlers.py adds the coverage block.
"""

import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from collect_claude_code import is_prompt
from redact import redact

SESSION_FILE_DAYS = 30  # Claude Code deletes session files this long after their last change
OPEN = "('proposed', 'supported', 'disputed')"  # statuses Claude may use; retracted and superseded never appear
LABELS = {"supported": "verified", "proposed": "unconfirmed", "disputed": "disputed"}
GROUPS = {"git.commit": "commits", "git.merge": "merges", "git.push": "pushes", "claude_code.session": "sessions"}
EVENT_KINDS = {"git": "e.type LIKE 'git.%'", "claude_code": "e.type LIKE 'claude_code.%'"}
NOT_CONFIDENTIAL_PROJECT = ("NOT EXISTS (SELECT 1 FROM labels l WHERE l.item_type = 'project'"
                            " AND l.item_id = {column})")


# Shapes ----------------------------------------------------------------------

def local_time(utc_text, offset_min):
    if not utc_text:
        return None
    moment = datetime.strptime(utc_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone(timedelta(minutes=offset_min))).isoformat(timespec="minutes")


def brief_event(e):
    """An event as Claude sees it in lists: its id to cite, when, what, and the numbers that matter."""
    p = json.loads(e["payload"])
    item = {"event_id": e["id"], "type": e["type"], "at": local_time(e["occurred_at"], e["utc_offset_min"])}
    if e["ended_at"]:
        item["until"] = local_time(e["ended_at"], e["utc_offset_min"])
    if e["title"]:
        item["title"] = e["title"]
    if e["actor"] != "me":
        item["actor"] = e["actor"]
    if e["type"] in ("git.commit", "git.merge"):
        item.update({k: p.get(k) for k in ("files_changed", "insertions", "deletions")})
    elif e["type"] == "git.push":
        item.update({k: p.get(k) for k in ("branch", "commits")})
    elif e["type"] == "claude_code.session":
        item["prompts"] = p.get("prompts")
    elif e["type"] == "git.snapshot":
        item.update({k: p.get(k) for k in ("branch", "head", "upstream", "ahead", "behind",
                                           "staged", "unstaged", "untracked", "conflicted")})
    if e["gone_at"]:
        item["gone"] = True  # rebased away, or the session file was deleted
    return {k: v for k, v in item.items() if v is not None}


def evidence_list(db, claim_id, version):
    rows = db.execute(
        "SELECT ev.*, a.kind AS artifact_kind, a.title, a.url FROM claim_evidence ce"
        " JOIN evidence ev ON ev.id = ce.evidence_id LEFT JOIN artifacts a ON a.id = ev.artifact_id"
        " WHERE ce.claim_id = ? AND ce.version = ? ORDER BY ev.id", (claim_id, version))
    items = []
    for r in rows:
        item = {"evidence_id": r["id"], "event_id": r["event_id"], "artifact_id": r["artifact_id"],
                "artifact_kind": r["artifact_kind"], "title": r["title"], "url": r["url"],
                "read_at": r["read_at"], "expired_at": r["expired_at"]}
        items.append({k: v for k, v in item.items() if v is not None})
    return items


def claim_item(db, c, today=None):
    item = {"claim_id": c["id"], "type": c["type"], "text": c["text"], "label": LABELS[c["status"]],
            "project": c["project_id"], "version": c["version"]}
    for key in ("about_day", "due_at", "owner", "confidence"):
        if c[key] is not None:
            item[key] = c[key]
    if today:
        item["age_days"] = (today - date.fromisoformat(c["first_proposed_at"][:10])).days
    item["evidence"] = evidence_list(db, c["id"], c["version"])
    return item


def claims(db, where="1", params=(), order="first_proposed_at", today=None):
    rows = db.execute(f"SELECT * FROM claims_for_claude WHERE status IN {OPEN} AND ({where}) ORDER BY {order}", params)
    return [claim_item(db, c, today) for c in rows.fetchall()]


def unconfirmed_count(db, where="1", params=()):
    return db.execute("SELECT COUNT(*) FROM claims_for_claude WHERE status IN ('proposed', 'disputed')"
                      f" AND type <> 'session_note' AND ({where})", params).fetchone()[0]


def find_project(db, project_id):
    return db.execute("SELECT * FROM projects p WHERE id = ? AND "
                      + NOT_CONFIDENTIAL_PROJECT.format(column="p.id"), (project_id,)).fetchone()


def unknown_project(db, project_id):
    known = [r["id"] for r in db.execute("SELECT id FROM projects p WHERE "
                                         + NOT_CONFIDENTIAL_PROJECT.format(column="p.id") + " ORDER BY id LIMIT 60")]
    return {"found": False, "gaps": [f"There's no project '{project_id}'. Known projects: {', '.join(known) or 'none'}."]}


def day_gaps(db, day):
    """Why a day might be empty, so Claude can say more than 'nothing'."""
    gaps = [f"No local activity recorded on {day}."]
    when = date.fromisoformat(day)
    if when > date.today():
        gaps.append("That day hasn't happened yet.")
    elif when.weekday() >= 5:
        gaps.append(f"It was a {when.strftime('%A')}.")
    first = db.execute("SELECT MIN(local_day) FROM events_for_claude").fetchone()[0]
    if first is None:
        gaps.append("The layer has no events yet: no repository is allowlisted, or nothing has been collected.")
    elif day < first:
        gaps.append(f"The layer's oldest event is from {first}; older activity wasn't collected or has expired.")
    return gaps


# Tools -----------------------------------------------------------------------

def list_projects(db, args):
    projects = [dict(r) for r in db.execute(
        "SELECT p.id, p.name, p.status, (SELECT MAX(e.local_day) FROM events_for_claude e"
        " WHERE e.project_id = p.id AND e.type <> 'git.snapshot') AS last_activity_day FROM projects p WHERE "
        + NOT_CONFIDENTIAL_PROJECT.format(column="p.id")
        + " ORDER BY last_activity_day IS NULL, last_activity_day DESC, p.id")]
    aliases = db.execute("SELECT project_id, kind, value FROM project_aliases ORDER BY kind, value").fetchall()
    for p in projects:
        p["aliases"] = [{"kind": a["kind"], "value": a["value"]} for a in aliases if a["project_id"] == p["id"]]
    result = {"projects": projects, "found": bool(projects)}
    if not projects:
        result["gaps"] = ["The layer has no projects yet: no repositories are allowlisted (pwi add-repo)."]
    return result


def get_day(db, args):
    day = args["day"]
    groups = {}
    for e in db.execute("SELECT * FROM events_for_claude WHERE local_day = ? AND type <> 'git.snapshot'"
                        " ORDER BY occurred_at, id", (day,)):
        group = groups.setdefault(e["project_id"] or "(no project)", {})
        group.setdefault(GROUPS.get(e["type"], "other"), []).append(brief_event(e))
    for s in db.execute(
            "SELECT * FROM events_for_claude e WHERE e.type = 'git.snapshot' AND e.local_day = ? AND e.seq ="
            " (SELECT x.seq FROM events_for_claude x WHERE x.type = 'git.snapshot' AND x.local_day = e.local_day"
            "  AND x.project_id IS e.project_id ORDER BY x.occurred_at DESC, x.seq DESC LIMIT 1)", (day,)):
        if s["project_id"] in groups:  # a snapshot alone isn't activity
            groups[s["project_id"]]["end_of_day_state"] = brief_event(s)
    result = {
        "day": day,
        "events_by_project": groups,
        "claims": claims(db, "about_day = ? AND type <> 'session_note'", (day,)),
        "due": claims(db, "type = 'commitment' AND due_at IS NOT NULL AND substr(due_at, 1, 10) <= ?", (day,),
                      order="due_at"),
        "unconfirmed_count": unconfirmed_count(db),
        "session_notes": claims(db, "type = 'session_note' AND about_day = ?", (day,)),
    }
    result["found"] = bool(groups or result["claims"] or result["due"] or result["session_notes"])
    if not groups:
        result["gaps"] = day_gaps(db, day)
    return result


def get_week(db, args):
    picked = date.fromisoformat(args["week_of"])
    monday = picked - timedelta(days=picked.weekday())
    sunday = monday + timedelta(days=6)
    span = (monday.isoformat(), sunday.isoformat())
    by_project = {}
    milestones = []
    for e in db.execute("SELECT * FROM events_for_claude WHERE local_day BETWEEN ? AND ? AND type <> 'git.snapshot'"
                        " ORDER BY occurred_at", span):
        p = by_project.setdefault(e["project_id"] or "(no project)",
                                  {"commits": 0, "commits_by_others": 0, "merges": 0, "pushes": 0, "sessions": 0,
                                   "active_days": set()})
        if e["type"] == "git.commit":
            p["commits" if e["actor"] == "me" else "commits_by_others"] += 1
        elif e["type"] in GROUPS:
            p[GROUPS[e["type"]]] += 1
        p["active_days"].add(e["local_day"])
        if e["type"] == "git.merge":
            milestones.append({**brief_event(e), "project": e["project_id"]})
    for project, p in by_project.items():
        p["active_days"] = sorted(p["active_days"])
        p["claims"] = claims(db, "project_id IS ? AND about_day BETWEEN ? AND ? AND type <> 'session_note'",
                             (None if project == "(no project)" else project, *span))
    reference = min(date.today(), sunday)
    aging = (
        [{"kind": "overdue_commitment", **c} for c in claims(
            db, "type = 'commitment' AND due_at IS NOT NULL AND substr(due_at, 1, 10) < ?",
            (reference.isoformat(),), order="due_at", today=reference)]
        + [{"kind": "open_blocker", **c} for c in claims(db, "type = 'blocker'", today=reference)]
        + [{"kind": "long_unconfirmed", **c} for c in claims(
            db, "status = 'proposed' AND type NOT IN ('session_note', 'blocker') AND first_proposed_at < ?",
            ((reference - timedelta(days=7)).isoformat(),), today=reference)]
    )
    in_week = "(about_day BETWEEN ? AND ? OR substr(first_proposed_at, 1, 10) BETWEEN ? AND ?)"
    result = {"week": {"from": span[0], "to": span[1]}, "by_project": by_project, "milestones": milestones,
              "aging": aging, "unconfirmed_count": unconfirmed_count(db, in_week, span * 2)}
    result["found"] = bool(by_project or aging)
    if not by_project:
        result["gaps"] = [f"No local activity recorded from {span[0]} to {span[1]}."] + day_gaps(db, span[0])[2:]
    return result


def get_project(db, args):
    project = find_project(db, args["project"])
    if project is None:
        return unknown_project(db, args["project"])
    pid = project["id"]

    def latest(types, limit=1):
        marks = ", ".join("?" * len(types))
        return db.execute(f"SELECT * FROM events_for_claude WHERE project_id = ? AND type IN ({marks})"
                          " AND gone_at IS NULL ORDER BY occurred_at DESC, seq DESC LIMIT ?", (pid, *types, limit)).fetchall()

    snapshot = latest(["git.snapshot"])
    commits = latest(["git.commit", "git.merge"], 10)
    push = latest(["git.push"])
    state = None
    if snapshot or commits:
        state = {"observed_at": local_time(snapshot[0]["occurred_at"], snapshot[0]["utc_offset_min"]) if snapshot else None,
                 **({k: v for k, v in brief_event(snapshot[0]).items() if k not in ("event_id", "type", "at", "title")}
                    if snapshot else {}),
                 "last_commit": brief_event(commits[0]) if commits else None,
                 "last_push": brief_event(push[0]) if push else None}
    objective = claims(db, "project_id = ? AND type IN ('session_note', 'fact')", (pid,),
                       order="COALESCE(about_day, substr(version_at, 1, 10)) DESC, version_at DESC LIMIT 1")
    aliases = db.execute("SELECT kind, value FROM project_aliases WHERE project_id = ? ORDER BY kind, value",
                         (pid,)).fetchall()
    branch = json.loads(snapshot[0]["payload"]).get("branch") if snapshot else None
    lookups = []
    for a in aliases:
        if a["kind"] == "github_repo":
            lookups.append({"connector": "github", "query": f"Open pull requests in {a['value']}: mine, and those waiting for my review"})
            lookups.append({"connector": "github", "query": f"CI status and failing checks for branch {branch or 'the default branch'} in {a['value']}"})
        elif a["kind"] == "notion":
            lookups.append({"connector": "notion", "query": f"Open tasks in {a['value']}"})
        elif a["kind"] == "calendar_match":
            lookups.append({"connector": "google_calendar", "query": f"Upcoming meetings matching '{a['value']}'"})
    result = {
        "project": {"id": pid, "name": project["name"], "status": project["status"],
                    "aliases": [dict(a) for a in aliases]},
        "objective": objective[0] if objective else None,
        "state": state,
        "recent_sessions": [brief_event(e) for e in latest(["claude_code.session"], 5)],
        "recent_commits": [brief_event(e) for e in commits],
        "blockers": claims(db, "project_id = ? AND type = 'blocker'", (pid,)),
        "decisions": claims(db, "project_id = ? AND type = 'decision'", (pid,), order="version_at DESC LIMIT 10"),
        "commitments": claims(db, "project_id = ? AND type = 'commitment'", (pid,), order="due_at IS NULL, due_at"),
        "last_activity_day": db.execute("SELECT MAX(local_day) FROM events_for_claude WHERE project_id = ?"
                                        " AND type <> 'git.snapshot'", (pid,)).fetchone()[0],
        "lookups": lookups,
        "found": True,
    }
    gaps = []
    if not objective:
        gaps.append("No session note or fact is saved for this project yet; infer the objective from "
                    "recent_sessions and recent_commits, and label it unconfirmed.")
    if not any(a["kind"] == "github_repo" for a in aliases):
        gaps.append("This project has no GitHub remote, so open PRs and CI can't be looked up.")
    if state is None:
        gaps.append("No Git state has been collected for this project yet.")
    if gaps:
        result["gaps"] = gaps
    return result


# Common English and Portuguese endings, longest first, accents already folded: "redaction" also
# finds "redacted", "pushes" finds "push", "decisões" finds "decisão".
SUFFIXES = ("ations", "mente", "ation", "ings", "ions", "coes", "cao", "oes", "ing", "ion", "ers", "ies",
            "ao", "er", "ed", "es", "os", "as", "s")


def fold(word):
    return "".join(c for c in unicodedata.normalize("NFKD", word) if not unicodedata.combining(c))


def fts_query(text):
    """Plain keywords as an FTS5 query: any word matches; longer words also match as prefixes,
    and by their stem without a common ending."""
    terms = []
    for word in re.findall(r"\w+", fold(text.lower())):
        terms.append(f'"{word}"*' if len(word) >= 3 else f'"{word}"')
        stem = next((word[:-len(s)] for s in SUFFIXES if word.endswith(s) and len(word) - len(s) >= 3), None)
        if stem:
            terms.append(f'"{stem}"*')
    return " OR ".join(dict.fromkeys(terms)) or None


def search(db, args):
    query = fts_query(args["query"])
    if query is None:
        return {"results": [], "found": False, "gaps": ["The query has no words to search for."]}
    kinds = args.get("kinds") or ["git", "claude_code", "claims", "artifacts"]
    limit = args.get("limit", 20)
    project, since, until = args.get("project"), args.get("since"), args.get("until")
    found = []

    event_kinds = [EVENT_KINDS[k] for k in kinds if k in EVENT_KINDS]
    if event_kinds:
        sql = ("SELECT e.*, snippet(events_fts, -1, '«', '»', '…', 12) AS snip, bm25(events_fts, 2.0, 1.0) AS rank"
               " FROM events_fts JOIN events_for_claude e ON e.seq = events_fts.rowid"
               f" WHERE events_fts MATCH ? AND e.type <> 'git.snapshot' AND ({' OR '.join(event_kinds)})")
        params = [query]
        for clause, value in (("e.project_id = ?", project), ("e.local_day >= ?", since), ("e.local_day <= ?", until)):
            if value:
                sql += f" AND {clause}"
                params.append(value)
        for r in db.execute(sql + " ORDER BY rank LIMIT ?", (*params, limit)):
            found.append((r["rank"], {"item_type": "event", "id": r["id"], "project": r["project_id"],
                                      "local_day": r["local_day"], "snippet": r["snip"], **brief_event(r)}))

    if "claims" in kinds:
        day = "COALESCE(c.about_day, substr(c.version_at, 1, 10))"
        sql = ("SELECT c.*, snippet(claims_fts, 0, '«', '»', '…', 12) AS snip, bm25(claims_fts) AS rank"
               " FROM claims_fts JOIN claims_for_claude c ON c.seq = claims_fts.rowid"
               f" WHERE claims_fts MATCH ? AND c.status IN {OPEN}")
        params = [query]
        for clause, value in (("c.project_id = ?", project), (f"{day} >= ?", since), (f"{day} <= ?", until)):
            if value:
                sql += f" AND {clause}"
                params.append(value)
        for r in db.execute(sql + " ORDER BY rank LIMIT ?", (*params, limit)).fetchall():
            item = claim_item(db, r)
            found.append((r["rank"], {"item_type": "claim", "id": r["id"], "local_day": r["about_day"] or r["version_at"][:10],
                                      "snippet": r["snip"], **item}))

    if "artifacts" in kinds:
        sql = ("SELECT a.*, snippet(artifacts_fts, 0, '«', '»', '…', 12) AS snip, bm25(artifacts_fts) AS rank"
               " FROM artifacts_fts JOIN artifacts a ON a.seq = artifacts_fts.rowid WHERE artifacts_fts MATCH ?"
               " AND NOT EXISTS (SELECT 1 FROM labels l WHERE l.item_type = 'artifact' AND l.item_id = a.id)"
               " AND " + NOT_CONFIDENTIAL_PROJECT.format(column="a.project_id"))
        params = [query]
        if project:
            sql += " AND a.project_id = ?"
            params.append(project)
        for r in db.execute(sql + " ORDER BY rank LIMIT ?", (*params, limit)):
            found.append((r["rank"], {"item_type": "artifact", "id": r["id"], "kind": r["kind"], "title": r["title"],
                                      "url": r["url"], "project": r["project_id"], "snippet": r["snip"]}))

    found.sort(key=lambda pair: pair[0])  # bm25: lower is a better match
    results = [item for _, item in found[:limit]]
    result = {"query": args["query"], "results": results, "found": bool(results)}
    if not results:
        result["gaps"] = [f"Nothing matched '{args['query']}'. Try other wordings, in Portuguese and English, "
                          "or a file, branch or project name."]
    return result


def list_unconfirmed(db, args):
    today = date.today()
    where, params = ["status IN ('proposed', 'disputed')", "type <> 'session_note'"], []
    if args.get("project"):
        where.append("project_id = ?")
        params.append(args["project"])
    if args.get("since"):
        where.append("COALESCE(about_day, substr(first_proposed_at, 1, 10)) >= ?")
        params.append(args["since"])
    waiting = claims(db, " AND ".join(where), params, today=today)

    sql = ("SELECT e.local_day AS day, e.project_id AS project, COUNT(*) AS sessions,"
           " MIN(COALESCE(e.ended_at, e.occurred_at)) AS oldest_change FROM events_for_claude e"
           " WHERE e.type = 'claude_code.session' AND e.gone_at IS NULL AND e.project_id IS NOT NULL"
           " AND NOT EXISTS (SELECT 1 FROM claims_for_claude n WHERE n.type = 'session_note'"
           "  AND n.project_id = e.project_id AND n.about_day = e.local_day)")
    params = []
    for clause, value in (("e.project_id = ?", args.get("project")), ("e.local_day >= ?", args.get("since"))):
        if value:
            sql += f" AND {clause}"
            params.append(value)
    missing = [{"day": r["day"], "project": r["project"], "sessions": r["sessions"],
                "session_file_expires_on": (date.fromisoformat(r["oldest_change"][:10])
                                            + timedelta(days=SESSION_FILE_DAYS)).isoformat()}
               for r in db.execute(sql + " GROUP BY e.local_day, e.project_id ORDER BY day, project", params)]
    result = {"claims": waiting, "unconfirmed_count": len(waiting), "days_missing_session_notes": missing,
              "found": bool(waiting or missing)}
    if not result["found"]:
        result["gaps"] = ["Nothing is waiting: no unconfirmed claims, and every day with Claude Code sessions has a note."]
    return result


def full_event(db, event_id):
    e = db.execute("SELECT * FROM events_for_claude WHERE id = ?", (event_id,)).fetchone()
    if e is None:
        return None
    item = {**brief_event(e), "project": e["project_id"], "local_day": e["local_day"],
            "payload": json.loads(e["payload"]), "observed_at": e["observed_at"]}
    if e["changed_at"]:
        item["changed_at"] = e["changed_at"]
    if e["type"] == "claude_code.session":
        item["session_file"] = e["payload_ref"]
    status = "gone" if e["gone_at"] else "available"
    cited = [{"claim_id": r["id"], "label": LABELS[r["status"]], "text": r["text"]} for r in db.execute(
        f"SELECT DISTINCT c.id, c.status, c.text FROM claims_for_claude c JOIN claim_evidence ce"
        f" ON ce.claim_id = c.id AND ce.version = c.version JOIN evidence ev ON ev.id = ce.evidence_id"
        f" WHERE ev.event_id = ? AND c.status IN {OPEN}", (event_id,))]
    return {"event": item, "status": status, "cited_by": cited}


def get_evidence(db, args):
    if "event_id" in args:
        found = full_event(db, args["event_id"])
        if found is None:
            return {"found": False, "gaps": [f"No event {args['event_id']} is available."]}
        if found["status"] == "gone":
            found["gaps"] = ["The source record is gone: the commit was rebased away, or Claude Code deleted the session file."]
        return {**found, "found": True}

    ev = db.execute("SELECT * FROM evidence WHERE id = ?", (args["evidence_id"],)).fetchone()
    if ev is None:
        return {"found": False, "gaps": [f"No evidence {args['evidence_id']}."]}
    result = {"evidence_id": ev["id"], "found": True}
    if ev["expired_at"] and not ev["event_id"]:
        return {**result, "status": "expired", "expired_at": ev["expired_at"],
                "gaps": ["The event behind this evidence was removed by retention. Say the evidence has expired."]}
    if ev["event_id"]:
        found = full_event(db, ev["event_id"])
        if found is None:
            return {"found": False, "gaps": [f"No evidence {args['evidence_id']} is available."]}
        return {**result, **found}
    a = db.execute("SELECT * FROM artifacts a WHERE id = ? AND NOT EXISTS (SELECT 1 FROM labels l WHERE"
                   " l.item_type = 'artifact' AND l.item_id = a.id) AND "
                   + NOT_CONFIDENTIAL_PROJECT.format(column="a.project_id"), (ev["artifact_id"],)).fetchone()
    if a is None:
        return {"found": False, "gaps": [f"No evidence {args['evidence_id']} is available."]}
    return {**result, "status": "online",
            "artifact": {"artifact_id": a["id"], "artifact_kind": a["kind"], "title": a["title"], "url": a["url"],
                         "project": a["project_id"]},
            "read_at": ev["read_at"], "source_version": ev["source_version"], "locator": ev["locator"],
            "gaps": ["Online evidence: re-read it through its connector. If its revision differs from source_version, "
                     "say 'source changed'; if it can't be read, say 'source unavailable'."]}


SESSION_PAGE_CHARS = 30000  # session text per read_claude_sessions page
MAX_TURN_CHARS = 4000
# Slash commands and their output, which Claude Code records as user messages.
NOISE = ("<local-command-", "<command-name>", "<command-message>")


def clip(text):
    return text if len(text) <= MAX_TURN_CHARS else text[:MAX_TURN_CHARS] + " […cut]"


def session_turns(path, offset_min):
    """My prompts and Claude's final reply to each: the text after its last tool call in that turn.
    Tool calls, tool output, thinking and subagent work are left out, and secrets are redacted."""
    turns, reply, reply_at = [], [], None

    def at(entry):
        try:
            moment = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
            return local_time(moment.strftime("%Y-%m-%dT%H:%M:%SZ"), offset_min)
        except (KeyError, TypeError, ValueError, AttributeError):
            return None

    def flush():
        if reply:
            turns.append({"role": "claude", "at": reply_at, "text": clip(redact("\n".join(reply).strip()))})

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict) or entry.get("isSidechain"):
                continue
            message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
            content = message.get("content")
            if entry.get("type") == "user" and not entry.get("isMeta") and is_prompt(message):
                text = content if isinstance(content, str) else "\n".join(
                    c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
                if not text.strip() or text.lstrip().startswith(NOISE):
                    continue
                flush()
                reply, reply_at = [], None
                turns.append({"role": "me", "at": at(entry), "text": clip(redact(text.strip()))})
            elif entry.get("type") == "assistant" and isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        reply = []  # what came before a tool call wasn't the final reply
                    elif block.get("type") == "text" and block.get("text", "").strip():
                        reply.append(block["text"])
                        reply_at = at(entry)
    flush()
    return turns


def read_claude_sessions(db, args):
    sql = ("SELECT * FROM events_for_claude WHERE type = 'claude_code.session' AND local_day = ? AND gone_at IS NULL")
    params = [args["day"]]
    if args.get("project"):
        sql += " AND project_id = ?"
        params.append(args["project"])
    sessions = db.execute(sql + " ORDER BY occurred_at, id", params).fetchall()
    start_session, start_turn = 0, 0
    if args.get("cursor"):
        m = re.fullmatch(r"(\d+):(\d+)", args["cursor"])
        if not m:
            return {"found": False, "gaps": ["That cursor isn't one read_claude_sessions returned. Start again without it."]}
        start_session, start_turn = int(m.group(1)), int(m.group(2))
    out, gaps, used, cursor = [], [], 0, None
    for i in range(start_session, len(sessions)):
        e = sessions[i]
        path = Path(e["payload_ref"])
        if not path.exists():
            gaps.append(f"{e['id']}: Claude Code has deleted the session file.")
            continue
        turns = session_turns(path, e["utc_offset_min"])
        first = start_turn if i == start_session else 0
        chunk = []
        for j in range(first, len(turns)):
            size = len(turns[j]["text"]) + 60
            if used + size > SESSION_PAGE_CHARS and (chunk or out):  # every page has at least one turn
                cursor = f"{i}:{j}"
                break
            chunk.append(turns[j])
            used += size
        if chunk or not cursor:
            out.append({"session_id": e["id"], "project": e["project_id"], "title": e["title"],
                        "start": local_time(e["occurred_at"], e["utc_offset_min"]),
                        "end": local_time(e["ended_at"], e["utc_offset_min"]),
                        **({"continued": True} if first else {}), "turns": chunk})
        if cursor:
            break
    result = {"day": args["day"], "sessions": out, "found": bool(out)}
    if cursor:
        result["cursor"] = cursor
        result["note"] = "More turns follow: call read_claude_sessions again with this cursor."
    if not sessions:
        gaps.append(f"No Claude Code sessions recorded on {args['day']}"
                    + (f" for project {args['project']}." if args.get("project") else "."))
    if gaps:
        result["gaps"] = gaps
    return result


def get_metrics(db, args):
    since = args.get("since") or (date.today() - timedelta(days=30)).isoformat()
    collectors = []
    for s in db.execute("SELECT * FROM sources s WHERE enabled = 1 AND NOT EXISTS (SELECT 1 FROM labels l"
                        " WHERE l.item_type = 'source' AND l.item_id = CAST(s.id AS TEXT)) ORDER BY id"):
        runs = db.execute("SELECT * FROM collector_runs WHERE source_id = ? AND started_at >= ? ORDER BY started_at",
                          (s["id"], since)).fetchall()
        ok = [r for r in runs if r["status"] == "ok"]
        times = [datetime.strptime(r["started_at"], "%Y-%m-%dT%H:%M:%SZ") for r in ok]
        times.append(datetime.now(timezone.utc).replace(tzinfo=None))
        gap = max((b - a for a, b in zip(times, times[1:])), default=timedelta(0))
        collectors.append({
            "source": f"git:{s['name']}" if s["kind"] == "git_repo" else s["kind"],
            "runs": len(runs), "failed_runs": len(runs) - len(ok),
            "last_success_at": ok[-1]["finished_at"] if ok else None,
            "longest_gap_hours": round(gap.total_seconds() / 3600, 1) if ok else None,
            "new_events": sum(r["inserted"] for r in ok), "corrections": sum(r["changed"] for r in ok),
            "duplicates_avoided": sum(r["unchanged"] for r in ok), "gone": sum(r["gone"] for r in ok),
            "last_error": runs[-1]["error"] if runs and runs[-1]["status"] == "error" else None,
        })
    claims_since = db.execute("SELECT c.id, c.type FROM claims c WHERE c.type <> 'session_note' AND c.created_at >= ?",
                              (since,)).fetchall()
    counts = {"proposed": len(claims_since), "confirmed": 0, "corrected": 0, "disputed": 0, "retracted": 0,
              "still_unconfirmed": 0}
    for c in claims_since:
        versions = db.execute("SELECT status, text FROM claim_versions WHERE claim_id = ? ORDER BY version",
                              (c["id"],)).fetchall()
        status = versions[-1]["status"]
        counts["confirmed"] += status == "supported"
        counts["disputed"] += status == "disputed"
        counts["retracted"] += status == "retracted"
        counts["still_unconfirmed"] += status == "proposed"
        counts["corrected"] += any(v["text"] != versions[0]["text"] for v in versions[1:])
    reviewed = counts["confirmed"] + counts["retracted"] + counts["corrected"]
    open_claims = db.execute(f"SELECT id, version FROM claims_for_claude WHERE status IN {OPEN} AND type <> 'session_note'").fetchall()
    cited = sum(bool(db.execute("SELECT 1 FROM claim_evidence WHERE claim_id = ? AND version = ? LIMIT 1",
                                (c["id"], c["version"])).fetchone()) for c in open_claims)
    return {
        "since": since,
        "collectors": collectors,
        "claims": counts,
        "claude_accuracy": {"confirmed_share": round(counts["confirmed"] / reviewed, 2) if reviewed else None,
                            "reviewed": reviewed},
        "citation_coverage": round(cited / len(open_claims), 2) if open_claims else None,
        "session_notes": db.execute("SELECT COUNT(*) FROM claims WHERE type = 'session_note' AND created_at >= ?",
                                    (since,)).fetchone()[0],
        "found": True,
    }


READS = {"list_projects": list_projects, "get_day": get_day, "get_week": get_week, "get_project": get_project,
         "search": search, "list_unconfirmed": list_unconfirmed, "get_evidence": get_evidence,
         "read_claude_sessions": read_claude_sessions, "get_metrics": get_metrics}
