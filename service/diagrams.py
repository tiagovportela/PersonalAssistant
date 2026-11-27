"""Diagrams for the wiki (docs/knowledge_wiki.md, step 3b): agents describe them, this module draws them.

An agent sends a typed description (nodes and edges, participants and messages, lanes and steps...), never
SVG. Here it's checked, laid out and drawn as SVG by code, with every label escaped and classes only (the
site's CSP allows no inline styles). Seven types:

    journey       a user's path through a UI: lanes (screens or actors), steps in order, branches, pain points
    flow          a process or decision logic: steps, decisions, start and end, optional groups
    sequence      messages between participants over time
    architecture  components and their boundaries: services, stores, UIs, queues, nested groups
    state         a lifecycle: states and the transitions between them
    tree          folders and what each is for
    timeline      dated events, each citing its evidence

Agents can't see the layout, so render() also returns warnings in words (crossings, labels cut, a group with one
node, a node with no edges), and preview() draws a PNG with rsvg-convert when it's installed, for agents that
read images. Standard library only.
"""

import base64
import html
import math
import re
import shutil
import subprocess

TYPES = ["journey", "flow", "sequence", "architecture", "state", "tree", "timeline"]
NODE_KINDS = {
    "flow": ["step", "decision", "start", "end", "data", "external"],
    "state": ["state", "start", "end"],
    "architecture": ["service", "store", "ui", "queue", "external", "person"],
    "sequence": ["service", "store", "ui", "queue", "external", "person"],
}
EDGE_KINDS, MESSAGE_KINDS = ["sync", "async", "data"], ["call", "reply", "async"]
GROUP_KINDS = ["machine", "cloud", "boundary", "folder"]
ITEM_KINDS = ["decision", "release", "milestone", "change", "plan"]
FIELDS = {  # which lists each type takes, and which it must have
    "journey": ({"lanes", "steps"}, {"lanes", "steps"}),
    "flow": ({"nodes", "edges", "groups"}, {"nodes"}),
    "state": ({"nodes", "edges"}, {"nodes"}),
    "architecture": ({"nodes", "edges", "groups"}, {"nodes"}),
    "sequence": ({"participants", "messages"}, {"participants", "messages"}),
    "tree": ({"entries"}, {"entries"}),
    "timeline": ({"items"}, {"items"}),
}
LISTS = ["nodes", "edges", "groups", "participants", "messages", "lanes", "steps", "entries", "items"]
MAX_ITEMS, MAX_LINKS, MAX_GROUPS, MAX_DEPTH = 30, 60, 12, 3
LABEL_CHARS, TITLE_CHARS, CAPTION_CHARS = 60, 80, 200
ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
HTML_TAG = re.compile(r"<[A-Za-z/!?]")
DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
WRAP, LINES = 26, 2  # label characters per line, and lines per box


# Checks ----------------------------------------------------------------------------------

def check(d, where):
    """Problems with a diagram's description, as a list of sentences for Claude to fix."""
    problems = []
    kind = d.get("type")
    if kind not in TYPES:
        return [f"{where}.type must be one of: {', '.join(TYPES)}."]
    allowed, needed = FIELDS[kind]
    if not ID.match(d.get("id", "")):
        problems.append(f"{where}.id is a short id: lowercase letters, digits, - and _.")
    for field, limit in (("title", TITLE_CHARS), ("caption", CAPTION_CHARS)):
        text(d.get(field, ""), limit, f"{where}.{field}", problems, required=field == "title")
    for field in LISTS:
        if field in d and field not in allowed:
            problems.append(f"{where}.{field} isn't used by {kind} diagrams, which take {', '.join(sorted(allowed))}.")
    for field in sorted(needed):
        if not d.get(field):
            problems.append(f"{where}.{field} is required for {kind} diagrams.")
    if problems:
        return problems
    items = d.get("nodes") or d.get("participants") or d.get("steps") or d.get("entries") or d.get("items") or []
    links = d.get("edges") or d.get("messages") or []
    if len(items) > MAX_ITEMS or len(links) > MAX_LINKS or len(d.get("groups", [])) > MAX_GROUPS:
        problems.append(f"{where} is too big: at most {MAX_ITEMS} nodes or steps, {MAX_LINKS} edges or messages and "
                        f"{MAX_GROUPS} groups. Split it into two diagrams.")
    ids = set()
    for field in ("nodes", "participants", "steps", "lanes", "groups"):
        for i, item in enumerate(d.get(field, [])):
            spot = f"{where}.{field}[{i}]"
            if not ID.match(item.get("id", "")):
                problems.append(f"{spot}.id is required: a short id of lowercase letters, digits, - and _.")
            elif item["id"] in ids:
                problems.append(f"{spot}.id '{item['id']}' is used twice in this diagram.")
            ids.add(item.get("id"))
            text(item.get("label", ""), LABEL_CHARS, f"{spot}.label", problems, required=True)
            if field in ("nodes", "participants") and kind in NODE_KINDS and item.get("kind", NODE_KINDS[kind][0]) not in NODE_KINDS[kind]:
                problems.append(f"{spot}.kind must be one of: {', '.join(NODE_KINDS[kind])}.")
            if field == "groups" and item.get("kind", "boundary") not in GROUP_KINDS:
                problems.append(f"{spot}.kind must be one of: {', '.join(GROUP_KINDS)}.")
            for extra in ("result", "pain"):
                text(item.get(extra, ""), LABEL_CHARS, f"{spot}.{extra}", problems)
    groups = {g["id"]: g for g in d.get("groups", [])}
    for i, n in enumerate(d.get("nodes", [])):
        if n.get("group") and n["group"] not in groups:
            problems.append(f"{where}.nodes[{i}].group '{n['group']}' isn't one of the diagram's groups.")
    for gid, g in groups.items():
        depth, seen, parent = 1, {gid}, g.get("parent")
        while parent:
            if parent not in groups or parent in seen:
                problems.append(f"{where}.groups: '{gid}' has a parent that's missing or loops back.")
                break
            depth, parent = depth + 1, groups[parent].get("parent")
            seen.add(parent)
        if depth > MAX_DEPTH:
            problems.append(f"{where}.groups: '{gid}' is nested {depth} deep; at most {MAX_DEPTH}.")
    targets = {i.get("id") for f in ("nodes", "participants", "steps") for i in d.get(f, [])}
    for field in ("edges", "messages"):
        for i, e in enumerate(d.get(field, [])):
            spot = f"{where}.{field}[{i}]"
            for end in ("from", "to"):
                if e.get(end) not in targets:
                    problems.append(f"{spot}.{end} '{e.get(end)}' isn't a {'participant' if field == 'messages' else 'node'} id.")
            text(e.get("label", ""), LABEL_CHARS, f"{spot}.label", problems, required=field == "messages")
            text(e.get("note", ""), LABEL_CHARS, f"{spot}.note", problems)
            kinds = MESSAGE_KINDS if field == "messages" else EDGE_KINDS
            if e.get("kind", kinds[0]) not in kinds:
                problems.append(f"{spot}.kind must be one of: {', '.join(kinds)}.")
    lanes = {l.get("id") for l in d.get("lanes", [])}
    for i, s in enumerate(d.get("steps", [])):
        if s.get("lane") not in lanes:
            problems.append(f"{where}.steps[{i}].lane '{s.get('lane')}' isn't one of the lanes.")
        for n in s.get("next", []):
            if n not in targets:
                problems.append(f"{where}.steps[{i}].next '{n}' isn't a step id.")
    for i, e in enumerate(d.get("entries", [])):
        path = e.get("path", "")
        if not path or path.startswith(("/", "-")) or ".." in path.split("/") or HTML_TAG.search(path) or len(path) > 120:
            problems.append(f"{where}.entries[{i}].path is a path inside the repository, e.g. service/wiki.py.")
        text(e.get("role", ""), LABEL_CHARS, f"{where}.entries[{i}].role", problems)
    for i, item in enumerate(d.get("items", [])):
        spot = f"{where}.items[{i}]"
        if not DATE.match(item.get("date", "")):
            problems.append(f"{spot}.date is YYYY-MM-DD or YYYY-MM.")
        text(item.get("label", ""), LABEL_CHARS, f"{spot}.label", problems, required=True)
        if item.get("kind", "change") not in ITEM_KINDS:
            problems.append(f"{spot}.kind must be one of: {', '.join(ITEM_KINDS)}.")
        if not item.get("cites"):
            problems.append(f"{spot}.cites is required: a date is a fact, so each timeline item cites its evidence.")
    return problems


def text(value, limit, where, problems, required=False):
    if required and not str(value).strip():
        problems.append(f"{where} is required.")
    elif len(value) > limit or "\n" in value or HTML_TAG.search(value):
        problems.append(f"{where} is one line of plain text, at most {limit} characters.")


def element_cites(d):
    """The citations on a diagram's elements, which count for its label and hiding like its own."""
    return [c for field in ("nodes", "items") for item in d.get(field, []) for c in item.get("cites", [])]


def page_links(d):
    return sorted({n["page"] for f in ("nodes", "participants") for n in d.get(f, []) if n.get("page")})


def plain_text(d):
    """A diagram's words, for search and for the 'Diagram as text' panel's summary."""
    words = [d.get("title", ""), d.get("caption", "")]
    for field in LISTS:
        for item in d.get(field, []):
            words += [str(item.get(k, "")) for k in ("label", "result", "pain", "note", "path", "role") if item.get(k)]
    return " · ".join(w for w in words if w)


def as_text(d):
    """The diagram as lines of text, for readers that don't see pictures."""
    name = {i.get("id"): i.get("label") or i.get("id")
            for f in ("nodes", "participants", "steps", "lanes", "groups") for i in d.get(f, [])}
    lines = []
    for f in ("nodes", "participants"):
        lines += [f"{n['label']} ({n.get('kind', NODE_KINDS.get(d['type'], ['step'])[0])})"
                  + (f", in {name.get(n['group'])}" if n.get("group") else "") for n in d.get(f, [])]
    lines += [f"{name.get(e['from'])} → {name.get(e['to'])}" + (f": {e['label']}" if e.get("label") else "")
              for f in ("edges", "messages") for e in d.get(f, [])]
    for s in d.get("steps", []):
        lines.append(f"{name.get(s['lane'])}: {s['label']}" + (f" → {s['result']}" if s.get("result") else "")
                     + (f" (pain: {s['pain']})" if s.get("pain") else ""))
    lines += [f"{e['path']}" + (f": {e['role']}" if e.get("role") else "") for e in d.get("entries", [])]
    lines += [f"{i['date']}: {i['label']}" for i in d.get("items", [])]
    return lines


# Layout and drawing -------------------------------------------------------------------------

def esc(value):
    return html.escape(str(value), quote=True)


def wrap(label, warnings, width=WRAP, lines=LINES):
    words, out, line = str(label).split(), [], ""
    for w in words:
        if line and len(line) + 1 + len(w) > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    out.append(line)
    out = [l if len(l) <= width else l[:width - 1] + "…" for l in out]
    if len(out) > lines:
        warnings.append(f"label cut: '{label}'")
        out = out[:lines - 1] + [out[lines - 1][:width - 1] + "…"]
    return out


def box_size(lines):
    return max(90, 7 * max(len(l) for l in lines) + 26), 18 * len(lines) + 18


def label_svg(x, y, lines, cls="dg-label"):
    top = y - 9 * (len(lines) - 1)
    return (f'<text class="{cls}" x="{x:.1f}" y="{top + 4:.1f}">'
            + "".join(f'<tspan x="{x:.1f}" dy="{0 if i == 0 else 18}">{esc(l)}</tspan>' for i, l in enumerate(lines))
            + "</text>")


def shape(kind, x, y, w, h):
    """A node's outline by its kind: the same shape for the same kind in every diagram."""
    if kind == "decision":
        return f'<polygon points="{x:.1f},{y - h / 2 - 6:.1f} {x + w / 2 + 8:.1f},{y:.1f} {x:.1f},{y + h / 2 + 6:.1f} {x - w / 2 - 8:.1f},{y:.1f}"/>'
    if kind in ("start", "end", "person"):
        return f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{h / 2:.1f}"/>'
    if kind == "store":
        return (f'<path d="M{x - w / 2:.1f},{y - h / 2 + 6:.1f} a{w / 2:.1f},6 0 0 0 {w:.1f},0 v{h - 12:.1f} '
                f'a{w / 2:.1f},6 0 0 1 {-w:.1f},0 z M{x - w / 2:.1f},{y - h / 2 + 6:.1f} a{w / 2:.1f},6 0 0 1 {w:.1f},0"/>')
    if kind in ("queue", "data"):
        return f'<polygon points="{x - w / 2 + 10:.1f},{y - h / 2:.1f} {x + w / 2 + 10:.1f},{y - h / 2:.1f} {x + w / 2 - 10:.1f},{y + h / 2:.1f} {x - w / 2 - 10:.1f},{y + h / 2:.1f}"/>'
    return f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w:.1f}" height="{h:.1f}" rx="6"/>'


def clip(x1, y1, x2, y2, w, h):
    """Where the segment from a box's centre towards (x2, y2) leaves the box."""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return x1, y1
    scale = min((w / 2) / abs(dx) if dx else math.inf, (h / 2) / abs(dy) if dy else math.inf)
    return x1 + dx * scale, y1 + dy * scale


def crosses(a, b):
    (x1, y1, x2, y2), (x3, y3, x4, y4) = a, b
    def side(px, py, qx, qy, rx, ry):
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)
    d1, d2 = side(x3, y3, x4, y4, x1, y1), side(x3, y3, x4, y4, x2, y2)
    d3, d4 = side(x1, y1, x2, y2, x3, y3), side(x1, y1, x2, y2, x4, y4)
    return d1 * d2 < 0 and d3 * d4 < 0


def place(order, edges, size):
    """Layers by longest path and barycentre sweeps for one set of nodes: {id: (x, y)}, width, height."""
    inside = set(order)
    edges = [e for e in edges if e["from"] in inside and e["to"] in inside]
    out = {i: [e["to"] for e in edges if e["from"] == i and e["to"] != i] for i in order}
    seen, done, forward = set(), set(), []
    def visit(v):  # depth-first: an edge back to a node on the current path closes a cycle and doesn't set layers
        seen.add(v)
        for w in out[v]:
            if w not in seen:
                forward.append((v, w))
                visit(w)
            elif w in done:
                forward.append((v, w))
        done.add(v)
    for v in order:
        if v not in seen:
            visit(v)
    layer = {v: 0 for v in order}
    for _ in order:
        for a, b in forward:
            layer[b] = max(layer[b], layer[a] + 1)
    rows = {}
    for v in order:
        rows.setdefault(layer[v], []).append(v)
    for sweep in range(4):
        keys = sorted(rows) if sweep % 2 == 0 else sorted(rows, reverse=True)
        for k in keys[1:]:
            ref = rows.get(k - 1 if sweep % 2 == 0 else k + 1, [])
            pos = {v: i for i, v in enumerate(ref)}
            before = list(rows[k])  # sort() empties the list while it works
            def bary(v):
                near = [pos[u] for a, b in forward for u, w in ((a, b), (b, a)) if w == v and u in pos]
                return sum(near) / len(near) if near else before.index(v)
            rows[k].sort(key=bary)
    widths = {k: sum(size[v][1] for v in row) + 48 * (len(row) - 1) for k, row in rows.items()}
    width = max(widths.values())
    pos = {}
    for k, row in rows.items():
        x = (width - widths[k]) / 2
        for v in row:
            pos[v] = (x + size[v][1] / 2, k * 120)
            x += size[v][1] + 48
    return pos, width, max(rows) * 120


def layered(d, warnings, pid):
    """flow, state and architecture. Each top-level group is laid out as its own block, by layers, and the blocks
    sit side by side, so a group's box never covers another group's nodes."""
    nodes, edges = d["nodes"], d.get("edges", [])
    order = [n["id"] for n in nodes]
    info = {n["id"]: n for n in nodes}
    groups = {g["id"]: g for g in d.get("groups", [])}
    def top(gid):
        while gid and groups.get(gid, {}).get("parent"):
            gid = groups[gid]["parent"]
        return gid
    size = {}
    for v in order:
        lines = wrap(info[v]["label"], warnings)
        size[v] = (lines, *box_size(lines))
    blocks = {}
    for v in order:
        blocks.setdefault(top(info[v].get("group")), []).append(v)
    pos, x, height = {}, 60, 0
    for members in blocks.values():
        placed, width, h = place(members, edges, size)
        for v, (px, py) in placed.items():
            pos[v] = (x + px, 80 + py)
        x += width + (90 if len(blocks) > 1 else 0)
        height = max(height, h)
    width = x + 60 - (90 if len(blocks) > 1 else 0)
    height += 80 + 90
    parts, boxes = [], {}
    def bounds(gid):
        members = [v for v in order if info[v].get("group") == gid]
        rects = [(pos[v][0] - size[v][1] / 2, pos[v][1] - size[v][2] / 2, pos[v][0] + size[v][1] / 2,
                  pos[v][1] + size[v][2] / 2) for v in members]
        rects += [bounds(c) for c in groups if groups[c].get("parent") == gid]
        rects = [r for r in rects if r]
        if not rects:
            return None
        box = (min(r[0] for r in rects) - 16, min(r[1] for r in rects) - 30, max(r[2] for r in rects) + 16,
               max(r[3] for r in rects) + 14)
        boxes[gid] = box
        return box
    for gid in groups:
        if not groups[gid].get("parent"):
            bounds(gid)
    for gid, g in groups.items():
        members = [v for v in order if info[v].get("group") == gid]
        if len(members) + sum(1 for c in groups.values() if c.get("parent") == gid) < 2:
            warnings.append(f"group '{g['label']}' holds a single node")
        if gid not in boxes:
            continue
        x1, y1, x2, y2 = boxes[gid]
        for v in order:
            inside = x1 < pos[v][0] < x2 and y1 < pos[v][1] < y2
            if inside and info[v].get("group") != gid and not in_group(info[v].get("group"), gid, groups):
                warnings.append(f"group '{g['label']}' is drawn over '{info[v]['label']}', which isn't in it")
        parts.append(f'<g class="dg-group {esc(g.get("kind", "boundary"))}"><rect x="{x1:.1f}" y="{y1:.1f}" '
                     f'width="{x2 - x1:.1f}" height="{y2 - y1:.1f}" rx="10"/>'
                     f'<text class="dg-group-label" x="{x1 + 10:.1f}" y="{y1 + 18:.1f}">{esc(g["label"])}</text></g>')
    segments = []
    for e in edges:
        (x1, y1), (x2, y2) = pos[e["from"]], pos[e["to"]]
        if e["from"] == e["to"]:
            w = size[e["from"]][1]
            parts.append(f'<path class="dg-edge {esc(e.get("kind", "sync"))}" data-from="{esc(e["from"])}" data-to="{esc(e["to"])}" '
                         f'd="M{x1 + w / 2:.1f},{y1 - 6:.1f} c40,-30 40,30 0,12" marker-end="url(#{pid}-arrow)"/>')
            continue
        sx, sy = clip(x1, y1, x2, y2, size[e["from"]][1] + 4, size[e["from"]][2] + 4)
        tx, ty = clip(x2, y2, x1, y1, size[e["to"]][1] + 8, size[e["to"]][2] + 8)
        if any(o["from"] == e["to"] and o["to"] == e["from"] for o in edges):
            sx, sy, tx, ty = apart(sx, sy, tx, ty)
        segments.append((sx, sy, tx, ty))
        parts.append(f'<line class="dg-edge {esc(e.get("kind", "sync"))}" data-from="{esc(e["from"])}" '
                     f'data-to="{esc(e["to"])}" x1="{sx:.1f}" y1="{sy:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" '
                     f'marker-end="url(#{pid}-arrow)"/>')
        if e.get("label"):
            parts.append(label_svg(sx + (tx - sx) * 0.35, sy + (ty - sy) * 0.35 - 6,
                                   [e["label"][:30] + ("…" if len(e["label"]) > 30 else "")], "dg-edge-label"))
    count = sum(crosses(a, b) for i, a in enumerate(segments) for b in segments[i + 1:])
    if count:
        warnings.append(f"{count} edge crossing{'s' if count != 1 else ''}")
    linked = {e["from"] for e in edges} | {e["to"] for e in edges}
    for v in order:
        if len(order) > 1 and v not in linked:
            warnings.append(f"'{info[v]['label']}' has no edges")
        x, y = pos[v]
        lines, w, h = size[v]
        parts.append(node_svg(info[v], info[v].get("kind", NODE_KINDS[d["type"]][0]), x, y, w, h, lines))
    return width, height, parts


def apart(sx, sy, tx, ty, gap=8):
    """An edge moved to its own side, so two edges between the same nodes in opposite directions don't overlap."""
    length = math.hypot(tx - sx, ty - sy) or 1
    ox, oy = -(ty - sy) / length * gap, (tx - sx) / length * gap
    return sx + ox, sy + oy, tx + ox, ty + oy


def in_group(gid, ancestor, groups):
    while gid:
        if gid == ancestor:
            return True
        gid = groups.get(gid, {}).get("parent")
    return False


def node_svg(n, kind, x, y, w, h, lines, extra=""):
    page = f' data-page="{esc(n["page"])}"' if n.get("page") else ""
    return (f'<g class="dg-node {esc(kind)}{extra}" data-node="{esc(n["id"])}"{page}>'
            f'<title>{esc(n["label"])}</title>{shape(kind, x, y, w, h)}{label_svg(x, y, lines)}</g>')


def sequence(d, warnings, pid):
    people = d["participants"]
    col = {p["id"]: 90 + i * 180 for i, p in enumerate(people)}
    rows = d["messages"]
    height = 110 + len(rows) * 52 + 50
    width = 90 + (len(people) - 1) * 180 + 140
    parts = []
    for p in people:
        x = col[p["id"]]
        lines = wrap(p["label"], warnings)
        w, h = box_size(lines)
        parts.append(f'<line class="dg-lifeline" data-node="{esc(p["id"])}" x1="{x}" y1="{40 + h / 2:.1f}" x2="{x}" y2="{height - 20}"/>')
        parts.append(node_svg(p, p.get("kind", "service"), x, 40, w, h, lines))
    for k, m in enumerate(rows):
        y = 110 + k * 52
        x1, x2 = col[m["from"]], col[m["to"]]
        kind = m.get("kind", "call")
        if x1 == x2:
            parts.append(f'<path class="dg-edge {esc(kind)}" data-from="{esc(m["from"])}" data-to="{esc(m["to"])}" '
                         f'd="M{x1},{y - 8} h40 v16 h-34" marker-end="url(#{pid}-arrow)"/>')
            parts.append(label_svg(x1 + 70, y - 12, [m["label"]], "dg-edge-label start"))
        else:
            gap = 6 if x2 > x1 else -6
            parts.append(f'<line class="dg-edge {esc(kind)}" data-from="{esc(m["from"])}" data-to="{esc(m["to"])}" '
                         f'x1="{x1 + gap}" y1="{y}" x2="{x2 - gap}" y2="{y}" marker-end="url(#{pid}-arrow)"/>')
            parts.append(label_svg((x1 + x2) / 2, y - 10, [m["label"]], "dg-edge-label"))
        if m.get("note"):
            parts.append(label_svg(max(x1, x2) + 16, y + 14, [m["note"]], "dg-note start"))
    return width, height, parts


def journey(d, warnings, pid):
    lanes = {l["id"]: i for i, l in enumerate(d["lanes"])}
    steps = d["steps"]
    width = 150 + len(steps) * 190 + 40
    height = 40 + len(lanes) * 120 + 20
    parts = [f'<g class="dg-lane"><rect x="10" y="{20 + i * 120}" width="{width - 20}" height="110" rx="8"/>'
             f'<text class="dg-lane-label" x="22" y="{80 + i * 120}">{esc(l["label"][:18])}</text></g>'
             for l, i in ((l, lanes[l["id"]]) for l in d["lanes"])]
    pos = {}
    for k, s in enumerate(steps):
        pos[s["id"]] = (150 + k * 190 + 85, 75 + lanes[s["lane"]] * 120)
    steps_next = {s["id"]: s.get("next") or ([steps[k + 1]["id"]] if k + 1 < len(steps) else []) for k, s in enumerate(steps)}
    segments = []
    for k, s in enumerate(steps):
        for n in s.get("next") or ([steps[k + 1]["id"]] if k + 1 < len(steps) else []):
            (x1, y1), (x2, y2) = pos[s["id"]], pos[n]
            sx, sy = clip(x1, y1, x2, y2, 172, 74)
            tx, ty = clip(x2, y2, x1, y1, 180, 82)
            if s["id"] in (steps_next.get(n) or []):
                sx, sy, tx, ty = apart(sx, sy, tx, ty)
            segments.append((sx, sy, tx, ty))
            parts.append(f'<line class="dg-edge sync" data-from="{esc(s["id"])}" data-to="{esc(n)}" x1="{sx:.1f}" '
                         f'y1="{sy:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" marker-end="url(#{pid}-arrow)"/>')
    count = sum(crosses(a, b) for i, a in enumerate(segments) for b in segments[i + 1:])
    if count:
        warnings.append(f"{count} edge crossing{'s' if count != 1 else ''}")
    for s in steps:
        x, y = pos[s["id"]]
        lines = wrap(s["label"], warnings, width=24)
        result = wrap(s["result"], warnings, width=26, lines=1) if s.get("result") else []
        parts.append(f'<g class="dg-node step{" pain" if s.get("pain") else ""}" data-node="{esc(s["id"])}">'
                     f'<title>{esc(s["label"])}{esc(" · pain: " + s["pain"]) if s.get("pain") else ""}</title>'
                     f'{shape("step", x, y, 170, 72)}{label_svg(x, y - (9 if result else 0), lines)}'
                     + (label_svg(x, y + 26, result, "dg-result") if result else "")
                     + (f'<circle class="dg-pain" cx="{x + 80:.1f}" cy="{y - 31:.1f}" r="9"/>'
                        f'<text class="dg-pain-mark" x="{x + 80:.1f}" y="{y - 27:.1f}">!</text>' if s.get("pain") else "")
                     + "</g>")
    return width, height, parts


def tree(d, warnings, pid):
    entries = d["entries"]
    parts, width = [], 300
    for i, e in enumerate(entries):
        path = e["path"].strip("/")
        depth = path.count("/")
        name = path.split("/")[-1] + ("/" if e["path"].endswith("/") else "")
        x, y = 24 + depth * 26, 30 + i * 28
        if depth:
            parts.append(f'<path class="dg-tree-line" d="M{x - 16},{y - 20} v16 h10"/>')
        role = e.get("role", "")
        name_width = 8.2 * len(name)  # estimated: wide enough for common sans-serif fonts at 13 px
        parts.append(f'<g class="dg-node entry" data-node="{esc(path)}"><text class="dg-path start" x="{x}" y="{y}">'
                     f'{esc(name)}</text>' + (f'<text class="dg-role start" x="{x + 16 + name_width:.1f}" y="{y}">'
                                             f'{esc(role)}</text>' if role else "") + "</g>")
        width = max(width, x + 24 + name_width + 7 * len(role))
    return width, 30 + len(entries) * 28, parts


def timeline(d, warnings, pid):
    items = sorted(d["items"], key=lambda i: i["date"])
    step = 170
    width, height = 80 + max(1, len(items) - 1) * step + 120, 210
    parts = [f'<line class="dg-axis" x1="40" y1="105" x2="{width - 40}" y2="105"/>']
    for k, item in enumerate(items):
        x = 80 + k * step
        up = k % 2 == 0
        lines = wrap(item["label"], warnings, width=22)
        parts.append(f'<g class="dg-node item {esc(item.get("kind", "change"))}" data-node="{esc(item["date"])}-{k}">'
                     f'<title>{esc(item["date"])}: {esc(item["label"])}</title>'
                     f'<circle cx="{x}" cy="105" r="7"/><line class="dg-tick" x1="{x}" y1="{98 if up else 112}" x2="{x}" '
                     f'y2="{70 if up else 140}"/>{label_svg(x, 52 if up else 160, lines)}'
                     f'<text class="dg-date" x="{x}" y="{125 if up else 92}">{esc(item["date"])}</text></g>')
    return width, height, parts


LAYOUTS = {"flow": layered, "state": layered, "architecture": layered, "sequence": sequence, "journey": journey,
           "tree": tree, "timeline": timeline}

PREVIEW_STYLE = """
.dg-bg{fill:#fff}text{font:13px Inter,"Helvetica Neue",Arial,sans-serif;fill:#242424;text-anchor:middle}.start{text-anchor:start}
.dg-node rect,.dg-node polygon,.dg-node path{fill:#fff;stroke:#628ac8;stroke-width:1.5}
.dg-node.decision polygon{fill:#fbf6ec;stroke:#d6ae65}.dg-node.store path,.dg-node.data polygon{fill:#f0f8f5;stroke:#65bc9d}
.dg-node.person rect,.dg-node.start rect,.dg-node.end rect{stroke:#a18bd4}
.dg-node.external rect{stroke:#909399;stroke-dasharray:5 4}.dg-node.pain rect{stroke:#d98298}.dg-pain{fill:#d98298}
.dg-pain-mark{fill:#fff;font-weight:700}.dg-edge{stroke:#909399;stroke-width:1.5;fill:none}
.dg-edge.async,.dg-edge.reply{stroke-dasharray:6 4}.dg-edge.data{stroke:#65bc9d}.dg-arrowhead{fill:#909399}
.dg-edge-label,.dg-note,.dg-result,.dg-role,.dg-date{font-size:11px;fill:#686b70}
.dg-edge-label{paint-order:stroke;stroke:#fff;stroke-width:4px;stroke-linejoin:round}
.dg-group rect{fill:#faf8fd;stroke:#a18bd4;stroke-dasharray:4 3}.dg-group-label,.dg-lane-label{text-anchor:start;font-size:12px;fill:#6a52a8}
.dg-lane rect{fill:#f3f3f1;stroke:#e0e1dd}.dg-lifeline,.dg-tree-line,.dg-tick{stroke:#e0e1dd;stroke-dasharray:4 4;fill:none}
.dg-axis{stroke:#909399;stroke-width:2}.dg-node.item circle{fill:#628ac8}
"""


def render(d, pid="dg", standalone=False):
    """{svg, width, height, warnings}. With standalone, the SVG carries its own style and background, for a
    preview; on the site it uses the site's stylesheet, since the CSP allows no inline styles."""
    warnings = []
    pid = re.sub(r"[^a-z0-9-]", "-", pid.lower())
    width, height, parts = LAYOUTS[d["type"]](d, warnings, pid)
    width, height = math.ceil(width), math.ceil(height)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" class="dg dg-{esc(d["type"])}" viewBox="0 0 {width} {height}" '
           f'width="{width}" height="{height}" role="img" aria-labelledby="{pid}-t {pid}-d">'
           f'<title id="{pid}-t">{esc(d["title"])}</title><desc id="{pid}-d">{esc(d.get("caption", ""))}</desc>'
           + (f"<style>{PREVIEW_STYLE}</style><rect class=\"dg-bg\" width=\"{width}\" height=\"{height}\"/>" if standalone else "")
           + f'<defs><marker id="{pid}-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
             f'orient="auto-start-reverse"><path class="dg-arrowhead" d="M0,0 L10,5 L0,10 z"/></marker></defs>'
           + "".join(parts) + "</svg>")
    return {"svg": svg, "width": width, "height": height, "warnings": sorted(set(warnings))}


def can_preview():
    return shutil.which("rsvg-convert") is not None


def preview(d, max_width=1200):
    """The diagram as a PNG, base64, for agents that read images; None without rsvg-convert."""
    if not can_preview():
        return None
    drawn = render(d, standalone=True)
    try:
        done = subprocess.run(["rsvg-convert", "-f", "png", "-w", str(min(max_width, drawn["width"]))],
                              input=drawn["svg"].encode(), capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return base64.b64encode(done.stdout).decode() if done.returncode == 0 and done.stdout else None
