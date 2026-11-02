"""Checks tool arguments against tools.py, in the service.

Claude Desktop enforces none of the input schemas, so this is the only check
between Claude and the store. It covers the JSON Schema keywords tools.py uses,
plus the evidence rules a flat schema can't express. Errors are written for
Claude to read and fix, and the service returns them as one tool error.
Standard library only.
"""

import re
from datetime import date, datetime

from tools import TOOLS

SCHEMAS = {t["name"]: t["inputSchema"] for t in TOOLS}
TYPES = {"string": str, "integer": int, "number": (int, float), "array": list, "object": dict, "boolean": bool}
ONLINE_FIELDS = {"artifact_id", "artifact_kind", "title", "url", "read_at", "source_version"}


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
