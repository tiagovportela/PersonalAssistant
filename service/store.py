"""Opens the layer's SQLite store, creating it from schema/schema.sql on first start."""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "schema.sql"
SCHEMA_VERSION = 1

# The one way events are written: re-reading a record never duplicates it, and only
# a real content change (a correction, a session that grew) touches the row.
UPSERT_EVENT = """
INSERT INTO events (id, source_id, type, actor, project_id, occurred_at, utc_offset_min, ended_at, observed_at,
                    title, payload, payload_ref, content_hash)
VALUES (:id, :source_id, :type, :actor, :project_id, :occurred_at, :utc_offset_min, :ended_at, :observed_at,
        :title, :payload, :payload_ref, :content_hash)
ON CONFLICT (id) DO UPDATE SET
    actor = excluded.actor, title = excluded.title, payload = excluded.payload, payload_ref = excluded.payload_ref,
    project_id = excluded.project_id, occurred_at = excluded.occurred_at, ended_at = excluded.ended_at,
    utc_offset_min = excluded.utc_offset_min, content_hash = excluded.content_hash,
    changed_at = excluded.observed_at, gone_at = NULL
WHERE events.content_hash <> excluded.content_hash OR events.gone_at IS NOT NULL
"""


def utc(ts):
    """A Unix time as the store's UTC text, YYYY-MM-DDTHH:MM:SSZ."""
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now():
    return utc(datetime.now(timezone.utc).timestamp())


def local_offset_min(ts):
    """This machine's UTC offset, in minutes, at a Unix time (DST-aware)."""
    return int(datetime.fromtimestamp(ts, timezone.utc).astimezone().utcoffset().total_seconds() // 60)


def connect(path):
    db = sqlite3.connect(path, isolation_level=None, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")  # SQLite doesn't remember it per database
    return db


def create_or_check(path):
    """Creates the store if it's missing, then checks it has the schema version this code expects."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    if not path.exists():
        # Built under another name and renamed, so a failed first start never leaves a half-made store.
        new = path.with_name(path.name + ".new")
        new.unlink(missing_ok=True)
        db = connect(new)
        try:
            db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        finally:
            db.close()
        os.chmod(new, 0o600)
        new.replace(path)
    db = connect(path)
    try:
        version = db.execute("SELECT version FROM schema_version").fetchone()[0]
    finally:
        db.close()
    if version != SCHEMA_VERSION:
        raise RuntimeError(f"{path} has schema version {version}, but this code expects {SCHEMA_VERSION}")
