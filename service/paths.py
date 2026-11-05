"""Where the layer keeps things, from the XDG base directories. Nothing here
depends on the user name, so the same code runs on any machine."""

import os
from pathlib import Path


def _xdg(variable, default):
    value = os.environ.get(variable, "")
    return Path(value) if os.path.isabs(value) else Path.home() / default


RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "pwi"
SOCKET_PATH = RUNTIME_DIR / "mcp.sock"

CONFIG_HOME = _xdg("XDG_CONFIG_HOME", ".config")
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "pwi"
STORE_PATH = DATA_DIR / "store.db"
APP_DIR = DATA_DIR / "app"  # installed code; replaced on every install, unlike the store
BIN_DIR = Path.home() / ".local" / "bin"  # on PATH by default on Ubuntu

CLAUDE_CLOUD = DATA_DIR / "claude_cloud"  # copies of cloud sessions I imported; kept until deleted
CLAUDE_PROJECTS = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
