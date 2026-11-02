# Daily briefing

A briefing for one workday: what I did, and what comes next.

## Which day

Use the day I named. "Yesterday" means the previous workday: on a Monday, that's Friday, and you say so. If I named no day, use the previous workday.

## Steps

1. Call `get_day` for that day.
2. Call `list_projects` to get each project's GitHub, Notion and calendar aliases.
3. Look up what comes next through the connectors:
   - Google Calendar: my meetings for the next workday.
   - Notion: tasks assigned to me that are due in the next 3 workdays, or overdue.
   - GitHub: for each active project, my open PRs, review requests, and failed CI on my branches.
4. Use the commitments in `get_day`'s `due` list. Check each against Notion or the calendar where possible.
5. Call `list_unconfirmed` for the count of claims waiting for my confirmation.
6. Save any new decision, commitment or blocker you found in the connectors with `propose_claim`, with evidence.

## Output

**What I did**: completed work, investigations, decisions and failed attempts, grouped by project. Each item cites its evidence and is labelled.

**What comes next**: meetings with times, deadlines, commitments, and anything to prepare.

**Needs attention**: blockers, aging PRs, failed CI and unanswered requests.

**Suggested focus**: up to 3 ranked recommendations, each with a one-line rationale and its evidence.

**Waiting for confirmation**: the number of unconfirmed claims, and a reminder that the end-of-day review can clear them.

**Confidence and coverage**
