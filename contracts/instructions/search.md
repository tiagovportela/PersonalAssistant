# Evidence-backed search

Answer a "what", "when" or "why" question about my past work, with evidence.

## Steps

1. Call `search` with several wordings: synonyms, Portuguese and English, and project or file names. Narrow with `project`, `since` and `until` when the question gives them. Results include Firefox pages I visited; for "when did I read about…" questions set `kinds` to only `firefox`, and add `app_usage` to search window titles, e.g. a document I had open.
2. For the most relevant results, call `get_evidence` to see the full record and whether it's still available.
3. For "why" questions, also search the online sources that hold reasoning: Notion and Drive documents, Gmail and Google Chat threads, and GitHub PR discussions.
4. If you find a decision or fact that isn't saved yet, save it with `propose_claim`, with evidence.

## Output

**Answer**: a direct answer, labelled verified or unconfirmed. If the evidence conflicts, say so and show both sides.

**Evidence**: the commits, sessions, claims, messages and documents behind the answer, with ids or links.

**Timeline**: when relevant, how the work or decision evolved, by date.

**Gaps**: what wasn't found, and sources that changed or are unavailable.

**Confidence and coverage**
