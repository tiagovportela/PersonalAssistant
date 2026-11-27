"""Checks the wiki's static site (service/wiki_site.py): what it builds, that only code writes HTML and every
piece of text is escaped, that confidential and hidden items never reach it, and that it rebuilds when the store
changes. Against data the real collectors gathered from temporary repositories, one of them named with markup.

Run: python3 -I service/test_wiki_site.py
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pwi-site-"))
os.environ.update({"HOME": str(TMP), "XDG_DATA_HOME": str(TMP / "data"), "XDG_CONFIG_HOME": str(TMP / "config"),
                   "CLAUDE_CONFIG_DIR": str(TMP / "claude"), "GIT_CONFIG_GLOBAL": str(TMP / "gitconfig"),
                   "GIT_CONFIG_NOSYSTEM": "1"})
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]

import collect  # noqa: E402
import handlers  # noqa: E402
import paths  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402
import wiki_site  # noqa: E402

D1 = (date.today() - timedelta(days=3)).isoformat()
NOW = store.now()
EVIL = '<script>alert(1)</script>"><img src=x onerror=alert(2)>'


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def sh(cwd, *args, **env):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, env={**os.environ, **env}).stdout.decode().strip()


def add_claim(db, claim_id, kind, text, project, status="proposed", **extra):
    db.execute("INSERT INTO claims VALUES (?, ?, ?)", (claim_id, kind, NOW))
    db.execute("INSERT INTO claim_versions (claim_id, version, status, text, project_id, about_day, due_at, owner,"
               " counterparty, method, changed_by, created_at) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, 'claude', ?, ?)",
               (claim_id, status, text, project, D1, extra.get("due_at"), extra.get("owner"), extra.get("counterparty"),
                "me" if status == "supported" else "claude", NOW))


def site_text(folder):
    return {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8") if p.suffix not in (".png", ".jpg") else ""
            for p in folder.rglob("*") if p.is_file()}


def bare_markup(markdown):
    """'<' in Markdown that a viewer could read as HTML: not escaped, not in a code span, not a link's <destination>."""
    text = re.sub(r"`[^`]*`", "", markdown)
    text = re.sub(r"\]\(<https://[^>\s]*>\)", "", text)
    return re.findall(r"(?<!\\)<", text)


def main():
    layer = handlers.Layer(paths.STORE_PATH)

    def call(name, args=None):
        result = layer.call_tool(name, args or {})
        text = result["content"][0]["text"]
        return {"error": text} if result["isError"] else json.loads(text.split("\n", 1)[1].rsplit("\n", 1)[0])

    os.umask(0o077)
    store.create_or_check(paths.STORE_PATH)
    repos = {"atlas": TMP / "Projects" / "atlas", "beta": TMP / "Projects" / "beta",
             "evil": TMP / "Projects" / "evil<b>repo", "vault": TMP / "Projects" / "vault"}
    for name, repo in repos.items():
        repo.mkdir(parents=True)
        sh(repo, "git", "init", "-q", "-b", "main")
        sh(repo, "git", "config", "user.email", "me@example.com")
        (repo / "README.md").write_text(f"# {name}\n\nRenders maps.\n\n![Map](map.png)\n")
        (repo / "map.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"not really a png, but bytes to copy")
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-q", "-m", "Initial", GIT_AUTHOR_DATE=f"{D1}T10:00:00+00:00",
           GIT_COMMITTER_DATE=f"{D1}T10:00:00+00:00")
    db = store.connect(paths.STORE_PATH)
    sources.add_path(db, TMP / "Projects")
    collect.run(paths.STORE_PATH)
    db.execute("INSERT INTO project_aliases VALUES ('github_repo', 'acme/atlas', 'atlas', 'me', ?)", (NOW,))
    db.execute("INSERT INTO project_aliases VALUES ('notion', 'javascript:alert(3)', 'atlas', 'me', ?)", (NOW,))
    add_claim(db, "clm_ver", "fact", "Atlas caches tiles on the device", "atlas", status="supported")
    add_claim(db, "clm_evil", "decision", EVIL, "atlas")
    add_claim(db, "clm_com", "commitment", "Send Ana the design", "atlas", owner="me", counterparty="ana@example.com",
              due_at=D1)
    add_claim(db, "clm_vault", "decision", "Buy the competitor quietly", "vault")
    db.execute("INSERT INTO labels VALUES ('project', 'vault', 'confidential', 'me', ?)", (NOW,))
    head = call("read_repo", {"project": "atlas"})
    readme = {**head["cite_as"], "path": "README.md"}
    saved = call("propose_wiki_update", {
        "page": "atlas", "base_version": 0, "reason": "first", "summary": "Offline maps.", "key_terms": ["mapas"],
        "built_from": [head["built_from"]],
        "sections": [{"id": "overview", "blocks": [
            {"text": "Atlas renders **offline maps**, see [[beta|Beta]] and [the spec](https://example.com/spec).",
             "cites": [readme, {"claim_id": "clm_ver"}]},
            {"text": "Tiles live in `sqlite` on the device.", "style": "bullet", "cites": [{"claim_id": "clm_ver"}]},
            {"text": "Secret detail hidden later.", "style": "bullet", "cites": [{"claim_id": "clm_evil"}]}]}]})
    check("a page to render", saved.get("version") == 1)
    tricky = 'Tom & "Jerry" say 1 < 2'
    diagram = {"id": "arch", "type": "architecture", "title": tricky, "caption": "It's <3 & more",
               "nodes": [{"id": "ui", "label": tricky, "kind": "ui", "page": "beta"}, {"id": "db", "label": "Store", "kind": "store"}],
               "edges": [{"from": "ui", "to": "db", "label": "reads & writes"}]}
    drawn = call("propose_wiki_update", {"page": "atlas", "base_version": 1, "reason": "diagram", "sections": [
        {"id": "how-it-works", "blocks": [{"diagram": diagram, "cites": [readme]},
                                         {"image": {"repo": "atlas", "commit": head["head"]["commit"][:12], "path": "map.png",
                                                    "caption": "The map, from the docs"}}]}]})
    check("and a diagram and an image on it", drawn.get("version") == 2)

    # Building ---------------------------------------------------------------------------------
    done = wiki_site.build(db)
    site = Path(done["path"])
    files = site_text(site)
    check("the site has llms.txt, its index, each page as HTML, Markdown and JSON, the statements, catalog and graph,"
          " a stylesheet, and no scripts",
          {"llms.txt", "index.html", "catalog.json", "graph.json", "statements.jsonl", "assets/site.css",
           "pages/atlas.html", "pages/atlas.md", "pages/atlas.json", "pages/beta.html", "pages/beta.md",
           "pages/evil-b-repo.html"} <= set(files) and not any(k.endswith(".js") for k in files)
          and done["pages"] == 3 and done["written"] == 1)
    check("it lives in the layer's own folder, readable only by me, and no half-built folder is left",
          site == paths.DATA_DIR / "wiki" and stat.S_IMODE(site.stat().st_mode) == 0o700
          and all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in site.rglob("*") if p.is_file())
          and not [p for p in site.parent.iterdir() if ".new-" in p.name or ".old-" in p.name])
    pages = {k: v for k, v in files.items() if k.endswith(".html")}
    check("every page has a strict CSP that lets no script run, and loads nothing from the network",
          all('http-equiv="Content-Security-Policy"' in t and "default-src 'none'" in t and "script-src" not in t
              for t in pages.values())
          and not any(re.search(r'<(script|link)[^>]+(src|href)="(https?:)?//', t) for t in pages.values()))
    check("plain HTML: the only script element is the page's JSON data block, which never runs",
          all(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", t) in ([], ['<script type="application/json" id="pwi-page">'])
              for t in pages.values()))
    everything = "\n".join(files.values())
    markdown = {k: v for k, v in files.items() if k.endswith((".md", ".txt"))}
    others = "\n".join(v for k, v in files.items() if k not in markdown)
    check("text from the store is escaped everywhere: a claim with markup, a project named with markup",
          "<script>alert" not in others and "<img src=x" not in others and "<b>repo" not in others
          and "&lt;script&gt;alert(1)&lt;/script&gt;" in files["pages/atlas.html"]
          and "evil&lt;b&gt;repo" in files["index.html"])
    check("and in the Markdown, where every '<' from the store is escaped with a backslash",
          not any(bare_markup(t) for t in markdown.values()) and "\\<script>alert(1)" in files["pages/atlas.md"]
          and "evil\\<b>repo" in files["llms.txt"])
    check("links can only be https or pages: a javascript: alias stays text",
          'href="javascript:' not in everything and "javascript:alert(3)" in files["pages/atlas.html"])
    atlas = files["pages/atlas.html"]
    check("the allowed marks become tags: bold, code, page links and https links that open safely",
          "<strong>offline maps</strong>" in atlas and "<code>sqlite</code>" in atlas
          and '<a class="wl" href="beta.html">Beta</a>' in atlas
          and '<a href="https://example.com/spec" rel="noopener noreferrer" target="_blank">the spec</a>' in atlas)
    check("each statement carries its label and citations; a cited file links to GitHub at its commit",
          'data-label="verified"' in atlas and '<span class="label verified">[verified]</span>' in atlas
          and f'href="https://github.com/acme/atlas/blob/{head["head"]["commit"][:12]}/README.md"' in atlas)
    embedded = re.search(r'<script type="application/json" id="pwi-page">(.*?)</script>', atlas, re.S).group(1)
    check("the page's data is inline and in pages/<id>.json, the same as get_wiki_page returns",
          json.loads(embedded) == json.loads(files["pages/atlas.json"])
          and json.loads(embedded)["content"][0]["blocks"][0]["label"] == "verified")
    check("generated sections render: decisions by month, commitments, where it lives",
          f'<h3 class="month">{D1[:7]}</h3>' in atlas
          and "Send Ana the design" in atlas and "I owe ana@example.com" in atlas and "acme/atlas" in atlas)
    check("a confidential project and its claims never reach the site",
          "Buy the competitor" not in everything
          and not any("vault" in k for k in files))

    # Diagrams and images --------------------------------------------------------------------
    svg = re.search(r'<figure id="s-\d+" class="diagram".*?</figure>', atlas, re.S).group(0)
    check("a diagram is drawn inline as SVG from its description, with classes only and no inline style",
          '<svg xmlns="http://www.w3.org/2000/svg" class="dg dg-architecture"' in svg and "style=" not in svg
          and "<style" not in svg and 'marker-end="url(#dg-s-' in svg)
    check("every label in a diagram is escaped: quotes, ampersands and angle brackets",
          "Tom &amp; &quot;Jerry&quot; say 1 &lt; 2" in svg and 'say 1 < 2' not in svg and "&lt;3 &amp; more" in svg)
    check("a diagram has a text version, and its nodes link to pages",
          "<summary>Diagram as text</summary>" in svg and 'data-page="beta"' in svg and "→" in svg)
    images = [k for k in files if k.startswith("images/")]
    check("a documentation image is copied into the site, named by its content, and shown with <img>",
          len(images) == 1 and f'<img src="../{images[0]}" alt="The map, from the docs">' in atlas)
    check("the repository map is drawn as a tree", 'class="dg dg-tree"' in atlas and "atlas/" in atlas)

    # Plain HTML for agents -------------------------------------------------------------------
    check("the site is plain: no scripts, no map, no search; a label reads as a word, sources as text",
          "<script src" not in "".join(pages.values()) and 'id="graph"' not in atlas and 'id="search"' not in atlas
          and "Sources: " in atlas and "[verified]" in atlas)
    check("the index lists every page and says where llms.txt and the JSON are and where to browse it",
          "llms.txt" in files["index.html"] and "catalog.json" in files["index.html"] and "pwi open" in files["index.html"]
          and 'href="pages/atlas.html"' in files["index.html"])

    # Formats for agents ---------------------------------------------------------------------
    llms = files["llms.txt"]
    check("llms.txt says what the wiki is and its files, and lists every page with its summary, linking its Markdown",
          llms.startswith("# Work wiki\n\n> ") and "statements.jsonl" in llms and "## Projects" in llms
          and "- [atlas](pages/atlas.md): Offline maps." in llms and "(pages/beta.md): not written yet" in llms)
    md = files["pages/atlas.md"]
    check("a page as Markdown: its title, summary, labels as words, sources, and page links to other .md files",
          md.startswith("# atlas\n\n> Offline maps.") and "Atlas renders **offline maps**, see [Beta](beta.md)" in md
          and "[the spec](<https://example.com/spec>)" in md and "[verified] (sources: `atlas@" in md
          and "- Tiles live in `sqlite` on the device. [verified]" in md and "## Commitments" in md
          and "Send Ana the design [unconfirmed] (I owe ana@example.com" in md)
    drawn_files = sorted(k for k in files if k.startswith("diagrams/"))
    check("each diagram is a file of its own, as SVG with its own style, and as PNG when rsvg-convert is installed",
          "diagrams/atlas.arch.svg" in drawn_files and "<style>" in files["diagrams/atlas.arch.svg"]
          and "Tom &amp; &quot;Jerry&quot;" in files["diagrams/atlas.arch.svg"]
          and (("diagrams/atlas.arch.png" in drawn_files) == bool(shutil.which("rsvg-convert"))))
    picture = "atlas.arch.png" if shutil.which("rsvg-convert") else "atlas.arch.svg"
    check("the Markdown shows the diagram as an image and as text, and the HTML links its files",
          f"(../diagrams/{picture})" in md and "As text:" in md and "→" in md
          and 'href="../diagrams/atlas.arch.svg">SVG</a>' in atlas and f"![The map, from the docs](../{images[0]})" in md)
    rows = [json.loads(line) for line in files["statements.jsonl"].splitlines()]
    check("statements.jsonl has one line per statement, diagram and image, with page, section, label and sources",
          {(r["page"], r["kind"]) for r in rows} == {("atlas", "statement"), ("atlas", "diagram"), ("atlas", "image")}
          and any(r["text"].startswith("Atlas renders") and r["label"] == "verified" and r["section"] == "overview"
                  and r["cites"] and r["md"] == "pages/atlas.md" for r in rows)
          and any(r["kind"] == "diagram" and r["svg"] == "diagrams/atlas.arch.svg" and r["as_text"] for r in rows)
          and "<" not in files["statements.jsonl"])
    graph = json.loads(files["graph.json"])
    check("graph.json has every page and the links between them; catalog.json says when it was built",
          {n["id"] for n in graph["nodes"]} == {"atlas", "beta", "evil-b-repo"}
          and {"from": "atlas", "to": "beta"} in graph["edges"] and json.loads(files["catalog.json"])["built_at"])
    check("each HTML page names its Markdown and JSON as alternates",
          '<link rel="alternate" type="text/markdown" href="atlas.md">' in atlas and 'href="atlas.json">JSON</a>' in atlas)

    # Rebuilding -------------------------------------------------------------------------------
    check("the service rebuilds only when something changed",
          wiki_site.rebuild_if_changed(db) is True and wiki_site.rebuild_if_changed(db) is False)
    db.execute("INSERT INTO labels VALUES ('claim', 'clm_evil', 'confidential', 'me', ?)", (NOW,))
    db.execute("INSERT INTO audit_log (at, actor, action, item_type, item_id) VALUES (?, 'me', 'label', 'claim', 'clm_evil')",
               (NOW,))
    check("a label set in the frontend triggers a rebuild", wiki_site.rebuild_if_changed(db) is True)
    files = site_text(site)
    check("after the rebuild, the statement citing the now-confidential claim is gone from every file",
          "Secret detail hidden later" not in "\n".join(files.values()) and "alert(1)" not in "\n".join(files.values()))
    cli = subprocess.run([sys.executable, "-I", str(HERE / "cli.py"), "wiki", "build"], capture_output=True, text=True,
                         timeout=120)
    check("pwi wiki build builds it and says where", cli.returncode == 0 and f"in {site}" in cli.stdout)
    db.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
