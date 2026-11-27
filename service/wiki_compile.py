"""The wiki's compile run: `pwi wiki compile`, started by itself after each end-of-day run (docs/knowledge_wiki.md).

For each page that needs it, the layer starts Claude Code headless (`claude -p`) once, with the compile run's
instructions (contracts/agent/wiki_compile.md) and the wiki's (contracts/instructions/wiki.md). Claude gets a few
of the layer's tools and nothing else: the reads it needs and propose_wiki_update. No connectors, no files, no
shell, no web: the run is in dontAsk mode, so anything off that list is denied without waiting, and its working
directory is an empty folder. Online content reaches the wiki only through the claims the end-of-day agent saved,
and repositories only through read_repo.

Which pages: the ones I name; with --all, every project's page; otherwise the stale pages, and project pages not
written yet whose project was active in the last ACTIVE_DAYS days, most recently active first, at most MAX_PAGES.
Each run is recorded in wiki_runs: the page, why, the versions before and after, turns and time, never the content.
"""

import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import eod
import paths
import reads
import store
import wiki

INSTRUCTIONS = eod.HERE.parent / "contracts" / "instructions" / "wiki.md"
TOOLS = ["get_wiki_page", "wiki_lint", "read_repo", "get_project", "list_projects", "search", "get_evidence",
         "propose_wiki_update"]
DENIED = ["Bash", "Read", "Glob", "Grep", "Edit", "Write", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch",
          "Task", "Agent"]
MAX_PAGES = 5
PAGE_TIMEOUT = 15 * 60
ACTIVE_DAYS = 30
REPLY_CHARS = 1500


def version(db, page_id):
    row = wiki.current(db, page_id)
    return row["version"] if row else 0


def last_active(db, project_id):
    if not project_id:
        return None
    return db.execute(f"SELECT MAX(local_day) FROM events_for_claude WHERE project_id = ? AND {reads.WORK}",
                      (project_id,)).fetchone()[0]


def pages_to_compile(db, pages=None, everything=False, limit=MAX_PAGES):
    """[(page, why)], in the order to compile them."""
    reader = wiki.Reader(db)
    if pages:
        picked = []
        for page_id in pages:
            page = reader.page(page_id)
            if page is None:
                raise eod.EodError(f"There's no wiki page {page_id}. pwi wiki status lists them.")
            picked.append((page, "asked for"))
        return picked
    since = (date.today() - timedelta(days=ACTIVE_DAYS)).isoformat()
    found = []
    for page in wiki.visible_pages(db):
        current = wiki.current(db, page["id"]) if page["stored"] else None
        active = last_active(db, page["project_id"]) or ""
        if everything and page["kind"] == "project":
            why = "not written yet" if current is None else "asked for every project's page"
        elif current is None:
            if page["kind"] != "project" or active < since:
                continue
            why = f"not written yet; the project was last active on {active}"
        else:
            stale = reader.staleness(page, current)
            if not stale["is_stale"]:
                continue
            why = "stale: " + " ".join(stale.get("why", []))
        found.append((active, page, why))
    found.sort(key=lambda f: f[0], reverse=True)
    return [(page, why) for _, page, why in (found if everything else found[:limit])]


def alive(pid):
    try:
        return b"wiki" in Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, ValueError):
        return False


def close_interrupted(db):
    """Marks as failed the runs still 'running' whose process is gone."""
    for r in db.execute("SELECT id, detail FROM wiki_runs WHERE status = 'running'").fetchall():
        pid = (r["detail"] or "").removeprefix("pid ")
        if not (pid.isdigit() and alive(int(pid))):
            db.execute("UPDATE wiki_runs SET status = 'failed', finished_at = ?, detail = ? WHERE id = ?",
                       (store.now(), "interrupted: it stopped before it finished", r["id"]))


def workdir():
    """An empty folder to run Claude in, so there's nothing for it to read."""
    folder = paths.RUNTIME_DIR / "wiki-compile"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(mode=0o700, parents=True)
    return folder


def compile_pages(db, pages=None, everything=False, limit=MAX_PAGES, each=None):
    """Runs Claude once per page that needs it. Returns one result per page: page, why, status, the versions
    before and after, detail, and Claude's reply."""
    settings = eod.settings(db)
    settings["claude"] = eod.find_claude(settings["claude"])
    close_interrupted(db)
    picked = pages_to_compile(db, pages, everything, limit)
    if not picked:
        return []
    folder = workdir()
    instructions = INSTRUCTIONS.read_text(encoding="utf-8")
    today = date.today()
    results = []
    for page, why in picked:
        before = version(db, page["id"])
        run_id = db.execute("INSERT INTO wiki_runs (page_id, reason, started_at, status, version_before, detail)"
                            " VALUES (?, ?, ?, 'running', ?, ?)",
                            (page["id"], why[:500], store.now(), before, f"pid {os.getpid()}")).lastrowid
        prompt = eod.render("wiki_compile", day=today.isoformat(), weekday=today.strftime("%A"), page=page["id"],
                            kind=page["kind"], title=page["title"], version=before, reason=why)
        prompt += "\n\n---\n\n" + instructions
        reply = None
        try:
            result = eod.ask_claude(settings, prompt, [f"mcp__pwi__{t}" for t in TOOLS], DENIED, folder, None,
                                    PAGE_TIMEOUT)
            after = version(db, page["id"])
            status = "ok"
            detail = eod.run_detail(result) + (f"; version {before} to {after}" if after != before else "; left as it was")
            reply = str(result.get("result") or "")[:REPLY_CHARS]
        except eod.EodError as e:
            after, status, detail = version(db, page["id"]), "failed", str(e)
        db.execute("UPDATE wiki_runs SET finished_at = ?, status = ?, version_after = ?, detail = ? WHERE id = ?",
                   (store.now(), status, after, detail[:1000], run_id))
        done = {"page": page["id"], "why": why, "status": status, "version_before": before, "version_after": after,
                "detail": detail, "reply": reply}
        results.append(done)
        if each:
            each(done)
    return results


def status(db):
    close_interrupted(db)
    runs = [dict(r) for r in db.execute("SELECT page_id, reason, started_at, status, version_before, version_after, detail"
                                        " FROM wiki_runs ORDER BY id DESC LIMIT 10")]
    catalog = wiki.get_wiki_page(db, {})
    return {"pages": catalog.get("pages", []), "due": [(p["id"], why) for p, why in pages_to_compile(db)],
            "runs": runs, "unit": (eod.UNIT_DIR / "pwi-wiki.service").exists()}


def interactive():
    """Claude's reply is printed only to a terminal: under systemd it would go to the journal, which keeps it
    past the layer's retention and deletes."""
    return sys.stdout.isatty()
