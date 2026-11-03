"""Runs the collectors for every enabled source and records each pass in
collector_runs, so freshness, duplicates and gaps are measurable.

A collector only reads: it returns a Batch of events, and this module writes
the batch in one short transaction. A slow `git log` therefore never holds the
store locked, and a failed pass writes nothing.
"""

import hashlib
import json
import logging
import threading
import time
from contextlib import closing

import collect_claude_code
import collect_firefox
import collect_git
import store
from batch import CollectorError

DEFAULT_RETENTION_DAYS = 90
log = logging.getLogger("pwi")
_one_at_a_time = threading.Lock()

COLLECTORS = {"git_repo": collect_git.collect, "claude_code": collect_claude_code.collect,
              "firefox": collect_firefox.collect}


def run(store_path, trigger="manual"):
    """Collects every enabled source once. Returns one summary per source."""
    with _one_at_a_time, closing(store.connect(store_path)) as db:
        sources = db.execute("SELECT * FROM sources WHERE enabled = 1 ORDER BY id").fetchall()
        return [run_source(db, s, trigger) for s in sources if s["kind"] in COLLECTORS]


def run_source(db, source, trigger, collector=None):
    """One pass over one source. `collector` defaults to the source kind's; app usage passes its own,
    which hands over the spans it sampled."""
    run_id = db.execute("INSERT INTO collector_runs (source_id, trigger, started_at, status) VALUES (?, ?, ?, 'running')",
                        (source["id"], trigger, store.now())).lastrowid
    counts, error = {}, None
    try:
        batch = (collector or COLLECTORS[source["kind"]])(db, source, since(db, source["kind"]))
        db.execute("BEGIN IMMEDIATE")
        try:
            counts = apply(db, source, batch)
            db.execute("INSERT INTO audit_log (at, actor, action, item_type, item_id, count)"
                       " VALUES (?, 'collector', 'collect', 'source', ?, ?)",
                       (store.now(), str(source["id"]), counts["inserted"] + counts["changed"] + counts["gone"]))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    except CollectorError as e:
        error = str(e)
    except Exception as e:  # a collector bug must not stop the other sources
        log.exception("collecting %s %s failed", source["kind"], source["locator"])
        error = f"{type(e).__name__}: {e}"[:500]
    if error:
        log.warning("%s %s: %s", source["kind"], source["name"], error)
    db.execute("UPDATE collector_runs SET finished_at = ?, status = ?, error = ?, seen = ?, inserted = ?, changed = ?,"
               " unchanged = ?, gone = ? WHERE id = ?",
               (store.now(), "error" if error else "ok", error, *(counts.get(k, 0) for k in
                ("seen", "inserted", "changed", "unchanged", "gone")), run_id))
    return {"source_id": source["id"], "kind": source["kind"], "name": source["name"],
            "status": "error" if error else "ok", "error": error, **counts}


def since(db, kind):
    """Unix time of the oldest record worth reading: older ones would be deleted by retention anyway."""
    row = db.execute("SELECT days FROM retention WHERE item_type = ?", (kind,)).fetchone()
    days = DEFAULT_RETENTION_DAYS if row is None else row["days"]
    return 0 if days is None else int(time.time()) - days * 86400


def content_hash(row):
    content = [row["actor"], row["occurred_at"], row["ended_at"], row["title"], row["payload"], row["project_id"]]
    return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()


def apply(db, source, batch):
    observed_at = store.now()
    counts = {"seen": len(batch.events) + batch.cached, "inserted": 0, "changed": 0,
              "unchanged": batch.cached, "gone": 0}
    for event in batch.events:
        row = {"actor": "me", "project_id": None, "ended_at": None, "title": None, "payload_ref": None, **event,
               "source_id": source["id"], "observed_at": observed_at}
        row["payload"] = json.dumps(event.get("payload", {}), ensure_ascii=False, sort_keys=True)
        row["content_hash"] = content_hash(row)
        old = db.execute("SELECT content_hash, gone_at FROM events WHERE id = ?", (row["id"],)).fetchone()
        if old is None:
            counts["inserted"] += 1
        elif old["content_hash"] != row["content_hash"] or old["gone_at"] is not None:
            counts["changed"] += 1
        else:
            counts["unchanged"] += 1
        db.execute(store.UPSERT_EVENT, row)
    if batch.gone_ids:
        counts["gone"] = db.execute("UPDATE events SET gone_at = ? WHERE gone_at IS NULL"
                                    " AND id IN (SELECT value FROM json_each(?))",
                                    (observed_at, json.dumps(batch.gone_ids))).rowcount
    if batch.cursor is not None:
        db.execute("UPDATE sources SET cursor = ? WHERE id = ?", (batch.cursor, source["id"]))
    return counts
