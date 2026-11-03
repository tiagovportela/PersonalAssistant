"""Installs the reviewed Focused Window D-Bus extension, which app usage needs.

The brief requires third-party code to be reviewed, pinned and checksum-checked,
with no automatic updates. The extension's files are kept in the repository
(third_party/focused-window-dbus, the reviewed commit), checked against the
review's checksums before every install, and installed under the layer's own
identifier. GNOME updates extensions by identifier from extensions.gnome.org,
which doesn't know this one, so an update can't replace the reviewed code.

GNOME loads a newly installed extension at the next login, so the first install
asks me to log out and back in once.
"""

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import app_usage

VENDORED = Path(__file__).resolve().parents[1] / "third_party" / "focused-window-dbus"
COMMIT = "c70038ebd2a669ae36d578abcb8b332224a88dcf"
CHECKSUMS = {  # sha256 of the upstream files at COMMIT, from docs/third_party_reviews.md
    "extension.js": "de7ab71d0c22a3c43b8acefda75cab44b55b6db5585fc858ce04025149a02ee7",
    "metadata.json": "1552abe743a17d164571370b20d820406cfeb044e2833b3e1d0ca2f8d3071101",
    "LICENSE": "737afd9cbd96c97e5bc2df15ae827bf33cc9cbfcba5d34f63a23056284974143",
}
UUID = "focused-window-dbus-pinned@pwi.local"
UPSTREAM_UUID = "focused-window-dbus@flexagoon.com"


class ExtensionError(Exception):
    """Why the extension can't be installed, in words I can act on."""


def extensions_dir():
    data = os.environ.get("XDG_DATA_HOME", "")
    base = Path(data) if os.path.isabs(data) else Path.home() / ".local" / "share"
    return base / "gnome-shell" / "extensions"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(folder=VENDORED):
    """Raises unless every vendored file matches the reviewed checksum."""
    for name, expected in CHECKSUMS.items():
        path = folder / name
        if not path.is_file() or sha256(path) != expected:
            raise ExtensionError(f"{path} doesn't match the reviewed version (commit {COMMIT[:7]}), so it isn't "
                                 "installed. Reinstall the layer from the repository.")


def metadata():
    """The upstream metadata with the layer's identifier, so extensions.gnome.org never updates it."""
    meta = json.loads((VENDORED / "metadata.json").read_text(encoding="utf-8"))
    meta.update({"uuid": UUID, "name": "Focused Window D-Bus (pinned by pwi)",
                 "description": f"{meta['description']}. Upstream {meta['url']} at commit {COMMIT}, reviewed and "
                                "installed by the Personal Work Intelligence layer; not updated automatically."})
    return json.dumps(meta, indent=2) + "\n"


def run(*command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def shell_version():
    out = run("gnome-shell", "--version") or ""
    m = re.search(r"(\d+)(?:\.\d+)*", out)
    return m.group(0) if m else None


def supported_versions():
    return json.loads((VENDORED / "metadata.json").read_text(encoding="utf-8"))["shell-version"]


def string_list(text):
    """A gsettings string list, e.g. "['a', 'b']" or '@as []'."""
    if not text:
        return []
    try:
        value = ast.literal_eval(text.removeprefix("@as").strip())
    except (ValueError, SyntaxError):
        return []
    return [v for v in value if isinstance(v, str)]


def gsettings_list(key):
    return string_list(run("gsettings", "get", "org.gnome.shell", key))


def set_gsettings_list(key, values):
    return run("gsettings", "set", "org.gnome.shell", key, str(list(values))) is not None


def installed():
    folder = extensions_dir() / UUID
    return ((folder / "extension.js").is_file() and sha256(folder / "extension.js") == CHECKSUMS["extension.js"]
            and (folder / "metadata.json").is_file() and (folder / "metadata.json").read_text(encoding="utf-8") == metadata())


def status():
    version = shell_version()
    major = version.split(".")[0] if version else None
    enabled = UUID in gsettings_list("enabled-extensions")
    return {
        "gnome_shell": version,
        "supported": bool(major) and major in supported_versions(),
        "supported_versions": supported_versions(),
        "installed": installed(),
        "enabled": enabled,
        "user_extensions_off": run("gsettings", "get", "org.gnome.shell", "disable-user-extensions") == "true",
        "running": app_usage.focused_window() is not None,
        "upstream_copy_enabled": UPSTREAM_UUID in gsettings_list("enabled-extensions"),
    }


def install():
    """Installs and enables the pinned extension. Returns status(), with what I still have to do in `todo`."""
    verify()
    version = shell_version()
    if version is None:
        raise ExtensionError("GNOME Shell wasn't found, so the active window can't be read. App usage can still "
                             "record active and idle time: pwi app-usage on --mode time")
    if version.split(".")[0] not in supported_versions():
        raise ExtensionError(f"The reviewed extension supports GNOME Shell {', '.join(supported_versions())}, and "
                             f"this is GNOME Shell {version}. App usage can still record active and idle time: "
                             "pwi app-usage on --mode time")
    folder = extensions_dir() / UUID
    new = folder.with_name(UUID + ".new")
    shutil.rmtree(new, ignore_errors=True)
    new.mkdir(parents=True)
    for name in ("extension.js", "LICENSE"):
        shutil.copyfile(VENDORED / name, new / name)
    (new / "metadata.json").write_text(metadata(), encoding="utf-8")
    verify_installed = sha256(new / "extension.js") == CHECKSUMS["extension.js"]
    if not verify_installed:
        shutil.rmtree(new, ignore_errors=True)
        raise ExtensionError("The extension changed while it was being copied; nothing was installed. Try again.")
    shutil.rmtree(folder, ignore_errors=True)
    new.rename(folder)
    enabled = gsettings_list("enabled-extensions")
    if UUID not in enabled:
        set_gsettings_list("enabled-extensions", [*enabled, UUID])
    disabled = gsettings_list("disabled-extensions")
    if UUID in disabled:
        set_gsettings_list("disabled-extensions", [d for d in disabled if d != UUID])
    run("gnome-extensions", "enable", UUID)  # works without a new login once GNOME has seen the extension
    result = status()
    todo = []
    if result["user_extensions_off"]:
        todo.append("Extensions are turned off for this account (disable-user-extensions). Turn them on in the "
                    "Extensions app; if your company locks this setting, use: pwi app-usage on --mode time")
    if not result["running"]:
        todo.append("Log out and back in once, so GNOME loads the extension.")
    if result["upstream_copy_enabled"]:
        todo.append(f"The upstream copy ({UPSTREAM_UUID}) is also enabled; remove it in the Extensions app, because "
                    "extensions.gnome.org can update it.")
    result["todo"] = todo
    return result


def uninstall():
    """Disables and removes the extension; touches GNOME's settings only if it's there."""
    enabled = gsettings_list("enabled-extensions")
    if UUID in enabled:
        set_gsettings_list("enabled-extensions", [e for e in enabled if e != UUID])
        run("gnome-extensions", "disable", UUID)
    shutil.rmtree(extensions_dir() / UUID, ignore_errors=True)
