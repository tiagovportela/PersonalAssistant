"""Checks read_confidential, retention, the idle check and `pwi cleanup`,
against data the real collectors gathered into a temporary home.

Retention is checked by running it "100 days from now", so everything
collected today is past its 90-day retention.

Run: python3 -I service/test_privacy.py
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pwi-privacy-"))
os.environ.update({"HOME": str(TMP), "XDG_DATA_HOME": str(TMP / "data"), "XDG_CONFIG_HOME": str(TMP / "config"),
                   "CLAUDE_CONFIG_DIR": str(TMP / "claude"), "GIT_CONFIG_GLOBAL": str(TMP / "gitconfig"),
                   "GIT_CONFIG_NOSYSTEM": "1"})
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]

import collect  # noqa: E402
import handlers  # noqa: E402
import idle  # noqa: E402
import paths  # noqa: E402
import retention  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402

D1 = (date.today() - timedelta(days=2)).isoformat()
NOW = time.time()
READ_AT = "2026-11-02T17:00:00Z"


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def sh(cwd, *args, **env):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, env={**os.environ, **env})


def commit(repo, subject):
    with open(repo / "a.txt", "a") as f:
        f.write(subject + "\n")
    sh(repo, "git", "add", "a.txt")
    stamp = f"{D1}T10:00:00+00:00"
    sh(repo, "git", "commit", "-q", "-m", subject, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)


def session(name, cwd):
    folder = paths.CLAUDE_PROJECTS / f"-{name}"
    folder.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "user", "cwd": str(cwd), "timestamp": f"{D1}T12:00:00.000Z", "message": {"content": "go"}},
             {"type": "assistant", "cwd": str(cwd), "timestamp": f"{D1}T12:30:00.000Z",
              "message": {"content": [{"type": "text", "text": "done"}]}}]
    (folder / f"{name}.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")


def main():
    layer = handlers.Layer(paths.STORE_PATH)

    def call(name, args=None):
        result = layer.call_tool(name, args or {})
        text = result["content"][0]["text"]
        if result["isError"]:
            return {"error": text}
        return json.loads(text.split("\n", 1)[1].rsplit("\n", 1)[0])

    os.umask(0o077)
    store.create_or_check(paths.STORE_PATH)
    work, secret = TMP / "Projects" / "work", TMP / "Projects" / "secret"
    for repo in (work, secret):
        repo.mkdir(parents=True)
        sh(repo, "git", "init", "-q", "-b", "main")
        sh(repo, "git", "config", "user.email", "me@example.com")
    commit(work, "Public work")
    commit(secret, "Acquisition prep")
    session("s-work", work)
    db = store.connect(paths.STORE_PATH)
    sources.add_path(db, TMP / "Projects")
    collect.run(paths.STORE_PATH)
    ids = {r["title"]: r["id"] for r in db.execute("SELECT id, title FROM events WHERE type = 'git.commit'")}
    public, hidden = ids["Public work"], ids["Acquisition prep"]

    def propose(text, evidence, **extra):
        return call("propose_claim", {"type": "decision", "text": text, "evidence": evidence, **extra})["claim_id"]

    secret_claim = propose("We prepare the acquisition quietly", [{"event_id": hidden}])
    unconfirmed = propose("We keep the public API stable", [{"event_id": public}])
    confirmed = propose("We ship weekly", [{"event_id": public}])
    call("set_claim_status", {"claim_id": confirmed, "status": "supported"})
    retracted = propose("We ship daily", [{"event_id": public}])
    call("set_claim_status", {"claim_id": retracted, "status": "retracted"})
    online = propose("We follow the Notion plan", [{"artifact_id": "notion:plan", "artifact_kind": "document",
                                                    "title": "Plan", "read_at": READ_AT}], project="work")
    note = call("save_session_note", {"project": "work", "day": D1, "text": "Did public work.",
                                      "session_ids": ["claude_code:session:s-work"]})["claim_id"]
    call("add_confidential_label", {"item": {"type": "project", "id": "secret"}})

    # read_confidential
    check("a confidential project is hidden from the normal tools",
          call("get_project", {"project": "secret"})["found"] is False
          and not any(r.get("project") == "secret" for r in call("search", {"query": "acquisition"})["results"]))
    shown = call("read_confidential", {"item": {"type": "project", "id": "secret"}})
    check("read_confidential shows it in get_project's shape, marked confidential, with a note on how to use it",
          shown["found"] is True and shown["confidential"] is True and "don't repeat it" in shown["note"]
          and shown["state"]["last_commit"]["title"] == "Acquisition prep"
          and [d["claim_id"] for d in shown["decisions"]] == [secret_claim])
    check("only that read sees it: the next normal read hides it again",
          call("get_project", {"project": "secret"})["found"] is False)
    check("read_confidential shows a confidential event, and a claim whose evidence is confidential",
          call("read_confidential", {"item": {"type": "event", "id": hidden}})["event"]["title"] == "Acquisition prep"
          and call("read_confidential", {"item": {"type": "claim", "id": secret_claim}})["claim"]["text"]
          == "We prepare the acquisition quietly")
    call("add_confidential_label", {"item": {"type": "event", "id": public}})
    lifted_one = call("read_confidential", {"item": {"type": "project", "id": "secret"}})
    check("lifting one label leaves every other confidential item hidden",
          public not in json.dumps(lifted_one) and call("get_evidence", {"event_id": public})["found"] is False)
    db.execute("DELETE FROM labels WHERE item_type = 'event' AND item_id = ?", (public,))  # what the frontend will do
    work_source = next(s["id"] for s in sources.list_sources(db) if s["name"] == "work")
    plain = call("read_confidential", {"item": {"type": "source", "id": str(work_source)}})
    check("an item that isn't confidential is shown, and Claude is told the normal tools would do",
          plain["confidential"] is False and "isn't labelled confidential" in plain["gaps"][0]
          and plain["recent_events"][0]["title"] == "Public work")
    check("an unknown item is not found", call("read_confidential", {"item": {"type": "claim", "id": "clm_x"}})["found"] is False)
    reads_logged = db.execute("SELECT item_type, item_id FROM audit_log WHERE action = 'read_confidential'").fetchall()
    check("every confidential read is in the audit log, by id only",
          len(reads_logged) == 5 and ("project", "secret") in [tuple(r) for r in reads_logged])

    # idle and when retention runs
    check("the idle time is read from GNOME's reply, in seconds", idle.parse("(uint64 123456,)\n") == 123.456
          and idle.parse("") is None)
    check("retention runs on the first check when it never ran", retention.due(db, lambda: 0) is True)
    for idle_s, hours_ago, expected, why in ((600, 25, True, "the laptop is idle and it last ran over a day ago"),
                                             (10, 25, False, "I'm using the laptop and it ran 25 hours ago"),
                                             (10, 27, True, "it hasn't run for over 26 hours, even though I'm busy"),
                                             (None, 25, True, "idle time can't be read and it ran over a day ago"),
                                             (600, 2, False, "it already ran today")):
        db.execute("DELETE FROM audit_log WHERE actor = 'retention'")
        db.execute("INSERT INTO audit_log (at, actor, action, item_type) VALUES (?, 'retention', 'expire', 'run')",
                   (store.utc(NOW - hours_ago * 3600),))
        check(f"retention {'runs' if expected else 'waits'} when {why}",
              retention.due(db, lambda: idle_s, NOW) is expected)
    db.execute("DELETE FROM audit_log WHERE actor = 'retention'")

    # retention
    later = NOW + 100 * 86400
    counts = retention.run(paths.STORE_PATH, now=later)
    remaining = {r[0] for r in db.execute("SELECT id FROM claims")}
    check("events past their retention are deleted, for every source kind",
          counts["events:git_repo"] >= 2 and counts["events:claude_code"] == 1
          and db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0)
    check("unconfirmed claims and unconfirmed session notes past retention are deleted",
          unconfirmed not in remaining and online not in remaining and secret_claim not in remaining
          and note not in remaining and counts["unconfirmed_claims"] == 3 and counts["session_notes"] == 1)
    check("confirmed claims are kept, and retracted ones stay for history", {confirmed, retracted} <= remaining)
    evidence = db.execute("SELECT ev.event_id, ev.expired_at FROM claim_evidence ce JOIN evidence ev ON ev.id = ce.evidence_id"
                          " WHERE ce.claim_id = ?", (confirmed,)).fetchall()
    check("a kept claim's evidence stays, marked expired, so Claude can say so",
          evidence and all(e["event_id"] is None and e["expired_at"] for e in evidence)
          and call("get_evidence", {"evidence_id": db.execute(
              "SELECT evidence_id FROM claim_evidence WHERE claim_id = ?", (confirmed,)).fetchone()[0]})["status"] == "expired")
    check("evidence and online references nothing uses any more are deleted",
          db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
          and db.execute("SELECT COUNT(*) FROM evidence WHERE id NOT IN (SELECT evidence_id FROM claim_evidence)").fetchone()[0] == 0)
    check("old audit entries and collector runs are deleted, and the deletions are counted in the audit log",
          counts["audit_entries"] > 0 and counts["collector_runs"] > 0
          and db.execute("SELECT COUNT(*) FROM audit_log WHERE actor = 'retention' AND item_type = 'unconfirmed_claims'"
                         " AND count = 3").fetchone()[0] == 1)
    for table in ("events_fts", "claims_fts", "artifacts_fts"):
        db.execute(f"INSERT INTO {table} ({table}) VALUES ('integrity-check')")
    check("search indexes, links and labels stay consistent",
          db.execute("PRAGMA foreign_key_check").fetchall() == []
          and db.execute("SELECT COUNT(*) FROM claims_fts WHERE claims_fts MATCH 'public'").fetchone()[0] == 0
          and db.execute("SELECT COUNT(*) FROM labels WHERE item_type IN ('event', 'claim')").fetchone()[0] == 0)
    again = retention.run(paths.STORE_PATH, now=later)
    # Its own audit entries carry the real time, which looks old from 100 days ahead; that can't happen in use.
    check("running it again deletes nothing more", sum(v for k, v in again.items() if k != "audit_entries") == 0)

    cli = subprocess.run([sys.executable, "-I", str(HERE / "cli.py"), "cleanup"], capture_output=True, text=True)
    check("pwi cleanup runs retention and says what it deleted",
          cli.returncode == 0 and ("Deleted" in cli.stdout or "Nothing was old enough" in cli.stdout))
    check("foreign keys hold", sqlite3.connect(paths.STORE_PATH).execute("PRAGMA foreign_key_check").fetchall() == [])
    db.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
