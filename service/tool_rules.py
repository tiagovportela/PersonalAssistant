"""Which tools the end-of-day agent may use, by name: shared by the run's allow list (eod.py) and the hook
that decides each MCP call as it happens (eod_hook.py). Standard library only, and nothing from the rest of
the layer but the approval tools' names, so the hook starts fast.
"""

import re

from tools import APPROVAL

# The layer's tools the end-of-day agent doesn't get: the wiki has its own run (wiki_compile.py).
NOT_FOR_EOD = {"propose_wiki_update"}

# Words in a tool's name. Allowed: at least one reading word and no changing word; anything else is denied.
READING = {"get", "list", "search", "read", "fetch", "find", "query", "view", "download", "lookup", "describe",
           "retrieve"}
CHANGING = {"create", "update", "delete", "remove", "trash", "send", "post", "share", "copy", "move", "duplicate",
            "merge", "push", "write", "edit", "add", "set", "insert", "upload", "append", "request", "assign",
            "archive", "fork", "run", "trigger", "enable", "disable", "resolve", "unresolve", "submit", "reply",
            "approve", "close", "reopen", "rename", "publish", "import", "invite", "schedule", "cancel", "patch",
            "put", "replace", "modify", "save", "mark", "subscribe", "unsubscribe", "accept", "decline", "respond",
            "rsvp", "complete", "execute", "apply", "restore", "transfer", "lock", "unlock", "pin", "unpin",
            "invoke", "start", "stop", "deploy", "release", "draft", "comment", "react", "forward", "revoke"}
SAFE_BUILTINS = {"Read", "Glob", "Grep", "LS", "TodoWrite", "ToolSearch", "ListMcpResourcesTool", "ReadMcpResourceTool"}
FILE_EDITS = {"Edit", "Write", "MultiEdit"}


def words(name):
    name = re.sub(r"(?i)(pull|merge)[_-]?requests?", "pr", name)  # a noun, not a request to do something
    return {w.lower() for w in re.split(r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])", name) if w}


def reads_only(name):
    found = words(name)
    return bool(found & READING) and not found & CHANGING


def classify(names, overrides=None):
    """(allowed, blocked) tool names: the layer's tools without the approval ones, connectors' tools that only
    read, and the built-in tools that only read. My overrides come last.

    The file-editing tools are in neither list: a run allows them through its Edit rule, inside the notes folder
    only, and a deny would override that rule. They're denied only if I block one, and never allowed everywhere."""
    overrides = overrides or {}
    allowed, blocked = [], []
    for name in sorted(set(names)):
        if name in FILE_EDITS:
            if name in overrides.get("block", []):
                blocked.append(name)
            continue
        if name.startswith("mcp__pwi__"):
            ok = name.removeprefix("mcp__pwi__") not in APPROVAL | NOT_FOR_EOD
        elif name.startswith("mcp__"):
            ok = reads_only(name.removeprefix("mcp__").split("__", 1)[-1])
        else:
            ok = name in SAFE_BUILTINS
        if name in overrides.get("allow", []):
            ok = True
        if name in overrides.get("block", []):
            ok = False
        (allowed if ok else blocked).append(name)
    return allowed, blocked
