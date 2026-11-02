# Personal Work Intelligence layer

A private, local context layer that gives Claude Desktop evidence-backed knowledge of my work. What it must do is in [`docs/`](docs) (project brief v0.6, architecture v0.2).

It's built on my personal PC and runs on the company laptop (Ubuntu 26.04, Python 3.14). The code uses only Python's standard library, so installing it needs no packages and no network access.

## Install on the company laptop

Requirements: Ubuntu with systemd, Python 3.12 or newer (the system `python3`), Git, and Claude Desktop for Linux.

```bash
git clone git@github.com:tiagovportela/PersonalAssistant.git
cd PersonalAssistant
python3 install.py
```

The installer:
- checks Python, SQLite, systemd and Git, and that Claude Desktop's config is readable, before changing anything;
- copies the code to `~/.local/share/pwi/app`, so the clone can be pulled or moved without breaking the running service;
- writes and starts the systemd user service `pwi`, which starts at every login, then checks that it answers;
- puts the `pwi` command in `~/.local/bin`;
- registers the bridge as `pwi` in Claude Desktop's `mcpServers`, keeping every other setting. The original config is backed up once as `claude_desktop_config.json.bak-before-pwi`, and the Phase 0 `pwi-spike` entry and service are removed.

Then quit Claude Desktop completely (Ctrl+Q, or Quit from the tray icon) and open it again. In its tool permissions for `pwi`, set `set_claim_status`, `add_confidential_label` and `read_confidential` to "Ask every time" and every other tool to "Always allow".

Then allowlist the repositories to collect. Nothing is read until you do:

```bash
pwi add-repo ~/Projects
```

A folder allowlists every Git repository in it, up to 4 levels down. It skips hidden folders, dependency and build folders such as `node_modules`, and broken `.git` folders. Run the same command again to add repositories created since; one you disabled stays off. A single repository works too: `pwi add-repo ~/Projects/some-repo`.

## Using it

| Command | What it does |
|---|---|
| `pwi add-repo PATH...` | Allowlists Git repositories, or every repository in a folder. Each becomes a project, and the Claude Code index turns on for sessions inside them. Collects straight away. |
| `pwi sources` | Lists sources, how many events each holds, and the last collection, with any error. |
| `pwi disable ID` / `pwi enable ID` | Stops collecting a source and hides it from Claude; its data stays. |
| `pwi collect` | Collects every enabled source now. |

The service collects at login (catching up after a shutdown) and then every hour, also after the laptop wakes from sleep.

**What's collected:**
- **Git:** commits, merges and pushes from the last 90 days, plus a snapshot of the branch, ahead/behind and uncommitted-change counts whenever it changes. Only metadata is kept: subject, message (secrets redacted), author, times, files and line counts. Pushes come from Git's reflog. No hooks are installed, and Git never takes a lock while collecting.
- **Claude Code:** an index of sessions whose working folder is inside an allowlisted repository: start, end, Claude Code's title for the session (redacted), and prompt count. Session content is never copied; it stays in `~/.claude/projects` until Claude Code deletes it after 30 days.

**Upgrade:** `git pull && python3 install.py`. The service restarts with the new code, and upgrades the store if its schema changed, after copying it to `store.db.bak-v<old version>`. Claude Desktop's bridge reconnects on its own, so Claude Desktop only needs a restart when the tool list changes.

**Uninstall:** `python3 install.py --uninstall`. The store in `~/.local/share/pwi` is kept.

**Logs:** `journalctl --user -u pwi -f`. **Status:** `systemctl --user status pwi`.

## Where things live

| What | Where |
|---|---|
| Store (SQLite) | `~/.local/share/pwi/store.db` |
| `pwi` command | `~/.local/bin/pwi` |
| Installed code | `~/.local/share/pwi/app` (`version.json` says which commit) |
| Socket the bridge connects to | `$XDG_RUNTIME_DIR/pwi/mcp.sock` (owner-only) |
| systemd unit | `~/.config/systemd/user/pwi.service` |

## Repository

| Folder | Contents |
|---|---|
| [`service/`](service) | The background service (`server.py`), the bridge Claude Desktop starts (`bridge.py`), the `pwi` CLI (`cli.py`), the collectors (`collect_*.py`), the read tools (`reads.py`), secret redaction, the store setup and the MCP handlers. |
| [`contracts/`](contracts) | The MCP tool contracts, validation and the six experiences' instructions. |
| [`schema/`](schema) | The SQLite schema, and `migrations/` that upgrade an older store. |
| [`spikes/`](spikes) | Phase 0 spike, kept for reference. |

## Tests

Each test uses temporary folders and never touches an installed layer. Run them on both Python versions before pushing:

```bash
for t in schema/test_schema.py contracts/test_tools.py contracts/test_experiences.py service/test_service.py service/test_collectors.py service/test_reads.py test_install.py; do
  python3 -I "$t" || break
done
```

To test on Python 3.14 on the dev PC, use `uv python install 3.14` and run the same loop with `"$(uv python find 3.14)"` in place of `python3`.

## Status

The service serves all 17 tools with validation and collects Git and Claude Code sessions. Working: `get_instructions` and the prompts, and the read tools `list_projects`, `get_day`, `get_week`, `get_project`, `search`, `list_unconfirmed` and `get_evidence`. Daily briefing, project resumption, search and weekly review work end to end, using connectors for the online sources. Not built yet: the write tools (they save nothing), `read_claude_sessions`, `get_metrics` and `read_confidential`. Next: claims and session notes, for the end-of-day review.
