# End-of-day review

I confirm what you saved, answer what you couldn't resolve, and you write the Claude Code session notes. It's optional: I can stop at any point, and everything answered so far stays saved.

## Steps

1. **Session notes first.** Claude Code deletes old session files, so these can't wait.
   - Call `list_unconfirmed`. Its `days_missing_session_notes` lists each workday and project with Claude Code sessions but no note.
   - Start with the oldest day. For each day, call `read_claude_sessions` and follow its `cursor` until done.
   - Write one note per project per day: the goal, what got done, decisions, what failed, and what's left. Keep it to a few sentences.
   - Save each with `save_session_note`, passing every session id it covers.
2. **Today's messages.** If Gmail or Google Chat is allowed, read today's sent mail, and my chat messages with `chat_messages` (`from_me` true), within their scope. Save what I promised and decisions I took part in with `propose_claim`, with the message as evidence, so they're waiting for confirmation in the next step. Requests to me I haven't answered aren't claims; list them under Open questions.
3. **Claims waiting for confirmation.** Use the claims from `list_unconfirmed`, oldest first. This includes days I skipped.
   - Show them 5 at a time, grouped by day and project. Number each one, and give its label and evidence.
   - I answer by number: confirm, correct, or retract.
   - Confirm → `set_claim_status` with `supported`.
   - Retract → `set_claim_status` with `retracted`.
   - Correct → `update_claim` with my wording and a reason. It stays unconfirmed until I confirm the new version.
   - If I question a claim without deciding → `set_claim_status` with `disputed`.
4. **Possible contradictions.** `list_unconfirmed` also returns `possible_contradictions`: pairs of claims the layer thinks may disagree, with `why`.
   - Show each pair numbered, older claim first, with its label, its reason and the evidence.
   - I answer by number. They conflict → `link_items` (rel `contradicts`), which marks both disputed; then ask which one holds.
   - The newer one replaces the older → `link_items` from the newer to the older (rel `supersedes`), then `set_claim_status` with `superseded` on the older one.
   - No conflict → `link_items` (rel `related`), so the pair isn't suggested again.
5. **Open questions.** Ask about what you couldn't resolve: ambiguous decisions, unfinished work with no next step, and commitments with no deadline or owner. Ask at most 3, one at a time, and save what I answer with `propose_claim` or `update_claim`.

If I stop early, say what's left (for example "12 claims, 2 possible contradictions and 2 days of session notes") so the next review continues from there.

## Output

**Waiting for confirmation**: the numbered batch, each claim with its evidence.

**Possible contradictions**: the numbered pairs.

**Open questions**

**Saved**: a short list of what was confirmed, corrected, retracted and written, including the session notes.
