"""Checks the rules schema.sql enforces by itself, against an in-memory database.

Run: python3 -I test_schema.py
"""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "service"))
from store import UPSERT_EVENT  # noqa: E402  the statement the collectors write with

SCHEMA = (HERE / "schema.sql").read_text()
NOW = "2026-11-02T17:00:00Z"


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def raises(db, sql, params=()):
    try:
        db.execute(sql, params)
    except sqlite3.DatabaseError as e:
        return str(e)
    return None


def event(sha, title, observed_at=NOW, occurred_at="2026-11-02T23:30:00Z", project="pwi", source_id=1):
    payload = json.dumps({"files_changed": 2})
    return {
        "id": f"git:commit:{sha}", "source_id": source_id, "type": "git.commit", "actor": "me", "project_id": project,
        "occurred_at": occurred_at, "utc_offset_min": 60, "ended_at": None, "observed_at": observed_at,
        "title": title, "payload": payload, "payload_ref": f"/repos/PersonalAssistant@{sha}",
        "content_hash": hashlib.sha256((title + payload).encode()).hexdigest(),
    }


def add_version(db, claim_id, version, status, text, changed_by="claude"):
    db.execute(
        "insert into claim_versions (claim_id, version, status, text, project_id, method, changed_by, created_at)"
        " values (?, ?, ?, ?, 'pwi', 'claude', ?, ?)", (claim_id, version, status, text, changed_by, NOW))


def main():
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    check("schema applies", db.execute("select version from schema_version").fetchone() == (1,))

    db.execute("insert into sources (id, kind, locator, name, added_at) values"
               " (1, 'git_repo', '/repos/PersonalAssistant', 'PersonalAssistant', ?),"
               " (2, 'git_repo', '/repos/Other', 'Other', ?)", (NOW, NOW))
    db.execute("insert into projects (id, name, created_at) values ('pwi', 'Personal Work Intelligence', ?),"
               " ('secret', 'Secret project', ?)", (NOW, NOW))

    # Ingestion
    first = db.execute(UPSERT_EVENT, event("abc123", "Add bridge reconnect")).rowcount
    again = db.execute(UPSERT_EVENT, event("abc123", "Add bridge reconnect", observed_at="2026-11-02T18:00:00Z")).rowcount
    check("re-reading the same commit changes nothing", (first, again) == (1, 0)
          and db.execute("select count(*), max(changed_at) from events").fetchone() == (1, None))
    db.execute(UPSERT_EVENT, event("abc123", "Add bridge reconnect (amended)", observed_at="2026-11-02T19:00:00Z"))
    check("a changed re-read updates the row and records when",
          db.execute("select title, observed_at, changed_at from events").fetchone()
          == ("Add bridge reconnect (amended)", NOW, "2026-11-02T19:00:00Z"))
    check("local_day uses the local offset (23:30Z at +01:00 is the next day)",
          db.execute("select local_day from events").fetchone() == ("2026-11-03",))
    check("non-UTC timestamps are rejected",
          raises(db, UPSERT_EVENT, event("bad", "x", occurred_at="2026-11-02 23:30:00+01:00")) is not None)
    check("payload must be valid JSON",
          raises(db, UPSERT_EVENT, {**event("bad2", "x"), "payload": "{not json"}) is not None)

    # Claims
    db.execute("insert into claims (id, type, created_at) values ('clm_1', 'decision', ?)", (NOW,))
    add_version(db, "clm_1", 1, "proposed", "Use SQLite for the store, decisão final")
    check("claim versions can't skip numbers",
          "numbered" in (raises(db, "insert into claim_versions (claim_id, version, status, text, method, changed_by,"
                                    " created_at) values ('clm_1', 3, 'proposed', 'x', 'claude', 'claude', ?)", (NOW,))
                         or ""))
    check("claim versions can't be edited in place",
          "append-only" in (raises(db, "update claim_versions set text = 'changed'") or ""))
    check("Claude can't mark a claim supported",
          raises(db, "insert into claim_versions (claim_id, version, status, text, method, changed_by, created_at)"
                     " values ('clm_1', 2, 'supported', 'x', 'claude', 'claude', ?)", (NOW,)) is not None)
    add_version(db, "clm_1", 2, "supported", "Use SQLite for the store", changed_by="me")
    check("current_claims shows the latest version",
          db.execute("select version, status, text from current_claims where id = 'clm_1'").fetchone()
          == (2, "supported", "Use SQLite for the store"))

    def search_claims(term):
        return db.execute("select cc.id, cc.version from claims_fts f join current_claims cc on cc.seq = f.rowid"
                          " where claims_fts match ?", (term,)).fetchall()
    check("search matches current text only", search_claims("sqlite") == [("clm_1", 2)]
          and search_claims("final") == [])
    db.execute("insert into claims (id, type, created_at) values ('clm_2', 'fact', ?)", (NOW,))
    add_version(db, "clm_2", 1, "proposed", "A decisão foi adiada")
    check("search folds diacritics ('decisao' finds 'decisão')", search_claims("decisao") == [("clm_2", 1)])

    # Evidence and what Claude sees
    db.execute("insert into evidence (id, event_id, created_at) values (1, 'git:commit:abc123', ?)", (NOW,))
    db.execute("insert into claim_evidence values ('clm_1', 2, 1)")
    db.execute(UPSERT_EVENT, event("def456", "Secret work", project="secret"))
    db.execute(UPSERT_EVENT, event("ghi789", "Other repo work", source_id=2))
    visible = lambda: {r[0] for r in db.execute("select id from events_for_claude")}
    check("everything is visible before any label", len(visible()) == 3)
    db.execute("insert into labels values ('project', 'secret', 'confidential', 'me', ?)", (NOW,))
    check("a confidential project hides its events", "git:commit:def456" not in visible())
    db.execute("update sources set enabled = 0 where id = 2")
    check("removing a source from the allowlist hides its events", visible() == {"git:commit:abc123"})
    db.execute("insert into labels values ('event', 'git:commit:abc123', 'confidential', 'claude', ?)", (NOW,))
    check("a claim citing confidential evidence is hidden from Claude",
          [r[0] for r in db.execute("select id from claims_for_claude")] == ["clm_2"])
    add_version(db, "clm_2", 2, "retracted", "A decisão foi adiada", changed_by="me")
    check("retracted claims are hidden from Claude",
          db.execute("select count(*) from claims_for_claude").fetchone() == (0,))

    # Retention and deletion
    db.execute("delete from events where id = 'git:commit:abc123'")
    expired = db.execute("select event_id, expired_at from evidence where id = 1").fetchone()
    check("expiring an event keeps the evidence row, pointer cleared and expiry recorded",
          expired[0] is None and expired[1] is not None)
    check("deleting an event removes its labels",
          db.execute("select count(*) from labels where item_type = 'event'").fetchone() == (0,))
    db.execute("insert into links values ('claim', 'clm_1', 'contradicts', 'claim', 'clm_2', 'claude', ?)", (NOW,))
    db.execute("delete from claims where id = 'clm_1'")
    check("deleting a claim removes its versions, evidence links and links",
          db.execute("select (select count(*) from claim_versions where claim_id = 'clm_1'),"
                     " (select count(*) from claim_evidence), (select count(*) from links)").fetchone() == (0, 0, 0))
    for table in ("events_fts", "claims_fts", "artifacts_fts"):
        db.execute(f"insert into {table} ({table}) values ('integrity-check')")
    check("search indexes are consistent after updates and deletes", True)
    check("foreign keys hold", db.execute("pragma foreign_key_check").fetchall() == [])


if __name__ == "__main__":
    main()
