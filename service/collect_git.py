"""Git collector for one allowlisted repository: commits, merges, pushes and
working-tree snapshots. It reads everything but stores metadata only (subject,
redacted message, author, times, files and line counts); code stays in the repo.

No hooks are installed, and Git runs with GIT_OPTIONAL_LOCKS=0 so a scan never
takes the index lock or gets in the way of my own Git commands.
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path

import store
from batch import Batch, CollectorError
from redact import redact

LOG_FORMAT = "%x1e%H%x1f%P%x1f%ae%x1f%at%x1f%ai%x1f%s%x1f%b%x1d"
MAX_FILES = 50  # file paths kept per commit
MAX_BODY = 2000
# Words like UTF-8 look like issue keys but aren't.
NOT_KEYS = {"UTF", "SHA", "ISO", "RFC", "TLS", "SSL", "AES", "RSA", "HTTP", "HTTPS", "MD", "IPV", "CVE", "GPL", "ES", "PEP"}
# Rule-based links to the same work elsewhere (FR4): what a commit message points at.
REFERENCES = (
    (re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/(?:pull|issues)/(\d+)"), lambda m, gh: f"github:{m[1]}#{m[2]}"),
    (re.compile(r"(?<![\w/&])#(\d{1,6})\b"), lambda m, gh: f"github:{gh}#{m[1]}" if gh else None),
    (re.compile(r"\b([A-Z][A-Z0-9]{1,9})-(\d{1,6})\b"), lambda m, gh: None if m[1] in NOT_KEYS else f"key:{m[1]}-{m[2]}"),
    (re.compile(r"https://(?:www\.)?notion\.so/\S*?([0-9a-f]{32})"), lambda m, gh: f"notion:{m[1]}"),
    (re.compile(r"https://docs\.google\.com/[a-z]+/d/([\w-]{20,})"), lambda m, gh: f"drive:{m[1]}"),
    (re.compile(r"https://drive\.google\.com/(?:file/d/|drive/folders/|open\?id=)([\w-]{20,})"), lambda m, gh: f"drive:{m[1]}"),
)


def references(text, github=None):
    """What a commit message points at: GitHub PRs and issues (#12 needs the repository's GitHub alias),
    issue keys such as ABC-123, and Notion, Google Docs and Drive links."""
    found = []
    for pattern, ref in REFERENCES:
        for match in pattern.finditer(text):
            value = ref(match, github)
            if value and value not in found:
                found.append(value)
    return found


def git(repo, *args):
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], env=env, capture_output=True,
                                encoding="utf-8", errors="replace", timeout=120)
    except FileNotFoundError:
        raise CollectorError("git isn't installed") from None
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, args, result.stdout, result.stderr)
    return result.stdout


def github_repo(url):
    """owner/repo for a GitHub remote URL, ignoring any credentials in it; None otherwise."""
    m = re.search(r"github\.com[:/]+([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def offset_min(iso_with_offset):
    """'+0100' at the end of `git log %ai` as minutes."""
    sign, hours, minutes = re.search(r"([+-])(\d{2})(\d{2})$", iso_with_offset).groups()
    return (1 if sign == "+" else -1) * (int(hours) * 60 + int(minutes))


def my_emails(repo):
    try:
        return {git(repo, "config", "--get", "user.email").strip().lower()} - {""}
    except subprocess.CalledProcessError:
        return set()


def collect(db, source, since):
    repo = Path(source["locator"])
    try:
        git(repo, "rev-parse", "--git-dir")
    except subprocess.CalledProcessError:
        raise CollectorError(f"{repo} is not a Git repository any more. Was it moved or deleted?") from None
    row = db.execute("SELECT project_id FROM project_aliases WHERE kind = 'repo_path' AND value = ?",
                     (str(repo),)).fetchone()
    project = row["project_id"] if row else None
    github = db.execute("SELECT value FROM project_aliases WHERE kind = 'github_repo' AND project_id = ? ORDER BY value",
                        (project,)).fetchone()
    batch = Batch()
    commits(repo, since, my_emails(repo), project, batch, github[0] if github else None)
    seen = [e["id"] for e in batch.events]
    batch.gone_ids = [r["id"] for r in db.execute(
        "SELECT id FROM events WHERE source_id = ? AND type IN ('git.commit', 'git.merge') AND gone_at IS NULL"
        " AND occurred_at >= ? AND id NOT IN (SELECT value FROM json_each(?))",
        (source["id"], store.utc(since), json.dumps(seen)))]
    pushes(repo, source["id"], since, project, batch)
    snapshot(db, repo, source["id"], project, batch)
    return batch


def commits(repo, since, me, project, batch, github=None):
    """Every commit reachable from a local or remote branch or tag, committed since `since`."""
    out = git(repo, "log", "--branches", "--remotes", "--tags", f"--since={store.utc(since)}",
              f"--format={LOG_FORMAT}", "--numstat", "--no-renames")
    for record in out.split("\x1e")[1:]:
        header, _, numstat = record.partition("\x1d")
        sha, parents, email, at, ai, subject, body = header.split("\x1f", 6)
        parents = parents.split()
        files, insertions, deletions = [], 0, 0
        for line in numstat.strip().splitlines():
            added, removed, path = line.split("\t", 2)
            files.append(path)
            insertions += int(added) if added.isdigit() else 0  # '-' for binary files
            deletions += int(removed) if removed.isdigit() else 0
        merge = len(parents) > 1
        payload = {"sha": sha, "parents": parents, "files_changed": len(files), "insertions": insertions,
                   "deletions": deletions, "files": files[:MAX_FILES]}
        if body.strip():
            payload["body"] = redact(body.strip())[:MAX_BODY]
        refs = references(redact(f"{subject}\n{body}"), github)
        if refs:
            payload["refs"] = refs
        batch.events.append({
            "id": f"git:{'merge' if merge else 'commit'}:{sha}",
            "type": "git.merge" if merge else "git.commit",
            "actor": "me" if email.lower() in me else email.lower(),
            "project_id": project,
            "occurred_at": store.utc(at),
            "utc_offset_min": offset_min(ai),
            "title": redact(subject)[:200],
            "payload": payload,
            "payload_ref": f"{repo}@{sha}",
        })


def pushes(repo, source_id, since, project, batch):
    """Pushes, from the remote-tracking refs' reflogs, where Git records each 'update by push' with its time."""
    for ref in git(repo, "for-each-ref", "--format=%(refname)", "refs/remotes").split():
        if ref.endswith("/HEAD"):
            continue
        try:
            entries = git(repo, "reflog", "show", "--date=unix", "--format=%H%x1f%gd%x1f%gs", ref, "--").splitlines()
        except subprocess.CalledProcessError:
            continue  # no reflog for this ref
        branch = ref.removeprefix("refs/remotes/")
        for i, entry in enumerate(entries):  # newest first
            sha, selector, message = entry.split("\x1f", 2)
            stamp = re.search(r"@\{(\d+)\}$", selector)
            if not message.startswith("update by push") or not stamp or int(stamp.group(1)) < since:
                continue
            ts = int(stamp.group(1))
            previous = entries[i + 1].split("\x1f", 1)[0] if i + 1 < len(entries) else None
            count = None
            if previous:
                try:
                    count = int(git(repo, "rev-list", "--count", f"{previous}..{sha}").strip())
                except subprocess.CalledProcessError:
                    pass  # the old tip was garbage-collected
            batch.events.append({
                "id": f"git:push:{source_id}:{branch}:{sha}",
                "type": "git.push",
                "project_id": project,
                "occurred_at": store.utc(ts),
                "utc_offset_min": store.local_offset_min(ts),
                "title": f"Pushed {count} commit{'s' if count != 1 else ''} to {branch}" if count else f"Pushed to {branch}",
                "payload": {"branch": branch, "sha": sha, "previous": previous, "commits": count},
                "payload_ref": f"{repo}@{sha}",
            })


def snapshot(db, repo, source_id, project, batch):
    """Branch, head, ahead/behind and uncommitted-change counts; written only when they change."""
    state = {"branch": None, "head": None, "upstream": None, "ahead": 0, "behind": 0,
             "staged": 0, "unstaged": 0, "untracked": 0, "conflicted": 0}
    for line in git(repo, "status", "--porcelain=v2", "--branch").splitlines():
        if line.startswith("# branch.oid "):
            state["head"] = None if line.endswith("(initial)") else line.split()[-1]
        elif line.startswith("# branch.head "):
            state["branch"] = None if line.endswith("(detached)") else line.split(" ", 2)[2]
        elif line.startswith("# branch.upstream "):
            state["upstream"] = line.split(" ", 2)[2]
        elif line.startswith("# branch.ab "):
            ahead, behind = line.split()[2:4]
            state["ahead"], state["behind"] = int(ahead), -int(behind)
        elif line.startswith(("1 ", "2 ")):
            xy = line.split()[1]
            state["staged"] += xy[0] != "."
            state["unstaged"] += xy[1] != "."
        elif line.startswith("u "):
            state["conflicted"] += 1
        elif line.startswith("? "):
            state["untracked"] += 1
    last = db.execute("SELECT payload FROM events WHERE source_id = ? AND type = 'git.snapshot'"
                      " ORDER BY occurred_at DESC, seq DESC LIMIT 1", (source_id,)).fetchone()
    if last and json.loads(last["payload"]) == state:
        return
    ts = int(time.time())
    now = store.utc(ts)
    changes = state["staged"] + state["unstaged"] + state["untracked"] + state["conflicted"]
    where = state["branch"] or "detached HEAD"
    batch.events.append({
        "id": f"git:snapshot:{source_id}:{now}",
        "type": "git.snapshot",
        "project_id": project,
        "occurred_at": now,
        "utc_offset_min": store.local_offset_min(ts),
        "title": f"{where} at {state['head'][:7] if state['head'] else 'no commits'}"
                 + (f", {changes} uncommitted change{'s' if changes != 1 else ''}" if changes else ""),
        "payload": state,
        "payload_ref": str(repo),
    })
