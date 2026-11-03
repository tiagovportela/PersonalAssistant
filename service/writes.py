"""The write tools: how Claude saves what it identifies back into the layer.

Writes only add: a claim, a new version of one, evidence, a link or a label.
Nothing is ever deleted or edited in place, and only set_claim_status (which
Claude Desktop asks me to approve every time) records a change as mine. Each
call runs in one transaction and goes into the audit log.

A write that can't be done raises Refused; the service turns that into a tool
error that says what to fix, and nothing is saved.
"""

import json
import re
import secrets
import unicodedata

import contradictions
import store
from collect_git import github_repo
from reads import LABELS, OPEN, find_project

DATE_OR_TIME = re.compile(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}Z)?")
CONTENT_FIELDS = ("text", "project", "about_day", "due_at", "owner", "confidence")


class Refused(Exception):
    """A write that can't be done as asked. The message says what to fix."""


def fold(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def normalised(text):
    return " ".join(re.findall(r"\w+", fold(text)))


def audit(db, action, item_type, item_id, actor="claude"):
    db.execute("INSERT INTO audit_log (at, actor, action, item_type, item_id) VALUES (?, ?, ?, ?, ?)",
               (store.now(), actor, action, item_type, item_id))


def transaction(db, work):
    db.execute("BEGIN IMMEDIATE")
    try:
        result = work()
        db.execute("COMMIT")
        return result
    except BaseException:
        db.execute("ROLLBACK")
        raise


def check_fields(db, args):
    if args.get("due_at") and not DATE_OR_TIME.fullmatch(args["due_at"]):
        raise Refused("due_at must be a date (2026-11-06) or a UTC time (2026-11-06T17:00:00Z).")
    if args.get("project") and find_project(db, args["project"]) is None:
        raise Refused(f"There's no project '{args['project']}'. Call list_projects for the ids.")


def visible_claim(db, claim_id):
    claim = db.execute("SELECT * FROM claims_for_claude WHERE id = ?", (claim_id,)).fetchone()
    if claim is None:
        raise Refused(f"There's no claim {claim_id}, or it was retracted. Search for it with search.")
    if claim["status"] == "superseded":
        raise Refused(f"Claim {claim_id} was superseded; work with the claim that replaced it.")
    return claim


def save_evidence(db, items):
    """Evidence rows for a new claim version. Local evidence must be an event Claude was shown;
    online evidence stores the reference only (id, kind, title, link, when read), never the content."""
    ids, projects, now = [], set(), store.now()
    for i, item in enumerate(items):
        if "event_id" in item:
            event = db.execute("SELECT id, project_id FROM events_for_claude WHERE id = ?", (item["event_id"],)).fetchone()
            if event is None:
                raise Refused(f"evidence[{i}].event_id {item['event_id']} isn't an event the layer has. Use an "
                              "event_id from get_day, get_week, get_project, search or read_claude_sessions.")
            projects.add(event["project_id"])
            ids.append(db.execute("INSERT INTO evidence (event_id, locator, created_at) VALUES (?, ?, ?)",
                                  (event["id"], item.get("locator"), now)).lastrowid)
        else:
            db.execute("INSERT INTO artifacts (id, kind, title, url, first_seen_at) VALUES (?, ?, ?, ?, ?)"
                       " ON CONFLICT (id) DO UPDATE SET title = COALESCE(excluded.title, title),"
                       " url = COALESCE(excluded.url, url)",
                       (item["artifact_id"], item["artifact_kind"], item.get("title"), item.get("url"), now))
            ids.append(db.execute("INSERT INTO evidence (artifact_id, locator, read_at, source_version, created_at)"
                                  " VALUES (?, ?, ?, ?, ?)", (item["artifact_id"], item.get("locator"), item["read_at"],
                                                              item.get("source_version"), now)).lastrowid)
    return ids, projects - {None}


def same_evidence(db, claim_id, version):
    """Keys of a version's evidence, so the same item isn't attached twice."""
    return {(r["event_id"], r["artifact_id"]) for r in db.execute(
        "SELECT ev.event_id, ev.artifact_id FROM claim_evidence ce JOIN evidence ev ON ev.id = ce.evidence_id"
        " WHERE ce.claim_id = ? AND ce.version = ?", (claim_id, version))}


def attach(db, claim_id, version, evidence_ids):
    for evidence_id in evidence_ids:
        db.execute("INSERT OR IGNORE INTO claim_evidence VALUES (?, ?, ?)", (claim_id, version, evidence_id))


def new_items(db, claim_id, version, items):
    """The evidence items not already attached to a claim version."""
    have = same_evidence(db, claim_id, version)
    return [e for e in items if (e.get("event_id"), e.get("artifact_id") if "event_id" not in e else None) not in have]


def add_version(db, claim_id, current, changes, status, changed_by, reason):
    version = current["version"] + 1 if current else 1
    fields = {k: (current["project_id" if k == "project" else k] if current else None) for k in CONTENT_FIELDS}
    fields.update({k: v for k, v in changes.items() if k in CONTENT_FIELDS})
    db.execute("INSERT INTO claim_versions (claim_id, version, status, text, project_id, about_day, due_at, owner,"
               " confidence, method, changed_by, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (claim_id, version, status, fields["text"], fields["project"], fields["about_day"], fields["due_at"],
                fields["owner"], fields["confidence"], current["method"] if current else "claude", changed_by,
                reason, store.now()))
    return version


def carry_evidence(db, claim_id, old_version, new_version):
    db.execute("INSERT INTO claim_evidence SELECT claim_id, ?, evidence_id FROM claim_evidence"
               " WHERE claim_id = ? AND version = ?", (new_version, claim_id, old_version))


def current(db, claim_id):
    return db.execute("SELECT * FROM current_claims WHERE id = ?", (claim_id,)).fetchone()


def result_for(db, claim_id, **extra):
    c = current(db, claim_id)
    return {"claim_id": claim_id, "version": c["version"], "label": LABELS.get(c["status"], c["status"]), **extra}


# Tools -----------------------------------------------------------------------

def propose_claim(db, args):
    check_fields(db, args)
    text = args["text"].strip()

    def work():
        # With no project given, use the evidence's project when it all comes from one.
        events = [e["event_id"] for e in args["evidence"] if "event_id" in e]
        projects = {r[0] for r in db.execute("SELECT DISTINCT project_id FROM events_for_claude WHERE id IN"
                                             " (SELECT value FROM json_each(?))", (json.dumps(events),))} - {None}
        project = args.get("project") or (projects.pop() if len(projects) == 1 else None)
        duplicate = db.execute(
            f"SELECT * FROM claims_for_claude WHERE type = ? AND project_id IS ? AND status IN {OPEN}",
            (args["type"], project)).fetchall()
        for c in duplicate:
            if normalised(c["text"]) == normalised(text):
                ids, _ = save_evidence(db, new_items(db, c["id"], c["version"], args["evidence"]))
                attach(db, c["id"], c["version"], ids)
                return result_for(db, c["id"], created=False)
        evidence_ids, _ = save_evidence(db, args["evidence"])
        claim_id = "clm_" + secrets.token_hex(5)
        db.execute("INSERT INTO claims (id, type, created_at) VALUES (?, ?, ?)", (claim_id, args["type"], store.now()))
        version = add_version(db, claim_id, None, {**args, "text": text, "project": project}, "proposed", "claude", None)
        attach(db, claim_id, version, evidence_ids)
        audit(db, "propose", "claim", claim_id)
        result = result_for(db, claim_id, created=True, project=project)
        conflicts, similar = contradictions.for_claim(db, claim_id)
        if conflicts:
            result["possible_contradictions"] = [{"claim": next(c for c in p["claims"] if c["claim_id"] != claim_id),
                                                  "why": p["why"]} for p in conflicts]
            result["hint"] = ("These claims are about the same thing and may disagree with the new one. Tell me, and "
                              "ask which holds: if they conflict, link them with link_items (rel: contradicts); if "
                              "the new one replaces an old one, link it (rel: supersedes) and ask me to mark the old "
                              "one superseded; if they don't conflict, link them (rel: related). Nothing is overwritten.")
        if similar:
            result["similar_claims"] = similar
        return result

    return transaction(db, work)


def update_claim(db, args):
    check_fields(db, args)

    def work():
        claim = visible_claim(db, args["claim_id"])
        changes = {k: args[k] for k in CONTENT_FIELDS if k in args}
        if "text" in changes:
            changes["text"] = changes["text"].strip()
        old = {"text": claim["text"], "project": claim["project_id"], "about_day": claim["about_day"],
               "due_at": claim["due_at"], "owner": claim["owner"], "confidence": claim["confidence"]}
        changed = {k: v for k, v in changes.items() if old[k] != v}
        extra = new_items(db, claim["id"], claim["version"], args.get("add_evidence", []))
        if not changed and not extra:
            raise Refused("Nothing would change: the fields given are the same as the current version.")
        evidence_ids, _ = save_evidence(db, extra)
        if not changed:
            # More evidence for the same content: it joins the current version, so a verified claim stays verified.
            attach(db, claim["id"], claim["version"], evidence_ids)
            audit(db, "revise", "claim", claim["id"])
            return result_for(db, claim["id"], new_version=False)
        # Different content is a new claim to check: it's unconfirmed until I confirm it.
        version = add_version(db, claim["id"], claim, changed, "proposed", "claude", args["reason"])
        carry_evidence(db, claim["id"], claim["version"], version)
        attach(db, claim["id"], version, evidence_ids)
        audit(db, "revise", "claim", claim["id"])
        return result_for(db, claim["id"], new_version=True, was=LABELS.get(claim["status"]))

    return transaction(db, work)


def save_session_note(db, args):
    project = find_project(db, args["project"])
    if project is None:
        raise Refused(f"There's no project '{args['project']}'. Call list_projects for the ids.")

    def work():
        sessions = []
        for session_id in args["session_ids"]:
            e = db.execute("SELECT * FROM events_for_claude WHERE id = ? AND type = 'claude_code.session'",
                           (session_id,)).fetchone()
            if e is None:
                raise Refused(f"{session_id} isn't a Claude Code session the layer has. Use the session_id values "
                              "from read_claude_sessions.")
            if e["project_id"] != project["id"]:
                raise Refused(f"{session_id} belongs to project '{e['project_id']}', not '{project['id']}'. "
                              "Write one note per project.")
            sessions.append({"event_id": session_id})
        note = db.execute("SELECT * FROM current_claims WHERE type = 'session_note' AND project_id = ? AND about_day = ?",
                          (project["id"], args["day"])).fetchone()
        evidence_ids, _ = save_evidence(db, sessions)
        if note is None:
            claim_id = "clm_" + secrets.token_hex(5)
            db.execute("INSERT INTO claims (id, type, created_at) VALUES (?, 'session_note', ?)", (claim_id, store.now()))
            version = add_version(db, claim_id, None, {"text": args["text"].strip(), "project": project["id"],
                                                        "about_day": args["day"]}, "proposed", "claude", None)
            created = True
        else:
            claim_id = note["id"]
            version = add_version(db, claim_id, note, {"text": args["text"].strip()}, "proposed", "claude",
                                  "session note rewritten")
            created = False
        attach(db, claim_id, version, evidence_ids)
        audit(db, "propose" if created else "revise", "claim", claim_id)
        return result_for(db, claim_id, created=created)

    return transaction(db, work)


ITEM_TABLES = {"event": "events_for_claude", "artifact": "artifacts", "claim": "claims_for_claude",
               "project": "projects"}


def check_item(db, item, label):
    if item["type"] not in ITEM_TABLES:
        raise Refused(f"{label}.type can't be '{item['type']}' here; use event, artifact, claim or project.")
    if item["type"] == "project":
        row = find_project(db, item["id"])
    else:
        row = db.execute(f"SELECT id FROM {ITEM_TABLES[item['type']]} WHERE id = ?", (item["id"],)).fetchone()
    if row is None:
        raise Refused(f"{label}: there's no {item['type']} {item['id']}.")


def link_items(db, args):
    def work():
        check_item(db, args["from"], "from")
        check_item(db, args["to"], "to")
        if args["from"] == args["to"]:
            raise Refused("An item can't be linked to itself.")
        created = db.execute("INSERT OR IGNORE INTO links VALUES (?, ?, ?, ?, ?, 'claude', ?)",
                             (args["from"]["type"], args["from"]["id"], args["rel"], args["to"]["type"],
                              args["to"]["id"], store.now())).rowcount == 1
        result = {"created": created}
        if args["rel"] == "contradicts" and args["from"]["type"] == args["to"]["type"] == "claim":
            disputed = []
            for item in (args["from"], args["to"]):
                claim = visible_claim(db, item["id"])
                if claim["status"] != "disputed":
                    version = add_version(db, claim["id"], claim, {}, "disputed", "claude",
                                          f"contradicts {args['to' if item is args['from'] else 'from']['id']}")
                    carry_evidence(db, claim["id"], claim["version"], version)
                disputed.append(result_for(db, claim["id"]))
            result["disputed"] = disputed
        if created:
            audit(db, "link", args["from"]["type"], args["from"]["id"])
        return result

    return transaction(db, work)


def set_claim_status(db, args):
    """Recorded as my change: Claude Desktop asked me to approve this call."""
    def work():
        claim = visible_claim(db, args["claim_id"])
        if claim["status"] == args["status"]:
            return result_for(db, claim["id"], changed=False)
        version = add_version(db, claim["id"], claim, {}, args["status"], "me",
                              args.get("reason") or {"supported": "confirmed", "disputed": "questioned",
                                                     "retracted": "retracted", "superseded": "replaced"}[args["status"]])
        carry_evidence(db, claim["id"], claim["version"], version)
        audit(db, "set_status", "claim", claim["id"], actor="me")
        return result_for(db, claim["id"], changed=True)

    return transaction(db, work)


LABEL_TABLES = {"source": "sources", "project": "projects", "event": "events", "artifact": "artifacts", "claim": "claims"}


def add_confidential_label(db, args):
    """Claude can add the label, with my approval, but never remove it."""
    item = args["item"]

    def work():
        key = int(item["id"]) if item["type"] == "source" and item["id"].isdigit() else item["id"]
        if db.execute(f"SELECT 1 FROM {LABEL_TABLES[item['type']]} WHERE id = ?", (key,)).fetchone() is None:
            raise Refused(f"There's no {item['type']} {item['id']}.")
        added = db.execute("INSERT OR IGNORE INTO labels VALUES (?, ?, 'confidential', 'claude', ?)",
                           (item["type"], str(item["id"]), store.now())).rowcount == 1
        if added:
            audit(db, "label", item["type"], str(item["id"]))
        return {"item": item, "labelled": True, "already_labelled": not added}

    return transaction(db, work)


def add_project_alias(db, args):
    """Claude records where a project lives online; only I remove aliases, in the frontend."""
    project = find_project(db, args["project"])
    if project is None:
        raise Refused(f"There's no project '{args['project']}'. Call list_projects for the ids.")
    kind, value = args["kind"], args["value"].strip()
    if kind == "github_repo" and "github.com" in value:
        value = github_repo(value) or value  # a link to the repository becomes owner/repo
    if kind == "github_repo" and not re.fullmatch(r"[\w.-]+/[\w.-]+", value):
        raise Refused("github_repo is owner/repo, e.g. acme/billing-service.")

    def work():
        row = db.execute("SELECT project_id FROM project_aliases WHERE kind = ? AND value = ?", (kind, value)).fetchone()
        if row and row["project_id"] == project["id"]:
            return {"project": project["id"], "kind": kind, "value": value, "created": False}
        if row:
            owner = find_project(db, row["project_id"])  # never name a confidential project
            raise Refused(f"That {kind} already belongs to {'project ' + owner['id'] if owner else 'another project'}. "
                          "Tell me if it should move; I change it in the frontend.")
        db.execute("INSERT INTO project_aliases VALUES (?, ?, ?, 'claude', ?)", (kind, value, project["id"], store.now()))
        audit(db, "link", "project", project["id"])
        return {"project": project["id"], "kind": kind, "value": value, "created": True}

    return transaction(db, work)


WRITES = {"propose_claim": propose_claim, "update_claim": update_claim, "save_session_note": save_session_note,
          "link_items": link_items, "set_claim_status": set_claim_status,
          "add_confidential_label": add_confidential_label, "add_project_alias": add_project_alias}
