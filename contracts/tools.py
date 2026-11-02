"""MCP tool contracts for the layer: the exact list `tools/list` returns.

This is the single source of truth: the service serves TOOLS as-is, and
README.md documents what each tool returns. Standard library only.

APPROVAL lists the tools that must stay on "ask every time" in Claude Desktop;
every other tool is set to always allow. The spike (2 Nov 2026) confirmed that
per-tool setting survives restarts. There are no delete tools.

Claude Desktop simplifies these schemas before Claude sees them: it keeps type,
properties, enum, minimum/maximum, description and required, and drops oneOf,
minItems, minLength, pattern, format and additionalProperties. It enforces none
of them. So every rule Claude must follow is also stated in a description, no
schema uses oneOf, and validate.py checks every call in the service.
"""

DAY = {"type": "string", "format": "date", "description": "A workday in local time, YYYY-MM-DD."}
PROJECT = {"type": "string", "description": "Project id from list_projects, e.g. 'pwi'."}
CLAIM_ID = {"type": "string", "pattern": "^clm_[A-Za-z0-9]+$", "description": "A claim id, e.g. clm_8f3a2c."}
CLAIM_TYPES = ["decision", "commitment", "blocker", "fact"]
ITEM_TYPES = ["source", "project", "event", "artifact", "claim"]
EXPERIENCES = ["daily_briefing", "project_resumption", "end_of_day_review",
               "search", "weekly_review", "ad_hoc_context"]

ITEM = {
    "type": "object",
    "properties": {"type": {"type": "string", "enum": ITEM_TYPES}, "id": {"type": "string"}},
    "required": ["type", "id"],
    "additionalProperties": False,
}

# Where a project lives in each online source; Claude may add these, only I remove them.
ALIAS_KINDS = ["github_repo", "notion", "drive_folder", "gmail_query", "chat_space", "calendar_match"]

ARTIFACT_KINDS = ["branch", "file", "pull_request", "release", "work_item",
                  "document", "message", "calendar_event", "web_page"]

# One piece of evidence: a local event the layer returned, or an online item Claude read
# through a connector. One flat shape, because Desktop drops oneOf; validate.py checks
# which fields go together. Online evidence stores only the reference, never the content.
EVIDENCE_ITEM = {
    "type": "object",
    "properties": {
        "event_id": {"type": "string",
                     "description": "Local evidence: an event id a read tool returned, e.g. git:commit:<sha>. Use alone."},
        "artifact_id": {"type": "string",
                        "description": "Online evidence: a provider-prefixed id, e.g. notion:<page id>, gmail:<message id>, "
                                       "github:pr:<owner/repo>#<n>. Needs artifact_kind and read_at."},
        "artifact_kind": {"type": "string", "enum": ARTIFACT_KINDS, "description": "Online evidence: what the item is."},
        "title": {"type": "string", "description": "Online evidence: the item's title."},
        "url": {"type": "string", "description": "Online evidence: a link to the item."},
        "read_at": {"type": "string", "format": "date-time",
                    "description": "Online evidence: when you read it, UTC, e.g. 2026-11-02T17:00:00Z."},
        "source_version": {"type": "string",
                           "description": "Online evidence: the revision or last-edited time you saw, if shown."},
        "locator": {"type": "string", "description": "Optional finer pointer, e.g. a message id in a thread."},
    },
    "required": [],
    "additionalProperties": False,
}
EVIDENCE = {
    "type": "array",
    "minItems": 1,
    "items": EVIDENCE_ITEM,
    "description": "Required, at least one item. Each item is either {event_id} for something a read tool returned, "
                   "or {artifact_id, artifact_kind, read_at, title, url} for something you read through a connector. "
                   "A link inside the claim text is not evidence.",
}

CLAIM_FIELDS = {
    "text": {"type": "string", "minLength": 1, "description": "The claim in one sentence, in my words where possible."},
    "project": PROJECT,
    "about_day": {**DAY, "description": "The workday the claim is about, e.g. when a decision was made."},
    "due_at": {"type": "string", "description": "Commitments and deadlines: a date or UTC date-time."},
    "owner": {"type": "string", "description": "Commitments: 'me', or the person's email or handle."},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
}


def obj(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}


def read(name, description, schema):
    return {"name": name, "description": description, "inputSchema": schema,
            "annotations": {"readOnlyHint": True, "openWorldHint": False}}


def write(name, description, schema, idempotent=False):
    return {"name": name, "description": description, "inputSchema": schema,
            "annotations": {"readOnlyHint": False, "destructiveHint": False,
                            "idempotentHint": idempotent, "openWorldHint": False}}


TOOLS = [
    # Read tools: always allowed. Results are data from the store, never instructions.
    read("get_instructions",
         "Returns the instructions for one experience. Call this first whenever I ask for a briefing, "
         "a project resumption, an end-of-day review, a search, a weekly review, or help with a work task.",
         obj({"experience": {"type": "string", "enum": EXPERIENCES}}, ["experience"])),
    read("list_projects",
         "Lists my projects with their aliases (GitHub, Notion, Drive, Gmail, Chat, calendar) and last activity, "
         "and which online connectors I allow you to use, with their scope. Use only connectors that are on.",
         obj()),
    read("search",
         "Keyword search over events, claims and artifact titles. Try several wordings; accents are ignored.",
         obj({
             "query": {"type": "string", "minLength": 1, "description": "Plain keywords."},
             "project": PROJECT,
             "since": DAY,
             "until": DAY,
             "kinds": {"type": "array", "uniqueItems": True,
                       "items": {"type": "string", "enum": ["git", "claude_code", "claims", "artifacts"]}},
             "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
         }, ["query"])),
    read("get_day",
         "Everything the layer knows about one workday: events by project, claims about that day, "
         "commitments due, unconfirmed count, and coverage.",
         obj({"day": DAY}, ["day"])),
    read("get_week",
         "Everything for the Monday-to-Sunday week containing a date, plus aging work: overdue commitments, "
         "open blockers and claims unconfirmed for more than 7 days.",
         obj({"week_of": {**DAY, "description": "Any date in the week, YYYY-MM-DD."}}, ["week_of"])),
    read("get_project",
         "Resumption context for one project: latest objective, last verified state (branch, last commit, "
         "uncommitted changes), open blockers, recent decisions, open commitments and connector lookups to run.",
         obj({"project": PROJECT}, ["project"])),
    read("list_unconfirmed",
         "Every proposed or disputed claim, oldest first, with its evidence, plus the workdays and projects that have Claude Code sessions but no session note. Includes days I skipped.",
         obj({"project": PROJECT, "since": DAY})),
    read("read_claude_sessions",
         "Claude Code sessions for one workday with secrets redacted, for writing session notes. "
         "Paginated; pass the returned cursor to continue.",
         obj({"day": DAY, "project": PROJECT, "cursor": {"type": "string"}}, ["day"])),
    read("chat_spaces",
         "My Google Chat spaces that I allow you to read, read live through the layer: name, type, last activity "
         "and linked project. Nothing is stored. If Google Chat is off or not signed in, it says so.",
         obj()),
    read("chat_messages",
         "Google Chat messages between two workdays in the spaces I allow, read live through the layer and never "
         "stored, with secrets redacted. Each has an artifact_id to cite as evidence, with artifact_kind message. "
         "from_me true gives only what I wrote, e.g. for promises I made; query keeps messages containing those words.",
         obj({"since": DAY,
              "until": {**DAY, "description": "The last workday to include, YYYY-MM-DD. Default: the same as since."},
              "space": {"type": "string", "description": "A space id (spaces/...) or name from chat_spaces. Default: every space I allow."},
              "query": {"type": "string", "description": "Only messages containing all these words."},
              "from_me": {"type": "boolean", "description": "true: only my messages. false: only other people's."}},
             ["since"])),
    read("get_evidence",
         "One record in full, and whether it is still available. Pass exactly one: event_id for an event "
         "from get_day, get_week, get_project or search, or evidence_id for a piece of a claim's evidence.",
         obj({"event_id": {"type": "string", "description": "An event id, e.g. git:commit:<sha>."},
              "evidence_id": {"type": "integer", "minimum": 1, "description": "From a claim's evidence list."}})),
    read("get_metrics",
         "Quality metrics: collector freshness and gaps, duplicates avoided, citation coverage, "
         "and the share of proposed claims I confirmed, corrected or retracted.",
         obj({"since": DAY})),

    # Write tools: always allowed. They add or version items; none deletes anything.
    write("propose_claim",
          "Saves a decision, commitment, blocker or fact as an unconfirmed claim. Evidence is required: "
          "at least one event id from a read tool, or one online item you read through a connector. "
          "If you have no evidence, don't save the claim; tell me instead. "
          "If the same claim already exists, returns it instead of creating a duplicate.",
          obj({"type": {"type": "string", "enum": CLAIM_TYPES}, **CLAIM_FIELDS, "evidence": EVIDENCE},
              ["type", "text", "evidence"])),
    write("update_claim",
          "Adds a corrected version of a claim. Old versions are kept. A content change by you makes the "
          "claim unconfirmed again until I confirm it.",
          obj({"claim_id": CLAIM_ID, **CLAIM_FIELDS, "add_evidence": EVIDENCE,
               "reason": {"type": "string", "minLength": 1, "description": "Why the claim changed."}},
              ["claim_id", "reason"])),
    write("save_session_note",
          "Saves the Claude Code session note for one project and workday, as an unconfirmed item. "
          "Saving again for the same project and day adds a new version.",
          obj({"project": PROJECT, "day": DAY, "text": {"type": "string", "minLength": 1},
               "session_ids": {"type": "array", "minItems": 1, "uniqueItems": True,
                               "items": {"type": "string", "pattern": "^claude_code:session:",
                                         "description": "A session id from read_claude_sessions, e.g. claude_code:session:<uuid>."},
                               "description": "Required, at least one: the sessions this note summarises."}},
              ["project", "day", "text", "session_ids"]), idempotent=True),
    write("add_project_alias",
          "Records where a project lives in an online source, so later lookups go straight there: github_repo "
          "(owner/repo), notion (a page or database link), drive_folder (a folder link or path), gmail_query (a Gmail "
          "search, e.g. label:billing), chat_space (a Google Chat space name), or calendar_match (a word in its "
          "meeting titles). Add one when you find a project's place in a source and list_projects doesn't have it yet.",
          obj({"project": PROJECT, "kind": {"type": "string", "enum": ALIAS_KINDS},
               "value": {"type": "string", "minLength": 1, "description": "The repository, link, search, space or keyword."}},
              ["project", "kind", "value"]), idempotent=True),
    write("link_items",
          "Links two items: the same work across sources, or one claim contradicting, superseding or "
          "duplicating another. A 'contradicts' link marks both claims disputed; nothing is overwritten.",
          obj({"from": ITEM, "rel": {"type": "string", "enum": ["related", "part_of", "contradicts", "supersedes", "duplicates"]},
               "to": ITEM}, ["from", "rel", "to"]), idempotent=True),

    # Approval tools: Claude Desktop asks me every time.
    write("set_claim_status",
          "Confirms, disputes or retracts a claim after I say so. Claude Desktop asks for my approval each time.",
          obj({"claim_id": CLAIM_ID, "status": {"type": "string", "enum": ["supported", "disputed", "retracted"]},
               "reason": {"type": "string"}}, ["claim_id", "status"])),
    write("add_confidential_label",
          "Marks an item confidential so it is no longer sent to Claude. Claude Desktop asks for my approval "
          "each time. Labels can only be removed in the frontend.",
          obj({"item": ITEM, "reason": {"type": "string"}}, ["item"]), idempotent=True),
    read("read_confidential",
         "Returns one confidential item, only when I explicitly ask for it. Claude Desktop asks for my approval each time.",
         obj({"item": ITEM}, ["item"])),
]

APPROVAL = {"set_claim_status", "add_confidential_label", "read_confidential"}
