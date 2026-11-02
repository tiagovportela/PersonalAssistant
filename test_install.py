"""Checks install.py against a throwaway home: files, systemd unit, Claude
Desktop config, upgrade, uninstall, and that the installed copy runs on its
own. Uses --no-systemd, so it never touches the real user's services.

Run: python3 -I test_install.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "contracts"))
from tools import TOOLS  # noqa: E402

OTHER_SERVER = {"command": "/usr/bin/other", "args": []}


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        env = {**os.environ, "HOME": tmp, "XDG_CONFIG_HOME": f"{tmp}/config", "XDG_DATA_HOME": f"{tmp}/data",
               "XDG_RUNTIME_DIR": f"{tmp}/run"}
        (home / "run").mkdir(mode=0o700)
        app = home / "data" / "pwi" / "app"
        unit = home / "config" / "systemd" / "user" / "pwi.service"
        claude = home / "config" / "Claude" / "claude_desktop_config.json"
        claude.parent.mkdir(parents=True)
        original = {"preferences": {"theme": "dark"},
                    "mcpServers": {"pwi-spike": {"command": "/usr/bin/python3", "args": ["bridge.py"]},
                                   "other": OTHER_SERVER}}
        claude.write_text(json.dumps(original))

        def run(*args):
            return subprocess.run([sys.executable, "-I", str(HERE / "install.py"), "--no-systemd", *args],
                                  env=env, capture_output=True, text=True)

        claude.write_text("{not json")
        bad = run()
        check("an invalid Claude Desktop config stops the install before anything is installed, and is left untouched",
              bad.returncode == 1 and "isn't valid JSON" in bad.stderr and claude.read_text() == "{not json"
              and not app.exists() and not unit.exists())
        claude.write_text(json.dumps(original))

        first = run()
        check("install succeeds", first.returncode == 0)
        installed = {str(p.relative_to(app)) for p in app.rglob("*") if p.is_file()}
        check("the code, contracts, instructions and schema are copied",
              {"service/server.py", "service/bridge.py", "service/handlers.py", "contracts/tools.py",
               "contracts/instructions/common.md", "schema/schema.sql", "version.json"} <= installed)
        check("tests and caches are not copied", not any("test_" in f or "__pycache__" in f for f in installed))
        check("the data folder is owner-only", (home / "data" / "pwi").stat().st_mode & 0o777 == 0o700)
        check("version.json records the commit and Python",
              {"commit", "python", "installed_at"} <= json.loads((app / "version.json").read_text()).keys())

        unit_text = unit.read_text()
        check("the systemd unit runs the installed server with this Python, isolated",
              f'ExecStart="{sys.executable}" -I "{app}/service/server.py"' in unit_text
              and "Restart=on-failure" in unit_text and "WantedBy=default.target" in unit_text)

        config = json.loads(claude.read_text())
        check("Claude Desktop gets the bridge, other settings and servers are kept, and the spike entry goes",
              config["mcpServers"] == {"other": OTHER_SERVER,
                                       "pwi": {"command": sys.executable, "args": ["-I", f"{app}/service/bridge.py"]}}
              and config["preferences"] == original["preferences"])
        backup = claude.with_name(claude.name + ".bak-before-pwi")
        check("the original Claude Desktop config is backed up",
              json.loads(backup.read_text()) == original)
        check("first install asks to set approvals", "Ask every time" in first.stdout)

        service = subprocess.Popen([sys.executable, "-I", str(app / "service" / "server.py")], env=env,
                                   stderr=subprocess.DEVNULL)
        try:
            sock = home / "run" / "pwi" / "mcp.sock"
            for _ in range(50):
                if sock.exists():
                    break
                time.sleep(0.1)
            bridge = subprocess.run([sys.executable, "-I", str(app / "service" / "bridge.py")], env=env,
                                    input=b'{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}\n',
                                    capture_output=True, timeout=10)
            tools = json.loads(bridge.stdout)["result"]["tools"]
            check("the installed copy runs on its own and serves every tool", tools == TOOLS)
        finally:
            service.terminate()
            service.wait(timeout=5)
        check("the store is created in the data folder, outside the app folder",
              (home / "data" / "pwi" / "store.db").exists())

        before = claude.read_text()
        second = run()
        check("running install again succeeds and leaves the Claude Desktop config as it was",
              second.returncode == 0 and claude.read_text() == before and "already registered" in second.stdout
              and "Ask every time" not in second.stdout)
        check("the backup still holds the original config", json.loads(backup.read_text()) == original)

        removed = run("--uninstall")
        config = json.loads(claude.read_text())
        check("uninstall removes the unit, the code and the Claude Desktop entry",
              removed.returncode == 0 and not unit.exists() and not app.exists()
              and config["mcpServers"] == {"other": OTHER_SERVER})
        check("uninstall keeps the store", (home / "data" / "pwi" / "store.db").exists())


if __name__ == "__main__":
    main()
