# Weekly review

Progress, aging work and open risks for one week.

## Which week

Use the week I named. Weeks run Monday to Sunday. If I named no week, use the last completed one. "This week" means the current week so far.

## Steps

1. Call `get_week` with any date in that week.
2. Call `list_projects`, then check the connectors for that week. `get_week` only holds local work; run every query in its `online_lookups`, which covers these:
   - GitHub: merged PRs, releases, and PRs open for more than 5 days.
   - Notion: tasks completed, and tasks overdue or due next week.
   - Google Calendar: key meetings, such as reviews, demos and decisions.
   - Gmail, and Google Chat with `chat_messages`: decisions and commitments made in threads that week, and requests to me still open.
   - Drive and Notion: documents written or substantially changed.
3. Use `aging` from `get_week` for overdue commitments, open blockers and long-unconfirmed claims, and `possible_contradictions` for claims that may disagree. Each project's `focus_minutes` and `pages_visited`, and `computer_time_by_day`, show where the time went.
4. Save any new commitment, blocker or decision you found online with `propose_claim`, with evidence, and any project alias you found with `add_project_alias`.

## Output

**Milestones**: what was completed or released.

**Progress by project**: a few lines each, with evidence, and the focus time when app usage has it.

**Aging work**: unfinished items, open PRs, and commitments past or near their deadline, each with its age.

**Unresolved risks and blockers**: including possible contradictions between claims, for the end-of-day review to settle.

**Waiting for confirmation**: the number of unconfirmed claims from that week.

**Confidence and coverage**
