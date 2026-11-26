"""The end-of-day agent's runner: `pwi eod ...`, and the systemd timers that start it.

At the time I chose, on workdays, a timer runs `pwi eod run`. The layer collects, then starts Claude
Code headless (`claude -p`) in the notes folder of my Obsidian vault, with the agent's instructions
(contracts/agent/end_of_day.md). Claude reads my day through the layer and the connectors I allow,
saves claims and session notes, and writes the day's notes. Then the layer posts the claims to my
direct message with its Chat app (review.py). When I've answered them all, the service starts
`pwi eod finish`, which has Claude rewrite the day's notes with my answers; a morning timer catches
answers that came late.

Claude gets an exact list of tools, worked out from the tools Claude Code reports at each run:
- the layer's tools, except the three that need my approval;
- the connectors' tools whose names say they only read (search, get, list, read, fetch...), and
  none whose names say they change something (create, update, send, delete, share...);
- Edit (which also covers Write) only inside the notes folder. Reading needs no rule: it's allowed
  in the working directory, the notes folder, and nowhere else.
Everything else is denied: the run is in dontAsk mode, so nothing waits for an approval that nobody
is there to give. Claude Code runs signed in to my claude.ai account (the company Team account),
so it has the connectors I set up there; an API key in the environment is removed for the run,
since Claude Code doesn't load connectors with one.
"""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import chat_app
import collect
import paths
import review
import store
from tools import APPROVAL

HERE = Path(__file__).resolve().parent
AGENT = HERE.parent / "contracts" / "agent"
COMMON = HERE.parent / "contracts" / "instructions" / "common.md"
UNIT_DIR = paths.CONFIG_HOME / "systemd" / "user"
UNITS = ("pwi-eod.service", "pwi-eod.timer", "pwi-eod-finish.service", "pwi-eod-finish.timer")
TIMERS = ("pwi-eod.timer", "pwi-eod-finish.timer")
RUN_TIMEOUT = 50 * 60  # seconds Claude may take for the day
FINISH_TIMEOUT = 15 * 60
CHECK_TIMEOUT = 120
DAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

# Words in a tool's name. Allowed: at least one reading word and no changing word; anything else is denied.
READING = {"get", "list", "search", "read", "fetch", "find", "query", "view", "download", "lookup", "describe",
           "retrieve"}
CHANGING = {"create", "update", "delete", "remove", "trash", "send", "post", "share", "copy", "move", "duplicate",
            "merge", "push", "write", "edit", "add", "set", "insert", "upload", "append", "request", "assign",
            "archive", "fork", "run", "trigger", "enable", "disable", "resolve", "unresolve", "submit", "reply",
            "approve", "close", "reopen", "rename", "publish", "import", "invite", "schedule", "cancel", "patch",
            "put", "replace", "modify", "save", "mark", "subscribe", "unsubscribe", "accept", "decline", "respond",
            "rsvp", "complete", "execute", "apply", "restore", "transfer", "lock", "unlock", "pin", "unpin",
            "invoke", "start", "stop", "deploy", "release", "draft", "comment", "react", "forward", "revoke"}
SAFE_BUILTINS = {"Read", "Glob", "Grep", "LS", "TodoWrite", "ToolSearch", "ListMcpResourcesTool", "ReadMcpResourceTool"}
FILE_EDITS = {"Edit", "Write", "MultiEdit"}


class EodError(Exception):
    """Something to tell me in plain words: not set up, Claude Code missing, a run that failed."""


# Settings -------------------------------------------------------------------------------

def settings(db):
    return {"vault": store.setting(db, "eod.vault"), "folder": store.setting(db, "eod.folder", "Work"),
            "at": store.setting(db, "eod.at", "19:30"), "days": store.setting(db, "eod.days", "Mon..Fri"),
            "claude": store.setting(db, "eod.claude"),
            "overrides": json.loads(store.setting(db, "eod.overrides", '{"allow": [], "block": []}'))}


def weekdays(spec):
    """The weekday numbers in a systemd weekday spec such as Mon..Fri or Mon,Wed,Fri."""
    found = set()
    for part in spec.split(","):
        ends = [p.strip()[:3].title() for p in part.split("..")]
        if not all(e in DAYS for e in ends) or len(ends) > 2:
            raise EodError(f"'{spec}' isn't a list of days, e.g. Mon..Fri or Mon,Wed,Fri.")
        first, last = DAYS[ends[0]], DAYS[ends[-1]]
        found |= set(range(first, last + 1)) if first <= last else set(range(first, 7)) | set(range(0, last + 1))
    return found


def notes_dir(s):
    if not s["vault"]:
        raise EodError("The agent isn't set up yet. Run: pwi eod setup --vault PATH_TO_YOUR_VAULT")
    return Path(s["vault"]) / s["folder"]


def find_claude(given=None):
    found = given or shutil.which("claude") or next(
        (str(p) for p in (Path.home() / ".local/bin/claude", Path.home() / ".claude/local/claude") if p.exists()), None)
    if not found or not Path(found).exists():
        raise EodError("Claude Code isn't installed, or isn't on PATH. Install it, sign in once with `claude` "
                       "(your claude.ai Team account), then run this again.")
    return str(Path(found).absolute())  # not resolved: an npm install's link sits next to the node it needs


def setup(db, vault, folder="Work", at="19:30", days="Mon..Fri", claude=None, systemd=True):
    vault = Path(vault).expanduser().resolve()
    if not vault.is_dir():
        raise EodError(f"{vault} isn't a folder.")
    folder = folder.strip().strip("/")
    if not folder or folder.startswith(".") or ".." in Path(folder).parts:
        raise EodError("The notes folder is a folder inside the vault, e.g. Work.")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", at):
        raise EodError("The time is HH:MM, e.g. 19:30.")
    weekdays(days)
    claude = find_claude(claude)
    (vault / folder).mkdir(parents=True, exist_ok=True)
    for key, value in (("eod.vault", str(vault)), ("eod.folder", folder), ("eod.at", at), ("eod.days", days),
                       ("eod.claude", claude)):
        store.set_setting(db, key, value)
    db.execute("INSERT INTO audit_log (at, actor, action, item_type, item_id) VALUES (?, 'me', 'settings', 'eod', NULL)",
               (store.now(),))
    write_units(at, days, claude)
    if systemd:
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        done = subprocess.run(["systemctl", "--user", "enable", "--now", *TIMERS], capture_output=True, text=True)
        if done.returncode != 0:
            raise EodError(f"systemctl couldn't start the timers: {done.stderr.strip()}")
    return {"vault": str(vault), "notes": str(vault / folder), "at": at, "days": days, "claude": claude,
            "is_vault": (vault / ".obsidian").is_dir()}


def cli_path():
    installed = paths.APP_DIR / "service" / "cli.py"
    return installed if installed.exists() else HERE / "cli.py"


def write_units(at, days, claude):
    """The timers: the agent at the chosen time on workdays, and a morning pass for answers that came late.
    Missed runs (the laptop was off or asleep) happen at the next start."""
    python, cli = sys.executable, cli_path()
    # My shell's PATH at setup, so Claude Code finds what it found then (node, for an npm install).
    folders = [str(Path(claude).parent), *os.environ.get("PATH", "").split(":"), "/usr/local/bin", "/usr/bin", "/bin"]
    path = ":".join(dict.fromkeys(f for f in folders if f))
    service = ("[Unit]\nDescription=Work layer: {what}\nWants=pwi.service\nAfter=pwi.service network-online.target\n\n"
               f'[Service]\nType=oneshot\nEnvironment="PATH={path}"\n'
               f'ExecStart="{python}" -I "{cli}" eod {{step}}\nTimeoutStartSec={{limit}}\nNice=5\n')
    timer = ("[Unit]\nDescription=Work layer: {what}\n\n[Timer]\nOnCalendar={when}\nPersistent=true\n\n"
             "[Install]\nWantedBy=timers.target\n")
    texts = {
        "pwi-eod.service": service.format(what="end-of-day agent", step="run", limit=RUN_TIMEOUT + 600),
        "pwi-eod.timer": timer.format(what=f"end-of-day agent at {at}", when=f"{days} *-*-* {at}:00"),
        "pwi-eod-finish.service": service.format(what="end-of-day notes after my review", step="finish",
                                                 limit=FINISH_TIMEOUT + 300),
        "pwi-eod-finish.timer": timer.format(what="end-of-day notes, morning pass", when="*-*-* 08:30:00"),
    }
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in texts.items():
        (UNIT_DIR / name).write_text(text, encoding="utf-8")


def remove_units(systemd=True):
    if systemd and (UNIT_DIR / TIMERS[0]).exists():
        subprocess.run(["systemctl", "--user", "disable", "--now", *TIMERS], capture_output=True)
    for name in UNITS:
        (UNIT_DIR / name).unlink(missing_ok=True)
    if systemd:
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)


def start_finish(day=None):
    """Called by the service when I've answered a whole review: rewrite the notes now, in the background."""
    if (UNIT_DIR / "pwi-eod-finish.service").exists() and os.environ.get("PWI_NO_SYSTEMD") != "1":
        subprocess.run(["systemctl", "--user", "start", "--no-block", "pwi-eod-finish.service"], capture_output=True)


# Which tools Claude gets ------------------------------------------------------------------

def words(name):
    name = re.sub(r"(?i)(pull|merge)[_-]?requests?", "pr", name)  # a noun, not a request to do something
    return {w.lower() for w in re.split(r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])", name) if w}


def reads_only(name):
    found = words(name)
    return bool(found & READING) and not found & CHANGING


def classify(names, overrides=None):
    """(allowed, blocked) tool names: the layer's tools without the approval ones, connectors' tools that only
    read, and the built-in tools that only read. My overrides come last.

    The file-editing tools are in neither list: a run allows them through its Edit rule, inside the notes folder
    only, and a deny would override that rule. They're denied only if I block one, and never allowed everywhere."""
    overrides = overrides or {}
    allowed, blocked = [], []
    for name in sorted(set(names)):
        if name in FILE_EDITS:
            if name in overrides.get("block", []):
                blocked.append(name)
            continue
        if name.startswith("mcp__pwi__"):
            ok = name.removeprefix("mcp__pwi__") not in APPROVAL
        elif name.startswith("mcp__"):
            ok = reads_only(name.removeprefix("mcp__").split("__", 1)[-1])
        else:
            ok = name in SAFE_BUILTINS
        if name in overrides.get("allow", []):
            ok = True
        if name in overrides.get("block", []):
            ok = False
        (allowed if ok else blocked).append(name)
    return allowed, blocked


def bridge_config():
    installed = paths.APP_DIR / "service" / "bridge.py"
    bridge = installed if installed.exists() else HERE / "bridge.py"
    path = paths.RUNTIME_DIR / "eod-mcp.json"
    paths.RUNTIME_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": {"pwi": {"command": sys.executable, "args": ["-I", str(bridge)]}}}))
    return path


def child_env(claude):
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    env["PATH"] = f"{Path(claude).parent}:{env.get('PATH', '/usr/bin:/bin')}"
    return env


def discover(s, cwd):
    """The tools Claude Code has right now, from the init event it prints before Claude starts answering;
    stopped there, so no turn is spent."""
    argv = [s["claude"], "-p", "--output-format", "stream-json", "--verbose", "--max-turns", "1",
            "--permission-mode", "dontAsk", "--mcp-config", str(bridge_config())]
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, cwd=cwd, env=child_env(s["claude"]))
    except OSError as e:
        raise EodError(f"Claude Code couldn't start: {e}") from None
    found = queue.Queue()

    def read_until_init():
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "system" and event.get("subtype") == "init":
                found.put(event)
                return
        found.put(None)  # Claude Code exited without one

    try:
        proc.stdin.write("Reply with the single word OK.")
        proc.stdin.close()
    except OSError:
        pass  # it exited already; what it printed says why
    threading.Thread(target=read_until_init, daemon=True).start()
    try:
        init = found.get(timeout=CHECK_TIMEOUT)
        late = None
    except queue.Empty:
        init, late = None, f"no answer within {CHECK_TIMEOUT} seconds"
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    err = late or proc.stderr.read()
    proc.stderr.close()
    if init is None:
        raise EodError("Claude Code didn't start: " + ((err or "").strip()[-400:] or "no output") +
                       "\nCheck it runs with `claude`, signed in to your claude.ai Team account.")
    return init


def check(db, allow=(), block=()):
    """Works out the tool list and saves it; returns what the run would get, by server."""
    s = settings(db)
    overrides = s["overrides"]
    for name in allow:
        overrides["block"] = [n for n in overrides["block"] if n != name]
        overrides["allow"] = sorted(set(overrides["allow"]) | {name})
    for name in block:
        overrides["allow"] = [n for n in overrides["allow"] if n != name]
        overrides["block"] = sorted(set(overrides["block"]) | {name})
    store.set_setting(db, "eod.overrides", json.dumps(overrides))
    init = discover(s, notes_dir(s))
    names = [t if isinstance(t, str) else (t or {}).get("name") for t in init.get("tools") or []]
    allowed, blocked = classify([n for n in names if n], overrides)
    servers = [{"name": m.get("name"), "status": m.get("status")} for m in init.get("mcp_servers") or []]
    store.set_setting(db, "eod.tools", json.dumps({"checked_at": store.now(), "allowed": allowed, "blocked": blocked,
                                                    "servers": servers}))
    return {"allowed": allowed, "blocked": blocked, "servers": servers,
            "pwi_connected": any(m["name"] == "pwi" and m["status"] == "connected" for m in servers)}


def edit_rule(folder):
    """Edit (and Write) only inside this folder. Claude Code reads //path as an absolute path."""
    return f"Edit(/{Path(folder).resolve()}/**)"


def claude_argv(s, allowed, blocked, edits_in):
    return [s["claude"], "-p", "--output-format", "json", "--permission-mode", "dontAsk",
            "--mcp-config", str(bridge_config()),
            "--allowedTools", *allowed, edit_rule(edits_in),
            "--disallowedTools", *sorted(set(blocked) | {"Bash", "WebFetch", "WebSearch", "NotebookEdit", "Task", "Agent"})]


def ask_claude(s, prompt, allowed, blocked, cwd, edits_in, timeout):
    """Runs Claude once, headless. Returns Claude Code's result: is_error, num_turns, duration_ms, result,
    permission_denials."""
    try:
        done = subprocess.run(claude_argv(s, allowed, blocked, edits_in), input=prompt, capture_output=True, text=True,
                              cwd=cwd, env=child_env(s["claude"]), timeout=timeout)
    except subprocess.TimeoutExpired:
        raise EodError(f"Claude didn't finish within {timeout // 60} minutes and was stopped.") from None
    except OSError as e:
        raise EodError(f"Claude Code couldn't start: {e}") from None
    try:
        result = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise EodError(f"Claude Code failed (exit {done.returncode}): {(done.stderr or done.stdout).strip()[-400:]}") from None
    if result.get("is_error"):
        raise EodError(f"Claude stopped with an error: {str(result.get('result') or result.get('subtype'))[:400]}")
    return result


def run_detail(result):
    denied = sorted({d.get("tool_name") for d in result.get("permission_denials") or [] if d.get("tool_name")})
    return (f"{result.get('num_turns', '?')} turns, {round((result.get('duration_ms') or 0) / 60000, 1)} min"
            + (f"; denied: {', '.join(denied)}" if denied else ""))


# Runs ---------------------------------------------------------------------------------

def workday(s, now=None):
    """The day a run is about: today in the afternoon or evening; in the morning (a run the laptop
    missed), the last workday before today."""
    now = now or datetime.now()
    if now.hour >= 12:
        return now.date().isoformat()
    days = weekdays(s["days"])
    day = now.date() - timedelta(days=1)
    while day.weekday() not in days:
        day -= timedelta(days=1)
    return day.isoformat()


def render(name, **values):
    text = (AGENT / f"{name}.md").read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def begin(db, day, kind):
    return db.execute("INSERT INTO eod_runs (day, kind, started_at, status) VALUES (?, ?, ?, 'running')",
                      (day, kind, store.now())).lastrowid


def end(db, run_id, status, detail):
    db.execute("UPDATE eod_runs SET finished_at = ?, status = ?, detail = ? WHERE id = ?",
               (store.now(), status, detail[:1000], run_id))


def run(db, day=None, force=False, post=True):
    """The 19:30 run. Returns {day, status, detail, review}. Without post, the claims aren't sent to the Chat
    review (run_range sends them once, at the end)."""
    s = settings(db)
    folder = notes_dir(s)
    day = day or workday(s)
    if not force and db.execute("SELECT 1 FROM eod_runs WHERE day = ? AND kind = 'run' AND status = 'ok'",
                                (day,)).fetchone():
        return {"day": day, "status": "skipped", "detail": f"{day} already ran. Use --force to run it again."}
    folder.mkdir(parents=True, exist_ok=True)
    run_id = begin(db, day, "run")
    detail, status, posted = "", "ok", None
    try:
        collect.run(paths.STORE_PATH, "schedule")
        tools = check(db)
        connected = chat_app.connected()
        prompt = render("end_of_day", day=day, weekday=date.fromisoformat(day).strftime("%A"), folder=s["folder"],
                        review="the Chat app is connected" if connected and review.review_space(db) else
                        "the Chat app isn't set up yet, so they wait for the review in Claude Desktop")
        prompt += "\n\n---\n\n" + COMMON.read_text(encoding="utf-8")
        result = ask_claude(s, prompt, tools["allowed"], tools["blocked"], folder, folder, RUN_TIMEOUT)
        detail = run_detail(result)
    except EodError as e:
        status, detail = "failed", str(e)
    try:  # what Claude saved before a failure is worth reviewing too
        if post and chat_app.connected():
            posted = review.post_batch(db, chat_app.App(), day)
            if posted.get("gaps"):
                detail += f"; review not posted: {posted['gaps'][0]}"
    except chat_app.AppError as e:
        detail += f"; review not posted: {e}"
    end(db, run_id, status, detail)
    return {"day": day, "status": status, "detail": detail, "review": posted}


def days_between(s, start, end):
    """The workdays (my --days) from start to end, both included, oldest first."""
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise EodError("Give the days as YYYY-MM-DD, e.g. --from 2026-11-02 --to 2026-11-25.") from None
    if first > last:
        raise EodError(f"--from {start} is after --to {end}.")
    if last > date.today():
        raise EodError(f"--to {end} is in the future.")
    days = weekdays(s["days"])
    return [(first + timedelta(n)).isoformat() for n in range((last - first).days + 1)
            if (first + timedelta(n)).weekday() in days]


def run_range(db, start, end, force=False, each=None):
    """Runs the agent for each workday from start to end, oldest first, so each summary can link the one before.
    Days that already ran are skipped unless forced. The claims go to the Chat review once, after the last day,
    instead of one review per day. each(result) is called after every day, to show progress."""
    s = settings(db)
    results = []
    for day in days_between(s, start, end):
        result = run(db, day, force, post=False)
        results.append(result)
        if each:
            each(result)
    posted = None
    if results and chat_app.connected():
        try:
            posted = review.post_batch(db, chat_app.App(), results[-1]["day"])
        except chat_app.AppError as e:
            posted = {"posted": 0, "gaps": [str(e)]}
    return {"days": results, "review": posted}


def answers(db, day):
    """The answers for a day's notes: (the items' ids, one line per answer: the claim id, my answer, and its text now).
    The text comes through the confidential filter: a claim labelled confidential since, or deleted, is named by
    its id only, to be taken out of the notes."""
    rows = db.execute("SELECT i.id, i.claim_id, i.answer, s.text, c.id AS exists_now FROM review_items i"
                      " JOIN review_batches b ON b.id = i.batch_id"
                      " LEFT JOIN claims_shareable s ON s.id = i.claim_id LEFT JOIN current_claims c ON c.id = i.claim_id"
                      " WHERE b.day = ? AND i.answer IS NOT NULL ORDER BY b.posted_at, i.position", (day,)).fetchall()
    return [r["id"] for r in rows], "\n".join(
        f"{r['claim_id']}  {r['answer']}  " + (r["text"].replace(chr(10), " ") if r["text"] is not None else
                                                 "(now confidential: remove its line)" if r["exists_now"] else
                                                 "(deleted: remove its line)") for r in rows)


def days_to_finish(db):
    """Days with an answer the notes don't show yet."""
    return [r[0] for r in db.execute(
        "SELECT DISTINCT b.day FROM review_batches b JOIN review_items i ON i.batch_id = b.id"
        " WHERE i.answer IN ('confirmed', 'corrected', 'disputed', 'retracted') AND i.noted = 0 ORDER BY b.day")]


def finish(db, day=None):
    """Rewrites the notes of each day I answered since their last rewrite. Returns one result per day."""
    s = settings(db)
    folder = notes_dir(s)
    results = []
    for d in ([day] if day else days_to_finish(db)):
        daily = folder / "Daily" / d
        if not daily.is_dir():
            results.append({"day": d, "status": "skipped", "detail": f"No notes in {daily}."})
            continue
        run_id = begin(db, d, "finish")
        try:
            # Only the answers Claude is given count as in the notes: one that comes in while it works stays due.
            seen, lines = answers(db, d)
            prompt = render("end_of_day_finish", day=d, weekday=date.fromisoformat(d).strftime("%A"),
                            folder=s["folder"], answers=lines or "(no answers recorded)")
            result = ask_claude(s, prompt, ["mcp__pwi__get_day"], [], folder, daily, FINISH_TIMEOUT)
            db.executemany("UPDATE review_items SET noted = 1 WHERE id = ?", [(i,) for i in seen])
            db.execute("UPDATE review_batches SET notes_updated_at = ? WHERE day = ?", (store.now(), d))
            end(db, run_id, "ok", run_detail(result))
            results.append({"day": d, "status": "ok"})
        except EodError as e:
            end(db, run_id, "failed", str(e))
            results.append({"day": d, "status": "failed", "detail": str(e)})
    return results


def status(db):
    s = settings(db)
    tools = json.loads(store.setting(db, "eod.tools", "{}"))
    runs = [dict(r) for r in db.execute("SELECT day, kind, started_at, status, detail FROM eod_runs ORDER BY id DESC LIMIT 5")]
    waiting = db.execute("SELECT COUNT(*) FROM review_items i JOIN review_batches b ON b.id = i.batch_id"
                         " WHERE b.status = 'open' AND i.answer IS NULL").fetchone()[0]
    return {"settings": s, "timers": all((UNIT_DIR / t).exists() for t in TIMERS), "tools": tools, "runs": runs,
            "waiting": waiting, "chat_app": chat_app.connected(), "review_space": review.review_space(db),
            "chat_app_error": store.setting(db, "chat_app.last_error"),
            "chat_app_last_event": store.setting(db, "chat_app.last_event_at")}
