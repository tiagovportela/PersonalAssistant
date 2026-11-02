"""Checks the frontend's web server: sign-in, host and origin checks, security
headers, static files, and every admin action (allowlist, deletion with a
decision per affected claim, labels, retention, projects, audit), against data
the real collectors and write tools put in a temporary store.

Run: python3 -I service/test_web.py
"""

import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pwi-web-"))
os.environ.update({"HOME": str(TMP), "XDG_DATA_HOME": str(TMP / "data"), "XDG_CONFIG_HOME": str(TMP / "config"),
                   "XDG_RUNTIME_DIR": str(TMP / "run"), "CLAUDE_CONFIG_DIR": str(TMP / "claude"),
                   "GIT_CONFIG_GLOBAL": str(TMP / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"})
(TMP / "run").mkdir(mode=0o700)
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]

import collect  # noqa: E402
import handlers  # noqa: E402
import paths  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402
import web  # noqa: E402

D1 = (date.today() - timedelta(days=2)).isoformat()


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def sh(cwd, *args, **env):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, env={**os.environ, **env})


def commit(repo, subject):
    with open(repo / "a.txt", "a") as f:
        f.write(subject + "\n")
    sh(repo, "git", "add", "a.txt")
    stamp = f"{D1}T10:00:00+00:00"
    sh(repo, "git", "commit", "-q", "-m", subject, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)


def main():
    os.umask(0o077)
    store.create_or_check(paths.STORE_PATH)
    work, side = TMP / "Projects" / "work", TMP / "Projects" / "side"
    for repo in (work, side):
        repo.mkdir(parents=True)
        sh(repo, "git", "init", "-q", "-b", "main")
        sh(repo, "git", "config", "user.email", "me@example.com")
    commit(work, "First change")
    commit(work, "Second change")
    commit(side, "Side work")
    db = store.connect(paths.STORE_PATH)
    sources.add_path(db, TMP / "Projects")
    collect.run(paths.STORE_PATH)
    ids = {r["title"]: r["id"] for r in db.execute("SELECT id, title FROM events WHERE type = 'git.commit'")}
    layer = handlers.Layer(paths.STORE_PATH)

    def propose(text, *events):
        result = layer.call_tool("propose_claim", {"type": "decision", "text": text,
                                                   "evidence": [{"event_id": e} for e in events]})
        return json.loads(result["content"][0]["text"].split("\n", 1)[1].rsplit("\n", 1)[0])["claim_id"]

    only_first = propose("We split the module", ids["First change"])
    both = propose("We keep the API stable", ids["First change"], ids["Second change"])
    to_delete = propose("We rename the service", ids["First change"])
    unrelated = propose("We use SQLite", ids["Second change"])

    static = TMP / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>pwi</title><script type=module src=/assets/app.js></script>")
    (static / "assets" / "app.js").write_text("console.log('app')")
    (TMP / "secret.txt").write_text("outside")
    front = web.Frontend(paths.STORE_PATH, "test", 0, static)
    front.start()
    host = f"127.0.0.1:{front.port}"
    cookie = None

    def request(method, path, body=None, headers=None, signed_in=True, origin=True):
        conn = http.client.HTTPConnection("127.0.0.1", front.port, timeout=30)
        sent = {"Host": host}
        if signed_in and cookie:
            sent["Cookie"] = cookie
        if origin and method != "GET":
            sent["Origin"] = f"http://{host}"
        if body is not None:
            sent["Content-Type"] = "application/json"
        sent.update(headers or {})
        conn.request(method, path, json.dumps(body) if body is not None else None, sent)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        try:
            parsed = json.loads(data) if data and "json" in (response.getheader("Content-Type") or "") else data
        except json.JSONDecodeError:
            parsed = data
        return response.status, parsed, response

    try:
        info = json.loads(web.INFO_PATH.read_text())
        check("the service writes the frontend's port and login link where only I can read them",
              info["port"] == front.port and "code=" in info["login_url"] and web.INFO_PATH.stat().st_mode & 0o777 == 0o600)

        # sign-in and the checks on every request
        status, _, _ = request("GET", "/api/status")
        check("without signing in, the API refuses", status == 401)
        status, page, _ = request("GET", "/")
        check("without signing in, the page says how to open the frontend", status == 401 and b"pwi open" in page)
        status, _, _ = request("GET", "/login?code=wrong")
        check("a wrong login code is refused", status == 403)
        status, _, response = request("GET", info["login_url"].split(host, 1)[1])
        set_cookie = response.getheader("Set-Cookie")
        check("the login link sets an HttpOnly, SameSite=Strict session cookie and goes to the app",
              status == 303 and response.getheader("Location") == "/" and "HttpOnly" in set_cookie
              and "SameSite=Strict" in set_cookie and front.login_code not in set_cookie)
        cookie = set_cookie.split(";", 1)[0]
        to = request("GET", info["login_url"].split(host, 1)[1] + "&to=claims")[2].getheader("Location")
        away = request("GET", info["login_url"].split(host, 1)[1] + "&to=//evil.example")[2].getheader("Location")
        check("the login link can open a section, but never send the browser elsewhere", to == "/#claims" and away == "/")
        status, data, response = request("GET", "/api/status")
        check("signed in, the API answers, with security headers on every response",
              status == 200 and data["events"] >= 3 and "frame-ancestors 'none'" in response.getheader("Content-Security-Policy")
              and response.getheader("X-Content-Type-Options") == "nosniff" and response.getheader("Cache-Control") == "no-store")
        check("a request for another host name is refused, which stops DNS-rebinding attacks",
              request("GET", "/api/status", headers={"Host": f"evil.example:{front.port}"})[0] == 403)
        check("a change from another website is refused, even with the cookie",
              request("POST", "/api/collect", headers={"Origin": "http://evil.example"})[0] == 403
              and request("POST", "/api/collect", origin=False)[0] == 403)
        check("a wrong session cookie is refused", request("GET", "/api/status", headers={"Cookie": "pwi_session=nope"})[0] == 401)
        status, page, response = request("GET", "/")
        check("the app's page and its files are served", status == 200 and b"<title>pwi</title>" in page
              and request("GET", "/assets/app.js")[2].getheader("Content-Type").startswith("text/javascript"))
        check("files outside the app's folder can't be read",
              b"outside" not in request("GET", "/../secret.txt")[1] and b"outside" not in request("GET", "/assets/../../secret.txt")[1])
        check("a bad request body is an error, not a crash",
              request("POST", "/api/sources", headers={"Content-Type": "application/json"}, body=None)[0] == 400
              and request("POST", "/api/labels", body=["not", "an", "object"])[0] == 400)

        # sources, projects, browsing
        status, added, _ = request("POST", "/api/sources", {"path": str(TMP / "nowhere")})
        check("adding a path that isn't a repository says why", status == 400 and "isn't a folder" in added["error"])
        side_id = next(s["id"] for s in request("GET", "/api/sources")[1] if s["name"] == "side")
        status, _, _ = request("PUT", f"/api/sources/{side_id}", {"enabled": False})
        check("a source can be turned off", status == 200
              and not next(s for s in request("GET", "/api/sources")[1] if s["id"] == side_id)["enabled"])
        status, _, _ = request("PUT", "/api/projects/work", {"name": "Work platform", "status": "paused"})
        projects = {p["id"]: p for p in request("GET", "/api/projects")[1]}
        check("a project can be renamed and paused", status == 200 and projects["work"]["name"] == "Work platform"
              and projects["work"]["status"] == "paused")
        events = request("GET", "/api/events?project=work")[1]
        check("events can be browsed by project, and searched", {e["title"] for e in events} == {"First change", "Second change"}
              and [e["title"] for e in request("GET", "/api/events?q=second")[1]] == ["Second change"])
        claims = {c["claim_id"]: c for c in request("GET", "/api/claims")[1]}
        check("claims can be browsed, with their status and evidence count",
              claims[both]["evidence"] == 2 and claims[both]["status"] == "proposed")
        history = request("GET", f"/api/claims/{both}")[1]
        check("a claim's full history is shown, with its evidence",
              history["versions"][0]["evidence"][0]["event_title"] in ("First change", "Second change"))

        # deletion: every claim relying on deleted evidence needs a decision
        item = [{"type": "event", "id": ids["First change"]}]
        impact = request("POST", "/api/impact", {"items": item})[1]
        check("before deleting, the frontend lists the claims that rely on the evidence",
              {c["claim_id"] for c in impact["affected_claims"]} == {only_first, both, to_delete} and impact["events"] == 1)
        status, refused, _ = request("POST", "/api/delete", {"items": item, "decisions": {only_first: "keep"}})
        check("deleting without a decision for every affected claim is refused, and nothing is deleted",
              status == 400 and "Decide what happens" in refused["error"]
              and db.execute("SELECT COUNT(*) FROM events WHERE id = ?", (ids["First change"],)).fetchone()[0] == 1)
        status, done, _ = request("POST", "/api/delete", {"items": item, "decisions": {
            only_first: "keep", both: "retract", to_delete: "delete"}})
        check("deleting applies each decision: keep, retract or delete", status == 200
              and done == {"events": 1, "claims": 1, "sources": 0, "retracted": 1})
        kept = db.execute("SELECT ev.expired_at FROM claim_evidence ce JOIN evidence ev ON ev.id = ce.evidence_id"
                          " JOIN current_claims c ON c.id = ce.claim_id AND c.version = ce.version WHERE c.id = ?",
                          (only_first,)).fetchone()
        check("a kept claim stays, with its evidence marked expired",
              kept["expired_at"] is not None
              and tuple(db.execute("SELECT status, changed_by FROM current_claims WHERE id = ?", (both,)).fetchone()) == ("retracted", "me")
              and db.execute("SELECT COUNT(*) FROM claims WHERE id = ?", (to_delete,)).fetchone()[0] == 0)
        check("claims that didn't rely on it are untouched",
              db.execute("SELECT status FROM current_claims WHERE id = ?", (unrelated,)).fetchone()[0] == "proposed")
        source_item = [{"type": "source", "id": str(side_id)}]
        status, done, _ = request("POST", "/api/delete", {"items": source_item, "decisions": {}})
        check("a whole source can be deleted with its data",
              status == 200 and done["sources"] == 1 and done["events"] >= 1
              and db.execute("SELECT COUNT(*) FROM events WHERE source_id = ?", (side_id,)).fetchone()[0] == 0)
        status, _, _ = request("POST", "/api/delete", {"items": [{"type": "claim", "id": unrelated}], "decisions": {}})
        check("a claim can be deleted directly", status == 200
              and db.execute("SELECT COUNT(*) FROM claims WHERE id = ?", (unrelated,)).fetchone()[0] == 0)
        check("deleting something that isn't there is refused",
              request("POST", "/api/delete", {"items": [{"type": "event", "id": "git:commit:nope"}]})[0] == 400)

        # confidential labels: only here can they be removed
        status, _, _ = request("POST", "/api/labels", {"type": "project", "id": "work"})
        listed = request("GET", "/api/labels")[1]
        check("a label can be added, and the list names what it hides",
              status == 200 and listed[0]["name"] == "Work platform" and listed[0]["set_by"] == "me")
        status, _, _ = request("DELETE", "/api/labels/project/work")
        check("a label can be removed here, and only here", status == 200 and request("GET", "/api/labels")[1] == [])
        check("removing a label that isn't there says so", request("DELETE", "/api/labels/project/work")[0] == 400)

        # retention, cleanup, collection, audit
        status, _, _ = request("PUT", "/api/retention/git_repo", {"days": 30})
        settings = {r["item_type"]: r["days"] for r in request("GET", "/api/retention")[1]}
        check("retention can be changed per kind", status == 200 and settings["git_repo"] == 30)
        check("retention can be set to keep until I delete, but not to nonsense",
              request("PUT", "/api/retention/transcript", {"days": None})[0] == 200
              and request("PUT", "/api/retention/transcript", {"days": -4})[0] == 400
              and request("PUT", "/api/retention/transcript", {"days": "soon"})[0] == 400)
        check("cleanup and collection can be run from here",
              request("POST", "/api/cleanup")[0] == 200 and request("POST", "/api/collect")[0] == 200)
        actions = {(a["actor"], a["action"]) for a in request("GET", "/api/audit")[1]}
        check("every change here is in the audit log as mine",
              {("me", "delete"), ("me", "label"), ("me", "unlabel"), ("me", "settings"), ("me", "set_status")} <= actions)
        check("an unknown API path is a clean 404", request("GET", "/api/nope")[0] == 404)
    finally:
        front.stop()
        db.close()
    check("stopping the service removes the login link", not web.INFO_PATH.exists())


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
