"""What the frontend can do to the store: the only place where data is deleted,
confidential labels are removed, and retention or project settings change.

Unlike the read tools, these see everything, including confidential items and
disabled sources, because they are for me, not for Claude. Every change goes
into the audit log as mine.
"""

import os
import platform
import sqlite3

import collect
import paths
import retention
import sources
import store
from batch import CollectorError
from reads import brief_event, fts_query

ITEM_TABLES = {"source": "sources", "project": "projects", "event": "events", "artifact": "artifacts", "claim": "claims"}
DECISIONS = ("keep", "retract", "delete")


class Invalid(Exception):
    """A request the frontend shouldn't have sent. The message is shown to me."""


def audit(db, action, item_type, item_id=None, count=1):
    db.execute("INSERT INTO audit_log (at, actor, action, item_type, item_id, count) VALUES (?, 'me', ?, ?, ?, ?)",
               (store.now(), action, item_type, item_id, count))


def transaction(db, work):
    db.execute("BEGIN IMMEDIATE")
    try:
        result = work()
        db.execute("COMMIT")
        return result
    except BaseException:
        db.execute("ROLLBACK")
        raise


def label_set(db):
    return {(r["item_type"], r["item_id"]) for r in db.execute("SELECT item_type, item_id FROM labels")}


# Overview --------------------------------------------------------------------

def status(db, version):
    claims = dict(db.execute("SELECT status, COUNT(*) FROM current_claims WHERE type <> 'session_note' GROUP BY status").fetchall())
    size = sum(os.path.getsize(p) for p in (paths.STORE_PATH, f"{paths.STORE_PATH}-wal") if os.path.exists(p))
    return {
        "version": version,
        "python": platform.python_version(),
        "store": {"path": str(paths.STORE_PATH), "bytes": size,
                  "schema_version": db.execute("SELECT version FROM schema_version").fetchone()[0]},
        "sources": sources.list_sources(db),
        "events": db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "claims": {k: claims.get(k, 0) for k in ("proposed", "supported", "disputed", "retracted", "superseded")},
        "session_notes": db.execute("SELECT COUNT(*) FROM claims WHERE type = 'session_note'").fetchone()[0],
        "confidential_labels": db.execute("SELECT COUNT(*) FROM labels").fetchone()[0],
        "last_retention_at": retention.last_run(db),
    }


def collect_now(store_path):
    return collect.run(store_path, "manual")


def cleanup_now(store_path):
    return retention.run(store_path)


def audit_entries(db, limit=200):
    return [dict(r) for r in db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (min(int(limit), 1000),))]


# Sources and projects --------------------------------------------------------

def add_sources(db, path):
    if not path or not str(path).strip():
        raise Invalid("Give the path of a repository, or of a folder such as ~/Projects.")
    try:
        return sources.add_path(db, str(path).strip())
    except CollectorError as e:
        raise Invalid(str(e)) from None


def set_source_enabled(db, source_id, enabled):
    try:
        sources.set_enabled(db, source_id, bool(enabled))
    except CollectorError as e:
        raise Invalid(str(e)) from None
    return {"source_id": source_id, "enabled": bool(enabled)}


def projects(db):
    labelled = label_set(db)
    rows = db.execute(
        "SELECT p.*, (SELECT COUNT(*) FROM events e WHERE e.project_id = p.id) AS events,"
        " (SELECT MAX(local_day) FROM events e WHERE e.project_id = p.id AND e.type <> 'git.snapshot') AS last_activity_day,"
        " (SELECT COUNT(*) FROM current_claims c WHERE c.project_id = p.id AND c.status <> 'retracted') AS claims"
        " FROM projects p ORDER BY last_activity_day IS NULL, last_activity_day DESC, p.id").fetchall()
    aliases = db.execute("SELECT project_id, kind, value FROM project_aliases ORDER BY kind, value").fetchall()
    return [{**dict(p), "confidential": ("project", p["id"]) in labelled,
             "aliases": [{"kind": a["kind"], "value": a["value"]} for a in aliases if a["project_id"] == p["id"]]}
            for p in rows]


def update_project(db, project_id, changes):
    if db.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise Invalid(f"There's no project {project_id}.")
    if "name" in changes and not str(changes["name"]).strip():
        raise Invalid("A project needs a name.")
    if "status" in changes and changes["status"] not in ("active", "paused", "done"):
        raise Invalid("A project's status is active, paused or done.")
    for field in ("name", "status"):
        if field in changes:
            db.execute(f"UPDATE projects SET {field} = ? WHERE id = ?", (str(changes[field]).strip(), project_id))
    audit(db, "settings", "project", project_id)
    return {"project_id": project_id, **{k: changes[k] for k in ("name", "status") if k in changes}}


# Browsing --------------------------------------------------------------------

def events(db, project=None, day=None, query=None, source=None, limit=200):
    labelled = label_set(db)
    confidential = {r[0] for r in db.execute("SELECT id FROM confidential_events")}
    sql, params = "SELECT e.*, s.name AS source_name, s.enabled FROM events e JOIN sources s ON s.id = e.source_id", []
    where = ["e.type <> 'git.snapshot'"]
    if query:
        match = fts_query(query)
        if not match:
            return []
        sql += " JOIN events_fts f ON f.rowid = e.seq"
        where.append("events_fts MATCH ?")
        params.append(match)
    for clause, value in (("e.project_id = ?", project), ("e.local_day = ?", day), ("e.source_id = ?", source)):
        if value:
            where.append(clause)
            params.append(value)
    rows = db.execute(f"{sql} WHERE {' AND '.join(where)} ORDER BY e.occurred_at DESC LIMIT ?",
                      (*params, min(int(limit), 1000))).fetchall()
    return [{**brief_event(e), "project": e["project_id"], "local_day": e["local_day"], "source": e["source_name"],
             "source_enabled": bool(e["enabled"]), "confidential": e["id"] in confidential,
             "labelled": ("event", e["id"]) in labelled} for e in rows]


def claims(db, status=None, project=None, query=None, limit=200):
    labelled = label_set(db)
    sql, params, where = "SELECT c.* FROM current_claims c", [], []
    if query:
        match = fts_query(query)
        if not match:
            return []
        sql += " JOIN claims_fts f ON f.rowid = c.seq"
        where.append("claims_fts MATCH ?")
        params.append(match)
    for clause, value in (("c.status = ?", status), ("c.project_id = ?", project)):
        if value:
            where.append(clause)
            params.append(value)
    visible = {r[0] for r in db.execute("SELECT id FROM claims_for_claude")}
    rows = db.execute(f"{sql} {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY c.version_at DESC LIMIT ?",
                      (*params, min(int(limit), 1000))).fetchall()
    return [{"claim_id": c["id"], "type": c["type"], "text": c["text"], "status": c["status"], "project": c["project_id"],
             "about_day": c["about_day"], "due_at": c["due_at"], "version": c["version"], "changed_at": c["version_at"],
             "changed_by": c["changed_by"],
             "evidence": db.execute("SELECT COUNT(*) FROM claim_evidence WHERE claim_id = ? AND version = ?",
                                    (c["id"], c["version"])).fetchone()[0],
             "labelled": ("claim", c["id"]) in labelled,
             "hidden_from_claude": c["id"] not in visible and c["status"] != "retracted"} for c in rows]


def claim_history(db, claim_id):
    versions = db.execute("SELECT * FROM claim_versions WHERE claim_id = ? ORDER BY version", (claim_id,)).fetchall()
    if not versions:
        raise Invalid(f"There's no claim {claim_id}.")
    out = []
    for v in versions:
        evidence = db.execute(
            "SELECT ev.id, ev.event_id, ev.artifact_id, ev.read_at, ev.expired_at, e.title AS event_title,"
            " a.title AS artifact_title, a.url FROM claim_evidence ce JOIN evidence ev ON ev.id = ce.evidence_id"
            " LEFT JOIN events e ON e.id = ev.event_id LEFT JOIN artifacts a ON a.id = ev.artifact_id"
            " WHERE ce.claim_id = ? AND ce.version = ? ORDER BY ev.id", (claim_id, v["version"])).fetchall()
        out.append({k: v[k] for k in ("version", "status", "text", "project_id", "about_day", "due_at", "owner",
                                      "changed_by", "reason", "created_at")} | {"evidence": [dict(e) for e in evidence]})
    return {"claim_id": claim_id, "versions": out}


# Deletion --------------------------------------------------------------------

def events_of(db, items):
    """The event ids that deleting these items removes."""
    ids = set()
    for item in items:
        if item["type"] == "event":
            ids.add(item["id"])
        elif item["type"] == "source":
            ids |= {r[0] for r in db.execute("SELECT id FROM events WHERE source_id = ?", (item["id"],))}
    return ids


def check_items(db, items):
    if not isinstance(items, list) or not items:
        raise Invalid("Choose what to delete.")
    for item in items:
        if not isinstance(item, dict) or item.get("type") not in ("event", "claim", "source"):
            raise Invalid("Only events, claims and sources can be deleted here.")
        key = int(item["id"]) if item["type"] == "source" else item["id"]
        if db.execute(f"SELECT 1 FROM {ITEM_TABLES[item['type']]} WHERE id = ?", (key,)).fetchone() is None:
            raise Invalid(f"There's no {item['type']} {item['id']}.")


def impact(db, items):
    """Claims whose current version relies on evidence these items remove, for me to decide on each."""
    check_items(db, items)
    removed = events_of(db, items)
    deleted_claims = {i["id"] for i in items if i["type"] == "claim"}
    affected = []
    for c in db.execute("SELECT * FROM current_claims ORDER BY version_at DESC"):
        if c["id"] in deleted_claims:
            continue
        evidence = db.execute("SELECT ev.event_id FROM claim_evidence ce JOIN evidence ev ON ev.id = ce.evidence_id"
                              " WHERE ce.claim_id = ? AND ce.version = ?", (c["id"], c["version"])).fetchall()
        hit = [e["event_id"] for e in evidence if e["event_id"] in removed]
        if hit:
            affected.append({"claim_id": c["id"], "type": c["type"], "text": c["text"], "status": c["status"],
                             "evidence_total": len(evidence), "evidence_removed": len(hit)})
    return {"events": len(removed), "claims_deleted": len(deleted_claims), "affected_claims": affected}


def delete(db, items, decisions):
    """Deletes events, claims or whole sources. Every affected claim needs my decision:
    keep it (its evidence shows as expired), retract it, or delete it too."""
    def work():
        affected = {c["claim_id"] for c in impact(db, items)["affected_claims"]}
        missing = affected - set(decisions or {})
        if missing:
            raise Invalid(f"Decide what happens to {len(missing)} claim(s) that rely on this evidence.")
        if any(d not in DECISIONS for d in (decisions or {}).values()):
            raise Invalid("For each claim, choose keep, retract or delete.")
        counts = {"events": 0, "claims": 0, "sources": 0, "retracted": 0}
        to_delete = {i["id"] for i in items if i["type"] == "claim"}
        for claim_id, decision in (decisions or {}).items():
            if claim_id not in affected:
                continue
            if decision == "delete":
                to_delete.add(claim_id)
            elif decision == "retract":
                c = db.execute("SELECT * FROM current_claims WHERE id = ?", (claim_id,)).fetchone()
                if c["status"] != "retracted":
                    db.execute("INSERT INTO claim_versions (claim_id, version, status, text, project_id, about_day,"
                               " due_at, owner, confidence, method, changed_by, reason, created_at) SELECT claim_id,"
                               " version + 1, 'retracted', text, project_id, about_day, due_at, owner, confidence, method,"
                               " 'me', 'evidence deleted', ? FROM claim_versions WHERE claim_id = ? AND version = ?",
                               (store.now(), claim_id, c["version"]))
                    db.execute("INSERT INTO claim_evidence SELECT claim_id, version + 1, evidence_id FROM claim_evidence"
                               " WHERE claim_id = ? AND version = ?", (claim_id, c["version"]))
                    counts["retracted"] += 1
        for claim_id in to_delete:
            counts["claims"] += db.execute("DELETE FROM claims WHERE id = ?", (claim_id,)).rowcount
        for item in items:
            if item["type"] == "event":
                counts["events"] += db.execute("DELETE FROM events WHERE id = ?", (item["id"],)).rowcount
            elif item["type"] == "source":
                counts["events"] += db.execute("SELECT COUNT(*) FROM events WHERE source_id = ?", (int(item["id"]),)).fetchone()[0]
                counts["sources"] += db.execute("DELETE FROM sources WHERE id = ?", (int(item["id"]),)).rowcount
        db.execute("DELETE FROM evidence WHERE id NOT IN (SELECT evidence_id FROM claim_evidence)")
        for kind, count in counts.items():
            if count and kind != "retracted":
                audit(db, "delete", kind.rstrip("s"), count=count)
        if counts["retracted"]:
            audit(db, "set_status", "claim", count=counts["retracted"])
        return counts

    return transaction(db, work)


# Confidential labels ---------------------------------------------------------

def labels(db):
    out = []
    for l in db.execute("SELECT * FROM labels ORDER BY set_at DESC"):
        kind, item_id = l["item_type"], l["item_id"]
        if kind == "event":
            row = db.execute("SELECT title, local_day FROM events WHERE id = ?", (item_id,)).fetchone()
            name = row and f"{row['title'] or item_id} ({row['local_day']})"
        elif kind == "claim":
            row = db.execute("SELECT text FROM current_claims WHERE id = ?", (item_id,)).fetchone()
            name = row and row["text"]
        elif kind == "source":
            row = db.execute("SELECT name, kind FROM sources WHERE CAST(id AS TEXT) = ?", (item_id,)).fetchone()
            name = row and f"{row['name']} ({row['kind']})"
        elif kind == "project":
            row = db.execute("SELECT name FROM projects WHERE id = ?", (item_id,)).fetchone()
            name = row and row["name"]
        else:
            row = db.execute("SELECT title FROM artifacts WHERE id = ?", (item_id,)).fetchone()
            name = row and (row["title"] or item_id)
        out.append({"type": kind, "id": item_id, "name": name or item_id, "set_by": l["set_by"], "set_at": l["set_at"]})
    return out


def add_label(db, kind, item_id):
    if kind not in ITEM_TABLES:
        raise Invalid("Label a source, project, event, artifact or claim.")
    key = int(item_id) if kind == "source" and str(item_id).isdigit() else item_id
    if db.execute(f"SELECT 1 FROM {ITEM_TABLES[kind]} WHERE id = ?", (key,)).fetchone() is None:
        raise Invalid(f"There's no {kind} {item_id}.")
    added = db.execute("INSERT OR IGNORE INTO labels VALUES (?, ?, 'confidential', 'me', ?)",
                       (kind, str(item_id), store.now())).rowcount
    if added:
        audit(db, "label", kind, str(item_id))
    return {"type": kind, "id": str(item_id), "labelled": True}


def remove_label(db, kind, item_id):
    removed = db.execute("DELETE FROM labels WHERE item_type = ? AND item_id = ?", (kind, str(item_id))).rowcount
    if not removed:
        raise Invalid(f"{kind} {item_id} isn't labelled confidential.")
    audit(db, "unlabel", kind, str(item_id))
    return {"type": kind, "id": str(item_id), "labelled": False}


# Retention -------------------------------------------------------------------

def retention_settings(db):
    return [dict(r) for r in db.execute("SELECT item_type, days FROM retention ORDER BY item_type")]


def set_retention(db, item_type, days):
    if db.execute("SELECT 1 FROM retention WHERE item_type = ?", (item_type,)).fetchone() is None:
        raise Invalid(f"There's no retention setting for {item_type}.")
    if days is not None and (isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650):
        raise Invalid("Keep it for 1 to 3650 days, or until you delete it.")
    try:
        db.execute("UPDATE retention SET days = ? WHERE item_type = ?", (days, item_type))
    except sqlite3.IntegrityError:
        raise Invalid("That retention isn't allowed.") from None
    audit(db, "settings", "retention", item_type)
    return {"item_type": item_type, "days": days}
