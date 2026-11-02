"""End-to-end check: starts a private copy of the service, then talks MCP to it
through bridge.py the way Claude Desktop does, including a service restart in
the middle of a session. Uses a temporary runtime dir and database, so it
doesn't touch a running spike.

Run: python3 -I test_pipe.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "XDG_RUNTIME_DIR": tmp, "PWI_SPIKE_DB": str(Path(tmp) / "test.db"),
               "PWI_BRIDGE_WAIT": "3"}
        sock = Path(tmp) / "pwi-spike" / "mcp.sock"

        def start_service():
            sock.unlink(missing_ok=True)
            proc = subprocess.Popen([sys.executable, "-I", str(HERE / "service.py")], env=env,
                                    stderr=subprocess.DEVNULL)
            for _ in range(50):
                if sock.exists():
                    break
                time.sleep(0.1)
            return proc

        def stop_service(proc):
            proc.terminate()
            proc.wait(timeout=5)

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

        down = rpc("ping")
        check("request while the service is down gets a 'not reachable' error",
              down.get("error", {}).get("code") == -32000 and "not reachable" in down["error"]["message"])

        service = start_service()
        try:
            check("socket is owner-only (0600) in an owner-only dir (0700)",
                  sock.stat().st_mode & 0o777 == 0o600 and sock.parent.stat().st_mode & 0o777 == 0o700)
            check("bridge connects once the service is up", rpc("ping").get("result") == {})

            init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "test_pipe", "version": "0"}})["result"]
            check("initialize echoes a supported protocol version",
                  init["protocolVersion"] == "2025-06-18")
            check("initialize declares tools and prompts",
                  {"tools", "prompts"} <= init["capabilities"].keys())
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})

            unknown = rpc("initialize", {"protocolVersion": "1999-01-01", "capabilities": {},
                                         "clientInfo": {"name": "test_pipe", "version": "0"}})["result"]
            check("unknown protocol version gets the newest supported one",
                  unknown["protocolVersion"] == "2025-11-25")

            tools = {t["name"]: t for t in rpc("tools/list")["result"]["tools"]}
            check("tools/list returns get_status (read-only) and propose_claim",
                  tools.keys() == {"get_status", "propose_claim"}
                  and tools["get_status"]["annotations"]["readOnlyHint"] is True)

            saved = rpc("tools/call", {"name": "propose_claim",
                                       "arguments": {"type": "decision", "text": "Use SQLite for the store."}})
            check("propose_claim saves a claim", "Saved claim 1" in saved["result"]["content"][0]["text"])

            bad = rpc("tools/call", {"name": "propose_claim", "arguments": {"type": "rumour", "text": "x"}})
            check("propose_claim rejects an unknown type as a tool error", bad["result"]["isError"] is True)

            status = rpc("tools/call", {"name": "get_status", "arguments": {}})["result"]["content"][0]["text"]
            check("get_status returns the claim, wrapped as data",
                  status.startswith("<data ") and "Use SQLite for the store." in status)

            missing_tool = rpc("tools/call", {"name": "delete_claim", "arguments": {}})
            check("unknown tool is a JSON-RPC error", missing_tool["error"]["code"] == -32602)

            prompts = rpc("prompts/list")["result"]["prompts"]
            check("prompts/list returns daily_briefing", [p["name"] for p in prompts] == ["daily_briefing"])

            prompt = rpc("prompts/get", {"name": "daily_briefing", "arguments": {"day": "2026-11-02"}})["result"]
            check("prompts/get fills in the day",
                  "2026-11-02" in prompt["messages"][0]["content"]["text"])

            check("unsupported method is 'method not found'", rpc("resources/list")["error"]["code"] == -32601)

            old_pid = json.loads(status.split("\n", 1)[1].rsplit("\n", 1)[0])["service_pid"]
            stop_service(service)
            service = start_service()
            after = rpc("tools/call", {"name": "get_status", "arguments": {}})
            text = after.get("result", {}).get("content", [{}])[0].get("text", "")
            check("after a service restart, the same session works without a new initialize",
                  "Use SQLite for the store." in text and f'"service_pid": {old_pid}' not in text)

            bridge.stdin.close()
            check("bridge exits cleanly when Claude Desktop closes stdin", bridge.wait(timeout=5) == 0)
        finally:
            stop_service(service)
            if bridge.poll() is None:
                bridge.kill()


if __name__ == "__main__":
    main()
