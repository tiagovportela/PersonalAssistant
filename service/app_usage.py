"""App usage: which window has my focus, and whether I'm active or idle.

Every 10 seconds the service asks GNOME two things over the session bus: the
time since my last input (Mutter's idle monitor), and the focused window (the
reviewed Focused Window D-Bus extension, see gnome_extension.py). Wayland
doesn't let other programs see the active window, hence the extension.
Nothing else is read: never what I type, the clipboard or the screen.

Samples are merged into spans, written to the store every 5 minutes in one
transaction (the brief's batched writes):

- app.focus: one continuous stretch on one window: its app, and its title
  (redacted) when the mode allows titles.
- app.active: active time with no window details (mode "time", or the
  extension isn't running).
- app.idle: no input for IDLE_AFTER seconds or more; it starts at my last input.

Gaps (suspend, shutdown, the service stopped) are left as gaps.

Modes, chosen in the frontend: titles (app names and window titles, the
default), apps (app names only) and time (active and idle time only). If
sampling gets slow, which means GNOME is busy, it falls back to time by
itself, as the brief asks, and says so in the metrics.

Window titles are never stored for private browsing windows or password
managers; their app name still is.
"""

import json
import logging
import re
import statistics
import subprocess
import threading
import time
from collections import deque
from contextlib import closing

import collect
import store
from batch import Batch
from redact import redact

log = logging.getLogger("pwi")
INTERVAL = 10  # seconds between samples
IDLE_AFTER = 120  # seconds without input that count as idle
FLUSH_EVERY = 300  # seconds between writes to the store
SLOW_SAMPLE = 0.25  # seconds: a median sample slower than this falls back to time only
SLOW_WINDOW = 30  # samples the median is taken over
MODES = ("titles", "apps", "time")
DEFAULT_MODE = "titles"
MAX_TITLE = 200

BUS = ["busctl", "--user", "--timeout=2", "--json=short", "call"]
WINDOW_CALL = BUS + ["org.gnome.Shell", "/org/gnome/shell/extensions/FocusedWindow",
                     "org.gnome.shell.extensions.FocusedWindow", "Get"]
IDLE_CALL = BUS + ["org.gnome.Mutter.IdleMonitor", "/org/gnome/Mutter/IdleMonitor/Core",
                   "org.gnome.Mutter.IdleMonitor", "GetIdletime"]

PRIVATE_TITLE = re.compile(r"(?i)private browsing|navegação privada|incognito|anónima|inprivate")
PASSWORD_APPS = re.compile(r"(?i)keepass|bitwarden|1password|lastpass|enpass|proton.?pass|seahorse|gnome-keyring"
                           r"|secrets|passwordsafe|org\.gnome\.World\.Secrets")


# Reading GNOME -------------------------------------------------------------------

def bus_data(command):
    """The reply of a busctl call, decoded, or None if it failed."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)["data"]
    except (ValueError, KeyError, TypeError):
        return None


def idle_seconds():
    data = bus_data(IDLE_CALL)
    return data[0] / 1000 if data and isinstance(data[0], (int, float)) else None


def focused_window():
    """{'app', 'title'} of the focused window; {} when no window has focus; None if the extension isn't there."""
    data = bus_data(WINDOW_CALL)
    if not data or not isinstance(data[0], str):
        return None
    try:
        window = json.loads(data[0])
    except ValueError:
        return None
    if not window:
        return {}
    return {"app": window.get("wm_class") or window.get("wm_class_instance") or None, "title": window.get("title")}


def clean_title(app, title):
    if not title or PRIVATE_TITLE.search(title) or (app and PASSWORD_APPS.search(app)):
        return None
    return redact(title.strip())[:MAX_TITLE] or None


# Turning samples into spans --------------------------------------------------------

class Spans:
    """Merges samples into spans. Pure: times come in, finished spans go out."""

    def __init__(self):
        self.current = None  # {"kind", "app", "title", "start", "last"}
        self.done = []

    def close(self, end):
        span = self.current
        self.current = None
        if span and end > span["start"]:
            self.done.append({**span, "end": end})

    def gap(self, now):
        """Ends the current span if samples stopped (suspend, the service paused)."""
        if self.current and now - self.current["last"] > 3 * INTERVAL:
            self.close(self.current["last"] + INTERVAL)

    def add(self, now, idle, window, mode):
        """One sample. `idle` is seconds since the last input; `window` is focused_window()'s answer."""
        self.gap(now)
        if idle is not None and idle >= IDLE_AFTER:
            since = now - int(idle)
            if self.current and self.current["kind"] == "idle":
                self.current["last"] = now
                return
            if self.current:
                since = max(since, self.current["start"] + 1)
                self.close(since)
            self.current = {"kind": "idle", "app": None, "title": None, "start": since, "last": now}
            return
        if mode == "time" or window is None:
            key = ("active", None, None)
        else:
            app = window.get("app")
            key = ("focus", app, clean_title(app, window.get("title")) if mode == "titles" else None)
        if self.current and (self.current["kind"], self.current["app"], self.current["title"]) == key:
            self.current["last"] = now
            return
        self.close(now)
        self.current = {"kind": key[0], "app": key[1], "title": key[2], "start": now, "last": now}

    def take(self, now):
        """Finished spans, plus the open one as it stands, for writing. The open one is written again
        (grown) next time, under the same id."""
        out, self.done = self.done, []
        if self.current and now - self.current["last"] <= 3 * INTERVAL:
            open_span = {**self.current, "end": max(self.current["last"], self.current["start"] + 1)}
            out.append(open_span)
        return out


# Linking to projects -------------------------------------------------------------

def title_matchers(db):
    """(pattern, project) for each project's folder names and name, longest first: editors and terminals
    put the folder in the window title. Names under 4 letters are too common to match."""
    names = {}
    for r in db.execute("SELECT a.value, a.project_id, p.name FROM project_aliases a JOIN projects p"
                        " ON p.id = a.project_id WHERE a.kind = 'repo_path'"):
        for name in (r["value"].rstrip("/").rsplit("/", 1)[-1], r["name"]):
            if len(name) >= 4:
                names.setdefault(name.lower(), r["project_id"])
    return [(re.compile(rf"(?<![\w.-]){re.escape(n)}(?![\w-])", re.I), p)
            for n, p in sorted(names.items(), key=lambda item: -len(item[0]))]


def project_for(matchers, title):
    if not title:
        return None
    return next((project for pattern, project in matchers if pattern.search(title)), None)


def events(spans, matchers):
    out = []
    for s in spans:
        kind = {"focus": "app.focus", "active": "app.active", "idle": "app.idle"}[s["kind"]]
        payload = {"seconds": s["end"] - s["start"]}
        if s["app"]:
            payload["app"] = s["app"]
        out.append({"id": f"app:{s['kind']}:{s['start']}", "type": kind,
                    "project_id": project_for(matchers, s["title"]) if s["kind"] == "focus" else None,
                    "occurred_at": store.utc(s["start"]), "utc_offset_min": store.local_offset_min(s["start"]),
                    "ended_at": store.utc(s["end"]), "title": s["title"], "payload": payload})
    return out


# Settings -----------------------------------------------------------------------

def mode(db):
    row = db.execute("SELECT value FROM settings WHERE key = 'app_usage.mode'").fetchone()
    return row["value"] if row and row["value"] in MODES else DEFAULT_MODE


def source(db):
    return db.execute("SELECT * FROM sources WHERE kind = 'app_usage' ORDER BY id LIMIT 1").fetchone()


def turn_on(db, chosen=None):
    """Turns app usage on (creating its source), with a mode. Collected from the next sample."""
    if chosen is not None and chosen not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    now = store.now()
    db.execute("BEGIN IMMEDIATE")
    try:
        row = source(db)
        if row:
            db.execute("UPDATE sources SET enabled = 1 WHERE id = ?", (row["id"],))
            source_id = row["id"]
        else:
            source_id = db.execute("INSERT INTO sources (kind, locator, name, added_at) VALUES ('app_usage', 'gnome',"
                                   " 'App usage', ?)", (now,)).lastrowid
        if chosen:
            db.execute("INSERT INTO settings VALUES ('app_usage.mode', ?, ?) ON CONFLICT (key) DO UPDATE SET"
                       " value = excluded.value, changed_at = excluded.changed_at", (chosen, now))
        db.execute("INSERT INTO audit_log (at, actor, action, item_type, item_id) VALUES (?, 'me', 'settings', 'source', ?)",
                   (now, str(source_id)))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return source_id


def turn_off(db):
    row = source(db)
    if row:
        db.execute("UPDATE sources SET enabled = 0 WHERE id = ?", (row["id"],))
        db.execute("INSERT INTO audit_log (at, actor, action, item_type, item_id) VALUES (?, 'me', 'settings', 'source', ?)",
                   (store.now(), str(row["id"])))
    return bool(row)


def status(db):
    """What the frontend and get_metrics show: on or off, the mode, and how sampling is going."""
    row = source(db)
    if row is None:
        return {"on": False, "mode": mode(db)}
    seen = json.loads(row["cursor"] or "{}")
    return {"on": bool(row["enabled"]), "source_id": row["id"], "mode": mode(db), **seen}


# The sampler ----------------------------------------------------------------------

class Sampler:
    """The thread the service runs. Reads the settings once a minute, so turning app usage on or off,
    or changing its mode, in the frontend or with `pwi app-usage`, takes effect within a minute."""

    def __init__(self, store_path, idle_fn=idle_seconds, window_fn=focused_window, clock=time.time,
                 interval=INTERVAL, flush_every=FLUSH_EVERY):
        self.store_path = store_path
        self.idle_fn, self.window_fn, self.clock = idle_fn, window_fn, clock
        self.interval, self.flush_every = interval, flush_every
        self.spans = Spans()
        self.durations = deque(maxlen=SLOW_WINDOW)
        self.samples = 0
        self.extension = "unknown"
        self.fallback = None
        self.settings = None  # (source row, mode)
        self.settings_at = self.flushed_at = 0
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self.run, name="app-usage", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(5)
        try:
            self.flush(self.clock(), final=True)
        except Exception:
            log.exception("app usage: last write failed")

    def run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("app usage sample failed")
            self._stop.wait(self.interval)

    def read_settings(self, now):
        if self.settings is None or now - self.settings_at >= 60:
            with closing(store.connect(self.store_path)) as db:
                row = source(db)
                self.settings = (dict(row) if row else None, mode(db))
            self.settings_at = now
        return self.settings

    def tick(self):
        now = int(self.clock())
        row, chosen = self.read_settings(now)
        if not row or not row["enabled"]:
            if self.spans.current or self.spans.done:
                self.flush(now, final=True)  # turned off: keep what was collected until now
            return
        started = time.monotonic()
        idle = self.idle_fn()
        in_use = "time" if self.fallback else chosen
        window = None
        if in_use != "time" and (idle is None or idle < IDLE_AFTER):
            window = self.window_fn()
            self.extension = "missing" if window is None else "running"
        self.durations.append(time.monotonic() - started)
        self.samples += 1
        if idle is None and window is None:
            self.spans.gap(now)  # GNOME isn't answering (not logged in to GNOME yet): record nothing
        else:
            self.spans.add(now, idle, window, in_use)
        if len(self.durations) == SLOW_WINDOW and not self.fallback \
                and statistics.median(self.durations) > SLOW_SAMPLE:
            self.fallback = (f"Sampling took {statistics.median(self.durations) * 1000:.0f} ms, so only active and "
                             "idle time is collected until the service restarts.")
            log.warning("app usage: %s", self.fallback)
        if now - self.flushed_at >= self.flush_every:
            self.flush(now)

    def stats(self, chosen):
        average = statistics.fmean(self.durations) if self.durations else None
        return {"mode_in_use": "time" if self.fallback else chosen, "extension": self.extension,
                "fallback": self.fallback, "samples_since_start": self.samples,
                "average_sample_ms": round(average * 1000, 1) if average is not None else None,
                "cpu_share_at_most": round(average / self.interval, 4) if average is not None else None,
                "last_sample_at": store.utc(self.clock())}

    def flush(self, now, final=False):
        self.flushed_at = now
        if final:
            self.spans.gap(now + 4 * INTERVAL)  # closes the open span at its last sample
        spans = self.spans.take(now)
        with closing(store.connect(self.store_path)) as db:
            row = source(db)
            if row is None:
                return
            chosen = mode(db)

            def collector(db, src, since):
                return Batch(events=events(spans, title_matchers(db)), cursor=json.dumps(self.stats(chosen)))

            collect.run_source(db, row, "schedule", collector)
