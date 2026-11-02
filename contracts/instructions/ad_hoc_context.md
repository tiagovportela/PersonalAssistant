# Ad-hoc context

Help with a work task, such as a status update or meeting preparation, using what the layer knows, so I don't have to paste context.

## Steps

1. Work out what the task is about: which project, people, meeting or topic. If it's unclear, ask one question.
2. Gather only what the task needs:
   - A project → `get_project`, and `search` for recent decisions and commitments.
   - A period → `get_day` or `get_week`.
   - A meeting → its Google Calendar event, then `search` and the connectors for its topic and attendees' recent threads in Gmail and Google Chat.
   - A document → Drive or Notion, starting from the project's aliases.
   - A topic → `search`, then the online sources.
3. Do the task with that context. Keep claims labelled inside the result too. For example, don't present an unconfirmed decision as final in a status update; flag it, or ask me first.
4. Save any new commitment or decision that came up with `propose_claim`, with evidence.

## Output

**Context used**: the claims and evidence you pulled, with ids or links.

**The task itself**: for example the status update or the meeting preparation.

**Gaps**: anything relevant that wasn't found, or is still unconfirmed.
