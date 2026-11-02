# Weekly review

Progress, aging work and open risks for one week.

## Which week

Use the week I named. Weeks run Monday to Sunday. If I named no week, use the last completed one. "This week" means the current week so far.

## Steps

1. Call `get_week` with any date in that week.
2. Call `list_projects`, then check the connectors for that week:
   - GitHub: merged PRs, releases, and PRs open for more than 5 days.
   - Notion: tasks completed, and tasks overdue or due next week.
   - Google Calendar: key meetings, such as reviews, demos and decisions.
3. Use `aging` from `get_week` for overdue commitments, open blockers and long-unconfirmed claims.
4. Save any new commitment, blocker or decision you found online with `propose_claim`, with evidence.

## Output

**Milestones**: what was completed or released.

**Progress by project**: a few lines each, with evidence.

**Aging work**: unfinished items, open PRs, and commitments past or near their deadline, each with its age.

**Unresolved risks and blockers**

**Waiting for confirmation**: the number of unconfirmed claims from that week.

**Confidence and coverage**
