"""Claude Code collector: a metadata index of sessions in ~/.claude/projects.

Local sessions are never copied. For each session file it stores the session
id, project, start and end time, Claude Code's own title for it (redacted), the
number of prompts and the file path. A session is indexed only if its working
folder is inside an allowlisted repository, so nothing else is read into the
store. Claude Code deletes session files after 30 days; the event is then
marked gone, and read_claude_sessions can no longer show it.

Cloud sessions I imported (cloud_sessions.py) are copies in DATA_DIR/claude_cloud,
each with a sidecar naming its repository. They're indexed the same way, with
origin "cloud", and win over a local file of the same session, which only
refreshes the copy when it has grown. A copy stays until its session is deleted,
by retention or by me; the next pass then removes the copy too.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

import paths
import store
from batch import Batch
from redact import redact

ALLOWLIST_SQL = """
SELECT s.locator AS repo, a.project_id FROM sources s
JOIN project_aliases a ON a.kind = 'repo_path' AND a.value = s.locator
WHERE s.kind = 'git_repo' AND s.enabled = 1
"""


def allowlisted_repos(db):
    """(repository path, project) pairs, deepest first so nested repositories win."""
    return sorted(((Path(r["repo"]), r["project_id"]) for r in db.execute(ALLOWLIST_SQL)),
                  key=lambda r: len(r[0].parts), reverse=True)


def project_of(repos, folder):
    return next((p for repo, p in repos if folder and is_inside(folder, repo)), None)


def session_event_id(stem):
    return f"claude_code:session:{stem}"


def cloud_copies():
    """Imported cloud sessions: {session file stem: (copy, sidecar dict)}."""
    copies = {}
    for path in sorted(paths.CLAUDE_CLOUD.glob("*.jsonl")) if paths.CLAUDE_CLOUD.is_dir() else []:
        try:
            meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        copies[path.stem] = (path, meta if isinstance(meta, dict) else {})
    return copies


def remove_copy(path):
    path.unlink(missing_ok=True)
    path.with_suffix(".json").unlink(missing_ok=True)


def collect(db, source, since):
    root = Path(source["locator"])
    repos = allowlisted_repos(db)
    allowlist = sorted(str(r) for r, _ in repos)
    cursor = json.loads(source["cursor"] or "{}")
    # A changed allowlist can make a skipped session relevant, so every file is read again.
    same_allowlist = cursor.get("allowlist") == allowlist
    known = cursor.get("files", {}) if same_allowlist else {}
    was_indexed = set(cursor.get("indexed", [])) if same_allowlist else set()
    files, indexed = {}, set()
    batch = Batch()

    # A copy whose session was indexed before but no longer exists was deleted: remove the copy too.
    copies = cloud_copies()
    for stem in cursor.get("cloud_indexed", []):
        if stem in copies and db.execute("SELECT 1 FROM events WHERE id = ?", (session_event_id(stem),)).fetchone() is None:
            remove_copy(copies.pop(stem)[0])

    local = sorted(root.glob("*/*.jsonl")) if root.is_dir() else []
    for path in local:
        if path.stem in copies:  # the copy is what's indexed; a grown local file refreshes it
            copy = copies[path.stem][0]
            try:
                if path.stat().st_mtime_ns > copy.stat().st_mtime_ns:
                    shutil.copy2(path, copy)
            except OSError:
                pass
    candidates = [(p, None) for p in local if p.stem not in copies] + list(copies.values())
    cloud_indexed = set()
    for path, meta in candidates:
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        key = str(path)
        files[key] = [stat.st_size, stat.st_mtime_ns]
        if known.get(key) == files[key]:  # unchanged since the last pass
            if key in was_indexed:
                indexed.add(key)
                batch.cached += 1
                if meta is not None:
                    cloud_indexed.add(path.stem)
            continue
        session = read_session(path)
        if not session or (meta is None and session["start"] < since):  # an import is wanted whatever its age
            continue
        project = project_of(repos, meta.get("repo") if meta is not None else session["cwd"])
        if project is None:
            continue
        indexed.add(key)
        payload = {"cwd": session["cwd"], "git_branch": session["git_branch"], "prompts": session["prompts"]}
        if meta is not None:
            cloud_indexed.add(path.stem)
            payload.update({"origin": "cloud", "cloud_session": meta.get("cloud_session")})
        batch.events.append({
            "id": session_event_id(session["id"]),
            "type": "claude_code.session",
            "project_id": project,
            "occurred_at": store.utc(session["start"]),
            "utc_offset_min": store.local_offset_min(session["start"]),
            "ended_at": store.utc(session["end"]),
            "title": redact(session["title"])[:200] if session["title"] else None,
            "payload": payload,
            "payload_ref": key,
        })
    batch.gone_ids = [r["id"] for r in db.execute(
        "SELECT id, payload_ref FROM events WHERE source_id = ? AND type = 'claude_code.session' AND gone_at IS NULL",
        (source["id"],)) if not Path(r["payload_ref"]).exists()]
    # cloud_indexed survives an allowlist change, so a deleted session's copy is still recognised.
    batch.cursor = json.dumps({"allowlist": allowlist, "files": files, "indexed": sorted(indexed),
                               "cloud_indexed": sorted(cloud_indexed | (set(cursor.get("cloud_indexed", [])) & set(copies)))})
    return batch


def is_inside(cwd, repo):
    cwd = Path(cwd)
    return cwd == repo or repo in cwd.parents


def read_session(path):
    """Metadata from one session file. Tolerant of lines it doesn't understand, since the format changes."""
    times, cwd, branch, title, prompts, session_id = [], None, None, None, 0, None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if isinstance(entry.get("timestamp"), str):
                try:
                    times.append(datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")).timestamp())
                except ValueError:
                    pass
            cwd = cwd or entry.get("cwd")
            session_id = session_id or (entry.get("sessionId") if isinstance(entry.get("sessionId"), str) else None)
            branch = entry.get("gitBranch") or branch
            if entry.get("type") == "ai-title" and entry.get("aiTitle"):
                title = entry["aiTitle"]
            if entry.get("type") == "user" and not entry.get("isMeta") and not entry.get("isSidechain") \
                    and is_prompt(entry.get("message")):
                prompts += 1
    if not times:
        return None
    return {"id": path.stem, "start": int(min(times)), "end": int(max(times)), "cwd": cwd,
            "git_branch": branch, "title": title, "prompts": prompts, "session_id": session_id}


def is_prompt(message):
    """A prompt I typed, as opposed to a tool result Claude Code records as a user message."""
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    return isinstance(content, list) and not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
