"""Checks the wiki's compile run (service/wiki_compile.py) against a fake Claude Code: which pages it picks,
the tools and folder Claude gets, the prompt, the runs it records, the unit that starts it after each
end-of-day run, and `pwi wiki`. The fake can also act as Claude would, calling the layer's tools, so a run
that writes a page is checked end to end.

Run: python3 -I service/test_wiki_compile.py
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

TMP = Path(tempfile.mkdtemp(prefix="pwi-wikirun-"))
HERE = Path(__file__).resolve().parent
os.environ.update({"HOME": str(TMP), "XDG_DATA_HOME": str(TMP / "data"), "XDG_CONFIG_HOME": str(TMP / "config"),
                   "XDG_RUNTIME_DIR": str(TMP / "run"), "CLAUDE_CONFIG_DIR": str(TMP / "claude"),
                   "GIT_CONFIG_GLOBAL": str(TMP / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1", "PWI_NO_SYSTEMD": "1",
                   "ANTHROPIC_API_KEY": "sk-ant-should-not-reach-claude", "FAKE_CLAUDE_LOG": str(TMP / "calls.jsonl"),
                   "FAKE_SERVICE": str(HERE), "FAKE_CONTRACTS": str(HERE.parent / "contracts"),
                   "PATH": f"{TMP / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}"})
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]

import collect  # noqa: E402
import eod  # noqa: E402
import handlers  # noqa: E402
import paths  # noqa: E402
import retention  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402
import tool_rules  # noqa: E402
import wiki_compile  # noqa: E402

TODAY = date.today()
D1, D2 = (TODAY - timedelta(days=3)).isoformat(), (TODAY - timedelta(days=2)).isoformat()
OLD = (TODAY - timedelta(days=60)).isoformat()

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, re, sys
args = sys.argv[1:]
prompt = sys.stdin.read()
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as log:
    log.write(json.dumps({"argv": args, "cwd": os.getcwd(), "files": sorted(os.listdir(".")), "prompt": prompt,
                          "api_key": "ANTHROPIC_API_KEY" in os.environ}) + "\n")
if os.environ.get("FAKE_CLAUDE_FAIL"):
    print(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "result": "stopped"}))
    sys.exit(1)
page = re.search(r"\*\*Page:\*\* `([^`]+)`", prompt).group(1)
if os.environ.get("FAKE_CLAUDE_WRITES"):  # do what Claude would, through the layer's tools
    sys.path[:0] = [os.environ["FAKE_SERVICE"], os.environ["FAKE_CONTRACTS"]]
    import handlers, paths
    layer = handlers.Layer(paths.STORE_PATH)
    def call(name, arguments):
        text = layer.call_tool(name, arguments)["content"][0]["text"]
        return json.loads(text.split("\n", 1)[1].rsplit("\n", 1)[0])
    outline = call("get_wiki_page", {"page": page})
    repo = call("read_repo", {"project": outline["project"]})
    call("propose_wiki_update", {"page": page, "base_version": outline["version"], "reason": "compile run",
                                 "built_from": [repo["built_from"]], "summary": "Compiled by the run.",
                                 "sections": [{"id": "overview", "blocks": [{"text": "It renders maps.", "cites": [
                                     {**repo["cite_as"], "path": repo["readme"]["path"]}]}]}]})
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 7, "duration_ms": 60000,
                  "result": f"Updated {page}. REPLY_MARKER", "permission_denials": []}))
'''


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def sh(cwd, *args, **env):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, env={**os.environ, **env}).stdout.decode().strip()


def commit(repo, name, text, day):
    (repo / name).write_text(text)
    sh(repo, "git", "add", "-A")
    stamp = f"{day}T10:00:00+00:00"
    sh(repo, "git", "commit", "-q", "-m", f"Change {name}", GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)


def calls():
    log = Path(os.environ["FAKE_CLAUDE_LOG"])
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def main():
    layer = handlers.Layer(paths.STORE_PATH)

    def call(name, args=None):
        text = layer.call_tool(name, args or {})["content"][0]["text"]
        return json.loads(text.split("\n", 1)[1].rsplit("\n", 1)[0])

    os.umask(0o077)
    store.create_or_check(paths.STORE_PATH)
    claude = TMP / "bin" / "claude"
    claude.parent.mkdir()
    claude.write_text(FAKE_CLAUDE)
    claude.chmod(0o755)
    repos = {name: TMP / "Projects" / name for name in ("atlas", "beta", "gamma", "vault")}
    for name, repo in repos.items():
        repo.mkdir(parents=True)
        sh(repo, "git", "init", "-q", "-b", "main")
        sh(repo, "git", "config", "user.email", "me@example.com")
        commit(repo, "README.md", f"# {name}\n\n{name} renders maps.\n", OLD if name == "gamma" else D1)
    db = store.connect(paths.STORE_PATH)
    sources.add_path(db, TMP / "Projects")
    collect.run(paths.STORE_PATH)
    db.execute("INSERT INTO labels VALUES ('project', 'vault', 'confidential', 'me', ?)", (store.now(),))
    first = call("read_repo", {"project": "atlas"})
    call("propose_wiki_update", {"page": "atlas", "base_version": 0, "reason": "first", "built_from": [first["built_from"]],
                                 "sections": [{"id": "overview", "blocks": [{"text": "Atlas renders maps.", "cites": [
                                     {**first["cite_as"], "path": "README.md"}]}]}]})
    commit(repos["atlas"], "docs.md", "More about Atlas.\n", D2)
    collect.run(paths.STORE_PATH)

    # Which pages --------------------------------------------------------------------------
    due = wiki_compile.pages_to_compile(db)
    check("by default: stale pages, and active projects' pages not written yet, most recently active first",
          [(p["id"], why.split(":")[0].split(";")[0]) for p, why in due] == [("atlas", "stale"), ("beta", "not written yet")]
          and due[1][1].endswith(f"last active on {D1}"))
    check("a stale page says why: the commits since it was built",
          "1 commits on atlas main since" in due[0][1])
    check("an inactive project's unwritten page and a confidential project's are left alone",
          not {"gamma", "vault"} & {p["id"] for p, _ in due})
    check("--max caps the pages, --all takes every project's page, --page names one",
          [p["id"] for p, _ in wiki_compile.pages_to_compile(db, limit=1)] == ["atlas"]
          and sorted(p["id"] for p, _ in wiki_compile.pages_to_compile(db, everything=True)) == ["atlas", "beta", "gamma"]
          and [(p["id"], why) for p, why in wiki_compile.pages_to_compile(db, ["gamma"])] == [("gamma", "asked for")])
    try:
        wiki_compile.pages_to_compile(db, ["vault"])
        check("a confidential project's page can't be named", False)
    except eod.EodError as e:
        check("a confidential project's page can't be named", "no wiki page vault" in str(e))

    # A run --------------------------------------------------------------------------------
    results = wiki_compile.compile_pages(db, limit=1)  # the default: atlas, the most recently active due page
    c = calls()[-1]
    argv = c["argv"]
    allowed = argv[argv.index("--allowedTools") + 1:argv.index("--disallowedTools")]
    denied = argv[argv.index("--disallowedTools") + 1:]
    check("Claude gets only the layer's read tools it needs and propose_wiki_update: no connectors, no edits",
          allowed == [f"mcp__pwi__{t}" for t in wiki_compile.TOOLS]
          and "mcp__pwi__propose_claim" not in allowed and not any(a.startswith("Edit(") for a in allowed)
          and {"Bash", "Read", "Glob", "Grep", "Edit", "Write", "WebFetch", "WebSearch", "Task"} <= set(denied))
    check("headless, in dontAsk mode, with the layer as its MCP server, and no hook to allow anything else",
          argv[0] == "-p" and argv[argv.index("--permission-mode") + 1] == "dontAsk" and "--mcp-config" in argv
          and "--settings" not in argv)
    check("in an empty folder, without an API key, so it uses my claude.ai sign-in",
          c["cwd"] == str(paths.RUNTIME_DIR / "wiki-compile") and c["files"] == [] and c["api_key"] is False)
    check("the prompt names the page, its version and why, then the wiki instructions",
          "**Page:** `atlas`, the project page *atlas*, now at version 1." in c["prompt"]
          and "**Why now:** stale: 1 commits on atlas main" in c["prompt"]
          and "# Knowledge wiki" in c["prompt"] and "{{" not in c["prompt"])
    run = db.execute("SELECT * FROM wiki_runs ORDER BY id DESC").fetchone()
    check("the run is recorded: page, why, versions, turns and time, never Claude's reply",
          results[0]["status"] == "ok" and run["page_id"] == "atlas" and run["status"] == "ok"
          and run["reason"].startswith("stale: 1 commits on atlas main")
          and (run["version_before"], run["version_after"]) == (1, 1) and "7 turns" in run["detail"]
          and "left as it was" in run["detail"] and "REPLY_MARKER" not in json.dumps(dict(run)))

    os.environ["FAKE_CLAUDE_WRITES"] = "1"
    results = wiki_compile.compile_pages(db, ["beta"])
    del os.environ["FAKE_CLAUDE_WRITES"]
    beta = call("get_wiki_page", {"page": "beta", "sections": ["overview"]})
    check("a run that writes the page is recorded with its new version, and the page holds what Claude wrote",
          results[0]["status"] == "ok" and (results[0]["version_before"], results[0]["version_after"]) == (0, 1)
          and "version 0 to 1" in results[0]["detail"] and beta["content"][0]["blocks"][0]["label"] == "repo"
          and beta["summary"] == "Compiled by the run.")
    check("a written page that's up to date is no longer due", "beta" not in [p["id"] for p, _ in wiki_compile.pages_to_compile(db)])

    os.environ["FAKE_CLAUDE_FAIL"] = "1"
    results = wiki_compile.compile_pages(db, ["atlas", "beta"])
    del os.environ["FAKE_CLAUDE_FAIL"]
    check("a failed run is recorded with the reason, and the next page still runs",
          [r["status"] for r in results] == ["failed", "failed"] and "stopped" in results[0]["detail"]
          and db.execute("SELECT COUNT(*) FROM wiki_runs WHERE status = 'failed'").fetchone()[0] == 2)
    db.execute("INSERT INTO wiki_runs (page_id, reason, started_at, status, detail) VALUES ('atlas', 'x', ?, 'running',"
               " 'pid 999999')", (store.now(),))
    wiki_compile.status(db)
    check("a run whose process is gone is marked interrupted",
          db.execute("SELECT detail FROM wiki_runs ORDER BY id DESC").fetchone()[0].startswith("interrupted"))

    # Started after each end-of-day run --------------------------------------------------------
    eod.write_units("19:30", "Mon..Fri", str(claude))
    unit = (eod.UNIT_DIR / "pwi-wiki.service").read_text()
    check("the end-of-day setup writes the wiki's unit: pwi wiki compile, with its own time limit",
          "wiki compile" in unit and "eod run" not in unit and f"TimeoutStartSec={eod.WIKI_TIMEOUT}" in unit
          and "pwi-wiki.service" in eod.UNITS and not (eod.UNIT_DIR / "pwi-wiki.timer").exists())
    eod.start_wiki()  # PWI_NO_SYSTEMD: a no-op here, the systemctl start under systemd
    eod.remove_units(systemd=False)
    check("turning the agent off removes the wiki's unit too", not (eod.UNIT_DIR / "pwi-wiki.service").exists())
    check("the end-of-day agent itself can't write the wiki; it reads it",
          tool_rules.classify(["mcp__pwi__propose_wiki_update", "mcp__pwi__get_wiki_page", "mcp__pwi__read_repo"])
          == (["mcp__pwi__get_wiki_page", "mcp__pwi__read_repo"], ["mcp__pwi__propose_wiki_update"]))

    # pwi wiki -------------------------------------------------------------------------------
    cli = [sys.executable, "-I", str(HERE / "cli.py")]
    status = subprocess.run([*cli, "wiki", "status"], capture_output=True, text=True, timeout=120)
    check("pwi wiki status lists the pages, what's due and the last runs",
          status.returncode == 0 and "pages, 2 written" in status.stdout and "due: atlas: stale" in status.stdout
          and "interrupted" in status.stdout)
    ran = subprocess.run([*cli, "wiki", "compile", "--max", "1"], capture_output=True, text=True, timeout=300)
    check("pwi wiki compile runs the due pages, and keeps Claude's reply out of logs when it isn't a terminal",
          ran.returncode == 0 and "1 page to compile" in ran.stdout and "atlas: ok" in ran.stdout
          and "REPLY_MARKER" not in ran.stdout)
    check("--page and --all can't go together",
          subprocess.run([*cli, "wiki", "compile", "--page", "atlas", "--all"], capture_output=True, text=True,
                         timeout=60).returncode == 1)

    counts = retention.run(paths.STORE_PATH, now=time.time() + 100 * 86400)
    check("retention removes old compile runs with the audit trail",
          counts["wiki_runs"] >= 4 and db.execute("SELECT COUNT(*) FROM wiki_runs").fetchone()[0] == 0)
    db.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
