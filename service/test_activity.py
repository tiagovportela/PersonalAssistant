"""Checks Phase 4: Firefox history, app usage, the GNOME extension installer,
contradiction detection and the metrics, against a fake Firefox profile, fake
GNOME answers and claims in a temporary store. Nothing here touches the real
desktop settings or the real Firefox profile.

Run: python3 -I service/test_activity.py
"""

import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pwi-activity-"))
os.environ.update({"HOME": str(TMP), "XDG_DATA_HOME": str(TMP / "data"), "XDG_CONFIG_HOME": str(TMP / "config"),
                   "XDG_RUNTIME_DIR": str(TMP / "run"), "CLAUDE_CONFIG_DIR": str(TMP / "claude"),
                   "GIT_CONFIG_GLOBAL": str(TMP / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"})
(TMP / "run").mkdir(mode=0o700)
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]

import app_usage  # noqa: E402
import collect  # noqa: E402
import collect_firefox as ff  # noqa: E402
import contradictions  # noqa: E402
import gnome_extension  # noqa: E402
import handlers  # noqa: E402
import paths  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402

TODAY = date.today()
NOW = store.now()


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def epoch(day, hour, minute=0):
    return int(datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute).astimezone().timestamp())


# Firefox -------------------------------------------------------------------------

def test_clean_url():
    cases = {
        "https://example.com/a?q=sqlite+wal&access_token=abc123secret&page=2": "https://example.com/a?q=sqlite+wal&page=2",
        "https://example.com/cb?code=4/0AbCd&state=xyz&scope=email": "https://example.com/cb?scope=email",
        "https://x.com/?utm_source=news&fbclid=IwAR123&id=7": "https://x.com/?id=7",
        "https://u:hunter2@example.com/private": "https://example.com/private",
        "https://app.example.com/#access_token=eyJhbGciOi&token_type=bearer&view=1": "https://app.example.com/#view=1",
        "https://docs.example.com/guide#install": "https://docs.example.com/guide#install",
        "https://shop.example.com/Some-Product-Name-V2-32GB-Black-Edition-2026": "https://shop.example.com/Some-Product-Name-V2-32GB-Black-Edition-2026",
        "https://example.com/reset/Xk9vQ2mLp7RtZ3wN8bYc4HdF6gJ1sA0e": "https://example.com/reset/[REDACTED]",
        "https://github.com/acme/billing/commit/0123456789abcdef0123456789abcdef01234567":
            "https://github.com/acme/billing/commit/0123456789abcdef0123456789abcdef01234567",
        "https://accounts.example.com/signin?continue=https://mail.example.com/?auth=SECRETVALUE%26folder=inbox":
            "https://accounts.example.com/signin?continue=https%3A%2F%2Fmail.example.com%2F%3Ffolder%3Dinbox",
        "https://accounts.example.com/o/oauth2?client_id=123.apps&redirect_uri=http://127.0.0.1:8123/":
            "https://accounts.example.com/o/oauth2?client_id=123.apps",
        "https://example.com/?note=ghp_abcdefghijklmnopqrstuvwxyz0123456789": "https://example.com/",
    }
    for raw, expected in cases.items():
        got = ff.clean_url(raw)
        check(f"clean_url: {raw[:60]}…", got == expected) if got == expected else check(
            f"clean_url: {raw} gave {got}, expected {expected}", False)
    for skipped in ("http://127.0.0.1:43210/login?code=abc", "http://localhost:5173/", "file:///home/me/notes.txt",
                    "about:config", "moz-extension://abc/page.html", "http://[::1]:8080/"):
        check(f"not stored at all: {skipped}", ff.clean_url(skipped) is None)


def make_profile(root, name="abcd.default-release", ini_extra=""):
    profile = root / name
    profile.mkdir(parents=True)
    (root / "profiles.ini").write_text(
        f"[Profile0]\nName=default-release\nIsRelative=1\nPath={name}\nDefault=1\n\n{ini_extra}", encoding="utf-8")
    db = sqlite3.connect(profile / "places.sqlite")
    db.executescript("""
        PRAGMA journal_mode = WAL;
        CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT NOT NULL, title TEXT, hidden INTEGER DEFAULT 0,
                                 guid TEXT UNIQUE);
        CREATE TABLE moz_historyvisits (id INTEGER PRIMARY KEY, from_visit INTEGER, place_id INTEGER,
                                        visit_date INTEGER, visit_type INTEGER, session INTEGER);
    """)
    db.close()
    return profile


class Firefox:
    """A fake places.sqlite that's written while 'Firefox runs': kept open, never checkpointed."""

    def __init__(self, profile):
        self.db = sqlite3.connect(profile / "places.sqlite", isolation_level=None)
        self.db.execute("PRAGMA wal_autocheckpoint = 0")
        self.places = {}

    def visit(self, url, title, when, visit_type=1, hidden=0):
        if url not in self.places:
            guid = f"g{len(self.places):011d}"
            self.places[url] = self.db.execute("INSERT INTO moz_places (url, title, hidden, guid) VALUES (?, ?, ?, ?)",
                                               (url, title, hidden, guid)).lastrowid
        return self.db.execute("INSERT INTO moz_historyvisits (place_id, visit_date, visit_type) VALUES (?, ?, ?)",
                               (self.places[url], when * 1_000_000, visit_type)).lastrowid


def test_profiles():
    home = TMP / "home-profiles"
    snap = home / "snap/firefox/common/.mozilla/firefox"
    make_profile(snap, "old.default")
    make_profile(snap.parent / "firefox-tmp", "unused")  # not a Firefox root: ignored
    (snap / "new.default-release").mkdir()
    sqlite3.connect(snap / "new.default-release" / "places.sqlite").close()
    (snap / "profiles.ini").write_text(
        "[Install4F96D1932A9F858E]\nDefault=new.default-release\nLocked=1\n\n"
        "[Profile1]\nName=default-release\nIsRelative=1\nPath=new.default-release\n\n"
        "[Profile0]\nName=default\nIsRelative=1\nPath=old.default\nDefault=1\n", encoding="utf-8")
    classic = home / ".mozilla/firefox"
    make_profile(classic, "classic.default")
    os.utime(classic / "classic.default" / "places.sqlite", (1_700_000_000, 1_700_000_000))  # an old install
    found = ff.profiles(home)
    check("the profile Firefox opens by default (its [Install] section) comes first, then other installs' "
          "defaults by last use", [f[0] for f in found] == [snap / "new.default-release", classic / "classic.default",
                                                             snap / "old.default"])


def test_firefox_collector(db, layer, call):
    root = TMP / "snap/firefox/common/.mozilla/firefox"
    profile = make_profile(root)
    fox = Firefox(profile)
    today_9 = epoch(TODAY, 9)
    fox.visit("https://github.com/acme/billing/pull/42", "Fix rounding by ana · Pull Request #42 · acme/billing", today_9)
    fox.visit("https://www.sqlite.org/wal.html?utm_source=x", "Write-Ahead Logging", today_9 + 60, visit_type=2)
    fox.visit("https://www.sqlite.org/wal.html?utm_source=x", "Write-Ahead Logging", today_9 + 600)
    fox.visit("https://login.example.com/cb?code=SECRETCODE&next=/home", "Signing in password=hunter22", today_9 + 700)
    fox.visit("http://127.0.0.1:41234/login?code=pwi-login", "Personal Work Intelligence", today_9 + 800)
    fox.visit("https://ads.example.com/frame", "ad", today_9 + 900, visit_type=8)  # framed link
    fox.visit("https://cdn.example.com/file.zip?sig=abc", "file.zip", today_9 + 950, visit_type=7)  # download
    fox.visit("https://www.sqlite.org/wal.html?utm_source=x", "Write-Ahead Logging", today_9 + 960, visit_type=9)  # reload
    fox.visit("https://t.example.com/r/abc", "redirect step", today_9 + 970, hidden=1)
    old = fox.visit("https://old.example.com/", "Too old", epoch(TODAY - timedelta(days=120), 9))
    check("the fake profile keeps its visits in the write-ahead log, as while Firefox runs",
          (profile / "places.sqlite-wal").stat().st_size > 0)

    added = sources.add_firefox(db)
    check("pwi add-firefox finds the default profile and turns Firefox history on",
          added["status"] == "turned on" and added["profile"] == os.path.realpath(profile))
    check("adding it again changes nothing", sources.add_firefox(db)["status"] == "already on")
    [run] = [r for r in collect.run(paths.STORE_PATH) if r["kind"] == "firefox"]
    visits = db.execute("SELECT * FROM events WHERE type = 'firefox.visit' ORDER BY occurred_at").fetchall()
    urls = [json.loads(v["payload"])["url"] for v in visits]
    check("only pages I opened are stored: not frames, downloads, reloads, hidden redirects, local addresses "
          "or visits older than retention",
          run["inserted"] == 4 and urls == ["https://github.com/acme/billing/pull/42", "https://www.sqlite.org/wal.html",
                                           "https://www.sqlite.org/wal.html", "https://login.example.com/cb?next=%2Fhome"])
    check("secret-looking parameters are stripped and titles redacted",
          "SECRETCODE" not in json.dumps([dict(v) for v in visits]) and visits[3]["title"] == "Signing in password=[REDACTED]")
    check("a visit to a project's GitHub repository is linked to the project",
          visits[0]["project_id"] == "billing" and visits[1]["project_id"] is None)
    check("the copy of Firefox's history is deleted after reading",
          not any((paths.RUNTIME_DIR).glob("firefox-*")))

    again = collect.run_source(db, db.execute("SELECT * FROM sources WHERE kind = 'firefox'").fetchone(), "manual")
    check("a second pass with Firefox's files unchanged reads nothing and counts the visits as unchanged",
          again["inserted"] == 0 and again["unchanged"] == 4)

    fox.visit("https://docs.python.org/3/library/sqlite3.html", "sqlite3 — DB-API 2.0", today_9 + 3600)
    synced = fox.visit("https://notes.example.com/from-my-phone", "Read on my phone", epoch(TODAY - timedelta(days=5), 20))
    fox.db.execute("DELETE FROM moz_historyvisits WHERE id = (SELECT MIN(id) FROM moz_historyvisits"
                   " WHERE place_id = (SELECT id FROM moz_places WHERE url LIKE 'https://www.sqlite.org/%'))")
    later = collect.run_source(db, db.execute("SELECT * FROM sources WHERE kind = 'firefox'").fetchone(), "manual")
    check("new visits are added, an older one Firefox Sync brought in late too, and one I deleted in Firefox "
          "is marked gone", later["inserted"] == 2 and later["gone"] == 1 and synced and old)

    db.execute("INSERT INTO project_aliases VALUES ('notion', 'https://www.notion.so/Billing-plan-0123456789abcdef0123456789abcdef',"
               " 'billing', 'me', ?)", (NOW,))
    fox.visit("https://www.notion.so/acme/Billing-plan-0123456789abcdef0123456789abcdef?pvs=4", "Billing plan", today_9 + 4000)
    collect.run_source(db, db.execute("SELECT * FROM sources WHERE kind = 'firefox'").fetchone(), "manual")
    check("a visit to a project's Notion page is linked to the project",
          db.execute("SELECT project_id FROM events WHERE title = 'Billing plan'").fetchone()[0] == "billing")

    day = call("get_day", {"day": TODAY.isoformat()})
    pages = day["browsing"]["pages"]
    check("get_day lists each page once with its visits, project pages first in the choice, and no gone visit",
          day["browsing"]["visits"] == 5 and {p["url"]: p["visits"] for p in pages}["https://www.sqlite.org/wal.html"] == 1
          and {p["project"] for p in pages if "project" in p} == {"billing"})
    check("Firefox visits aren't listed with commits and sessions",
          all("firefox.visit" not in json.dumps(g) for g in day["events_by_project"].values()))
    found = call("search", {"query": "write ahead logging"})
    check("search finds a page by its title, once", [r["url"] for r in found["results"] if r.get("type") == "firefox.visit"]
          == ["https://www.sqlite.org/wal.html"])
    check("search finds a page by a word in its address", any(
        r.get("site") == "docs.python.org" for r in call("search", {"query": "library", "kinds": ["firefox"]})["results"]))
    project = call("get_project", {"project": "billing"})
    check("get_project shows the project's recent pages", {p["title"] for p in project["recent_pages"]}
          == {"Fix rounding by ana · Pull Request #42 · acme/billing", "Billing plan"})
    firefox_id = db.execute("SELECT id FROM sources WHERE kind = 'firefox'").fetchone()[0]
    db.execute("INSERT INTO labels VALUES ('source', ?, 'confidential', 'me', ?)", (str(firefox_id), NOW))
    check("a confidential label on Firefox hides all browsing from Claude",
          "browsing" not in call("get_day", {"day": TODAY.isoformat()}))
    db.execute("DELETE FROM labels WHERE item_type = 'source'")
    fox.db.close()


# App usage -------------------------------------------------------------------------

def test_spans():
    spans = app_usage.Spans()
    t = 1_800_000_000
    editor = {"app": "code", "title": "main.py - billing - Visual Studio Code"}
    for i in range(3):
        spans.add(t + 10 * i, 1, editor, "titles")
    spans.add(t + 30, 2, {"app": "firefox", "title": "Pricing — Mozilla Firefox Private Browsing"}, "titles")
    spans.add(t + 40, 3, {"app": "org.keepassxc.KeePassXC", "title": "work.kdbx - KeePassXC"}, "titles")
    spans.add(t + 50, 130, {"app": "org.keepassxc.KeePassXC", "title": "work.kdbx - KeePassXC"}, "titles")
    spans.add(t + 60, 140, None, "titles")
    spans.add(t + 70, 2, editor, "titles")
    spans.add(t + 700, 1, editor, "titles")  # after a suspend
    done = spans.take(t + 700)
    check("samples merge into spans: focus, idle from the last input, a gap after a suspend, and the open span",
          [(s["kind"], s["start"], s["end"]) for s in done] == [
              ("focus", t, t + 30), ("focus", t + 30, t + 40), ("focus", t + 40, t + 41), ("idle", t + 41, t + 70),
              ("focus", t + 70, t + 80), ("focus", t + 700, t + 701)])
    check("private browsing and password manager windows keep their app but not their title",
          done[1]["app"] == "firefox" and done[1]["title"] is None and done[2]["title"] is None)
    other = app_usage.Spans()
    other.add(t, 1, editor, "apps")
    other.add(t + 10, 1, {"app": "code", "title": "other.py - billing"}, "apps")
    other.add(t + 20, 1, editor, "time")
    check("mode apps keeps one span per app with no title; mode time keeps only active time",
          [(s["kind"], s["app"], s["title"]) for s in other.take(t + 20)] == [("focus", "code", None), ("active", None, None)])


class FakeGnome:
    def __init__(self):
        self.idle, self.window, self.now = 1, {"app": "code", "title": "main.py - billing - Visual Studio Code"}, 0

    def idle_fn(self):
        return self.idle

    def window_fn(self):
        return self.window

    def clock(self):
        return self.now


def test_sampler(db, call):
    gnome = FakeGnome()
    start = epoch(TODAY, 10)
    gnome.now = start
    sampler = app_usage.Sampler(paths.STORE_PATH, gnome.idle_fn, gnome.window_fn, gnome.clock, flush_every=300)
    sampler.tick()
    check("nothing is sampled until app usage is turned on", sampler.samples == 0)
    app_usage.turn_on(db)
    sampler.settings = None
    for i in range(30):  # 5 minutes in the editor
        gnome.now = start + 10 * i
        sampler.tick()
    gnome.window = {"app": "firefox", "title": "Pricing ideas — Mozilla Firefox"}
    for i in range(30, 60):
        gnome.now = start + 10 * i
        sampler.tick()
    gnome.idle = 200
    for i in range(60, 90):
        gnome.now = start + 10 * i
        sampler.tick()
    spans = db.execute("SELECT type, title, project_id, payload FROM events WHERE type LIKE 'app.%' ORDER BY occurred_at").fetchall()
    check("spans are written in batches, about every 5 minutes, with the open one written as it stands",
          [s["type"] for s in spans] == ["app.focus", "app.focus", "app.idle"]
          and db.execute("SELECT COUNT(*) FROM collector_runs r JOIN sources s ON s.id = r.source_id"
                         " WHERE s.kind = 'app_usage'").fetchone()[0] == 3)
    check("a window title naming a project's folder links the span to the project",
          spans[0]["project_id"] == "billing" and spans[1]["project_id"] is None)
    sampler.stop()
    status = app_usage.status(db)
    check("the source records the mode in use, the extension's state and the cost of sampling",
          status["mode_in_use"] == "titles" and status["extension"] == "running" and status["average_sample_ms"] is not None)
    day = call("get_day", {"day": TODAY.isoformat()})
    ct = day["computer_time"]
    # Idle starts at my last input, 200 s before the first idle sample: Firefox had 100 s, not 300.
    check("get_day shows active and idle time, by app, project and window",
          ct["active_minutes"] == 6.7 and ct["idle_minutes"] == 8.3 and ct["by_app"][0]["minutes"] == 5.0
          and ct["by_project"] == {"billing": 5.0} and ct["top_windows"][0]["project"] == "billing")
    coverage = day["coverage"]
    check("app usage that wrote recently isn't stale, and it never triggers a collection",
          "app_usage" in coverage["sources_checked"] and "app_usage" not in coverage["stale_sources"])

    app_usage.turn_on(db, "time")
    timed = app_usage.Sampler(paths.STORE_PATH, gnome.idle_fn, lambda: (_ for _ in ()).throw(AssertionError("asked")),
                              gnome.clock)
    gnome.idle, gnome.now = 1, start + 3600
    timed.tick()
    check("in mode time the focused window is never asked for", timed.samples == 1)
    app_usage.turn_on(db, "titles")
    slow = app_usage.Sampler(paths.STORE_PATH, gnome.idle_fn, gnome.window_fn, gnome.clock)
    saved, app_usage.SLOW_SAMPLE = app_usage.SLOW_SAMPLE, -1
    try:
        for i in range(app_usage.SLOW_WINDOW + 1):
            gnome.now = start + 7200 + 10 * i
            slow.tick()
    finally:
        app_usage.SLOW_SAMPLE = saved
    check("slow sampling falls back to active and idle time only, and says why",
          slow.fallback and "active and idle time" in slow.fallback and slow.stats("titles")["mode_in_use"] == "time")
    missing = app_usage.Sampler(paths.STORE_PATH, gnome.idle_fn, lambda: None, gnome.clock)
    gnome.now = start + 9000
    missing.tick()
    check("without the extension, active time is still recorded, and the status says only time is",
          missing.extension == "missing" and missing.spans.current["kind"] == "active"
          and missing.stats("titles")["mode_in_use"] == "time")
    app_usage.turn_off(db)
    off = app_usage.Sampler(paths.STORE_PATH, gnome.idle_fn, gnome.window_fn, gnome.clock)
    off.tick()
    check("turned off, nothing is sampled", off.samples == 0)


def test_extension():
    gnome_extension.verify()
    check("the vendored extension matches the reviewed checksums", True)
    tampered = TMP / "tampered"
    shutil.copytree(gnome_extension.VENDORED, tampered)
    with open(tampered / "extension.js", "a") as f:
        f.write("\n// changed\n")
    try:
        gnome_extension.verify(tampered)
        check("a changed extension is refused", False)
    except gnome_extension.ExtensionError as e:
        check("a changed extension is refused", "doesn't match the reviewed version" in str(e))
    meta = json.loads(gnome_extension.metadata())
    check("it's installed under the layer's own identifier, so extensions.gnome.org can't update it",
          meta["uuid"] == gnome_extension.UUID and gnome_extension.COMMIT in meta["description"])
    check("gsettings lists are read", gnome_extension.string_list("['a@x', 'b@y']") == ["a@x", "b@y"]
          and gnome_extension.string_list("@as []") == [])

    settings = {"enabled-extensions": "['ubuntu-dock@ubuntu.com']", "disabled-extensions": "@as []",
                "disable-user-extensions": "false"}
    version = {"v": "GNOME Shell 50.1"}

    def fake_run(*command):
        if command[0] == "gnome-shell":
            return version["v"]
        if command[:2] == ("gsettings", "get"):
            return settings[command[3]]
        if command[:2] == ("gsettings", "set"):
            settings[command[3]] = command[4]
            return ""
        return None  # gnome-extensions: GNOME hasn't seen the extension yet

    real_run, real_window = gnome_extension.run, gnome_extension.app_usage.focused_window
    gnome_extension.run, gnome_extension.app_usage.focused_window = fake_run, lambda: None
    try:
        result = gnome_extension.install()
        folder = Path(os.environ["XDG_DATA_HOME"]) / "gnome-shell" / "extensions" / gnome_extension.UUID
        check("install copies the reviewed files, enables the extension and asks for one new login",
              result["installed"] and result["enabled"] and (folder / "extension.js").is_file()
              and gnome_extension.UUID in settings["enabled-extensions"] and "ubuntu-dock@ubuntu.com" in settings["enabled-extensions"]
              and any("Log out" in step for step in result["todo"]))
        gnome_extension.uninstall()
        check("uninstall removes it and disables it", not folder.exists()
              and gnome_extension.UUID not in settings["enabled-extensions"])
        version["v"] = "GNOME Shell 46.0"
        try:
            gnome_extension.install()
            check("an unsupported GNOME Shell is refused, pointing to time-only mode", False)
        except gnome_extension.ExtensionError as e:
            check("an unsupported GNOME Shell is refused, pointing to time-only mode", "--mode time" in str(e))
    finally:
        gnome_extension.run, gnome_extension.app_usage.focused_window = real_run, real_window


# Contradictions and metrics ----------------------------------------------------------

def add_claim(db, claim_id, kind, text, project="billing", status="proposed", due_at=None, owner=None, at=NOW):
    db.execute("INSERT INTO claims VALUES (?, ?, ?)", (claim_id, kind, at))
    db.execute("INSERT INTO claim_versions (claim_id, version, status, text, project_id, due_at, owner, method,"
               " changed_by, created_at) VALUES (?, 1, ?, ?, ?, ?, ?, 'claude', ?, ?)",
               (claim_id, status, text, project, due_at, owner, "me" if status == "supported" else "claude", at))


def test_contradictions(db, call):
    add_claim(db, "clm_a1", "decision", "We will use Redis for the session cache in billing", status="supported")
    add_claim(db, "clm_a2", "decision", "We won't use Redis for the session cache in billing")
    add_claim(db, "clm_b1", "decision", "Keep the nightly export job for finance reports")
    add_claim(db, "clm_b2", "decision", "Remove the nightly export job for finance reports")
    add_claim(db, "clm_c1", "commitment", "Send the invoice migration plan to Ana", due_at="2026-11-06", owner="me")
    add_claim(db, "clm_c2", "commitment", "Send the invoice migration plan to Ana", due_at="2026-11-13", owner="me")
    add_claim(db, "clm_d1", "fact", "Release 2.3 ships the CSV export to customers")
    add_claim(db, "clm_d2", "fact", "Release 2.4 ships the CSV export to customers")
    add_claim(db, "clm_e1", "decision", "Use GitHub Actions for the deploy pipeline")
    add_claim(db, "clm_e2", "decision", "The deploy pipeline uses GitHub Actions runners on our hardware")
    add_claim(db, "clm_f1", "decision", "We will use Redis for the session cache in billing", project="alpha")
    add_claim(db, "clm_g1", "decision", "Lunch is at noon on Fridays")
    found, total = contradictions.candidates(db)
    pairs = {frozenset(c["claim_id"] for c in p["claims"]): p["why"] for p in found}
    check("negation, opposite words, different due dates and different numbers are found",
          pairs.get(frozenset({"clm_a1", "clm_a2"})) == ["one is negated and the other isn't"]
          and "opposite words" in pairs.get(frozenset({"clm_b1", "clm_b2"}), [""])[0]
          and pairs.get(frozenset({"clm_c1", "clm_c2"})) == ["different due dates (2026-11-06 / 2026-11-13)"]
          and "2.3" in pairs.get(frozenset({"clm_d1", "clm_d2"}), [""])[0])
    check("claims that only add detail, are about other things, or belong to other projects aren't flagged",
          total == 4 and frozenset({"clm_e1", "clm_e2"}) not in pairs
          and not any("clm_f1" in p or "clm_g1" in p for p in pairs))
    unconfirmed = call("list_unconfirmed")
    check("list_unconfirmed brings the possible contradictions to the review",
          len(unconfirmed["possible_contradictions"]) == 4)
    linked = call("link_items", {"from": {"type": "claim", "id": "clm_b2"}, "rel": "related",
                                 "to": {"type": "claim", "id": "clm_b1"}})
    check("once I say a pair doesn't conflict (a link), it isn't suggested again",
          linked["created"] and contradictions.candidates(db)[1] == 3)
    call("link_items", {"from": {"type": "claim", "id": "clm_d2"}, "rel": "supersedes",
                        "to": {"type": "claim", "id": "clm_d1"}})
    superseded = call("set_claim_status", {"claim_id": "clm_d1", "status": "superseded", "reason": "replaced by clm_d2"})
    check("a claim I say was replaced is marked superseded and disappears from what Claude uses",
          superseded["changed"] and "clm_d1" not in json.dumps(call("get_project", {"project": "billing"})))
    project = call("get_project", {"project": "billing"})
    check("get_project shows the project's open contradictions",
          {frozenset(c["claim_id"] for c in p["claims"]) for p in project["possible_contradictions"]}
          == {frozenset({"clm_a1", "clm_a2"}), frozenset({"clm_c1", "clm_c2"})})


def test_metrics(db, call):
    add_claim(db, "clm_m1", "commitment", "Review Ana's pricing PR", due_at=(TODAY - timedelta(days=2)).isoformat(),
              owner="me")
    db.execute("INSERT INTO claim_versions (claim_id, version, status, text, project_id, method, changed_by, created_at)"
               " VALUES ('clm_m1', 2, 'retracted', 'Review Ana''s pricing PR', 'billing', 'claude', 'me', ?)", (NOW,))
    add_claim(db, "clm_m3", "commitment", "Reply to finance about the audit export", project="alpha",
              due_at=(TODAY - timedelta(days=1)).isoformat(), owner="me")
    add_claim(db, "clm_m2", "fact", "The tax module belongs to billing")
    db.execute("INSERT INTO claim_versions (claim_id, version, status, text, project_id, method, changed_by, created_at)"
               " VALUES ('clm_m2', 2, 'proposed', 'The tax module belongs to billing', 'alpha', 'claude', 'claude', ?)", (NOW,))
    m = call("get_metrics")
    firefox = next(c for c in m["collectors"] if c["source"] == "firefox")
    check("each source reports freshness, ingestion lag and how much is linked to a project",
          firefox["minutes_since_last_success"] is not None and firefox["ingestion_lag_minutes"]["median"] >= 0
          and 0 < firefox["linked_to_project"] < 1)
    check("claims are counted by type, with false commitments and project corrections",
          m["claims_by_type"]["commitment"]["retracted"] == 1 and m["false_commitments"]["retracted_share"] == 1.0
          and m["project_matching"]["project_corrected"] == 1)
    check("missed deadlines and possible contradictions are reported",
          [c["claim_id"] for c in m["missed_deadlines"]["commitments"]] == ["clm_m3"]
          and m["contradictions"]["possible"] == 2
          and m["contradictions"]["disputed_claims"] == 0)
    check("app usage's overhead is reported", m["app_usage"]["average_sample_ms"] is not None)


def main():
    logging.disable(logging.WARNING)  # the fallback test logs a warning on purpose
    os.umask(0o077)
    store.create_or_check(paths.STORE_PATH)
    layer = handlers.Layer(paths.STORE_PATH)

    def call(name, args=None):
        result = layer.call_tool(name, args or {})
        text = result["content"][0]["text"]
        if result["isError"]:
            return {"error": text}
        return json.loads(text.split("\n", 1)[1].rsplit("\n", 1)[0])

    repo = TMP / "Projects" / "billing"
    repo.mkdir(parents=True)
    sh(repo, "git", "init", "-q", "-b", "main")
    sh(repo, "git", "remote", "add", "origin", "git@github.com:acme/billing.git")
    alpha = TMP / "Projects" / "alpha"
    alpha.mkdir()
    sh(alpha, "git", "init", "-q", "-b", "main")
    db = store.connect(paths.STORE_PATH)
    sources.add_path(db, TMP / "Projects")
    test_clean_url()
    test_profiles()
    test_firefox_collector(db, layer, call)
    test_spans()
    test_sampler(db, call)
    test_extension()
    test_contradictions(db, call)
    test_metrics(db, call)
    db.close()
    shutil.rmtree(TMP)


if __name__ == "__main__":
    main()
