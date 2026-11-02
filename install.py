"""Installs the layer for the current user, upgrades it, or removes it.

    python3 install.py              install or upgrade, start the service, register it in Claude Desktop
    python3 install.py --uninstall  stop and remove it; the store (your data) is kept

Run it from a clone of the repository with the system python3. It copies the
code to ~/.local/share/pwi/app, so the clone can be pulled or moved without
breaking the running service. Running it again is safe. Standard library only.
"""

import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path[:0] = [str(REPO / "service"), str(REPO / "contracts")]
import paths  # noqa: E402
from tools import APPROVAL, TOOLS  # noqa: E402

MIN_PYTHON = (3, 12)
UNIT = "pwi.service"
UNIT_PATH = paths.CONFIG_HOME / "systemd" / "user" / UNIT
CLAUDE_CONFIG = paths.CONFIG_HOME / "Claude" / "claude_desktop_config.json"
SERVER_NAME = "pwi"
SPIKE = "pwi-spike"  # the Phase 0 spike's entry, replaced by this one
BRIDGE = paths.APP_DIR / "service" / "bridge.py"
SERVER = paths.APP_DIR / "service" / "server.py"


def say(message):
    print(f"- {message}")


def fail(message):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def systemctl(*args, check=True):
    result = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        fail(f"systemctl --user {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def check_requirements(use_systemd):
    if not sys.platform.startswith("linux"):
        fail("the layer runs on Linux only.")
    if sys.version_info < MIN_PYTHON:
        fail(f"Python {'.'.join(map(str, MIN_PYTHON))} or newer is needed; this is {sys.version.split()[0]}.")
    if sys.prefix != sys.base_prefix:
        fail("run this with the system python3, not from a virtual environment.")
    try:
        db = sqlite3.connect(":memory:")
        db.executescript((REPO / "schema" / "schema.sql").read_text(encoding="utf-8"))
        db.close()
    except sqlite3.Error as e:
        fail(f"this Python's SQLite ({sqlite3.sqlite_version}) can't create the store: {e}")
    if use_systemd and (not shutil.which("systemctl") or systemctl("show-environment", check=False).returncode):
        fail("systemd user services aren't available in this session.")
    read_claude_config()  # fails now, before anything is installed, if the file is broken


def current_commit():
    try:
        commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return commit + ("+changes" if dirty else "")


def copy_app(commit):
    """Copies the code next to the store; a new copy replaces the old one in one rename."""
    paths.DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    paths.DATA_DIR.chmod(0o700)
    new, old = paths.APP_DIR.with_name("app.new"), paths.APP_DIR.with_name("app.old")
    for leftover in (new, old):
        shutil.rmtree(leftover, ignore_errors=True)
    skip = shutil.ignore_patterns("test_*.py", "__pycache__", "*.pyc")
    shutil.copytree(REPO / "service", new / "service", ignore=skip)
    shutil.copytree(REPO / "contracts", new / "contracts", ignore=skip)
    (new / "schema").mkdir()
    shutil.copy2(REPO / "schema" / "schema.sql", new / "schema")
    (new / "version.json").write_text(json.dumps({
        "commit": commit,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": sys.version.split()[0],
    }, indent=2) + "\n", encoding="utf-8")
    if paths.APP_DIR.exists():
        paths.APP_DIR.rename(old)
    new.rename(paths.APP_DIR)
    shutil.rmtree(old, ignore_errors=True)
    say(f"code copied to {paths.APP_DIR}")


def write_unit(python):
    quote = lambda p: '"' + str(p).replace("%", "%%") + '"'  # noqa: E731
    UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    UNIT_PATH.write_text(
        "[Unit]\n"
        "Description=Personal Work Intelligence layer\n"
        "\n"
        "[Service]\n"
        f"ExecStart={quote(python)} -I {quote(SERVER)}\n"
        "Restart=on-failure\n"
        "RestartSec=2\n"
        "UMask=0077\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n",
        encoding="utf-8")
    say(f"systemd unit written to {UNIT_PATH}")


def start_service():
    if systemctl("is-active", SPIKE, check=False).stdout.strip() == "active":
        systemctl("stop", SPIKE)
        say(f"stopped the Phase 0 spike service ({SPIKE})")
    systemctl("daemon-reload")
    systemctl("enable", UNIT)
    systemctl("restart", UNIT)  # starts it, or loads the new code on an upgrade
    expected = len(TOOLS)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_UNIX) as conn:
                conn.settimeout(5)
                conn.connect(str(paths.SOCKET_PATH))
                conn.sendall(b'{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}\n')
                tools = json.loads(conn.makefile("rb").readline())["result"]["tools"]
            if len(tools) == expected:
                say(f"service is running and serves {expected} tools")
                return
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.3)
    fail("the service didn't answer. See: journalctl --user -u pwi -n 50")


def read_claude_config():
    if not CLAUDE_CONFIG.exists():
        return {}
    text = CLAUDE_CONFIG.read_text(encoding="utf-8")
    try:
        config = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        fail(f"{CLAUDE_CONFIG} isn't valid JSON. Fix it or move it aside, then run this again.")
    if not isinstance(config, dict) or not isinstance(config.get("mcpServers", {}), dict):
        fail(f"{CLAUDE_CONFIG} doesn't look like a Claude Desktop config. Fix it or move it aside, then run this again.")
    return config


def write_claude_config(config):
    """Writes the whole file at once, keeping its permissions; every other setting is left as it was."""
    CLAUDE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    new = CLAUDE_CONFIG.with_name(CLAUDE_CONFIG.name + ".pwi-new")
    new.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if CLAUDE_CONFIG.exists():
        shutil.copymode(CLAUDE_CONFIG, new)
    new.replace(CLAUDE_CONFIG)


def register_in_claude(python):
    """Adds the bridge to Claude Desktop's mcpServers. Returns True if the entry is new or changed."""
    config = read_claude_config()
    backup = CLAUDE_CONFIG.with_name(CLAUDE_CONFIG.name + ".bak-before-pwi")
    if CLAUDE_CONFIG.exists() and not backup.exists():
        shutil.copy2(CLAUDE_CONFIG, backup)
    servers = config.setdefault("mcpServers", {})
    removed_spike = servers.pop(SPIKE, None) is not None
    entry = {"command": str(python), "args": ["-I", str(BRIDGE)]}
    added = servers.get(SERVER_NAME) != entry
    servers[SERVER_NAME] = entry
    if added or removed_spike:
        write_claude_config(config)
        say(f"registered '{SERVER_NAME}' in {CLAUDE_CONFIG}" + (f", replacing '{SPIKE}'" if removed_spike else ""))
    else:
        say(f"'{SERVER_NAME}' is already registered in Claude Desktop")
    return added


def install(use_systemd):
    check_requirements(use_systemd)
    # Not resolved: /usr/bin/python3 survives an Ubuntu upgrade, /usr/bin/python3.12 may not.
    python = Path(sys.executable)
    commit = current_commit()
    copy_app(commit)
    write_unit(python)
    if use_systemd:
        start_service()
    added = register_in_claude(python)

    print(f"\nInstalled pwi{f' {commit}' if commit else ''} with Python {sys.version.split()[0]}.")
    print("Next:")
    print("  1. Quit Claude Desktop completely (Ctrl+Q, or Quit from the tray icon) and open it again,")
    print("     so it loads the tool list. Closing the window isn't enough.")
    if added:
        print("  2. In Claude Desktop's tool permissions for 'pwi', set these to \"Ask every time\":")
        print(f"     {', '.join(sorted(APPROVAL))}. Set every other tool to \"Always allow\".")
    print("Logs: journalctl --user -u pwi -f")


def uninstall(use_systemd):
    if use_systemd and UNIT_PATH.exists():
        systemctl("disable", "--now", UNIT, check=False)
    UNIT_PATH.unlink(missing_ok=True)
    if use_systemd:
        systemctl("daemon-reload", check=False)
    say("service stopped and removed")
    config = read_claude_config()
    if config.get("mcpServers", {}).pop(SERVER_NAME, None) is not None:
        write_claude_config(config)
        say(f"removed '{SERVER_NAME}' from {CLAUDE_CONFIG}")
    shutil.rmtree(paths.APP_DIR, ignore_errors=True)
    say(f"code removed from {paths.APP_DIR}")
    print(f"\nYour data is kept in {paths.DATA_DIR}. Delete that folder yourself if you no longer want it.")
    print("Quit and reopen Claude Desktop so it forgets the tools.")


def main():
    parser = argparse.ArgumentParser(description="Install, upgrade or remove the Personal Work Intelligence layer.")
    parser.add_argument("--uninstall", action="store_true", help="stop and remove the layer; your data is kept")
    parser.add_argument("--no-systemd", action="store_true",
                        help="write files and config only; don't start, stop or enable the service")
    args = parser.parse_args()
    (uninstall if args.uninstall else install)(not args.no_systemd)


if __name__ == "__main__":
    main()
