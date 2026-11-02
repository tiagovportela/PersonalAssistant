"""End-to-end check: starts a private copy of the service, then talks MCP to it
through bridge.py the way Claude Desktop does, including a second client and a
service restart mid-session. Uses temporary XDG dirs, so it never touches an
installed service or its store.

Run: python3 -I service/test_service.py
"""

import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "contracts"))
from experiences import instructions  # noqa: E402
from tools import TOOLS  # noqa: E402

NOW = "2026-11-02T17:00:00Z"
EVIDENCE = [{"event_id": "git:commit:abc123"}]


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def text_of(reply):
    return reply["result"]["content"][0]["text"]


def data_of(reply):
    text = text_of(reply)
    assert text.startswith("<data "), text
    return json.loads(text.split("\n", 1)[1].rsplit("\n", 1)[0])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "XDG_RUNTIME_DIR": f"{tmp}/run", "XDG_DATA_HOME": f"{tmp}/data",
               "PWI_BRIDGE_WAIT": "3"}
        Path(env["XDG_RUNTIME_DIR"]).mkdir(mode=0o700)
        sock = Path(tmp) / "run" / "pwi" / "mcp.sock"
        db_path = Path(tmp) / "data" / "pwi" / "store.db"

        def start_service():
            proc = subprocess.Popen([sys.executable, "-I", str(HERE / "server.py")], env=env,
                                    stderr=subprocess.DEVNULL)
            for _ in range(50):
                if sock.exists():
                    break
                time.sleep(0.1)
            return proc

        bridge = subprocess.Popen([sys.executable, "-I", str(HERE / "bridge.py")], env=env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        next_id = iter(range(1, 1000))

        def send(message):
            bridge.stdin.write(json.dumps(message).encode() + b"\n")
            bridge.stdin.flush()

        def rpc(method, params=None):
            request_id = next(next_id)
            send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
            reply = json.loads(bridge.stdout.readline())
            assert reply["id"] == request_id, reply
            return reply

        def call(name, arguments=None):
            return rpc("tools/call", {"name": name, "arguments": arguments or {}})

        down = rpc("ping")
        check("request while the service is down gets a 'not reachable' error",
              down.get("error", {}).get("code") == -32000 and "not reachable" in down["error"]["message"])

        service = start_service()
        try:
            check("socket is owner-only (0600) in an owner-only dir (0700)",
                  sock.stat().st_mode & 0o777 == 0o600 and sock.parent.stat().st_mode & 0o777 == 0o700)
            check("the store is created owner-only, with schema version 1",
                  db_path.stat().st_mode & 0o777 == 0o600 and db_path.parent.stat().st_mode & 0o777 == 0o700
                  and sqlite3.connect(db_path).execute("select version from schema_version").fetchone() == (1,))
            check("bridge connects once the service is up", rpc("ping").get("result") == {})

            init = rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                      "clientInfo": {"name": "test_service", "version": "0"}})["result"]
            check("initialize echoes the protocol, declares tools and prompts, and says to call get_instructions",
                  init["protocolVersion"] == "2025-11-25" and {"tools", "prompts"} <= init["capabilities"].keys()
                  and "get_instructions" in init["instructions"] and init["serverInfo"]["name"] == "pwi")
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})

            check("tools/list serves contracts/tools.py exactly", rpc("tools/list")["result"]["tools"] == TOOLS)

            got = call("get_instructions", {"experience": "daily_briefing"})
            check("get_instructions returns the template and shared rules, not wrapped as data",
                  text_of(got) == instructions("daily_briefing") and got["result"]["isError"] is False)

            missing = call("propose_claim", {"type": "decision", "text": "We use SQLite."})
            check("a claim without evidence is rejected with a retry hint",
                  missing["result"]["isError"] is True and text_of(missing).endswith("call propose_claim again."))
            unbuilt = call("propose_claim", {"type": "decision", "text": "We use SQLite.", "evidence": EVIDENCE})
            check("a write tool that isn't built yet errors and saves nothing",
                  unbuilt["result"]["isError"] is True and "nothing was saved" in text_of(unbuilt)
                  and sqlite3.connect(db_path).execute("select count(*) from claims").fetchone() == (0,))

            day = data_of(call("get_day", {"day": "2026-11-02"}))
            check("a read tool that isn't built yet says not found, with gaps and coverage",
                  day["found"] is False and day["gaps"] and "coverage" in day)

            empty = data_of(call("list_projects"))
            check("list_projects on an empty store says not found", empty["found"] is False and empty["projects"] == [])

            db = sqlite3.connect(db_path, isolation_level=None)
            db.execute("insert into sources (id, kind, locator, name, added_at) values"
                       " (1, 'git_repo', '/repos/pwi', 'PersonalAssistant', ?)", (NOW,))
            db.execute("insert into projects (id, name, created_at) values ('pwi', 'Personal Work Intelligence', ?),"
                       " ('secret', 'Secret project', ?)", (NOW, NOW))
            db.execute("insert into project_aliases values ('repo_path', '/repos/pwi', 'pwi', 'rule', ?)", (NOW,))
            db.execute("insert into events (id, source_id, type, project_id, occurred_at, utc_offset_min, observed_at,"
                       " title, content_hash) values ('git:commit:abc123', 1, 'git.commit', 'pwi',"
                       " '2026-11-02T10:00:00Z', 0, ?, 'Add service', 'h')", (NOW,))
            db.execute("insert into labels values ('project', 'secret', 'confidential', 'me', ?)", (NOW,))
            db.close()
            listed = data_of(call("list_projects"))
            check("list_projects returns projects with aliases and last activity, never confidential ones",
                  listed["found"] is True
                  and listed["projects"] == [{"id": "pwi", "name": "Personal Work Intelligence", "status": "active",
                                              "last_activity_day": "2026-11-02",
                                              "aliases": [{"kind": "repo_path", "value": "/repos/pwi"}]}]
                  and listed["coverage"]["sources_checked"] == ["git:PersonalAssistant"])

            prompts = rpc("prompts/list")["result"]["prompts"]
            prompt = rpc("prompts/get", {"name": "weekly_review"})["result"]
            check("the six experiences are also served as prompts, with the same text",
                  len(prompts) == 6 and prompt["messages"][0]["content"]["text"] == instructions("weekly_review"))
            check("unknown prompt and unknown tool are JSON-RPC errors",
                  rpc("prompts/get", {"name": "nope"})["error"]["code"] == -32602
                  and call("delete_claim")["error"]["code"] == -32602)
            check("unsupported method is 'method not found'", rpc("resources/list")["error"]["code"] == -32601)

            send([{"jsonrpc": "2.0", "id": 99, "method": "ping"}])
            check("a non-object message is an invalid request",
                  json.loads(bridge.stdout.readline())["error"]["code"] == -32600)

            other = socket.socket(socket.AF_UNIX)
            other.connect(str(sock))
            other.sendall(b'{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}\n')
            other_reply = json.loads(other.makefile("rb").readline())
            check("a second client is served while the first stays connected",
                  len(other_reply["result"]["tools"]) == len(TOOLS) and rpc("ping").get("result") == {})
            other.close()

            started = time.monotonic()
            service.send_signal(signal.SIGTERM)
            code = service.wait(timeout=5)
            check("SIGTERM stops the service promptly with clients connected, and removes the socket",
                  code == 0 and time.monotonic() - started < 4 and not sock.exists())

            service = start_service()
            after = data_of(call("list_projects"))
            check("after a restart, the same session works without a new initialize, and the store is kept",
                  [p["id"] for p in after["projects"]] == ["pwi"])

            bridge.stdin.close()
            check("bridge exits cleanly when Claude Desktop closes stdin", bridge.wait(timeout=5) == 0)
        finally:
            if service.poll() is None:
                service.terminate()
                service.wait(timeout=5)
            if bridge.poll() is None:
                bridge.kill()


if __name__ == "__main__":
    main()
