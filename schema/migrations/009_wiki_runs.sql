-- Schema 8 -> 9: the wiki's compile runs (docs/knowledge_wiki.md), kept like the end-of-day agent's runs.
-- store.py runs this in one transaction and backs the store up first.

-- The wiki's compile runs: one headless Claude run per page, after the end-of-day agent or when I
-- ask (service/wiki_compile.py). Kept like the agent's runs: which page and why, never its content.
CREATE TABLE wiki_runs (
    id             INTEGER PRIMARY KEY,
    page_id        TEXT NOT NULL,               -- no foreign key: a project's page may not be written yet
    reason         TEXT NOT NULL,               -- why it was picked: stale and why, not written yet, asked
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    status         TEXT NOT NULL CHECK (status IN ('running', 'ok', 'failed')),
    version_before INTEGER NOT NULL DEFAULT 0,
    version_after  INTEGER,
    detail         TEXT                         -- turns and duration, or the error
) STRICT;
CREATE INDEX wiki_runs_by_page ON wiki_runs (page_id, started_at);

UPDATE schema_version SET version = 9;
