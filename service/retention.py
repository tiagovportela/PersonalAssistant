"""Retention: deletes what the retention table says is too old, once a day.

- Events of each source kind (Git metadata, the Claude Code index, ...) after
  `retention.days` for that kind. Evidence pointing at them stays, marked
  expired, so Claude can say a confirmed claim's evidence has expired.
- Unconfirmed claims (proposed or disputed) not changed for `unconfirmed_claim` days.
- Session notes I haven't confirmed, about days older than `session_note` days.
- Audit entries and collector runs older than `audit` days.
- Then evidence and online references nothing uses any more.

Confirmed claims are kept until I delete them (confirmed_claim is NULL), and
retracted claims are kept for history. Everything deleted is counted in the
audit log, never its content. Search indexes, links and labels follow through
the schema's triggers.
"""

import logging
import time
from contextlib import closing

import store

DAY = 86400
RUN_AFTER_IDLE = 300  # seconds without input that count as "the laptop is idle"
RUN_ANYWAY_AFTER = 26 * 3600  # if it's never idle (or idle can't be read), don't skip more than a day
log = logging.getLogger("pwi")


def cutoff(db, item_type, now):
    row = db.execute("SELECT days FROM retention WHERE item_type = ?", (item_type,)).fetchone()
    return None if row is None or row["days"] is None else store.utc(now - row["days"] * DAY)


def last_run(db):
    return db.execute("SELECT MAX(at) FROM audit_log WHERE actor = 'retention'").fetchone()[0]


def due(db, idle_seconds, now=None):
    """Once a day, at the first moment the laptop is idle; or after RUN_ANYWAY_AFTER regardless.
    `idle_seconds` is a function, called only when a run is otherwise due; it returns None if unknown."""
    now = now or time.time()
    last = last_run(db)
    if last is None:
        return True
    if last >= store.utc(now - DAY + 3600):  # ran in the last 23 hours
        return False
    idle = idle_seconds()
    if idle is None or idle >= RUN_AFTER_IDLE:
        return True
    return last < store.utc(now - RUN_ANYWAY_AFTER)


def run(store_path, now=None):
    """Applies retention once. Returns the counts deleted, by kind."""
    now = now or time.time()
    counts = {}
    with closing(store.connect(store_path)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            for kind in [r["kind"] for r in db.execute("SELECT DISTINCT kind FROM sources")]:
                before = cutoff(db, kind, now)
                if before:
                    counts[f"events:{kind}"] = db.execute(
                        "DELETE FROM events WHERE source_id IN (SELECT id FROM sources WHERE kind = ?)"
                        " AND COALESCE(ended_at, occurred_at) < ?", (kind, before)).rowcount
            before = cutoff(db, "unconfirmed_claim", now)
            if before:
                counts["unconfirmed_claims"] = db.execute(
                    "DELETE FROM claims WHERE id IN (SELECT id FROM current_claims WHERE status IN ('proposed', 'disputed')"
                    " AND type <> 'session_note' AND version_at < ?)", (before,)).rowcount
            before = cutoff(db, "session_note", now)
            if before:
                counts["session_notes"] = db.execute(
                    "DELETE FROM claims WHERE id IN (SELECT id FROM current_claims WHERE type = 'session_note'"
                    " AND status NOT IN ('supported', 'retracted') AND about_day < ?)", (before[:10],)).rowcount
            before = cutoff(db, "audit", now)
            if before:
                counts["audit_entries"] = db.execute("DELETE FROM audit_log WHERE at < ?", (before,)).rowcount
                counts["collector_runs"] = db.execute("DELETE FROM collector_runs WHERE started_at < ?", (before,)).rowcount
            counts["unused_evidence"] = db.execute(
                "DELETE FROM evidence WHERE id NOT IN (SELECT evidence_id FROM claim_evidence)").rowcount
            counts["unused_references"] = db.execute(
                "DELETE FROM artifacts WHERE id NOT IN (SELECT artifact_id FROM evidence WHERE artifact_id IS NOT NULL)"
                " AND id NOT IN (SELECT from_id FROM links WHERE from_type = 'artifact')"
                " AND id NOT IN (SELECT to_id FROM links WHERE to_type = 'artifact')").rowcount
            at = store.now()
            for kind, count in counts.items():
                if count:
                    db.execute("INSERT INTO audit_log (at, actor, action, item_type, count)"
                               " VALUES (?, 'retention', 'expire', ?, ?)", (at, kind, count))
            # Always one entry, even when nothing expired: it's how `due` knows today's run happened.
            db.execute("INSERT INTO audit_log (at, actor, action, item_type, count) VALUES (?, 'retention', 'expire',"
                       " 'run', ?)", (at, sum(counts.values())))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    deleted = {k: v for k, v in counts.items() if v}
    log.info("retention: %s", ", ".join(f"{v} {k}" for k, v in deleted.items()) or "nothing to delete")
    return counts
