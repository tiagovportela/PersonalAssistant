"""The wiki in the frontend (docs/knowledge_wiki.md, step 4): what I see and change, apart from what Claude sees.

Like admin.py, it sees everything, statements hidden from Claude included, because it's for me. I can read every
version of a page and what changed between two, restore an old version (saved as a new one, by me), delete a page,
and write my notes on a page, which Claude reads as verified. Every change goes into the audit log as mine.
"""

import difflib
import json

import diagrams
import paths
import store
import wiki
import wiki_site
from admin import Invalid, audit, transaction

MISSES = 50


def page_or_project(db, page_id):
    """A stored page, or a project's page not written yet; confidential projects included."""
    row = db.execute("SELECT * FROM wiki_pages WHERE id = ?", (page_id,)).fetchone()
    if row:
        return {**dict(row), "stored": True}
    project = db.execute("SELECT * FROM projects WHERE id = ?", (page_id.removesuffix("-project"),)).fetchone()
    if project and wiki.project_page_id(db, project["id"]) == page_id:
        return {"id": page_id, "kind": "project", "title": project["name"], "project_id": project["id"], "email": None,
                "stored": False}
    raise Invalid(f"There's no wiki page {page_id}.")


def confidential_projects(db):
    return {r[0] for r in db.execute("SELECT item_id FROM labels WHERE item_type = 'project'")}


def overview(db):
    reader = wiki.Reader(db)
    hidden = confidential_projects(db)
    pages = [{**dict(r), "stored": True} for r in db.execute("SELECT * FROM wiki_pages ORDER BY kind, id")]
    have = {p["project_id"] for p in pages}
    pages += [{"id": wiki.project_page_id(db, r["id"]), "kind": "project", "title": r["name"], "project_id": r["id"],
               "email": None, "stored": False} for r in db.execute("SELECT * FROM projects ORDER BY id") if r["id"] not in have]
    rows = []
    for p in pages:
        v = wiki.current(db, p["id"]) if p["stored"] else None
        confidential = p["project_id"] in hidden
        rows.append({"page": p["id"], "kind": p["kind"], "title": p["title"], "project": p["project_id"],
                     "version": v["version"] if v else 0, "updated_at": v["written_at"] if v else None,
                     "written_by": v["written_by"] if v else None, "summary": v["summary"] if v else None,
                     "confidential": confidential,
                     "stale": False if confidential or v is None else reader.staleness(p, v, detail=False)["is_stale"],
                     "has_notes": bool(db.execute("SELECT 1 FROM wiki_notes WHERE page_id = ?", (p["id"],)).fetchone())})
    site = wiki_site.SITE_DIR
    return {"pages": rows, "lint": wiki.lint(db, {}),
            "misses": [dict(r) for r in db.execute("SELECT at, query, kinds, project_id FROM search_misses"
                                                   " ORDER BY at DESC LIMIT ?", (MISSES,))],
            "site": {"path": str(site), "built": (site / "index.html").exists(),
                     "built_at": store.setting(db, "wiki.site_built_at"),
                     "seconds": store.setting(db, "wiki.site_build_seconds")}}


def block_text(st):
    """One stored block as one line of text, for reading versions and diffing them."""
    if st["kind"] == "diagram":
        block = st["block"]
        return f"[{block['type']} diagram] {block['title']}: " + "; ".join(diagrams.as_text(block))
    if st["kind"] == "image":
        return f"[image] {st['block']['path']}: {st['block'].get('caption') or ''}"
    return ("• " if st["style"] == "bullet" else "") + st["text"]


def version_sections(db, page_id, version):
    return [{"id": s["id"], "heading": s["heading"], "lines": [block_text(st) for st in s["statements"]]}
            for s in wiki.stored_sections(db, page_id, version)]


def page(db, page_id):
    p = page_or_project(db, page_id)
    versions = [dict(r) for r in db.execute(
        "SELECT v.version, v.written_at, v.written_by, v.reason, v.summary,"
        " (SELECT COUNT(*) FROM wiki_sections s JOIN wiki_statements st ON st.section_seq = s.seq"
        "  WHERE s.page_id = v.page_id AND s.version = v.version) AS blocks"
        " FROM wiki_versions v WHERE v.page_id = ? ORDER BY v.version DESC", (p["id"],))]
    note = db.execute("SELECT text, changed_at FROM wiki_notes WHERE page_id = ?", (p["id"],)).fetchone()
    return {"page": p["id"], "kind": p["kind"], "title": p["title"], "project": p["project_id"], "email": p["email"],
            "confidential": p["project_id"] in confidential_projects(db),
            "versions": versions, "notes": dict(note) if note else None,
            "sections": version_sections(db, p["id"], versions[0]["version"]) if versions else [],
            "lint": wiki.lint(db, {"page": p["id"]}).get("findings", []) if wiki.page_row(db, p["id"]) else []}


def diff(db, page_id, old, new):
    """What changed from one version to another, section by section: lines added, removed or kept."""
    p = page_or_project(db, page_id)
    have = {r[0] for r in db.execute("SELECT version FROM wiki_versions WHERE page_id = ?", (p["id"],))}
    for v in (old, new):
        if v not in have:
            raise Invalid(f"Page {p['id']} has no version {v} (past versions are kept 90 days).")
    a = {s["id"]: s for s in version_sections(db, p["id"], old)}
    b = {s["id"]: s for s in version_sections(db, p["id"], new)}
    sections = []
    for sid in list(b) + [s for s in a if s not in b]:
        before, after = a.get(sid, {}).get("lines", []), b.get(sid, {}).get("lines", [])
        lines = [{"op": line[0], "text": line[2:]} for line in difflib.ndiff(before, after) if line[0] in " +-"]
        sections.append({"id": sid, "heading": (b.get(sid) or a.get(sid))["heading"],
                         "change": "added" if sid not in a else "removed" if sid not in b else
                         "changed" if before != after else "same", "lines": lines})
    return {"page": p["id"], "from": old, "to": new, "sections": sections}


def restore(db, page_id, version):
    """Brings back an old version, whole, as the newest one, by me."""
    p = page_or_project(db, page_id)
    row = db.execute("SELECT * FROM wiki_versions WHERE page_id = ? AND version = ?", (p["id"], version)).fetchone()
    if row is None:
        raise Invalid(f"Page {p['id']} has no version {version}.")

    def work():
        new = wiki.save_version(db, p, wiki.stored_sections(db, p["id"], version), row["summary"],
                                json.loads(row["key_terms"]), json.loads(row["built_from"]), "me", f"restored version {version}")
        audit(db, "revise", "wiki_page", p["id"])
        return {"page": p["id"], "version": new, "restored": version}
    return transaction(db, work)


def delete_page(db, page_id):
    """Deletes a page with all its versions. A project's page goes back to unwritten."""
    p = page_or_project(db, page_id)
    if not p["stored"]:
        raise Invalid(f"Page {p['id']} isn't written, so there's nothing to delete.")

    def work():
        db.execute("DELETE FROM wiki_pages WHERE id = ?", (p["id"],))
        audit(db, "delete", "wiki_page", p["id"])
        return {"page": p["id"], "deleted": True}
    return transaction(db, work)


def set_notes(db, page_id, text):
    """My notes on a page; empty text removes them. Claude reads them as mine, verified."""
    p = page_or_project(db, page_id)
    text = (text or "").strip()
    if len(text) > 4000:
        raise Invalid("Notes are at most 4,000 characters.")

    def work():
        if not p["stored"]:
            db.execute("INSERT INTO wiki_pages (id, kind, title, project_id, email, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                       (p["id"], p["kind"], p["title"], p["project_id"], p["email"], store.now()))
        if text:
            db.execute("INSERT INTO wiki_notes VALUES (?, ?, ?) ON CONFLICT (page_id) DO UPDATE SET text = excluded.text,"
                       " changed_at = excluded.changed_at", (p["id"], text, store.now()))
        else:
            db.execute("DELETE FROM wiki_notes WHERE page_id = ?", (p["id"],))
        audit(db, "revise", "wiki_notes", p["id"])
        return {"page": p["id"], "notes": text or None}
    return transaction(db, work)


def build(db):
    done = wiki_site.build(db)
    store.set_setting(db, "wiki.site_fingerprint", wiki_site.fingerprint(db))
    return {**done, "built_at": store.setting(db, "wiki.site_built_at"), "url": (paths.DATA_DIR / "wiki" / "index.html").as_uri()}
