"""Checks tools.py against the architecture's rules and against schema.sql.

Run: python3 -I test_tools.py
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tools import ALIAS_KINDS, APPROVAL, ARTIFACT_KINDS, CLAIM_TYPES, ITEM_TYPES, TOOLS  # noqa: E402
from validate import error_text, validate  # noqa: E402

SCHEMA = (HERE.parent / "schema" / "schema.sql").read_text()
ARCHITECTURE_TOOLS = {  # architecture v0.2 §4
    "search", "get_day", "get_week", "get_project", "list_unconfirmed", "read_claude_sessions",
    "get_evidence", "get_metrics", "get_instructions",
    "propose_claim", "update_claim", "save_session_note", "link_items", "set_claim_status", "add_confidential_label",
}
ADDED_TOOLS = {"list_projects", "read_confidential", "add_project_alias", "chat_spaces", "chat_messages"}


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def check_enum(table, column):
    """Values allowed by a CHECK (column IN (...)) inside one CREATE TABLE in schema.sql."""
    body = re.search(rf"CREATE TABLE {table} \((.*?)\) STRICT;", SCHEMA, re.S).group(1)
    values = re.search(rf"{column}\s.*?CHECK \({column} IN\s*\((.*?)\)\)", body, re.S).group(1)
    return set(re.findall(r"'([^']+)'", values))


def objects(schema):
    """Every object schema inside an input schema."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from objects(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from objects(value)


def fields(schema):
    """Every property schema inside an input schema."""
    for o in objects(schema):
        for sub in o.get("properties", {}).values():
            yield sub
            if sub.get("type") == "array" and sub.get("items", {}).get("type") != "object":
                yield sub["items"]


def main():
    by_name = {t["name"]: t for t in TOOLS}
    check("no duplicate tool names", len(by_name) == len(TOOLS))
    check("every architecture tool is present, plus the five documented additions",
          set(by_name) == ARCHITECTURE_TOOLS | ADDED_TOOLS)
    check("no delete or remove tools", not any(re.search(r"delete|remove|purge", n) for n in by_name))
    check("names follow MCP naming rules", all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", n) for n in by_name))
    check("contracts serialise to JSON", json.loads(json.dumps(TOOLS)) == TOOLS)
    check("every tool has a description", all(t["description"].strip() for t in TOOLS))

    reads = {"search", "get_day", "get_week", "get_project", "list_unconfirmed", "read_claude_sessions",
             "get_evidence", "get_metrics", "get_instructions", "list_projects", "read_confidential",
             "chat_spaces", "chat_messages"}
    check("read tools say read-only, write tools don't",
          all(by_name[n]["annotations"]["readOnlyHint"] is (n in reads) for n in by_name))
    check("no tool claims to be destructive",
          not any(t["annotations"].get("destructiveHint") for t in TOOLS))
    check("approval tools are status changes, labels and confidential reads",
          APPROVAL == {"set_claim_status", "add_confidential_label", "read_confidential"})
    check("approval tools say so in their description",
          all("approval each time" in by_name[n]["description"] for n in APPROVAL))

    all_objects = [o for t in TOOLS for o in objects(t["inputSchema"])]
    check("every object schema rejects unknown fields",
          all(o.get("additionalProperties") is False for o in all_objects))
    check("required fields are all defined",
          all(set(o.get("required", [])) <= set(o.get("properties", {})) for o in all_objects))
    check("propose_claim requires at least one piece of evidence",
          "evidence" in by_name["propose_claim"]["inputSchema"]["required"]
          and by_name["propose_claim"]["inputSchema"]["properties"]["evidence"]["minItems"] == 1)
    check("update_claim requires a reason",
          "reason" in by_name["update_claim"]["inputSchema"]["required"])

    check("claim types match schema.sql (minus session_note, which has its own tool)",
          set(CLAIM_TYPES) == check_enum("claims", "type") - {"session_note"})
    check("item types match the labels table", set(ITEM_TYPES) == check_enum("labels", "item_type"))
    statuses = set(by_name["set_claim_status"]["inputSchema"]["properties"]["status"]["enum"])
    check("set_claim_status only uses statuses the schema allows",
          statuses <= check_enum("claim_versions", "status"))
    rels = set(by_name["link_items"]["inputSchema"]["properties"]["rel"]["enum"])
    check("link relations match the links table", rels == check_enum("links", "rel"))
    check("artifact kinds match the artifacts table", set(ARTIFACT_KINDS) == check_enum("artifacts", "kind"))
    check("Claude can add online aliases only, never local ones like repository paths",
          set(ALIAS_KINDS) < check_enum("project_aliases", "kind") and "repo_path" not in ALIAS_KINDS)

    # Claude Desktop drops these keywords, so no rule may depend on them alone.
    text = json.dumps(TOOLS)
    check("no schema uses oneOf, anyOf or allOf", not re.search(r'"(oneOf|anyOf|allOf)"', text))
    check("every field with a pattern or format also has a description",
          all("description" in o for t in TOOLS for o in fields(t["inputSchema"]) if {"pattern", "format"} & o.keys()))
    check("propose_claim's description says evidence is required",
          "Evidence is required" in by_name["propose_claim"]["description"])

    # Server-side validation
    evidence = [{"event_id": "git:commit:abc123"}]
    online = [{"artifact_id": "notion:example-123", "artifact_kind": "work_item",
               "url": "https://www.notion.so/example-123", "read_at": "2026-11-02T17:40:00Z"}]
    claim = {"type": "decision", "text": "We use SQLite for the store."}
    check("a valid claim with local evidence passes", validate("propose_claim", {**claim, "evidence": evidence}) == [])
    check("a valid claim with online evidence passes", validate("propose_claim", {**claim, "evidence": online}) == [])
    missing = validate("propose_claim", claim)
    check("a claim without evidence is rejected, with a hint on how to add it",
          len(missing) == 1 and missing[0].startswith("evidence is required") and "event_id" in missing[0])
    check("empty evidence is rejected", validate("propose_claim", {**claim, "evidence": []}) != [])
    check("evidence with neither event_id nor artifact_id is rejected",
          "needs either event_id" in " ".join(validate("propose_claim", {**claim, "evidence": [{"url": "x"}]})))
    check("online evidence needs a kind and a read time",
          "artifact_kind and read_at" in " ".join(validate("propose_claim", {**claim, "evidence": [{"artifact_id": "notion:x"}]})))
    check("mixing local and online fields is rejected",
          "mixes" in " ".join(validate("propose_claim", {**claim, "evidence": [{**evidence[0], "read_at": "2026-11-02T17:40:00Z"}]})))
    check("unknown fields, bad enums and bad dates are each reported",
          len(validate("propose_claim", {**claim, "type": "rumour", "about_day": "02/11/2026",
                                         "evidence": evidence, "colour": "red"})) == 3)
    check("bad read_at time is rejected",
          validate("propose_claim", {**claim, "evidence": [{**online[0], "read_at": "yesterday"}]}) != [])
    check("a bad claim id is rejected with an example",
          "clm_" in " ".join(validate("set_claim_status", {"claim_id": "42", "status": "supported"})))
    check("numbers outside their range are rejected",
          validate("search", {"query": "x", "limit": 500}) != [] and validate("search", {"query": "x", "limit": True}) != [])
    check("tools with no arguments accept an empty call", validate("list_projects", {}) == [])
    check("get_evidence takes exactly one of event_id or evidence_id",
          validate("get_evidence", {"event_id": "git:commit:abc"}) == [] and validate("get_evidence", {"evidence_id": 3}) == []
          and validate("get_evidence", {}) != [] and validate("get_evidence", {"event_id": "x", "evidence_id": 3}) != [])
    check("the error text tells Claude to retry",
          error_text("propose_claim", missing).endswith("Fix these and call propose_claim again."))


if __name__ == "__main__":
    main()
