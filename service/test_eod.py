"""Checks the end-of-day agent against a fake Google and a fake Claude Code running locally: the Chat
app's own token (a JWT signed here, checked by the fake), recording my direct message with the app,
posting the review as cards, every rule a click must pass before it changes a claim, my answers
recorded as mine, the review rolling over and wrapping up, the tool list the agent gets, the 19:30
run and the rewrite after my answers, the timers, and commitments' counterparty.

Run: python3 -I service/test_eod.py
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import shlex
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pwi-eod-"))
HERE = Path(__file__).resolve().parent
TODAY = date.today().isoformat()
SUB = "projects/acme-work/subscriptions/pwi-chat-events"
DM, GROUP = "spaces/DM1", "spaces/GROUP1"
ME = {"name": "users/42", "displayName": "Me", "email": "me@acme.com", "type": "HUMAN"}
ANA = {"name": "users/7", "displayName": "Ana", "email": "ana@acme.com", "type": "HUMAN"}


# A test key, made here so no private key is ever committed -------------------------------

def probable_prime(n):
    if n % 2 == 0:
        return n == 2
    d, r = n - 1, 0
    while d % 2 == 0:
        d, r = d // 2, r + 1
    for _ in range(24):
        x = pow(secrets.randbelow(n - 3) + 2, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def prime(bits):
    while True:
        candidate = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if all(candidate % p for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31)) and probable_prime(candidate):
            return candidate


def der(tag, body):
    size = len(body)
    length = bytes([size]) if size < 128 else bytes([0x80 | ((size.bit_length() + 7) // 8)]) + size.to_bytes((size.bit_length() + 7) // 8, "big")
    return bytes([tag]) + length + body


def der_int(i):
    return der(0x02, i.to_bytes(i.bit_length() // 8 + 1, "big"))


def test_key():
    e = 65537
    while True:
        p, q = prime(1024), prime(1024)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            break
    n, d = p * q, pow(e, -1, phi)
    pkcs1 = der(0x30, b"".join(der_int(x) for x in (0, n, e, d, p, q, d % (p - 1), d % (q - 1), pow(q, -1, p))))
    algorithm = der(0x30, der(0x06, bytes.fromhex("2a864886f70d010101")) + der(0x05, b""))
    body = base64.b64encode(der(0x30, der_int(0) + algorithm + der(0x04, pkcs1))).decode()
    pem = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(body[i:i + 64] for i in range(0, len(body), 64)) + "\n-----END PRIVATE KEY-----\n"
    return pem, n, e


PEM, N, E = test_key()


def unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# A fake Google: the token endpoint, Chat and Pub/Sub -------------------------------------

class FakeGoogle(BaseHTTPRequestHandler):
    state = {"messages": {}, "posts": [], "updates": [], "queue": [], "acks": [], "tokens": 0, "bad_jwt": 0,
             "fail_posts": False, "next": 0}

    def log_message(self, *args):
        pass

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_POST(self):
        s, url = self.state, urllib.parse.urlsplit(self.path)
        raw = self.body()
        if url.path == "/oauth/token":
            fields = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode()).items()}
            if fields.get("grant_type") == "refresh_token":
                return self.reply(200, {"access_token": "USER", "expires_in": 3600})
            header, claims, signature = fields["assertion"].split(".")
            digest = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(f"{header}.{claims}".encode()).digest()
            size = (N.bit_length() + 7) // 8
            expected = b"\x00\x01" + b"\xff" * (size - len(digest) - 3) + b"\x00" + digest
            c = json.loads(unb64(claims))
            if (pow(int.from_bytes(unb64(signature), "big"), E, N).to_bytes(size, "big") != expected
                    or json.loads(unb64(header))["alg"] != "RS256" or c["aud"] != "https://oauth2.googleapis.com/token"
                    or c["iss"] != "pwi-app@acme-work.iam.gserviceaccount.com" or "chat.bot" not in c["scope"]):
                s["bad_jwt"] += 1
                return self.reply(400, {"error": "invalid_grant"})
            s["tokens"] += 1
            return self.reply(200, {"access_token": "APP", "expires_in": 3600})
        if self.headers.get("Authorization") != "Bearer APP":
            return self.reply(401, {"error": "unauthenticated"})
        if url.path.startswith("/pubsub/"):
            if url.path.endswith(":pull"):
                events, s["queue"] = s["queue"], []
                return self.reply(200, {"receivedMessages": [
                    {"ackId": f"ack-{i}-{secrets.token_hex(2)}",
                     "message": {"data": base64.b64encode(json.dumps(e).encode()).decode(),
                                 "messageId": hashlib.sha256(json.dumps(e, sort_keys=True).encode()).hexdigest()[:12]}}
                    for i, e in enumerate(events)]})
            s["acks"] += json.loads(raw)["ackIds"]
            return self.reply(200, {})
        if s["fail_posts"]:
            return self.reply(503, {"error": "unavailable"})
        space = url.path.removeprefix("/chat/").removesuffix("/messages")
        custom = urllib.parse.parse_qs(url.query).get("messageId", [None])[0]
        if custom and any(m.get("clientAssignedMessageId") == custom for m in s["messages"].values()):
            return self.reply(409, {"error": "ALREADY_EXISTS"})
        s["next"] += 1
        name = f"{space}/messages/m{s['next']}"
        message = {"name": name, **json.loads(raw), **({"clientAssignedMessageId": custom} if custom else {})}
        s["messages"][name] = message
        s["posts"].append(message)
        return self.reply(200, message)

    def do_PATCH(self):
        s, url = self.state, urllib.parse.urlsplit(self.path)
        if self.headers.get("Authorization") != "Bearer APP":
            return self.reply(401, {"error": "unauthenticated"})
        name = url.path.removeprefix("/chat/")
        update = json.loads(self.body())
        s["updates"].append((name, urllib.parse.parse_qs(url.query)["updateMask"][0], update))
        s["messages"].setdefault(name, {"name": name}).update(update)
        return self.reply(200, s["messages"][name])


fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeGoogle)
threading.Thread(target=fake.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{fake.server_address[1]}"
os.environ.update({"HOME": str(TMP), "XDG_DATA_HOME": str(TMP / "data"), "XDG_CONFIG_HOME": str(TMP / "config"),
                   "XDG_RUNTIME_DIR": str(TMP / "run"), "CLAUDE_CONFIG_DIR": str(TMP / "claude"),
                   "PWI_SECRET_STORE": "file", "PWI_NO_SYSTEMD": "1", "PWI_GOOGLE_OAUTH_URL": f"{BASE}/oauth",
                   "PWI_GOOGLE_API_URL": f"{BASE}/chat", "PWI_PUBSUB_URL": f"{BASE}/pubsub",
                   "ANTHROPIC_API_KEY": "sk-ant-should-not-reach-claude", "FAKE_CLAUDE_LOG": str(TMP / "claude-calls.jsonl")})
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]

import chat_app  # noqa: E402
import eod  # noqa: E402
import google_signin as google  # noqa: E402
import handlers  # noqa: E402
import paths  # noqa: E402
import review  # noqa: E402
import store  # noqa: E402
import writes  # noqa: E402


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


# A fake Claude Code: reports its tools at init, and does a run's work in the notes folder ---------

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, re, sys, time
args = sys.argv[1:]
mode = args[args.index("--output-format") + 1]
if mode == "stream-json":
    if os.environ.get("FAKE_CLAUDE_HANG"):
        time.sleep(30)
    tools = ["Task", "Bash", "Glob", "Grep", "Read", "Edit", "Write", "WebFetch", "WebSearch", "TodoWrite", "ToolSearch",
             "mcp__pwi__get_day", "mcp__pwi__list_unconfirmed", "mcp__pwi__propose_claim", "mcp__pwi__save_session_note",
             "mcp__pwi__set_claim_status", "mcp__pwi__read_confidential", "mcp__pwi__add_confidential_label",
             "mcp__claude_ai_Notion__notion-search", "mcp__claude_ai_Notion__notion-fetch",
             "mcp__claude_ai_Notion__notion-get-comments", "mcp__claude_ai_Notion__notion-create-pages",
             "mcp__claude_ai_Notion__notion-update-page", "mcp__claude_ai_Notion__notion-create-comment",
             "mcp__claude_ai_Google_Drive__search_files", "mcp__claude_ai_Google_Drive__read_file_content",
             "mcp__claude_ai_Google_Drive__download_file_content", "mcp__claude_ai_Google_Drive__share_file",
             "mcp__claude_ai_Google_Drive__request_access", "mcp__claude_ai_Google_Drive__trash_file",
             "mcp__claude_ai_Gmail__search_threads", "mcp__claude_ai_Gmail__get_thread", "mcp__claude_ai_Gmail__create_draft",
             "mcp__claude_ai_Gmail__send_message", "mcp__claude_ai_Google_Calendar__list_events",
             "mcp__claude_ai_Google_Calendar__find_free_time", "mcp__claude_ai_Google_Calendar__respond_to_event",
             "mcp__claude_ai_GitHub__pull_request_read", "mcp__claude_ai_GitHub__get_label",
             "mcp__claude_ai_GitHub__merge_pull_request", "mcp__claude_ai_GitHub__actions_run_trigger",
             "mcp__claude_ai_Slack__slack_status"]
    print(json.dumps({"type": "system", "subtype": "init", "tools": tools,
                      "mcp_servers": [{"name": "pwi", "status": "connected"}, {"name": "claude.ai Notion", "status": "connected"}]}),
          flush=True)
    time.sleep(30)
    sys.exit(0)
prompt = sys.stdin.read()
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as log:
    log.write(json.dumps({"argv": args, "cwd": os.getcwd(), "prompt": prompt,
                          "api_key": "ANTHROPIC_API_KEY" in os.environ}) + "\n")
if os.environ.get("FAKE_CLAUDE_FAIL"):
    print(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "result": "stopped"}))
    sys.exit(1)
day = re.search(r"\d{4}-\d{2}-\d{2}", [l for l in prompt.splitlines() if l.startswith("You run by yourself")][0]).group()
folder = os.path.join("Daily", day)
os.makedirs(folder, exist_ok=True)
with open(os.path.join(folder, day + " Executive summary.md"), "a") as note:
    note.write("finish\n" if "after my review" in prompt else "run\n")
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 9, "duration_ms": 90000,
                  "result": "Notes written.", "permission_denials": [{"tool_name": "mcp__claude_ai_Gmail__send_message"}]}))
'''


def claude_calls():
    log = Path(os.environ["FAKE_CLAUDE_LOG"])
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


# Helpers -------------------------------------------------------------------------------------

def event(kind, user=ME, space=DM, **extra):
    space_body = {"name": space, "spaceType": "DIRECT_MESSAGE" if space == DM else "SPACE",
                  **({"singleUserBotDm": True} if space == DM else {})}
    return {"type": kind, "user": user, "space": space_body, **extra}


def click(item, function="confirm", user=ME, space=DM, text=None, message=None, legacy=False):
    body = {"message": {"name": message or item["message"]}}
    if legacy:
        body["action"] = {"actionMethodName": function, "parameters": [{"key": "item", "value": item["id"]}]}
    else:
        body["common"] = {"invokedFunction": function, "parameters": {"item": item["id"]},
                          **({"formInputs": {f"fix_{item['id']}": {"stringInputs": {"value": [text]}}}} if text is not None else {})}
    return event("CARD_CLICKED", user, space, **body)


def propose(db, text, kind="fact", **extra):
    evidence = [{"artifact_id": f"gmail:{secrets.token_hex(4)}", "artifact_kind": "message", "title": "Re: VAT",
                 "url": "https://mail.google.com/mail/u/0/#inbox/1", "read_at": "2026-11-26T18:00:00Z"}]
    return writes.propose_claim(db, {"type": kind, "text": text, "project": "billing", "evidence": evidence, **extra})["claim_id"]


def item_of(db, claim_id):
    return db.execute("SELECT * FROM review_items WHERE claim_id = ? ORDER BY rowid DESC", (claim_id,)).fetchone()


def current(db, claim_id):
    return db.execute("SELECT * FROM current_claims WHERE id = ?", (claim_id,)).fetchone()


def all_text(message):
    return json.dumps(message, ensure_ascii=False)


def main():
    logging.disable(logging.CRITICAL)  # the failure tests log on purpose
    os.umask(0o077)
    store.create_or_check(paths.STORE_PATH)
    db = store.connect(paths.STORE_PATH)
    db.execute("INSERT INTO projects (id, name, created_at) VALUES ('billing', 'Billing API', ?)", (store.now(),))
    google.save_token({"refresh_token": "REFRESH", "scope": "openid email", "email": "me@acme.com", "sub": "42"})

    # the Chat app's identity
    key = TMP / "key.json"
    key.write_text(json.dumps({"type": "service_account", "project_id": "acme-work", "private_key_id": "k1",
                               "private_key": PEM, "client_email": "pwi-app@acme-work.iam.gserviceaccount.com"}))
    bad = TMP / "oauth-client.json"
    bad.write_text(json.dumps({"installed": {"client_id": "x"}}))
    try:
        chat_app.connect(bad)
        check("a file that isn't a service account key is refused", False)
    except chat_app.AppError as e:
        check("a file that isn't a service account key is refused", "isn't a service account key" in str(e)
              and not chat_app.connected())
    done = chat_app.connect(key, "pwi-chat-events")
    check("connecting checks the key with Google (a JWT signed here, RS256) before keeping it",
          FakeGoogle.state["tokens"] == 1 and FakeGoogle.state["bad_jwt"] == 0 and chat_app.connected()
          and done["subscription"] == SUB)
    check("the key is kept owner-only, without secret-tool", stat.S_IMODE(chat_app.KEY_FILE.stat().st_mode) == 0o600)
    app = chat_app.App()

    # where the review goes
    answered_days = []
    on_answered = answered_days.append
    mine = review.me()
    check("the layer knows me from its read-only sign-in", mine == {"name": "users/42", "email": "me@acme.com"})
    check("being added by someone else is ignored",
          review.handle(db, app, event("ADDED_TO_SPACE", ANA), mine) == "added by someone else: ignored"
          and review.review_space(db) is None)
    posts = len(FakeGoogle.state["posts"])
    check("added to a shared space, the app refuses to work there and remembers nothing",
          review.handle(db, app, event("ADDED_TO_SPACE", space=GROUP), mine) == "added to a shared space: refused"
          and review.review_space(db) is None and "direct message" in FakeGoogle.state["posts"][posts]["text"])
    check("my direct message with the app becomes the review's place, with a welcome",
          review.handle(db, app, event("ADDED_TO_SPACE"), mine) == "review space recorded"
          and review.review_space(db) == DM and "19:30" in FakeGoogle.state["posts"][-1]["text"])

    # posting the review
    old = propose(db, "We keep VAT rates in the shared sheet", "decision", about_day=(date.today() - timedelta(days=2)).isoformat())
    promise = propose(db, "Send the VAT notes to Ana by Friday", "commitment", owner="me",
                      counterparty="ana@acme.com", due_at="2026-11-28")
    tricky = propose(db, "Use <b>bold</b> & keep it")
    extra = [propose(db, f"Fact number {i}") for i in range(4)]
    note = writes.save_session_note
    check("a commitment keeps who it's promised to",
          current(db, promise)["counterparty"] == "ana@acme.com" and current(db, promise)["owner"] == "me")
    layer = handlers.Layer(paths.STORE_PATH)
    listed = json.loads(layer.call_tool("list_unconfirmed", {})["content"][0]["text"].split("\n", 1)[1].rsplit("\n", 1)[0])
    check("Claude sees the counterparty too", any(c.get("counterparty") == "ana@acme.com" for c in listed["claims"]))
    before = len(FakeGoogle.state["posts"])
    posted = review.post_batch(db, app, TODAY)
    new = FakeGoogle.state["posts"][before:]
    cards = [m for m in new if "cardsV2" in m]
    check("the review is a header and the claims as cards, 5 per card",
          posted["posted"] == 7 and len(new) == 3 and "7 claims to confirm, 1 from earlier days" in new[0]["text"]
          and [len(m["cardsV2"][0]["card"]["sections"]) for m in cards] == [5, 2])
    check("each post has a custom message id, so a retry can't post twice",
          all(m.get("clientAssignedMessageId", "").startswith("client-pwi-") for m in new))
    first = item_of(db, promise)
    text = all_text(cards)
    check("each claim shows its text, due date, owner, who it's for, label and evidence, with the four buttons",
          "Send the VAT notes to Ana by Friday" in text and "Due 2026-11-28" in text and "With ana@acme.com" in text
          and "unconfirmed" in text and 'href=\\"https://mail.google.com' in text
          and all(f'"function": "{f}"' in text for f in ("confirm", "correct", "dispute", "retract")))
    check("claim text is escaped, so it can't format or break the card", "Use &lt;b&gt;bold&lt;/b&gt; &amp; keep it" in text)
    check("every item knows the card it's on", db.execute("SELECT COUNT(*) FROM review_items WHERE message IS NULL").fetchone()[0] == 0)

    # clicks that must not count
    versions = db.execute("SELECT COUNT(*) FROM claim_versions").fetchone()[0]
    outcomes = [review.handle(db, app, click(first, user=ANA), mine),
                review.handle(db, app, click(first, user={**ME, "type": "BOT"}), mine),
                review.handle(db, app, click(first, user={**ME, "email": "other@acme.com"}), mine),
                review.handle(db, app, click(first, space=GROUP), mine),
                review.handle(db, app, click({**dict(first), "id": "rvi_forged"}), mine),
                review.handle(db, app, click(first, message=item_of(db, extra[-1])["message"]), mine),
                review.handle(db, app, click(first, function="delete"), mine),
                review.handle(db, app, click(first), None)]
    check("clicks from someone else, a bot, another account, another space, a forged item, another card, an "
          "unknown button, or before the layer knows me, change nothing",
          all("dropped" in o for o in outcomes) and db.execute("SELECT COUNT(*) FROM claim_versions").fetchone()[0] == versions)

    # my answers
    updates = len(FakeGoogle.state["updates"])
    check("my Confirm verifies the claim, as my change", review.handle(db, app, click(first), mine).endswith("confirmed")
          and current(db, promise)["status"] == "supported" and current(db, promise)["changed_by"] == "me"
          and current(db, promise)["reason"] == "confirmed in the Chat review")
    name, mask, body = FakeGoogle.state["updates"][updates]
    check("the card is redrawn at once: the answered claim shows the answer, without buttons",
          name == first["message"] and mask == "cardsV2" and "✅ Confirmed" in all_text(body)
          and all_text(body).count('"function": "confirm"') == 4)
    check("the confirmation is in the audit trail as mine",
          db.execute("SELECT actor FROM audit_log WHERE item_id = ? AND action = 'set_status'", (promise,)).fetchone()[0] == "me")
    check("a click Google delivers twice is applied once",
          review.handle(db, app, click(first), mine).endswith("confirmed")
          and db.execute("SELECT COUNT(*) FROM claim_versions WHERE claim_id = ?", (promise,)).fetchone()[0] == 2)
    it = item_of(db, tricky)
    check("an empty correction asks for the text and changes nothing",
          review.handle(db, app, click(it, "correct", text="  "), mine) == "empty correction"
          and current(db, tricky)["version"] == 1 and "write the correction" in FakeGoogle.state["posts"][-1]["text"])
    check("my correction is a new version in my words, verified",
          review.handle(db, app, click(it, "correct", text="Use bold sparingly"), mine).endswith("corrected")
          and current(db, tricky)["text"] == "Use bold sparingly" and current(db, tricky)["status"] == "supported"
          and current(db, tricky)["method"] == "me")
    it = item_of(db, old)
    check("Dispute and Retract work, from the older form of the event too",
          review.handle(db, app, click(it, "dispute", legacy=True), mine).endswith("disputed")
          and current(db, old)["status"] == "disputed"
          and review.handle(db, app, click(item_of(db, extra[0]), "retract"), mine).endswith("retracted")
          and current(db, extra[0])["status"] == "retracted")
    writes.update_claim(db, {"claim_id": extra[1], "text": "Fact number one, reworded", "reason": "clearer"})
    check("a claim that changed since its card was posted isn't confirmed by an old card",
          review.handle(db, app, click(item_of(db, extra[1])), mine).endswith("changed")
          and current(db, extra[1])["status"] == "proposed" and current(db, extra[1])["version"] == 2)
    check("a message from me in the DM gets how many are still waiting",
          review.handle(db, app, event("MESSAGE", message={"name": "x", "text": "?"}), mine) == "status sent"
          and "2 claims still waiting" in FakeGoogle.state["posts"][-1]["text"])

    # wrapping up, and the next review
    for claim_id in extra[2:]:
        review.handle(db, app, click(item_of(db, claim_id)), mine, on_answered)
    batch = db.execute("SELECT * FROM review_batches").fetchone()
    check("when everything is answered, the review says what I answered and the notes rewrite starts",
          batch["status"] == "answered" and answered_days == [TODAY]
          and "1 corrected" in FakeGoogle.state["posts"][-1]["text"] and "3 confirmed" in FakeGoogle.state["posts"][-1]["text"])
    many = [propose(db, f"Another fact {i}") for i in range(32)]
    before = len(FakeGoogle.state["posts"])
    posted = review.post_batch(db, app, TODAY)
    check("at most 30 claims per review, those about the oldest day first; the rest wait",
          posted["posted"] == 30 and "more will follow" in FakeGoogle.state["posts"][before]["text"]
          and len(FakeGoogle.state["posts"]) - before == 7
          and item_of(db, old)["position"] == 1 and item_of(db, extra[1])["position"] == 2)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    review.post_batch(db, app, tomorrow)
    replaced = db.execute("SELECT status FROM review_batches WHERE day = ? ORDER BY posted_at", (TODAY,)).fetchall()
    check("a new review replaces one still open: its cards say the claims moved",
          [r[0] for r in replaced][-1] == "replaced"
          and any("Moved to a newer review" in all_text(u[2]) for u in FakeGoogle.state["updates"][-6:]))

    # a post that failed is retried, and a lost answer doesn't post twice
    FakeGoogle.state["fail_posts"] = True
    try:
        review.post_batch(db, app, "2030-01-02")
        check("a failed post is reported", False)
    except chat_app.AppError:
        check("a failed post is reported", True)
    FakeGoogle.state["fail_posts"] = False
    before = len(FakeGoogle.state["posts"])
    review.refresh(db, app)
    open_batch = db.execute("SELECT id FROM review_batches WHERE status = 'open'").fetchone()[0]
    check("the cards of a failed post go out on the next pass",
          len(FakeGoogle.state["posts"]) - before == 7
          and db.execute("SELECT COUNT(*) FROM review_items WHERE batch_id = ? AND message IS NULL", (open_batch,)).fetchone()[0] == 0)
    lost = db.execute("SELECT * FROM review_items WHERE batch_id = ? ORDER BY position LIMIT 1", (open_batch,)).fetchone()
    db.execute("UPDATE review_items SET message = NULL WHERE message = ?", (lost["message"],))
    db.execute("DELETE FROM review_messages WHERE name = ?", (lost["message"],))
    review.refresh(db, app)
    relinked = item_of(db, lost["claim_id"])
    mid = review.message_id(open_batch, lost["position"])
    check("if Google created a card but its answer got lost, the retry finds it instead of posting it again",
          relinked["message"] == f"{DM}/messages/{mid}"
          and review.handle(db, app, click(relinked, message="spaces/DM1/messages/m999") |
                            {"message": {"name": "spaces/DM1/messages/m999", "clientAssignedMessageId": mid}}, mine).endswith("confirmed"))

    # the service's listener: pull, handle, acknowledge
    FakeGoogle.state["queue"] = [click(item_of(db, many[5])), event("REMOVED_FROM_SPACE", space=GROUP)]
    listener = review.Listener(paths.STORE_PATH, wait=1)
    check("the listener handles what Pub/Sub delivers and acknowledges it",
          listener.once(app) == 2 and len(FakeGoogle.state["acks"]) == 2
          and current(db, many[5])["status"] == "supported")
    check("removing the app from my DM forgets where the review goes",
          review.handle(db, app, event("REMOVED_FROM_SPACE"), mine) == "review space removed" and review.review_space(db) is None)
    review.handle(db, app, event("ADDED_TO_SPACE"), mine)

    # which tools the agent gets
    allowed, blocked = eod.classify([
        "mcp__pwi__get_day", "mcp__pwi__propose_claim", "mcp__pwi__set_claim_status", "mcp__pwi__read_confidential",
        "mcp__claude_ai_Notion__notion-search", "mcp__claude_ai_Notion__notion-get-comments",
        "mcp__claude_ai_Notion__notion-create-comment", "mcp__claude_ai_Google_Drive__download_file_content",
        "mcp__claude_ai_Google_Drive__request_access", "mcp__claude_ai_GitHub__pull_request_read",
        "mcp__claude_ai_GitHub__get_label", "mcp__claude_ai_GitHub__merge_pull_request", "mcp__x__frobnicate",
        "Read", "Grep", "Bash", "Edit", "Write", "WebFetch", "Artifact"])
    check("the agent gets the layer's tools but not the approval ones, connectors' tools that only read, and "
          "the built-ins that only read; nothing that writes, runs commands or fetches pages",
          set(allowed) == {"mcp__pwi__get_day", "mcp__pwi__propose_claim", "mcp__claude_ai_Notion__notion-search",
                           "mcp__claude_ai_Notion__notion-get-comments", "mcp__claude_ai_Google_Drive__download_file_content",
                           "mcp__claude_ai_GitHub__pull_request_read", "mcp__claude_ai_GitHub__get_label", "Read", "Grep"})
    check("Edit and Write are in neither list: a deny would override the run's rule that allows them in the notes folder",
          not {"Edit", "Write"} & set(allowed) and not {"Edit", "Write"} & set(blocked))
    check("an override changes one tool", eod.classify(["Artifact", "Read"], {"allow": ["Artifact"], "block": ["Read"]})
          == (["Artifact"], ["Read"]))
    check("blocking Edit denies it, and allowing it never allows edits everywhere",
          eod.classify(["Edit", "Write"], {"allow": ["Write"], "block": ["Edit"]}) == ([], ["Edit"]))

    # setting up
    vault = TMP / "My Vault"
    (vault / ".obsidian").mkdir(parents=True)
    claude = TMP / "bin" / "claude"
    claude.parent.mkdir()
    claude.write_text(FAKE_CLAUDE)
    claude.chmod(0o755)
    for bad_args, why in (({"at": "7pm"}, "HH:MM"), ({"folder": "../out"}, "inside the vault"), ({"days": "Weekdays"}, "list of days")):
        try:
            eod.setup(db, vault, claude=str(claude), systemd=False, **bad_args)
            check(f"setup refuses a bad {list(bad_args)[0]}", False)
        except eod.EodError as e:
            check(f"setup refuses a bad {list(bad_args)[0]}", why in str(e))
    done = eod.setup(db, vault, claude=str(claude), systemd=False)
    timer = (eod.UNIT_DIR / "pwi-eod.timer").read_text()
    service = (eod.UNIT_DIR / "pwi-eod.service").read_text()
    check("setup writes the timers: 19:30 on workdays, catching up a missed run, and a morning pass",
          done["is_vault"] and "OnCalendar=Mon..Fri *-*-* 19:30:00" in timer and "Persistent=true" in timer
          and "eod run" in service and f'Environment="PATH={claude.parent}:' in service
          and "OnCalendar=*-*-* 08:30:00" in (eod.UNIT_DIR / "pwi-eod-finish.timer").read_text())
    s = eod.settings(db)
    check("a run in the morning is about the last workday",
          eod.workday(s, datetime(2026, 11, 30, 8, 0)) == "2026-11-27" and eod.workday(s, datetime(2026, 11, 26, 19, 30)) == "2026-11-26")

    # the 19:30 run
    claim_count = db.execute("SELECT COUNT(*) FROM review_items").fetchone()[0]
    result = eod.run(db, TODAY)
    call = claude_calls()[-1]
    argv = call["argv"]
    allowed_tools = argv[argv.index("--allowedTools") + 1:argv.index("--disallowedTools")]
    denied_tools = argv[argv.index("--disallowedTools") + 1:]
    notes = vault / "Work"
    check("the run is recorded, with Claude's turns and the calls it was denied",
          result["status"] == "ok" and "9 turns" in result["detail"] and "mcp__claude_ai_Gmail__send_message" in result["detail"]
          and db.execute("SELECT status FROM eod_runs WHERE day = ? AND kind = 'run'", (TODAY,)).fetchone()[0] == "ok")
    check("Claude runs headless in the notes folder, in dontAsk mode, with the layer as its MCP server",
          call["cwd"] == str(notes) and argv[0] == "-p" and argv[argv.index("--permission-mode") + 1] == "dontAsk"
          and json.loads(Path(argv[argv.index("--mcp-config") + 1]).read_text())["mcpServers"]["pwi"]["args"][-1].endswith("bridge.py"))
    check("its tools: read-only connector tools and the layer without its approval tools; edits only in the notes folder",
          "mcp__claude_ai_Notion__notion-search" in allowed_tools and "mcp__claude_ai_Gmail__get_thread" in allowed_tools
          and "mcp__claude_ai_Google_Calendar__find_free_time" in allowed_tools
          and "mcp__pwi__set_claim_status" in denied_tools and "mcp__claude_ai_Gmail__send_message" in denied_tools
          and "mcp__claude_ai_Google_Drive__share_file" in denied_tools and "Bash" in denied_tools
          and "Edit" not in allowed_tools and f"Edit(/{notes}/**)" in allowed_tools
          and not {"Edit", "Write", "MultiEdit"} & set(denied_tools))
    hooks = json.loads(Path(argv[argv.index("--settings") + 1]).read_text())["hooks"]["PreToolUse"]
    command = hooks[0]["hooks"][0]["command"]
    check("the run has a PreToolUse hook on MCP tools, so connectors that load late are judged when called",
          hooks[0]["matcher"] == "mcp__.*" and "eod_hook.py" in command)

    def hook_says(tool, policy=None):
        if policy is not None:
            Path(command.rsplit('"', 2)[-2]).write_text(policy)
        done = subprocess.run(shlex.split(command), input=json.dumps({"tool_name": tool, "tool_input": {}}),
                              capture_output=True, text=True, timeout=20)
        return json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"]

    check("the hook allows a connector's read tools that weren't on the startup list, and denies the rest",
          hook_says("mcp__claude_ai_Gmail__search_threads") == "allow"
          and hook_says("mcp__claude_ai_Google_Calendar__list_events") == "allow"
          and hook_says("mcp__claude_ai_Gmail__create_label") == "deny"
          and hook_says("mcp__claude_ai_Gmail__send_message") == "deny"
          and hook_says("mcp__pwi__set_claim_status") == "deny" and hook_says("mcp__pwi__get_day") == "allow")
    check("the hook applies my overrides, and denies if it can't decide",
          hook_says("mcp__claude_ai_Gmail__search_threads", json.dumps({"overrides": {"block": ["mcp__claude_ai_Gmail__search_threads"]}})) == "deny"
          and hook_says("mcp__claude_ai_Gmail__get_thread", "not json") == "deny")
    check("an API key in the environment doesn't reach Claude Code, so it uses my claude.ai account and connectors",
          call["api_key"] is False)
    check("the prompt is the agent's instructions for the day, with the shared rules",
          f"at the end of my workday, {date.fromisoformat(TODAY).strftime('%A')} {TODAY}" in call["prompt"]
          and "#status/unconfirmed" in call["prompt"] and "# Rules for every experience" in call["prompt"]
          and "{{" not in call["prompt"])
    check("then the claims go to the Chat review", result["review"]["posted"] > 0
          and db.execute("SELECT COUNT(*) FROM review_items").fetchone()[0] > claim_count)
    check("a day that already ran isn't run again unless forced",
          eod.run(db, TODAY)["status"] == "skipped" and len(claude_calls()) == 1)
    first_run = db.execute("SELECT MAX(id) FROM eod_runs").fetchone()[0]
    reviews = db.execute("SELECT COUNT(*) FROM review_batches").fetchone()[0]
    seen = []
    ranged = eod.run_range(db, "2026-11-13", "2026-11-17", each=seen.append)
    check("a range runs each workday oldest first, skipping the weekend, and shows each as it ends",
          [r["day"] for r in ranged["days"]] == ["2026-11-13", "2026-11-16", "2026-11-17"] and seen == ranged["days"]
          and [c["prompt"].count(d) > 0 for c, d in zip(claude_calls()[-3:], ("2026-11-13", "2026-11-16", "2026-11-17"))]
          == [True, True, True])
    check("and posts one Chat review at the end, not one per day",
          db.execute("SELECT COUNT(*) FROM review_batches").fetchone()[0] - reviews <= 1
          and db.execute("SELECT COUNT(*) FROM eod_runs WHERE id > ?", (first_run,)).fetchone()[0] == 3)
    check("days that already ran are skipped in a range too",
          [r["status"] for r in eod.run_range(db, "2026-11-13", "2026-11-13")["days"]] == ["skipped"])
    for bad in (("2026-11-17", "2026-11-13"), ("2026-13-01", "2026-11-13"), ("2026-11-13", "2999-01-01")):
        try:
            eod.days_between(eod.settings(db), *bad)
            check("a range that's backwards, not a date, or in the future is refused", False)
        except eod.EodError:
            pass
    check("a range that's backwards, not a date, or in the future is refused", True)
    os.environ["FAKE_CLAUDE_FAIL"] = "1"
    failed = eod.run(db, "2026-11-20")
    del os.environ["FAKE_CLAUDE_FAIL"]
    check("a run where Claude fails is recorded as failed, with the reason", failed["status"] == "failed"
          and "stopped" in failed["detail"])

    # after my answers: the rewrite
    for row in db.execute("SELECT * FROM review_items WHERE answer IS NULL AND batch_id IN"
                          " (SELECT id FROM review_batches WHERE status = 'open')").fetchall():
        review.handle(db, app, click(row), mine, on_answered)
    check("the days to rewrite are those with answers since their notes were written", TODAY in eod.days_to_finish(db))
    results = eod.finish(db)
    call = claude_calls()[-1]
    argv = call["argv"]
    allowed_tools = argv[argv.index("--allowedTools") + 1:argv.index("--disallowedTools")]
    check("the rewrite gets my answers, get_day, and edits only in that day's folder",
          {"day": TODAY, "status": "ok"} in results and "after my review" in call["prompt"]
          and f"{promise}  confirmed  Send the VAT notes to Ana by Friday" in call["prompt"]
          and allowed_tools == ["mcp__pwi__get_day", f"Edit(/{notes / 'Daily' / TODAY}/**)"]
          and "--settings" not in argv
          and (notes / "Daily" / TODAY / f"{TODAY} Executive summary.md").read_text() == "run\nfinish\n")
    check("once rewritten, there's nothing more to do for that day", TODAY not in eod.days_to_finish(db))

    # confidential since posting: nothing more of it leaves the store
    day2 = "2030-02-04"
    secret, plain = propose(db, "Acquisition talks with Contoso", about_day=day2), propose(db, "Moved the standup", about_day=day2)
    review.post_batch(db, app, day2)
    secret_item = item_of(db, secret)
    db.execute("INSERT INTO labels VALUES ('claim', ?, 'confidential', 'me', ?)", (secret, store.now()))
    before = len(FakeGoogle.state["updates"])
    review.refresh(db, app)
    redrawn = [u for u in FakeGoogle.state["updates"][before:] if u[0] == secret_item["message"]]
    check("a claim labelled confidential after posting is hidden at the next pass: its card is redrawn without it",
          item_of(db, secret)["answer"] == "hidden" and redrawn and "Contoso" not in all_text(redrawn[-1][2])
          and "Moved the standup" in all_text(redrawn[-1][2]))
    check("and an old click on it changes nothing",
          review.handle(db, app, click(secret_item), mine).endswith("hidden") and current(db, secret)["status"] == "proposed")
    fixed = item_of(db, plain)
    review.handle(db, app, click(fixed, "correct", text="Moved the standup to 9:30"), mine, on_answered)
    writes.update_claim(db, {"claim_id": plain, "text": "Standup moved, by Claude later", "reason": "newer"})
    db.execute("UPDATE review_messages SET stale = 1 WHERE name = ?", (fixed["message"],))
    review.refresh(db, app)
    check("a corrected claim's card shows my correction, not a version that came after it",
          "Moved the standup to 9:30" in all_text(FakeGoogle.state["updates"][-1][2])
          and "by Claude later" not in all_text(FakeGoogle.state["updates"][-1][2]))
    (notes / "Daily" / day2).mkdir(parents=True)
    eod.finish(db, day2)
    prompt = claude_calls()[-1]["prompt"]
    check("the rewrite's prompt names a claim that's confidential now by its id only",
          f"{secret}  hidden  (now confidential: remove its line)" in prompt and "Contoso" not in prompt)

    # an answer that comes in while the notes are being rewritten
    day3 = "2030-02-05"
    first3, second3 = propose(db, "Fact A", about_day=day3), propose(db, "Fact B", about_day=day3)
    review.post_batch(db, app, day3)
    review.handle(db, app, click(item_of(db, first3)), mine)
    (notes / "Daily" / day3).mkdir(parents=True)
    real_ask = eod.ask_claude

    def answered_meanwhile(*args, **kwargs):
        review.handle(db, app, click(item_of(db, second3)), mine)
        return real_ask(*args, **kwargs)

    eod.ask_claude = answered_meanwhile
    eod.finish(db, day3)
    eod.ask_claude = real_ask
    check("an answer that came in during the rewrite isn't counted as in the notes: the day stays due",
          day3 in eod.days_to_finish(db) and "Fact B" not in claude_calls()[-1]["prompt"])
    eod.finish(db)
    check("and the next rewrite takes it", day3 not in eod.days_to_finish(db) and "Fact B" in claude_calls()[-1]["prompt"])

    # finishing a review is retried until it works
    day4 = "2030-02-06"
    last = propose(db, "Fact C", about_day=day4)
    review.post_batch(db, app, day4)
    batch4 = db.execute("SELECT * FROM review_batches WHERE day = ?", (day4,)).fetchone()
    for row in db.execute("SELECT * FROM review_items WHERE batch_id = ? AND claim_id <> ?", (batch4["id"], last)).fetchall():
        review.handle(db, app, click(row), mine, on_answered)  # everything else first, so this click is the last
    calls_before = len(answered_days)
    FakeGoogle.state["fail_posts"] = True
    try:
        review.handle(db, app, click(item_of(db, last)), mine, on_answered)
        check("a failed wrap-up post is reported", False)
    except chat_app.AppError:
        pass
    FakeGoogle.state["fail_posts"] = False
    batch4 = db.execute("SELECT * FROM review_batches WHERE day = ?", (day4,)).fetchone()
    check("if the closing post fails, the review stays open, its answer kept, and the rewrite isn't started yet",
          batch4["status"] == "open" and current(db, last)["status"] == "supported" and len(answered_days) == calls_before)
    review.settle(db, app, on_answered)
    review.settle(db, app, on_answered)
    done_posts = [m for m in FakeGoogle.state["posts"] if m.get("clientAssignedMessageId") == review.message_id(batch4["id"], "done")]
    check("the listener's next pass finishes it once: one closing message, and the rewrite starts",
          len(done_posts) == 1 and answered_days[calls_before:] == [day4]
          and db.execute("SELECT status FROM review_batches WHERE id = ?", (batch4["id"],)).fetchone()[0] == "answered")

    # events are acknowledged only once handled
    day5 = "2030-02-07"
    flaky = propose(db, "Fact D", about_day=day5)
    review.post_batch(db, app, day5)
    flaky_click = click(item_of(db, flaky))
    real_handle, failures = review.handle, {"left": 1}

    def locked_once(db_, app_, event_, *rest):
        if event_ is not None and event_.get("type") == "CARD_CLICKED" and failures["left"]:
            failures["left"] -= 1
            raise sqlite3.OperationalError("database is locked")
        return real_handle(db_, app_, event_, *rest)

    review.handle = locked_once
    listener = review.Listener(paths.STORE_PATH, wait=1)
    acks = len(FakeGoogle.state["acks"])
    FakeGoogle.state["queue"] = [flaky_click, event("MESSAGE", message={"name": "x", "text": "?"})]
    handled = listener.once(app)
    check("an event that failed isn't acknowledged, so Pub/Sub delivers it again; the others are",
          handled == 1 and len(FakeGoogle.state["acks"]) - acks == 1 and current(db, flaky)["status"] == "proposed")
    FakeGoogle.state["queue"] = [flaky_click]
    check("delivered again, the click is applied", listener.once(app) == 1 and current(db, flaky)["status"] == "supported")
    failures["left"] = 99
    poison = event("CARD_CLICKED", message={"name": "nowhere"}, common={"invokedFunction": "confirm", "parameters": {"item": "x"}})
    for _ in range(review.MAX_TRIES):
        FakeGoogle.state["queue"] = [poison]
        listener.once(app)
    review.handle = real_handle
    check("an event that keeps failing is dropped after a few tries, not delivered forever",
          len(FakeGoogle.state["acks"]) - acks == 3 and not listener.tries)

    # discovery has a deadline
    os.environ["FAKE_CLAUDE_HANG"] = "1"
    eod.CHECK_TIMEOUT = 2
    started = datetime.now()
    try:
        eod.check(db)
        check("a Claude Code that never starts is stopped at the deadline", False)
    except eod.EodError as e:
        check("a Claude Code that never starts is stopped at the deadline, and says so",
              "within 2 seconds" in str(e) and (datetime.now() - started).total_seconds() < 15)
    del os.environ["FAKE_CLAUDE_HANG"]

    status = eod.status(db)
    check("status shows the settings, the tools and the last runs",
          status["settings"]["folder"] == "Work" and status["tools"]["allowed"] and status["runs"][0]["kind"] == "finish")
    eod.remove_units(systemd=False)
    check("off removes the timers", not any((eod.UNIT_DIR / u).exists() for u in eod.UNITS))
    check("disconnecting forgets the app's key", chat_app.disconnect() and not chat_app.connected())
    db.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        fake.shutdown()
        shutil.rmtree(TMP, ignore_errors=True)
