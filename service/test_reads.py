"""Checks the read tools against data the real collectors gathered from
temporary Git repositories and session files, plus claims in every state.
Calls tools the way the service does (Layer.call_tool), so validation,
refresh-on-stale, coverage and trimming are covered too.

Run: python3 -I service/test_reads.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pwi-reads-"))
os.environ.update({"HOME": str(TMP), "XDG_DATA_HOME": str(TMP / "data"), "XDG_CONFIG_HOME": str(TMP / "config"),
                   "CLAUDE_CONFIG_DIR": str(TMP / "claude"), "GIT_CONFIG_GLOBAL": str(TMP / "gitconfig"),
                   "GIT_CONFIG_NOSYSTEM": "1"})
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]

import collect  # noqa: E402
import handlers  # noqa: E402
import paths  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402

TODAY = date.today()
D1, D2 = (TODAY - timedelta(days=3)).isoformat(), (TODAY - timedelta(days=2)).isoformat()
NOW = store.now()


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def sh(cwd, *args, **env):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, env={**os.environ, **env})


def commit(repo, subject, day, body="", file="a.txt", email="me@example.com"):
    with open(repo / file, "a") as f:
        f.write(subject + "\n")
    sh(repo, "git", "add", file)
    stamp = f"{day}T10:00:00+00:00"
    sh(repo, "git", "commit", "-q", "-m", subject + (f"\n\n{body}" if body else ""),
       GIT_AUTHOR_EMAIL=email, GIT_AUTHOR_NAME="x", GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)


def session(name, cwd, day, title):
    folder = paths.CLAUDE_PROJECTS / f"-{name}"
    folder.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "user", "cwd": str(cwd), "timestamp": f"{day}T12:00:00.000Z",
              "message": {"role": "user", "content": "go"}},
             {"type": "assistant", "cwd": str(cwd), "timestamp": f"{day}T12:40:00.000Z", "message": {}},
             {"type": "ai-title", "aiTitle": title}]
    (folder / f"{name}.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")


def add_claim(db, claim_id, kind, text, project, status="proposed", about_day=None, due_at=None, evidence=(),
              proposed_at=NOW):
    db.execute("INSERT INTO claims VALUES (?, ?, ?)", (claim_id, kind, proposed_at))
    db.execute("INSERT INTO claim_versions (claim_id, version, status, text, project_id, about_day, due_at, method,"
               " changed_by, created_at) VALUES (?, 1, ?, ?, ?, ?, ?, 'claude', ?, ?)",
               (claim_id, status, text, project, about_day, due_at, "me" if status == "supported" else "claude",
                proposed_at))
    for event_id in evidence:
        ev = db.execute("INSERT INTO evidence (event_id, created_at) VALUES (?, ?)", (event_id, NOW)).lastrowid
        db.execute("INSERT INTO claim_evidence VALUES (?, 1, ?)", (claim_id, ev))


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
    repos = {name: TMP / "Projects" / name for name in ("alpha", "beta", "secret")}
    for repo in repos.values():
        repo.mkdir(parents=True)
        sh(repo, "git", "init", "-q", "-b", "main")
        sh(repo, "git", "config", "user.email", "me@example.com")
    sh(repos["alpha"], "git", "remote", "add", "origin", "git@github.com:acme/alpha.git")
    commit(repos["alpha"], "Add cache layer", D1, body="Chose SQLite over Redis because the laptop has no server.",
           file="cache_store.py")
    commit(repos["alpha"], "Fix login bug", D2)
    commit(repos["alpha"], "Review fixes", D2, email="ana@example.com")
    commit(repos["beta"], "Beta work", D1)
    commit(repos["secret"], "Secret stuff about the cache", D1)
    session("alpha1", repos["alpha"], D1, "Planning the cache")
    session("beta1", repos["beta"], D2, "Beta session")

    db = store.connect(paths.STORE_PATH)
    sources.add_path(db, TMP / "Projects")
    collect.run(paths.STORE_PATH)
    ids = {r["title"]: r["id"] for r in db.execute("SELECT id, title FROM events")}
    db.execute("INSERT INTO labels VALUES ('project', 'secret', 'confidential', 'me', ?)", (NOW,))
    add_claim(db, "clm_dec1", "decision", "Decisão: usar SQLite em vez de Redis", "alpha", about_day=D1,
              evidence=[ids["Add cache layer"]])
    add_claim(db, "clm_note1", "session_note", "Planned the cache layer; next, wire it in.", "alpha", about_day=D1,
              evidence=[ids["Planning the cache"]])
    add_claim(db, "clm_com1", "commitment", "Send the cache design to Ana", "alpha", due_at=D2)
    add_claim(db, "clm_blk1", "blocker", "Waiting for the staging database", "alpha", status="supported")
    add_claim(db, "clm_ret1", "decision", "Use Redis", "alpha", status="retracted", about_day=D1)
    add_claim(db, "clm_sec1", "decision", "Secret decision", "secret", about_day=D1)
    add_claim(db, "clm_old", "fact", "The old API is deprecated", "beta",
              proposed_at=store.utc(time.time() - 10 * 86400))

    # get_day
    day1 = call("get_day", {"day": D1})
    alpha = day1["events_by_project"]["alpha"]
    check("get_day groups the day's events by project, each with an event_id to cite",
          [c["title"] for c in alpha["commits"]] == ["Add cache layer"]
          and alpha["commits"][0]["event_id"].startswith("git:commit:") and alpha["commits"][0]["files_changed"] == 1)
    check("get_day shows sessions with start, end and title, in local time",
          alpha["sessions"][0]["title"] == "Planning the cache" and alpha["sessions"][0]["until"] > alpha["sessions"][0]["at"])
    check("get_day never shows a confidential project", set(day1["events_by_project"]) == {"alpha", "beta"})
    check("get_day lists the day's claims, labelled, with evidence; never retracted or confidential ones",
          [(c["claim_id"], c["label"]) for c in day1["claims"]] == [("clm_dec1", "unconfirmed")]
          and day1["claims"][0]["evidence"][0]["event_id"] == ids["Add cache layer"])
    check("get_day lists the day's session notes separately",
          [n["claim_id"] for n in day1["session_notes"]] == ["clm_note1"])
    check("unconfirmed_count leaves out session notes, verified, retracted and confidential claims",
          day1["unconfirmed_count"] == 3)
    check("every read has a coverage block; fresh data isn't refreshed again",
          day1["coverage"]["refreshed_now"] is False and "git:alpha" in day1["coverage"]["sources_checked"]
          and day1["coverage"]["stale_sources"] == [])
    day2 = call("get_day", {"day": D2})
    check("get_day lists commitments due that day, and marks colleagues' commits",
          [c["claim_id"] for c in day2["due"]] == ["clm_com1"]
          and any(c.get("actor") == "ana@example.com" for c in day2["events_by_project"]["alpha"]["commits"]))
    empty = call("get_day", {"day": (TODAY - timedelta(days=60)).isoformat()})
    check("an empty day says not found and explains why", empty["found"] is False
          and any("oldest event" in g for g in empty["gaps"]))

    # get_week
    week = call("get_week", {"week_of": D1})
    check("get_week counts each project's work and active days, mine and colleagues' apart",
          week["by_project"]["alpha"]["commits"] >= 1 and D1 in week["by_project"]["alpha"]["active_days"]
          and "secret" not in week["by_project"])
    now_week = call("get_week", {"week_of": TODAY.isoformat()})
    aging = {(a["kind"], a["claim_id"]) for a in now_week["aging"]}
    check("get_week's aging has overdue commitments, open blockers and long-unconfirmed claims",
          {("overdue_commitment", "clm_com1"), ("open_blocker", "clm_blk1"), ("long_unconfirmed", "clm_old")} <= aging
          and all(a["age_days"] >= 0 for a in now_week["aging"]))

    # get_project
    project = call("get_project", {"project": "alpha"})
    check("get_project gives the last verified state: branch, head and last commit, with when it was seen",
          project["state"]["branch"] == "main" and project["state"]["observed_at"]
          and project["state"]["last_commit"]["title"] in ("Fix login bug", "Review fixes"))
    check("get_project's objective is the latest session note, labelled, with evidence",
          project["objective"]["claim_id"] == "clm_note1" and project["objective"]["label"] == "unconfirmed")
    check("get_project lists blockers, decisions and commitments, never retracted ones",
          [b["claim_id"] for b in project["blockers"]] == ["clm_blk1"] and project["blockers"][0]["label"] == "verified"
          and [d["claim_id"] for d in project["decisions"]] == ["clm_dec1"]
          and [c["claim_id"] for c in project["commitments"]] == ["clm_com1"])
    check("get_project gives GitHub lookups for the repository and its branch",
          any("acme/alpha" in q["query"] and "main" in q["query"] for q in project["lookups"])
          and project["last_activity_day"] == D2 and project["recent_sessions"][0]["title"] == "Planning the cache")
    check("get_project says when there's no GitHub remote",
          any("no GitHub remote" in g for g in call("get_project", {"project": "beta"})["gaps"]))
    hidden = call("get_project", {"project": "secret"})
    check("a confidential project is not found, and isn't listed among the known ones",
          hidden["found"] is False and "secret" not in hidden["gaps"][0] .split("Known projects:")[1])

    # search
    why = call("search", {"query": "redis"})
    check("search finds a commit by the reason in its message body, best match first, with a snippet",
          why["results"][0]["id"] == ids["Add cache layer"] and "«Redis»" in why["results"][0]["snippet"]
          and why["results"][0]["project"] == "alpha")
    check("search finds claims, accents folded, with their label",
          any(r["item_type"] == "claim" and r["id"] == "clm_dec1" and r["label"] == "unconfirmed"
              for r in call("search", {"query": "decisao"})["results"]))
    check("search matches other forms of a word, in English and Portuguese",
          call("search", {"query": "servers"})["results"][0]["id"] == ids["Add cache layer"]
          and any(r["id"] == "clm_dec1" for r in call("search", {"query": "decisões"})["results"])
          and any(r["id"] == ids["Fix login bug"] for r in call("search", {"query": "fixes"})["results"]))
    check("search finds a commit by a file it changed", call("search", {"query": "cache_store"})["results"][0]["id"]
          == ids["Add cache layer"])
    check("search never returns confidential items or retracted claims",
          not any(r.get("project") == "secret" or r["id"] in ("clm_ret1", "clm_sec1")
                  for r in call("search", {"query": "cache redis secret decision"})["results"]))
    check("search filters by kind, project and dates",
          [r["type"] for r in call("search", {"query": "cache", "kinds": ["claude_code"]})["results"]] == ["claude_code.session"]
          and call("search", {"query": "cache", "project": "beta"})["found"] is False
          and all(r["local_day"] >= D2 for r in call("search", {"query": "fix login cache", "since": D2})["results"]))
    nothing = call("search", {"query": "kubernetes"})
    check("a search with no match says not found and suggests other wordings",
          nothing["found"] is False and "Portuguese and English" in nothing["gaps"][0])

    # list_unconfirmed
    waiting = call("list_unconfirmed")
    check("list_unconfirmed lists proposed and disputed claims oldest first, with age and evidence",
          [c["claim_id"] for c in waiting["claims"]] == ["clm_old", "clm_dec1", "clm_com1"]
          and waiting["claims"][0]["age_days"] == 10)
    check("list_unconfirmed lists days with sessions but no session note, with when the files expire",
          waiting["days_missing_session_notes"] == [{"day": D2, "project": "beta", "sessions": 1,
                                                     "session_file_expires_on": (TODAY + timedelta(days=28)).isoformat()}])

    # get_evidence
    full = call("get_evidence", {"event_id": ids["Add cache layer"]})
    check("get_evidence by event_id gives the full record and the claims that cite it",
          full["status"] == "available" and "Redis" in full["event"]["payload"]["body"]
          and full["event"]["payload"]["files"] == ["cache_store.py"] and full["cited_by"][0]["claim_id"] == "clm_dec1")
    evidence_id = call("list_unconfirmed")["claims"][1]["evidence"][0]["evidence_id"]
    check("get_evidence by evidence_id resolves to the event",
          call("get_evidence", {"evidence_id": evidence_id})["event"]["event_id"] == ids["Add cache layer"])
    check("get_evidence won't show a confidential event",
          call("get_evidence", {"event_id": ids["Secret stuff about the cache"]})["found"] is False)
    db.execute("INSERT INTO artifacts (id, kind, title, url, project_id, first_seen_at) VALUES"
               " ('notion:abc', 'work_item', 'Cache task', 'https://notion.so/abc', 'alpha', ?)", (NOW,))
    online = db.execute("INSERT INTO evidence (artifact_id, read_at, source_version, created_at)"
                        " VALUES ('notion:abc', ?, 'rev7', ?)", (NOW, NOW)).lastrowid
    online_result = call("get_evidence", {"evidence_id": online})
    check("online evidence says to re-read it, with the version seen",
          online_result["status"] == "online" and online_result["source_version"] == "rev7"
          and "source changed" in online_result["gaps"][0])
    db.execute("DELETE FROM events WHERE id = ?", (ids["Planning the cache"],))  # what retention will do
    note_evidence = db.execute("SELECT evidence_id FROM claim_evidence WHERE claim_id = 'clm_note1'").fetchone()[0]
    check("evidence whose event was removed says expired",
          call("get_evidence", {"evidence_id": note_evidence})["status"] == "expired")
    check("get_evidence needs exactly one of event_id or evidence_id",
          "exactly one" in call("get_evidence", {"event_id": "x", "evidence_id": 1}).get("error", ""))

    # refresh, coverage and trimming
    db.execute("UPDATE collector_runs SET finished_at = ?", (store.utc(time.time() - 3600),))
    commit(repos["alpha"], "Today's commit", TODAY.isoformat())
    today = call("get_day", {"day": TODAY.isoformat()})
    check("a read on data older than 5 minutes collects first, and says so",
          today["coverage"]["refreshed_now"] is True
          and any(c["title"] == "Today's commit" for c in today["events_by_project"]["alpha"]["commits"]))
    check("the next read doesn't collect again", call("list_projects")["coverage"]["refreshed_now"] is False)
    shutil.move(repos["beta"], TMP / "moved-beta")
    db.execute("UPDATE collector_runs SET finished_at = ?", (store.utc(time.time() - 3600),))
    broken = call("list_projects")["coverage"]
    check("a source that fails to refresh is listed as stale, with its error",
          broken["refreshed_now"] is True and "git:beta" in broken["stale_sources"]
          and "moved or deleted" in broken["source_errors"]["git:beta"])
    check("a failing source doesn't make every read collect again",
          call("list_projects")["coverage"]["refreshed_now"] is False)
    beta_id = next(s["id"] for s in sources.list_sources(db) if s["name"] == "beta")
    sources.set_enabled(db, beta_id, False)
    check("a disabled source's events disappear from reads",
          "beta" not in call("get_day", {"day": D1})["events_by_project"])
    big = {"items": [{"title": "x" * 200} for _ in range(1000)], "found": True}
    trimmed = handlers.fit(big)
    check("results over 40,000 characters are trimmed and say so",
          len(json.dumps(trimmed)) <= handlers.MAX_CHARS and trimmed["truncated"] is True and trimmed["gaps"])
    db.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
