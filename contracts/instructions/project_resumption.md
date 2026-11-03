# Project resumption

Help me pick up a project where I left it.

## Which project

Use the project I named. If the name doesn't match a project id, call `list_projects` and pick the clear match. If there's more than one, ask me which.

## Steps

1. Call `get_project`.
2. Run each query in its `lookups` list through its connector: GitHub for open PRs, CI and failing tests, and Notion, Gmail, Google Chat, Drive and Calendar where the project has aliases there. Follow its `references` too.
3. If the project has no alias in a source you'd expect, look for it there within the allowlist, and add what you find with `add_project_alias`.
4. If the objective is unclear or older than a week, `search` for recent session notes and decisions on this project. `recent_pages` shows what I was reading for it.
5. Save any new blocker or decision you found online with `propose_claim`, with evidence.

## Output

**Latest objective**: what I was trying to achieve, with its date and evidence.

**Last verified state**: branch, last commit, PR and CI status, and uncommitted changes, with when the layer last saw them.

**Failing tests and open problems**

**Recent decisions and open questions**: each labelled, with evidence. List `possible_contradictions` here as open questions.

**Next action**: one suggested next step and why. If the evidence doesn't point to one, say so and list the options.

**Confidence and coverage**: include the date of last activity.
