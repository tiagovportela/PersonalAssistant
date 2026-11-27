"""The wiki as a static site for agents (docs/knowledge_wiki.md): `pwi wiki build` and `pwi wiki open`.

No scripts and no app: every page Claude may see, as Claude sees it, through wiki.py, so labels, hiding and
generated sections are the same, in the formats agents read best. Plain HTML pages come from wiki_site_html.py,
the Markdown, llms.txt and JSONL from wiki_site_text.py, and every piece of text is escaped in both.
The app's Wiki section (`pwi open`) is where I browse the wiki, with a map, search, versions and notes.

    llms.txt            start here: what the wiki is, its files, and every page with a one-line summary
    index.html          the same list as a web page
    pages/<id>.md       one per page, as Markdown, the diagrams as images with a text version
    pages/<id>.html     one per page, as plain HTML with the diagrams drawn inline; its data also inline
    pages/<id>.json     its data, as get_wiki_page returns it
    statements.jsonl    every statement, diagram and image, one per line, to grep without opening a page
    catalog.json        the list of pages; graph.json, the links between them
    diagrams/           each diagram as SVG (with its own style) and PNG (when rsvg-convert is installed)
    images/             documentation images, copied from their repositories
    assets/site.css     a small stylesheet: readable text, and the diagrams' look

It's built into a new folder and swapped in, so a half-built site is never seen. The service rebuilds it within
a minute of any change the wiki shows (a page, a claim, a label, a deletion, retention), so it's a snapshot that
stays close to the store. It lives in the layer's own folder (700, files 600), not in the vault.
"""

import base64
import hashlib
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
import wiki_site_text as text
from wiki_render import data

SITE_DIR = paths.DATA_DIR / "wiki"
ASSETS = Path(__file__).resolve().parent / "wiki_site_assets"


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


def write(path, text):
    write_bytes(path, text.encode("utf-8"))


def write_bytes(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(data)
    os.chmod(path, 0o600)


def copy_images(db, pages, folder):
    """The pages' documentation images, copied from their repositories at the cited commit, named by content.
    Returns block id -> {"image": file name}."""
    names, files = {}, {}
    for page in pages.values():
        for s in page.get("content", []):
            for b in s.get("blocks", []):
                if b.get("kind") != "image":
                    continue
                key = (b["image"]["repo"], b["image"]["commit"], b["image"]["path"])
                if key not in names:
                    names[key] = copy_image(db, key, folder)
                if names[key]:
                    files[b["id"]] = {"image": names[key]}
    return files


def copy_image(db, key, folder):
    repo = repos.by_name(db, key[0])
    kind = repos.image_type(key[2])
    if repo is None or not kind:
        return None
    try:
        data = repos.git_bytes(repo["locator"], "cat-file", "blob", f"{key[1]}:{key[2]}")
    except Exception:
        return None
    name = hashlib.sha256(data).hexdigest()[:32] + "." + kind.split("/")[1].replace("jpeg", "jpg")
    write_bytes(folder / name, data)
    return name


def draw_diagrams(pages, folder):
    """Each diagram as its own SVG, which carries its style, and as a PNG when rsvg-convert is installed, for agents
    that look at pictures. Named <page>.<diagram id>. Returns block id -> {"svg": path, "png": path}."""
    files, used = {}, set()
    for page_id, page in pages.items():
        for s in page.get("content", []):
            for b in s.get("blocks", []):
                if b.get("kind") != "diagram":
                    continue
                name = f"{page_id}.{b['diagram']['id']}"
                name = name if name not in used else f"{name}.{b['id']}"
                used.add(name)
                write(folder / f"{name}.svg", diagrams.render(b["diagram"], pid=name, standalone=True)["svg"] + "\n")
                files[b["id"]] = {"svg": f"{folder.name}/{name}.svg"}
                png = diagrams.preview(b["diagram"])
                if png:
                    write_bytes(folder / f"{name}.png", base64.b64decode(png))
                    files[b["id"]]["png"] = f"{folder.name}/{name}.png"
    return files


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
    built_at = store.now()
    files = {**copy_images(db, pages, fresh / "images"), **draw_diagrams(pages, fresh / "diagrams")}
    write(fresh / "llms.txt", text.llms_txt(catalog, built_at))
    write(fresh / "index.html", view.index_html(catalog, pages))
    for page_id, page in pages.items():
        write(fresh / "pages" / f"{page_id}.html", view.page_html(page, catalog, known, github, files))
        write(fresh / "pages" / f"{page_id}.md", text.page_md(page, known, files))
        write(fresh / "pages" / f"{page_id}.json", data(page, indent=1))
    write(fresh / "statements.jsonl", text.statements_jsonl(pages, files))
    write(fresh / "catalog.json", data({"built_at": built_at, "pages": catalog}, indent=1))
    write(fresh / "graph.json", data(graph(catalog, pages), indent=1))
    write(fresh / "assets" / "site.css", (ASSETS / "site.css").read_text(encoding="utf-8"))
    old = target.with_name(f"{target.name}.old-{os.getpid()}")
    if target.exists():
        target.rename(old)
    fresh.rename(target)
    os.chmod(target, 0o700)
    shutil.rmtree(old, ignore_errors=True)
    store.set_setting(db, "wiki.site_built_at", built_at)
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
