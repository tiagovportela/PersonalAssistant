"""Checks the knowledge wiki (docs/knowledge_wiki.md): read_repo, get_wiki_page and propose_wiki_update,
the wiki in search, get_project and get_metrics, and retention. Against temporary Git repositories the
real collectors gathered, calling tools the way the service does (Layer.call_tool).

Run: python3 -I service/test_wiki.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pwi-wiki-"))
os.environ.update({"HOME": str(TMP), "XDG_DATA_HOME": str(TMP / "data"), "XDG_CONFIG_HOME": str(TMP / "config"),
                   "CLAUDE_CONFIG_DIR": str(TMP / "claude"), "GIT_CONFIG_GLOBAL": str(TMP / "gitconfig"),
                   "GIT_CONFIG_NOSYSTEM": "1"})
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]

import collect  # noqa: E402
import evaluation  # noqa: E402
import handlers  # noqa: E402
import paths  # noqa: E402
import retention  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402

TODAY = date.today()
D1, D2 = (TODAY - timedelta(days=3)).isoformat(), (TODAY - timedelta(days=2)).isoformat()
NOW = store.now()
TOKEN = "ghp_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6"


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def sh(cwd, *args, **env):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, env={**os.environ, **env}).stdout.decode().strip()


def write(repo, files, subject, day):
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())
    sh(repo, "git", "add", "-A")
    stamp = f"{day}T10:00:00+00:00"
    sh(repo, "git", "commit", "-q", "-m", subject, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
    return sh(repo, "git", "rev-parse", "HEAD")


def add_claim(db, claim_id, kind, text, project, status="proposed", owner=None, counterparty=None, due_at=None,
              evidence=()):
    db.execute("INSERT INTO claims VALUES (?, ?, ?)", (claim_id, kind, NOW))
    db.execute("INSERT INTO claim_versions (claim_id, version, status, text, project_id, about_day, due_at, owner,"
               " counterparty, method, changed_by, created_at) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, 'claude', ?, ?)",
               (claim_id, status, text, project, D1, due_at, owner, counterparty,
                "me" if status == "supported" else "claude", NOW))
    for event_id in evidence:
        ev = db.execute("INSERT INTO evidence (event_id, created_at) VALUES (?, ?)", (event_id, NOW)).lastrowid
        db.execute("INSERT INTO claim_evidence VALUES (?, 1, ?)", (claim_id, ev))


def new_status(db, claim_id, status):
    v = db.execute("SELECT * FROM current_claims WHERE id = ?", (claim_id,)).fetchone()
    db.execute("INSERT INTO claim_versions (claim_id, version, status, text, project_id, about_day, owner, counterparty,"
               " method, changed_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'claude', 'me', ?)",
               (claim_id, v["version"] + 1, status, v["text"], v["project_id"], v["about_day"], v["owner"],
                v["counterparty"], store.utc(time.time() + 1)))


def main():
    layer = handlers.Layer(paths.STORE_PATH)

    def call(name, args=None):
        result = layer.call_tool(name, args or {})
        text = result["content"][0]["text"]
        if result["isError"]:
            return {"error": text}
        return json.loads(text.split("\n", 1)[1].rsplit("\n", 1)[0])

    os.umask(0o077)
    store.create_or_check(paths.STORE_PATH)
    repos = {name: TMP / "Projects" / name for name in ("atlas", "beta", "vault")}
    for repo in repos.values():
        repo.mkdir(parents=True)
        sh(repo, "git", "init", "-q", "-b", "main")
        sh(repo, "git", "config", "user.email", "me@example.com")
        sh(repo, "git", "config", "user.name", "Me")
    first = write(repos["atlas"], {
        "README.md": f"# Atlas\n\nAtlas renders offline maps for field teams.\n\nDeploy token: {TOKEN}\n",
        "CLAUDE.md": "Run the tests with make test.\n",
        "package.json": '{"name": "atlas", "dependencies": {"maplibre-gl": "4.7.1"}}\n',
        "docs/architecture.md": "Tiles are cached in SQLite on the device; the server only builds them.\n",
        "docs/decisions/0001-sqlite.md": "We chose SQLite for the tile cache.\n",
        ".env": "API_KEY=do-not-read-this-value\n",
        "deploy/secrets.yaml": "password: do-not-read-this-either\n",
        "logo.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(64),
        "src/app.py": "print('atlas')\n",
        "src/tiles/cache.py": "CACHE = 'sqlite'\n",
    }, "Initial Atlas", D1)
    write(repos["beta"], {"README.md": "# Beta\n\nBeta also renders maps.\n"}, "Initial Beta", D1)
    write(repos["vault"], {"README.md": "# Vault\n\nAcquisition plans.\n"}, "Initial Vault", D1)

    db = store.connect(paths.STORE_PATH)
    sources.add_path(db, TMP / "Projects")
    collect.run(paths.STORE_PATH)
    events = {r["title"]: r["id"] for r in db.execute("SELECT id, title FROM events WHERE type = 'git.commit'")}
    add_claim(db, "clm_ver", "fact", "Atlas caches tiles on the device", "atlas", status="supported",
              evidence=[events["Initial Atlas"]])
    add_claim(db, "clm_dec", "decision", "Use SQLite for the tile cache", "atlas", evidence=[events["Initial Atlas"]])
    add_claim(db, "clm_disp", "decision", "Drop the server", "atlas", status="disputed")
    add_claim(db, "clm_com", "commitment", "Send Ana the tile cache design", "atlas", owner="me",
              counterparty="ana@example.com", due_at=D2)
    add_claim(db, "clm_gone", "fact", "Atlas started as a hack week project", "atlas")
    add_claim(db, "clm_vault", "decision", "Buy the competitor", "vault")
    db.execute("INSERT INTO labels VALUES ('project', 'vault', 'confidential', 'me', ?)", (NOW,))

    # read_repo -------------------------------------------------------------------------
    overview = call("read_repo", {"project": "atlas"})
    head = overview["head"]["commit"]
    check("read_repo's overview has the head commit, README, CLAUDE.md, manifests, docs and tree",
          head == first and overview["branch"] == "main" and "offline maps" in overview["readme"]["text"]
          and [f["path"] for f in overview["agent_files"]] == ["CLAUDE.md"]
          and [f["path"] for f in overview["manifests"]] == ["package.json"]
          and {d["path"] for d in overview["docs"]} == {"docs/architecture.md", "docs/decisions/0001-sqlite.md"}
          and any(t["path"] == "src/" and "tiles/" in t["entries"] for t in overview["tree"]))
    check("read_repo redacts secrets in what it returns", TOKEN not in json.dumps(overview)
          and "[REDACTED]" in overview["readme"]["text"])
    check("the overview leaves out files that look like secrets, and says how to cite and what was read",
          ".env" not in [t["path"] for t in overview["tree"]]
          and "secrets.yaml" not in next(t for t in overview["tree"] if t["path"] == "deploy/")["entries"]
          and overview["cite_as"] == {"repo": "atlas", "commit": first[:12]}
          and overview["built_from"] == {"repo": "atlas", "commit": first[:12]})
    doc = call("read_repo", {"project": "atlas", "path": "docs/architecture.md"})
    check("read_repo reads one committed file at the head, with how to cite it",
          doc["text"].startswith("Tiles are cached") and doc["commit"] == first
          and doc["cite_as"] == {"repo": "atlas", "commit": first[:12], "path": "docs/architecture.md"})
    check("read_repo refuses files that look like secrets, even committed ones",
          call("read_repo", {"project": "atlas", "path": ".env"})["found"] is False
          and "secrets" in call("read_repo", {"project": "atlas", "path": "deploy/secrets.yaml"})["gaps"][0]
          and "do-not-read" not in json.dumps(call("read_repo", {"project": "atlas", "path": "deploy"})))
    check("read_repo doesn't return binary files, and lists a folder's files",
          "binary" in call("read_repo", {"project": "atlas", "path": "logo.png"})["gaps"][0]
          and {e["path"] for e in call("read_repo", {"project": "atlas", "path": "src"})["folder"]}
          == {"src/app.py", "src/tiles/"})
    (repos["atlas"] / "notes.md").write_text("Untracked notes\n")
    (repos["atlas"] / "docs" / "architecture.md").write_text("Edited but not committed\n")
    check("read_repo reads committed files only, never the working tree",
          call("read_repo", {"project": "atlas", "path": "notes.md"})["found"] is False
          and call("read_repo", {"project": "atlas", "path": "docs/architecture.md"})["text"].startswith("Tiles are cached"))
    sh(repos["atlas"], "git", "checkout", "--", "docs/architecture.md")
    (repos["atlas"] / "notes.md").unlink()
    check("read_repo refuses a confidential project's repository, and unknown projects",
          call("read_repo", {"project": "vault"})["found"] is False
          and call("read_repo", {"project": "nope"})["found"] is False
          and "Acquisition" not in json.dumps(call("read_repo", {"project": "vault", "path": "README.md"})))
    audited = [r["item_id"] for r in db.execute("SELECT item_id FROM audit_log WHERE action = 'read_repo'")]
    check("each read goes into the audit trail as repository, commit and path, never the content",
          len(audited) >= 5 and any(i.endswith(":docs/architecture.md") for i in audited)
          and not any("Tiles" in i for i in audited))

    # Writing a page ------------------------------------------------------------------------
    catalog = call("get_wiki_page")
    check("the catalog lists every project's page, unwritten, and never a confidential project's",
          {(p["page"], p["compiled"]) for p in catalog["pages"]} == {("atlas", False), ("beta", False)})
    readme = {"repo": "atlas", "commit": first[:12], "path": "README.md"}
    update = {"page": "atlas", "base_version": 0, "reason": "first version",
              "summary": "Offline maps for field teams.", "key_terms": ["mapas offline", "tile cache"],
              "built_from": [{"repo": "atlas", "commit": first[:12]}],
              "sections": [
                  {"id": "overview", "summary": "What Atlas is.", "blocks": [
                      {"text": "Atlas renders **offline maps** for field teams.", "cites": [readme]},
                      {"text": "Tiles are cached on the device.", "cites": [readme, {"claim_id": "clm_ver"}]},
                      {"text": "It started in a hack week.", "cites": [{"claim_id": "clm_gone"}]}]},
                  {"id": "status", "blocks": [{"text": "The tile cache uses SQLite.", "style": "bullet",
                                               "cites": [{"claim_id": "clm_dec"}]}]},
                  {"id": "why", "blocks": [{"text": "Dropping the server is still open.", "cites": [{"claim_id": "clm_disp"}]}]},
                  {"id": "setup", "heading": "Setting it up", "blocks": [
                      {"text": "Run the tests with `make test`.", "cites": [{"repo": "atlas", "commit": first[:12],
                                                                             "path": "CLAUDE.md"}]}]}]}
    dry = call("propose_wiki_update", {**update, "dry_run": True})
    check("dry_run checks everything and saves nothing",
          dry["dry_run"] is True and dry["saved"] is False and dry["version"] == 1
          and call("get_wiki_page", {"page": "atlas"})["version"] == 0)
    saved = call("propose_wiki_update", update)
    check("a first version is saved, with what it holds and a warning about unconfirmed statements",
          saved["version"] == 1 and saved["created"] is True
          and saved["sections_saved"] == ["overview", "status", "why", "setup"]
          and saved["labels"] == {"repo": 2, "verified": 1, "unconfirmed": 2, "disputed": 1}
          and "unconfirmed" in saved["warnings"][0])
    page = call("get_wiki_page", {"page": "atlas"})
    ids = [s["id"] for s in page["sections"]]
    check("the outline lists compiled sections first, then the generated ones, with summaries and labels",
          ids == ["overview", "status", "why", "setup", "decisions", "commitments", "open-work", "people",
                  "where-it-lives", "activity"]
          and page["sections"][0]["summary"] == "What Atlas is." and page["sections"][0]["labels"] == {"repo": 1, "verified": 1,
                                                                                                    "unconfirmed": 1}
          and page["not_written"] == ["how-it-works", "lessons"]
          and page["built_from"] == [{"repo": "atlas", "commit": first[:12]}] and page["stale"] == {"is_stale": False})
    full = call("get_wiki_page", {"page": "atlas", "sections": ["overview", "why", "commitments"]})
    overview_blocks = full["content"][0]["blocks"]
    check("a statement's label is its best citation: verified, then repo, then unconfirmed; disputed wins",
          [b["label"] for b in overview_blocks] == ["repo", "verified", "unconfirmed"]
          and full["content"][1]["blocks"][0]["label"] == "disputed"
          and overview_blocks[1]["cites"] == [{"repo": "atlas", "commit": first[:12], "path": "README.md"},
                                              {"claim_id": "clm_ver", "label": "verified"}])
    check("generated sections come from the store: open commitments, both ways",
          full["content"][2]["source"] == "generated"
          and [(c["claim_id"], c["direction"]) for c in full["content"][2]["items"]] == [("clm_com", "mine")])

    def problems(**changes):
        result = call("propose_wiki_update", {**update, "base_version": 1, **changes})
        return result.get("error", "")
    check("an update is refused if the page changed since it was read",
          "at version 1, not 0" in call("propose_wiki_update", update).get("error", ""))
    statement = lambda cites, text="Some fact.": [{"id": "lessons", "blocks": [{"text": text, "cites": cites}]}]  # noqa: E731
    check("citations must exist and be visible: claims, events, commits, files and pages",
          "no claim clm_nope" in problems(sections=statement([{"claim_id": "clm_nope"}]))
          and "no claim clm_vault" in problems(sections=statement([{"claim_id": "clm_vault"}]))
          and "isn't an event" in problems(sections=statement([{"event_id": "git:commit:feedface"}]))
          and "has no commit" in problems(sections=statement([{"repo": "atlas", "commit": "deadbeef"}]))
          and "no repository vault" in problems(sections=statement([{"repo": "vault", "commit": first[:12]}]))
          and "no missing.md" in problems(sections=statement([{"repo": "atlas", "commit": first[:12], "path": "missing.md"}]))
          and "secrets" in problems(sections=statement([{"repo": "atlas", "commit": first[:12], "path": ".env"}]))
          and "no wiki page nowhere" in problems(sections=statement([readme, {"page": "nowhere"}])))
    check("links must point to pages that exist, and HTML is refused before anything is checked",
          "[[nowhere]]" in problems(sections=statement([readme], "See [[nowhere]].")) and
          "has HTML" in problems(sections=statement([readme], "<b>bold</b>")))
    check("generated sections can't be written, and the page has a size budget",
          "built by the layer" in problems(sections=[{"id": "decisions", "blocks": []}])
          and "at most 12000" in problems(sections=[{"id": f"part-{n}", "heading": f"Part {n}", "blocks": [
              {"text": "x" * 600, "cites": [readme]} for _ in range(5)]} for n in range(5)]))
    check("a confidential project's page can't be read or written",
          call("get_wiki_page", {"page": "vault"})["found"] is False
          and "no wiki page vault" in call("propose_wiki_update", {**update, "page": "vault"}).get("error", ""))

    second = call("propose_wiki_update", {"page": "atlas", "base_version": 1, "reason": "status changed",
                                          "sections": [{"id": "status", "blocks": [
                                              {"text": "Offline maps ship to field teams next month.",
                                               "cites": [{"claim_id": "clm_dec"}]}]},
                                                       {"id": "why", "blocks": []}]})
    page = call("get_wiki_page", {"page": "atlas", "sections": ["overview", "status"]})
    check("an update replaces only the sections sent; an empty one removes its section",
          second["version"] == 2 and second["sections_removed"] == ["why"]
          and [s["id"] for s in page["sections"] if s["source"] == "compiled"] == ["overview", "status", "setup"]
          and page["content"][1]["blocks"][0]["text"].startswith("Offline maps ship")
          and len(page["content"][0]["blocks"]) == 3)

    # Labels and hiding at read time ----------------------------------------------------------
    new_status(db, "clm_dec", "supported")
    check("confirming a claim makes the statements citing it verified, with no rewrite",
          call("get_wiki_page", {"page": "atlas", "sections": ["status"]})["content"][0]["blocks"][0]["label"] == "verified")
    new_status(db, "clm_gone", "retracted")
    db.execute("INSERT INTO labels VALUES ('claim', 'clm_ver', 'confidential', 'me', ?)", (NOW,))
    blocks = call("get_wiki_page", {"page": "atlas", "sections": ["overview"]})["content"][0]["blocks"]
    check("a statement on a retracted claim disappears, and one citing anything confidential is hidden whole",
          [b["text"] for b in blocks] == ["Atlas renders **offline maps** for field teams."])
    hidden = call("get_wiki_page", {"page": "atlas", "sections": ["overview"]})
    check("Claude sees no count of what's hidden", "hidden" not in json.dumps(hidden)
          and "Tiles are cached on the device" not in json.dumps(hidden))
    db.execute("DELETE FROM labels WHERE item_id = 'clm_ver'")

    # Staleness ---------------------------------------------------------------------------------
    later = write(repos["atlas"], {"docs/architecture.md": "Tiles are cached in SQLite and pre-warmed at night.\n"},
                  "Pre-warm the tile cache", D2)
    stale = call("get_wiki_page", {"page": "atlas"})["stale"]
    check("a page is stale when its repository moved on, and says how far, docs included",
          stale["is_stale"] is True and any("1 commits on atlas main since" in w and "1 of them in its docs" in w
                                            for w in stale["why"])
          and next(p for p in call("get_wiki_page")["pages"] if p["page"] == "atlas")["stale"] is True)
    since = call("read_repo", {"project": "atlas", "since": first[:12]})
    check("read_repo lists the commits since a page's built_from, and which touched docs",
          since["count"] == 1 and since["commits"][0]["subject"] == "Pre-warm the tile cache"
          and since["commits"][0]["touches_docs"] is True and since["built_from"]["commit"] == later[:12])
    add_claim(db, "clm_new", "blocker", "Night pre-warming drains batteries", "atlas")
    check("new claims about the project also make its page stale",
          any("claims about the project" in w for w in call("get_wiki_page", {"page": "atlas"})["stale"]["why"]))

    # Person and topic pages -------------------------------------------------------------------
    person = call("propose_wiki_update", {"new": {"kind": "person", "title": "Ana  Silva", "email": "Ana@Example.com"},
                                          "reason": "she reviews Atlas", "summary": "Reviews Atlas.",
                                          "sections": [{"id": "role", "blocks": [
                                              {"text": "Ana reviews the tile cache design for [[atlas]].",
                                               "cites": [{"claim_id": "clm_com"}]}]}]})
    ana = call("get_wiki_page", {"page": "ana-silva", "sections": ["commitments", "projects"]})
    check("a person page is made from their name, one per email, with commitments both ways",
          person["page"] == "ana-silva" and person["created"] is True and ana["email"] == "ana@example.com"
          and [(c["claim_id"], c["direction"]) for c in ana["content"][0]["items"]] == [("clm_com", "mine")]
          and ana["content"][1]["items"] == [{"project": "atlas", "page": "atlas"}])
    check("there's one page per person",
          "already a page for ana@example.com" in call("propose_wiki_update", {
              "new": {"kind": "person", "title": "Ana S.", "email": "ana@example.com"}, "reason": "x",
              "summary": "Again."}).get("error", ""))
    beta_head = call("read_repo", {"project": "beta"})["head"]["commit"][:12]
    topic_section = lambda text: [{"id": "summary", "blocks": [  # noqa: E731
        {"text": text, "cites": [readme, {"repo": "beta", "commit": beta_head, "path": "README.md"}]}]}]
    check("a topic page links at least two projects",
          "at least two project pages" in call("propose_wiki_update", {
              "new": {"kind": "topic", "title": "Offline maps"}, "reason": "x",
              "sections": topic_section("Only [[atlas]] renders maps.")}).get("error", ""))
    topic = call("propose_wiki_update", {"new": {"kind": "topic", "title": "Offline maps"}, "reason": "two projects",
                                         "key_terms": ["cartografia"],
                                         "sections": topic_section("Both [[atlas]] and [[beta]] render maps.")})
    maps = call("get_wiki_page", {"page": topic["page"], "sections": ["projects"]})
    atlas = call("get_wiki_page", {"page": "atlas"})
    check("a topic page lists the projects it links, and the projects show it links to them",
          topic["page"] == "offline-maps" and [i["page"] for i in maps["content"][0]["items"]] == ["atlas", "beta"]
          and {p["page"] for p in atlas["linked_from"]} == {"ana-silva", "offline-maps"})
    check("the catalog filters by kind and by project",
          [p["page"] for p in call("get_wiki_page", {"kind": "person"})["pages"]] == ["ana-silva"]
          and {p["page"] for p in call("get_wiki_page", {"project": "beta"})["pages"]} == {"beta", "offline-maps"})

    # Search, get_project, metrics -------------------------------------------------------------
    hits = [r for r in call("search", {"query": "pre-warmed field teams"})["results"] if r["item_type"] == "wiki"]
    check("search finds wiki sections, one result per section, with labels",
          any(h["page"] == "atlas" and h["section"] == "overview" and h["labels"] for h in hits))
    check("search finds a page by its key terms, accents ignored",
          any(r["item_type"] == "wiki" and r["page"] == "offline-maps"
              for r in call("search", {"query": "cartografía", "kinds": ["wiki"]})["results"]))
    db.execute("INSERT INTO labels VALUES ('claim', 'clm_dec', 'confidential', 'me', ?)", (NOW,))
    check("search never shows a statement Claude may not see",
          not any(r["item_type"] == "wiki" for r in call("search", {"query": "ship next month", "kinds": ["wiki"]})["results"]))
    db.execute("DELETE FROM labels WHERE item_id = 'clm_dec'")
    missed = call("search", {"query": f"zebra quokka {TOKEN}"})
    misses = db.execute("SELECT * FROM search_misses ORDER BY id").fetchall()
    check("a search that finds nothing is recorded, redacted, including the one above that found only hidden text",
          missed["found"] is False and [json.loads(m["kinds"]) for m in misses][0] == ["wiki"]
          and len(misses) == 2 and TOKEN not in misses[1]["query"] and "zebra" in misses[1]["query"])
    project = call("get_project", {"project": "atlas"})
    check("get_project shows the project's wiki page: written sections, and whether it's stale",
          project["wiki"]["page"] == "atlas" and project["wiki"]["compiled"] is True
          and [s["id"] for s in project["wiki"]["sections"]] == ["overview", "status", "setup"]
          and project["wiki"]["stale"]["is_stale"] is True
          and call("get_project", {"project": "beta"})["wiki"]["compiled"] is False)
    wiki_metrics = call("get_metrics")["wiki"]
    check("get_metrics counts pages, labels and search misses",
          wiki_metrics["pages"] == {"project": 2, "person": 1, "topic": 1} and wiki_metrics["written"] == 3
          and wiki_metrics["search_misses"]["count"] == 2 and wiki_metrics["statements_by_label"]["repo"] >= 3)

    # Leaks, retention ---------------------------------------------------------------------------
    _, leaks = evaluation.leak_check(paths.STORE_PATH, db, [D1, D2], {"atlas", "beta"}, ["Buy the competitor", "maps"])
    check("the evaluation's leak check covers the wiki, and finds nothing confidential", leaks == [])
    future = time.time() + 100 * 86400
    counts = retention.run(paths.STORE_PATH, now=future)
    versions = [r[0] for r in db.execute("SELECT version FROM wiki_versions WHERE page_id = 'atlas'")]
    check("retention deletes past wiki versions and old search misses, never a page's current version",
          versions == [2] and counts["wiki_versions"] == 1 and counts["search_misses"] == 2
          and db.execute("SELECT COUNT(*) FROM wiki_pages").fetchone()[0] == 3)
    check("foreign keys still hold, and the wiki's search indexes are consistent",
          db.execute("PRAGMA foreign_key_check").fetchall() == []
          and db.execute("INSERT INTO wiki_fts (wiki_fts) VALUES ('integrity-check')").rowcount is not None)
    db.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
