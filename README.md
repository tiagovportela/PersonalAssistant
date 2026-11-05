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

**The frontend** (`pwi open`) is where you see what the layer holds and control it: sources and projects, claims with their full history (where you can also confirm, retract or edit them: type, text, project, dates, owner and status, each change a new version recorded as yours, verified unless you choose otherwise), activity, confidential labels (the only place to remove one), retention per kind of data, and the audit trail. Deleting is done only here: deleting evidence lists the claims that rely on it, and you decide for each one whether to keep it (its evidence shows as deleted), retract it, or delete it too. The frontend listens on 127.0.0.1 only, on a new port and with a new sign-in link each time the service starts; `pwi open` always finds them.


| Command | What it does |
|---|---|
| `pwi add-repo PATH...` | Allowlists Git repositories, or every repository in a folder. Each becomes a project, and the Claude Code index turns on for sessions inside them. Collects straight away. |
| `pwi add-firefox [PROFILE]` | Turns on Firefox history: the profile Firefox opens by default (snap, classic or Flatpak), or the one given. Collects straight away. |
| `pwi app-usage on [--mode titles\|apps\|time]` | Records which apps and windows you use, and active vs idle time. Installs the reviewed GNOME extension, pinned; log out and back in once. |
| `pwi app-usage off`, `status` | Stops it and removes the extension; or shows what's recorded and what sampling costs. |
| `pwi sources` | Lists sources, how many events each holds, and the last collection, with any error. |
| `pwi disable ID` / `pwi enable ID` | Stops collecting a source and hides it from Claude; its data stays. |
| `pwi collect` | Collects every enabled source now. |
| `pwi import-cloud-session ID` | Brings a Claude Code cloud session (its `session_...` id or claude.ai/code link) into the layer. Run it in a clean checkout of the session's repository, or pass `--repo PATH`: it runs `claude --teleport`, which checks out the session's branch and loads the conversation; quit Claude Code with `/exit` once it has loaded. The layer then keeps a copy, switches your checkout back to its branch and collects. `--file F` imports a transcript you already have instead. `--list F` imports every session in a list that's missing or was updated in the cloud since its import, each in your checkout of its repository (`--check` only says which). Only a cloud session can list your cloud sessions: ask one to "list my cloud sessions for pwi" (see `CLAUDE.md`) and paste the command it gives you. |
| `pwi cleanup` | Applies retention now. It also runs by itself once a day. |
| `pwi open [SECTION]` | Opens the frontend in your browser, e.g. `pwi open confidential`. |
| `pwi eval label [DAY]`, `pwi eval report` | The 5-day evaluation, below. |
| `pwi google connect FILE`, `status`, `disconnect` | The layer's own read-only Google sign-in, for Google Chat. |

The service collects at login (catching up after a shutdown) and then every hour, also after the laptop wakes from sleep.

**Retention:** once a day, at the first moment the laptop has been idle for 5 minutes (from GNOME's idle monitor, which reads only the time since your last input), the service deletes what's past its retention: events after 90 days, unconfirmed claims not changed for 90 days, unconfirmed session notes about days over 90 days old, and audit entries after 90 days. Confirmed claims are kept until you delete them, and Claude says when their evidence has expired. Retracted claims stay for history. If the laptop is never idle, retention runs anyway after 26 hours.

**Online sources** (Phase 2): GitHub, Google Calendar, Notion, Gmail, Google Chat and Google Drive are read live by Claude through its connectors, set up in Claude Desktop; the layer keeps no copy. In the frontend's Online sources page you choose which of them Claude may use for your work, and within what (for example Gmail `label:work`). GitHub, Calendar and Notion start allowed; Gmail, Chat and Drive start off until you turn them on. On Projects, note where each project lives online (a Notion page, a Drive folder, a Gmail search, a Chat space), or let Claude add it when it finds one. Google Chat is the exception: the layer reads it itself, read-only, rather than through a Claude connector, so its allowlist is enforced in code (see below). Commit messages that mention a PR (`#12`), an issue key (`BILL-345`) or a Notion, Docs or Drive link are linked to that work automatically.

**What's collected:**
- **Git:** commits, merges and pushes from the last 90 days, plus a snapshot of the branch, ahead/behind and uncommitted-change counts whenever it changes. Only metadata is kept: subject, message (secrets redacted), author, times, files and line counts. Pushes come from Git's reflog. No hooks are installed, and Git never takes a lock while collecting.
- **Claude Code:** an index of sessions whose working folder is inside an allowlisted repository: start, end, Claude Code's title for the session (redacted), and prompt count. Session content is never copied; it stays in `~/.claude/projects` until Claude Code deletes it after 30 days. Cloud sessions (claude.ai/code) aren't on this computer, and there's no documented API to fetch them, so they come in only when you import one with `pwi import-cloud-session`. Those are the exception: the layer keeps a copy in `~/.local/share/pwi/claude_cloud`, indexed the same way with `origin` `cloud`, until retention or you delete the session.
- **Firefox** (Phase 4, once you turn it on): every page you open, read each hour from a copy of the profile's history, since Firefox locks the original. It's the one source read in full, so what's kept is cut down instead: only http and https pages you opened (not frames, downloads, reloads or redirect steps), never local addresses such as the frontend's, and no URL parameters that look like secrets (token, code, key, password, session, signature…) or tracking, no user names or passwords in addresses, no long random path parts. Titles are redacted. A visit to a project's GitHub repository, Notion page or Drive folder is linked to the project. A visit you delete in Firefox disappears from Claude's view at the next pass.
- **App usage** (Phase 4, once you turn it on): every 10 seconds, the focused window (through the reviewed [Focused Window D-Bus](third_party/focused-window-dbus) extension, since Wayland hides it) and the time since your last input, saved every 5 minutes as spans: a window, active time, or idle time (2 minutes without input, starting at your last input). Never keystrokes, the clipboard or the screen. Choose what's kept in the frontend's Sources page: app names and window titles (the default), app names only, or active and idle time only. Private browsing and password manager windows never keep their title. A window title naming a project's folder is linked to the project. If sampling gets slow, it falls back to active and idle time by itself, and `get_metrics` says so. On GNOME Shell older than 49 only active and idle time can be recorded.

Claude sees browsing and computer time as summaries (in `get_day`, `get_week` and `get_project`) and through search, as context: never as proof that something was done.

**Contradictions** (Phase 4): whenever Claude saves a claim, and in the end-of-day review, weekly review and project resumption, the layer points out pairs of claims about the same project that use mostly the same words but differ checkably: one negated, opposite words (keep/remove, manter/remover), "instead of", different numbers or dates, or two due dates or owners for one commitment. Nothing is changed by itself: you say whether they conflict (both become disputed), one replaced the other (the older becomes superseded), or they don't conflict, and the pair isn't suggested again.

**Upgrade:** `git pull && python3 install.py`. The service restarts with the new code, and upgrades the store if its schema changed, after copying it to `store.db.bak-v<old version>`. Claude Desktop's bridge reconnects on its own, so Claude Desktop only needs a restart when the tool list changes.

**Uninstall:** `python3 install.py --uninstall`. The store in `~/.local/share/pwi` is kept.

**Logs:** `journalctl --user -u pwi -f`. **Status:** `systemctl --user status pwi`.

## Google Chat

The layer reads Google Chat itself, live and never stored, with your own Google account and read-only access only: if Google ever granted it more, the sign-in is refused and revoked. It reads only the spaces you allow: those named in Google Chat's scope on the Online sources page, or linked to a project as a Chat alias (an empty scope means every space), and never a confidential project's spaces. Claude gets two tools for it, `chat_spaces` and `chat_messages`.

To set it up, once:
1. In a Google Cloud project (your company's, if your admin prefers): enable the **Google Chat API**, and fill in its **Configuration** page with an app name, avatar and description; Google requires that even for reading. Leave interactive features off.
2. **OAuth consent screen:** user type *Internal*, with the scopes `chat.spaces.readonly`, `chat.messages.readonly` and `chat.memberships.readonly`.
3. **Credentials:** create an OAuth client ID of type **Desktop app**, and download its JSON file.
4. On the laptop: `sudo apt install libsecret-tools` (so the sign-in is kept in GNOME Keyring), then `pwi google connect ~/Downloads/client_secret_….json`. Your browser opens Google's consent page.
5. `pwi open online`: turn Google Chat on, and name the spaces it may read.

If your Workspace admin restricts third-party apps, they need to allow this OAuth client once. `pwi google status` says who the layer is signed in as; `pwi google disconnect` revokes the sign-in at Google and forgets it.

## The 5-day evaluation

Before relying on the layer daily, test it against one real week you label by hand (brief §11 and §16). Your labels and the report are work data, so they stay in `~/.local/share/pwi/evaluation` and never go into the repository.

**Each workday, at the end of the day:**
1. `pwi eval label` opens today's file in your editor (`$EDITOR`, or the desktop's default). Write what really happened, before asking Claude about it, one item per line as `- project: what`: projects worked on, decisions, commitments (add `| due YYYY-MM-DD`), blockers and unfinished work. A few minutes is enough. A missed day can be labelled later with `pwi eval label 2026-11-09`.
2. In Claude Desktop, run the end-of-day review.

**During the week, in Claude Desktop:** ask for each day's briefing the next morning; resume a project; ask a what, a when and a why question; do one real task with it, such as a status update or meeting preparation. Restart the laptop once, to check collection catches up. Delete something in the frontend once.

**After the fifth day:** `pwi eval report` (or `--from` and `--to` for other days). It compares your labels with what the layer found and Claude saved:
- **Activity:** labelled project-days the layer saw or missed, and ones it recorded that you didn't label.
- **Claims:** your decisions, commitments, blockers and unfinished work against Claude's claims and session notes, with what was missed, and the claims that match no label for you to judge. This is where false commitments or completions that didn't happen would show.
- **Deadlines:** found with the right date, the wrong date, or missing.
- **Evidence, confirmation and collection:** citation coverage, how many of Claude's claims you confirmed, corrected or retracted, session-note coverage, collector gaps and ingestion lag.
- **No leaks:** it calls Claude's read tools over your week and checks that no confidential item, or item from a disabled source, appears in any result.
- **Your checks:** a tick list for what only you can judge, such as whether each briefing was right.

The brief sets the pass thresholds after this first week, from these numbers.

## Choosing the Whisper model (Phase 0)

Meeting transcription (Phase 3) runs Whisper on the laptop's CPU. Which model is accurate enough and fast enough on mixed Portuguese and English is decided by measuring, on the company laptop:

1. Put 3 to 5 real recordings in a folder, 10 to 15 minutes in all, mixing Portuguese and English as your meetings do. For each, write a hand-corrected transcript with the same name and `.txt`, e.g. `standup.m4a` and `standup.txt`. Without them the benchmark still measures speed and memory, and you judge the transcripts by eye.
2. Plug the laptop in, close heavy apps, and run `python3 bench/whisper_benchmark.py ~/path/to/folder`.

No recordings yet? `python3 bench/fetch_samples.py` downloads public sample sentences (Google's FLEURS, CC BY 4.0) with exact transcripts, and builds a Portuguese, an English and a mixed recording, about 9 minutes in all. Then run the benchmark on the folder it prints. Read sentences are easier than meetings, and its Portuguese is Brazilian, so they rank the models and measure speed well, but a real recording is still the better test of accuracy.

The first run sets up a separate environment in `~/.local/share/pwi/bench-venv` and installs faster-whisper there, every package checked against the hashes in `bench/requirements.txt`; the service never uses it. If Python's `venv` module is missing, it tells you to `sudo apt install python3-venv`. It then runs NVIDIA's Parakeet TDT 0.6B v3, and Whisper tiny, base, small, medium and large-v3-turbo, each Whisper model with the language detected once per window (`auto`) and per utterance between pauses (`utterance`, for meetings that switch between Portuguese and English), and reports speed, memory and word error rate, overall and per recording. It suggests the fastest model within 2 points of the best error rate that still runs at least twice as fast as real time. The report, every transcript, and the chosen model's revision and checksum (to pin it) stay in `~/.local/share/pwi/benchmark`. Expect it to take about an hour for 15 minutes of audio.

First results, from the dev PC on the sample recordings, are in [`docs/whisper_benchmark.md`](docs/whisper_benchmark.md): large-v3-turbo is the choice, because accuracy matters more than speed; Parakeet is 6.5 times faster but makes about twice the errors.

Reviews of the third-party code the brief needs (the GNOME Focused Window extension and the Google Chat servers) are in [`docs/third_party_reviews.md`](docs/third_party_reviews.md).

## Where things live

| What | Where |
|---|---|
| Store (SQLite) | `~/.local/share/pwi/store.db` |
| GNOME extension, when app usage is on | `~/.local/share/gnome-shell/extensions/focused-window-dbus-pinned@pwi.local` |
| Evaluation labels and reports | `~/.local/share/pwi/evaluation` |
| `pwi` command | `~/.local/bin/pwi` |
| Installed code | `~/.local/share/pwi/app` (`version.json` says which commit) |
| Socket the bridge connects to | `$XDG_RUNTIME_DIR/pwi/mcp.sock` (owner-only) |
| systemd unit | `~/.config/systemd/user/pwi.service` |

## Repository

| Folder | Contents |
|---|---|
| [`service/`](service) | The background service (`server.py`), the bridge Claude Desktop starts (`bridge.py`), the `pwi` CLI (`cli.py`), the collectors (`collect_*.py`), app usage and its GNOME extension installer (`app_usage.py`, `gnome_extension.py`), contradiction detection (`contradictions.py`), the read tools (`reads.py`), the write tools (`writes.py`), retention (`retention.py`), the frontend's web server and admin actions (`web.py`, `admin.py`), the evaluation (`evaluation.py`), secret redaction, the store setup and the MCP handlers. |
| [`contracts/`](contracts) | The MCP tool contracts, validation and the six experiences' instructions. |
| [`schema/`](schema) | The SQLite schema, and `migrations/` that upgrade an older store. |
| [`frontend/`](frontend) | The React frontend. `dist/` is the built app the service serves, committed so the laptop never needs Node.js. |
| [`third_party/`](third_party) | The reviewed GNOME extension, unchanged from upstream at the reviewed commit; installed only after a checksum check. |
| [`bench/`](bench) | The Phase 0 Whisper benchmark, with its own hash-pinned dependencies. |
| [`spikes/`](spikes) | Phase 0 spike, kept for reference. |

## Tests

Each test uses temporary folders and never touches an installed layer. Run them on both Python versions before pushing:

```bash
for t in schema/test_schema.py contracts/test_tools.py contracts/test_experiences.py service/test_service.py service/test_collectors.py service/test_reads.py service/test_writes.py service/test_privacy.py service/test_web.py service/test_evaluation.py service/test_online.py service/test_google_chat.py service/test_activity.py test_install.py; do
  python3 -I "$t" || break
done
```

After changing anything in `frontend/src`, rebuild and commit `frontend/dist` with it (Node.js 22, on the dev PC only):

```bash
cd frontend && npm ci && npm run build
```

Dependencies are pinned to exact versions, with integrity hashes in `package-lock.json`.

To test on Python 3.14 on the dev PC, use `uv python install 3.14` and run the same loop with `"$(uv python find 3.14)"` in place of `python3`.

## Status

Phases 1, 2 and 4 are built; Phase 3 (meetings) is on hold. All 20 tools work, with validation. The service collects Git, Claude Code sessions, Firefox history and app usage, saves claims and session notes, points out possible contradictions, applies retention once a day, and serves the local frontend. Claude uses Gmail, Drive and Notion within the allowlist you set, and Google Chat through the layer's own read-only sign-in, saves commitments and decisions from them with the message or document as evidence, and links projects to where they live online. `get_metrics` reports freshness, ingestion lag, project linking, claims by type, false commitments, project corrections, missed deadlines, contradictions and app usage's overhead. Next: the 5-day evaluation on real workdays (`pwi eval`).
