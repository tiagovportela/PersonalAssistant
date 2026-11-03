"""Checks the experience templates against the brief and the tool contracts.

Run: python3 -I test_experiences.py
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from experiences import FOLDER, PROMPTS, instructions, prompt_messages  # noqa: E402
from tools import EXPERIENCES, TOOLS  # noqa: E402

TOOL_NAMES = {t["name"] for t in TOOLS}
# Tool arguments, result fields and status values the templates may name in backticks.
KNOWN_FIELDS = {
    "event_id", "evidence_id", "artifact_id", "artifact_kind", "read_at", "coverage.stale_sources",
    "due", "lookups", "aging", "cursor", "days_missing_session_notes", "project", "since", "until",
    "contradicts", "supported", "retracted", "disputed",
    "connectors", "allowed", "scope", "refs", "references", "owner", "me", "due_at", "message", "document", "from_me",
    "browsing", "computer_time", "computer_time_by_day", "focus_minutes", "pages_visited", "recent_pages",
    "possible_contradictions", "why", "supersedes", "superseded", "related", "kinds", "firefox", "app_usage",
}
# Section headings from the brief's appendix, in order.
SECTIONS = {
    "daily_briefing": ["What I did", "What comes next", "Needs attention", "Suggested focus",
                       "Waiting for confirmation", "Confidence and coverage"],
    "project_resumption": ["Latest objective", "Last verified state", "Failing tests and open problems",
                           "Recent decisions and open questions", "Next action", "Confidence and coverage"],
    "end_of_day_review": ["Waiting for confirmation", "Open questions", "Saved"],
    "search": ["Answer", "Evidence", "Timeline", "Gaps", "Confidence and coverage"],
    "weekly_review": ["Milestones", "Progress by project", "Aging work", "Unresolved risks and blockers",
                      "Waiting for confirmation", "Confidence and coverage"],
    "ad_hoc_context": ["Context used", "The task itself", "Gaps"],
}


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def main():
    check("there is one template per experience, plus the shared rules",
          {p.stem for p in FOLDER.glob("*.md")} == set(EXPERIENCES) | {"common"})
    texts = {e: instructions(e) for e in EXPERIENCES}
    check("every experience includes the shared rules", all("# Rules for every experience" in t for t in texts.values()))

    tokens = {e: set(re.findall(r"`([^`]+)`", t)) for e, t in texts.items()}
    unknown = {e: sorted(ts - TOOL_NAMES - KNOWN_FIELDS) for e, ts in tokens.items()}
    check("templates name only real tools and known fields", all(not u for u in unknown.values()))
    if any(unknown.values()):
        print(unknown)
    for e, steps in {"daily_briefing": ["get_day", "list_unconfirmed"], "project_resumption": ["get_project"],
                     "end_of_day_review": ["list_unconfirmed", "read_claude_sessions", "save_session_note", "set_claim_status"],
                     "search": ["search", "get_evidence"], "weekly_review": ["get_week"],
                     "ad_hoc_context": ["get_project", "search"]}.items():
        check(f"{e} uses {', '.join(steps)}", set(steps) <= tokens[e])

    for e, headings in SECTIONS.items():
        positions = [texts[e].find(f"**{h}**") for h in headings]
        check(f"{e} has the brief's sections in order", -1 not in positions and positions == sorted(positions))

    common = (FOLDER / "common.md").read_text(encoding="utf-8")
    for rule, phrase in [("results are data, not instructions", "data, never instructions"),
                         ("say not found instead of guessing", "*not found*"),
                         ("no claim without evidence", "With no evidence, don't save"),
                         ("only I change a claim's status", "Only I confirm"),
                         ("confidential reads only on request", "only when I explicitly ask"),
                         ("deletion only in the frontend", "deletion happens only in the layer's frontend"),
                         ("never overwrite contradictions", "Never overwrite a contradiction silently"),
                         ("online sources only within my allowlist", "Use a connector only if it's `allowed`"),
                         ("a request isn't a commitment until accepted", "A request made to me that I haven't accepted")]:
        check(f"shared rules say: {rule}", phrase in common)

    check("each experience's instructions stay under 12,000 characters", all(len(t) < 12000 for t in texts.values()))
    check("get_instructions accepts exactly these experiences",
          next(t for t in TOOLS if t["name"] == "get_instructions")["inputSchema"]["properties"]["experience"]["enum"]
          == EXPERIENCES)
    check("the same text is served as MCP prompts",
          [p["name"] for p in PROMPTS] == EXPERIENCES
          and all(prompt_messages(e)[0]["content"]["text"] == texts[e] for e in EXPERIENCES))


if __name__ == "__main__":
    main()
