"""The end-of-day review in Google Chat: the claims waiting for confirmation, posted as cards to my
direct message with the layer's Chat app, and my answers applied when I click.

Only my click verifies a claim, as Claude Desktop's approval prompt does in the chat review. A click
counts only when all of these hold, and anything else is dropped and logged:
- Google Chat says it came from me: the Google account of the layer's read-only sign-in, a person;
- in my direct message with the app, the one the layer recorded when I opened it;
- on a card the layer posted, for an item of that card;
- for the version of the claim the card showed, still waiting for confirmation.
Claude never takes part here: it saves claims during the run, and the layer posts them. The answer
is recorded as my change, like an edit in the frontend: confirm and correct make it verified.
"""

import html
import logging
import secrets
import threading
import time
from contextlib import closing
from datetime import date, datetime

import admin
import chat_app
import google_signin as google
import store
import writes
from reads import claims as open_claims, evidence_list

log = logging.getLogger("pwi")
PER_CARD = 5  # claims per card message, as the chat review shows them 5 at a time
MOST = 30  # claims per review; the rest follow once these are answered
MAX_TRIES = 5  # attempts at an event that keeps failing, before it's dropped
TYPE_NAMES = {"decision": "Decision", "commitment": "Commitment", "blocker": "Blocker", "fact": "Fact"}
LABELS = {"proposed": "unconfirmed", "disputed": "disputed"}
ACTIONS = {  # button -> (answer, new status, reason recorded on the version)
    "confirm": ("confirmed", "supported", "confirmed in the Chat review"),
    "correct": ("corrected", "supported", "corrected in the Chat review"),
    "dispute": ("disputed", "disputed", "questioned in the Chat review"),
    "retract": ("retracted", "retracted", "retracted in the Chat review"),
}
ANSWERS = {"confirmed": "✅ Confirmed", "corrected": "✏️ Corrected", "disputed": "❓ Disputed",
           "retracted": "❌ Retracted", "changed": "↻ Changed since this card was posted; it's in the next review",
           "moved": "→ Moved to a newer review",
           "hidden": "Marked confidential since this card was posted, so it isn't shown here any more"}


def day_label(day):
    return date.fromisoformat(day).strftime("%a %d %b")


def local_time(at):
    try:
        return datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except (AttributeError, ValueError):
        return ""


def esc(text):
    return html.escape(text or "", quote=False)


# Who and where ------------------------------------------------------------------------

def me():
    """My Google identity, from the layer's read-only sign-in: the only person whose clicks count."""
    record = google.load_token() or {}
    if not record.get("sub"):
        return None
    return {"name": f"users/{record['sub']}", "email": (record.get("email") or "").lower()}


def is_me(user, mine):
    user = user or {}
    if not mine or user.get("name") != mine["name"] or user.get("type", "HUMAN") != "HUMAN":
        return False
    return not user.get("email") or not mine["email"] or user["email"].lower() == mine["email"]


def is_dm(space):
    space = space or {}
    return space.get("spaceType") == "DIRECT_MESSAGE" or space.get("type") == "DM" or bool(space.get("singleUserBotDm"))


def review_space(db):
    return store.setting(db, "chat_app.space")


# What a card shows ----------------------------------------------------------------------

def evidence_text(db, claim_id, version):
    parts = []
    for e in evidence_list(db, claim_id, version)[:3]:
        if e.get("event_id"):
            row = db.execute("SELECT title FROM events WHERE id = ?", (e["event_id"],)).fetchone()
            parts.append(esc((row["title"] if row and row["title"] else e["event_id"])[:120]))
        elif e.get("url", "").startswith(("https://", "http://")):
            parts.append(f'<a href="{html.escape(e["url"])}">{esc((e.get("title") or e["artifact_id"])[:120])}</a>')
        else:
            parts.append(esc((e.get("title") or e.get("artifact_id") or "")[:120]))
    return " · ".join(p for p in parts if p)


def button(text, function, item_id):
    return {"text": text, "onClick": {"action": {"function": function, "parameters": [{"key": "item", "value": item_id}]}}}


def shareable(db, claim_id):
    """The claim's current version, unless it's confidential now (a label on it, its project or its evidence)."""
    return db.execute("SELECT * FROM claims_shareable WHERE id = ?", (claim_id,)).fetchone()


def section(db, item, today):
    """One claim on a card. Every redraw goes through the confidential filter, so a claim labelled confidential
    after it was posted loses its text and buttons at the next redraw."""
    claim = shareable(db, item["claim_id"])
    if claim is None:
        gone = db.execute("SELECT 1 FROM current_claims WHERE id = ?", (item["claim_id"],)).fetchone() is None
        return {"header": str(item["position"]),
                "widgets": [{"textParagraph": {"text": "<i>Deleted.</i>" if gone else f"<i>{ANSWERS['hidden']}.</i>"}}]}
    project = db.execute("SELECT name FROM projects WHERE id = ?", (claim["project_id"],)).fetchone()
    shown = db.execute("SELECT * FROM claim_versions WHERE claim_id = ? AND version = ?",
                       (item["claim_id"], item["version"])).fetchone() or claim
    head = [str(item["position"]), TYPE_NAMES.get(claim["type"], claim["type"])]
    if project:
        head.append(project["name"])
    about = claim["about_day"] or claim["first_proposed_at"][:10]
    if about != today:
        head.append(f"from {day_label(about)}")
    widgets = []
    if item["answer"]:
        if item["answer"] == "corrected":  # the version my correction made, not whatever came after it
            shown = db.execute("SELECT * FROM claim_versions WHERE claim_id = ? AND version = ?",
                               (item["claim_id"], item["version"] + 1)).fetchone() or shown
        text = esc(shown["text"])
        widgets.append({"textParagraph": {"text": f"<s>{text}</s>" if item["answer"] == "retracted" else text}})
        widgets.append({"textParagraph": {"text": f"<b>{ANSWERS[item['answer']]}</b> {local_time(item['answered_at'])}"}})
        return {"header": " · ".join(head), "widgets": widgets}
    widgets.append({"textParagraph": {"text": esc(shown["text"])}})
    details = [f"{k} {esc(v)}" for k, v in (("Due", shown["due_at"]), ("Owner", shown["owner"]),
                                            ("With", shown["counterparty"])) if v]
    details.append(LABELS.get(shown["status"], shown["status"]))
    widgets.append({"decoratedText": {"text": " · ".join(details), "wrapText": True}})
    proof = evidence_text(db, item["claim_id"], item["version"])
    if proof:
        widgets.append({"decoratedText": {"topLabel": "Evidence", "text": proof, "wrapText": True}})
    widgets.append({"textInput": {"name": f"fix_{item['id']}", "label": "Correct it in your words, then Save correction",
                                  "type": "MULTIPLE_LINE"}})
    widgets.append({"buttonList": {"buttons": [button("Confirm", "confirm", item["id"]),
                                               button("Save correction", "correct", item["id"]),
                                               button("Dispute", "dispute", item["id"]),
                                               button("Retract", "retract", item["id"])]}})
    return {"header": " · ".join(head), "widgets": widgets}


def card(db, batch, items):
    total = db.execute("SELECT COUNT(*) FROM review_items WHERE batch_id = ?", (batch["id"],)).fetchone()[0]
    first, last = items[0]["position"], items[-1]["position"]
    return {"cardsV2": [{"cardId": f"claims-{first}", "card": {
        "header": {"title": f"Claims {first}–{last} of {total}" if first != last else f"Claim {first} of {total}",
                   "subtitle": f"End-of-day review, {day_label(batch['day'])}"},
        "sections": [section(db, item, batch["day"]) for item in items]}}]}


def message_id(batch_id, position):
    """A custom message id, so a retried post lands on the same message: lowercase, digits and hyphens."""
    return f"client-pwi-{batch_id.removeprefix('rvb_')}-{position}"


# Posting a review -----------------------------------------------------------------------

def pending(db):
    """What the chat review lists: every claim proposed or disputed, session notes aside. Oldest first: by the
    day it's about, then when it was proposed."""
    return open_claims(db, "status IN ('proposed', 'disputed') AND type <> 'session_note'",
                       order="COALESCE(about_day, substr(first_proposed_at, 1, 10)), first_proposed_at, seq")


def post_text(app, space, text, mid=None):
    return app.post(space, {"text": text}, mid)


def post_batch(db, app, day, continuation=False, keep=None):
    """Posts the claims waiting for confirmation to my DM with the app. Returns what was posted."""
    space = review_space(db)
    if not space:
        return {"posted": 0, "gaps": ["The Chat app has no conversation with you yet. In Google Chat, open a direct "
                                      "message with the app; the layer records it and posts there from then on."]}
    seen = {r[0] for r in db.execute("SELECT i.claim_id FROM review_items i JOIN review_batches b ON b.id = i.batch_id"
                                     " WHERE b.day = ?", (day,))} if continuation else set()
    waiting = [c for c in pending(db) if c["claim_id"] not in seen]
    if not waiting:
        if not continuation:
            post_text(app, space, f"*End-of-day review, {day_label(day)}*: nothing to confirm today.")
        return {"posted": 0, "waiting": 0}
    chosen = waiting[:MOST]
    batch_id = "rvb_" + secrets.token_hex(6)

    def create():
        old = [r["id"] for r in db.execute("SELECT id FROM review_batches WHERE status = 'open'") if r["id"] != keep]
        for old_id in old:
            db.execute("UPDATE review_messages SET stale = 1 WHERE batch_id = ? AND name IN"
                       " (SELECT message FROM review_items WHERE batch_id = ? AND answer IS NULL)", (old_id, old_id))
            db.execute("UPDATE review_items SET answer = 'moved', answered_at = ? WHERE batch_id = ? AND answer IS NULL",
                       (store.now(), old_id))
            db.execute("UPDATE review_batches SET status = 'replaced' WHERE id = ?", (old_id,))
        db.execute("INSERT INTO review_batches (id, day, space, posted_at, status) VALUES (?, ?, ?, ?, 'open')",
                   (batch_id, day, space, store.now()))
        for position, c in enumerate(chosen, 1):
            db.execute("INSERT INTO review_items (id, batch_id, position, claim_id, version) VALUES (?, ?, ?, ?, ?)",
                       ("rvi_" + secrets.token_hex(6), batch_id, position, c["claim_id"], c["version"]))

    writes.transaction(db, create)
    refresh(db, app)
    return {"posted": len(chosen), "waiting": len(waiting), "batch": batch_id}


def header(db, batch):
    """The review's first message: how many claims, and where the notes are."""
    items = db.execute("SELECT i.*, c.about_day FROM review_items i LEFT JOIN current_claims c ON c.id = i.claim_id"
                       " WHERE i.batch_id = ?", (batch["id"],)).fetchall()
    earlier = sum(1 for i in items if (i["about_day"] or batch["day"]) < batch["day"])
    continued = db.execute("SELECT 1 FROM review_batches WHERE day = ? AND posted_at < ? AND id <> ?",
                           (batch["day"], batch["posted_at"], batch["id"])).fetchone()
    shown = {r[0] for r in db.execute("SELECT i.claim_id FROM review_items i JOIN review_batches b ON b.id = i.batch_id"
                                      " WHERE b.day = ?", (batch["day"],))}
    later = sum(1 for c in pending(db) if c["claim_id"] not in shown)
    folder = store.setting(db, "eod.folder", "Work") if store.setting(db, "eod.vault") else None
    return (f"*End-of-day review, {day_label(batch['day'])}*{' (continued)' if continued else ''}: "
            f"{len(items)} claim{'s' if len(items) != 1 else ''} to confirm"
            + (f", {earlier} from earlier days" if earlier else "") + ". Answer each with its buttons."
            + (f" {later} more will follow once these are answered." if later else "")
            + (f"\nNotes: {folder}/Daily/{batch['day']}" if folder else ""))


def post_once(db, app, batch, body, mid):
    """Posts one message of a review, once: a retry of a post Google already made answers 409, and the
    message is then named by its custom id."""
    try:
        name = app.post(batch["space"], body, mid).get("name")
    except chat_app.AppError as e:
        if "409" not in str(e):
            raise
        name = None
    name = name or f"{batch['space']}/messages/{mid}"
    db.execute("INSERT OR IGNORE INTO review_messages (name, batch_id) VALUES (?, ?)", (name, batch["id"]))
    return name


def refresh(db, app):
    """Posts what isn't posted yet (after a post that failed: the header, then the cards) and redraws the
    cards whose answers changed. A claim labelled confidential since it was posted is marked hidden first, so its
    card is redrawn without it and it never holds up the end of the review."""
    for item in db.execute("SELECT i.* FROM review_items i JOIN review_batches b ON b.id = i.batch_id"
                           " WHERE b.status = 'open' AND i.answer IS NULL"
                           " AND i.claim_id NOT IN (SELECT id FROM claims_shareable)").fetchall():
        mark(db, item, "hidden")
    for batch in db.execute("SELECT * FROM review_batches WHERE status = 'open'").fetchall():
        has_header = db.execute("SELECT 1 FROM review_messages m WHERE m.batch_id = ? AND NOT EXISTS"
                                " (SELECT 1 FROM review_items i WHERE i.message = m.name)", (batch["id"],)).fetchone()
        if not has_header:
            post_once(db, app, batch, {"text": header(db, batch)}, message_id(batch["id"], 0))
        unposted = db.execute("SELECT * FROM review_items WHERE batch_id = ? AND message IS NULL AND answer IS NULL"
                              " ORDER BY position", (batch["id"],)).fetchall()
        groups = {}
        for item in unposted:
            groups.setdefault((item["position"] - 1) // PER_CARD, []).append(item)
        for _, items in sorted(groups.items()):
            name = post_once(db, app, batch, card(db, batch, items), message_id(batch["id"], items[0]["position"]))
            db.executemany("UPDATE review_items SET message = ? WHERE id = ?", [(name, i["id"]) for i in items])
    for m in db.execute("SELECT * FROM review_messages WHERE stale = 1").fetchall():
        batch = db.execute("SELECT * FROM review_batches WHERE id = ?", (m["batch_id"],)).fetchone()
        items = db.execute("SELECT * FROM review_items WHERE message = ? ORDER BY position", (m["name"],)).fetchall()
        if items:
            app.update(m["name"], card(db, batch, items), "cardsV2")
        db.execute("UPDATE review_messages SET stale = 0 WHERE name = ?", (m["name"],))


# My answers -----------------------------------------------------------------------------

def invoked(event):
    """The button's function and parameters, from either form Google Chat sends."""
    common, action = event.get("common") or {}, event.get("action") or {}
    params = dict(common.get("parameters") or {})
    for p in action.get("parameters") or []:
        params.setdefault(p.get("key"), p.get("value"))
    return common.get("invokedFunction") or action.get("actionMethodName"), params


def form_value(event, name):
    field = ((event.get("common") or {}).get("formInputs") or {}).get(name) or {}
    values = (field.get("stringInputs") or {}).get("value") or []
    return (values[0] if values else "").strip()


def same_message(stored, message):
    """Whether the click came from the card holding this item. A card the layer named after its custom id
    (when Google's answer to the post got lost) matches the event's clientAssignedMessageId instead."""
    if not stored:
        return False
    custom = message.get("clientAssignedMessageId")
    return stored == message.get("name") or bool(custom) and stored.endswith(f"/messages/{custom}")


def mark(db, item, answer):
    db.execute("UPDATE review_items SET answer = ?, answered_at = ? WHERE id = ?", (answer, store.now(), item["id"]))
    if item["message"]:
        db.execute("UPDATE review_messages SET stale = 1 WHERE name = ?", (item["message"],))


def apply(db, item, action, text=None):
    """Records my answer as my change to the claim, and the item as answered, in one transaction.
    Returns the answer, or 'changed' if the claim moved on since the card was posted."""
    def work():
        fresh = db.execute("SELECT * FROM review_items WHERE id = ?", (item["id"],)).fetchone()
        if fresh is None or fresh["answer"]:
            return fresh["answer"] if fresh else None  # a click Google Chat delivered twice
        if shareable(db, item["claim_id"]) is None and db.execute(
                "SELECT status FROM current_claims WHERE id = ?", (item["claim_id"],)).fetchone() is not None:
            mark(db, fresh, "hidden")  # labelled confidential since the card was posted
            return "hidden"
        claim = db.execute("SELECT * FROM current_claims WHERE id = ?", (item["claim_id"],)).fetchone()
        if claim is None or claim["version"] != item["version"] or claim["status"] not in ("proposed", "disputed"):
            mark(db, fresh, "changed")
            return "changed"
        answer, status, reason = ACTIONS[action]
        changes = {"text": text, "method": "me"} if action == "correct" and text != claim["text"] else {}
        if action == "correct" and not changes:
            answer, reason = "confirmed", ACTIONS["confirm"][2]
        if changes or status != claim["status"]:
            version = writes.add_version(db, claim["id"], claim, changes, status, "me", reason)
            writes.carry_evidence(db, claim["id"], claim["version"], version)
            admin.audit(db, "revise" if changes else "set_status", "claim", claim["id"])
        mark(db, fresh, answer)
        return answer

    return writes.transaction(db, work)


def summary(db, day):
    counts = dict(db.execute("SELECT i.answer, COUNT(*) FROM review_items i JOIN review_batches b ON b.id = i.batch_id"
                             " WHERE b.day = ? AND i.answer IN ('confirmed', 'corrected', 'disputed', 'retracted')"
                             " GROUP BY i.answer", (day,)).fetchall())
    parts = [f"{counts[a]} {a}" for a in ("confirmed", "corrected", "disputed", "retracted") if counts.get(a)]
    return ", ".join(parts) or "nothing answered"


def post_quietly(app, space, text, mid):
    """A message posted once: a retry after Google already took it answers 409, which means done."""
    try:
        app.post(space, {"text": text}, mid)
    except chat_app.AppError as e:
        if "409" not in str(e):
            raise


def finished(db, app, batch_id, on_answered):
    """When every item of a review is answered: post the next claims, or say what I answered and start the notes
    rewrite. The review is marked answered only once that worked: if a post fails, the review stays open and the
    listener's next pass (settle) does it again, and the posts carry custom ids, so a retry never posts twice."""
    batch = db.execute("SELECT * FROM review_batches WHERE id = ?", (batch_id,)).fetchone()
    left = db.execute("SELECT COUNT(*) FROM review_items WHERE batch_id = ? AND answer IS NULL", (batch_id,)).fetchone()[0]
    if batch is None or left or batch["status"] != "open":
        return False
    done = False
    continued = db.execute("SELECT 1 FROM review_batches WHERE day = ? AND id <> ? AND status = 'open'",
                           (batch["day"], batch_id)).fetchone()  # made by an earlier try whose posts failed
    if not continued:
        more = post_batch(db, app, batch["day"], continuation=True, keep=batch_id)
        if not more.get("posted"):
            post_quietly(app, batch["space"], f"Done for {day_label(batch['day'])}: {summary(db, batch['day'])}. "
                                              "Updating the day's notes in Obsidian with your answers.",
                         message_id(batch_id, "done"))
            if on_answered:
                on_answered(batch["day"])
            done = True
    db.execute("UPDATE review_batches SET status = 'answered' WHERE id = ? AND status = 'open'", (batch_id,))
    return done


def settle(db, app, on_answered):
    """Finishes the reviews whose items are all answered but weren't finished: a post failed, or the last
    open items were hidden."""
    for batch in db.execute("SELECT id FROM review_batches b WHERE status = 'open' AND NOT EXISTS"
                            " (SELECT 1 FROM review_items i WHERE i.batch_id = b.id AND i.answer IS NULL)").fetchall():
        finished(db, app, batch["id"], on_answered)


def handle(db, app, event, mine, on_answered=None):
    """One event from Google Chat. Returns what happened, for the log."""
    kind, user, space = event.get("type"), event.get("user") or {}, event.get("space") or {}
    mine_now = is_me(user, mine)
    if kind == "ADDED_TO_SPACE":
        if not mine_now:
            return "added by someone else: ignored"
        if not is_dm(space):
            post_text(app, space["name"], "I only work in a direct message with you, so nobody else sees your claims. "
                                          "Remove me from here and open a direct message with me instead.")
            return "added to a shared space: refused"
        store.set_setting(db, "chat_app.space", space["name"])
        at = store.setting(db, "eod.at", "19:30")
        post_text(app, space["name"], f"Hi! This is where I'll ask you to confirm what I saved about your day, at {at} "
                                      "on workdays. Answer each card with its buttons; only your clicks count.")
        return "review space recorded"
    if kind == "REMOVED_FROM_SPACE":
        if space.get("name") == review_space(db):
            store.set_setting(db, "chat_app.space", None)
            return "review space removed"
        return "removed from a space"
    if space.get("name") != review_space(db) or not mine_now:
        return f"{kind or 'event'} from {'someone else' if not mine_now else 'another space'}: dropped"
    if kind == "MESSAGE":
        row = db.execute("SELECT COUNT(*) FROM review_items i JOIN review_batches b ON b.id = i.batch_id"
                         " WHERE b.status = 'open' AND i.answer IS NULL").fetchone()
        post_text(app, space["name"], f"{row[0]} claim{'s' if row[0] != 1 else ''} still waiting, in the cards above."
                  if row[0] else "Nothing is waiting. The next review comes at " + store.setting(db, "eod.at", "19:30") + ".")
        return "status sent"
    if kind != "CARD_CLICKED":
        return f"{kind}: ignored"
    function, params = invoked(event)
    item = db.execute("SELECT * FROM review_items WHERE id = ?", (params.get("item") or "",)).fetchone()
    if function not in ACTIONS or item is None:
        return "click on something the layer didn't post: dropped"
    if not same_message(item["message"], event.get("message") or {}):
        return "click from another card than the item's own: dropped"
    text = None
    if function == "correct":
        text = form_value(event, f"fix_{item['id']}")
        if not text:
            post_text(app, space["name"], f"To correct claim {item['position']}, write the correction in its box first, "
                                          "then press Save correction.")
            return "empty correction"
    answer = apply(db, item, function, text)
    refresh(db, app)
    finished(db, app, item["batch_id"], on_answered)
    return f"claim {item['claim_id']}: {answer}"


# The thread the service runs ------------------------------------------------------------

class Listener:
    """Pulls the Chat app's events while it's connected: long requests that end as soon as I click,
    so a card updates about a second after the click. Checks for a connection every few minutes."""

    def __init__(self, store_path, on_answered=None, wait=30, idle=300):
        self.store_path, self.on_answered, self.wait, self.idle = store_path, on_answered, wait, idle
        self.stopping = threading.Event()
        self.thread = None
        self.last_error = None
        self.tries = {}  # Pub/Sub message id -> failed attempts

    def start(self):
        self.thread = threading.Thread(target=self.run, name="chat-app", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(2)

    def failed(self, error):
        text = str(error)
        if text != self.last_error:
            log.warning("chat app: %s", text)
            self.last_error = text
            try:
                with closing(store.connect(self.store_path)) as db:
                    store.set_setting(db, "chat_app.last_error", f"{store.now()} {text}")
            except Exception:
                pass

    def run(self):
        app, checked = None, 0
        while not self.stopping.is_set():
            if app is None or time.monotonic() - checked > self.idle:
                checked = time.monotonic()
                if not chat_app.connected():  # never connected, or pwi chat-app disconnect since
                    app = None
                    self.stopping.wait(self.idle)
                    continue
                app = app or chat_app.App()
            try:
                self.once(app)
                self.last_error = None
            except chat_app.AppError as e:
                self.failed(e)
                app = None if "isn't connected" in str(e) else app
                self.stopping.wait(60)
            except Exception as e:
                log.exception("chat app listener")
                self.failed(e)
                self.stopping.wait(60)

    def once(self, app):
        with closing(store.connect(self.store_path)) as db:
            refresh(db, app)
            settle(db, app, self.on_answered)
        events = app.pull(wait=True, timeout=self.wait)
        if not events:
            return 0
        mine = me()
        handled = []
        with closing(store.connect(self.store_path)) as db:
            for ack, event, message in events:
                try:
                    log.info("chat app: %s", handle(db, app, event, mine, self.on_answered))
                    handled.append(ack)
                    self.tries.pop(message, None)
                except Exception as e:
                    # Not acknowledged, so Pub/Sub delivers it again: handling is idempotent, and a click whose
                    # answer wasn't saved (a locked store, Google unreachable) gets another chance.
                    tries = self.tries[message] = self.tries.get(message, 0) + 1
                    if tries >= MAX_TRIES:
                        log.error("chat app: dropping an event that failed %d times: %s", tries, e)
                        handled.append(ack)
                        self.tries.pop(message, None)
                    elif isinstance(e, chat_app.AppError):
                        self.failed(e)
                    else:
                        log.exception("chat app event")
            store.set_setting(db, "chat_app.last_event_at", store.now())
        app.ack(handled)
        return len(handled)
