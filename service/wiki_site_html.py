"""The wiki site's HTML: presentation only (wiki_site.py builds the data and the files).

Soft Technical Minimalism: a warm off-white canvas, white panels with thin borders and soft radii, tonal layering
instead of shadows, and muted accents kept for data and states. Every colour, radius, space and motion is a token in
assets/site.css; this module writes only structure and classes, since the CSP allows no inline styles.

Everything from the store is escaped here. Statements' small Markdown subset (bold, italics, code, [[page]] links,
https links) becomes tags here and nowhere else. Charts are SVG drawn from data, with their numbers also in text, and
labels are always a word next to their colour, never the colour alone.
"""

import html
import json
import re
from collections import Counter, defaultdict
from datetime import date

import diagrams
import store
from validate import MARKDOWN_LINK, WIKI_LINK

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; base-uri 'none'; "
       "form-action 'none'")
LABELS = ("verified", "repo", "unconfirmed", "disputed")
LABEL_NAMES = {"verified": "Verified", "repo": "Repository", "unconfirmed": "Unconfirmed", "disputed": "Disputed"}
KINDS = ("project", "topic", "person")
KIND_NAMES = {"project": "Projects", "topic": "Topics", "person": "People"}
KIND_ONE = {"project": "Project", "topic": "Topic", "person": "Person"}

# Outline icons, 16 px, stroked in the current colour.
ICONS = {
    "search": '<circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5 14 14"/>',
    "overview": '<rect x="2" y="2" width="5" height="5" rx="1.5"/><rect x="9" y="2" width="5" height="5" rx="1.5"/>'
                '<rect x="2" y="9" width="5" height="5" rx="1.5"/><rect x="9" y="9" width="5" height="5" rx="1.5"/>',
    "alert": '<path d="M8 2.5 14 13H2Z"/><path d="M8 6.5v3"/><path d="M8 11.5v.01"/>',
    "sources": '<path d="M4 2.5h6l2.5 2.5v8.5H4Z"/><path d="M6.5 8h4M6.5 10.5h4"/>',
    "commit": '<circle cx="8" cy="8" r="2.5"/><path d="M2 8h3.5M10.5 8H14"/>',
    "out": '<path d="M9 3h4v4"/><path d="M13 3 7.5 8.5"/><path d="M11 9.5V13H3V5h3.5"/>',
    "in": '<path d="M7 13H3V9"/><path d="M3 13l5.5-5.5"/><path d="M5 6.5V3h8v8H9.5"/>',
    "note": '<path d="M3 2.5h10v11H3Z"/><path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3"/>',
}


def icon(name):
    return (f'<svg class="icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">'
            f'{ICONS[name]}</svg>')


def esc(text):
    return html.escape(str(text if text is not None else ""), quote=True)


def data(value):
    text = json.dumps(value, ensure_ascii=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def short_date(text):
    """'2026-11-27T11:32:05Z' as 'Nov 27, 2026'; the same for a bare date."""
    try:
        return date.fromisoformat(str(text)[:10]).strftime("%b %-d, %Y")
    except ValueError:
        return esc(text)


# Statements' text ---------------------------------------------------------------------------

def inline(text, known, prefix):
    """A statement's text as HTML: escaped first, then only the allowed marks become tags."""
    out = []
    for part in re.split(r"(`[^`]*`)", text):
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


def badge(label):
    """A label as a coloured dot and its word: never colour alone."""
    if label not in LABELS:
        return ""
    return f'<span class="label {esc(label)}"><span class="dot" aria-hidden="true"></span>{esc(label)}</span>'


# Charts: SVG from data, numbers also in text -------------------------------------------------

def label_bar(counts, wide=False):
    """How a page's or the wiki's statements split by label: a rounded stacked bar and its legend."""
    total = sum(counts.get(l, 0) for l in LABELS)
    if not total:
        return '<p class="quiet">No statements yet.</p>'
    width, x, parts = 100.0, 0.0, []
    for label in LABELS:
        n = counts.get(label, 0)
        if n:
            w = width * n / total
            parts.append(f'<rect class="seg {label}" x="{x:.2f}" y="0" width="{max(w - 0.6, 0.4):.2f}" height="8" rx="4">'
                         f'<title>{LABEL_NAMES[label]}: {n}</title></rect>')
            x += w
    legend = "".join(f'<li>{badge(l)}<span class="num">{counts.get(l, 0)}</span></li>' for l in LABELS if counts.get(l))
    return (f'<div class="label-bar{" wide" if wide else ""}"><svg viewBox="0 0 100 8" preserveAspectRatio="none" '
            f'role="img" aria-label="Statements by label">{"".join(parts)}</svg><ul class="legend">{legend}</ul></div>')


def activity_chart(weeks):
    """Commits per week as rounded bars on a quiet grid; focus time in the tooltip and the table below."""
    weeks = sorted(weeks, key=lambda w: w["week"])
    top = max([w["commits"] for w in weeks] + [1])
    step, height, base = 34, 96, 108
    width = max(40 + step * len(weeks), 320)
    ticks = [0, top] if top < 4 else [0, top // 2, top]  # only lines that add a distinct value
    grid = "".join(f'<line class="grid" x1="32" x2="{width}" y1="{base - height * t / top:.1f}" y2="{base - height * t / top:.1f}"/>'
                   f'<text class="axis" x="26" y="{base - height * t / top + 4:.1f}">{t}</text>' for t in ticks)
    bars = []
    for i, w in enumerate(weeks):
        h = max(2.0, height * w["commits"] / top) if w["commits"] else 0
        x = 40 + i * step
        bars.append(f'<g class="bar"><rect x="{x}" y="{base - h:.1f}" width="20" height="{h:.1f}" rx="5">'
                    f'<title>{esc(w["week"])}: {w["commits"]} commits, {w["focus_minutes"]} min focus</title></rect>'
                    f'<text class="axis" x="{x + 10}" y="{base + 16}">{esc(w["week"][-3:])}</text></g>')
    return (f'<figure class="chart"><svg viewBox="0 0 {width} {base + 24}" width="{width}" height="{base + 24}" role="img" '
            f'aria-label="Commits per week">{grid}{"".join(bars)}</svg>'
            f'<figcaption class="quiet">Commits per week. Hover a bar for focus time.</figcaption></figure>')


# Pieces of a page ----------------------------------------------------------------------------

def head(title, root):
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
            f'<meta name="referrer" content="no-referrer">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>{esc(title)}</title>\n<link rel="stylesheet" href="{root}assets/site.css">\n</head>\n')


def scripts(root):
    return "".join(f'<script src="{root}{f}"></script>\n' for f in
                   ("data/catalog.js", "data/graph.js", "data/search.js", "assets/site.js"))


def sidebar(catalog, root, current=""):
    groups = []
    for kind in KINDS:
        entries = [e for e in catalog if e["kind"] == kind]
        if not entries:
            continue
        items = "".join(
            f'<li><a href="{root}pages/{esc(e["page"])}.html"{" aria-current=\"page\"" if e["page"] == current else ""}>'
            f'<span class="name">{esc(e["title"])}</span>'
            + ('<span class="state stale" title="Stale">stale</span>' if e["stale"] else
               '<span class="state unwritten" title="Not written yet">new</span>' if not e["compiled"] else "")
            + "</a></li>" for e in entries)
        groups.append(f'<div class="nav-group"><p class="nav-title">{KIND_NAMES[kind]}</p><ul>{items}</ul></div>')
    return (f'<aside class="sidebar" aria-label="Wiki navigation">'
            f'<a class="brand" href="{root}index.html"><span class="brand-mark" aria-hidden="true"></span>Work wiki</a>'
            f'<div class="search" role="search">{icon("search")}'
            f'<input id="search" type="search" placeholder="Search the wiki" autocomplete="off" aria-label="Search the wiki" '
            f'aria-controls="results">'
            f'<div id="results" class="popover results" hidden></div></div>'
            f'<nav><a class="nav-top" href="{root}index.html"{" aria-current=\"page\"" if not current else ""}>'
            f'{icon("overview")}Overview</a>{"".join(groups)}</nav>'
            f'<p class="sidebar-foot">Built {short_date(store.now())}. A snapshot of the layer, rebuilt within a minute '
            f'of a change.</p></aside>\n')


def cite_html(cite, github):
    if "claim_id" in cite:
        return f'<li>{icon("sources")}<span class="mono">{esc(cite["claim_id"])}</span>{badge(cite.get("label"))}</li>'
    if "event_id" in cite:
        return f'<li>{icon("commit")}<span class="mono">{esc(cite["event_id"])}</span></li>'
    if "commit" in cite:
        where = f'{cite["repo"]}@{cite["commit"][:8]}' + (f':{cite["path"]}' if cite.get("path") else "")
        owner = github.get(cite["repo"])
        if owner:
            url = (f"https://github.com/{owner}/{'blob' if cite.get('path') else 'commit'}/{cite['commit']}"
                   + (f"/{cite['path']}" if cite.get("path") else ""))
            return (f'<li>{icon("commit")}<a class="mono" href="{esc(url)}" rel="noopener noreferrer" '
                    f'target="_blank">{esc(where)}</a></li>')
        return f'<li>{icon("commit")}<span class="mono">{esc(where)}</span></li>'
    if "page" in cite:
        return f'<li>{icon("out")}<a href="{esc(cite["page"])}.html">{esc(cite["page"])}</a></li>'
    return ""


def sources(cites, github):
    """A statement's evidence behind a small button, opened in place: progressive disclosure, no page change."""
    n = len(cites)
    return (f'<details class="sources"><summary aria-label="{n} source{"s" if n != 1 else ""}">{icon("sources")}'
            f'<span class="num">{n}</span></summary><ul class="popover">{"".join(cite_html(c, github) for c in cites)}</ul>'
            f'</details>')


def figure_html(b, cites, images):
    if b["kind"] == "diagram":
        d = b["diagram"]
        drawn = diagrams.render(d, pid=f"dg-{b['id']}")
        lines = "".join(f"<li>{esc(line)}</li>" for line in diagrams.as_text(d))
        return (f'<figure id="{esc(b["id"])}" class="diagram" data-label="{esc(b["label"])}" data-diagram="{esc(d["id"])}">'
                f'<div class="figure-head"><div><p class="figure-title">{esc(d["title"])}</p>'
                + (f'<p class="quiet">{esc(d["caption"])}</p>' if d.get("caption") else "")
                + f'</div><div class="figure-meta">{badge(b["label"])}{cites}</div></div>'
                f'<div class="dg-scroll">{drawn["svg"]}</div>'
                f'<details class="as-text"><summary>Diagram as text</summary><ul>{lines}</ul></details></figure>')
    name = images.get((b["image"]["repo"], b["image"]["commit"], b["image"]["path"]))
    picture = (f'<img src="../images/{esc(name)}" alt="{esc(b.get("caption") or b["image"]["path"])}">' if name
               else f'<p class="quiet">{esc(b["image"]["path"])} couldn\'t be copied.</p>')
    return (f'<figure id="{esc(b["id"])}" class="image" data-label="{esc(b["label"])}">{picture}'
            f'<figcaption><span>{esc(b.get("caption") or "")}</span><span class="figure-meta">{badge(b["label"])}{cites}'
            f'</span></figcaption></figure>')


def compiled_html(section, known, github, images):
    out, run = [], []
    def flush():
        if run:
            out.append('<ul class="bullets">' + "".join(run) + "</ul>")
            run.clear()
    for b in section["blocks"]:
        cites = sources(b["cites"], github)
        if b.get("kind") in ("diagram", "image"):
            flush()
            out.append(figure_html(b, cites, images))
            continue
        body = (f'<span class="st-text">{inline(b["text"], known, "")}</span>'
                f'<span class="st-meta">{badge(b["label"])}{cites}</span>')
        attrs = f'id="{esc(b["id"])}" class="statement" data-label="{esc(b["label"])}"'
        if b["style"] == "bullet":
            run.append(f"<li {attrs}>{body}</li>")
        else:
            flush()
            out.append(f"<div {attrs}>{body}</div>")
    flush()
    return "\n".join(out)


def claim_row(c):
    when = (c.get("due_at") or c.get("about_day") or "")[:10]
    who = ""
    if c.get("direction"):
        mine = c["direction"] == "mine"
        person = (c.get("counterparty") if mine else c.get("owner")) or "someone"
        who = (f'<span class="who">{icon("out" if mine else "in")}'
               f'{"I owe " if mine else "owed to me by "}{esc(person)}</span>')
    due = f'<span class="date{" overdue" if c.get("overdue") else ""}">{esc(when)}{" · overdue" if c.get("overdue") else ""}</span>'
    return (f'<li class="row" data-label="{esc(c.get("label"))}"><span class="row-main">{esc(c.get("text"))}{who}</span>'
            f'<span class="row-meta">{due}{badge(c.get("label"))}<span class="mono quiet">{esc(c.get("claim_id"))}</span></span></li>')


def generated_html(section, known):
    items, sid = section.get("items", []), section["id"]
    if not items:
        return f'<p class="empty">{esc(section.get("summary"))}</p>'
    if sid == "decisions":  # a timeline, by month
        months = defaultdict(list)
        for c in items:
            months[(c.get("about_day") or "")[:7] or "undated"].append(c)
        return '<ol class="timeline">' + "".join(
            f'<li><span class="month">{esc(m)}</span><ul class="rows">{"".join(claim_row(c) for c in cs)}</ul></li>'
            for m, cs in sorted(months.items(), reverse=True)) + "</ol>"
    if sid in ("commitments", "open-work"):
        return '<ul class="rows">' + "".join(claim_row(c) for c in items) + "</ul>"
    if sid == "activity":
        rows = "".join(f'<tr><td class="mono">{esc(w["week"])}</td><td class="num">{w["commits"]}</td>'
                       f'<td class="num">{w["focus_minutes"]} min</td></tr>' for w in items)
        return (activity_chart(items) + '<details class="as-text"><summary>As a table</summary><table class="table">'
                f'<thead><tr><th>Week</th><th class="num">Commits</th><th class="num">Focus</th></tr></thead>'
                f'<tbody>{rows}</tbody></table></details>')
    if sid == "where-it-lives":
        return '<dl class="pairs">' + "".join(
            f'<dt>{esc(a["kind"].replace("_", " "))}</dt><dd>' + (
                f'<a href="{esc(a["value"])}" rel="noopener noreferrer" target="_blank">{esc(a["value"])}</a>'
                if str(a["value"]).startswith("https://") else f'<span class="mono">{esc(a["value"])}</span>') + "</dd>"
            for a in items) + "</dl>"
    if sid == "repo-map":
        out = []
        for m in items:
            entries = [{"path": f"{m['repo']}/", "role": f"{m['files']} files at {m['commit'][:8]}"}]
            entries += [{"path": f"{m['repo']}/{f['path']}", "role": f"{f['files']} file{'s' if f['files'] != 1 else ''}"
                         + (f" · {', '.join(f['languages'])}" if f["languages"] else "")} for f in m["folders"]]
            d = {"id": f"map-{m['repo']}", "type": "tree", "title": f"{m['repo']} at {m['commit'][:8]}", "entries": entries}
            out.append(f'<div class="dg-scroll">{diagrams.render(d, pid="map-" + m["repo"])["svg"]}</div>')
        return "".join(out)
    lines = []
    for i in items:
        page = i.get("page")
        name = i.get("title") or i.get("person") or i.get("project") or page
        initial = (str(name)[:1] or "?").upper()
        link = f'<a href="{esc(page)}.html">{esc(name)}</a>' if page in known else esc(name)
        counts = ", ".join(f"{i[k]} {k if i[k] != 1 else k[:-1]}" for k in ("claims", "commits") if i.get(k))
        lines.append(f'<li class="row"><span class="row-main"><span class="avatar" aria-hidden="true">{esc(initial)}</span>'
                     f'{link}</span><span class="row-meta quiet">{esc(counts)}</span></li>')
    return '<ul class="rows">' + "".join(lines) + "</ul>"


def page_html(page, catalog, known, github, images=None):
    root = "../"
    stale = page.get("stale", {})
    blocks = [b for s in page.get("content", []) if s["source"] == "compiled" for b in s["blocks"]]
    counts = Counter(b["label"] for b in blocks)
    meta = [f'<span>Version <span class="num">{esc(page["version"])}</span></span>']
    if page.get("updated_at"):
        meta.append(f'<span>Updated <time datetime="{esc(page["updated_at"])}">{short_date(page["updated_at"])}</time>'
                    f' by {"you" if page.get("written_by") == "me" else "Claude"}</span>')
    if page.get("built_from"):
        meta.append("<span>Built from " + ", ".join(f'<span class="mono">{esc(b["repo"])}@{esc(b["commit"][:8])}</span>'
                                                    for b in page["built_from"]) + "</span>")
    notices = []
    if stale.get("is_stale"):
        notices.append(f'<div class="notice warn" role="note">{icon("alert")}<div><strong>Stale.</strong> '
                       + " ".join(esc(w) for w in stale.get("why", [])) + "</div></div>")
    if page.get("version", 0) == 0:
        notices.append(f'<div class="notice" role="note">{icon("alert")}<div><strong>Not written yet.</strong> '
                       "The compile run writes it after the evening run, or ask Claude to.</div></div>")
    sections = []
    for s in page.get("content", []):
        body = compiled_html(s, known, github, images or {}) if s["source"] == "compiled" else generated_html(s, known)
        summary = (f'<p class="section-summary">{esc(s.get("summary"))}</p>'
                   if s["source"] == "generated" and s.get("summary") and s.get("items") else "")
        sections.append(f'<section id="{esc(s["id"])}" class="section" data-source="{esc(s["source"])}">'
                        f'<div class="section-head"><h2>{esc(s["heading"])}</h2>'
                        + ('<span class="source-tag">from the store</span>' if s["source"] == "generated" else "")
                        + f'</div>{summary}{body}</section>')
    toc = "".join(f'<li><a href="#{esc(s["id"])}">{esc(s["heading"])}</a></li>' for s in page.get("content", []))
    links = [l for l in page.get("links", []) if l["page"] in known]
    back = [l for l in page.get("linked_from", []) if l["page"] in known]
    def link_list(entries, direction):
        return "".join(f'<li>{icon(direction)}<a href="{esc(l["page"])}.html">{esc(l.get("title") or l["page"])}</a>'
                       f'<span class="quiet">{esc(KIND_ONE.get(l["type"], l["type"]))}</span></li>' for l in entries)
    rail = [f'<section class="panel rail-panel"><h3>On this page</h3><ul class="toc">{toc}</ul></section>' if toc else "",
            f'<section class="panel rail-panel"><h3>Evidence</h3>{label_bar(counts)}</section>' if blocks else "",
            (f'<section class="panel rail-panel notes"><h3>{icon("note")}My notes</h3><p>{esc(page["my_notes"]["text"])}</p>'
             f'<p class="quiet">Yours, so Claude reads them as verified.</p></section>') if page.get("my_notes") else "",
            '<section class="panel rail-panel graph-box"><h3>Around this page</h3><svg id="graph" class="graph local" '
            'role="img" aria-label="Pages linked to this one"></svg></section>',
            (f'<section class="panel rail-panel"><h3>Linked pages</h3><ul class="links">{link_list(links, "out")}'
             f'{link_list(back, "in")}</ul></section>') if links or back else ""]
    return "".join([
        head(f"{page['title']} · Work wiki", root),
        f'<body data-root="{root}" data-page="{esc(page["page"])}">\n<div class="app">\n',
        sidebar(catalog, root, page["page"]),
        f'<main class="main" id="main">\n<nav class="crumbs" aria-label="Breadcrumb"><a href="{root}index.html">Overview</a>'
        f'<span aria-hidden="true">/</span><span>{KIND_NAMES.get(page["kind"], "")}</span></nav>\n'
        f'<article data-page="{esc(page["page"])}" data-kind="{esc(page["kind"])}">\n'
        f'<header class="page-head"><p class="eyebrow">{KIND_ONE.get(page["kind"], "")} page</p>'
        f'<h1>{esc(page["title"])}</h1>'
        + (f'<p class="lede">{esc(page["summary"])}</p>' if page.get("summary") else "")
        + f'<p class="meta">{"".join(meta)}</p></header>\n' + "".join(notices) +
        '<div class="page-grid">\n<div class="panel article-panel">' + "".join(sections) + "</div>\n"
        f'<aside class="rail">{"".join(rail)}</aside>\n</div>\n</article>\n</main>\n</div>\n'
        f'<script type="application/json" id="pwi-page">{data(page)}</script>\n' + scripts(root) + "</body>\n</html>\n"])


def index_html(catalog, pages):
    root = ""
    written = [e for e in catalog if e["compiled"]]
    stale = [e for e in catalog if e["stale"]]
    counts = Counter(b["label"] for p in pages.values() for s in p.get("content", []) if s["source"] == "compiled"
                     for b in s["blocks"])
    metrics = [("Pages", len(catalog), f"{sum(e['kind'] == 'project' for e in catalog)} projects"),
               ("Written", len(written), f"{len(catalog) - len(written)} to write"),
               ("Stale", len(stale), "behind their repositories or claims"),
               ("Statements", sum(counts.values()), f"{counts['verified'] + counts['repo']} verified or from a repository")]
    attention = [f'<li class="row"><span class="row-main"><a href="pages/{esc(e["page"])}.html">{esc(e["title"])}</a></span>'
                 f'<span class="row-meta"><span class="state stale">stale</span></span></li>' for e in stale]
    attention += [f'<li class="row"><span class="row-main"><a href="pages/{esc(e["page"])}.html">{esc(e["title"])}</a></span>'
                  f'<span class="row-meta"><span class="state unwritten">not written</span></span></li>'
                  for e in catalog if not e["compiled"] and e["kind"] == "project"][:8]
    recent = sorted(written, key=lambda e: e.get("updated_at") or "", reverse=True)[:6]
    recent_rows = "".join(f'<li class="row"><span class="row-main"><a href="pages/{esc(e["page"])}.html">{esc(e["title"])}</a>'
                          f'<span class="quiet">{esc(e.get("summary") or "")}</span></span><span class="row-meta">'
                          f'<span class="num">v{e["version"]}</span><time class="date" datetime="{esc(e.get("updated_at"))}">'
                          f'{short_date(e.get("updated_at"))}</time></span></li>' for e in recent)
    catalog_groups = "".join(
        f'<section class="catalog-group" data-kind="{k}"><h3>{KIND_NAMES[k]} <span class="count">'
        f'{sum(e["kind"] == k for e in catalog)}</span></h3><ul class="rows">' + "".join(
            f'<li class="row" data-kind="{k}"><span class="row-main"><a href="pages/{esc(e["page"])}.html">{esc(e["title"])}</a>'
            f'<span class="quiet">{esc(e.get("summary") or ("Not written yet" if not e["compiled"] else ""))}</span></span>'
            f'<span class="row-meta">' + ('<span class="state stale">stale</span>' if e["stale"] else "")
            + (f'<span class="num">v{e["version"]}</span>' if e["compiled"] else "") + "</span></li>"
            for e in catalog if e["kind"] == k) + "</ul></section>" for k in KINDS if any(e["kind"] == k for e in catalog))
    segmented = "".join(f'<button type="button" class="segment" data-kind="{k}" aria-pressed="true">{KIND_NAMES[k]}</button>'
                        for k in KINDS)
    return "".join([
        head("Work wiki", root), f'<body data-root="{root}" data-page="">\n<div class="app">\n', sidebar(catalog, root),
        '<main class="main" id="main">\n<header class="page-head"><p class="eyebrow">Knowledge wiki</p><h1>Overview</h1>'
        '<p class="lede">Every page Claude may see, as it sees it: what each project is, how it works and why, with every '
        'statement cited.</p></header>\n<div class="bento">\n',
        '<section class="panel metrics" aria-label="The wiki in numbers">' + "".join(
            f'<div class="metric"><p class="metric-label">{name}</p><p class="metric-value num">{value}</p>'
            f'<p class="quiet">{esc(note)}</p></div>' for name, value, note in metrics)
        + f'<div class="metric wide"><p class="metric-label">Evidence</p>{label_bar(counts, wide=True)}</div></section>\n',
        '<section class="panel graph-panel"><div class="panel-head"><h2>Map of the wiki</h2>'
        f'<div class="segmented" role="group" aria-label="Show page kinds">{segmented}</div></div>'
        '<svg id="graph" class="graph full" role="img" aria-label="Every page and the links between them"></svg>'
        '<ul class="legend">' + "".join(f'<li><span class="kind-dot {k}" aria-hidden="true"></span>{KIND_NAMES[k]}</li>'
                                        for k in KINDS) + '<li><span class="kind-dot ring" aria-hidden="true"></span>Stale</li>'
        '<li><span class="kind-dot faint" aria-hidden="true"></span>Not written</li></ul></section>\n',
        f'<section class="panel attention-panel"><div class="panel-head"><h2>{icon("alert")}Needs attention</h2></div>'
        + (f'<ul class="rows">{"".join(attention)}</ul>' if attention else
           '<p class="empty">Nothing: every written page is current.</p>') + "</section>\n",
        '<section class="panel recent-panel"><div class="panel-head"><h2>Recently updated</h2></div>'
        + (f'<ul class="rows">{recent_rows}</ul>' if recent else '<p class="empty">No page is written yet.</p>') + "</section>\n",
        f'<section class="panel catalog">{catalog_groups}</section>\n',
        "</div>\n</main>\n</div>\n", scripts(root), "</body>\n</html>\n"])
