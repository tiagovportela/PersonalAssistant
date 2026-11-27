"""Checks tool arguments against tools.py, in the service.

Claude Desktop enforces none of the input schemas, so this is the only check
between Claude and the store. It covers the JSON Schema keywords tools.py uses,
plus the evidence rules a flat schema can't express. Errors are written for
Claude to read and fix, and the service returns them as one tool error.
Standard library only.
"""

import re
from datetime import date, datetime

from tools import TOOLS, WIKI_COMPILED, WIKI_GENERATED, WIKI_ID

SCHEMAS = {t["name"]: t["inputSchema"] for t in TOOLS}
TYPES = {"string": str, "integer": int, "number": (int, float), "array": list, "object": dict, "boolean": bool}
ONLINE_FIELDS = {"artifact_id", "artifact_kind", "title", "url", "read_at", "source_version"}

# The wiki's budgets (docs/knowledge_wiki.md). The page-wide one is checked in wiki.py, after merging.
STATEMENT_CHARS, SECTION_STATEMENTS, STATEMENT_CITES = 600, 40, 8
HEADING_CHARS, SUMMARY_CHARS, TITLE_CHARS = 80, 200, 80
KEY_TERMS, KEY_TERM_CHARS, UPDATE_SECTIONS = 30, 40, 12
HTML_TAG = re.compile(r"<[A-Za-z/!?]")
MARKDOWN_LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)]*)\)")
WIKI_LINK = re.compile(r"\[\[([^\]|]*)(?:\|([^\]]*))?\]\]")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate(tool, args):
    """Returns a list of problems with the arguments; an empty list means they're valid."""
    errors = []
    check(SCHEMAS[tool], args, "arguments", errors)
    for field in ("evidence", "add_evidence"):
        if isinstance(args, dict) and isinstance(args.get(field), list):
            for i, item in enumerate(args[field]):
                if isinstance(item, dict):
                    check_evidence(item, f"{field}[{i}]", errors)
    if tool == "get_evidence" and isinstance(args, dict) and len(args.keys() & {"event_id", "evidence_id"}) != 1:
        errors.append("Pass exactly one of event_id (an event from a read tool) or evidence_id (from a claim).")
    if isinstance(args, dict) and not errors:
        {"get_wiki_page": check_get_wiki_page, "read_repo": check_read_repo,
         "propose_wiki_update": check_wiki_update}.get(tool, lambda a, e: None)(args, errors)
    return errors


def error_text(tool, errors):
    lines = "\n".join(f"- {e}" for e in errors)
    return f"{tool} was not run because its arguments are invalid:\n{lines}\nFix these and call {tool} again."


def check(schema, value, path, errors):
    kind = schema.get("type")
    if kind and (not isinstance(value, TYPES[kind]) or (kind in ("integer", "number") and isinstance(value, bool))):
        errors.append(f"{path} must be {'an' if kind[0] in 'aeiou' else 'a'} {kind}.")
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} must be one of: {', '.join(schema['enum'])}.")
    if kind == "string":
        if len(value.strip()) < schema.get("minLength", 0):
            errors.append(f"{path} must not be empty.")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path} doesn't look right. {schema.get('description', '')}".strip())
        check_format(schema.get("format"), value, path, errors)
    elif kind in ("integer", "number"):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path} must be at least {schema['minimum']}.")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path} must be at most {schema['maximum']}.")
    elif kind == "array":
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path} needs at least {schema['minItems']} item(s). {schema.get('description', '')}".strip())
        if schema.get("uniqueItems") and len({repr(v) for v in value}) != len(value):
            errors.append(f"{path} has duplicate items.")
        for i, item in enumerate(value):
            check(schema.get("items", {}), item, f"{path}[{i}]", errors)
    elif kind == "object":
        properties = schema.get("properties", {})
        field = lambda name: name if path == "arguments" else f"{path}.{name}"  # noqa: E731
        for name in schema.get("required", []):
            if name not in value:
                hint = properties.get(name, {}).get("description", "")
                errors.append(f"{field(name)} is required. {hint}".strip())
        if schema.get("additionalProperties") is False:
            for name in sorted(value.keys() - properties.keys()):
                errors.append(f"{field(name)} is not a known field.")
        for name, sub in properties.items():
            if name in value:
                check(sub, value[name], field(name), errors)


def check_format(fmt, value, path, errors):
    try:
        if fmt == "date":
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError
            date.fromisoformat(value)
        elif fmt == "date-time":
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z", value):
                raise ValueError
            datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        example = "2026-11-02" if fmt == "date" else "a UTC time like 2026-11-02T17:00:00Z"
        errors.append(f"{path} must be {example}.")


def check_evidence(item, path, errors):
    online = item.keys() & ONLINE_FIELDS
    if "event_id" in item:
        if online:
            errors.append(f"{path} mixes local and online fields: use either event_id alone, "
                          "or artifact_id with artifact_kind and read_at.")
    elif "artifact_id" in item:
        missing = [f for f in ("artifact_kind", "read_at") if f not in item]
        if missing:
            errors.append(f"{path} is online evidence, so it also needs {' and '.join(missing)}.")
    else:
        errors.append(f"{path} needs either event_id (from a read tool) or artifact_id "
                      "(for something read through a connector).")


def check_get_wiki_page(args, errors):
    if "page" in args:
        for name in sorted(args.keys() & {"kind", "project"}):
            errors.append(f"{name} filters the catalog, so it goes without page.")
    elif "sections" in args:
        errors.append("sections needs page: the page whose sections to read.")
    if args.get("previews") and "sections" not in args:
        errors.append("previews goes with sections: the sections whose diagrams to draw.")


def check_read_repo(args, errors):
    if "path" in args and "since" in args:
        errors.append("Pass path to read a file, or since to list commits, not both.")
    if "commit" in args and "path" not in args:
        errors.append("commit goes with path: the commit to read that file at.")
    path = args.get("path")
    if path is not None and (path.startswith(("/", "-")) or "\0" in path or ".." in path.split("/")):
        errors.append("path is a path inside the repository, e.g. docs/architecture.md, without .. or a leading /.")


def check_wiki_text(text, path, errors):
    """The plain-text subset a statement may use. Code renders it; anything else is refused, not cleaned."""
    if len(text) > STATEMENT_CHARS:
        errors.append(f"{path} is {len(text)} characters; a statement has at most {STATEMENT_CHARS}. Split it.")
    if "\n" in text or "\r" in text:
        errors.append(f"{path} must be on one line: one sentence or bullet per statement.")
    if HTML_TAG.search(text):
        errors.append(f"{path} has HTML. Use plain text, **bold**, *italics*, `code` and links.")
    for image, _, url in MARKDOWN_LINK.findall(text):
        if image:
            errors.append(f"{path} has an image. Statements are text only.")
        elif not url.startswith("https://"):
            errors.append(f"{path} links to '{url[:60]}'. Links must start with https://, or be [[page]] links.")
    for target, _ in WIKI_LINK.findall(text):
        if not re.fullmatch(WIKI_ID, target):
            errors.append(f"{path} links to [[{target[:60]}]], which isn't a page id. Use ids from get_wiki_page.")


def check_cite(cite, path, errors):
    families = [name for name, fields in (("claim_id", {"claim_id"}), ("event_id", {"event_id"}),
                                          ("commit", {"repo", "commit", "path"}), ("page", {"page", "section"}))
                if cite.keys() & fields]
    if len(families) != 1:
        errors.append(f"{path} needs exactly one of: claim_id; event_id; repo with commit (and path for a file); "
                      "or page (and section).")
    elif families == ["commit"] and not {"repo", "commit"} <= cite.keys():
        errors.append(f"{path} is a commit or file, so it needs both repo and commit.")


def check_wiki_update(args, errors):
    if ("page" in args) == ("new" in args):
        errors.append("Pass page for an existing page, or new to create a person or topic page, not both.")
    if "page" in args and "base_version" not in args:
        errors.append("base_version is required with page: the version get_wiki_page showed, 0 for a project page "
                      "never written.")
    new = args.get("new") or {}
    if new.get("kind") == "person" and not EMAIL.match(new.get("email", "")):
        errors.append("new.email is required for a person page, e.g. ana.silva@example.com.")
    if new.get("kind") == "topic" and "email" in new:
        errors.append("new.email is for person pages only.")
    if len(new.get("title", "")) > TITLE_CHARS:
        errors.append(f"new.title has at most {TITLE_CHARS} characters.")
    if not args.keys() & {"sections", "summary", "key_terms", "built_from"}:
        errors.append("Nothing to save: pass sections, summary, key_terms or built_from.")
    if len(args.get("summary", "")) > SUMMARY_CHARS or HTML_TAG.search(args.get("summary", "")):
        errors.append(f"summary is one line of plain text, at most {SUMMARY_CHARS} characters.")
    terms = args.get("key_terms", [])
    if len(terms) > KEY_TERMS or any(len(t) > KEY_TERM_CHARS or HTML_TAG.search(t) for t in terms):
        errors.append(f"key_terms has at most {KEY_TERMS} plain-text terms of up to {KEY_TERM_CHARS} characters.")
    sections = args.get("sections", [])
    if len(sections) > UPDATE_SECTIONS:
        errors.append(f"sections has at most {UPDATE_SECTIONS} sections per update.")
    generated = {i for ids in WIKI_GENERATED.values() for i in ids}
    standard = {i for ids in WIKI_COMPILED.values() for i in ids}
    seen = set()
    for i, section in enumerate(sections):
        where, sid = f"sections[{i}]", section["id"]
        if sid in seen:
            errors.append(f"{where}.id '{sid}' appears twice. Send each section once.")
        seen.add(sid)
        if sid in generated:
            errors.append(f"{where}.id '{sid}' is built by the layer from the store, so it can't be written.")
        elif sid not in standard and section["blocks"] and not section.get("heading", "").strip():
            errors.append(f"{where}.heading is required for your own section '{sid}'.")
        for field, limit in (("heading", HEADING_CHARS), ("summary", SUMMARY_CHARS)):
            value = section.get(field, "")
            if len(value) > limit or HTML_TAG.search(value) or "\n" in value:
                errors.append(f"{where}.{field} is one line of plain text, at most {limit} characters.")
        if len(section["blocks"]) > SECTION_STATEMENTS:
            errors.append(f"{where} has {len(section['blocks'])} statements; a section has at most {SECTION_STATEMENTS}.")
        for j, block in enumerate(section["blocks"]):
            spot = f"{where}.blocks[{j}]"
            kinds = [k for k in ("text", "diagram", "image") if k in block]
            if len(kinds) != 1:
                errors.append(f"{spot} is one of: text (a statement), diagram, or image.")
                continue
            if "text" in block:
                check_wiki_text(block["text"], f"{spot}.text", errors)
            if "image" not in block and not block.get("cites"):
                errors.append(f"{spot}.cites is required: every statement and diagram cites its evidence.")
            cites = block.get("cites", [])
            if len(cites) > STATEMENT_CITES:
                errors.append(f"{spot}.cites has at most {STATEMENT_CITES} items.")
            for k, cite in enumerate(cites):
                check_cite(cite, f"{spot}.cites[{k}]", errors)
            if cites and all(c.keys() <= {"page", "section"} for c in cites):
                errors.append(f"{spot} cites only pages. A page is a link, not evidence: also cite a claim, an "
                              "event, or a commit or file.")
            if "diagram" in block:
                for field in ("nodes", "items"):
                    for k, item in enumerate(block["diagram"].get(field, [])):
                        for m, cite in enumerate(item.get("cites", [])):
                            check_cite(cite, f"{spot}.diagram.{field}[{k}].cites[{m}]", errors)
            if "image" in block and len(block["image"].get("caption", "")) > SUMMARY_CHARS:
                errors.append(f"{spot}.image.caption is at most {SUMMARY_CHARS} characters.")
