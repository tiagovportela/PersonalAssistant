"""The `pwi` command: allowlist repositories and collect on demand, until the
frontend exists. install.py puts a `pwi` launcher in ~/.local/bin.

    pwi add-repo PATH...   allowlist Git repositories (each becomes a project); a folder
                           allowlists every repository in it, and running it again adds new ones
    pwi add-firefox [PROFILE]  read Firefox history (the default profile, or the folder given)
    pwi sources            list sources, what they hold and their last collection
    pwi disable ID         stop collecting a source and hide it from Claude; its data stays
    pwi enable ID          turn it back on
    pwi collect            collect every enabled source now
    pwi import-cloud-session ID  bring a Claude Code cloud session (id or claude.ai/code link) into the
                           layer: runs claude --teleport in this checkout and keeps a copy; --repo PATH
                           for another checkout, --file F to import a transcript you already have;
                           --list F imports every session in a list that's missing or out of date
                           (--check only says which), each in your checkout of its repository
    pwi cleanup            apply retention now (it also runs once a day by itself)
    pwi open [SECTION]     open the frontend in the browser, e.g. pwi open claims
    pwi eval label [DAY]   write down what really happened on a workday (default: today)
    pwi eval report        compare your labelled days with what the layer found
    pwi app-usage on       record which apps and windows I use, and active vs idle time
                           (--mode titles, apps or time); installs the reviewed GNOME extension
    pwi app-usage off      stop, and remove the extension
    pwi app-usage status   what's being recorded, and how the extension is doing
    pwi google connect F   sign the layer in to Google, read-only, with the OAuth client file F
    pwi google status      who the layer is signed in as
    pwi google disconnect  revoke the layer's Google sign-in and forget it
    pwi chat-app connect KEY  connect the layer's Google Chat app (its service account key), which posts
                           the end-of-day review to my direct message with it; --subscription NAME
    pwi chat-app status    whether it's connected, and where the review goes
    pwi chat-app disconnect  forget the app's key
    pwi eod setup --vault PATH  turn on the end-of-day agent: the Obsidian vault, --folder (Work),
                           --at (19:30) and --days (Mon..Fri); starts its timers
    pwi eod check          which tools the agent gets: the layer's, connectors' read-only tools, the notes folder
                           (--allow TOOL or --block TOOL to change one)
    pwi eod run [--day D]  run the agent now (the timer runs it by itself); --force runs a day again;
                           --from D --to D runs every workday in a range, oldest first
    pwi eod finish [--day D]  rewrite the day's notes with my answers from the Chat review
    pwi eod status         settings, last runs, and what's waiting in the review
    pwi eod off            stop the timers
    pwi wiki compile       update the wiki pages that need it: stale ones, and active projects' pages not
                           written yet (at most 5; --max N). --page ID for one page, --all for every project's
                           page. It also runs by itself after each end-of-day run
    pwi wiki status        the wiki's pages, which are due, and the last compile runs
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]

import argparse  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import shlex  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from datetime import date  # noqa: E402
import webbrowser  # noqa: E402
from contextlib import closing  # noqa: E402

import app_usage  # noqa: E402
import chat_app  # noqa: E402
import cloud_sessions  # noqa: E402
import collect  # noqa: E402
import eod  # noqa: E402
import wiki_compile  # noqa: E402
import evaluation  # noqa: E402
import gnome_extension  # noqa: E402
import google_signin as google  # noqa: E402
import paths  # noqa: E402
import retention  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402
from batch import CollectorError  # noqa: E402


def print_runs(results):
    if not results:
        print("Nothing to collect yet. Allowlist a repository first: pwi add-repo PATH")
    for r in results:
        if r["status"] == "ok":
            print(f"  {r['name']}: {r['inserted']} new, {r['changed']} changed, {r['unchanged']} unchanged,"
                  f" {r['gone']} gone")
        else:
            print(f"  {r['name']}: failed: {r['error']}")


def open_frontend(section=""):
    """The running service writes its frontend's address and a login link at each start."""
    try:
        info = json.loads((paths.RUNTIME_DIR / "frontend.json").read_text())
    except (OSError, ValueError):
        print("error: the service isn't running. Start it with: systemctl --user start pwi", file=sys.stderr)
        return 1
    print(f"Opening the frontend at http://127.0.0.1:{info['port']}")
    link = info["login_url"] + (f"&to={section}" if section else "")
    if not webbrowser.open(link):
        print(f"No browser opened. Open this link yourself: {link}")
    return 0


def label_day(db, day):
    try:
        date.fromisoformat(day)
    except ValueError:
        print("error: give the day as YYYY-MM-DD", file=sys.stderr)
        return 1
    path = evaluation.label_path(day)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(evaluation.template(db, day), encoding="utf-8")
        path.chmod(0o600)
    print(f"Labels for {day}: {path}")
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if editor:
        return subprocess.call([*shlex.split(editor), str(path)])
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


def report_days(start, end):
    days = evaluation.labelled_days(start, end)
    if not days:
        print("No labelled days yet. Start with: pwi eval label", file=sys.stderr)
        return 1
    text, summary = evaluation.report(paths.STORE_PATH, days)
    out = evaluation.folder() / f"report-{days[0]}-to-{days[-1]}.md"
    out.write_text(text, encoding="utf-8")
    out.chmod(0o600)
    print(f"{summary['days']} labelled days. Activity found: {summary['activity_recall']}. "
          f"Leaks: {summary['leaks']}.")
    if summary["unknown_projects"]:
        print(f"Unknown project names in your labels: {', '.join(summary['unknown_projects'])}")
    print(f"Report, with the checks to tick: {out}")
    return 0


MODE_TEXT = {"titles": "app names and window titles", "apps": "app names only", "time": "active and idle time only"}


def app_usage_command(db, args):
    if args.step == "off":
        app_usage.turn_off(db)
        gnome_extension.uninstall()
        print("App usage is off, and the extension is removed. What was recorded stays until retention or you delete it.")
        return 0
    if args.step == "on":
        app_usage.turn_on(db, args.mode)
        mode = app_usage.mode(db)
        print(f"App usage is on: {MODE_TEXT[mode]}. The service starts sampling within a minute.")
        if mode != "time":
            try:
                result = gnome_extension.install()
                print(f"Installed the reviewed Focused Window D-Bus extension (commit {gnome_extension.COMMIT[:7]}).")
                for step in result["todo"]:
                    print(f"  To do: {step}")
            except gnome_extension.ExtensionError as e:
                print(f"  {e}")
                print("  Until then, only active and idle time is recorded.")
        return 0
    s = app_usage.status(db)
    if not s.get("source_id"):
        print("App usage is off. Turn it on with: pwi app-usage on")
        return 0
    print(f"App usage is {'on' if s['on'] else 'off'}: {MODE_TEXT[s['mode']]}.")
    if s.get("last_sample_at"):
        print(f"  Recording: {MODE_TEXT[s['mode_in_use']]}; last write {s['last_sample_at']}, "
              f"{s['average_sample_ms']} ms per sample on average.")
    if s.get("fallback"):
        print(f"  Fallback: {s['fallback']}")
    ext = gnome_extension.status()
    print(f"  GNOME Shell {ext['gnome_shell'] or 'not found'}; extension "
          + ("running" if ext["running"] else "installed, waiting for a new login: log out and back in once"
             if ext["installed"] else "not installed"))
    return 0


def google_command(args):
    os.umask(0o077)
    try:
        if args.step == "connect":
            def show(url):
                print(f"Opening Google's sign-in page. If no browser opens, visit:\n{url}\n")
                webbrowser.open(url)
            done = google.connect(args.client_json, show)
            print(f"Signed in as {done['email']}, read-only. The sign-in is kept in {done['stored_in']}.")
            if not google.keyring_available():
                print("To keep it in GNOME Keyring instead of a file: sudo apt install libsecret-tools, then connect again.")
            print("Turn Google Chat on, and choose its spaces, with: pwi open online")
        elif args.step == "status":
            s = google.status()
            print(f"Signed in as {s['email']}, read-only, kept in {'GNOME Keyring' if s['keyring'] else 'a file'}."
                  if s["connected"] else "Not signed in. Run: pwi google connect CLIENT_JSON")
        else:
            print("Signed out; Google's access was revoked." if google.disconnect() else "The layer wasn't signed in.")
    except (google.GoogleError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def chat_app_command(args):
    os.umask(0o077)
    try:
        if args.step == "connect":
            done = chat_app.connect(args.key_json, args.subscription)
            print(f"Connected the Chat app as {done['client_email']}, reading {done['subscription']}. "
                  f"Its key is kept in {done['stored_in']}; you can delete {args.key_json} now.")
            print("In Google Chat, open a direct message with the app: the layer records it and posts the review there.")
            if not google.status()["connected"]:
                print("Also sign in with: pwi google connect CLIENT_JSON. The layer needs to know who you are, "
                      "so that only your clicks count.")
        elif args.step == "status":
            if not chat_app.connected():
                print("The Chat app isn't connected. Run: pwi chat-app connect KEY_JSON")
                return 0
            key = chat_app.load()
            print(f"Connected as {key['client_email']}, reading {key['subscription']}.")
            store.create_or_check(paths.STORE_PATH)
            with closing(store.connect(paths.STORE_PATH)) as db:
                space = store.setting(db, "chat_app.space")
                print(f"Review goes to your direct message {space}." if space else
                      "No direct message yet: in Google Chat, open a direct message with the app.")
                for name, text in (("chat_app.last_event_at", "Last event"), ("chat_app.last_error", "Last error")):
                    value = store.setting(db, name)
                    if value:
                        print(f"{text}: {value}")
        else:
            print("The app's key is forgotten. Delete the key in Google Cloud too (IAM & Admin, Service accounts)."
                  if chat_app.disconnect() else "The Chat app wasn't connected.")
    except (google.GoogleError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def eod_command(db, args):
    try:
        if args.step == "setup":
            done = eod.setup(db, args.vault, args.folder, args.at, args.days, args.claude,
                             systemd=os.environ.get("PWI_NO_SYSTEMD") != "1")
            print(f"The end-of-day agent runs at {done['at']} ({done['days']}) and writes to {done['notes']}.")
            if not done["is_vault"]:
                print(f"  {done['vault']} has no .obsidian folder: is it your vault? Open it in Obsidian once.")
            print("  Next: pwi eod check, to see which tools it gets.")
            if not chat_app.connected():
                print("  The review goes to Google Chat once the app is connected: pwi chat-app connect KEY_JSON")
        elif args.step == "check":
            done = eod.check(db, args.allow or (), args.block or ())
            print("Connected: " + ", ".join(f"{m['name']} ({m['status']})" for m in done["servers"]))
            if not done["pwi_connected"]:
                print("  The layer isn't connected: is the service running? systemctl --user status pwi")
            print(f"Allowed ({len(done['allowed'])}): " + ", ".join(done["allowed"]))
            print(f"Denied ({len(done['blocked'])}): " + ", ".join(done["blocked"]))
            print("Edits: only inside the notes folder. Change a tool with --allow NAME or --block NAME.")
        elif args.step == "run" and (args.start or args.end):
            if args.day or not (args.start and args.end):
                print("error: give --from and --to together, without --day", file=sys.stderr)
                return 1
            days = eod.days_between(eod.settings(db), args.start, args.end)
            print(f"{len(days)} workday{'s' if len(days) != 1 else ''} to run, oldest first. Each takes a few minutes.")
            done = eod.run_range(db, args.start, args.end, args.force,
                                 each=lambda r: print(f"{r['day']}: {r['status']}. {r['detail']}", flush=True))
            posted = done.get("review") or {}
            if posted.get("posted"):
                print(f"{posted['posted']} claims posted to Google Chat.")
            elif posted.get("gaps"):
                print(f"Review not posted: {posted['gaps'][0]}")
            return 1 if any(r["status"] == "failed" for r in done["days"]) else 0
        elif args.step == "run":
            done = eod.run(db, args.day, args.force)
            print(f"{done['day']}: {done['status']}. {done['detail']}")
            posted = done.get("review") or {}
            if posted.get("posted"):
                print(f"  {posted['posted']} claims posted to Google Chat.")
            return 1 if done["status"] == "failed" else 0
        elif args.step == "finish":
            results = eod.finish(db, args.day)
            for r in results:
                print(f"{r['day']}: {r['status']}" + (f". {r['detail']}" if r.get("detail") else ""))
            if not results:
                print("No answers since the notes were last written.")
            return 1 if any(r["status"] == "failed" for r in results) else 0
        elif args.step == "off":
            eod.remove_units(systemd=os.environ.get("PWI_NO_SYSTEMD") != "1")
            print("The end-of-day timers are stopped and removed. Your notes and settings stay; "
                  "pwi eod setup turns it back on.")
        else:
            s = eod.status(db)
            cfg = s["settings"]
            if not cfg["vault"]:
                print("The end-of-day agent is off. Turn it on with: pwi eod setup --vault PATH")
                return 0
            print(f"Runs at {cfg['at']} ({cfg['days']}), timers {'on' if s['timers'] else 'off'}; "
                  f"notes in {cfg['vault']}/{cfg['folder']}.")
            tools = s["tools"]
            if tools:
                print(f"Tools (checked {tools['checked_at']}): {len(tools['allowed'])} allowed, "
                      f"{len(tools['blocked'])} denied.")
            print("Chat review: " + ("waiting for a direct message with the app" if s["chat_app"] and not s["review_space"]
                                     else f"{s['waiting']} claims waiting" if s["chat_app"] else "the app isn't connected"))
            if s["chat_app_error"]:
                print(f"  Last Chat app error: {s['chat_app_error']}")
            for r in s["runs"]:
                print(f"  {r['day']} {r['kind']:<6} {r['status']:<7} {r['started_at']}  {r['detail'] or ''}")
    except eod.EodError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def wiki_command(db, args):
    try:
        if args.step == "compile":
            def show(r):
                print(f"{r['page']}: {r['status']}, {r['detail']}", flush=True)
                if r["reply"] and wiki_compile.interactive():
                    print("  " + r["reply"].replace("\n", "\n  "), flush=True)
            if args.page and args.all:
                print("error: give --page or --all, not both", file=sys.stderr)
                return 1
            due = wiki_compile.pages_to_compile(db, args.page, args.all, args.max)
            if not due:
                print("No wiki page needs compiling: none is stale, and every active project's page is written.")
                return 0
            print(f"{len(due)} page{'s' if len(due) != 1 else ''} to compile, a few minutes each: "
                  + ", ".join(p["id"] for p, _ in due) + ".", flush=True)
            results = wiki_compile.compile_pages(db, args.page, args.all, args.max, each=show)
            return 1 if any(r["status"] == "failed" for r in results) else 0
        s = wiki_compile.status(db)
        written = [p for p in s["pages"] if p["compiled"]]
        print(f"{len(s['pages'])} pages, {len(written)} written, {sum(p['stale'] for p in written)} stale."
              + ("" if s["unit"] else " The compile run doesn't start by itself yet: pwi eod setup turns it on."))
        for page_id, why in s["due"]:
            print(f"  due: {page_id}: {why}")
        for r in s["runs"]:
            versions = f"v{r['version_before']} to v{r['version_after']}" if r["version_after"] is not None else ""
            print(f"  {r['started_at']} {r['page_id']:<20} {r['status']:<7} {versions:<12} {r['detail'] or ''}")
    except eod.EodError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(prog="pwi", description="Personal Work Intelligence layer")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add-repo", help="allowlist Git repositories, or every repository in a folder")
    add.add_argument("paths", nargs="+", metavar="PATH",
                     help="a repository, or a folder such as ~/Projects; run it again to add new repositories")
    commands.add_parser("add-firefox", help="read Firefox history, with secret-looking URL parts removed").add_argument(
        "profile", nargs="?", help="the profile folder; default: the profile Firefox opens")
    commands.add_parser("sources", help="list sources and their last collection")
    for name, text in (("disable", "stop collecting a source and hide it from Claude"), ("enable", "turn a source back on")):
        commands.add_parser(name, help=text).add_argument("source_id", type=int, metavar="ID")
    commands.add_parser("collect", help="collect every enabled source now")
    cloud = commands.add_parser("import-cloud-session", help="bring a Claude Code cloud session into the layer")
    cloud.add_argument("session", nargs="?", help="the session id (session_...) or its claude.ai/code link")
    cloud.add_argument("--repo", help="your checkout of the session's repository (default: this folder)")
    cloud.add_argument("--file", help="import this transcript (.jsonl) instead of teleporting")
    cloud.add_argument("--list", help="import every session in this list that's missing or out of date")
    cloud.add_argument("--check", action="store_true", help="with --list: only say what would be imported")
    commands.add_parser("cleanup", help="apply retention now; it also runs once a day by itself")
    commands.add_parser("open", help="open the frontend in the browser").add_argument(
        "section", nargs="?", default="", help="e.g. sources, claims, confidential or retention")
    evaluate = commands.add_parser("eval", help="the 5-day evaluation").add_subparsers(dest="step", required=True)
    evaluate.add_parser("label", help="write down what really happened on a workday").add_argument(
        "day", nargs="?", default=date.today().isoformat(), help="YYYY-MM-DD, default today")
    reporting = evaluate.add_parser("report", help="compare your labelled days with what the layer found")
    reporting.add_argument("--from", dest="start", metavar="DAY", help="first day, YYYY-MM-DD")
    reporting.add_argument("--to", dest="end", metavar="DAY", help="last day, YYYY-MM-DD")
    usage = commands.add_parser("app-usage", help="which apps and windows I use, and active vs idle time")
    usage_steps = usage.add_subparsers(dest="step", required=True)
    usage_steps.add_parser("on", help="start recording").add_argument(
        "--mode", choices=app_usage.MODES, help="titles (default): app names and window titles; apps: app names "
        "only; time: active and idle time only")
    usage_steps.add_parser("off", help="stop recording, and remove the extension")
    usage_steps.add_parser("status", help="what's being recorded")
    signin = commands.add_parser("google", help="the layer's own read-only Google sign-in").add_subparsers(
        dest="step", required=True)
    signin.add_parser("connect", help="sign in, read-only").add_argument(
        "client_json", help="the OAuth client file (Desktop app) from your Google Cloud project")
    signin.add_parser("status", help="who the layer is signed in as")
    signin.add_parser("disconnect", help="revoke the sign-in and forget it")
    app = commands.add_parser("chat-app", help="the layer's Google Chat app, for the end-of-day review").add_subparsers(
        dest="step", required=True)
    connect = app.add_parser("connect", help="connect it with its service account key")
    connect.add_argument("key_json", help="the service account's JSON key, from your Google Cloud project")
    connect.add_argument("--subscription", default=chat_app.DEFAULT_SUBSCRIPTION,
                         help=f"the Pub/Sub subscription for its events (default: {chat_app.DEFAULT_SUBSCRIPTION})")
    app.add_parser("status", help="whether it's connected, and where the review goes")
    app.add_parser("disconnect", help="forget its key")
    agent = commands.add_parser("eod", help="the end-of-day agent").add_subparsers(dest="step", required=True)
    setup = agent.add_parser("setup", help="turn it on: where the notes go, and when it runs")
    setup.add_argument("--vault", required=True, help="your Obsidian vault's folder")
    setup.add_argument("--folder", default="Work", help="the folder inside the vault for its notes (default: Work)")
    setup.add_argument("--at", default="19:30", help="when it runs, HH:MM (default: 19:30)")
    setup.add_argument("--days", default="Mon..Fri", help="which days, e.g. Mon..Fri (the default) or Mon,Wed,Fri")
    setup.add_argument("--claude", help="the claude command, if it isn't on PATH")
    checking = agent.add_parser("check", help="which tools it gets")
    checking.add_argument("--allow", action="append", metavar="TOOL", help="allow this tool too")
    checking.add_argument("--block", action="append", metavar="TOOL", help="deny this tool")
    running = agent.add_parser("run", help="run it now")
    running.add_argument("--day", help="the workday, YYYY-MM-DD (default: today, or the last workday before noon)")
    running.add_argument("--from", dest="start", metavar="DAY",
                         help="with --to: run every workday in a range, oldest first, YYYY-MM-DD")
    running.add_argument("--to", dest="end", metavar="DAY", help="the last day of the range, YYYY-MM-DD")
    running.add_argument("--force", action="store_true", help="run again for a day that already ran")
    agent.add_parser("finish", help="rewrite the day's notes with my answers").add_argument("--day", help="YYYY-MM-DD")
    agent.add_parser("status", help="settings, last runs and the review")
    agent.add_parser("off", help="stop the timers")
    pages = commands.add_parser("wiki", help="the knowledge wiki").add_subparsers(dest="step", required=True)
    compiling = pages.add_parser("compile", help="update the wiki pages that need it")
    compiling.add_argument("--page", action="append", metavar="ID", help="this page (repeat for more)")
    compiling.add_argument("--all", action="store_true", help="every project's page")
    compiling.add_argument("--max", type=int, default=wiki_compile.MAX_PAGES,
                           help=f"at most this many pages (default {wiki_compile.MAX_PAGES})")
    pages.add_parser("status", help="pages, which are due, and the last compile runs")
    args = parser.parse_args()
    if args.command == "google":
        return google_command(args)
    if args.command == "chat-app":
        return chat_app_command(args)
    if args.command == "open":
        return open_frontend(args.section)

    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")  # errors are printed per source
    os.umask(0o077)
    store.create_or_check(paths.STORE_PATH)
    try:
        with closing(store.connect(paths.STORE_PATH)) as db:
            if args.command == "add-repo":
                added = [a for p in args.paths for a in sources.add_path(db, p)]
                for a in added:
                    print(f"{a['path']}: {a['status']}" + (f" as project '{a['project']}'" if a["project"] else ""))
                new = sum(a["status"] in ("allowlisted", "allowlisted again") for a in added)
                print(f"{len(added)} repositor{'y' if len(added) == 1 else 'ies'}, {new} newly allowlisted. Collecting...")
                print_runs(collect.run(paths.STORE_PATH, "manual"))
            elif args.command == "add-firefox":
                a = sources.add_firefox(db, args.profile)
                print(f"Firefox history {a['status']}: profile {a['name']} ({a['profile']}).")
                if a["other_profiles_on"]:
                    print(f"Other Firefox profiles are also on (sources {', '.join(map(str, a['other_profiles_on']))});"
                          " turn off any you don't use with: pwi disable ID")
                print("Collecting...")
                print_runs(collect.run(paths.STORE_PATH, "manual"))
            elif args.command == "app-usage":
                return app_usage_command(db, args)
            elif args.command == "eod":
                return eod_command(db, args)
            elif args.command == "wiki":
                return wiki_command(db, args)
            elif args.command == "sources":
                for s in sources.list_sources(db):
                    state = "on " if s["enabled"] else "off"
                    last = (f"last run {s['last_run_at']} {s['last_status']}" if s["last_run_at"] else "never collected")
                    print(f"{s['id']:>3}  {state}  {s['kind']:<11}  {s['name']:<24} {s['events']:>6} events  {last}")
                    print(f"          {s['locator']}")
                    if s["last_status"] == "error":
                        print(f"          error: {s['last_error']}")
            elif args.command in ("enable", "disable"):
                sources.set_enabled(db, args.source_id, args.command == "enable")
                print(f"Source {args.source_id} {args.command}d.")
            elif args.command == "import-cloud-session" and args.list:
                results = cloud_sessions.import_list(db, args.list, args.repo, dry_run=args.check)
                count = sum(r["outcome"].startswith("imported") for r in results)
                if args.check:
                    print(f"{sum(r['outcome'].startswith('would') for r in results)} of {len(results)} to import.")
                else:
                    print(f"{count} of {len(results)} imported." + (" Collecting..." if count else ""))
                    if count:
                        print_runs(collect.run(paths.STORE_PATH, "manual"))
                return 1 if any(r["outcome"].startswith("failed") for r in results) else 0
            elif args.command == "import-cloud-session":
                done = cloud_sessions.import_session(db, args.session, args.file, args.repo)
                print(f"{'Updated' if done['replaced'] else 'Imported'} session {done['session_file']} into project "
                      f"'{done['project']}': {done['title'] or 'untitled'}, {done['prompts']} prompt(s). Collecting...")
                print_runs(collect.run(paths.STORE_PATH, "manual"))
            elif args.command == "collect":
                print_runs(collect.run(paths.STORE_PATH, "manual"))
            elif args.command == "eval" and args.step == "label":
                return label_day(db, args.day)
            elif args.command == "eval":
                return report_days(args.start, args.end)
            elif args.command == "cleanup":
                deleted = {k: v for k, v in retention.run(paths.STORE_PATH).items() if v}
                print("Deleted: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in deleted.items())
                      if deleted else "Nothing was old enough to delete.")
    except CollectorError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
