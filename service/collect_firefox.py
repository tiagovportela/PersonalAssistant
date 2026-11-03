"""Firefox collector: the pages I visited, from a copy of the profile's history.

Firefox locks places.sqlite while it runs, so each pass copies it (and its
write-ahead log) into the service's owner-only runtime folder, reads the copy
and deletes it. Firefox history is the one source read in full, without an
allowlist (brief §10), so what's stored is cut down instead:

- Only http and https pages I opened (a link, a typed address, a bookmark),
  not embedded frames, downloads, reloads or hidden redirect steps.
- Never local addresses (localhost, 127.0.0.1): that's the frontend, with its
  login code, and local dev servers.
- URL parameters that look like secrets (token, code, key, password,
  session, signature…) and tracking parameters are removed, as are user
  names and passwords in the address, long random path parts, and fragments
  that carry parameters. Titles are redacted like every other title.

A visit to a project's GitHub repository, Notion page or Drive folder (its
aliases) is linked to that project. A visit I delete from Firefox's history is
marked gone at the next pass, and Claude stops seeing it.
"""

import configparser
import json
import re
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import paths
import store
from batch import Batch, CollectorError
from redact import MARK, redact

# Where Firefox keeps profiles on Ubuntu: the snap (the default), the newer XDG folder,
# the classic folder, and the Flatpak.
ROOTS = ["snap/firefox/common/.mozilla/firefox", ".config/mozilla/firefox", ".mozilla/firefox",
         ".var/app/org.mozilla.firefox/.mozilla/firefox"]
HOW = {1: "link", 2: "typed", 3: "bookmark", 5: "redirect", 6: "redirect"}  # moz_historyvisits.visit_type
RECHECK = 86400  # seconds of recent visits read again each pass: a page's title often arrives after the visit
MAX_TITLE = 300

VISITS_SQL = f"""
SELECT v.id, v.visit_date, v.visit_type, p.url, p.title, p.guid
FROM moz_historyvisits v JOIN moz_places p ON p.id = v.place_id
WHERE v.visit_date >= ? AND v.visit_type IN ({', '.join(str(t) for t in HOW)}) AND p.hidden = 0
ORDER BY v.visit_date
"""


# Finding the profile -----------------------------------------------------------

def profiles(home=None):
    """Firefox profiles with a history database, most recently used first: [(path, name)]."""
    home = Path(home or Path.home())
    found = []
    for root in (home / r for r in ROOTS):
        ini = root / "profiles.ini"
        if not ini.is_file():
            continue
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        try:
            parser.read(ini, encoding="utf-8")
        except configparser.Error:
            continue
        # The [Install…] section names the profile this Firefox opens by default.
        preferred = {parser[s].get("Default") for s in parser.sections() if s.startswith("Install")}
        for section in parser.sections():
            if not section.startswith("Profile") or "Path" not in parser[section]:
                continue
            p = parser[section]
            path = (root / p["Path"]) if p.get("IsRelative", "1") == "1" else Path(p["Path"])
            if (path / "places.sqlite").is_file():
                default = p["Path"] in preferred or (not preferred and p.get("Default") == "1")
                found.append((default, (path / "places.sqlite").stat().st_mtime, path, p.get("Name") or path.name))
    found.sort(key=lambda f: (f[0], f[1]), reverse=True)
    return [(path, name) for _, _, path, name in found]


def default_profile(home=None):
    found = profiles(home)
    return found[0] if found else None


# Cleaning addresses --------------------------------------------------------------

# A parameter is dropped when a part of its name starts with one of these, or its whole
# name contains one of SECRET_INSIDE. It errs towards dropping: "keyword" goes too.
SECRET_STARTS = ("token", "code", "key", "pass", "pwd", "secret", "session", "sess", "sid", "auth", "sig",
                 "credential", "cred", "otp", "nonce", "ticket", "jwt", "saml", "csrf", "xsrf", "cookie", "state",
                 "hash", "hmac", "apikey", "access", "refresh", "bearer", "login", "private", "pin")
SECRET_INSIDE = ("token", "secret", "password", "passwd", "apikey", "accesskey", "signature", "credential",
                 "session", "sessid", "auth")
TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|dclid|gbraid|wbraid|msclkid|yclid|mc_cid|mc_eid|_hsenc|_hsmi|igshid)$")
LOOPBACK = re.compile(r"^(localhost|.*\.localhost|127(\.\d+){3}|0\.0\.0\.0|\[?::1\]?)$")
TOKEN_LIKE = re.compile(r"^[A-Za-z0-9_\-.~+/=%]{32,}$")


def mixed(part):
    return any(c.isdigit() for c in part) and any(c.isupper() for c in part) and any(c.islower() for c in part)


def random_looking(value, length=48):
    """A token: long, few separators, and a long run mixing upper and lower case letters and digits. Not a
    word, a slug such as Some-Product-Name-V2-32GB, or a lowercase hex id like a commit or a Notion page."""
    return (len(value) >= length and bool(TOKEN_LIKE.match(value)) and sum(value.count(c) for c in "-_.") <= 3
            and any(len(part) >= 16 and mixed(part) for part in re.split(r"[-_.]", value)))


def secret_name(name):
    name = name.lower()
    parts = [p for p in re.split(r"[^a-z0-9]+", name) if p]
    joined = "".join(parts)
    return any(p.startswith(SECRET_STARTS) for p in parts) or any(s in joined for s in SECRET_INSIDE)


def clean_params(text, depth):
    """A query string without its secret-looking or tracking parameters. A parameter holding a whole
    address (continue=, redirect_uri=) is cleaned the same way, and dropped if it's a local one."""
    kept = []
    for name, value in parse_qsl(text, keep_blank_values=True):
        if secret_name(name) or TRACKING.match(name.lower()):
            continue
        if re.match(r"(?i)https?://", value):
            value = clean_url(value, depth + 1) if depth < 3 else None
            if value is None:
                continue
        elif redact(value) != value or random_looking(value):
            continue
        kept.append((name, value))
    return urlencode(kept)


def clean_url(url, depth=0):
    """The address as stored, or None for one that isn't stored at all."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host or LOOPBACK.match(host):
        return None
    netloc = (host + (f":{port}" if port else "")) if parts.username or parts.password else parts.netloc
    path = "/".join(MARK if random_looking(segment, 32) else segment for segment in parts.path.split("/"))
    fragment = parts.fragment
    if "=" in fragment or "&" in fragment:  # parameters in the fragment, e.g. an OAuth access_token
        fragment = clean_params(fragment, depth)
    elif len(fragment) > 100 or redact(fragment) != fragment or random_looking(fragment, 32):
        fragment = ""
    return redact(urlunsplit((parts.scheme, netloc, path, clean_params(parts.query, depth), fragment)))


# Linking to projects ---------------------------------------------------------------

def project_matchers(db):
    """(kind, value, project) for the aliases that point at web pages: a GitHub repository (owner/repo),
    a Notion page id, or a Drive folder id."""
    matchers = []
    for a in db.execute("SELECT kind, value, project_id FROM project_aliases WHERE kind IN"
                        " ('github_repo', 'notion', 'drive_folder') ORDER BY kind, value"):
        if a["kind"] == "github_repo":
            matchers.append(("github", a["value"].lower().strip("/"), a["project_id"]))
        elif a["kind"] == "notion":
            matchers += [("id", page, a["project_id"]) for page in re.findall(r"[0-9a-f]{32}", a["value"].replace("-", "").lower())]
        else:
            folders = re.findall(r"folders/([\w-]{10,})", a["value"]) or re.findall(r"^[\w-]{20,}$", a["value"].strip())
            matchers += [("id", folder, a["project_id"]) for folder in folders]
    return matchers


def project_for(matchers, url):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    repo = "/".join(parts.path.lower().strip("/").split("/")[:2])
    flat = (parts.path + "?" + parts.query).replace("-", "").lower()
    for kind, value, project in matchers:
        if kind == "github" and host in ("github.com", "www.github.com") and repo == value:
            return project
        if kind == "id" and value.replace("-", "").lower() in flat:
            return project
    return None


# Collecting --------------------------------------------------------------------------

def stamp(profile):
    out = []
    for name in ("places.sqlite", "places.sqlite-wal"):
        try:
            s = (profile / name).stat()
            out.append([s.st_size, s.st_mtime_ns])
        except FileNotFoundError:
            out.append(None)
    return out


def read_copy(profile, since_us):
    """The visits since a time, read from a fresh copy of the history database."""
    paths.RUNTIME_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    for attempt in range(2):
        with tempfile.TemporaryDirectory(prefix="firefox-", dir=paths.RUNTIME_DIR) as tmp:
            for name in ("places.sqlite", "places.sqlite-wal"):
                if (profile / name).exists():
                    shutil.copyfile(profile / name, Path(tmp) / name)
            db = sqlite3.connect(Path(tmp) / "places.sqlite")
            try:
                return db.execute(VISITS_SQL, (since_us,)).fetchall()
            except sqlite3.DatabaseError:
                if attempt:  # Firefox wrote to it while it was being copied, twice
                    raise CollectorError("Firefox's history couldn't be read (it was being written). "
                                         "It's tried again at the next pass.") from None
            finally:
                db.close()
        time.sleep(1)


def collect(db, source, since):
    profile = Path(source["locator"])
    if not (profile / "places.sqlite").is_file():
        raise CollectorError(f"There's no Firefox history in {profile}. If Firefox uses another profile now, "
                             "add it again with: pwi add-firefox")
    cursor = json.loads(source["cursor"] or "{}")
    files = stamp(profile)
    matchers = [list(m) for m in project_matchers(db)]
    if cursor.get("files") == files and cursor.get("aliases") == matchers:
        return Batch(cached=cursor.get("visits", 0))  # Firefox hasn't written anything since the last pass
    # New project aliases can link older visits, so then every visit is read again.
    recheck_from = cursor.get("newest", 0) - RECHECK if cursor.get("aliases") == matchers else 0
    stored = {r["id"] for r in db.execute("SELECT id FROM events WHERE source_id = ? AND type = 'firefox.visit'"
                                          " AND gone_at IS NULL AND occurred_at >= ?", (source["id"], store.utc(since)))}
    batch = Batch()
    present, newest = set(), cursor.get("newest", 0)
    for visit_id, visit_us, visit_type, url, title, guid in read_copy(profile, since * 1_000_000):
        clean = clean_url(url)
        if clean is None:
            continue
        event_id = f"firefox:visit:{guid}:{visit_us}"
        present.add(event_id)
        at = visit_us // 1_000_000
        newest = max(newest, at)
        # Older visits already stored are skipped; ones Firefox Sync brought in late are still read.
        if at < recheck_from and event_id in stored:
            batch.cached += 1
            continue
        batch.events.append({
            "id": event_id,
            "type": "firefox.visit",
            "project_id": project_for(matchers, clean),
            "occurred_at": store.utc(at),
            "utc_offset_min": store.local_offset_min(at),
            "title": redact(title.strip())[:MAX_TITLE] if title and title.strip() else None,
            "payload": {"url": clean, "site": urlsplit(clean).hostname, "how": HOW[visit_type]},
        })
    batch.gone_ids = sorted(stored - present)
    batch.cursor = json.dumps({"files": files, "aliases": matchers, "newest": newest, "visits": len(present)})
    return batch
