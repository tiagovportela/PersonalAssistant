"""Checks the read-only Google sign-in and the Chat tools against a fake Google
running locally: the OAuth flow with PKCE, refusing more than read access,
token storage and refresh, the allowlist enforced in code, redaction, paging,
errors, and that nothing from Chat is stored.

Run: python3 -I service/test_google_chat.py
"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pwi-gchat-"))
HERE = Path(__file__).resolve().parent
TOKEN = "ghp_" + "Q1w2E3r4T5y6U7i8O9p0A1s2D3f4"
READ_ONLY = {"openid", "email", "https://www.googleapis.com/auth/chat.spaces.readonly",
             "https://www.googleapis.com/auth/chat.messages.readonly",
             "https://www.googleapis.com/auth/chat.memberships.readonly"}
YESTERDAY = date.today() - timedelta(days=1)


def at(day, hour):
    return datetime.combine(day, time(hour)).astimezone().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


SPACES = [{"name": "spaces/AAA", "displayName": "Billing team", "spaceType": "SPACE", "lastActiveTime": at(YESTERDAY, 15)},
          {"name": "spaces/BBB", "displayName": "Data guild", "spaceType": "SPACE", "lastActiveTime": at(YESTERDAY, 11)},
          {"name": "spaces/CCC", "displayName": "Deal room", "spaceType": "SPACE", "lastActiveTime": at(YESTERDAY, 9)},
          {"name": "spaces/DDD", "displayName": "Random", "spaceType": "SPACE", "lastActiveTime": at(YESTERDAY, 8)},
          {"name": "spaces/EEE", "spaceType": "DIRECT_MESSAGE", "lastActiveTime": at(YESTERDAY - timedelta(days=9), 8)}]
MESSAGES = {
    "spaces/AAA": [
        {"name": "spaces/AAA/messages/1", "sender": {"name": "users/42", "displayName": "Me"}, "createTime": at(YESTERDAY, 10),
         "text": "I'll send the VAT notes to Ana by Friday", "thread": {"name": "spaces/AAA/threads/t1"}},
        {"name": "spaces/AAA/messages/2", "sender": {"name": "users/7", "displayName": "Ana"}, "createTime": at(YESTERDAY, 11),
         "text": f"Thanks! The deploy token is {TOKEN}"},
        {"name": "spaces/AAA/messages/3", "sender": {"name": "users/7", "displayName": "Ana"}, "createTime": at(YESTERDAY - timedelta(days=3), 9),
         "text": "An old message"}],
    "spaces/BBB": [{"name": f"spaces/BBB/messages/{i}", "sender": {"name": "users/9", "displayName": "Rui"},
                    "createTime": at(YESTERDAY, 9), "text": f"Pipeline note {i}"} for i in range(150)],
    "spaces/CCC": [{"name": "spaces/CCC/messages/1", "sender": {"name": "users/9"}, "createTime": at(YESTERDAY, 9),
                    "text": "Secret acquisition talk"}],
    "spaces/DDD": [{"name": "spaces/DDD/messages/1", "sender": {"name": "users/9"}, "createTime": at(YESTERDAY, 9),
                    "text": "Lunch?"}],
}


class FakeGoogle(BaseHTTPRequestHandler):
    state = {"grant": " ".join(sorted(READ_ONLY)), "deny": False, "revoked": [], "refreshes": 0, "requested_scope": None,
             "challenge": None, "fail_space": None}

    def log_message(self, *args):
        pass

    def reply(self, status, body, headers=None):
        data = json.dumps(body).encode()
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        s = self.state
        if url.path == "/auth":
            s["requested_scope"], s["challenge"] = q["scope"], q["code_challenge"]
            target = q["redirect_uri"] + "?" + urllib.parse.urlencode(
                {"error": "access_denied", "state": q["state"]} if s["deny"] else {"code": "CODE1", "state": q["state"]})
            return self.reply(302, {}, {"Location": target})
        if self.headers.get("Authorization") != "Bearer ACCESS":
            return self.reply(401, {"error": "unauthenticated"})
        if url.path == "/chat/spaces":
            page = int(q.get("pageToken", 0))
            return self.reply(200, {"spaces": SPACES[page * 3:page * 3 + 3], **({"nextPageToken": "1"} if page == 0 else {})})
        space = url.path.removeprefix("/chat/").removesuffix("/messages")
        if space == s["fail_space"]:
            return self.reply(500, {"error": "backend"})
        low, high = [part.split('"')[1] for part in q["filter"].split(" AND ")]
        found = [m for m in MESSAGES.get(space, []) if low < m["createTime"] < high]
        page = int(q.get("pageToken", 0))
        size = int(q["pageSize"])
        more = len(found) > (page + 1) * size
        return self.reply(200, {"messages": found[page * size:(page + 1) * size], **({"nextPageToken": str(page + 1)} if more else {})})

    def do_POST(self):
        fields = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode()).items()}
        s = self.state
        if self.path == "/oauth/revoke":
            s["revoked"].append(fields["token"])
            return self.reply(200, {})
        if fields["grant_type"] == "authorization_code":
            verifier_ok = base64.urlsafe_b64encode(hashlib.sha256(fields["code_verifier"].encode()).digest()).rstrip(b"=").decode() == s["challenge"]
            if fields["code"] != "CODE1" or not verifier_ok:
                return self.reply(400, {"error": "invalid_grant"})
            claims = base64.urlsafe_b64encode(json.dumps({"email": "me@acme.com", "sub": "42"}).encode()).decode().rstrip("=")
            return self.reply(200, {"access_token": "ACCESS", "expires_in": 3600, "refresh_token": "REFRESH",
                                    "scope": s["grant"], "id_token": f"h.{claims}.sig"})
        s["refreshes"] += 1
        if fields.get("refresh_token") != "REFRESH":
            return self.reply(400, {"error": "invalid_grant"})
        return self.reply(200, {"access_token": "ACCESS", "expires_in": 3600})


fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeGoogle)
threading.Thread(target=fake.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{fake.server_address[1]}"
os.environ.update({"HOME": str(TMP), "XDG_DATA_HOME": str(TMP / "data"), "XDG_CONFIG_HOME": str(TMP / "config"),
                   "XDG_RUNTIME_DIR": str(TMP / "run"), "CLAUDE_CONFIG_DIR": str(TMP / "claude"),
                   "PWI_SECRET_STORE": "file", "PWI_GOOGLE_AUTH_URL": f"{BASE}/auth",
                   "PWI_GOOGLE_OAUTH_URL": f"{BASE}/oauth", "PWI_GOOGLE_API_URL": f"{BASE}/chat"})
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]

import admin  # noqa: E402
import chat  # noqa: E402
import google_signin as google  # noqa: E402
import handlers  # noqa: E402
import paths  # noqa: E402
import store  # noqa: E402


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def browser(url):
    """Stands in for me clicking Allow: Google's page redirects to the layer's loopback address."""
    urllib.request.urlopen(url, timeout=10).read()


def main():
    os.umask(0o077)
    store.create_or_check(paths.STORE_PATH)
    db = store.connect(paths.STORE_PATH)
    layer = handlers.Layer(paths.STORE_PATH)

    def call(name, args=None):
        text = layer.call_tool(name, args or {})["content"][0]["text"]
        return json.loads(text.split("\n", 1)[1].rsplit("\n", 1)[0])

    client = TMP / "client.json"
    client.write_text(json.dumps({"installed": {"client_id": "abc.apps.googleusercontent.com", "client_secret": "s"}}))
    (TMP / "bad.json").write_text("{}")

    # signing in
    try:
        google.connect(TMP / "bad.json", browser)
        check("a file that isn't an OAuth client is refused", False)
    except google.GoogleError as e:
        check("a file that isn't an OAuth client is refused", "no client_id" in str(e))
    FakeGoogle.state["deny"] = True
    try:
        google.connect(client, browser, wait=10)
        check("cancelling on Google's page stops the sign-in", False)
    except google.GoogleError as e:
        check("cancelling on Google's page stops the sign-in", "access_denied" in str(e) and google.load_token() is None)
    FakeGoogle.state.update(deny=False, grant=" ".join(sorted(READ_ONLY | {"https://www.googleapis.com/auth/chat.messages"})))
    try:
        google.connect(client, browser, wait=10)
        check("a sign-in that grants write access is revoked and refused", False)
    except google.GoogleError as e:
        check("a sign-in that grants write access is revoked and refused",
              "more than read access" in str(e) and "REFRESH" in FakeGoogle.state["revoked"] and google.load_token() is None)
    FakeGoogle.state["grant"] = " ".join(sorted(READ_ONLY))
    done = google.connect(client, browser, wait=10)
    check("only read-only scopes are requested", set(FakeGoogle.state["requested_scope"].split()) == READ_ONLY)
    check("signing in with PKCE stores the sign-in owner-only, and says where",
          done["email"] == "me@acme.com" and done["stored_in"] == str(google.TOKEN_FILE)
          and google.TOKEN_FILE.stat().st_mode & 0o777 == 0o600 and google.CLIENT_PATH.stat().st_mode & 0o777 == 0o600
          and json.loads(google.TOKEN_FILE.read_text())["refresh_token"] == "REFRESH")
    check("status says who is signed in", google.status()["connected"] and google.status()["email"] == "me@acme.com")

    # the allowlist, enforced in code
    off = call("chat_spaces")
    check("with Google Chat off in my settings, nothing is read", off["found"] is False and "off in my settings" in off["gaps"][0]
          and FakeGoogle.state["refreshes"] == 0)
    admin.set_connector(db, "google_chat", {"enabled": True, "scope": "Billing team"})
    for name in ("work", "deals"):
        db.execute("INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)", (name, name, store.now()))
    admin.add_alias(db, "work", "chat_space", "Data guild")
    admin.add_alias(db, "deals", "chat_space", "Deal room")
    db.execute("INSERT INTO labels VALUES ('project', 'deals', 'confidential', 'me', ?)", (store.now(),))
    spaces = call("chat_spaces")
    check("only spaces in the scope or linked to a project are read, across pages, and never a confidential project's",
          [(s["name"], s["project"]) for s in spaces["spaces"]] == [("Billing team", None), ("Data guild", "work")]
          and spaces["outside_my_allowlist"] == 3 and spaces["signed_in_as"] == "me@acme.com")
    admin.set_connector(db, "google_chat", {"scope": ""})
    check("an empty scope means every space, still never a confidential project's",
          {s["name"] for s in call("chat_spaces")["spaces"]} == {"Billing team", "Data guild", "Random", "Direct message"})
    admin.set_connector(db, "google_chat", {"scope": "Billing team"})

    # messages
    day = YESTERDAY.isoformat()
    read = call("chat_messages", {"since": day})
    texts = [m["text"] for m in read["messages"]]
    check("messages come from allowed spaces only, within the days asked, oldest first",
          not any("Lunch" in t or "acquisition" in t or "old message" in t for t in texts)
          and set(read["spaces_read"]) == {"Billing team", "Data guild"} and len(read["messages"]) == 152)
    mine = [m for m in read["messages"] if m["from_me"]]
    check("each message has an artifact id to cite, and says whether I wrote it",
          len(mine) == 1 and mine[0]["artifact_id"] == "chat:spaces/AAA/messages/1" and mine[0]["artifact_kind"] == "message"
          and mine[0]["from"] == "Me")
    check("secrets in messages are redacted", TOKEN not in json.dumps(read) and any("[REDACTED]" in t for t in texts))
    check("from_me, space and query narrow it down",
          [m["text"] for m in call("chat_messages", {"since": day, "from_me": True})["messages"]] == [mine[0]["text"]]
          and len(call("chat_messages", {"since": day, "space": "data guild"})["messages"]) == 150
          and [m["text"] for m in call("chat_messages", {"since": day, "query": "vat ana"})["messages"]] == [mine[0]["text"]])
    check("a space outside the allowlist can't be asked for by name",
          "No space 'Random'" in call("chat_messages", {"since": day, "space": "Random"})["gaps"][0])
    check("the access token is refreshed once and reused", FakeGoogle.state["refreshes"] == 1)
    FakeGoogle.state["fail_space"] = "spaces/BBB"
    partial = call("chat_messages", {"since": day})
    check("an error from Google is reported, with what was read until then",
          any("500" in g for g in partial["gaps"]) and partial["found"] is True)
    FakeGoogle.state["fail_space"] = None
    check("validation applies to the chat tools too",
          "since is required" in layer.call_tool("chat_messages", {})["content"][0]["text"])
    db.close()
    raw = Path(paths.STORE_PATH).read_bytes() + (Path(f"{paths.STORE_PATH}-wal").read_bytes()
                                                 if Path(f"{paths.STORE_PATH}-wal").exists() else b"")
    check("nothing read from Chat is stored", b"VAT notes" not in raw and b"Pipeline note" not in raw)
    db = store.connect(paths.STORE_PATH)
    chat_row = next(c for c in admin.connectors(db) if c["provider"] == "google_chat")
    check("the frontend shows Google Chat is read through the layer, and who is signed in",
          chat_row["through_layer"] and chat_row["signed_in_as"] == "me@acme.com")

    # signing out
    cli = subprocess.run([sys.executable, "-I", str(HERE / "cli.py"), "google", "status"], capture_output=True, text=True)
    check("pwi google status says who is signed in", cli.returncode == 0 and "me@acme.com" in cli.stdout)
    check("disconnecting revokes the sign-in at Google and forgets it",
          google.disconnect() and FakeGoogle.state["revoked"][-1] == "REFRESH" and not google.TOKEN_FILE.exists()
          and not google.CLIENT_PATH.exists())
    chat.SESSION.access_token = None
    check("signed out, the chat tools say how to sign in again",
          "pwi google connect" in call("chat_spaces")["gaps"][0])
    db.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        fake.shutdown()
        shutil.rmtree(TMP, ignore_errors=True)
