"""The six experiences, from one source: instructions/*.md.

get_instructions returns instructions(name). The same text is also served as
MCP prompts (PROMPTS / prompt_messages), in case a later Claude Desktop shows
them. Standard library only.
"""

from pathlib import Path

from tools import EXPERIENCES

FOLDER = Path(__file__).resolve().with_name("instructions")


def instructions(experience):
    """The shared rules followed by one experience's template."""
    if experience not in EXPERIENCES:
        raise ValueError(f"unknown experience: {experience}")
    common = (FOLDER / "common.md").read_text(encoding="utf-8")
    template = (FOLDER / f"{experience}.md").read_text(encoding="utf-8")
    return f"{template.rstrip()}\n\n---\n\n{common.rstrip()}\n"


def title(experience):
    return (FOLDER / f"{experience}.md").read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()


PROMPTS = [{"name": e, "title": title(e), "description": f"{title(e)} from my work layer.", "arguments": []}
           for e in EXPERIENCES]


def prompt_messages(experience):
    return [{"role": "user", "content": {"type": "text", "text": instructions(experience)}}]
