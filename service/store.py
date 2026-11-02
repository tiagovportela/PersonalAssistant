"""Opens the layer's SQLite store, creating it from schema/schema.sql on first start."""

import os
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "schema.sql"
SCHEMA_VERSION = 1


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
