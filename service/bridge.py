"""What Claude Desktop starts: copies MCP messages between stdio and the
service's Unix socket. Standard library only.

Claude Desktop never relaunches a bridge that exits, so the bridge survives
service restarts: it reconnects in the background, and a request sent while
the service is away waits briefly for it, then gets a JSON-RPC error instead
of hanging. The service doesn't need a fresh `initialize` per connection, so a
reconnect is invisible to Claude Desktop (Phase 0 spike, 2 Nov 2026).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import json  # noqa: E402
import os  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from paths import SOCKET_PATH  # noqa: E402

WAIT_SECONDS = float(os.environ.get("PWI_BRIDGE_WAIT", "5"))  # how long a request waits for the service
SERVICE_DOWN = -32000

state = threading.Condition()
sock = None  # connected socket, or None while the service is away
pending = set()  # ids of requests the service hasn't answered yet
out_lock = threading.Lock()


def log(message):
    print(f"pwi bridge: {message}", file=sys.stderr, flush=True)


def write_stdout(data):
    with out_lock:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


def fail(request_id, reason):
    error = {"code": SERVICE_DOWN, "message": f"The pwi service {reason}; try again in a few seconds. "
                                              "If it keeps failing: systemctl --user status pwi"}
    write_stdout(json.dumps({"jsonrpc": "2.0", "id": request_id, "error": error}).encode() + b"\n")


def connect_forever():
    """Keeps a connection to the service and copies its replies to stdout."""
    global sock
    delay = 0.2
    while True:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            conn.connect(str(SOCKET_PATH))
        except OSError:
            conn.close()
            time.sleep(delay)
            delay = min(delay * 2, 2)
            continue
        delay = 0.2
        log("connected")
        with state:
            sock = conn
            state.notify_all()
        try:
            for line in conn.makefile("rb"):
                try:
                    reply_id = json.loads(line).get("id")
                except (json.JSONDecodeError, AttributeError):
                    reply_id = None
                write_stdout(line)
                with state:
                    pending.discard(reply_id)
                    state.notify_all()
        except OSError:
            pass
        log("service went away; reconnecting")
        with state:
            sock = None
            lost = list(pending)
            pending.clear()
        conn.close()
        for request_id in lost:
            fail(request_id, "restarted before answering")


def main():
    threading.Thread(target=connect_forever, daemon=True).start()
    for line in sys.stdin.buffer:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
            request_id = msg["id"] if "method" in msg and "id" in msg else None
        except (json.JSONDecodeError, TypeError):
            request_id = None
        with state:
            state.wait_for(lambda: sock is not None, timeout=WAIT_SECONDS)
            conn = sock
            if conn is not None and request_id is not None:
                pending.add(request_id)
        try:
            if conn is None:
                raise OSError
            conn.sendall(line)
        except OSError:
            with state:
                # The reader may already have failed it when the connection dropped.
                still_pending = request_id in pending
                pending.discard(request_id)
            if request_id is not None and (conn is None or still_pending):
                fail(request_id, "is not reachable")
            # A notification sent while the service is away is dropped.
    # stdin closed: let replies to requests already sent reach stdout before exiting.
    with state:
        state.wait_for(lambda: not pending, timeout=WAIT_SECONDS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
