"""The static wiki in the formats agents read best, next to its HTML (wiki_site.py builds them all).

    llms.txt            where to start: what the wiki is, its files, and every page with a one-line summary
    pages/<id>.md       a page as Markdown: each statement with its label as a word and its sources, the diagrams
                        as images (PNG, else SVG) with a text version, and the generated sections as lists and tables
    statements.jsonl    one line per statement, diagram and image on every page, so `grep` finds one without
                        opening any page: its page, section, label, text and sources
    graph.json          the pages and the links between them

The same data as the HTML, from the same pages wiki.py returns, so labels, hiding and generated sections match.
Text from the store is Markdown already (statements' small subset); anything else that could be read as markup
is escaped with a backslash, so no viewer turns it into HTML, and the JSON has no '<', '>' or '&'.
"""

import re

import diagrams
from validate import MARKDOWN_LINK, WIKI_LINK
from wiki_render import data

KINDS = ("project", "topic", "person")
KIND_NAMES = {"project": "Projects", "topic": "Topics", "person": "People"}
KIND_ONE = {"project": "Project", "topic": "Topic", "person": "Person"}
LABEL_HELP = ("verified: confirmed by me, or my own notes; repo: read from a repository at a commit; "
              "unconfirmed: proposed by Claude, not yet confirmed; disputed: cites a claim I disputed")


def md(text):
    """Text that isn't Markdown (titles, captions, names, values) as literal Markdown text."""
    return re.sub(r"([\\`*\[\]<])", r"\\\1", " ".join(str(text if text is not None else "").split()))


def statement_md(text, known):
    """A statement's own Markdown, kept, with [[page]] links pointing at the page's .md file and raw HTML disarmed."""
    out = []
    for part in re.split(r"(`[^`]*`)", text):
        if len(part) >= 2 and part.startswith("`") and part.endswith("`"):
            out.append(part)
            continue
        pieces, last = [], 0
        for m in re.finditer(f"{WIKI_LINK.pattern}|{MARKDOWN_LINK.pattern}", part):
            pieces.append(part[last:m.start()].replace("<", "\\<"))
            if m.group(0).startswith("[["):
                target, label = m.group(1), m.group(2) or m.group(1)
                pieces.append(f"[{md(label)}]({target}.md)" if target in known else md(label))
            else:
                url = m.group(5)
                pieces.append(m.group(0).replace("<", "\\<") if m.group(3) or not url.startswith("https://")
                              else f"[{m.group(4).replace('<', '\\<')}](<{url.replace('>', '%3E')}>)")
            last = m.end()
        pieces.append(part[last:].replace("<", "\\<"))
        out.append("".join(pieces))
    return " ".join("".join(out).split())


def cite_md(cite):
    if "claim_id" in cite:
        return f"claim `{cite['claim_id']}`" + (f" [{cite['label']}]" if cite.get("label") else "")
    if "event_id" in cite:
        return f"event `{cite['event_id']}`"
    if "commit" in cite:
        return f"`{cite['repo']}@{cite['commit'][:8]}" + (f":{cite['path']}" if cite.get("path") else "") + "`"
    if "page" in cite:
        return f"page [{md(cite['page'])}]({cite['page']}.md)"
    return ""


def sources_md(cites):
    return "(sources: " + "; ".join(cite_md(c) for c in cites) + ")" if cites else ""


def figure_md(b, files):
    """A diagram or an image: the picture, then what it is, its label and sources."""
    if b["kind"] == "diagram":
        d = b["diagram"]
        drawn = files.get(b["id"], {})
        picture = drawn.get("png") or drawn.get("svg")
        lines = [f"**Diagram ({d['type']}): {md(d['title'])}.**" + (f" {md(d['caption'])}" if d.get("caption") else "")
                 + f" [{b['label']}] {sources_md(b['cites'])}"]
        if picture:
            lines.insert(0, f"![{md(d['title'])}](../{picture})")
            lines.append("Files: " + " · ".join(f"[{kind.upper()}](../{drawn[kind]})" for kind in ("svg", "png")
                                                  if drawn.get(kind)))
        lines.append("As text:")
        lines += [f"- {md(line)}" for line in diagrams.as_text(d)]
        return "\n".join(lines)
    name = files.get(b["id"], {}).get("image")
    caption = b.get("caption") or b["image"]["path"]
    picture = f"![{md(caption)}](../images/{name})" if name else f"({md(b['image']['path'])} couldn't be copied.)"
    return f"{picture}\n**Image:** {md(caption)} [{b['label']}] {sources_md(b['cites'])}"


def claim_md(c):
    when = (c.get("due_at") or c.get("about_day") or "")[:10]
    extra = []
    if c.get("direction"):
        mine = c["direction"] == "mine"
        extra.append(("I owe " if mine else "owed to me by ") + ((c.get("counterparty") if mine else c.get("owner")) or "someone"))
    if c.get("overdue"):
        extra.append("overdue")
    return (f"- {when + ' ' if when else ''}{md(c.get('text'))} [{c.get('label')}]"
            + (f" ({md(', '.join(extra))})" if extra else "") + f" claim `{c.get('claim_id')}`")


def generated_md(section, known):
    items, sid = section.get("items", []), section["id"]
    if not items:
        return md(section.get("summary") or "")
    if sid in ("decisions", "commitments", "open-work"):
        return "\n".join(claim_md(c) for c in sorted(items, key=lambda c: c.get("about_day") or "", reverse=sid == "decisions"))
    if sid == "activity":
        return "| Week | Commits | Focus minutes |\n| --- | --- | --- |\n" + "\n".join(
            f"| {w['week']} | {w['commits']} | {w['focus_minutes']} |" for w in sorted(items, key=lambda w: w["week"], reverse=True))
    if sid == "where-it-lives":
        return "\n".join(f"- {md(a['kind'])}: `{str(a['value']).replace('`', '')}`" for a in items)
    if sid == "repo-map":
        return "\n".join(f"- `{m['repo']}` at `{m['commit'][:8]}`, {m['files']} files: "
                         + ", ".join(f"`{f['path']}` ({f['files']})" for f in m["folders"]) for m in items)
    lines = []
    for i in items:
        page = i.get("page")
        name = md(i.get("title") or i.get("person") or i.get("project") or page)
        counts = ", ".join(f"{i[k]} {k if i[k] != 1 else k[:-1]}" for k in ("claims", "commits") if i.get(k))
        lines.append(f"- {f'[{name}]({page}.md)' if page in known else name}" + (f" ({counts})" if counts else ""))
    return "\n".join(lines)


def page_md(page, known, files):
    meta = [f"{KIND_ONE.get(page['kind'], '')} page", f"version {page['version']}"]
    if page.get("updated_at"):
        meta.append(f"updated {page['updated_at'][:10]} by {'me' if page.get('written_by') == 'me' else 'Claude'}")
    if page.get("built_from"):
        meta.append("built from " + ", ".join(f"`{b['repo']}@{b['commit'][:8]}`" for b in page["built_from"]))
    parts = [f"# {md(page['title'])}"]
    if page.get("summary"):
        parts.append(f"> {md(page['summary'])}")
    parts.append(" · ".join(meta) + f"  \nPage id `{page['page']}`. Labels: {LABEL_HELP}.")
    if page.get("key_terms"):
        parts.append("Key terms: " + ", ".join(md(t) for t in page["key_terms"]))
    if page.get("stale", {}).get("is_stale"):
        parts.append("**Stale.** " + " ".join(md(w) for w in page["stale"].get("why", [])))
    if page.get("version", 0) == 0:
        parts.append("Not written yet.")
    if page.get("my_notes"):
        parts.append(f"**My notes** [verified]: {md(page['my_notes']['text'])}")
    for s in page.get("content", []):
        parts.append(f"## {md(s['heading'])}")
        if s["source"] == "generated":
            if s.get("items") and s.get("summary"):
                parts.append(f"*{md(s['summary'])}*")
            parts.append(generated_md(s, known))
            continue
        run = []
        for b in s["blocks"]:
            if b.get("kind") in ("diagram", "image"):
                if run:
                    parts.append("\n".join(run))
                    run = []
                parts.append(figure_md(b, files))
                continue
            line = f"{statement_md(b['text'], known)} [{b['label']}] {sources_md(b['cites'])}"
            if b["style"] == "bullet":
                run.append(f"- {line}")
            else:
                if run:
                    parts.append("\n".join(run))
                    run = []
                parts.append(line)
        if run:
            parts.append("\n".join(run))
    links = [l for l in page.get("links", []) if l["page"] in known]
    back = [l for l in page.get("linked_from", []) if l["page"] in known]
    if links or back:
        parts.append("## Linked pages")
        parts.append("\n".join(f"- {arrow} [{md(l.get('title') or l['page'])}]({l['page']}.md) ({KIND_ONE.get(l['type'], l['type'])})"
                               for arrow, entries in (("links to", links), ("linked from", back)) for l in entries))
    return "\n\n".join(p for p in parts if p) + "\n"


def statements_jsonl(pages, files):
    """One JSON object per line: every statement, diagram and image, with where it is and what it rests on."""
    lines = []
    for page_id, page in pages.items():
        for s in page.get("content", []):
            for b in s.get("blocks", []):
                row = {"page": page_id, "page_title": page["title"], "section": s["id"], "heading": s["heading"],
                       "id": b["id"], "kind": b.get("kind", "statement"), "label": b["label"]}
                if b.get("kind") == "diagram":
                    d = b["diagram"]
                    row.update(text=f"{d['title']}. {d.get('caption') or ''}".strip(), diagram_type=d["type"],
                               as_text=diagrams.as_text(d), **{k: v for k, v in files.get(b["id"], {}).items()})
                elif b.get("kind") == "image":
                    row.update(text=b.get("caption") or b["image"]["path"], image=b["image"],
                               **({"file": f"images/{files[b['id']]['image']}"} if files.get(b["id"], {}).get("image") else {}))
                else:
                    row["text"] = b["text"]
                row.update(cites=b["cites"], html=f"pages/{page_id}.html#{b['id']}", md=f"pages/{page_id}.md")
                lines.append(data(row))
    return "\n".join(lines) + ("\n" if lines else "")


def llms_txt(catalog, built_at):
    """The entry point, as llms.txt (llmstxt.org): what's here and every page, linking to its Markdown."""
    parts = ["# Work wiki",
             "> What I know about my work, one page per project, person and topic, written by Claude from my claims, "
             "events and repositories, and kept up to date. Every statement carries its label and its sources.",
             f"Built {built_at[:16].replace('T', ' ')} UTC. {len(catalog)} pages. Labels: {LABEL_HELP}.",
             "Each page is here four ways: `pages/<id>.md` (Markdown, the easiest to read), `pages/<id>.json` (its data), "
             "`pages/<id>.html` (plain HTML with the diagrams drawn inline) and, line by line, in `statements.jsonl`. "
             "To find something without opening every page, search `statements.jsonl` (one statement, diagram or image "
             "per line, with its page, section, label and sources) or `catalog.json`. Diagrams are in `diagrams/` as SVG "
             "and PNG; documentation images in `images/`. `graph.json` has the links between pages. With the layer's MCP "
             "tools, use search and get_wiki_page instead: they're always current."]
    for kind in KINDS:
        entries = [e for e in catalog if e["kind"] == kind]
        if entries:
            parts.append(f"## {KIND_NAMES[kind]}\n\n" + "\n".join(
                f"- [{md(e['title'])}](pages/{e['page']}.md): "
                + (md(e["summary"]) if e.get("summary") else "not written yet")
                + (" (stale)" if e["stale"] else "") for e in entries))
    return "\n\n".join(parts) + "\n"
