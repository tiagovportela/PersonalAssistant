"""Checks Phase 2, online sources: the connectors allowlist, project aliases
Claude and I add, rule-based references from commit messages, and how
get_project turns them into lookups. Uses a temporary home with real Git data.

Run: python3 -I service/test_online.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pwi-online-"))
os.environ.update({"HOME": str(TMP), "XDG_DATA_HOME": str(TMP / "data"), "XDG_CONFIG_HOME": str(TMP / "config"),
                   "XDG_RUNTIME_DIR": str(TMP / "run"), "CLAUDE_CONFIG_DIR": str(TMP / "claude"),
                   "GIT_CONFIG_GLOBAL": str(TMP / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"})
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]

import admin  # noqa: E402
import collect  # noqa: E402
import collect_git  # noqa: E402
import handlers  # noqa: E402
import paths  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402

D1 = (date.today() - timedelta(days=2)).isoformat()
NOTION_ID = "0123456789abcdef0123456789abcdef"


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def sh(cwd, *args, **env):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, env={**os.environ, **env})


def commit(repo, message):
    with open(repo / "a.txt", "a") as f:
        f.write(message + "\n")
    sh(repo, "git", "add", "a.txt")
    stamp = f"{D1}T10:00:00+00:00"
    sh(repo, "git", "commit", "-q", "-m", message, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)


def main():
    layer = handlers.Layer(paths.STORE_PATH)

    def call(name, args=None):
        result = layer.call_tool(name, args or {})
        text = result["content"][0]["text"]
        if result["isError"]:
            return {"error": text}
        return json.loads(text.split("\n", 1)[1].rsplit("\n", 1)[0])

    # references in commit messages
    refs = collect_git.references(
        f"Fix #12 and BILL-345 (see UTF-8, SHA-256)\n\nhttps://github.com/acme/other/pull/7 "
        f"https://www.notion.so/acme/Retry-plan-{NOTION_ID} https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUv/edit "
        "&#39; https://drive.google.com/drive/folders/1ZyXwVuTsRqPoNmLkJiHgFe", "acme/billing")
    check("commit messages yield references to PRs, issue keys and Notion, Docs and Drive items, not false keys",
          refs == ["github:acme/other#7", "github:acme/billing#12", "key:BILL-345", f"notion:{NOTION_ID}",
                   "drive:1AbCdEfGhIjKlMnOpQrStUv", "drive:1ZyXwVuTsRqPoNmLkJiHgFe"])
    check("a bare #12 needs the repository's GitHub alias", collect_git.references("Fix #12") == [])

    os.umask(0o077)
    store.create_or_check(paths.STORE_PATH)
    billing, notes = TMP / "Projects" / "billing", TMP / "Projects" / "notes"
    for repo in (billing, notes):
        repo.mkdir(parents=True)
        sh(repo, "git", "init", "-q", "-b", "main")
        sh(repo, "git", "config", "user.email", "me@example.com")
    sh(billing, "git", "remote", "add", "origin", "git@github.com:acme/billing.git")
    commit(billing, f"Add retry queue (#12, BILL-345)\n\nPlan: https://www.notion.so/acme/Retry-{NOTION_ID}")
    commit(billing, "Tune retry delay for BILL-345")
    commit(notes, "Notes")
    db = store.connect(paths.STORE_PATH)
    sources.add_path(db, TMP / "Projects")
    collect.run(paths.STORE_PATH)

    day = call("get_day", {"day": D1})
    first = next(c for c in day["events_by_project"]["billing"]["commits"] if c["title"].startswith("Add retry"))
    check("commits Claude sees list their references, with #12 resolved through the GitHub alias",
          first["refs"] == ["github:acme/billing#12", "key:BILL-345", f"notion:{NOTION_ID}"])

    # the allowlist for online sources
    listed = call("list_projects")
    allowed = {c["connector"]: c["allowed"] for c in listed["connectors"]}
    check("list_projects gives the online-sources allowlist: GitHub, Calendar and Notion on; Gmail, Chat and Drive off",
          allowed == {"github": True, "google_calendar": True, "notion": True, "gmail": False, "google_chat": False,
                      "google_drive": False}
          and next(c for c in listed["connectors"] if c["connector"] == "github")["scope"] == "everything you can see")

    # aliases Claude adds
    added = call("add_project_alias", {"project": "billing", "kind": "gmail_query", "value": " label:billing "})
    check("Claude can add where a project lives online", added == {"project": "billing", "kind": "gmail_query",
                                                                   "value": "label:billing", "created": True})
    check("adding it again changes nothing",
          call("add_project_alias", {"project": "billing", "kind": "gmail_query", "value": "label:billing"})["created"] is False)
    check("a GitHub link becomes owner/repo, and a malformed repository is refused",
          call("add_project_alias", {"project": "notes", "kind": "github_repo",
                                     "value": "https://github.com/acme/notes"})["value"] == "acme/notes"
          and "owner/repo" in call("add_project_alias", {"project": "notes", "kind": "github_repo", "value": "notes"})["error"])
    check("an alias that belongs to another project is refused, naming it",
          "already belongs to project billing" in call("add_project_alias", {"project": "notes", "kind": "gmail_query",
                                                                             "value": "label:billing"})["error"])
    call("add_project_alias", {"project": "notes", "kind": "chat_space", "value": "Secret deal room"})
    call("add_confidential_label", {"item": {"type": "project", "id": "notes"}})
    check("but never names a confidential project",
          "another project" in call("add_project_alias", {"project": "billing", "kind": "chat_space",
                                                          "value": "Secret deal room"})["error"])
    check("Claude can't add local aliases or aliases to unknown projects",
          "must be one of" in call("add_project_alias", {"project": "billing", "kind": "repo_path", "value": "/tmp"})["error"]
          and "no project" in call("add_project_alias", {"project": "nope", "kind": "notion", "value": "x"})["error"])

    # lookups follow aliases, but only through allowed connectors
    call("add_project_alias", {"project": "billing", "kind": "notion", "value": f"https://www.notion.so/acme/Billing-{NOTION_ID}"})
    project = call("get_project", {"project": "billing"})
    connectors = {q["connector"] for q in project["lookups"]}
    check("get_project turns aliases into lookups, only for allowed connectors, and says which are off",
          connectors == {"github", "notion"} and any("Gmail" in g for g in project["gaps"]))
    check("get_project lists the references its recent commits make, most recent first, with counts",
          {r["ref"]: r["commits"] for r in project["references"]} == {"key:BILL-345": 2, "github:acme/billing#12": 1,
                                                                    f"notion:{NOTION_ID}": 1})
    admin.set_connector(db, "gmail", {"enabled": True, "scope": "label:work"})
    project = call("get_project", {"project": "billing"})
    gmail = next(c for c in call("list_projects")["connectors"] if c["connector"] == "gmail")
    check("turning Gmail on in the frontend adds its lookup, and Claude sees its scope",
          any(q["connector"] == "gmail" and "label:billing" in q["query"] for q in project["lookups"])
          and gmail == {"connector": "gmail", "name": "Gmail", "allowed": True, "scope": "label:work"}
          and not any("Gmail" in g for g in project.get("gaps", [])))
    check("link_items between a project and an online item shows up on the project",
          "error" not in call("propose_claim", {"type": "fact", "text": "Billing tasks live in Notion", "project": "billing",
                                                "evidence": [{"artifact_id": f"notion:{NOTION_ID}", "artifact_kind": "document",
                                                              "read_at": "2026-11-02T17:00:00Z"}]})
          and call("link_items", {"from": {"type": "artifact", "id": f"notion:{NOTION_ID}"}, "rel": "part_of",
                                  "to": {"type": "project", "id": "billing"}})["created"] is True
          and call("get_project", {"project": "billing"})["links"][0]["from_id"] == f"notion:{NOTION_ID}")

    # my aliases and connector settings, from the frontend
    check("I can add aliases of the online kinds, but not repository folders",
          admin.add_alias(db, "billing", "drive_folder", "Work/Billing")["kind"] == "drive_folder")
    try:
        admin.remove_alias(db, "repo_path", str(billing))
        check("a repository folder can't be removed as an alias", False)
    except admin.Invalid as e:
        check("a repository folder can't be removed as an alias", "Sources" in str(e))
    admin.remove_alias(db, "gmail_query", "label:billing")
    aliases = {a["kind"]: a for a in next(p for p in admin.projects(db) if p["id"] == "billing")["aliases"]}
    check("I can remove any online alias, and the frontend shows who added each",
          "gmail_query" not in aliases and aliases["notion"]["added_by"] == "claude" and aliases["drive_folder"]["added_by"] == "me")
    try:
        admin.set_connector(db, "myspace", {"enabled": True})
        check("an unknown connector is refused", False)
    except admin.Invalid:
        check("an unknown connector is refused", True)
    actions = {(r["actor"], r["action"], r["item_type"]) for r in db.execute("SELECT actor, action, item_type FROM audit_log")}
    check("alias and connector changes are in the audit log",
          {("claude", "link", "project"), ("me", "link", "project"), ("me", "settings", "connector")} <= actions)
    db.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
