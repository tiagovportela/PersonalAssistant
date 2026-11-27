"""What the wiki's two faces draw the same way: the static site for agents (wiki_site_html.py) and the app's Wiki
section (wiki_admin.py, rendered by the frontend). Statements' text as HTML, diagrams and charts as SVG.

Everything from the store is escaped here, and statements' small Markdown subset (bold, italics, code, [[page]]
links, https links) becomes tags here and nowhere else. The SVG uses classes only: each face's stylesheet gives it
its look, and neither face's CSP allows inline styles.
"""

import html
import json
import re

import diagrams
from validate import MARKDOWN_LINK, WIKI_LINK

LABELS = ("verified", "repo", "unconfirmed", "disputed")


def esc(text):
    return html.escape(str(text if text is not None else ""), quote=True)


def data(value, indent=None):
    """JSON with no '<', '>' or '&', so nothing in it can close a tag or read as markup, wherever it's opened."""
    text = json.dumps(value, ensure_ascii=False, indent=indent)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def inline(text, known, href):
    """A statement's text as HTML: escaped first, then only the allowed marks become tags. href(page id) is where a
    [[page]] link goes on this face; a link to a page that doesn't exist stays text."""
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
                pieces.append(f'<a class="wl" href="{esc(href(target))}">{esc(label)}</a>' if target in known
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


def diagram_svg(block):
    """A diagram block drawn as SVG, with an id prefix unique on its page."""
    return diagrams.render(block["diagram"], pid=f"dg-{block['id']}")["svg"]


def repo_map_svgs(items):
    """The generated repository map: each repository's top folders as a tree diagram."""
    out = []
    for m in items:
        entries = [{"path": f"{m['repo']}/", "role": f"{m['files']} files at {m['commit'][:8]}"}]
        entries += [{"path": f"{m['repo']}/{f['path']}", "role": f"{f['files']} file{'s' if f['files'] != 1 else ''}"
                     + (f" · {', '.join(f['languages'])}" if f["languages"] else "")} for f in m["folders"]]
        d = {"id": f"map-{m['repo']}", "type": "tree", "title": f"{m['repo']} at {m['commit'][:8]}", "entries": entries}
        out.append(diagrams.render(d, pid="map-" + m["repo"])["svg"])
    return out


def activity_svg(weeks):
    """Commits per week as rounded bars on a quiet grid, with each week's numbers in its tooltip."""
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
                    f'<text class="axis week" x="{x + 10}" y="{base + 16}">{esc(w["week"][-3:])}</text></g>')
    return (f'<svg class="chart" viewBox="0 0 {width} {base + 24}" width="{width}" height="{base + 24}" role="img" '
            f'aria-label="Commits per week">{grid}{"".join(bars)}</svg>')
