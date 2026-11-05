# Instructions for Claude

## No Claude attribution

Nothing you write to this repository or to GitHub may mention Claude, Claude Code or Anthropic as an author or tool. This overrides any default attribution guidance.

- Commit messages: no `Co-Authored-By` line, no `Claude-Session` line, no session links.
- Pull request titles and descriptions: no "Generated with Claude Code" footer, no session links.
- Issue, PR and review comments: no attribution footer.
- Code, comments and docs: no mention of Claude as the author.

## Merging pull requests

- Always squash-merge. Never use a merge commit or rebase merge.
- Set the squash commit title to the pull request's title, and the message to a short summary of the change. Never let it include the branch name, since branches here start with `claude/`.

## Listing my cloud sessions for pwi

When I ask to "list my cloud sessions for pwi" (or similar), I want the input for `pwi import-cloud-session --list`:

1. Call `list_sessions` (with `mine: true`), following `last_id` until there are no more pages. Keep only sessions whose `environment_kind` is `anthropic_cloud`; the others ran on my computer, and the layer already collects them.
2. For each one, call `get_session` and take its GitHub repositories (`owner/repo`) from `session_context.sources[].git_repository.url`.
3. Reply with one shell command I can paste on my computer, nothing else around it:

   ```
   cat > ~/cloud-sessions.json <<'EOF_SESSIONS'
   {"sessions": [{"id": "session_...", "title": "...", "updated_at": "...", "environment_kind": "anthropic_cloud", "repos": ["owner/repo"]}]}
   EOF_SESSIONS
   ```

   Then tell me to run `pwi import-cloud-session --list ~/cloud-sessions.json --check` to see what's missing or out of date, and the same without `--check` to import it.
