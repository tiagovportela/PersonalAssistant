"""The wiki's static site as plain HTML: for agents first, and readable by me in any browser.

No scripts at all (the CSP has no script-src, so nothing could run), no map and no search: a list of pages, and per
page its text, each statement with its label as a word and its sources, the diagrams as inline SVG with a text
version and links to their SVG and PNG files, and the images. Each page carries its data as JSON too, and links to
its Markdown and JSON, which wiki_site_text.py and wiki_site.py write. The app's Wiki section (`pwi open`) is where
the wiki is browsed with a map, search and versions.

Everything from the store is escaped (wiki_render.py). A small stylesheet keeps it readable and draws the diagrams,
whose SVG uses classes only.
"""

from collections import defaultdict
from datetime import date

import diagrams
import store
from wiki_render import LABELS, activity_svg, data, diagram_svg, esc, inline, repo_map_svgs

CSP = "default-src 'none'; style-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'"
KINDS = ("project", "topic", "person")
KIND_NAMES = {"project": "Projects", "topic": "Topics", "person": "People"}
KIND_ONE = {"project": "Project", "topic": "Topic", "person": "Person"}


def short_date(text):
    try:
        return date.fromisoformat(str(text)[:10]).isoformat()
    except ValueError:
        return esc(text)


def badge(label):
    """A label as a word, in brackets, so it reads the same with or without the stylesheet."""
    return f'<span class="label {esc(label)}">[{esc(label)}]</span>' if label in LABELS else ""


def head(title, root, alternates=()):
    """The page's head; alternates are (media type, href) of the same content in other formats."""
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
            f'<meta name="referrer" content="no-referrer">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>{esc(title)}</title>\n<link rel="stylesheet" href="{root}assets/site.css">\n'
            + "".join(f'<link rel="alternate" type="{kind}" href="{esc(href)}">\n' for kind, href in alternates)
            + "</head>\n")


def cite_text(cite, github):
    if "claim_id" in cite:
        return f'claim <code>{esc(cite["claim_id"])}</code> {badge(cite.get("label"))}'
    if "event_id" in cite:
        return f'event <code>{esc(cite["event_id"])}</code>'
    if "commit" in cite:
        where = f'{cite["repo"]}@{cite["commit"][:8]}' + (f':{cite["path"]}' if cite.get("path") else "")
        owner = github.get(cite["repo"])
        if owner:
            url = (f"https://github.com/{owner}/{'blob' if cite.get('path') else 'commit'}/{cite['commit']}"
                   + (f"/{cite['path']}" if cite.get("path") else ""))
            return f'<a href="{esc(url)}" rel="noopener noreferrer"><code>{esc(where)}</code></a>'
        return f"<code>{esc(where)}</code>"
    if "page" in cite:
        return f'page <a href="{esc(cite["page"])}.html">{esc(cite["page"])}</a>'
    return ""


def sources(cites, github):
    return '<span class="sources">Sources: ' + "; ".join(cite_text(c, github) for c in cites) + "</span>"


def figure_html(b, github, files):
    drawn = files.get(b["id"], {})
    if b["kind"] == "diagram":
        d = b["diagram"]
        lines = "".join(f"<li>{esc(line)}</li>" for line in diagrams.as_text(d))
        links = " · ".join(f'<a href="../{esc(drawn[kind])}">{kind.upper()}</a>' for kind in ("svg", "png") if drawn.get(kind))
        return (f'<figure id="{esc(b["id"])}" class="diagram" data-label="{esc(b["label"])}" data-diagram="{esc(d["id"])}">'
                f'<div class="drawing">{diagram_svg(b)}</div>'
                f'<figcaption><strong>{esc(d["title"])}</strong>' + (f". {esc(d['caption'])}" if d.get("caption") else "")
                + f' {badge(b["label"])} {sources(b["cites"], github)}'
                + (f'<span class="files">Files: {links}</span>' if links else "") + "</figcaption>"
                f'<details><summary>Diagram as text</summary><ul>{lines}</ul></details></figure>')
    name = drawn.get("image")
    picture = (f'<img src="../images/{esc(name)}" alt="{esc(b.get("caption") or b["image"]["path"])}">' if name
               else f'<p>{esc(b["image"]["path"])} couldn\'t be copied.</p>')
    return (f'<figure id="{esc(b["id"])}" class="image" data-label="{esc(b["label"])}">{picture}'
            f'<figcaption>{esc(b.get("caption") or "")} {badge(b["label"])} {sources(b["cites"], github)}</figcaption></figure>')


def compiled_html(section, known, github, files):
    out, run = [], []
    def flush():
        if run:
            out.append("<ul>" + "".join(run) + "</ul>")
            run.clear()
    for b in section["blocks"]:
        if b.get("kind") in ("diagram", "image"):
            flush()
            out.append(figure_html(b, github, files))
            continue
        body = f'{inline(b["text"], known, lambda t: f"{t}.html")} {badge(b["label"])} {sources(b["cites"], github)}'
        attrs = f'id="{esc(b["id"])}" class="statement" data-label="{esc(b["label"])}"'
        if b["style"] == "bullet":
            run.append(f"<li {attrs}>{body}</li>")
        else:
            flush()
            out.append(f"<p {attrs}>{body}</p>")
    flush()
    return "\n".join(out)


def claim_line(c):
    when = (c.get("due_at") or c.get("about_day") or "")[:10]
    extra = []
    if c.get("direction"):
        mine = c["direction"] == "mine"
        who = (c.get("counterparty") if mine else c.get("owner")) or "someone"
        extra.append(("I owe " if mine else "owed to me by ") + who)
    if c.get("overdue"):
        extra.append("overdue")
    return (f'<li data-label="{esc(c.get("label"))}">{esc(when)} {esc(c.get("text"))} {badge(c.get("label"))}'
            + (f' <span class="meta">({esc(", ".join(extra))})</span>' if extra else "")
            + f' <code>{esc(c.get("claim_id"))}</code></li>')


def generated_html(section, known):
    items, sid = section.get("items", []), section["id"]
    if not items:
        return f'<p class="meta">{esc(section.get("summary"))}</p>'
    if sid == "decisions":
        months = defaultdict(list)
        for c in items:
            months[(c.get("about_day") or "")[:7] or "undated"].append(c)
        return "".join(f'<h3 class="month">{esc(m)}</h3><ul>{"".join(claim_line(c) for c in cs)}</ul>'
                       for m, cs in sorted(months.items(), reverse=True))
    if sid in ("commitments", "open-work"):
        return "<ul>" + "".join(claim_line(c) for c in items) + "</ul>"
    if sid == "activity":
        rows = "".join(f'<tr><td>{esc(w["week"])}</td><td>{w["commits"]}</td><td>{w["focus_minutes"]} min</td></tr>'
                       for w in sorted(items, key=lambda w: w["week"], reverse=True))
        return (f'<div class="drawing">{activity_svg(items)}</div>'
                f'<table><thead><tr><th>Week</th><th>Commits</th><th>Focus</th></tr></thead><tbody>{rows}</tbody></table>')
    if sid == "where-it-lives":
        return "<dl>" + "".join(
            f'<dt>{esc(a["kind"])}</dt><dd>' + (
                f'<a href="{esc(a["value"])}" rel="noopener noreferrer">{esc(a["value"])}</a>'
                if str(a["value"]).startswith("https://") else f'<code>{esc(a["value"])}</code>') + "</dd>"
            for a in items) + "</dl>"
    if sid == "repo-map":
        return "".join(f'<div class="drawing">{svg}</div>' for svg in repo_map_svgs(items))
    lines = []
    for i in items:
        page = i.get("page")
        name = i.get("title") or i.get("person") or i.get("project") or page
        link = f'<a href="{esc(page)}.html">{esc(name)}</a>' if page in known else esc(name)
        counts = ", ".join(f"{i[k]} {k if i[k] != 1 else k[:-1]}" for k in ("claims", "commits") if i.get(k))
        lines.append(f"<li>{link}" + (f' <span class="meta">({esc(counts)})</span>' if counts else "") + "</li>")
    return "<ul>" + "".join(lines) + "</ul>"


def page_html(page, catalog, known, github, files=None):
    root = "../"
    stale = page.get("stale", {})
    meta = [f'{KIND_ONE.get(page["kind"], "")} page', f'version {esc(page["version"])}']
    if page.get("updated_at"):
        meta.append(f'updated {short_date(page["updated_at"])} by {"me" if page.get("written_by") == "me" else "Claude"}')
    if page.get("built_from"):
        meta.append("built from " + ", ".join(f'<code>{esc(b["repo"])}@{esc(b["commit"][:8])}</code>'
                                              for b in page["built_from"]))
    alternates = (("text/markdown", f"{page['page']}.md"), ("application/json", f"{page['page']}.json"))
    parts = [head(f"{page['title']} · Work wiki", root, alternates),
             f'<body data-page="{esc(page["page"])}">\n<p class="crumbs"><a href="{root}index.html">Work wiki</a> / '
             f'{KIND_NAMES.get(page["kind"], "")}</p>\n'
             f'<article data-page="{esc(page["page"])}" data-kind="{esc(page["kind"])}">\n<h1>{esc(page["title"])}</h1>\n']
    if page.get("summary"):
        parts.append(f'<p class="summary">{esc(page["summary"])}</p>\n')
    meta.append(f'also as <a href="{esc(page["page"])}.md">Markdown</a> and <a href="{esc(page["page"])}.json">JSON</a>')
    parts.append(f'<p class="meta">{" · ".join(meta)}</p>\n')
    if stale.get("is_stale"):
        parts.append('<p class="note"><strong>Stale.</strong> ' + " ".join(esc(w) for w in stale.get("why", [])) + "</p>\n")
    if page.get("version", 0) == 0:
        parts.append('<p class="note">Not written yet.</p>\n')
    if page.get("my_notes"):
        parts.append(f'<aside class="note"><strong>My notes</strong> {badge("verified")}: {esc(page["my_notes"]["text"])}</aside>\n')
    toc = "".join(f'<li><a href="#{esc(s["id"])}">{esc(s["heading"])}</a></li>' for s in page.get("content", []))
    if toc:
        parts.append(f"<nav><h2>Contents</h2><ul>{toc}</ul></nav>\n")
    for s in page.get("content", []):
        body = compiled_html(s, known, github, files or {}) if s["source"] == "compiled" else generated_html(s, known)
        parts.append(f'<section id="{esc(s["id"])}" data-source="{esc(s["source"])}">\n<h2>{esc(s["heading"])}</h2>\n'
                     + (f'<p class="meta">{esc(s.get("summary"))}</p>\n' if s["source"] == "generated" and s.get("items") else "")
                     + body + "\n</section>\n")
    links = [l for l in page.get("links", []) if l["page"] in known]
    back = [l for l in page.get("linked_from", []) if l["page"] in known]
    if links or back:
        parts.append('<section id="links"><h2>Linked pages</h2><ul>' + "".join(
            f'<li>{arrow} <a href="{esc(l["page"])}.html">{esc(l.get("title") or l["page"])}</a> '
            f'<span class="meta">({esc(KIND_ONE.get(l["type"], l["type"]))})</span></li>'
            for arrow, entries in (("→", links), ("←", back)) for l in entries) + "</ul></section>\n")
    parts.append(f'</article>\n<script type="application/json" id="pwi-page">{data(page)}</script>\n</body>\n</html>\n')
    return "".join(parts)


def index_html(catalog, pages):
    groups = []
    for kind in KINDS:
        entries = [e for e in catalog if e["kind"] == kind]
        if not entries:
            continue
        items = "".join(
            f'<li><a href="pages/{esc(e["page"])}.html">{esc(e["title"])}</a>'
            + (f' — {esc(e["summary"])}' if e.get("summary") else "")
            + f' <span class="meta">({"version " + str(e["version"]) if e["compiled"] else "not written yet"}'
            + (", stale" if e["stale"] else "") + ")</span></li>" for e in entries)
        groups.append(f"<h2>{KIND_NAMES[kind]}</h2>\n<ul>{items}</ul>\n")
    return "".join([
        head("Work wiki", "", (("text/plain", "llms.txt"), ("application/json", "catalog.json"))),
        "<body>\n<h1>Work wiki</h1>\n",
        f'<p class="meta">{len(catalog)} pages, built {short_date(store.now())}. For agents: start with '
        '<a href="llms.txt">llms.txt</a>. Each page is also Markdown (<code>pages/&lt;id&gt;.md</code>) and JSON '
        '(<code>pages/&lt;id&gt;.json</code>); <a href="statements.jsonl">statements.jsonl</a> has every statement, '
        'one per line, to search; <a href="catalog.json">catalog.json</a> lists the pages and '
        '<a href="graph.json">graph.json</a> links them; diagrams are in <code>diagrams/</code> as SVG and PNG. '
        'Browse it with its map, search and versions in the app: <code>pwi open</code>, then Wiki.</p>\n',
        *groups, "</body>\n</html>\n"])
