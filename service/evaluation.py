"""The 5-day evaluation (brief §11 and §16): compares what I hand-label for each
workday with what the layer collected and Claude saved, and checks that nothing
confidential or disabled reaches Claude.

Labels and reports are work data, so they live in ~/.local/share/pwi/evaluation,
never in the repository. A label file is plain text, one item per line:

    ## Decisions
    - billing-service: Retry failed invoices 3 times before alerting
    ## Commitments
    - billing-service: Send Ana the VAT notes | due 2026-11-13

What can't be measured automatically (did the briefing read well, was the next
action right) ends up as a tick list in the report.
"""

import json
import re
import statistics
import unicodedata
from contextlib import closing
from datetime import datetime, timedelta

import paths
import store

SECTIONS = {"worked on": "worked_on", "decisions": "decision", "commitments": "commitment",
            "blockers": "blocker", "unfinished": "unfinished"}
CLAIM_TYPES = ("decision", "commitment", "blocker", "unfinished")
STOPWORDS = {"that", "this", "with", "from", "have", "will", "were", "been", "they", "them", "then", "than", "when",
             "what", "which", "about", "into", "over", "para", "como", "mais", "pelo", "pela", "isto", "esta", "este",
             "foram", "sobre", "porque", "quando", "entre", "depois", "antes", "should", "would", "could", "the", "and"}
SUFFIXES = ("ations", "ation", "ings", "ions", "coes", "cao", "oes", "ing", "ion", "ers", "ies", "ao", "er", "ed",
            "es", "s")
MATCH = 0.5  # share of the shorter item's key terms two items must share to count as the same thing


def folder():
    return paths.DATA_DIR / "evaluation"


def label_path(day):
    return folder() / f"{day}.md"


# Label files -----------------------------------------------------------------

def template(db, day):
    projects = ", ".join(r[0] for r in db.execute("SELECT id FROM projects ORDER BY id")) or "none yet"
    return f"""# Workday {day}

Write what really happened, from memory and your own notes, before asking Claude about this day.
One item per line, as "- project: what". Leave a section empty if nothing fits.
Project ids: {projects}

## Worked on
-

## Decisions
-

## Commitments
Add "| due YYYY-MM-DD" when there's a deadline.
-

## Blockers
-

## Unfinished
-
"""


def parse(text):
    """{kind: [{project, text, due}]} from a label file. Lines that aren't items are ignored."""
    labels, section = {kind: [] for kind in SECTIONS.values()}, None
    for line in text.splitlines():
        heading = re.fullmatch(r"\s*##\s+(.+?)\s*", line)
        if heading:
            section = SECTIONS.get(heading.group(1).lower())
            continue
        item = re.fullmatch(r"\s*[-*]\s+(.*\S)\s*", line)
        if not section or not item:
            continue
        body = item.group(1)
        due = re.search(r"\|\s*due\s+(\d{4}-\d{2}-\d{2})\s*$", body, re.I)
        body = body[:due.start()].strip() if due else body
        project, _, what = body.partition(":") if ":" in body else ("", "", body)
        labels[section].append({"project": project.strip() or None, "text": what.strip() or project.strip(),
                                "due": due.group(1) if due else None})
    return labels


def resolve(db, name):
    """A project id from what I typed: its id, its name, or its folder name."""
    if not name:
        return None
    for sql in ("SELECT id FROM projects WHERE id = ?", "SELECT id FROM projects WHERE lower(name) = lower(?)",
                "SELECT project_id FROM project_aliases WHERE kind = 'repo_path' AND value LIKE '%/' || ?"):
        row = db.execute(sql, (name,)).fetchone()
        if row:
            return row[0]
    return None


# Matching --------------------------------------------------------------------

def terms(text):
    folded = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    out = set()
    for word in re.findall(r"\w+", folded):
        if len(word) < 3 or word in STOPWORDS:
            continue
        out.add(next((word[:-len(s)] for s in SUFFIXES if word.endswith(s) and len(word) - len(s) >= 3), word))
    return out


def similar(a, b):
    x, y = terms(a), terms(b)
    return bool(x and y) and len(x & y) / min(len(x), len(y)) >= MATCH


# Report ----------------------------------------------------------------------

def percent(part, whole):
    return f"{round(100 * part / whole)}%" if whole else "n/a"


def labelled_days(start=None, end=None):
    days = sorted(p.stem for p in folder().glob("????-??-??.md"))
    return [d for d in days if (not start or d >= start) and (not end or d <= end)]


def claims_for(db, days):
    """Claims Claude saved about these days, or created on them; retracted ones count too (they were saved)."""
    first, last = days[0], days[-1]
    return db.execute(
        "SELECT c.*, (SELECT text FROM claim_versions v WHERE v.claim_id = c.id AND v.version = 1) AS first_text"
        " FROM current_claims c WHERE COALESCE(c.about_day, substr(c.first_proposed_at, 1, 10)) BETWEEN ? AND ?",
        (first, last)).fetchall()


def leak_check(store_path, db, days, active_projects, labelled_texts):
    """Calls Claude's read tools over these days and looks for anything Claude must never see."""
    import handlers  # imported here: it needs the contracts folder on the path
    layer = handlers.Layer(store_path)
    forbidden = {r[0]: "confidential event" for r in db.execute("SELECT id FROM confidential_events")}
    forbidden |= {r[0]: "event from a disabled source" for r in db.execute(
        "SELECT e.id FROM events e JOIN sources s ON s.id = e.source_id WHERE s.enabled = 0")}
    forbidden |= {r[0]: "retracted or hidden claim" for r in db.execute(
        "SELECT id FROM current_claims WHERE id NOT IN (SELECT id FROM claims_for_claude)")}
    hidden_projects = [r[0] for r in db.execute("SELECT item_id FROM labels WHERE item_type = 'project'")]
    calls = [("get_day", {"day": d}) for d in days]
    calls += [("get_week", {"week_of": d}) for d in sorted({days[0], days[-1]})]
    calls += [("list_unconfirmed", {}), ("list_projects", {}), ("get_metrics", {})]
    calls += [("get_project", {"project": p}) for p in sorted(active_projects)]
    calls += [("search", {"query": t, "limit": 50}) for t in labelled_texts[:40]]
    calls += [("read_claude_sessions", {"day": d}) for d in days]
    found = []
    for name, args in calls:
        output = json.dumps(layer.call_tool(name, args), ensure_ascii=False)
        found += [(name, item, why) for item, why in forbidden.items() if item in output]
        found += [(name, p, "confidential project") for p in hidden_projects if f'"project": "{p}"' in output
                  or f'\\"project\\": \\"{p}\\"' in output]
    return len(calls), found


def report(store_path, days):
    """The report as Markdown, and its headline numbers."""
    with closing(store.connect(store_path)) as db:
        labels = {d: parse(label_path(d).read_text(encoding="utf-8")) for d in days}
        lines = [f"# Evaluation report, {days[0]} to {days[-1]}", "",
                 f"Labelled workdays: {len(days)} ({', '.join(days)}).", ""]
        unknown = sorted({i["project"] for d in labels.values() for items in d.values() for i in items
                          if i["project"] and resolve(db, i["project"]) is None})
        if unknown:
            lines += [f"Project names in your labels that match no project (fix them, then report again): "
                      f"{', '.join(unknown)}.", ""]

        # Activity coverage: project-days
        recorded = {(r["local_day"], r["project_id"]) for r in db.execute(
            "SELECT DISTINCT local_day, project_id FROM events WHERE type <> 'git.snapshot' AND local_day BETWEEN ? AND ?"
            " AND project_id IS NOT NULL", (days[0], days[-1])) if r["local_day"] in days}
        worked = {(d, resolve(db, i["project"])) for d in days for i in labels[d]["worked_on"] if resolve(db, i["project"])}
        seen = worked & recorded
        lines += ["## Activity", "",
                  f"You labelled {len(worked)} project-days of work; the layer recorded activity on {len(seen)} "
                  f"of them ({percent(len(seen), len(worked))}).", ""]
        if worked - seen:
            lines += ["Missed by the layer (is the repository allowlisted? was the work outside Git and Claude Code?):", ""]
            lines += [f"- {d}, {p}" for d, p in sorted(worked - seen)] + [""]
        if recorded - worked:
            lines += ["Recorded by the layer but not in your labels (real work you left out, or a colleague's commits?):", ""]
            lines += [f"- {d}, {p}" for d, p in sorted(recorded - worked)] + [""]

        # Claims against labels
        claims = claims_for(db, days)
        used = set()
        rows, missed = [], []
        for kind in CLAIM_TYPES:
            items = [(d, i) for d in days for i in labels[d][kind]]
            hits = 0
            for d, item in items:
                project = resolve(db, item["project"])
                pool = [c for c in claims if (project is None or c["project_id"] == project)
                        and (kind == "unfinished" or c["type"] in (kind, "session_note"))]
                match = next((c for c in pool if similar(item["text"], c["text"]) or similar(item["text"], c["first_text"])), None)
                if match:
                    hits += 1
                    used.add(match["id"])
                    continue
                signal = ""
                if kind == "unfinished" and project:
                    # The state at the end of that day, or the first one seen after it.
                    snap = db.execute("SELECT payload, local_day FROM events WHERE project_id = ? AND type = 'git.snapshot'"
                                      " AND local_day <= ? ORDER BY occurred_at DESC LIMIT 1", (project, d)).fetchone() \
                        or db.execute("SELECT payload, local_day FROM events WHERE project_id = ? AND type = 'git.snapshot'"
                                      " AND local_day > ? ORDER BY occurred_at LIMIT 1", (project, d)).fetchone()
                    if snap:
                        s = json.loads(snap["payload"])
                        changes = s["staged"] + s["unstaged"] + s["untracked"]
                        if changes or s["ahead"]:
                            signal = (f" (on {snap['local_day']} the layer saw {changes} uncommitted changes and "
                                      f"{s['ahead']} unpushed commits)")
                missed.append(f"- {kind}, {d}, {item['project'] or 'no project'}: {item['text']}{signal}")
            rows.append(f"| {kind.capitalize()} | {len(items)} | {hits} | {percent(hits, len(items))} |")
        lines += ["## Claims against your labels", "",
                  "| Kind | You labelled | Claude saved | Found |", "|---|---|---|---|", *rows, ""]
        if missed:
            lines += ["Not found among Claude's claims or session notes:", "", *missed, ""]
        extra = [c for c in claims if c["id"] not in used and c["type"] != "session_note"]
        if extra:
            lines += ["Claims Claude saved that match none of your labels. Judge each: right but not labelled, "
                      "a false commitment, or a completion that didn't happen?", ""]
            lines += [f"- [ ] {c['type']} `{c['id']}` ({c['status']}), {c['project_id'] or 'no project'}: {c['text']}"
                      for c in extra] + [""]

        # Deadlines
        due = [(d, i) for d in days for i in labels[d]["commitment"] if i["due"]]
        if due:
            lines += ["## Deadlines", ""]
            for d, item in due:
                project = resolve(db, item["project"])
                match = next((c for c in claims if c["type"] == "commitment" and (project is None or c["project_id"] == project)
                              and similar(item["text"], c["text"])), None)
                state = ("missing" if match is None else "right date" if (match["due_at"] or "")[:10] == item["due"]
                         else f"wrong date ({match['due_at'] or 'none'})")
                lines.append(f"- {item['text']} (due {item['due']}): {state}")
            lines.append("")

        # Evidence, confirmation, session notes
        open_claims = db.execute("SELECT id, version FROM current_claims WHERE status IN ('proposed', 'supported', 'disputed')"
                                 " AND type <> 'session_note'").fetchall()
        cited = sum(bool(db.execute("SELECT 1 FROM claim_evidence WHERE claim_id = ? AND version = ?", tuple(c)).fetchone())
                    for c in open_claims)
        statuses = [c["status"] for c in claims if c["type"] != "session_note"]
        corrected = sum(c["text"] != c["first_text"] for c in claims if c["type"] != "session_note")
        session_days = {(r[0], r[1]) for r in db.execute(
            "SELECT DISTINCT local_day, project_id FROM events WHERE type = 'claude_code.session' AND local_day BETWEEN ? AND ?",
            (days[0], days[-1])) if r[0] in days}
        noted = {(r[0], r[1]) for r in db.execute(
            "SELECT about_day, project_id FROM current_claims WHERE type = 'session_note' AND about_day BETWEEN ? AND ?",
            (days[0], days[-1]))}
        lines += ["## Evidence and confirmation", "",
                  f"- Citation coverage: {cited} of {len(open_claims)} open claims have evidence ({percent(cited, len(open_claims))}).",
                  f"- Of {len(statuses)} claims from these days: {statuses.count('supported')} confirmed, {corrected} corrected, "
                  f"{statuses.count('retracted')} retracted, {statuses.count('proposed')} still unconfirmed.",
                  f"- Session notes: {len(session_days & noted)} of {len(session_days)} project-days with Claude Code sessions "
                  f"have one ({percent(len(session_days & noted), len(session_days))}).", ""]

        # Collection health
        lines += ["## Collection", ""]
        start = days[0] + "T00:00:00Z"
        for s in db.execute("SELECT * FROM sources WHERE enabled = 1 ORDER BY id"):
            runs = db.execute("SELECT * FROM collector_runs WHERE source_id = ? AND started_at >= ? ORDER BY started_at",
                              (s["id"], start)).fetchall()
            ok = [datetime.strptime(r["started_at"], "%Y-%m-%dT%H:%M:%SZ") for r in runs if r["status"] == "ok"]
            gap = max((b - a for a, b in zip(ok, ok[1:])), default=timedelta(0))
            lines.append(f"- {s['name']}: {len(runs)} runs, {sum(r['status'] == 'error' for r in runs)} failed, "
                         f"longest gap {round(gap.total_seconds() / 3600, 1)} h, "
                         f"{sum(r['unchanged'] for r in runs)} duplicates avoided.")
        lags = sorted((datetime.strptime(r[0], "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(r[1], "%Y-%m-%dT%H:%M:%SZ"))
                      .total_seconds() / 60 for r in db.execute(
                          "SELECT observed_at, occurred_at FROM events WHERE type = 'git.commit' AND actor = 'me'"
                          " AND local_day BETWEEN ? AND ?", (days[0], days[-1])))
        if lags:
            lines.append(f"- Ingestion lag for your commits: median {round(statistics.median(lags))} min, "
                         f"slowest {round(lags[-1])} min. Commits seen more than 2 h late "
                         f"(collected after a shutdown or sleep): {sum(lag > 120 for lag in lags)}.")
        lines.append("")

        # No leaks
        active = {p for _, p in recorded} | {p for _, p in worked}
        texts = [i["text"] for d in days for kind in CLAIM_TYPES for i in labels[d][kind]]
        checked, leaks = leak_check(store_path, db, days, active, texts)
        lines += ["## No leaks", "",
                  f"{checked} calls to Claude's read tools over these days. Confidential or disabled items in their "
                  f"results: {len(leaks)}.", ""]
        lines += [f"- {tool} returned {item} ({why})" for tool, item, why in leaks] + ([""] if leaks else [])

        # What only I can judge
        lines += ["## Your checks in Claude Desktop", "",
                  "Tick each one you saw work. The brief's thresholds are set after this first week, from these numbers.", ""]
        lines += [f"- [ ] Daily briefing for {d}: correct, every claim cited and labelled" for d in days]
        lines += ["- [ ] Project resumption for one repository: right objective, state and next action",
                  "- [ ] End-of-day review listed every unconfirmed claim, including days you skipped",
                  "- [ ] Search answered a what, a when and a why question about the week, with evidence",
                  "- [ ] Weekly review covered milestones, aging work and risks for the week",
                  "- [ ] An ad-hoc task (a status update, meeting prep) used the layer without pasting, and showed its evidence",
                  "- [ ] Unconfirmed and verified were always distinguished, and Claude said not found instead of guessing",
                  "- [ ] Deleting in the frontend worked, including deciding on the claims that relied on it",
                  "- [ ] After a shutdown or restart, collection caught up on its own", ""]
        summary = {"days": len(days), "activity_recall": percent(len(seen), len(worked)),
                   "leaks": len(leaks), "unknown_projects": unknown}
        return "\n".join(lines), summary
