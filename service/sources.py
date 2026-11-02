"""The allowlist: which repositories the layer reads. Nothing is collected
until I add it here (default deny). Adding a repository also creates its
project and turns on the Claude Code index, which only covers sessions inside
allowlisted repositories."""

import os
import re
import subprocess
from pathlib import Path

import collect_git
import paths
import store
from batch import CollectorError

SOURCES_SQL = """
SELECT s.id, s.kind, s.name, s.locator, s.enabled,
       (SELECT COUNT(*) FROM events e WHERE e.source_id = s.id AND e.gone_at IS NULL) AS events,
       r.status AS last_status, r.finished_at AS last_run_at, r.error AS last_error
FROM sources s
LEFT JOIN collector_runs r ON r.id = (SELECT MAX(id) FROM collector_runs WHERE source_id = s.id)
ORDER BY s.id
"""


def slug(name, taken):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def add_repo(db, path):
    """Allowlists one repository. Returns what happened, for the CLI to print."""
    path = Path(path).expanduser()
    try:
        top = os.path.realpath(collect_git.git(path, "rev-parse", "--show-toplevel").strip())
    except subprocess.CalledProcessError:
        raise CollectorError(f"{path} isn't inside a Git repository.") from None
    now = store.now()
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT id, enabled FROM sources WHERE kind = 'git_repo' AND locator = ?", (top,)).fetchone()
        if row:
            status = "already allowlisted" if row["enabled"] else "allowlisted again"
            db.execute("UPDATE sources SET enabled = 1 WHERE id = ?", (row["id"],))
            source_id = row["id"]
        else:
            status = "allowlisted"
            source_id = db.execute("INSERT INTO sources (kind, locator, name, added_at) VALUES ('git_repo', ?, ?, ?)",
                                   (top, Path(top).name, now)).lastrowid
        alias = db.execute("SELECT project_id FROM project_aliases WHERE kind = 'repo_path' AND value = ?",
                           (top,)).fetchone()
        if alias:
            project = alias["project_id"]
        else:
            project = slug(Path(top).name, {r["id"] for r in db.execute("SELECT id FROM projects")})
            db.execute("INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)", (project, Path(top).name, now))
            db.execute("INSERT INTO project_aliases VALUES ('repo_path', ?, ?, 'rule', ?)", (top, project, now))
        for remote in collect_git.git(top, "remote").split():
            github = collect_git.github_repo(collect_git.git(top, "remote", "get-url", remote))
            if github:
                db.execute("INSERT OR IGNORE INTO project_aliases VALUES ('github_repo', ?, ?, 'rule', ?)",
                           (github, project, now))
        db.execute("INSERT OR IGNORE INTO sources (kind, locator, name, added_at) VALUES ('claude_code', ?, 'Claude Code', ?)",
                   (str(paths.CLAUDE_PROJECTS), now))
        db.execute("INSERT INTO audit_log (at, actor, action, item_type, item_id) VALUES (?, 'me', 'settings', 'source', ?)",
                   (now, str(source_id)))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return {"source_id": source_id, "project": project, "path": top, "status": status}


def set_enabled(db, source_id, enabled):
    """Turns a source on or off. Its data stays; Claude stops seeing it while it's off."""
    changed = db.execute("UPDATE sources SET enabled = ? WHERE id = ?", (int(enabled), source_id)).rowcount
    if not changed:
        raise CollectorError(f"There's no source {source_id}. See: pwi sources")
    db.execute("INSERT INTO audit_log (at, actor, action, item_type, item_id) VALUES (?, 'me', 'settings', 'source', ?)",
               (store.now(), str(source_id)))


def list_sources(db):
    return [dict(r) for r in db.execute(SOURCES_SQL)]
