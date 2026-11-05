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

import cloud_sessions  # noqa: E402
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
    test_folders(env, cli)
    test_cloud_sessions(env, cli, work)
    check("foreign keys hold", sqlite3.connect(paths.STORE_PATH).execute("PRAGMA foreign_key_check").fetchall() == [])


def test_folders(env, cli):
    """`pwi add-repo ~/Projects`: every repository in a folder, and new ones on a second run."""
    projects = TMP / "repos"  # holds work (allowlisted) and other (disabled earlier)
    for repo in ("third", "clients/acme/app", "node_modules/dep", ".hidden/x", "a/b/c/d/too-deep"):
        (projects / repo).mkdir(parents=True)
        sh(projects / repo, "git", "init", "-q")
    (projects / "notes").mkdir()
    (projects / "broken" / ".git").mkdir(parents=True)  # a .git folder that isn't a repository
    (projects / "broken" / ".git" / "._HEAD").write_text("zip junk")
    db = store.connect(paths.STORE_PATH)
    results = {Path(a["path"]).resolve().relative_to(projects.resolve()).as_posix(): a["status"]
               for a in sources.add_path(db, projects)}
    check("a folder allowlists the repositories in it, including nested folders, but not dependencies, "
          "hidden folders or anything too deep",
          set(results) == {"work", "other", "third", "clients/acme/app", "broken"})
    check("a broken .git folder is skipped and reported instead of stopping the others",
          results["broken"].startswith("skipped"))
    check("repositories already allowlisted stay as they are, and a disabled one stays off",
          results["work"] == "already allowlisted" and results["other"].startswith("disabled, left off")
          and results["third"] == results["clients/acme/app"] == "allowlisted")
    (projects / "fourth").mkdir()
    sh(projects / "fourth", "git", "init", "-q")
    again = subprocess.run([*cli, "add-repo", str(projects)], env=env, capture_output=True, text=True)
    check("running it again on the folder adds only the new repository",
          again.returncode == 0 and "fourth: allowlisted as project 'fourth'" in again.stdout
          and "1 newly allowlisted" in again.stdout)
    dotfiles = TMP / "home"
    (dotfiles / "Projects" / "real").mkdir(parents=True)
    sh(dotfiles, "git", "init", "-q")
    sh(dotfiles / "Projects" / "real", "git", "init", "-q")
    inside = [Path(a["path"]).name for a in sources.add_path(db, dotfiles / "Projects")]
    check("a folder inside a dotfiles repository allowlists the repositories in it, not the home repository",
          inside == ["real"])
    try:
        sources.add_path(db, projects / "notes")
        check("a folder with no repositories is an error", False)
    except CollectorError as e:
        check("a folder with no repositories is an error", "no Git repositories" in str(e))
    db.close()


def test_cloud_sessions(env, cli, work):
    db = store.connect(paths.STORE_PATH)
    work = Path(os.path.realpath(work))
    sh(work, "git", "checkout", "-q", "--", ".")
    sh(work, "git", "clean", "-qfd")
    copies = paths.CLAUDE_CLOUD
    check("a cloud session id is found in a claude.ai/code link",
          cloud_sessions.cloud_session_id("https://claude.ai/code/session_012Tbapi?x=1") == "session_012Tbapi")

    # teleport: a stand-in for `claude --teleport` that checks out a branch and writes the session file
    def fake_claude(args, cwd):
        assert args == ["claude", "--teleport", "session_ABC123"] and cwd == str(work)
        sh(work, "git", "checkout", "-q", "-b", "claude/cloud-branch")
        session_file(paths.CLAUDE_PROJECTS / "-work-tp", "44444444-dddd", str(work), "Cloud work", ["cloud prompt"])
        return subprocess.CompletedProcess(args, 0)
    done = cloud_sessions.import_session(db, "https://claude.ai/code/session_ABC123", repo=str(work / "service"),
                                         run=fake_claude)
    check("import-cloud-session teleports in the checkout, copies the session file and switches the branch back",
          done["project"] == "work" and done["session_file"] == "44444444-dddd"
          and (copies / "44444444-dddd.jsonl").exists()
          and json.loads((copies / "44444444-dddd.json").read_text())["cloud_session"] == "session_ABC123"
          and subprocess.run(["git", "-C", str(work), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                             text=True).stdout.strip() == "main")
    collect.run(paths.STORE_PATH)
    row = db.execute("SELECT * FROM events WHERE id = 'claude_code:session:44444444-dddd'").fetchone()
    check("the copy is indexed like a local session, with origin cloud, once, not also as the local file",
          row and row["project_id"] == "work" and row["payload_ref"] == str(copies / "44444444-dddd.jsonl")
          and json.loads(row["payload"])["origin"] == "cloud"
          and db.execute("SELECT COUNT(*) FROM events WHERE id LIKE '%44444444-dddd'").fetchone()[0] == 1)

    local = paths.CLAUDE_PROJECTS / "-work-tp" / "44444444-dddd.jsonl"
    with open(local, "a") as f:
        f.write(json.dumps({"type": "user", "cwd": str(work), "timestamp": "2026-11-02T12:00:00.000Z",
                            "message": {"role": "user", "content": "kept going locally"}}) + "\n")
    collect.run(paths.STORE_PATH)
    local.unlink()
    collect.run(paths.STORE_PATH)
    row = db.execute("SELECT * FROM events WHERE id = 'claude_code:session:44444444-dddd'").fetchone()
    check("a session continued locally refreshes the copy, which outlives the local file",
          row["gone_at"] is None and json.loads(row["payload"])["prompts"] == 2)

    def no_file(args, cwd):
        return subprocess.CompletedProcess(args, 1)
    try:
        cloud_sessions.import_session(db, "session_XYZ", repo=str(work), run=no_file)
        check("a teleport that writes nothing is an error", False)
    except CollectorError as e:
        check("a teleport that writes nothing is an error that suggests --file", "--file" in str(e))
    (work / "dirty.txt").write_text("x")
    try:
        cloud_sessions.import_session(db, "session_XYZ", repo=str(work), run=fake_claude)
        check("teleport refuses a checkout with uncommitted changes", False)
    except CollectorError as e:
        check("teleport refuses a checkout with uncommitted changes", "uncommitted" in str(e))
    (work / "dirty.txt").unlink()

    # --file: a transcript from a cloud container, whose working folder is /home/user/<repo>
    transcript = session_file(TMP / "downloads", "55555555-eeee", "/home/user/work", "From the cloud", ["hi", "more"])
    added = subprocess.run([*cli, "import-cloud-session", "--file", str(transcript)], env=env, capture_output=True,
                           text=True)
    check("pwi import-cloud-session --file maps /home/user/<repo> to the allowlisted repository and collects",
          added.returncode == 0 and "into project 'work'" in added.stdout
          and db.execute("SELECT project_id FROM events WHERE id = 'claude_code:session:55555555-eeee'").fetchone()[0] == "work")
    renamed = TMP / "downloads" / "transcript.jsonl"
    lines = [{"type": "user", "cwd": "/home/user/work", "sessionId": "77777777-abcd", "timestamp": "2026-11-03T09:00:00.000Z",
              "message": {"role": "user", "content": "why is it broken?"}},
             {"type": "assistant", "timestamp": "2026-11-03T09:01:00.000Z",
              "message": {"role": "assistant", "content": [{"type": "text", "text": "Because of the cache."}]}},
             {"type": "user", "isMeta": True, "timestamp": "2026-11-03T09:02:00.000Z",
              "message": {"role": "user", "content": "Stop hook feedback: push your commits"}},
             {"type": "assistant", "timestamp": "2026-11-03T09:03:00.000Z",
              "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
             {"type": "assistant", "timestamp": "2026-11-03T09:04:00.000Z",
              "message": {"role": "assistant", "content": [{"type": "text", "text": "Pushed."}]}}]
    renamed.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    imported = cloud_sessions.import_session(db, file=str(renamed))
    import reads
    check("a renamed transcript is stored under the session id it records",
          imported["session_file"] == "77777777-abcd" and (copies / "77777777-abcd.jsonl").exists())
    check("a reply before hook feedback is kept, and the reply after it is a turn of its own",
          [t["text"] for t in reads.session_turns(copies / "77777777-abcd.jsonl", 0)]
          == ["why is it broken?", "Because of the cache.", "Pushed."])
    unknown = session_file(TMP / "downloads", "66666666-ffff", "/home/user/nowhere", "?", ["x"])
    bad = subprocess.run([*cli, "import-cloud-session", "--file", str(unknown)], env=env, capture_output=True, text=True)
    check("a transcript from an unknown repository asks for --repo", bad.returncode == 1 and "--repo" in bad.stderr)

    db.execute("DELETE FROM events WHERE id = 'claude_code:session:55555555-eeee'")
    db.commit()
    collect.run(paths.STORE_PATH)
    check("deleting an imported session's event (retention or me) removes its copy, and it isn't indexed again",
          not (copies / "55555555-eeee.jsonl").exists() and not (copies / "55555555-eeee.json").exists()
          and db.execute("SELECT 1 FROM events WHERE id = 'claude_code:session:55555555-eeee'").fetchone() is None)
    db.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
