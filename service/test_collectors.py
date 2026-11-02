"""Checks secret redaction, the Git and Claude Code collectors, the runner and
the `pwi` CLI, against real Git repositories and session files in a temporary
home. Never reads the real ~/.claude or any real repository.

Run: python3 -I service/test_collectors.py
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pwi-test-"))
os.environ.update({"HOME": str(TMP), "XDG_DATA_HOME": str(TMP / "data"), "XDG_CONFIG_HOME": str(TMP / "config"),
                   "CLAUDE_CONFIG_DIR": str(TMP / "claude"), "GIT_CONFIG_GLOBAL": str(TMP / "gitconfig"),
                   "GIT_CONFIG_NOSYSTEM": "1"})
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import collect  # noqa: E402
import collect_git  # noqa: E402
import paths  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402
from batch import CollectorError  # noqa: E402
from redact import redact  # noqa: E402

TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4"
PROMPT = "please refactor the zanzibar module"  # must never reach the store


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def sh(cwd, *args, **env):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, env={**os.environ, **env})


def commit(repo, message, file="a.txt", email="me@example.com", date=None):
    with open(repo / file, "a") as f:
        f.write(message + "\n")
    sh(repo, "git", "add", file)
    env = {"GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_NAME": email.split("@")[0]}
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    sh(repo, "git", "commit", "-q", "-m", message, **env)


def session_file(project_dir, uuid, cwd, title, prompts, start="2026-11-02T09:00:00.000Z", end="2026-11-02T10:30:00.000Z"):
    project_dir.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "mode", "mode": "normal", "sessionId": uuid}]
    for i, p in enumerate(prompts):
        lines.append({"type": "user", "cwd": cwd, "sessionId": uuid, "gitBranch": "main", "timestamp": start if i == 0 else end,
                      "message": {"role": "user", "content": p}})
        lines.append({"type": "user", "cwd": cwd, "sessionId": uuid, "timestamp": end,
                      "message": {"role": "user", "content": [{"type": "tool_result", "content": "output"}]}})
    lines.append({"type": "ai-title", "aiTitle": title, "sessionId": uuid})
    path = project_dir / f"{uuid}.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\nnot json\n")
    return path


def events(db, kind=None):
    sql = "SELECT * FROM events" + (" WHERE type = ?" if kind else "") + " ORDER BY occurred_at, id"
    return [dict(r) for r in db.execute(sql, (kind,) if kind else ())]


def by_name(results):
    return {r["name"]: r for r in results}


def test_redact():
    check("redaction hides known token formats",
          TOKEN not in redact(f"use {TOKEN} here") and "sk-ant-" not in redact("key sk-ant-api03-abcdefghijklmnopqrstuv"))
    check("redaction hides labelled values but keeps the label",
          redact("password=hunter22 and api_key: 'abc123xyz'") == "password=[REDACTED] and api_key: '[REDACTED]'")
    check("redaction hides credentials in URLs and bearer tokens",
          redact("https://bob:s3cret@github.com/x") == "https://[REDACTED]@github.com/x"
          and redact("Authorization: Bearer abcdefghijklmnop1234") == "Authorization: Bearer [REDACTED]")
    check("redaction hides private keys", "MIIE" not in redact("-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----"))
    check("redaction leaves ordinary text alone",
          redact("Fix the token refresh bug in auth.py") == "Fix the token refresh bug in auth.py")
    check("github_repo reads owner/repo from SSH and HTTPS remotes, ignoring credentials",
          collect_git.github_repo("git@github.com:acme/widget.git") == "acme/widget"
          and collect_git.github_repo(f"https://bob:{TOKEN}@github.com/acme/widget") == "acme/widget"
          and collect_git.github_repo("/srv/git/widget.git") is None)


def main():
    test_redact()
    os.umask(0o077)
    store.create_or_check(paths.STORE_PATH)
    db = store.connect(paths.STORE_PATH)

    remote, work, other = TMP / "remote.git", TMP / "repos" / "work", TMP / "repos" / "other"
    sh(TMP, "git", "init", "-q", "--bare", str(remote))
    for repo in (work, other):
        repo.mkdir(parents=True)
        sh(repo, "git", "init", "-q", "-b", "main")
        sh(repo, "git", "config", "user.email", "Me@Example.com")
        sh(repo, "git", "config", "user.name", "Me")
    commit(work, "Start the service", date="2026-11-02T23:30:00+01:00")
    commit(work, f"Add config\n\nThe deploy token={TOKEN} goes in the keyring.", file="b.txt", email="ana@example.com")
    sh(work, "git", "checkout", "-q", "-b", "feature")
    commit(work, "Feature work", file="c.txt")
    sh(work, "git", "checkout", "-q", "main")
    sh(work, "git", "merge", "-q", "--no-ff", "-m", "Merge feature", "feature")
    sh(work, "git", "remote", "add", "origin", str(remote))
    sh(work, "git", "push", "-q", "-u", "origin", "main")
    (work / "a.txt").write_text("edited\n")
    (work / "untracked.txt").write_text("new\n")
    commit(other, "Other repo commit")

    claude = paths.CLAUDE_PROJECTS
    in_work = session_file(claude / "-work", "11111111-aaaa", str(work / "service"),
                           f"Refactor with {TOKEN}", [PROMPT, "and add tests"])
    session_file(claude / "-other", "22222222-bbbb", str(other), "Other repo session", ["hello"])
    session_file(claude / "-elsewhere", "33333333-cccc", str(TMP / "notes"), "Not a repo", ["private"])

    check("nothing is collected before anything is allowlisted", collect.run(paths.STORE_PATH) == [])
    (work / "service").mkdir()
    added = sources.add_repo(db, work / "service")
    check("add-repo, given a folder inside a repository, allowlists the whole repository as a project",
          added["status"] == "allowlisted" and added["project"] == "work" and added["path"] == os.path.realpath(work))
    check("adding the same repository again changes nothing", sources.add_repo(db, work)["status"] == "already allowlisted")
    try:
        sources.add_repo(db, TMP / "notes")
        check("a folder that isn't a repository is refused", False)
    except CollectorError as e:
        check("a folder that isn't a repository is refused", "isn't inside a Git repository" in str(e))
    kinds = {s["kind"] for s in sources.list_sources(db)}
    check("allowlisting a repository also turns on the Claude Code index", kinds == {"git_repo", "claude_code"})

    first = by_name(collect.run(paths.STORE_PATH, "catch_up"))
    check("both sources collect successfully", all(r["status"] == "ok" for r in first.values()))

    commits, merges = events(db, "git.commit"), events(db, "git.merge")
    check("every commit and the merge are recorded once, as separate types",
          len(commits) == 3 and len(merges) == 1 and merges[0]["title"] == "Merge feature")
    start = next(c for c in commits if c["title"] == "Start the service")
    check("commit times are UTC with the author's offset, and local_day uses it",
          start["occurred_at"] == "2026-11-02T22:30:00Z" and start["utc_offset_min"] == 60
          and start["local_day"] == "2026-11-02")
    late = commits and next(c for c in commits if c["title"] == "Add config")
    payload = json.loads(late["payload"])
    check("a colleague's commit keeps their email as actor; mine say 'me' (case-insensitive)",
          late["actor"] == "ana@example.com" and start["actor"] == "me")
    check("commit metadata has files and line counts, and the message body is redacted",
          payload["files"] == ["b.txt"] and payload["insertions"] == 3 and TOKEN not in payload["body"]
          and "[REDACTED]" in payload["body"])
    check("events belong to the repository's project", {e["project_id"] for e in events(db)} == {"work"})

    pushes = events(db, "git.push")
    check("the push is read from the reflog, with the branch",
          len(pushes) == 1 and json.loads(pushes[0]["payload"])["branch"] == "origin/main"
          and pushes[0]["title"] == "Pushed to origin/main")

    snaps = events(db, "git.snapshot")
    state = json.loads(snaps[0]["payload"])
    check("a snapshot records branch, upstream and uncommitted-change counts",
          len(snaps) == 1 and state["branch"] == "main" and state["upstream"] == "origin/main"
          and (state["unstaged"], state["untracked"], state["ahead"]) == (1, 1, 0))

    sessions = events(db, "claude_code.session")
    check("only the session inside the allowlisted repository is indexed", len(sessions) == 1)
    s = sessions[0]
    check("a session gets its project, start, end, prompt count and redacted title",
          s["id"] == "claude_code:session:11111111-aaaa" and s["project_id"] == "work"
          and (s["occurred_at"], s["ended_at"]) == ("2026-11-02T09:00:00Z", "2026-11-02T10:30:00Z")
          and json.loads(s["payload"])["prompts"] == 2 and TOKEN not in s["title"] and s["payload_ref"] == str(in_work))
    db.close()
    raw = Path(paths.STORE_PATH).read_bytes() + Path(str(paths.STORE_PATH) + "-wal").read_bytes() \
        if Path(str(paths.STORE_PATH) + "-wal").exists() else Path(paths.STORE_PATH).read_bytes()
    check("no prompt text and no secret ever reaches the store", PROMPT.encode() not in raw and TOKEN.encode() not in raw)
    db = store.connect(paths.STORE_PATH)

    runs = db.execute("SELECT trigger, status, seen, inserted FROM collector_runs ORDER BY id").fetchall()
    check("each pass is recorded in collector_runs", [tuple(r) for r in runs] == [("catch_up", "ok", 6, 6), ("catch_up", "ok", 1, 1)])
    check("each pass is in the audit log",
          db.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'collect'").fetchone()[0] == 2)

    second = by_name(collect.run(paths.STORE_PATH, "schedule"))
    check("a second pass with nothing new inserts nothing and counts duplicates avoided",
          all(r["inserted"] == r["changed"] == r["gone"] == 0 for r in second.values())
          and second["work"]["unchanged"] == 5 and second["Claude Code"]["unchanged"] == 1)
    check("an unchanged working tree writes no new snapshot", len(events(db, "git.snapshot")) == 1)

    commit(work, "To be amended", file="d.txt")
    collect.run(paths.STORE_PATH)
    amended_from = next(e for e in events(db, "git.commit") if e["title"] == "To be amended")["id"]
    sh(work, "git", "commit", "-q", "--amend", "-m", "Amended")
    with open(in_work, "a") as f:
        f.write(json.dumps({"type": "user", "cwd": str(work), "timestamp": "2026-11-02T11:00:00.000Z",
                            "message": {"role": "user", "content": "one more"}}) + "\n")
    third = by_name(collect.run(paths.STORE_PATH))
    gone = db.execute("SELECT gone_at FROM events WHERE id = ?", (amended_from,)).fetchone()[0]
    check("an amended commit marks the old one gone and adds the new one",
          gone is not None and any(e["title"] == "Amended" for e in events(db, "git.commit"))
          and third["work"]["gone"] == 1)
    grown = events(db, "claude_code.session")[0]
    check("a session that grew is updated, not duplicated",
          third["Claude Code"]["changed"] == 1 and grown["ended_at"] == "2026-11-02T11:00:00Z"
          and json.loads(grown["payload"])["prompts"] == 3 and grown["changed_at"] is not None)
    head = subprocess.run(["git", "-C", str(work), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    check("a changed working tree is snapshotted again with the new head",
          json.loads(events(db, "git.snapshot")[-1]["payload"])["head"] == head)

    sources.add_repo(db, other)
    fourth = by_name(collect.run(paths.STORE_PATH))
    check("allowlisting another repository indexes its sessions that were skipped before",
          fourth["Claude Code"]["inserted"] == 1 and len(events(db, "claude_code.session")) == 2
          and fourth["other"]["inserted"] >= 1)

    in_work.unlink()
    fifth = by_name(collect.run(paths.STORE_PATH))
    check("a deleted session file marks its session gone",
          fifth["Claude Code"]["gone"] == 1
          and db.execute("SELECT gone_at FROM events WHERE id = 'claude_code:session:11111111-aaaa'").fetchone()[0])

    other_id = next(s["id"] for s in sources.list_sources(db) if s["name"] == "other")
    sources.set_enabled(db, other_id, False)
    check("a disabled source is not collected and its events are hidden from Claude",
          "other" not in by_name(collect.run(paths.STORE_PATH))
          and not db.execute("SELECT COUNT(*) FROM events_for_claude WHERE source_id = ?", (other_id,)).fetchone()[0])

    shutil.move(work, TMP / "moved")
    moved = by_name(collect.run(paths.STORE_PATH))
    check("a repository that was moved fails clearly without stopping the other sources",
          moved["work"]["status"] == "error" and "moved or deleted" in moved["work"]["error"]
          and moved["Claude Code"]["status"] == "ok")
    db.close()

    env = {**os.environ}
    cli = [sys.executable, "-I", str(HERE / "cli.py")]
    listed = subprocess.run([*cli, "sources"], env=env, capture_output=True, text=True)
    check("pwi sources lists each source with its last run and errors",
          listed.returncode == 0 and "work" in listed.stdout and "moved or deleted" in listed.stdout)
    shutil.move(TMP / "moved", work)
    added = subprocess.run([*cli, "add-repo", str(work)], env=env, capture_output=True, text=True)
    check("pwi add-repo reports the project and collects straight away",
          added.returncode == 0 and "as project 'work'" in added.stdout and "work:" in added.stdout)
    bad = subprocess.run([*cli, "disable", "999"], env=env, capture_output=True, text=True)
    check("pwi reports a bad source id as an error, not a traceback",
          bad.returncode == 1 and "no source 999" in bad.stderr)
    check("foreign keys hold", sqlite3.connect(paths.STORE_PATH).execute("PRAGMA foreign_key_check").fetchall() == [])


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
