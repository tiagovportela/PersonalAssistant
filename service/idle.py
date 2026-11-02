"""How long since my last keyboard or mouse input, from GNOME's idle monitor.

Only the idle time is read, never what was typed. Returns None when it can't
be read (not GNOME, or no session bus), so callers can fall back.
"""

import re
import subprocess

COMMAND = ["gdbus", "call", "--session", "--dest", "org.gnome.Mutter.IdleMonitor",
           "--object-path", "/org/gnome/Mutter/IdleMonitor/Core",
           "--method", "org.gnome.Mutter.IdleMonitor.GetIdletime"]


def parse(output):
    """Seconds from gdbus's reply, e.g. '(uint64 123456,)' in milliseconds."""
    m = re.search(r"uint64\s+(\d+)", output)
    return int(m.group(1)) / 1000 if m else None


def idle_seconds():
    try:
        result = subprocess.run(COMMAND, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse(result.stdout) if result.returncode == 0 else None
