"""The end-of-day agent's PreToolUse hook: Claude Code runs it before each MCP tool call of a run, with the call
on stdin, and it answers allow or deny by the tool's name (tool_rules.py) and my overrides (the policy file the
run writes). So a connector's tools are judged when they're called, even if the connector was still connecting
when the run's allow list was made. If anything goes wrong it denies: it never allows by mistake.

Run by Claude Code: python3 -I eod_hook.py POLICY_JSON
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]


def decide(name, overrides):
    import tool_rules
    allowed, _ = tool_rules.classify([name], overrides)
    return name in allowed


def main():
    name = ""
    try:
        name = json.load(sys.stdin).get("tool_name") or ""
        overrides = json.loads(Path(sys.argv[1]).read_text()).get("overrides") or {}
        ok = bool(name) and decide(name, overrides)
        reason = ("only reads" if ok else "can change something, or needs my approval: the end-of-day agent may "
                  "only read")
    except Exception as e:  # fail closed
        ok, reason = False, f"the layer's hook couldn't decide ({type(e).__name__}), so it denies"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "allow" if ok else "deny",
                                             "permissionDecisionReason": f"{name}: {reason}"}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
