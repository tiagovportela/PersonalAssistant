"""The `pwi` command: allowlist repositories and collect on demand, until the
frontend exists. install.py puts a `pwi` launcher in ~/.local/bin.

    pwi add-repo PATH...   allowlist Git repositories (each becomes a project); a folder
                           allowlists every repository in it, and running it again adds new ones
    pwi sources            list sources, what they hold and their last collection
    pwi disable ID         stop collecting a source and hide it from Claude; its data stays
    pwi enable ID          turn it back on
    pwi collect            collect every enabled source now
    pwi cleanup            apply retention now (it also runs once a day by itself)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
from contextlib import closing  # noqa: E402

import collect  # noqa: E402
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


def main():
    parser = argparse.ArgumentParser(prog="pwi", description="Personal Work Intelligence layer")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add-repo", help="allowlist Git repositories, or every repository in a folder")
    add.add_argument("paths", nargs="+", metavar="PATH",
                     help="a repository, or a folder such as ~/Projects; run it again to add new repositories")
    commands.add_parser("sources", help="list sources and their last collection")
    for name, text in (("disable", "stop collecting a source and hide it from Claude"), ("enable", "turn a source back on")):
        commands.add_parser(name, help=text).add_argument("source_id", type=int, metavar="ID")
    commands.add_parser("collect", help="collect every enabled source now")
    commands.add_parser("cleanup", help="apply retention now; it also runs once a day by itself")
    args = parser.parse_args()

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
