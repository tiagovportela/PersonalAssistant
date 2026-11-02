"""The layer's background service: MCP over an owner-only Unix socket.

systemd starts it at login (see install.py), so it runs whether or not Claude
Desktop is open. Claude Desktop reaches it through bridge.py, and opens several
connections at once (chat, and Code/Cowork), so every connection is served
independently. Standard library only.

Run: python3 -I service/server.py
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]

import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import platform  # noqa: E402
import signal  # noqa: E402
import time  # noqa: E402

import collect  # noqa: E402
import paths  # noqa: E402
import store  # noqa: E402
from handlers import VERSION, Layer, RpcError  # noqa: E402

log = logging.getLogger("pwi")
COLLECT_EVERY = int(os.environ.get("PWI_COLLECT_EVERY", "3600"))  # seconds


async def scheduler():
    """Collects at start (catching up after a shutdown) and then every COLLECT_EVERY seconds.

    It checks the wall clock every minute instead of sleeping for an hour, because
    asyncio's clock stops while the laptop is suspended."""
    trigger, last = "catch_up", None
    while True:
        if last is None or time.time() - last >= COLLECT_EVERY:
            last = time.time()
            try:
                results = await asyncio.to_thread(collect.run, paths.STORE_PATH, trigger)
                for r in results:
                    if r["status"] == "ok":
                        log.info("collected %s: %d new, %d changed, %d unchanged, %d gone", r["name"],
                                 r["inserted"], r["changed"], r["unchanged"], r["gone"])
            except Exception:
                log.exception("collection failed")
            trigger = "schedule"
        await asyncio.sleep(min(60, COLLECT_EVERY))


def installed_commit():
    """The commit install.py recorded, so the logs say which code is running."""
    try:
        return json.loads((HERE.parent / "version.json").read_text(encoding="utf-8")).get("commit")
    except (OSError, ValueError):
        return None


async def send(writer, message):
    writer.write(json.dumps(message, ensure_ascii=False).encode() + b"\n")
    await writer.drain()


def reply_to(layer, msg):
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
    method = msg.get("method")
    if method is None or "id" not in msg:
        return None  # a notification, or a response to a request we never send
    try:
        return {"jsonrpc": "2.0", "id": msg["id"], "result": layer.handle(method, msg.get("params") or {})}
    except RpcError as e:
        log.warning("%s: %s", method, e.message)
        return {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": e.code, "message": e.message}}
    except Exception:
        log.exception("%s failed", method)
        return {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": "Internal error in the pwi service"}}


async def main():
    os.umask(0o077)
    commit = installed_commit()
    store.create_or_check(paths.STORE_PATH)
    layer = Layer(paths.STORE_PATH, commit)

    clients = set()
    count = 0

    async def serve_connection(reader, writer):
        nonlocal count
        count += 1
        conn = count
        clients.add(writer)
        log.info("connection %d opened", conn)
        try:
            while line := await reader.readline():
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    await send(writer, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
                    continue
                # In a thread: a read may wait for a refresh, and other clients mustn't wait with it.
                reply = await asyncio.to_thread(reply_to, layer, msg)
                if reply is not None:
                    await send(writer, reply)
        except (ConnectionError, ValueError):  # ValueError: a line over the read limit
            pass
        finally:
            log.info("connection %d closed", conn)
            clients.discard(writer)
            writer.close()

    paths.RUNTIME_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    paths.RUNTIME_DIR.chmod(0o700)
    paths.SOCKET_PATH.unlink(missing_ok=True)
    os.umask(0o177)  # the socket file is 0600
    server = await asyncio.start_unix_server(serve_connection, path=paths.SOCKET_PATH, limit=1 << 22)
    os.umask(0o077)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    log.info("pwi %s%s on Python %s, listening on %s, store %s", VERSION, f" ({commit})" if commit else "",
             platform.python_version(), paths.SOCKET_PATH, paths.STORE_PATH)
    collecting = asyncio.create_task(scheduler())
    try:
        await stop.wait()
    finally:
        log.info("stopping")
        collecting.cancel()
        server.close()
        for writer in list(clients):  # the bridges reconnect on their own once we're back
            writer.close()
        try:
            await asyncio.wait_for(server.wait_closed(), timeout=3)
        except TimeoutError:
            pass
        paths.SOCKET_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(main())
