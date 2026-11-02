"""Claude Code collector: a metadata index of sessions in ~/.claude/projects.

Sessions are never copied. For each session file it stores the session id,
project, start and end time, Claude Code's own title for it (redacted), the
number of prompts and the file path. A session is indexed only if its working
folder is inside an allowlisted repository, so nothing else is read into the
store. Claude Code deletes session files after 30 days; the event is then
marked gone, and read_claude_sessions can no longer show it.
"""

import json
from datetime import datetime
from pathlib import Path

import store
from batch import Batch
from redact import redact

ALLOWLIST_SQL = """
SELECT s.locator AS repo, a.project_id FROM sources s
JOIN project_aliases a ON a.kind = 'repo_path' AND a.value = s.locator
WHERE s.kind = 'git_repo' AND s.enabled = 1
"""


def collect(db, source, since):
    root = Path(source["locator"])
    repos = sorted(((Path(r["repo"]), r["project_id"]) for r in db.execute(ALLOWLIST_SQL)),
                   key=lambda r: len(r[0].parts), reverse=True)  # deepest repo wins for nested repos
    allowlist = sorted(str(r) for r, _ in repos)
    cursor = json.loads(source["cursor"] or "{}")
    # A changed allowlist can make a skipped session relevant, so every file is read again.
    same_allowlist = cursor.get("allowlist") == allowlist
    known = cursor.get("files", {}) if same_allowlist else {}
    was_indexed = set(cursor.get("indexed", [])) if same_allowlist else set()
    files, indexed = {}, set()
    batch = Batch()
    for path in sorted(root.glob("*/*.jsonl")) if root.is_dir() else []:
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
            continue
        session = read_session(path)
        if not session or session["start"] < since:
            continue
        project = next((p for repo, p in repos if session["cwd"] and is_inside(session["cwd"], repo)), None)
        if project is None:
            continue
        indexed.add(key)
        batch.events.append({
            "id": f"claude_code:session:{session['id']}",
            "type": "claude_code.session",
            "project_id": project,
            "occurred_at": store.utc(session["start"]),
            "utc_offset_min": store.local_offset_min(session["start"]),
            "ended_at": store.utc(session["end"]),
            "title": redact(session["title"])[:200] if session["title"] else None,
            "payload": {"cwd": session["cwd"], "git_branch": session["git_branch"], "prompts": session["prompts"]},
            "payload_ref": str(path),
        })
    batch.gone_ids = [r["id"] for r in db.execute(
        "SELECT id, payload_ref FROM events WHERE source_id = ? AND type = 'claude_code.session' AND gone_at IS NULL",
        (source["id"],)) if not Path(r["payload_ref"]).exists()]
    batch.cursor = json.dumps({"allowlist": allowlist, "files": files, "indexed": sorted(indexed)})
    return batch


def is_inside(cwd, repo):
    cwd = Path(cwd)
    return cwd == repo or repo in cwd.parents


def read_session(path):
    """Metadata from one session file. Tolerant of lines it doesn't understand, since the format changes."""
    times, cwd, branch, title, prompts = [], None, None, None, 0
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
            branch = entry.get("gitBranch") or branch
            if entry.get("type") == "ai-title" and entry.get("aiTitle"):
                title = entry["aiTitle"]
            if entry.get("type") == "user" and not entry.get("isMeta") and not entry.get("isSidechain") \
                    and is_prompt(entry.get("message")):
                prompts += 1
    if not times:
        return None
    return {"id": path.stem, "start": int(min(times)), "end": int(max(times)), "cwd": cwd,
            "git_branch": branch, "title": title, "prompts": prompts}


def is_prompt(message):
    """A prompt I typed, as opposed to a tool result Claude Code records as a user message."""
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    return isinstance(content, list) and not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
