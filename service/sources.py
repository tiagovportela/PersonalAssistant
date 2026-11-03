"""The allowlist: which repositories the layer reads. Nothing is collected
until I add it here (default deny). Adding a repository also creates its
project and turns on the Claude Code index, which only covers sessions inside
allowlisted repositories. Firefox history is added the same way, once, and is
then read in full (the brief's one exception)."""

import os
import re
import subprocess
from pathlib import Path

import collect_firefox
import collect_git
import paths
import store
from batch import CollectorError

SKIP_DIRS = {"node_modules", "venv", "site-packages", "__pycache__", "dist", "build", "target", "__MACOSX"}
MAX_DEPTH = 4  # how far below a folder to look for repositories

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


def find_repos(folder):
    """Git repositories in a folder, up to MAX_DEPTH levels down. Doesn't look inside a repository it
    found, or inside hidden folders and dependency or build folders."""
    found = []

    def walk(directory, depth):
        if (directory / ".git").exists():
            found.append(directory)
            return
        if depth == MAX_DEPTH:
            return
        try:
            children = sorted(p for p in directory.iterdir() if p.is_dir() and not p.is_symlink()
                              and not p.name.startswith(".") and p.name not in SKIP_DIRS)
        except PermissionError:
            return
        for child in children:
            walk(child, depth + 1)

    walk(folder, 0)
    return found


def add_path(db, path):
    """Allowlists a repository, or every repository found in a folder.

    Running it again on the same folder adds repositories created since. A repository
    found this way that I disabled stays disabled."""
    path = Path(path).expanduser()
    if not path.is_dir():
        raise CollectorError(f"{path} isn't a folder or a Git repository.")
    if (path / ".git").exists():
        return [add_repo(db, path)]
    # Repositories below the folder win over one around it, so ~/Projects inside a
    # dotfiles repository in ~ means the projects, not the whole home folder.
    repos = find_repos(path)
    if repos:
        results = []
        for repo in repos:
            try:
                results.append(add_repo(db, repo, reenable=False))
            except CollectorError:  # e.g. a .git folder left over from a copy, not a real repository
                results.append({"source_id": None, "project": None, "path": str(repo),
                                "status": "skipped: not a working Git repository"})
        return results
    try:
        return [add_repo(db, path)]  # a folder inside a repository
    except CollectorError:
        raise CollectorError(f"There are no Git repositories in {path}.") from None


def add_repo(db, path, reenable=True):
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
        if row and not row["enabled"] and not reenable:
            db.execute("ROLLBACK")
            return {"source_id": row["id"], "project": None, "path": top,
                    "status": f"disabled, left off (turn it on with: pwi enable {row['id']})"}
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


def add_firefox(db, profile=None):
    """Turns on Firefox history: the default profile, or the one given. Returns what happened."""
    if profile is None:
        found = collect_firefox.default_profile()
        if found is None:
            raise CollectorError("No Firefox profile with history was found. Open Firefox once, or give the "
                                 "profile folder: pwi add-firefox PATH (see about:profiles in Firefox).")
        profile, name = found
    else:
        profile, name = Path(profile).expanduser(), Path(profile).name
        if not (profile / "places.sqlite").is_file():
            raise CollectorError(f"{profile} isn't a Firefox profile with history (there's no places.sqlite).")
    profile = os.path.realpath(profile)
    now = store.now()
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT id, enabled FROM sources WHERE kind = 'firefox' AND locator = ?", (profile,)).fetchone()
        if row:
            status = "already on" if row["enabled"] else "turned on again"
            db.execute("UPDATE sources SET enabled = 1 WHERE id = ?", (row["id"],))
            source_id = row["id"]
        else:
            status = "turned on"
            source_id = db.execute("INSERT INTO sources (kind, locator, name, added_at) VALUES ('firefox', ?, 'Firefox', ?)",
                                   (profile, now)).lastrowid
        others = [r["id"] for r in db.execute("SELECT id FROM sources WHERE kind = 'firefox' AND enabled = 1 AND id <> ?",
                                              (source_id,))]
        db.execute("INSERT INTO audit_log (at, actor, action, item_type, item_id) VALUES (?, 'me', 'settings', 'source', ?)",
                   (now, str(source_id)))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return {"source_id": source_id, "profile": profile, "name": name, "status": status, "other_profiles_on": others}


def set_enabled(db, source_id, enabled):
    """Turns a source on or off. Its data stays; Claude stops seeing it while it's off."""
    changed = db.execute("UPDATE sources SET enabled = ? WHERE id = ?", (int(enabled), source_id)).rowcount
    if not changed:
        raise CollectorError(f"There's no source {source_id}. See: pwi sources")
    db.execute("INSERT INTO audit_log (at, actor, action, item_type, item_id) VALUES (?, 'me', 'settings', 'source', ?)",
               (store.now(), str(source_id)))


def list_sources(db):
    return [dict(r) for r in db.execute(SOURCES_SQL)]
