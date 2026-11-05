"""Imports Claude Code cloud sessions (claude.ai/code) into the layer.

A cloud session keeps its transcript in the cloud, and Anthropic documents no API
to list or download one. The documented way to bring one to this computer is
`claude --teleport <session id>`, run in a clean checkout of the same repository:
it checks out the session's branch and loads the conversation into a local
Claude Code session file. `pwi import-cloud-session` runs it, finds the session
file it wrote, and keeps a copy in DATA_DIR/claude_cloud with a sidecar naming
the repository. The Claude Code collector then indexes the copy like a local
session, so read_claude_sessions can show it.

`--list FILE` imports every listed session that's missing or was updated in the
cloud since its import, each in my checkout of its repository. Only a cloud
session can list my cloud sessions, so CLAUDE.md tells one how to write the file.

A transcript obtained another way can be imported with --file; a cloud
transcript's working folder (/home/user/<repo>) is matched to the allowlisted
repository of the same name.
"""

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import paths
import store
from batch import CollectorError
from collect_claude_code import allowlisted_repos, is_inside, read_session

CLOUD_ID = re.compile(r"\b((?:session|cse)_[A-Za-z0-9]+)\b")


def cloud_session_id(text):
    """A session id, or the id inside a claude.ai/code link."""
    match = CLOUD_ID.search(text or "")
    if not match:
        raise CollectorError(f"'{text}' isn't a cloud session id (session_... or cse_...) or a claude.ai/code link.")
    return match.group(1)


def repository_for(db, folder):
    """The allowlisted repository containing `folder`, and its project."""
    folder = Path(os.path.realpath(folder))
    for repo, project in allowlisted_repos(db):
        if is_inside(folder, repo):
            return repo, project
    raise CollectorError(f"{folder} isn't inside an allowlisted repository. Run this from your checkout of the "
                         "session's repository, or pass --repo; allowlist it first with: pwi add-repo PATH")


def repository_by_name(db, cwd):
    """The allowlisted repository named like a cloud session's working folder, e.g. /home/user/<repo>."""
    name = Path(cwd).name if cwd else None
    matches = [(repo, project) for repo, project in allowlisted_repos(db) if name and repo.name == name]
    if len(matches) != 1:
        found = "none" if not matches else ", ".join(str(r) for r, _ in matches)
        raise CollectorError(f"Can't tell which allowlisted repository the session in {cwd} belongs to "
                             f"(matches: {found}). Pass --repo PATH.")
    return matches[0]


def session_files():
    root = paths.CLAUDE_PROJECTS
    found = {}
    for path in root.glob("*/*.jsonl") if root.is_dir() else []:
        try:
            found[path] = path.stat().st_mtime_ns
        except FileNotFoundError:
            pass
    return found


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout.strip()


def teleport(repo, session_id, run=subprocess.run):
    """Runs `claude --teleport` in the repository and returns the session file it wrote or changed."""
    if run is subprocess.run and shutil.which("claude") is None:
        raise CollectorError("Claude Code ('claude') isn't on PATH, so the session can't be teleported. "
                             "Install it, or import a transcript you have with --file.")
    if git(repo, "status", "--porcelain"):
        raise CollectorError(f"{repo} has uncommitted changes. Teleport needs a clean checkout: "
                             "commit or stash them, then try again.")
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    before = session_files()
    print(f"Opening the cloud session {session_id} in {repo}.\n"
          "Once the conversation has loaded, quit Claude Code (/exit) to finish the import.", flush=True)
    code = run(["claude", "--teleport", session_id], cwd=str(repo)).returncode
    changed = [p for p, mtime in session_files().items() if before.get(p) != mtime]
    if branch and branch != "HEAD" and git(repo, "rev-parse", "--abbrev-ref", "HEAD") != branch:
        if git(repo, "status", "--porcelain"):
            print(f"Teleport left {repo} on another branch, with changes; it isn't switched back to {branch}.")
        else:
            git(repo, "checkout", "-q", branch)
            print(f"Switched {repo} back to {branch}.")
    if not changed:
        raise CollectorError(f"claude --teleport {'exited with ' + str(code) if code else 'finished'} without writing a "
                             "session file, so there's nothing to import. Check you're signed in to the same claude.ai "
                             "account, or import a transcript you have with --file.")
    sessions = {p: read_session(p) or {} for p in changed}
    inside = [p for p in changed if sessions[p].get("cwd") and is_inside(sessions[p]["cwd"], repo)]
    return max(inside or changed, key=lambda p: p.stat().st_mtime_ns)


def imported():
    """{cloud session id: (copy, sidecar)} for the cloud sessions already imported."""
    found = {}
    for path in sorted(paths.CLAUDE_CLOUD.glob("*.json")) if paths.CLAUDE_CLOUD.is_dir() else []:
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and meta.get("cloud_session") and path.with_suffix(".jsonl").exists():
            found[meta["cloud_session"]] = (path.with_suffix(".jsonl"), meta)
    return found


def import_session(db, session=None, file=None, repo=None, run=subprocess.run):
    """Copies one cloud session into DATA_DIR/claude_cloud. Returns what was imported."""
    session_id = cloud_session_id(session) if session else None
    if file is None:
        if session_id is None:
            raise CollectorError("Give a cloud session id or link, or a transcript with --file.")
        repo, project = repository_for(db, repo or os.getcwd())
        source = teleport(repo, session_id, run)
    else:
        source = Path(file).expanduser()
        if not source.is_file():
            raise CollectorError(f"There's no file {source}.")
    meta = read_session(source)
    if meta is None:
        raise CollectorError(f"{source} isn't a Claude Code session transcript (no timestamped entries).")
    if file is not None:
        repo, project = repository_for(db, repo) if repo else repository_by_name(db, meta["cwd"])
    paths.CLAUDE_CLOUD.mkdir(parents=True, exist_ok=True, mode=0o700)
    earlier = imported().get(session_id) if session_id else None
    if earlier:
        # Imported before: keep its name, so it stays one session, and remember the new local file it came from.
        name, local_files = earlier[0].stem, sorted(set(earlier[1].get("local_files", [])) | {source.stem})
    else:
        # A teleported file keeps its name, so it stays the same session as the local file; a transcript
        # imported with --file may have been renamed, so it's named after the session id it records.
        name = source.stem if file is None or not re.fullmatch(r"[\w-]+", meta["session_id"] or "") else meta["session_id"]
        local_files = [source.stem] if file is None else []
    copy = paths.CLAUDE_CLOUD / f"{name}.jsonl"
    replaced = copy.exists()
    shutil.copy2(source, copy)
    copy.with_suffix(".json").write_text(json.dumps(
        {"repo": str(repo), "cloud_session": session_id, "imported_at": store.now(), "imported_from": str(source),
         "local_files": local_files}, indent=2) + "\n", encoding="utf-8")
    return {"session_file": name, "project": project, "repo": str(repo), "title": meta["title"],
            "prompts": meta["prompts"], "copy": str(copy), "replaced": replaced}


# A list of cloud sessions -----------------------------------------------------
# Only a cloud session can list my cloud sessions (CLAUDE.md says how). Its list is JSON:
# {"sessions": [{"id", "title", "updated_at", "environment_kind", "repos": ["owner/repo"]}]};
# a plain file with one id or claude.ai/code link per line works too.

def read_list(path):
    text = Path(path).expanduser().read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except ValueError:
        return [{"id": cloud_session_id(line)} for line in text.splitlines() if line.strip() and not line.startswith("#")]
    items = data.get("sessions") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise CollectorError(f"{path} has no list of sessions.")
    sessions = []
    for item in items:
        item = {"id": item} if isinstance(item, str) else item
        if not isinstance(item, dict) or not item.get("id"):
            raise CollectorError(f"{path}: every session needs an id.")
        sessions.append({**item, "id": cloud_session_id(item["id"])})
    return sessions


def parse_time(text):
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def state_of(session, done):
    """missing, stale (updated in the cloud since it was imported) or current."""
    if session["id"] not in done:
        return "missing"
    updated, imported_at = parse_time(session.get("updated_at")), parse_time(done[session["id"]][1].get("imported_at"))
    return "stale" if updated and imported_at and updated > imported_at else "current"


def checkout_for(db, repos):
    """My allowlisted checkout of one of these GitHub repositories (owner/repo), through the project's alias."""
    for name in repos or []:
        name = re.sub(r"^https://github\.com/|\.git$", "", str(name)).strip("/").lower()
        for row in db.execute(
                "SELECT s.locator, a.project_id FROM project_aliases g"
                " JOIN project_aliases a ON a.project_id = g.project_id AND a.kind = 'repo_path'"
                " JOIN sources s ON s.kind = 'git_repo' AND s.locator = a.value AND s.enabled = 1"
                " WHERE g.kind = 'github_repo' AND lower(g.value) = ?", (name,)):
            return Path(row["locator"]), row["project_id"]
    return None


def import_list(db, path, repo=None, dry_run=False, run=subprocess.run, say=print):
    """Imports every listed cloud session that's missing or out of date. Returns one result per session."""
    done, results = imported(), []
    for session in read_list(path):
        label = f"{session['id']}" + (f" ({session['title']})" if session.get("title") else "")
        result = {"id": session["id"], "state": state_of(session, done)}
        results.append(result)
        if session.get("environment_kind") not in (None, "anthropic_cloud"):
            result["outcome"] = "skipped: it ran on a computer, so the Claude Code collector already has it"
        elif result["state"] == "current":
            result["outcome"] = "up to date"
        elif session.get("repos"):
            found = checkout_for(db, session["repos"])
            if found is None:
                result["outcome"] = f"skipped: {', '.join(session['repos'])} isn't an allowlisted repository"
            else:
                result["checkout"] = str(found[0])
        else:
            try:
                result["checkout"] = str(repository_for(db, repo or os.getcwd())[0])
            except CollectorError as e:
                result["outcome"] = f"skipped: {e}"
        if "outcome" in result or dry_run:
            result.setdefault("outcome", f"would import ({result['state']}) in {result.get('checkout')}")
            say(f"{label}: {result['outcome']}")
            continue
        say(f"{label}: {result['state']}, importing...")
        try:
            imported_one = import_session(db, session["id"], repo=result["checkout"], run=run)
            result["outcome"] = f"imported into project '{imported_one['project']}'"
        except CollectorError as e:
            result["outcome"] = f"failed: {e}"
        say(f"{label}: {result['outcome']}")
    return results
