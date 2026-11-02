"""Google Chat, read live through the layer's own read-only Google sign-in.

Nothing is stored: messages go straight to Claude, redacted and marked as data.
Unlike the other connectors, the allowlist is enforced here, in code: Google
Chat must be on in my settings; only spaces named in its scope, or linked to a
project with a chat_space alias, are read (an empty scope means every space);
and the spaces of a confidential project are never read.
"""

import os
import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone

import google_signin as google
from redact import redact

API = os.environ.get("PWI_GOOGLE_API_URL", "https://chat.googleapis.com/v1")
MAX_SPACES = 50  # spaces read per call, most recently active first
MAX_MESSAGES = 300
MAX_TEXT = 2000
SESSION = google.Session()


def fold(text):
    return "".join(c for c in unicodedata.normalize("NFKD", (text or "").lower()) if not unicodedata.combining(c))


def allowlist(db):
    """(on, names in the scope, names linked to projects {name: project}, names of confidential projects' spaces)."""
    row = db.execute("SELECT enabled, scope FROM connectors WHERE provider = 'google_chat'").fetchone()
    scope = {fold(s).strip() for s in re.split(r"[,\n;]", (row["scope"] or "") if row else "") if s.strip()}
    linked, hidden = {}, set()
    for a in db.execute("SELECT a.value, a.project_id, EXISTS (SELECT 1 FROM labels l WHERE l.item_type = 'project'"
                        " AND l.item_id = a.project_id) AS confidential FROM project_aliases a WHERE a.kind = 'chat_space'"):
        if a["confidential"]:
            hidden.add(fold(a["value"]).strip())
        else:
            linked[fold(a["value"]).strip()] = a["project_id"]
    return bool(row and row["enabled"]), scope, linked, hidden


def keys(space):
    return {fold(space["name"]), fold(space.get("displayName"))} - {""}


def readable(space, scope, linked, hidden):
    names = keys(space)
    if names & hidden:
        return False
    return not scope or bool(names & (scope | set(linked)))


def all_spaces(token):
    spaces, page = [], None
    while True:
        answer = google.get_json(f"{API}/spaces", token, {"pageSize": 1000, **({"pageToken": page} if page else {})})
        spaces += answer.get("spaces", [])
        page = answer.get("nextPageToken")
        if not page:
            return spaces


def label(space):
    if space.get("displayName"):
        return space["displayName"]
    return "Direct message" if space.get("spaceType") == "DIRECT_MESSAGE" else "Group chat"


def utc(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local(text):
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone().isoformat(timespec="minutes")
    except (AttributeError, ValueError):
        return text


def unavailable(db):
    on, *_ = allowlist(db)
    if not on:
        return {"found": False, "gaps": ["Google Chat is off in my settings, so don't read it. I can turn it on "
                                         "in the frontend's Online sources page."]}
    return None


def chat_spaces(db, args):
    closed = unavailable(db)
    if closed:
        return closed
    _, scope, linked, hidden = allowlist(db)
    try:
        spaces = all_spaces(SESSION.token())
        me = SESSION.me()
    except google.GoogleError as e:
        return {"found": False, "gaps": [str(e)]}
    allowed = [s for s in spaces if readable(s, scope, linked, hidden)]
    allowed.sort(key=lambda s: s.get("lastActiveTime") or "", reverse=True)
    result = {"signed_in_as": me.get("email"), "found": bool(allowed),
              "spaces": [{"space": s["name"], "name": label(s), "type": s.get("spaceType"),
                          "last_active": local(s.get("lastActiveTime")),
                          "project": next((linked[k] for k in keys(s) if k in linked), None)} for s in allowed],
              "outside_my_allowlist": len(spaces) - len(allowed)}
    if not allowed:
        result["gaps"] = ["No Google Chat space is within my allowlist."]
    return result


def chat_messages(db, args):
    closed = unavailable(db)
    if closed:
        return closed
    _, scope, linked, hidden = allowlist(db)
    first = date.fromisoformat(args["since"])
    last = date.fromisoformat(args.get("until") or args["since"])
    start = datetime.combine(first, time()).astimezone()
    end = datetime.combine(last + timedelta(days=1), time()).astimezone()
    try:
        token = SESSION.token()
        me = SESSION.me()
        spaces = [s for s in all_spaces(token) if readable(s, scope, linked, hidden)]
    except google.GoogleError as e:
        return {"found": False, "gaps": [str(e)]}
    gaps = []
    if args.get("space"):
        wanted = fold(args["space"]).strip()
        spaces = [s for s in spaces if wanted in keys(s)]
        if not spaces:
            return {"found": False, "gaps": [f"No space '{args['space']}' within my allowlist. Call chat_spaces for the names."]}
    active = [s for s in spaces if not s.get("lastActiveTime") or s["lastActiveTime"] >= utc(start)]
    active.sort(key=lambda s: s.get("lastActiveTime") or "", reverse=True)
    if len(active) > MAX_SPACES:
        gaps.append(f"{len(active)} spaces were active; only the {MAX_SPACES} most recent were read. Name a space to read others.")
        active = active[:MAX_SPACES]
    mine = f"users/{me.get('sub')}" if me.get("sub") else None
    query = fold(args.get("query") or "").split()
    messages = []
    try:
        for space in active:
            page = None
            while len(messages) < MAX_MESSAGES:
                params = {"pageSize": 100, "orderBy": "createTime asc",
                          "filter": f'createTime > "{utc(start)}" AND createTime < "{utc(end)}"'}
                if page:
                    params["pageToken"] = page
                answer = google.get_json(f"{API}/{space['name']}/messages", token, params)
                for m in answer.get("messages", []):
                    sender = m.get("sender") or {}
                    item = {"artifact_id": f"chat:{m['name']}", "artifact_kind": "message", "space": label(space),
                            "space_id": space["name"], "at": local(m.get("createTime")),
                            "from": sender.get("displayName") or sender.get("name"),
                            "from_me": bool(mine) and sender.get("name") == mine,
                            "text": redact((m.get("text") or m.get("formattedText") or "").strip())[:MAX_TEXT],
                            "thread": (m.get("thread") or {}).get("name")}
                    if "from_me" in args and item["from_me"] != args["from_me"]:
                        continue
                    if query and not all(w in fold(item["text"]) for w in query):
                        continue
                    messages.append(item)
                page = answer.get("nextPageToken")
                if not page:
                    break
            if len(messages) >= MAX_MESSAGES:
                gaps.append(f"Stopped at {MAX_MESSAGES} messages. Narrow it with a space, fewer days or words.")
                break
    except google.GoogleError as e:
        gaps.append(str(e))
    messages.sort(key=lambda m: m["at"] or "")
    result = {"since": args["since"], "until": last.isoformat(), "signed_in_as": me.get("email"),
              "spaces_read": [label(s) for s in active], "messages": messages, "found": bool(messages)}
    if not messages:
        gaps.append(f"No messages found from {args['since']} to {last.isoformat()} in the spaces I allow.")
    if gaps:
        result["gaps"] = gaps
    return result


CHAT_READS = {"chat_spaces": chat_spaces, "chat_messages": chat_messages}
