# Personal Work Intelligence layer

A private, local context layer that gives Claude Desktop evidence-backed knowledge of my work. What it must do is in [`docs/`](docs) (project brief v0.6, architecture v0.2).

It's built on my personal PC and runs on the company laptop (Ubuntu 26.04, Python 3.14). The code uses only Python's standard library, so installing it needs no packages and no network access.

## Install on the company laptop

Requirements: Ubuntu with systemd, Python 3.12 or newer (the system `python3`), and Claude Desktop for Linux.

```bash
git clone git@github.com:tiagovportela/PersonalAssistant.git
cd PersonalAssistant
python3 install.py
```

The installer:
- checks Python, SQLite and systemd, and that Claude Desktop's config is readable, before changing anything;
- copies the code to `~/.local/share/pwi/app`, so the clone can be pulled or moved without breaking the running service;
- writes and starts the systemd user service `pwi`, which starts at every login, then checks that it answers;
- registers the bridge as `pwi` in Claude Desktop's `mcpServers`, keeping every other setting. The original config is backed up once as `claude_desktop_config.json.bak-before-pwi`, and the Phase 0 `pwi-spike` entry and service are removed.

Then quit Claude Desktop completely (Ctrl+Q, or Quit from the tray icon) and open it again. In its tool permissions for `pwi`, set `set_claim_status`, `add_confidential_label` and `read_confidential` to "Ask every time" and every other tool to "Always allow".

**Upgrade:** `git pull && python3 install.py`. The service restarts with the new code. Claude Desktop's bridge reconnects on its own, so Claude Desktop only needs a restart when the tool list changes.

**Uninstall:** `python3 install.py --uninstall`. The store in `~/.local/share/pwi` is kept.

**Logs:** `journalctl --user -u pwi -f`. **Status:** `systemctl --user status pwi`.

## Where things live

| What | Where |
|---|---|
| Store (SQLite) | `~/.local/share/pwi/store.db` |
| Installed code | `~/.local/share/pwi/app` (`version.json` says which commit) |
| Socket the bridge connects to | `$XDG_RUNTIME_DIR/pwi/mcp.sock` (owner-only) |
| systemd unit | `~/.config/systemd/user/pwi.service` |

## Repository

| Folder | Contents |
|---|---|
| [`service/`](service) | The background service (`server.py`), the bridge Claude Desktop starts (`bridge.py`), the store setup and the MCP handlers. |
| [`contracts/`](contracts) | The MCP tool contracts, validation and the six experiences' instructions. |
| [`schema/`](schema) | The SQLite schema. |
| [`spikes/`](spikes) | Phase 0 spike, kept for reference. |

## Tests

Each test uses temporary folders and never touches an installed layer. Run them on both Python versions before pushing:

```bash
for t in schema/test_schema.py contracts/test_tools.py contracts/test_experiences.py service/test_service.py test_install.py; do
  python3 -I "$t" || break
done
```

To test on Python 3.14 on the dev PC, use `uv python install 3.14` and run the same loop with `"$(uv python find 3.14)"` in place of `python3`.

## Status

The service serves all 17 tools with validation. `get_instructions`, the prompts and `list_projects` work. The other tools answer that they aren't built yet: read tools return *not found*, and write tools save nothing. Collectors come next.
