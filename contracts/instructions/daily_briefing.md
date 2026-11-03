# Daily briefing

A briefing for one workday: what I did, and what comes next.

## Which day

Use the day I named. "Yesterday" means the previous workday: on a Monday, that's Friday, and you say so. If I named no day, use the previous workday.

## Steps

1. Call `get_day` for that day.
2. Call `list_projects` to get each project's GitHub, Notion and calendar aliases.
3. Look up that workday in the connectors my allowlist allows:
   - Gmail, and Google Chat with `chat_messages`: what I promised, decisions made in threads, and requests to me still unanswered.
   - Drive and Notion: documents I wrote or changed that day.
4. Look up what comes next through the connectors:
   - Google Calendar: my meetings for the next workday.
   - Notion: tasks assigned to me that are due in the next 3 workdays, or overdue.
   - GitHub: for each active project, my open PRs, review requests, and failed CI on my branches.
5. Use the commitments in `get_day`'s `due` list. Check each against Notion or the calendar where possible.
6. Call `list_unconfirmed` for the count of claims waiting for my confirmation.
7. Save any new decision, commitment or blocker you found in the connectors with `propose_claim`, with evidence.

## Output

**What I did**: completed work, investigations, decisions, documents written and failed attempts, grouped by project. Each item cites its evidence and is labelled.

**Time and reading**: from `computer_time` and `browsing`, if present: active hours and the projects that took most of them, in one line, and up to 5 pages I read that matter for the work.

**What comes next**: meetings with times, deadlines, commitments, and anything to prepare.

**Needs attention**: blockers, aging PRs, failed CI, and requests to me in mail and chat that are still unanswered.

**Suggested focus**: up to 3 ranked recommendations, each with a one-line rationale and its evidence.

**Waiting for confirmation**: the number of unconfirmed claims, and a reminder that the end-of-day review can clear them.

**Confidence and coverage**
