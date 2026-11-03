"""The `pwi` command: allowlist repositories and collect on demand, until the
frontend exists. install.py puts a `pwi` launcher in ~/.local/bin.

    pwi add-repo PATH...   allowlist Git repositories (each becomes a project); a folder
                           allowlists every repository in it, and running it again adds new ones
    pwi add-firefox [PROFILE]  read Firefox history (the default profile, or the folder given)
    pwi sources            list sources, what they hold and their last collection
    pwi disable ID         stop collecting a source and hide it from Claude; its data stays
    pwi enable ID          turn it back on
    pwi collect            collect every enabled source now
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
import collect  # noqa: E402
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
    args = parser.parse_args()
    if args.command == "google":
        return google_command(args)
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
