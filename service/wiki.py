"""The knowledge wiki (docs/knowledge_wiki.md): pages Claude compiles, read and written through the layer.

One page per project, person and recurring topic. A page has compiled sections, which Claude writes
with propose_wiki_update, and generated ones, which this module builds from the store each time the
page is read. A compiled section is a list of statements, and every statement cites its evidence:
a claim, an event, or a commit or file in a repository (repos.py), plus links to other pages.

Labels are never stored. Each read works them out from the citations, best first: verified (a claim I
confirmed), repo (a commit or file), unconfirmed (only unconfirmed claims or events); disputed if any
cited claim is. A statement with any confidential citation is hidden, and so is one whose evidence is
all gone, so a deletion, a label or retention reaches the wiki at the next read. Claude sees no
count of what's hidden.
"""

import json
import re
from collections import Counter
from datetime import date, timedelta

import diagrams
import reads
import repos
import store
from tools import WIKI_COMPILED, WIKI_GENERATED
from validate import HTML_TAG, MARKDOWN_LINK, TITLE_CHARS, WIKI_LINK
from writes import Refused, audit, transaction

PAGE_CHARS = 12000  # compiled text on one page
PAGE_DIAGRAMS = 4
REPO_MAP_FOLDERS = 25
CUSTOM_SECTIONS = 8
LABEL_ORDER = ("verified", "repo", "unconfirmed")
LIVE, GONE, HIDDEN = "live", "gone", "hidden"
GENERATED_CLAIMS = 30  # claims listed in one generated section
ACTIVITY_WEEKS = 12


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", reads.fold(text.lower())).strip("-")[:50].strip("-") or "page"


def plain(text):
    """A statement's words for the search index: link targets and Markdown marks left out."""
    text = WIKI_LINK.sub(lambda m: m.group(2) or m.group(1), text)
    text = MARKDOWN_LINK.sub(lambda m: m.group(2), text)
    return re.sub(r"[*`]", "", text)


def tokens(chars):
    return max(1, round(chars / 4))


# Pages ---------------------------------------------------------------------------

def project_page_id(db, project_id):
    """A project's page id: its stored page's, else the project's id, unless another page took it."""
    row = db.execute("SELECT id FROM wiki_pages WHERE project_id = ?", (project_id,)).fetchone()
    if row:
        return row["id"]
    taken = db.execute("SELECT 1 FROM wiki_pages WHERE id = ?", (project_id,)).fetchone()
    return f"{project_id}-project" if taken else project_id


def unwritten_project_page(db, project):
    return {"id": project_page_id(db, project["id"]), "kind": "project", "title": project["name"],
            "project_id": project["id"], "email": None, "created_at": None, "stored": False}


def page_row(db, page_id):
    """The page with this id, if Claude may see it: a stored page, or a project's page not written yet."""
    row = db.execute("SELECT * FROM wiki_pages WHERE id = ?", (page_id,)).fetchone()
    if row:
        if row["kind"] == "project" and reads.find_project(db, row["project_id"]) is None:
            return None
        return {**dict(row), "stored": True}
    for project_id in dict.fromkeys([page_id, page_id.removesuffix("-project")]):
        project = reads.find_project(db, project_id)
        if project and project_page_id(db, project_id) == page_id:
            return unwritten_project_page(db, project)
    return None


def visible_pages(db):
    pages = [{**dict(r), "stored": True} for r in db.execute("SELECT * FROM wiki_pages ORDER BY kind, id")]
    pages = [p for p in pages if p["kind"] != "project" or reads.find_project(db, p["project_id"])]
    have = {p["project_id"] for p in pages}
    for project in db.execute("SELECT * FROM projects p WHERE " + reads.NOT_CONFIDENTIAL_PROJECT.format(column="p.id")
                              + " ORDER BY id"):
        if project["id"] not in have:
            pages.append(unwritten_project_page(db, project))
    return pages


def current(db, page_id):
    return db.execute("SELECT * FROM wiki_current WHERE page_id = ?", (page_id,)).fetchone()


class Reader:
    """One tool call's view of the wiki: citations checked once, repository heads looked up once."""

    def __init__(self, db):
        self.db = db
        self.heads = repos.Heads()
        self.repos = {r["id"]: r for r in repos.visible_repos(db)}
        self.cache = {}

    # Citations and statements ----------------------------------------------------

    def cite(self, c):
        """(state, label, what Claude sees) for one citation."""
        db = self.db
        if c["claim_id"]:
            row = db.execute("SELECT status FROM claims_shareable WHERE id = ?", (c["claim_id"],)).fetchone()
            if row is None:
                exists = db.execute("SELECT 1 FROM claims WHERE id = ?", (c["claim_id"],)).fetchone()
                return (HIDDEN if exists else GONE), None, None
            if row["status"] not in reads.LABELS:  # retracted or superseded
                return GONE, None, None
            label = reads.LABELS[row["status"]]
            return LIVE, label, {"claim_id": c["claim_id"], "label": label}
        if c["event_id"]:
            if db.execute("SELECT 1 FROM events_for_claude WHERE id = ?", (c["event_id"],)).fetchone():
                return LIVE, "unconfirmed", {"event_id": c["event_id"]}
            exists = db.execute("SELECT 1 FROM events WHERE id = ?", (c["event_id"],)).fetchone()
            return (HIDDEN if exists else GONE), None, None
        if c["commit_sha"]:
            repo = self.repos.get(c["source_id"])
            if repo is None:
                exists = db.execute("SELECT 1 FROM sources WHERE id = ?", (c["source_id"],)).fetchone()
                return (HIDDEN if exists else GONE), None, None
            item = {"repo": repo["repo"], "commit": c["commit_sha"][:12]}
            if c["path"]:
                item["path"] = c["path"]
            return LIVE, "repo", item
        target = self.page(c["page_id"])
        if target is None:
            return GONE, None, None
        return LIVE, None, {"page": target["id"], **({"section": c["section_id"]} if c["section_id"] else {})}

    def judge(self, cites):
        """A statement's label and visible citations, or None if it's hidden."""
        states = [self.cite(c) for c in cites]
        if any(s[0] == HIDDEN for s in states):
            return None
        live = [s for s in states if s[0] == LIVE]
        labels = {s[1] for s in live if s[1]}
        if not labels:
            return None
        label = "disputed" if "disputed" in labels else next(x for x in LABEL_ORDER if x in labels)
        return {"label": label, "cites": [s[2] for s in live], "gone": len(states) - len(live)}

    def statements(self, section_seq):
        """The visible statements of one stored section, with the pages each links to."""
        rows = self.db.execute("SELECT * FROM wiki_statements WHERE section_seq = ? ORDER BY position", (section_seq,)).fetchall()
        cites, links = {}, {}
        for c in self.db.execute("SELECT c.* FROM wiki_citations c JOIN wiki_statements s ON s.seq = c.statement_seq"
                                 " WHERE s.section_seq = ? ORDER BY c.statement_seq, c.position", (section_seq,)):
            cites.setdefault(c["statement_seq"], []).append(c)
        for l in self.db.execute("SELECT l.* FROM wiki_links l JOIN wiki_statements s ON s.seq = l.statement_seq"
                                 " WHERE s.section_seq = ?", (section_seq,)):
            links.setdefault(l["statement_seq"], []).append(l["target"])
        shown = []
        for st in rows:
            verdict = self.judge(cites.get(st["seq"], []))
            if verdict is None:
                continue
            block = json.loads(st["block"]) if st["block"] else {}
            if st["kind"] == "diagram":
                item = {"id": f"s-{st['seq']}", "kind": "diagram",
                        "diagram": {k: v for k, v in block.items() if k != "warnings"},
                        "layout_warnings": block.get("warnings", []), "label": verdict["label"], "cites": verdict["cites"]}
            elif st["kind"] == "image":
                item = {"id": f"s-{st['seq']}", "kind": "image",
                        "image": {"repo": verdict["cites"][0].get("repo"), "commit": block["commit"][:12], "path": block["path"]},
                        "caption": block.get("caption"), "label": verdict["label"], "cites": verdict["cites"]}
            else:
                item = {"id": f"s-{st['seq']}", "text": st["text"], "style": st["style"], "label": verdict["label"],
                        "cites": verdict["cites"]}
            if verdict["gone"]:
                item["citations_gone"] = verdict["gone"]
            shown.append((item, links.get(st["seq"], [])))
        return shown

    def statement_visible(self, statement_seq):
        cites = self.db.execute("SELECT * FROM wiki_citations WHERE statement_seq = ? ORDER BY position",
                                (statement_seq,)).fetchall()
        return self.judge(cites) is not None

    # Pages -----------------------------------------------------------------------

    def page(self, page_id):
        if ("page", page_id) not in self.cache:
            self.cache[("page", page_id)] = page_row(self.db, page_id)
        return self.cache[("page", page_id)]

    def compiled(self, page_id, version):
        """The compiled sections of a version, with only visible statements; empty sections left out."""
        sections = []
        for s in self.db.execute("SELECT * FROM wiki_sections WHERE page_id = ? AND version = ? ORDER BY position",
                                 (page_id, version)):
            shown = self.statements(s["seq"])
            if not shown:
                continue
            blocks = [item for item, _ in shown]
            sections.append({"id": s["section_id"], "heading": s["heading"], "source": "compiled",
                             "summary": s["summary"], "blocks": blocks,
                             "size_tokens": tokens(sum(len(b.get("text") or json.dumps(b.get("diagram") or b.get("image")))
                                                       + 40 for b in blocks)),
                             "labels": dict(Counter(b["label"] for b in blocks)),
                             "links": sorted({t for _, targets in shown for t in targets})})
        return sections

    def incoming(self, page_id):
        """The pages whose visible statements link to this one."""
        rows = self.db.execute(
            "SELECT DISTINCT l.statement_seq, sec.page_id FROM wiki_links l"
            " JOIN wiki_statements st ON st.seq = l.statement_seq JOIN wiki_sections sec ON sec.seq = st.section_seq"
            " JOIN wiki_current v ON v.page_id = sec.page_id AND v.version = sec.version"
            " WHERE l.target = ? AND sec.page_id <> ?", (page_id, page_id)).fetchall()
        found = {}
        for r in rows:
            source = self.page(r["page_id"])
            if source and r["page_id"] not in found and self.statement_visible(r["statement_seq"]):
                found[r["page_id"]] = {"type": source["kind"], "page": source["id"], "title": source["title"]}
        return list(found.values())

    def staleness(self, page, version, detail=True):
        """Whether a page's current version is behind its repositories or its claims, and why."""
        if version is None:
            return {"is_stale": False}
        why = []
        for source_id, built in json.loads(version["built_from"]).items():
            repo = self.repos.get(int(source_id))
            head = self.heads.get(repo["locator"]) if repo else None
            if head is None or head["commit"] == built:
                continue
            if not detail:
                why.append(repo["repo"])
                continue
            try:
                moved = repos.drift(repo["locator"], built, head["commit"])
            except Exception:  # a repository that moved or broke: say only that it changed
                moved = {"commits": None}
            if moved.get("missing"):
                why.append(f"{repo['repo']} no longer has {built[:12]}, the commit this page was built from.")
            elif moved.get("commits") is None:
                why.append(f"{repo['repo']} changed since {built[:12]}.")
            else:
                why.append(f"{moved['commits']} commits on {repo['repo']} {head['branch']} since {built[:12]}, "
                           f"{moved['docs_commits']} of them in its docs.")
        if page["kind"] == "project":
            changed = self.db.execute(
                f"SELECT COUNT(*) FROM claims_for_claude WHERE project_id = ? AND status IN {reads.OPEN}"
                " AND type <> 'session_note' AND version_at > ?", (page["project_id"], version["written_at"])).fetchone()[0]
        else:
            changed = self.db.execute(
                "SELECT COUNT(DISTINCT c.claim_id) FROM wiki_citations c JOIN wiki_statements st ON st.seq = c.statement_seq"
                " JOIN wiki_sections sec ON sec.seq = st.section_seq JOIN claims_for_claude cc ON cc.id = c.claim_id"
                " WHERE sec.page_id = ? AND sec.version = ? AND cc.version_at > ?",
                (page["id"], version["version"], version["written_at"])).fetchone()[0]
        if changed:
            why.append(f"{changed} claims {'about the project' if page['kind'] == 'project' else 'it cites'} "
                       "are new or changed since this version.")
        return {"is_stale": bool(why), **({"why": why} if detail and why else {})}

    # Generated sections ------------------------------------------------------------

    def claim_rows(self, where, params, order):
        rows = reads.claims(self.db, where, params, order=order)
        keep = ("claim_id", "type", "text", "label", "project", "about_day", "due_at", "owner", "counterparty")
        return [{k: c[k] for k in keep if c.get(k) is not None} for c in rows]

    def generated(self, page):
        """Each generated section of a page: (id, heading, summary, items)."""
        kind, db = page["kind"], self.db
        sections = {}
        today = date.today().isoformat()
        if kind == "project":
            pid = page["project_id"]
            recent = "COALESCE(about_day, substr(version_at, 1, 10)) DESC, version_at DESC LIMIT ?"
            decisions = self.claim_rows("project_id = ? AND type = 'decision'", (pid, GENERATED_CLAIMS), recent)
            commitments = self.claim_rows("project_id = ? AND type = 'commitment'", (pid,), "due_at IS NULL, due_at")
            for c in commitments:
                c["direction"] = "mine" if c.get("owner") == "me" else "theirs"
                if c.get("due_at") and c["due_at"][:10] < today:
                    c["overdue"] = True
            blockers = self.claim_rows("project_id = ? AND type = 'blocker'", (pid, GENERATED_CLAIMS), recent)
            sections["decisions"] = (claims_summary(decisions, "decision"), decisions)
            sections["commitments"] = (claims_summary(commitments, "open commitment"), commitments)
            sections["open-work"] = (claims_summary(blockers, "blocker"), blockers)
            people = Counter()
            for c in self.claim_rows("project_id = ?", (pid,), "first_proposed_at"):
                for who in (c.get("owner"), c.get("counterparty")):
                    if who and who != "me":
                        people[who.lower()] += 1
            authors = dict(db.execute(
                "SELECT lower(actor), COUNT(*) FROM events_for_claude WHERE project_id = ? AND type IN"
                " ('git.commit', 'git.merge') AND actor <> 'me' GROUP BY lower(actor)", (pid,)).fetchall())
            pages = {r["email"]: r["id"] for r in db.execute("SELECT id, email FROM wiki_pages WHERE kind = 'person'")}
            items = [{"person": who, **({"page": pages[who]} if who in pages else {}),
                      **({"claims": people[who]} if people[who] else {}), **({"commits": authors[who]} if who in authors else {})}
                     for who in sorted(set(people) | set(authors), key=lambda w: -(people[w] + authors.get(w, 0)))]
            sections["people"] = (f"{len(items)} {'person' if len(items) == 1 else 'people'} in its claims and commits."
                                  if items else "Nobody yet.", items[:30])
            aliases = [dict(a) for a in db.execute("SELECT kind, value FROM project_aliases WHERE project_id = ?"
                                                   " ORDER BY kind, value", (pid,))]
            sections["where-it-lives"] = (", ".join(sorted({a["kind"] for a in aliases})) or "Nowhere recorded.", aliases)
            weeks = {}
            since = (date.today() - timedelta(weeks=ACTIVITY_WEEKS)).isoformat()
            for e in db.execute("SELECT local_day, type, payload FROM events_for_claude WHERE project_id = ? AND local_day >= ?"
                                " AND type IN ('git.commit', 'git.merge', 'app.focus')", (pid, since)):
                year, week, _ = date.fromisoformat(e["local_day"]).isocalendar()
                w = weeks.setdefault(f"{year}-W{week:02d}", {"week": f"{year}-W{week:02d}", "commits": 0, "focus_minutes": 0})
                if e["type"] == "app.focus":
                    w["focus_minutes"] += (json.loads(e["payload"]).get("seconds") or 0) / 60
                else:
                    w["commits"] += 1
            activity = sorted(weeks.values(), key=lambda w: w["week"], reverse=True)
            for w in activity:
                w["focus_minutes"] = round(w["focus_minutes"])
            maps = self.repo_map(pid)
            sections["repo-map"] = (f"{sum(m['files'] for m in maps)} files in {len(maps)} "
                                    f"{'repository' if len(maps) == 1 else 'repositories'}." if maps else
                                    "No repository the layer may read.", maps)
            sections["activity"] = (f"{sum(w['commits'] for w in activity)} commits in the last {ACTIVITY_WEEKS} weeks."
                                    if activity else f"No activity in the last {ACTIVITY_WEEKS} weeks.", activity)
        elif kind == "person":
            email = page["email"]
            commitments = self.claim_rows("type = 'commitment' AND (lower(owner) = ? OR lower(counterparty) = ?)",
                                          (email, email), "due_at IS NULL, due_at")
            for c in commitments:
                c["direction"] = "theirs" if (c.get("owner") or "").lower() == email else "mine"
            sections["commitments"] = (claims_summary(commitments, "open commitment"), commitments)
            projects = {c["project"] for c in self.claim_rows("lower(owner) = ? OR lower(counterparty) = ?",
                                                              (email, email), "first_proposed_at") if c.get("project")}
            projects |= {self.page(p["page"])["project_id"] for p in self.incoming(page["id"]) if p["type"] == "project"}
            items = [{"project": p, "page": project_page_id(db, p)} for p in sorted(projects) if reads.find_project(db, p)]
            sections["projects"] = (f"{len(items)} projects." if items else "None yet.", items)
        if kind in ("person", "topic"):
            mentioned = self.incoming(page["id"])
            sections["mentioned-in"] = (f"{len(mentioned)} pages link here." if mentioned else "No page links here.", mentioned)
        if kind == "topic":
            version = current(db, page["id"])
            linked = {t for s in (self.compiled(page["id"], version["version"]) if version else []) for t in s["links"]}
            items = [{"page": p["id"], "title": p["title"]} for t in sorted(linked)
                     for p in [self.page(t)] if p and p["kind"] == "project"]
            sections["projects"] = (f"{len(items)} projects." if items else "None yet.", items)
        return [{"id": sid, "heading": heading, "source": "generated", "summary": sections[sid][0], "items": sections[sid][1],
                 "size_tokens": tokens(len(json.dumps(sections[sid][1], ensure_ascii=False)))}
                for sid, heading in WIKI_GENERATED[kind].items() if sid in sections]

    def repo_map(self, project_id):
        """Each repository's top folders at its head, with how many files and which languages: built by code."""
        maps = []
        for repo in (r for r in self.repos.values() if r["project_id"] == project_id):
            head = self.heads.get(repo["locator"])
            if head is None:
                continue
            try:
                files = [f for f in repos.git(repo["locator"], "ls-tree", "-r", "--name-only", "-z", head["commit"]).split("\0") if f]
            except Exception:
                continue
            folders = {}
            for f in files:
                if repos.is_secret(f):
                    continue
                top = f.split("/", 1)[0] + ("/" if "/" in f else "")
                entry = folders.setdefault(top, {"files": 0, "languages": Counter()})
                entry["files"] += 1
                ext = f.rsplit(".", 1)[-1].lower() if "." in f.rsplit("/", 1)[-1] else ""
                if ext and len(ext) <= 5:
                    entry["languages"][ext] += 1
            ranked = sorted(folders.items(), key=lambda kv: (not kv[0].endswith("/"), -kv[1]["files"]))[:REPO_MAP_FOLDERS]
            maps.append({"repo": repo["repo"], "commit": head["commit"][:12], "files": len(files),
                         "folders": [{"path": name, "files": e["files"],
                                      "languages": [x for x, _ in e["languages"].most_common(3)]} for name, e in ranked]})
        return maps

    # Tool results --------------------------------------------------------------------

    def catalog(self, kind=None, project=None):
        pages = visible_pages(self.db)
        if kind:
            pages = [p for p in pages if p["kind"] == kind]
        if project:
            target = project_page_id(self.db, project)
            linking = {r[0] for r in self.db.execute(
                "SELECT DISTINCT sec.page_id FROM wiki_links l JOIN wiki_statements st ON st.seq = l.statement_seq"
                " JOIN wiki_sections sec ON sec.seq = st.section_seq JOIN wiki_current v ON v.page_id = sec.page_id"
                " AND v.version = sec.version WHERE l.target = ?", (target,))}
            pages = [p for p in pages if p["project_id"] == project or p["id"] in linking]
        entries = []
        for p in pages:
            v = current(self.db, p["id"]) if p["stored"] else None
            chars = self.db.execute("SELECT COALESCE(SUM(length(st.text)), 0) FROM wiki_statements st JOIN wiki_sections sec"
                                    " ON sec.seq = st.section_seq WHERE sec.page_id = ? AND sec.version = ?",
                                    (p["id"], v["version"] if v else 0)).fetchone()[0]
            entry = {"page": p["id"], "kind": p["kind"], "title": p["title"],
                     **({"project": p["project_id"]} if p["project_id"] else {}), **({"email": p["email"]} if p["email"] else {}),
                     "summary": v["summary"] if v else None, "version": v["version"] if v else 0,
                     "updated_at": v["written_at"] if v else None, "compiled": v is not None,
                     "stale": self.staleness(p, v, detail=False)["is_stale"], "size_tokens": tokens(chars) if v else 0}
            entries.append({k: val for k, val in entry.items() if val is not None})
        entries.sort(key=lambda e: (["project", "topic", "person"].index(e["kind"]), e["page"]))
        result = {"pages": entries, "count": len(entries), "found": bool(entries)}
        if not entries:
            result["gaps"] = ["The wiki has no pages yet" + (" of that kind" if kind else "") +
                              (f" for project {project}" if project else "") + "."]
        return result

    def outline(self, page, sections=None, previews=False):
        v = current(self.db, page["id"]) if page["stored"] else None
        compiled = self.compiled(page["id"], v["version"]) if v else []
        generated = self.generated(page)
        written = {s["id"] for s in compiled}
        result = {"page": page["id"], "kind": page["kind"], "title": page["title"],
                  **({"project": page["project_id"]} if page["project_id"] else {}),
                  **({"email": page["email"]} if page["email"] else {}),
                  "summary": v["summary"] if v else None,
                  "key_terms": json.loads(v["key_terms"]) if v else [],
                  "version": v["version"] if v else 0,
                  "updated_at": v["written_at"] if v else None,
                  "written_by": v["written_by"] if v else None,
                  "built_from": [{"repo": self.repos[int(s)]["repo"], "commit": c[:12]}
                                 for s, c in (json.loads(v["built_from"]).items() if v else []) if int(s) in self.repos],
                  "stale": self.staleness(page, v),
                  "sections": [{k: s[k] for k in ("id", "heading", "source", "summary", "size_tokens") if s.get(k) is not None}
                               | ({"labels": s["labels"]} if s.get("labels") else {}) for s in compiled + generated],
                  "not_written": [sid for sid in WIKI_COMPILED[page["kind"]] if sid not in written],
                  "links": [{"type": t["kind"], "page": t["id"], "title": t["title"]}
                            for target in sorted({x for s in compiled for x in s["links"]})
                            for t in [self.page(target)] if t and t["id"] != page["id"]],
                  "linked_from": self.incoming(page["id"]),
                  "found": True}
        note = self.db.execute("SELECT text, changed_at FROM wiki_notes WHERE page_id = ?", (page["id"],)).fetchone()
        if note:
            result["my_notes"] = {"text": note["text"], "changed_at": note["changed_at"], "label": "verified"}
        gaps = []
        if v is None:
            gaps.append("This page hasn't been written yet." + (
                " Read the project's repository with read_repo, and write it with propose_wiki_update (base_version 0)."
                if page["kind"] == "project" else ""))
        if sections is not None:
            by_id = {s["id"]: s for s in compiled + generated}
            if previews:
                shown = [b for sid in sections if sid in by_id for b in by_id[sid].get("blocks", []) if b.get("kind") == "diagram"]
                images = [(b["diagram"]["id"], diagrams.preview(b["diagram"])) for b in shown]
                result["previews"] = [{"diagram": d, "image": n + 1} for n, (d, png) in enumerate(i for i in images if i[1])]
                result["_images"] = [{"data": png, "mimeType": "image/png"} for _, png in images if png]
                if shown and not result["_images"]:
                    gaps.append("The layer can't draw previews here (rsvg-convert isn't installed); the descriptions "
                                "and layout_warnings are all there is.")
            result["content"] = [{k: val for k, val in by_id[sid].items() if k not in ("links", "size_tokens")}
                                 for sid in sections if sid in by_id]
            missing = [sid for sid in sections if sid not in by_id]
            if missing:
                gaps.append(f"No section {', '.join(missing)} on this page, or nothing in it you can see. "
                            "The outline lists its sections.")
        if gaps:
            result["gaps"] = gaps
        return {k: val for k, val in result.items() if val is not None}


def claims_summary(items, noun):
    if not items:
        return f"No {noun}s."
    labels = Counter(c["label"] for c in items)
    detail = ", ".join(f"{n} {label}" for label, n in labels.most_common())
    return f"{len(items)} {noun}{'s' if len(items) != 1 else ''} ({detail})."


# Read tools -------------------------------------------------------------------------

def get_wiki_page(db, args):
    reader = Reader(db)
    if "page" not in args:
        return reader.catalog(args.get("kind"), args.get("project"))
    page = reader.page(args["page"])
    if page is None:
        return {"found": False, "gaps": [f"There's no wiki page {args['page']}. Call get_wiki_page without page "
                                         "for the catalog of pages."]}
    return reader.outline(page, args.get("sections"), args.get("previews", False))


def for_project(db, project_id):
    """The project page's outline for get_project: what's written, and whether it's stale."""
    reader = Reader(db)
    page = reader.page(project_page_id(db, project_id))
    if page is None:
        return None
    outline = reader.outline(page)
    if not outline["version"]:
        return {"page": page["id"], "compiled": False,
                "note": "No wiki page yet. Write one with read_repo and propose_wiki_update."}
    return {"page": page["id"], "compiled": True, "version": outline["version"], "updated_at": outline.get("updated_at"),
            "summary": outline.get("summary"), "stale": outline["stale"],
            "sections": [s for s in outline["sections"] if s["source"] == "compiled"],
            "note": "Read sections in full with get_wiki_page(page, sections)."}


def search_hits(db, query, project, limit):
    """Wiki sections and pages matching a search, as (rank, item) pairs; only what Claude may see."""
    reader = Reader(db)
    target = project_page_id(db, project) if project else None

    def allowed(page):
        if page is None or not project:
            return page is not None
        if page["project_id"] == project:
            return True
        return db.execute("SELECT 1 FROM wiki_links l JOIN wiki_statements st ON st.seq = l.statement_seq JOIN wiki_sections"
                          " sec ON sec.seq = st.section_seq JOIN wiki_current v ON v.page_id = sec.page_id AND v.version ="
                          " sec.version WHERE sec.page_id = ? AND l.target = ? LIMIT 1", (page["id"], target)).fetchone()

    found, seen = [], set()
    for r in db.execute("SELECT rowid, snippet(wiki_fts, -1, '«', '»', '…', 12) AS snip, bm25(wiki_fts, 2.0, 1.0) AS rank"
                        " FROM wiki_fts WHERE wiki_fts MATCH ? ORDER BY rank LIMIT ?", (query, limit * 5)).fetchall():
        sec = db.execute("SELECT sec.* FROM wiki_statements st JOIN wiki_sections sec ON sec.seq = st.section_seq"
                         " JOIN wiki_current v ON v.page_id = sec.page_id AND v.version = sec.version WHERE st.seq = ?",
                         (r["rowid"],)).fetchone()
        if sec is None or (sec["page_id"], sec["section_id"]) in seen:
            continue
        page = reader.page(sec["page_id"])
        if not allowed(page) or not reader.statement_visible(r["rowid"]):
            continue
        seen.add((sec["page_id"], sec["section_id"]))
        shown = [item for item, _ in reader.statements(sec["seq"])]
        found.append((r["rank"], {"item_type": "wiki", "page": page["id"], "title": page["title"], "section": sec["section_id"],
                                  "heading": sec["heading"], "snippet": r["snip"],
                                  "labels": dict(Counter(s["label"] for s in shown)),
                                  "stale": reader.staleness(page, current(db, page["id"]), detail=False)["is_stale"]}))
    for r in db.execute("SELECT rowid, snippet(wiki_pages_fts, -1, '«', '»', '…', 12) AS snip,"
                        " bm25(wiki_pages_fts, 3.0, 2.0, 1.0) AS rank FROM wiki_pages_fts WHERE wiki_pages_fts MATCH ?"
                        " ORDER BY rank LIMIT ?", (query, limit)).fetchall():
        v = db.execute("SELECT * FROM wiki_current WHERE seq = ?", (r["rowid"],)).fetchone()
        page = reader.page(v["page_id"]) if v else None
        if v is None or not allowed(page) or any(p == page["id"] for p, _ in seen):
            continue
        found.append((r["rank"], {"item_type": "wiki", "page": page["id"], "title": page["title"], "kind": page["kind"],
                                  "summary": v["summary"], "snippet": r["snip"],
                                  "stale": reader.staleness(page, v, detail=False)["is_stale"]}))
    return found


def metrics(db, since):
    reader = Reader(db)
    pages = visible_pages(db)
    labels, stale, compiled = Counter(), 0, 0
    for p in pages:
        v = current(db, p["id"]) if p["stored"] else None
        if v is None:
            continue
        compiled += 1
        stale += reader.staleness(p, v, detail=False)["is_stale"]
        for s in reader.compiled(p["id"], v["version"]):
            labels.update(b["label"] for b in s["blocks"])
    statements = sum(labels.values())
    misses = db.execute("SELECT at, query FROM search_misses WHERE at >= ? ORDER BY at DESC", (since,)).fetchall()
    return {"pages": dict(Counter(p["kind"] for p in pages)), "written": compiled, "stale": stale,
            "statements_by_label": dict(labels),
            "verified_or_repo_share": round((labels["verified"] + labels["repo"]) / statements, 2) if statements else None,
            "search_misses": {"count": len(misses), "recent": [dict(m) for m in misses[:10]]}}


# Writing -------------------------------------------------------------------------------

def stored_sections(db, page_id, version):
    """Every section of a stored version as written, hidden statements included, to carry into the next one."""
    sections = []
    for s in db.execute("SELECT * FROM wiki_sections WHERE page_id = ? AND version = ? ORDER BY position", (page_id, version)):
        statements = []
        for st in db.execute("SELECT * FROM wiki_statements WHERE section_seq = ? ORDER BY position", (s["seq"],)):
            cites = [dict(c) for c in db.execute("SELECT * FROM wiki_citations WHERE statement_seq = ? ORDER BY position",
                                                 (st["seq"],))]
            links = [l["target"] for l in db.execute("SELECT target FROM wiki_links WHERE statement_seq = ?", (st["seq"],))]
            statements.append({"text": st["text"], "style": st["style"], "cites": cites, "links": links,
                               "kind": st["kind"], "block": json.loads(st["block"]) if st["block"] else None})
        sections.append({"id": s["section_id"], "heading": s["heading"], "summary": s["summary"], "statements": statements})
    return sections


def check_cites(db, reader, page, block, where, problems):
    """The citations of one statement as stored rows, and the pages it links to; problems are added to the list."""
    rows, links = [], []
    empty = {"claim_id": None, "event_id": None, "source_id": None, "commit_sha": None, "path": None,
             "page_id": None, "section_id": None}
    for k, c in enumerate(block["cites"]):
        spot = f"{where}.cites[{k}]"
        if "claim_id" in c:
            claim = db.execute("SELECT status FROM claims_for_claude WHERE id = ?", (c["claim_id"],)).fetchone()
            if claim is None:
                problems.append(f"{spot}: there's no claim {c['claim_id']} you can cite. Find it with search.")
            elif claim["status"] == "superseded":
                problems.append(f"{spot}: claim {c['claim_id']} was superseded; cite the claim that replaced it.")
            rows.append({**empty, "claim_id": c["claim_id"]})
        elif "event_id" in c:
            if not db.execute("SELECT 1 FROM events_for_claude WHERE id = ?", (c["event_id"],)).fetchone():
                problems.append(f"{spot}: {c['event_id']} isn't an event the layer has. Use an event_id a read tool returned.")
            rows.append({**empty, "event_id": c["event_id"]})
        elif "commit" in c:
            repo = repos.by_name(db, c["repo"])
            if repo is None:
                names = ", ".join(r["repo"] for r in reader.repos.values()) or "none"
                problems.append(f"{spot}: there's no repository {c['repo']} you can read. Repositories: {names}.")
                continue
            sha = repos.resolve(repo["locator"], c["commit"])
            if sha is None:
                problems.append(f"{spot}: {c['repo']} has no commit {c['commit']}.")
                continue
            path = c.get("path", "").strip("/") or None
            if path and repos.is_secret(path):
                problems.append(f"{spot}: {path} looks like a file holding secrets, so it can't be cited.")
            elif path and repos.try_git(repo["locator"], "cat-file", "-e", f"{sha}:{path}") is None:
                problems.append(f"{spot}: there's no {path} in {c['repo']} at {c['commit']}.")
            rows.append({**empty, "source_id": repo["id"], "commit_sha": sha, "path": path})
        else:
            target = reader.page(c["page"])
            if target is None and c["page"] != page["id"]:
                problems.append(f"{spot}: there's no wiki page {c['page']}.")
            elif c.get("section") and target is not None and c["section"] not in section_ids(db, target):
                problems.append(f"{spot}: page {c['page']} has no section {c['section']}.")
            rows.append({**empty, "page_id": c["page"], "section_id": c.get("section")})
            links.append(c["page"])
    for target, _ in WIKI_LINK.findall(block["text"]):
        if reader.page(target) is None and target != page["id"]:
            problems.append(f"{where}.text links to [[{target}]], but there's no such page. Use an id from the catalog.")
        links.append(target)
    return rows, sorted(set(links))


def check_diagram(db, reader, page, block, where, problems):
    """A diagram block as a statement to store: checked, laid out (for its warnings), with its words for search."""
    d = block["diagram"]
    found = diagrams.check(d, f"{where}.diagram")
    problems += found
    cites, links = check_cites(db, reader, page, {"text": "", "cites": block.get("cites", []) + diagrams.element_cites(d)},
                               where, problems)
    for target in diagrams.page_links(d):
        if reader.page(target) is None and target != page["id"]:
            problems.append(f"{where}.diagram links to page {target}, which doesn't exist.")
    stored = dict(d)
    if not found:
        stored["warnings"] = diagrams.render(d)["warnings"]
    return {"text": diagrams.plain_text(d)[:2000], "style": "paragraph", "cites": cites,
            "links": sorted(set(links) | set(diagrams.page_links(d))), "kind": "diagram", "block": stored}


def check_image(db, image, where, problems):
    """An image block: a documentation image in a repository Claude may read, at a commit."""
    repo = repos.by_name(db, image["repo"])
    sha = repos.resolve(repo["locator"], image["commit"]) if repo else None
    path = image["path"].strip("/")
    if sha is None:
        problems.append(f"{where}.image: {image['repo']} at {image['commit']} isn't a repository and commit you can read.")
    else:
        data, why = repos.image_at(repo["locator"], sha, path)
        if data is None:
            problems.append(f"{where}.image: {why}")
    caption = " ".join(image.get("caption", "").split())
    if HTML_TAG.search(caption):
        problems.append(f"{where}.image.caption is plain text.")
    empty = {"claim_id": None, "event_id": None, "page_id": None, "section_id": None}
    cites = [{**empty, "source_id": repo["id"] if repo else None, "commit_sha": sha, "path": path}]
    return {"text": caption or path, "style": "paragraph", "cites": cites, "links": [], "kind": "image",
            "block": {"commit": sha, "path": path, "caption": caption}}


def section_ids(db, page):
    v = current(db, page["id"]) if page["stored"] else None
    written = {r[0] for r in db.execute("SELECT section_id FROM wiki_sections WHERE page_id = ? AND version = ?",
                                        (page["id"], v["version"]))} if v else set()
    return written | set(WIKI_COMPILED[page["kind"]]) | set(WIKI_GENERATED[page["kind"]])


def new_page(db, new, problems):
    kind, title = new["kind"], " ".join(new["title"].split())
    if len(title) > TITLE_CHARS or HTML_TAG.search(title):
        problems.append(f"new.title is plain text, at most {TITLE_CHARS} characters.")
    email = new.get("email", "").strip().lower() or None
    if email:
        existing = db.execute("SELECT id FROM wiki_pages WHERE email = ?", (email,)).fetchone()
        if existing:
            problems.append(f"There's already a page for {email}: {existing['id']}. Update it with page and base_version.")
    base = slug(title)
    if kind == "topic":
        existing = db.execute("SELECT id, title FROM wiki_pages WHERE kind = 'topic' AND (id = ? OR lower(title) = ?)",
                              (base, title.lower())).fetchone()
        if existing:
            problems.append(f"There's already a topic page {existing['id']} ('{existing['title']}'). Update it instead.")
    taken = {r[0] for r in db.execute("SELECT id FROM wiki_pages UNION SELECT id FROM projects")}
    page_id, n = base, 2
    while page_id in taken or page_id.removesuffix("-project") in taken - {page_id}:  # leave projects their page ids
        page_id, n = f"{base}-{n}", n + 1
    return {"id": page_id, "kind": kind, "title": title, "project_id": None, "email": email, "created_at": None,
            "stored": False}


def propose_wiki_update(db, args):
    reader = Reader(db)
    problems = []
    if "new" in args:
        page = new_page(db, args["new"], problems)
    else:
        page = reader.page(args["page"])
        if page is None:
            raise Refused(f"There's no wiki page {args['page']}. Call get_wiki_page without page for the catalog, "
                          "or pass new to create a person or topic page.")
    kind = page["kind"]
    before = current(db, page["id"]) if page["stored"] else None
    at_version = before["version"] if before else 0
    if "page" in args and args["base_version"] != at_version:
        raise Refused(f"Page {page['id']} is at version {at_version}, not {args['base_version']}: it changed since you "
                      "read it. Read it again with get_wiki_page and make your change on top of what's there now.")

    sent = {}
    for i, section in enumerate(args.get("sections", [])):
        where, sid = f"sections[{i}]", section["id"]
        if sid not in WIKI_COMPILED[kind] and section["blocks"] and not section.get("heading", "").strip():
            problems.append(f"{where}.heading is required: '{sid}' isn't one of a {kind} page's standard sections "
                            f"({', '.join(WIKI_COMPILED[kind])}).")
        if sid in WIKI_GENERATED[kind]:
            problems.append(f"{where}.id '{sid}' is built by the layer on {kind} pages, so it can't be written.")
        statements = []
        for j, block in enumerate(section["blocks"]):
            spot = f"{where}.blocks[{j}]"
            if "diagram" in block:
                statements.append(check_diagram(db, reader, page, block, spot, problems))
            elif "image" in block:
                statements.append(check_image(db, block["image"], spot, problems))
            else:
                cites, links = check_cites(db, reader, page, block, spot, problems)
                statements.append({"text": block["text"].strip(), "style": block.get("style", "paragraph"),
                                   "cites": cites, "links": links, "kind": None, "block": None})
        sent[sid] = {"id": sid, "heading": section.get("heading", "").strip() or None,
                     "summary": section.get("summary", "").strip() or None, "statements": statements}

    built = {}
    for i, item in enumerate(args.get("built_from", [])):
        repo = repos.by_name(db, item["repo"])
        sha = repos.resolve(repo["locator"], item["commit"]) if repo else None
        if sha is None:
            problems.append(f"built_from[{i}]: {item['repo']} at {item['commit']} isn't a repository and commit you can read.")
        else:
            built[str(repo["id"])] = sha

    # The new version: the sections sent replace theirs, an empty one removes it, the others carry over.
    old = stored_sections(db, page["id"], at_version) if before else []
    merged, removed = [], []
    for s in old:
        if s["id"] not in sent:
            merged.append(s)
    for sid, s in sent.items():
        if not s["statements"]:
            removed.append(sid)
            continue
        previous = next((o for o in old if o["id"] == sid), None)
        s["heading"] = s["heading"] or (previous or {}).get("heading") or WIKI_COMPILED[kind].get(sid, sid)
        merged.append(s)
    standard = list(WIKI_COMPILED[kind])
    position = {s["id"]: n for n, s in enumerate(old)}
    merged.sort(key=lambda s: (0, standard.index(s["id"])) if s["id"] in standard
                else (1, position.get(s["id"], len(old) + list(sent).index(s["id"]) if s["id"] in sent else 0)))
    custom = [s["id"] for s in merged if s["id"] not in standard]
    if len(custom) > CUSTOM_SECTIONS:
        problems.append(f"The page would have {len(custom)} sections of your own; at most {CUSTOM_SECTIONS}. Fold some together.")
    chars = sum(len(st["text"]) for s in merged for st in s["statements"] if not st["kind"])
    drawn = [st["block"]["id"] for s in merged for st in s["statements"] if st["kind"] == "diagram"]
    if len(drawn) > PAGE_DIAGRAMS:
        problems.append(f"The page would have {len(drawn)} diagrams; at most {PAGE_DIAGRAMS}. Keep the ones that explain most.")
    if len(set(drawn)) != len(drawn):
        problems.append("Two diagrams on the page share an id: " + ", ".join(sorted({d for d in drawn if drawn.count(d) > 1}))
                        + ". Each diagram's id is unique on its page.")
    if chars > PAGE_CHARS:
        problems.append(f"The page would hold {chars} characters of compiled text; at most {PAGE_CHARS}. Say it shorter, "
                        "or move detail to a topic page.")
    if kind == "topic":
        projects = {t for s in merged for st in s["statements"] for t in st["links"]
                    for p in [reader.page(t)] if p and p["kind"] == "project"}
        if len(projects) < 2:
            problems.append("A topic page is for a theme across projects: link at least two project pages, with "
                            "[[project]] in a statement or a page citation.")
    if problems:
        raise Refused("these parts don't check out:\n" + "\n".join(f"- {p}" for p in problems))

    new_statements = [st for sid, s in sent.items() for st in s["statements"]]
    verdicts = [reader.judge(st["cites"]) for st in new_statements]
    labels = Counter(v["label"] for v in verdicts if v)
    warnings = []
    if labels["unconfirmed"]:
        warnings.append(f"{labels['unconfirmed']} of the statements you sent rest only on unconfirmed claims or events: "
                        "they show as unconfirmed, and disappear if those expire unconfirmed.")
    if chars > PAGE_CHARS * 0.8:
        warnings.append(f"The page holds {chars} of its {PAGE_CHARS} characters.")
    cited_repos = {str(c["source_id"]) for st in new_statements for c in st["cites"] if c["source_id"]}
    known = set(json.loads(before["built_from"]) if before else {}) | set(built)
    if cited_repos - known:
        warnings.append("You cited a repository without passing it in built_from, so the page can't tell when it goes "
                        "stale. Pass built_from with the head commit read_repo showed.")
    summary = {"page": page["id"], "version": at_version + 1, "created": not page["stored"],
               "sections_saved": [sid for sid in sent if sid not in removed], "sections_removed": removed,
               "statements_sent": len(new_statements), "labels": dict(labels), "page_chars": chars,
               "page_budget": PAGE_CHARS}
    sent_diagrams = [st["block"] for st in new_statements if st["kind"] == "diagram"]
    if sent_diagrams:
        summary["layout"] = [{"diagram": b["id"], "warnings": b.get("warnings", [])} for b in sent_diagrams]
        pictures = [diagrams.preview({k: v for k, v in b.items() if k != "warnings"}) for b in sent_diagrams]
        summary["_images"] = [{"data": png, "mimeType": "image/png"} for png in pictures if png]
        summary["previews"] = ("each diagram's preview follows, in order; look at it before you're done"
                               if summary["_images"] else "no previews: the layer can't draw them here (rsvg-convert "
                               "isn't installed), so rely on the layout warnings")
    if warnings:
        summary["warnings"] = warnings
    if args.get("dry_run"):
        return {"dry_run": True, "saved": False, **summary,
                "note": "Nothing was saved. Call again without dry_run to save it."}

    def work():
        now = store.now()
        again = current(db, page["id"])
        if (again["version"] if again else 0) != at_version:
            raise Refused(f"Page {page['id']} changed while you were writing. Read it again with get_wiki_page.")
        if not db.execute("SELECT 1 FROM wiki_pages WHERE id = ?", (page["id"],)).fetchone():
            db.execute("INSERT INTO wiki_pages (id, kind, title, project_id, email, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                       (page["id"], kind, page["title"], page["project_id"], page["email"], now))
        version = at_version + 1
        key_terms = args["key_terms"] if "key_terms" in args else json.loads(before["key_terms"]) if before else []
        summary_text = args["summary"].strip() if "summary" in args else before["summary"] if before else None
        built_from = {**(json.loads(before["built_from"]) if before else {}), **built}
        seq = db.execute("INSERT INTO wiki_versions (page_id, version, summary, key_terms, built_from, written_by, reason,"
                         " written_at) VALUES (?, ?, ?, ?, ?, 'claude', ?, ?)",
                         (page["id"], version, summary_text, json.dumps(key_terms, ensure_ascii=False),
                          json.dumps(built_from), args["reason"].strip(), now)).lastrowid
        if before:
            db.execute("DELETE FROM wiki_fts WHERE rowid IN (SELECT st.seq FROM wiki_statements st JOIN wiki_sections s"
                       " ON s.seq = st.section_seq WHERE s.page_id = ? AND s.version = ?)", (page["id"], at_version))
            db.execute("DELETE FROM wiki_pages_fts WHERE rowid = ?", (before["seq"],))
        for n, s in enumerate(merged):
            section_seq = db.execute("INSERT INTO wiki_sections (page_id, version, section_id, position, heading, summary)"
                                     " VALUES (?, ?, ?, ?, ?, ?)",
                                     (page["id"], version, s["id"], n, s["heading"], s["summary"])).lastrowid
            for m, st in enumerate(s["statements"]):
                statement_seq = db.execute("INSERT INTO wiki_statements (section_seq, position, style, text, kind, block)"
                                           " VALUES (?, ?, ?, ?, ?, ?)",
                                           (section_seq, m, st["style"], st["text"], st["kind"],
                                            json.dumps(st["block"], ensure_ascii=False) if st["block"] else None)).lastrowid
                for k, c in enumerate(st["cites"]):
                    db.execute("INSERT INTO wiki_citations (statement_seq, position, claim_id, event_id, source_id, commit_sha,"
                               " path, page_id, section_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (statement_seq, k, c["claim_id"], c["event_id"], c["source_id"], c["commit_sha"], c["path"],
                                c["page_id"], c["section_id"]))
                for target in st["links"]:
                    db.execute("INSERT OR IGNORE INTO wiki_links VALUES (?, ?)", (statement_seq, target))
                db.execute("INSERT INTO wiki_fts (rowid, heading, text) VALUES (?, ?, ?)", (statement_seq, s["heading"], plain(st["text"])))
        db.execute("INSERT INTO wiki_pages_fts (rowid, title, key_terms, summary) VALUES (?, ?, ?, ?)",
                   (seq, page["title"], " ".join(key_terms), summary_text or ""))
        audit(db, "propose", "wiki_page", page["id"])
        return summary

    return transaction(db, work)


WIKI_READS = {"get_wiki_page": get_wiki_page}
WIKI_WRITES = {"propose_wiki_update": propose_wiki_update}
