-- Schema 3 -> 4: online sources (Phase 2). Adds the connectors allowlist, and project
-- aliases for Drive folders, Gmail searches and Google Chat spaces. SQLite can't change
-- a CHECK in place, so project_aliases is rebuilt with its rows. store.py runs this in
-- one transaction and backs the store up first.

CREATE TABLE project_aliases_v4 (
    kind        TEXT NOT NULL CHECK (kind IN
                    ('repo_path', 'git_remote', 'github_repo', 'claude_code_cwd', 'notion', 'calendar_match',
                     'drive_folder', 'gmail_query', 'chat_space')),
    value       TEXT NOT NULL,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    method      TEXT NOT NULL CHECK (method IN ('rule', 'claude', 'me')),
    created_at  TEXT NOT NULL,
    PRIMARY KEY (kind, value)
) STRICT;
INSERT INTO project_aliases_v4 SELECT * FROM project_aliases;
DROP TABLE project_aliases;
ALTER TABLE project_aliases_v4 RENAME TO project_aliases;

CREATE TABLE connectors (
    provider    TEXT PRIMARY KEY CHECK (provider IN
                    ('github', 'google_calendar', 'notion', 'gmail', 'google_chat', 'google_drive')),
    enabled     INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    scope       TEXT,
    changed_at  TEXT NOT NULL
) STRICT;
INSERT INTO connectors (provider, enabled, changed_at) VALUES
    ('github', 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')), ('google_calendar', 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('notion', 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')), ('gmail', 0, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('google_chat', 0, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')), ('google_drive', 0, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));

UPDATE schema_version SET version = 4;
