"""Checks the write tools, read_claude_sessions and get_metrics: the end-of-day
review from start to finish, against data the real collectors gathered from a
temporary Git repository and session files. Calls tools the way the service
does (Layer.call_tool).

Run: python3 -I service/test_writes.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pwi-writes-"))
os.environ.update({"HOME": str(TMP), "XDG_DATA_HOME": str(TMP / "data"), "XDG_CONFIG_HOME": str(TMP / "config"),
                   "CLAUDE_CONFIG_DIR": str(TMP / "claude"), "GIT_CONFIG_GLOBAL": str(TMP / "gitconfig"),
                   "GIT_CONFIG_NOSYSTEM": "1"})
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]

import collect  # noqa: E402
import handlers  # noqa: E402
import paths  # noqa: E402
import reads  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402

D1 = (date.today() - timedelta(days=2)).isoformat()
TOKEN = "ghp_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6"
READ_AT = "2026-11-02T17:00:00Z"


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def sh(cwd, *args, **env):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, env={**os.environ, **env})


def commit(repo, subject, day):
    with open(repo / "a.txt", "a") as f:
        f.write(subject + "\n")
    sh(repo, "git", "add", "a.txt")
    stamp = f"{day}T10:00:00+00:00"
    sh(repo, "git", "commit", "-q", "-m", subject, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)


def write_session(name, cwd, day):
    """A session as Claude Code writes it: prompts, thinking, tool calls, tool output, a subagent."""
    t = lambda minute: f"{day}T12:{minute:02d}:00.000Z"  # noqa: E731
    base = {"cwd": str(cwd), "sessionId": name}
    lines = [
        {**base, "type": "user", "timestamp": t(0), "message": {"role": "user", "content": f"Add a cache. Token is {TOKEN}"}},
        {**base, "type": "assistant", "timestamp": t(1), "message": {"content": [{"type": "thinking", "thinking": "THINKING_MARKER"}]}},
        {**base, "type": "assistant", "timestamp": t(1), "message": {"content": [{"type": "text", "text": "Let me look first."}]}},
        {**base, "type": "assistant", "timestamp": t(2), "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]}},
        {**base, "type": "user", "timestamp": t(2), "message": {"content": [{"type": "tool_result", "content": "OUTPUT_MARKER"}]}},
        {**base, "type": "assistant", "timestamp": t(3), "isSidechain": True, "message": {"content": [{"type": "text", "text": "SIDECHAIN_MARKER"}]}},
        {**base, "type": "assistant", "timestamp": t(4), "message": {"content": [{"type": "text", "text": "Done: added the cache with SQLite."}]}},
        {**base, "type": "user", "timestamp": t(5), "isMeta": True, "message": {"content": "META_MARKER"}},
        {**base, "type": "user", "timestamp": t(5), "message": {"content": "<local-command-caveat>CAVEAT_MARKER</local-command-caveat>"}},
        {**base, "type": "user", "timestamp": t(5), "message": {"content": "<command-name>/model</command-name> COMMAND_MARKER"}},
        {**base, "type": "user", "timestamp": t(6), "message": {"content": [{"type": "text", "text": "Now write the tests."}]}},
        {**base, "type": "assistant", "timestamp": t(9), "message": {"content": [{"type": "text", "text": "Tests written; all pass."}]}},
        {"type": "ai-title", "aiTitle": "Cache work", "sessionId": name},
    ]
    folder = paths.CLAUDE_PROJECTS / f"-{name}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


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
    alpha, beta = TMP / "Projects" / "alpha", TMP / "Projects" / "beta"
    for repo in (alpha, beta):
        repo.mkdir(parents=True)
        sh(repo, "git", "init", "-q", "-b", "main")
        sh(repo, "git", "config", "user.email", "me@example.com")
    commit(alpha, "Add cache layer", D1)
    commit(alpha, "Tune cache size", D1)
    commit(beta, "Beta work", D1)
    session_file = write_session("sess-alpha", alpha, D1)
    write_session("sess-beta", beta, D1)
    db = store.connect(paths.STORE_PATH)
    sources.add_path(db, TMP / "Projects")
    collect.run(paths.STORE_PATH)
    ids = {r["title"]: r["id"] for r in db.execute("SELECT id, title FROM events WHERE type = 'git.commit'")}
    cache_commit, tune_commit = ids["Add cache layer"], ids["Tune cache size"]
    alpha_session, beta_session = "claude_code:session:sess-alpha", "claude_code:session:sess-beta"
    claims_count = lambda: db.execute("SELECT COUNT(*) FROM claims").fetchone()[0]  # noqa: E731

    # read_claude_sessions
    read = call("read_claude_sessions", {"day": D1, "project": "alpha"})
    turns = read["sessions"][0]["turns"]
    check("read_claude_sessions gives my prompts and Claude's final reply to each, in order",
          [(t["role"], t["text"][:20]) for t in turns] == [
              ("me", "Add a cache. Token i"), ("claude", "Done: added the cach"),
              ("me", "Now write the tests."), ("claude", "Tests written; all p")])
    text = json.dumps(read)
    check("it leaves out tool output, thinking, subagents, meta entries and command noise",
          not any(m in text for m in ("OUTPUT_MARKER", "THINKING_MARKER", "SIDECHAIN_MARKER", "META_MARKER",
                                      "CAVEAT_MARKER", "COMMAND_MARKER", "Let me look first")))
    check("it redacts secrets in what I typed", TOKEN not in text and "[REDACTED]" in turns[0]["text"])
    check("each session has its id, project, title and times",
          read["sessions"][0]["session_id"] == alpha_session and read["sessions"][0]["title"] == "Cache work"
          and read["sessions"][0]["start"] < read["sessions"][0]["end"])
    reads.SESSION_PAGE_CHARS = 120
    pages, cursor = [], None
    while True:
        page = call("read_claude_sessions", {"day": D1, **({"cursor": cursor} if cursor else {})})
        pages.append(page)
        cursor = page.get("cursor")
        if not cursor:
            break
    reads.SESSION_PAGE_CHARS = 30000
    paged = [(s["session_id"], t["text"]) for p in pages for s in p["sessions"] for t in s["turns"]]
    whole = [(s["session_id"], t["text"]) for s in call("read_claude_sessions", {"day": D1})["sessions"] for t in s["turns"]]
    check("long days come in pages; following the cursor returns every turn once",
          len(pages) > 2 and paged == whole and len(whole) == 8)
    check("a cursor that wasn't returned is refused",
          call("read_claude_sessions", {"day": D1, "cursor": "nonsense"})["found"] is False)

    # propose_claim
    first = call("propose_claim", {"type": "decision", "text": "We use SQLite for the cache.",
                                   "evidence": [{"event_id": cache_commit}]})
    claim_a = first["claim_id"]
    check("propose_claim saves an unconfirmed claim and takes the project from its evidence",
          first["created"] is True and first["label"] == "unconfirmed" and first["version"] == 1
          and first["project"] == "alpha")
    again = call("propose_claim", {"type": "decision", "text": "we use sqlite for the CACHE",
                                   "evidence": [{"event_id": tune_commit}]})
    check("the same claim again returns the existing one, with the new evidence added",
          again == {"claim_id": claim_a, "version": 1, "label": "unconfirmed", "created": False}
          and len(call("get_evidence", {"event_id": tune_commit})["cited_by"]) == 1)
    similar = call("propose_claim", {"type": "decision", "text": "We use Redis for the cache instead of SQLite.",
                                     "evidence": [{"event_id": tune_commit}]})
    claim_b = similar["claim_id"]
    check("a claim sharing key terms with another comes back with possible contradictions to check",
          [c["claim_id"] for c in similar["possible_contradictions"]] == [claim_a] and "link_items" in similar["hint"])
    before = claims_count()
    for args, reason in (
            ({"evidence": [{"event_id": "git:commit:deadbeef"}]}, "isn't an event the layer has"),
            ({"evidence": [{"event_id": cache_commit}], "project": "nope"}, "no project 'nope'"),
            ({"evidence": [{"event_id": cache_commit}], "due_at": "next friday"}, "due_at must be"),
            ({}, "evidence is required")):
        refused = call("propose_claim", {"type": "commitment", "text": "Ship it", **args})
        check(f"propose_claim is refused when {reason}, saying what to fix", reason in refused.get("error", ""))
    check("refused claims save nothing", claims_count() == before)
    online = call("propose_claim", {"type": "commitment", "text": "Send the cache design to Ana by Friday",
                                    "project": "alpha", "due_at": "2026-11-06", "owner": "me",
                                    "evidence": [{"artifact_id": "notion:task-42", "artifact_kind": "work_item",
                                                  "title": "Cache design", "url": "https://notion.so/task-42",
                                                  "read_at": READ_AT, "source_version": "rev3"}]})
    evidence_id = call("list_unconfirmed")["claims"][-1]["evidence"][0]["evidence_id"]
    check("online evidence is saved as a reference only: id, kind, title, link and when it was read",
          online["created"] is True and call("get_evidence", {"evidence_id": evidence_id})["artifact"]["title"] == "Cache design"
          and db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 1)

    # set_claim_status, update_claim
    confirmed = call("set_claim_status", {"claim_id": claim_a, "status": "supported"})
    check("set_claim_status confirms a claim as my change, and it's verified",
          confirmed == {"claim_id": claim_a, "version": 2, "label": "verified", "changed": True}
          and db.execute("SELECT changed_by FROM current_claims WHERE id = ?", (claim_a,)).fetchone()[0] == "me")
    check("a verified claim leaves the waiting list",
          claim_a not in [c["claim_id"] for c in call("list_unconfirmed")["claims"]])
    more = call("update_claim", {"claim_id": claim_a, "reason": "another commit",
                                 "add_evidence": [{"event_id": beta_session}]})
    check("adding evidence without changing the claim keeps it verified, in the same version",
          more == {"claim_id": claim_a, "version": 2, "label": "verified", "new_version": False})
    corrected = call("update_claim", {"claim_id": claim_a, "text": "We use SQLite for the cache, in WAL mode.",
                                      "reason": "more precise"})
    check("changing a verified claim's text adds a version that is unconfirmed until I confirm it",
          corrected == {"claim_id": claim_a, "version": 3, "label": "unconfirmed", "new_version": True, "was": "verified"})
    evidence_v3 = db.execute("SELECT COUNT(*) FROM claim_evidence WHERE claim_id = ? AND version = 3", (claim_a,)).fetchone()[0]
    check("evidence carries over to the new version, and old versions are kept",
          evidence_v3 == 3 and db.execute("SELECT COUNT(*) FROM claim_versions WHERE claim_id = ?", (claim_a,)).fetchone()[0] == 3)
    check("an update that changes nothing is refused",
          "Nothing would change" in call("update_claim", {"claim_id": claim_a, "text": "We use SQLite for the cache, in WAL mode.",
                                                          "reason": "same"}).get("error", ""))

    # link_items
    linked = call("link_items", {"from": {"type": "claim", "id": claim_b}, "rel": "contradicts",
                                 "to": {"type": "claim", "id": claim_a}})
    check("a 'contradicts' link marks both claims disputed; neither is overwritten",
          linked["created"] is True and [d["label"] for d in linked["disputed"]] == ["disputed", "disputed"]
          and {c["claim_id"]: c["label"] for c in call("list_unconfirmed")["claims"]}.get(claim_a) == "disputed")
    check("the same link again creates nothing",
          call("link_items", {"from": {"type": "claim", "id": claim_b}, "rel": "contradicts",
                              "to": {"type": "claim", "id": claim_a}})["created"] is False)
    check("links to unknown items, to sources, or from an item to itself are refused",
          "no event" in call("link_items", {"from": {"type": "event", "id": "git:commit:nope"}, "rel": "related",
                                            "to": {"type": "claim", "id": claim_a}}).get("error", "")
          and "can't be 'source'" in call("link_items", {"from": {"type": "source", "id": "1"}, "rel": "related",
                                                          "to": {"type": "claim", "id": claim_a}}).get("error", "")
          and "itself" in call("link_items", {"from": {"type": "claim", "id": claim_a}, "rel": "related",
                                              "to": {"type": "claim", "id": claim_a}}).get("error", ""))
    retracted = call("set_claim_status", {"claim_id": claim_b, "status": "retracted", "reason": "wrong"})
    check("a retracted claim is hidden from every read and can't be updated",
          retracted["label"] == "retracted"
          and not any(r["id"] == claim_b for r in call("search", {"query": "redis"})["results"])
          and "retracted" in call("update_claim", {"claim_id": claim_b, "text": "x", "reason": "y"}).get("error", ""))

    # save_session_note
    waiting = call("list_unconfirmed")["days_missing_session_notes"]
    check("before the notes, both days and projects with sessions are waiting for one",
          [(d["day"], d["project"]) for d in waiting] == [(D1, "alpha"), (D1, "beta")])
    note = call("save_session_note", {"project": "alpha", "day": D1, "session_ids": [alpha_session],
                                      "text": "Added a SQLite cache and its tests."})
    check("save_session_note saves the day's note for the project, as unconfirmed",
          note["created"] is True and note["label"] == "unconfirmed"
          and [(d["day"], d["project"]) for d in call("list_unconfirmed")["days_missing_session_notes"]] == [(D1, "beta")])
    rewrite = call("save_session_note", {"project": "alpha", "day": D1, "session_ids": [alpha_session],
                                         "text": "Added a SQLite cache, WAL mode, and its tests."})
    check("saving the same project and day again adds a version instead of a second note",
          rewrite["claim_id"] == note["claim_id"] and rewrite["version"] == 2 and rewrite["created"] is False
          and call("get_day", {"day": D1})["session_notes"][0]["text"].startswith("Added a SQLite cache, WAL"))
    check("a session from another project is refused",
          "belongs to project 'beta'" in call("save_session_note", {"project": "alpha", "day": D1, "text": "x",
                                                                     "session_ids": [beta_session]}).get("error", ""))
    check("session notes don't count as claims waiting for confirmation",
          note["claim_id"] not in [c["claim_id"] for c in call("list_unconfirmed")["claims"]])
    check("get_project now has the latest objective from the session note",
          call("get_project", {"project": "alpha"})["objective"]["claim_id"] == note["claim_id"])

    # add_confidential_label
    labelled = call("add_confidential_label", {"item": {"type": "event", "id": tune_commit}, "reason": "client name"})
    check("a confidential label hides the item from every read",
          labelled == {"item": {"type": "event", "id": tune_commit}, "labelled": True, "already_labelled": False}
          and tune_commit not in json.dumps(call("get_day", {"day": D1})["events_by_project"])
          and call("get_evidence", {"event_id": tune_commit})["found"] is False)
    check("labelling it again changes nothing",
          call("add_confidential_label", {"item": {"type": "event", "id": tune_commit}})["already_labelled"] is True)
    beta_source = next(s["id"] for s in sources.list_sources(db) if s["name"] == "beta")
    call("add_confidential_label", {"item": {"type": "source", "id": str(beta_source)}})
    check("a confidential source hides all its events (its project's sessions come from another source), "
          "and an unknown item is refused",
          "commits" not in call("get_day", {"day": D1})["events_by_project"].get("beta", {})
          and "There's no claim clm_nope" in call("add_confidential_label", {"item": {"type": "claim", "id": "clm_nope"}}).get("error", ""))

    # what the store enforces, and what's measured
    check("every verified version in the store was made by me",
          db.execute("SELECT COUNT(*) FROM claim_versions WHERE status = 'supported' AND changed_by <> 'me'").fetchone()[0] == 0)
    actions = {r[0] for r in db.execute("SELECT DISTINCT action FROM audit_log WHERE actor IN ('claude', 'me')")}
    check("every write is in the audit log", {"propose", "revise", "set_status", "link", "label"} <= actions)
    metrics = call("get_metrics")
    check("get_metrics counts claims proposed, confirmed, corrected and retracted, and citation coverage",
          metrics["claims"]["proposed"] == 3 and metrics["claims"]["corrected"] == 1
          and metrics["claims"]["retracted"] == 1 and metrics["citation_coverage"] == 1.0
          and metrics["session_notes"] == 1)
    check("get_metrics reports each collector's runs and duplicates avoided, never a confidential source",
          {c["source"] for c in metrics["collectors"]} == {"git:alpha", "claude_code"}
          and all(c["runs"] >= 1 for c in metrics["collectors"]))
    session_file.unlink()
    collect.run(paths.STORE_PATH)
    check("when Claude Code deletes a session file, read_claude_sessions says so instead of failing",
          call("read_claude_sessions", {"day": D1, "project": "alpha"})["found"] is False)
    db.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
