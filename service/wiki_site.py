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

import html
import json
import os
import re
import shutil
from collections import defaultdict
from pathlib import Path

import paths
import repos
import store
import wiki
from validate import MARKDOWN_LINK, WIKI_LINK

SITE_DIR = paths.DATA_DIR / "wiki"
ASSETS = Path(__file__).resolve().parent / "wiki_site_assets"
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; base-uri 'none'; "
       "form-action 'none'")
LABELS = ("verified", "repo", "unconfirmed", "disputed")


def esc(text):
    return html.escape(str(text if text is not None else ""), quote=True)


def data(value, indent=None):
    """JSON with no '<', '>' or '&', so nothing in it can close a tag or read as markup, wherever it's opened."""
    text = json.dumps(value, ensure_ascii=False, indent=indent)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def inline(text, known, prefix):
    """A statement's text as HTML: escaped first, then only the allowed marks become tags."""
    parts = re.split(r"(`[^`]*`)", text)
    out = []
    for part in parts:
        if len(part) >= 2 and part.startswith("`") and part.endswith("`"):
            out.append(f"<code>{esc(part[1:-1])}</code>")
            continue
        pieces, last = [], 0
        for m in re.finditer(f"{WIKI_LINK.pattern}|{MARKDOWN_LINK.pattern}", part):
            pieces.append(marks(esc(part[last:m.start()])))
            if m.group(0).startswith("[["):
                target, label = m.group(1), m.group(2) or m.group(1)
                pieces.append(f'<a class="wl" href="{prefix}{esc(target)}.html">{esc(label)}</a>' if target in known
                              else f'<span class="missing">{esc(label)}</span>')
            else:
                image, label, url = m.group(3), m.group(4), m.group(5)
                pieces.append(esc(m.group(0)) if image or not url.startswith("https://") else
                              f'<a href="{esc(url)}" rel="noopener noreferrer" target="_blank">{marks(esc(label))}</a>')
            last = m.end()
        pieces.append(marks(esc(part[last:])))
        out.append("".join(pieces))
    return "".join(out)


def marks(escaped):
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return re.sub(r"(?<![*\w])\*([^*]+)\*(?![*\w])", r"<em>\1</em>", escaped)


def plain(text):
    return wiki.plain(text)


def badge(label):
    return f'<span class="label {esc(label)}">{esc(label)}</span>' if label in LABELS else ""


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
                text = " ".join(plain(b["text"]) for b in s["blocks"])
            else:
                text = " ".join(str(i.get("text") or i.get("title") or i.get("person") or i.get("value") or "")
                                for i in s.get("items", []))
            if text.strip():
                entries.append({"page": page_id, "title": page["title"], "section": s["id"], "heading": s["heading"],
                                "text": text[:4000]})
    return entries


# HTML ------------------------------------------------------------------------------------

def head(title, root):
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
            f'<meta name="referrer" content="no-referrer">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>{esc(title)}</title>\n<link rel="stylesheet" href="{root}assets/site.css">\n</head>\n')


def scripts(root):
    return "".join(f'<script src="{root}{f}"></script>\n' for f in
                   ("data/catalog.js", "data/graph.js", "data/search.js", "assets/site.js"))


def nav(root):
    return (f'<header class="top"><a class="home" href="{root}index.html">Work wiki</a>'
            '<input id="search" type="search" placeholder="Search the wiki" autocomplete="off" aria-label="Search the wiki">'
            '<div id="results" class="results" hidden></div></header>\n')


def cite_html(cite, github):
    if "claim_id" in cite:
        return f'<span class="cite claim">claim {esc(cite["claim_id"])} {badge(cite.get("label"))}</span>'
    if "event_id" in cite:
        return f'<span class="cite event">{esc(cite["event_id"])}</span>'
    if "commit" in cite:
        where = f'{cite["repo"]}@{cite["commit"][:8]}' + (f':{cite["path"]}' if cite.get("path") else "")
        owner = github.get(cite["repo"])
        if owner:
            url = f"https://github.com/{owner}/{'blob' if cite.get('path') else 'commit'}/{cite['commit']}" \
                  + (f"/{cite['path']}" if cite.get("path") else "")
            return f'<a class="cite repo" href="{esc(url)}" rel="noopener noreferrer" target="_blank">{esc(where)}</a>'
        return f'<span class="cite repo">{esc(where)}</span>'
    if "page" in cite:
        return f'<a class="cite page" href="{esc(cite["page"])}.html">{esc(cite["page"])}</a>'
    return ""


def compiled_html(section, known, github):
    items = []
    for b in section["blocks"]:
        tag = "li" if b["style"] == "bullet" else "p"
        cites = "".join(cite_html(c, github) for c in b["cites"])
        items.append(f'<{tag} id="{esc(b["id"])}" class="statement" data-label="{esc(b["label"])}" '
                     f'data-cites="{esc(json.dumps(b["cites"], ensure_ascii=False))}">'
                     f'{inline(b["text"], known, "")} {badge(b["label"])}<span class="cites">{cites}</span></{tag}>')
    body, run = [], []
    for item in items:  # consecutive bullets form one list
        if item.startswith("<li"):
            run.append(item)
            continue
        if run:
            body.append("<ul>" + "".join(run) + "</ul>")
            run = []
        body.append(item)
    if run:
        body.append("<ul>" + "".join(run) + "</ul>")
    return "\n".join(body)


def claim_line(c):
    when = c.get("due_at") or c.get("about_day") or ""
    extra = []
    if c.get("direction"):
        who = c.get("counterparty") if c["direction"] == "mine" else c.get("owner")
        extra.append(("I owe " if c["direction"] == "mine" else "owed to me by ") + (who or "someone"))
    if c.get("overdue"):
        extra.append("overdue")
    return (f'<li data-label="{esc(c.get("label"))}"><span class="when">{esc(when[:10])}</span> {esc(c.get("text"))} '
            f'{badge(c.get("label"))}<span class="meta">{esc(", ".join(extra))}</span>'
            f'<span class="cites"><span class="cite claim">{esc(c.get("claim_id"))}</span></span></li>')


def generated_html(section, known):
    items, sid = section.get("items", []), section["id"]
    if not items:
        return f'<p class="empty">{esc(section.get("summary"))}</p>'
    if sid == "decisions":  # a timeline, by month
        months = defaultdict(list)
        for c in items:
            months[(c.get("about_day") or "")[:7] or "undated"].append(c)
        return '<ol class="timeline">' + "".join(
            f'<li><span class="month">{esc(m)}</span><ul>{"".join(claim_line(c) for c in cs)}</ul></li>'
            for m, cs in sorted(months.items(), reverse=True)) + "</ol>"
    if sid in ("commitments", "open-work"):
        return '<ul class="claims">' + "".join(claim_line(c) for c in items) + "</ul>"
    if sid == "activity":
        top = max([w["commits"] for w in items] + [1])
        return '<table class="activity"><tr><th>Week</th><th>Commits</th><th></th><th>Focus</th></tr>' + "".join(
            f'<tr><td>{esc(w["week"])}</td><td>{esc(w["commits"])}</td><td><meter min="0" max="{top}" '
            f'value="{esc(w["commits"])}"></meter></td><td>{esc(w["focus_minutes"])} min</td></tr>' for w in items) + "</table>"
    if sid == "where-it-lives":
        return '<ul class="aliases">' + "".join(
            f'<li><span class="kind">{esc(a["kind"])}</span> ' + (
                f'<a href="{esc(a["value"])}" rel="noopener noreferrer" target="_blank">{esc(a["value"])}</a>'
                if str(a["value"]).startswith("https://") else esc(a["value"])) + "</li>" for a in items) + "</ul>"
    lines = []
    for i in items:
        page = i.get("page")
        name = i.get("title") or i.get("person") or i.get("project") or page
        link = f'<a href="{esc(page)}.html">{esc(name)}</a>' if page in known else esc(name)
        counts = ", ".join(f"{i[k]} {k if i[k] != 1 else k[:-1]}" for k in ("claims", "commits") if i.get(k))
        lines.append(f'<li>{link}<span class="meta">{esc(counts)}</span></li>')
    return "<ul>" + "".join(lines) + "</ul>"


def page_html(page, known, github):
    root = "../"
    stale = page.get("stale", {})
    parts = [head(f"{page['title']} · Work wiki", root),
             f'<body data-root="{root}" data-page="{esc(page["page"])}">\n', nav(root),
             f'<main>\n<article data-page="{esc(page["page"])}" data-kind="{esc(page["kind"])}">\n'
             f'<p class="kind">{esc(page["kind"])} page · version {esc(page["version"])}'
             + (f' · updated {esc((page.get("updated_at") or "")[:10])}' if page.get("updated_at") else "") + "</p>\n"
             f'<h1>{esc(page["title"])}</h1>\n']
    if page.get("summary"):
        parts.append(f'<p class="summary">{esc(page["summary"])}</p>\n')
    if stale.get("is_stale"):
        parts.append('<div class="stale"><strong>Stale.</strong> ' + " ".join(esc(w) for w in stale.get("why", [])) + "</div>\n")
    if page.get("version", 0) == 0:
        parts.append('<div class="stale">Not written yet. The compile run writes it, or ask Claude to.</div>\n')
    if page.get("my_notes"):
        parts.append(f'<aside class="notes"><h2>My notes</h2><p>{esc(page["my_notes"]["text"])}</p></aside>\n')
    toc = "".join(f'<li><a href="#{esc(s["id"])}">{esc(s["heading"])}</a></li>' for s in page.get("content", []))
    if toc:
        parts.append(f'<nav class="toc"><ul>{toc}</ul></nav>\n')
    for s in page.get("content", []):
        body = compiled_html(s, known, github) if s["source"] == "compiled" else generated_html(s, known)
        parts.append(f'<section id="{esc(s["id"])}" data-source="{esc(s["source"])}">\n<h2>{esc(s["heading"])}</h2>\n'
                     + (f'<p class="section-summary">{esc(s.get("summary"))}</p>\n'
                        if s["source"] == "generated" and s.get("summary") and s.get("items") else "")
                     + body + "\n</section>\n")
    links = page.get("links", []) + [{**l, "from": True} for l in page.get("linked_from", [])]
    if links:
        parts.append('<section id="links"><h2>Linked pages</h2><ul>' + "".join(
            f'<li>{"← " if l.get("from") else "→ "}<a href="{esc(l["page"])}.html">{esc(l.get("title") or l["page"])}</a>'
            f' <span class="meta">{esc(l["type"])}</span></li>' for l in links if l["page"] in known) + "</ul></section>\n")
    if page.get("built_from"):
        parts.append('<p class="built">Built from ' + ", ".join(f'{esc(b["repo"])}@{esc(b["commit"])}' for b in page["built_from"])
                     + "</p>\n")
    parts.append('<section class="graph-box"><h2>Around this page</h2><svg id="graph" class="graph local" role="img" '
                 'aria-label="Pages linked to this one"></svg></section>\n')
    parts.append(f'</article>\n</main>\n<script type="application/json" id="pwi-page">{data(page)}</script>\n'
                 + scripts(root) + "</body>\n</html>\n")
    return "".join(parts)


def index_html(catalog):
    root = ""
    kinds = ["project", "topic", "person"]
    plural = {"project": "Projects", "topic": "Topics", "person": "People"}
    return "".join([
        head("Work wiki", root), f'<body data-root="{root}" data-page="">\n', nav(root),
        '<main class="index">\n<h1>Work wiki</h1>\n',
        f'<p class="summary">{len(catalog)} pages: {sum(e["compiled"] for e in catalog)} written, '
        f'{sum(e["stale"] for e in catalog)} stale. Generated {esc(store.now())}.</p>\n',
        '<div class="filters">' + "".join(f'<label><input type="checkbox" class="kind-filter" value="{k}" checked> {plural[k].lower()}</label>'
                                          for k in kinds) + "</div>\n",
        '<svg id="graph" class="graph full" role="img" aria-label="Every page and the links between them"></svg>\n',
        '<div class="catalog">' + "".join(
            f'<section><h2>{plural[k]}</h2><ul>' + "".join(
                f'<li data-kind="{k}"><a href="pages/{esc(e["page"])}.html">{esc(e["title"])}</a>'
                f'{" <span class=\"label stale\">stale</span>" if e["stale"] else ""}'
                f'<span class="meta">{esc(e.get("summary") or ("not written yet" if not e["compiled"] else ""))}</span></li>'
                for e in catalog if e["kind"] == k) + "</ul></section>" for k in kinds) + "</div>\n",
        "</main>\n", scripts(root), "</body>\n</html>\n"])


# Building ------------------------------------------------------------------------------------

def write(path, text):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)


def build(db, target=None):
    """Builds the site into a new folder and swaps it in. Returns what was built."""
    target = Path(target or SITE_DIR)
    catalog, pages = collect_pages(db)
    known = set(pages)
    github = github_links(db)
    fresh = target.with_name(f"{target.name}.new-{os.getpid()}")
    shutil.rmtree(fresh, ignore_errors=True)
    fresh.mkdir(mode=0o700, parents=True)
    write(fresh / "index.html", index_html(catalog))
    for page_id, page in pages.items():
        write(fresh / "pages" / f"{page_id}.html", page_html(page, known, github))
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
