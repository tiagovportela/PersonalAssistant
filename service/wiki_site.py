"""The wiki as a static site (docs/knowledge_wiki.md, step 3): `pwi wiki build` and `pwi wiki open`.

The site is a rendering of the store: every page Claude may see, as Claude sees it, through wiki.py, so
labels, hiding and generated sections are the same. Only code writes HTML: every piece of text is escaped,
and statements' small Markdown subset (bold, italics, code, [[page]] links and https links) is turned into
tags here, never passed through. Each page has a strict Content-Security-Policy, no inline scripts, and loads
nothing from the network. The data goes in classic <script src> files that set a global, since browsers block
fetch and module scripts on file://.

    index.html          catalog, search and the full graph
    pages/<id>.html     one per page; its data also inline (<script type="application/json">) and in
    pages/<id>.json     for agents that only read files
    catalog.json        the catalog, for the same agents
    assets/site.css, assets/site.js     the look, and the graph, search and filters (written here, no library)
    data/catalog.js, data/graph.js, data/search.js

It's built into a new folder and swapped in, so a half-built site is never seen. The service rebuilds it within
a minute of any change the wiki shows (a page, a claim, a label, a deletion, retention), so it's a snapshot that
stays close to the store. It lives in the layer's own folder (700, files 600), not in the vault.
"""

import hashlib
import html
import json
import os
import shutil
import time
from pathlib import Path

import diagrams
import paths
import repos
import store
import wiki
import wiki_site_html as view

SITE_DIR = paths.DATA_DIR / "wiki"
ASSETS = Path(__file__).resolve().parent / "wiki_site_assets"


def esc(text):
    return html.escape(str(text if text is not None else ""), quote=True)


def data(value, indent=None):
    """JSON with no '<', '>' or '&', so nothing in it can close a tag or read as markup, wherever it's opened."""
    text = json.dumps(value, ensure_ascii=False, indent=indent)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def plain(text):
    return wiki.plain(text)


# The data the site is made of --------------------------------------------------------

def github_links(db):
    """repo name -> GitHub owner/repo, for linking cited commits and files."""
    found = {}
    for r in repos.visible_repos(db):
        github = [a["value"] for a in db.execute("SELECT value FROM project_aliases WHERE kind = 'github_repo'"
                                                 " AND project_id = ?", (r["project_id"],))]
        if len(github) == 1:
            found[r["repo"]] = github[0]
    return found


def collect_pages(db):
    """Every visible page as get_wiki_page returns it, with every section in full."""
    catalog = wiki.get_wiki_page(db, {})
    pages = {}
    for entry in catalog.get("pages", []):
        outline = wiki.get_wiki_page(db, {"page": entry["page"]})
        ids = [s["id"] for s in outline.get("sections", [])]
        pages[entry["page"]] = wiki.get_wiki_page(db, {"page": entry["page"], **({"sections": ids} if ids else {})})
    return catalog.get("pages", []), pages


def graph(catalog, pages):
    nodes = [{"id": e["page"], "title": e["title"], "kind": e["kind"], "compiled": e["compiled"], "stale": e["stale"]}
             for e in catalog]
    edges = sorted({(p, link["page"]) for p, page in pages.items() for link in page.get("links", [])
                    if link["page"] in pages})
    return {"nodes": nodes, "edges": [{"from": a, "to": b} for a, b in edges]}


def search_index(pages):
    entries = []
    for page_id, page in pages.items():
        entries.append({"page": page_id, "title": page["title"], "section": "", "heading": page["title"],
                        "text": " ".join(filter(None, [page.get("summary"), " ".join(page.get("key_terms", []))]))})
        for s in page.get("content", []):
            if s["source"] == "compiled":
                text = " ".join(plain(b["text"]) if "text" in b else diagrams.plain_text(b["diagram"]) if "diagram" in b
                                else b.get("caption") or b["image"]["path"] for b in s["blocks"])
            else:
                text = " ".join(str(i.get("text") or i.get("title") or i.get("person") or i.get("value") or "")
                                for i in s.get("items", []))
            if text.strip():
                entries.append({"page": page_id, "title": page["title"], "section": s["id"], "heading": s["heading"],
                                "text": text[:4000]})
    return entries


# Building ------------------------------------------------------------------------------------

def write(path, text):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)


def copy_images(db, pages, folder):
    """The pages' documentation images, copied from their repositories at the cited commit, named by content."""
    names = {}
    for page in pages.values():
        for s in page.get("content", []):
            for b in s.get("blocks", []):
                if b.get("kind") != "image":
                    continue
                key = (b["image"]["repo"], b["image"]["commit"], b["image"]["path"])
                repo = repos.by_name(db, key[0])
                if repo is None or key in names:
                    continue
                try:
                    data = repos.git_bytes(repo["locator"], "cat-file", "blob", f"{key[1]}:{key[2]}")
                except Exception:
                    continue
                kind = repos.image_type(key[2])
                if not kind:
                    continue
                name = hashlib.sha256(data).hexdigest()[:32] + "." + kind.split("/")[1].replace("jpeg", "jpg")
                folder.mkdir(mode=0o700, parents=True, exist_ok=True)
                (folder / name).write_bytes(data)
                os.chmod(folder / name, 0o600)
                names[key] = name
    return names


def build(db, target=None):
    """Builds the site into a new folder and swaps it in. Returns what was built."""
    target = Path(target or SITE_DIR)
    started = time.monotonic()
    catalog, pages = collect_pages(db)
    known = set(pages)
    github = github_links(db)
    fresh = target.with_name(f"{target.name}.new-{os.getpid()}")
    shutil.rmtree(fresh, ignore_errors=True)
    fresh.mkdir(mode=0o700, parents=True)
    write(fresh / "index.html", view.index_html(catalog, pages))
    images = copy_images(db, pages, fresh / "images")
    for page_id, page in pages.items():
        write(fresh / "pages" / f"{page_id}.html", view.page_html(page, catalog, known, github, images))
        write(fresh / "pages" / f"{page_id}.json", data(page, indent=1))
    write(fresh / "catalog.json", data({"pages": catalog}, indent=1))
    write(fresh / "data" / "catalog.js", f"window.PWI_CATALOG = {data(catalog)};\n")
    write(fresh / "data" / "graph.js", f"window.PWI_GRAPH = {data(graph(catalog, pages))};\n")
    write(fresh / "data" / "search.js", f"window.PWI_SEARCH = {data(search_index(pages))};\n")
    for asset in ("site.css", "site.js"):
        write(fresh / "assets" / asset, (ASSETS / asset).read_text(encoding="utf-8"))
    old = target.with_name(f"{target.name}.old-{os.getpid()}")
    if target.exists():
        target.rename(old)
    fresh.rename(target)
    os.chmod(target, 0o700)
    shutil.rmtree(old, ignore_errors=True)
    store.set_setting(db, "wiki.site_built_at", store.now())
    store.set_setting(db, "wiki.site_build_seconds", round(time.monotonic() - started, 1))
    return {"path": str(target), "pages": len(pages), "written": sum(e["compiled"] for e in catalog)}


def fingerprint(db):
    """Changes whenever something the site shows may have: a page, a claim, a label, an event, a deletion
    (every delete and retention pass is in the audit trail), a source turned on or off, my notes."""
    row = db.execute(
        "SELECT (SELECT MAX(id) FROM audit_log), (SELECT MAX(seq) FROM claim_versions), (SELECT MAX(seq) FROM"
        " wiki_versions), (SELECT COUNT(*) FROM labels), (SELECT MAX(seq) FROM events), (SELECT COUNT(*) FROM events),"
        " (SELECT group_concat(id || ':' || enabled) FROM sources), (SELECT MAX(changed_at) FROM wiki_notes),"
        " (SELECT COUNT(*) FROM projects)").fetchone()
    return json.dumps(list(row))


def rebuild_store(store_path, target=None):
    """rebuild_if_changed with its own connection, for the service's scheduler thread."""
    from contextlib import closing
    with closing(store.connect(store_path)) as db:
        return rebuild_if_changed(db, target)


def rebuild_if_changed(db, target=None):
    """Called every minute by the service: rebuilds when the fingerprint moved. Returns whether it built."""
    now = fingerprint(db)
    if now == store.setting(db, "wiki.site_fingerprint") and Path(target or SITE_DIR).exists():
        return False
    build(db, target)
    store.set_setting(db, "wiki.site_fingerprint", now)
    return True
