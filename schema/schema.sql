-- Personal Work Intelligence layer: SQLite schema (schema version 6).
-- A store made by an older version is upgraded by the files in migrations/.
--
-- Times are UTC text, 'YYYY-MM-DDTHH:MM:SSZ'. Ids that come from a source are
-- natural keys (git:commit:<sha>), so re-reading a source updates rows instead
-- of duplicating them. The service must run `PRAGMA foreign_keys = ON` on every
-- connection; SQLite doesn't remember it.
--
-- Read tools query only the *_for_claude views, which apply the allowlist,
-- confidential labels and retraction in one place. See README.md for the rules.

PRAGMA journal_mode = WAL;

CREATE TABLE schema_version (version INTEGER NOT NULL) STRICT;
INSERT INTO schema_version VALUES (6);

-- Sources: each allowlisted repository, folder or profile ------------------

CREATE TABLE sources (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN
                    ('git_repo', 'claude_code', 'firefox', 'app_usage', 'calendar', 'notes_folder', 'recorder')),
    locator     TEXT NOT NULL,                  -- repo path, ~/.claude/projects, Firefox profile, folder
    name        TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),  -- the allowlist switch
    cursor      TEXT,                           -- collector's incremental position (last visit id, last scan)
    added_at    TEXT NOT NULL,
    UNIQUE (kind, locator)
) STRICT;

-- One row per collection pass: freshness, lag, duplication and gaps come from here.
CREATE TABLE collector_runs (
    id          INTEGER PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    trigger     TEXT NOT NULL CHECK (trigger IN ('schedule', 'stale_read', 'catch_up', 'manual')),
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL CHECK (status IN ('running', 'ok', 'error')),
    seen        INTEGER NOT NULL DEFAULT 0,     -- records read
    inserted    INTEGER NOT NULL DEFAULT 0,     -- new events
    changed     INTEGER NOT NULL DEFAULT 0,     -- re-read with different content (corrections)
    unchanged   INTEGER NOT NULL DEFAULT 0,     -- re-read, identical (duplicates avoided)
    gone        INTEGER NOT NULL DEFAULT 0,     -- source records that disappeared
    error       TEXT
) STRICT;
CREATE INDEX collector_runs_by_source ON collector_runs (source_id, started_at);

-- Projects: the same work across repos, sessions, tasks and meetings --------

CREATE TABLE projects (
    id          TEXT PRIMARY KEY,               -- short slug, e.g. 'pwi'
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'done')),
    created_at  TEXT NOT NULL
) STRICT;

-- Rule-based linking: an event whose repo, cwd or page matches an alias belongs to that project.
-- The online kinds tell Claude where the project lives in each connector: a Notion page or
-- database, a Drive folder, a Gmail search, a Google Chat space, a calendar keyword.
CREATE TABLE project_aliases (
    kind        TEXT NOT NULL CHECK (kind IN
                    ('repo_path', 'git_remote', 'github_repo', 'claude_code_cwd', 'notion', 'calendar_match',
                     'drive_folder', 'gmail_query', 'chat_space')),
    value       TEXT NOT NULL,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    method      TEXT NOT NULL CHECK (method IN ('rule', 'claude', 'me')),
    created_at  TEXT NOT NULL,
    PRIMARY KEY (kind, value)                   -- an alias points at exactly one project
) STRICT;

-- Online sources, read live by Claude through its connectors; the layer keeps no copy.
-- The allowlist for them: Claude uses a connector only when it's on, and only within
-- its scope (free text such as "label:work" or "the Engineering teamspace"), plus each
-- project's aliases. Default deny: Gmail, Chat and Drive start off.
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

-- Episodic memory: local events --------------------------------------------

CREATE TABLE events (
    seq            INTEGER PRIMARY KEY,         -- stable rowid for the search index
    id             TEXT NOT NULL UNIQUE,        -- natural key, see README "Event ids and types"
    source_id      INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    type           TEXT NOT NULL,               -- git.commit, git.push, claude_code.session, ...
    actor          TEXT NOT NULL DEFAULT 'me',  -- 'me', or a colleague's email or handle
    project_id     TEXT REFERENCES projects(id) ON DELETE SET NULL,
    occurred_at    TEXT NOT NULL CHECK (occurred_at GLOB
                       '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    utc_offset_min INTEGER NOT NULL,            -- local offset when it happened
    local_day      TEXT GENERATED ALWAYS AS (date(occurred_at, utc_offset_min || ' minutes')) STORED,
    ended_at       TEXT,                        -- intervals: sessions, focus spans, recordings
    observed_at    TEXT NOT NULL,               -- first time the layer saw it
    changed_at     TEXT,                        -- last re-read that found different content
    gone_at        TEXT,                        -- source record disappeared (rebased away, session file deleted)
    title          TEXT,                        -- short and redacted: commit subject, session title
    payload        TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload)),  -- redacted metadata only
    payload_ref    TEXT,                        -- where the original lives: <repo path>@<sha>, session file
    content_hash   TEXT NOT NULL                -- of title + payload: tells corrections from repeats
) STRICT;
CREATE INDEX events_by_day ON events (local_day, occurred_at);
CREATE INDEX events_by_project ON events (project_id, occurred_at);
CREATE INDEX events_by_source ON events (source_id, occurred_at);

-- Things events and claims are about: branches, PRs, Notion tasks, documents, messages.
-- Online artifacts are references only (id, title, url); the layer never copies their content.
CREATE TABLE artifacts (
    seq           INTEGER PRIMARY KEY,
    id            TEXT NOT NULL UNIQUE,         -- git:branch:<repo>:<name>, github:pr:<owner/repo>#<n>, notion:<page id>
    kind          TEXT NOT NULL CHECK (kind IN
                      ('branch', 'file', 'pull_request', 'release', 'work_item', 'document',
                       'message', 'calendar_event', 'web_page')),
    title         TEXT,
    url           TEXT,
    project_id    TEXT REFERENCES projects(id) ON DELETE SET NULL,
    first_seen_at TEXT NOT NULL
) STRICT;

-- Evidence: one reading of a local event or an online artifact -----------

CREATE TABLE evidence (
    id             INTEGER PRIMARY KEY,
    event_id       TEXT REFERENCES events(id) ON DELETE SET NULL,
    artifact_id    TEXT REFERENCES artifacts(id) ON DELETE SET NULL,
    locator        TEXT,                        -- finer pointer: message id in a thread, line range in a session
    read_at        TEXT,                        -- online: when Claude read it
    source_version TEXT,                        -- online: revision or last-edited time seen, for "source changed"
    expired_at     TEXT,                        -- when the local event behind it was removed
    created_at     TEXT NOT NULL,
    CHECK (event_id IS NOT NULL OR artifact_id IS NOT NULL OR expired_at IS NOT NULL)
) STRICT;
CREATE INDEX evidence_by_event ON evidence (event_id);

-- When retention or I remove an event, the evidence row stays with event_id cleared,
-- so Claude can say a confirmed claim's evidence has expired. Runs before the
-- foreign key's SET NULL, so the CHECK above still holds.
CREATE TRIGGER evidence_expire BEFORE DELETE ON events BEGIN
    UPDATE evidence SET expired_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE event_id = OLD.id;
END;

-- Semantic and prospective memory: claims ----------------------------------

CREATE TABLE claims (
    id          TEXT PRIMARY KEY,               -- 'clm_' + random
    type        TEXT NOT NULL CHECK (type IN ('decision', 'commitment', 'blocker', 'fact', 'session_note')),
                                                -- the type first proposed; each version has its current one
    created_at  TEXT NOT NULL
) STRICT;

-- Append-only: every correction and every status change is a new version.
CREATE TABLE claim_versions (
    seq         INTEGER PRIMARY KEY,
    claim_id    TEXT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL CHECK (version >= 1),
    status      TEXT NOT NULL CHECK (status IN ('proposed', 'supported', 'disputed', 'superseded', 'retracted')),
    text        TEXT NOT NULL,
    project_id  TEXT REFERENCES projects(id) ON DELETE SET NULL,
    about_day   TEXT,                           -- the workday it's about: when decided, the session note's day
    due_at      TEXT,                           -- commitments and deadlines
    owner       TEXT,                           -- commitments: 'me', or a colleague's email or handle
    confidence  REAL CHECK (confidence BETWEEN 0 AND 1),
    method      TEXT NOT NULL CHECK (method IN ('rule', 'claude', 'me')),     -- how the content was extracted
    changed_by  TEXT NOT NULL CHECK (changed_by IN ('rule', 'claude', 'me')), -- who made this version
    reason      TEXT,                           -- 'correction', 'confirmed in review', ...
    created_at  TEXT NOT NULL,
    type        TEXT CHECK (type IS NULL OR type IN ('decision', 'commitment', 'blocker', 'fact', 'session_note')),  -- NULL: as in claims.type
    UNIQUE (claim_id, version),
    CHECK (status <> 'supported' OR changed_by = 'me')   -- only I can verify a claim
) STRICT;
CREATE INDEX claim_versions_by_project ON claim_versions (project_id, claim_id);

CREATE TRIGGER claim_versions_numbered BEFORE INSERT ON claim_versions
WHEN NEW.version <> COALESCE((SELECT MAX(version) FROM claim_versions WHERE claim_id = NEW.claim_id), 0) + 1
BEGIN
    SELECT RAISE(ABORT, 'claim versions must be numbered 1, 2, 3, ... with no gaps');
END;

CREATE TRIGGER claim_versions_append_only BEFORE UPDATE ON claim_versions
BEGIN
    SELECT RAISE(ABORT, 'claim versions are append-only; add a new version instead');
END;

CREATE TABLE claim_evidence (
    claim_id    TEXT NOT NULL,
    version     INTEGER NOT NULL,
    evidence_id INTEGER NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    PRIMARY KEY (claim_id, version, evidence_id),
    FOREIGN KEY (claim_id, version) REFERENCES claim_versions (claim_id, version) ON DELETE CASCADE
) STRICT;

CREATE VIEW current_claims AS
SELECT c.id, COALESCE(v.type, c.type) AS type, c.type AS proposed_type, c.created_at AS first_proposed_at,
       v.version, v.status, v.text, v.project_id, v.about_day, v.due_at, v.owner,
       v.confidence, v.method, v.changed_by, v.reason, v.created_at AS version_at, v.seq
FROM claims c
JOIN claim_versions v ON v.claim_id = c.id
WHERE v.version = (SELECT MAX(version) FROM claim_versions WHERE claim_id = c.id);

-- Links between any two items: cross-source work, contradictions, supersession --

CREATE TABLE links (
    from_type   TEXT NOT NULL CHECK (from_type IN ('event', 'artifact', 'claim', 'project')),
    from_id     TEXT NOT NULL,
    rel         TEXT NOT NULL CHECK (rel IN ('related', 'part_of', 'contradicts', 'supersedes', 'duplicates')),
    to_type     TEXT NOT NULL CHECK (to_type IN ('event', 'artifact', 'claim', 'project')),
    to_id       TEXT NOT NULL,
    method      TEXT NOT NULL CHECK (method IN ('rule', 'claude', 'me')),
    created_at  TEXT NOT NULL,
    PRIMARY KEY (from_type, from_id, rel, to_type, to_id)
) STRICT;
CREATE INDEX links_to ON links (to_type, to_id);

-- Confidential labels ------------------------------------------------------

-- A label on a source or project covers everything in it. Removing a label means
-- deleting its row, which only the frontend does.
CREATE TABLE labels (
    item_type   TEXT NOT NULL CHECK (item_type IN ('source', 'project', 'event', 'artifact', 'claim')),
    item_id     TEXT NOT NULL,                  -- sources.id as text
    label       TEXT NOT NULL CHECK (label = 'confidential'),
    set_by      TEXT NOT NULL CHECK (set_by IN ('claude', 'me')),   -- claude only with my approval
    set_at      TEXT NOT NULL,
    PRIMARY KEY (item_type, item_id, label)
) STRICT;

-- Polymorphic rows in links and labels have no foreign keys, so clean them up here.
CREATE TRIGGER events_cleanup AFTER DELETE ON events BEGIN
    DELETE FROM links WHERE (from_type = 'event' AND from_id = OLD.id) OR (to_type = 'event' AND to_id = OLD.id);
    DELETE FROM labels WHERE item_type = 'event' AND item_id = OLD.id;
END;
CREATE TRIGGER artifacts_cleanup AFTER DELETE ON artifacts BEGIN
    DELETE FROM links WHERE (from_type = 'artifact' AND from_id = OLD.id) OR (to_type = 'artifact' AND to_id = OLD.id);
    DELETE FROM labels WHERE item_type = 'artifact' AND item_id = OLD.id;
END;
CREATE TRIGGER claims_cleanup AFTER DELETE ON claims BEGIN
    DELETE FROM links WHERE (from_type = 'claim' AND from_id = OLD.id) OR (to_type = 'claim' AND to_id = OLD.id);
    DELETE FROM labels WHERE item_type = 'claim' AND item_id = OLD.id;
END;
CREATE TRIGGER projects_cleanup AFTER DELETE ON projects BEGIN
    DELETE FROM links WHERE (from_type = 'project' AND from_id = OLD.id) OR (to_type = 'project' AND to_id = OLD.id);
    DELETE FROM labels WHERE item_type = 'project' AND item_id = OLD.id;
END;
CREATE TRIGGER sources_cleanup AFTER DELETE ON sources BEGIN
    DELETE FROM labels WHERE item_type = 'source' AND item_id = CAST(OLD.id AS TEXT);
END;

-- What Claude may see ------------------------------------------------------

CREATE VIEW confidential_events AS
SELECT e.id FROM events e
WHERE EXISTS (SELECT 1 FROM labels l WHERE
          (l.item_type = 'event'   AND l.item_id = e.id) OR
          (l.item_type = 'source'  AND l.item_id = CAST(e.source_id AS TEXT)) OR
          (l.item_type = 'project' AND l.item_id = e.project_id));

CREATE VIEW events_for_claude AS
SELECT e.* FROM events e
JOIN sources s ON s.id = e.source_id
WHERE s.enabled = 1
  AND e.id NOT IN (SELECT id FROM confidential_events);

-- A claim is hidden if it, its project, or any evidence of its current version is confidential.
CREATE VIEW claims_for_claude AS
SELECT cc.* FROM current_claims cc
WHERE cc.status <> 'retracted'
  AND NOT EXISTS (SELECT 1 FROM labels l WHERE
          (l.item_type = 'claim'   AND l.item_id = cc.id) OR
          (l.item_type = 'project' AND l.item_id = cc.project_id))
  AND NOT EXISTS (SELECT 1 FROM claim_evidence ce JOIN evidence ev ON ev.id = ce.evidence_id
                  WHERE ce.claim_id = cc.id AND ce.version = cc.version
                    AND (ev.event_id IN (SELECT id FROM confidential_events)
                         OR EXISTS (SELECT 1 FROM labels l
                                    WHERE l.item_type = 'artifact' AND l.item_id = ev.artifact_id)));

-- Keyword search -----------------------------------------------------------
-- FTS5 tables keyed on the stable seq columns. Every claim version is indexed;
-- search joins current_claims so only current text matches. Diacritics are
-- folded, so 'decisao' finds 'decisão'.
--
-- events_fts keeps its own copy of an event's searchable text: the title, plus
-- `details` from the payload (a commit's redacted message body and file paths,
-- a push's branch, a Firefox visit's address, an app span's app), because the
-- reasons behind a change are usually in the body.

CREATE VIRTUAL TABLE events_fts USING fts5 (
    title, details, tokenize = 'unicode61 remove_diacritics 2');
CREATE TRIGGER events_fts_insert AFTER INSERT ON events BEGIN
    INSERT INTO events_fts (rowid, title, details) VALUES (NEW.seq, NEW.title,
        COALESCE(json_extract(NEW.payload, '$.body'), '') || ' ' || COALESCE(json_extract(NEW.payload, '$.branch'), '')
        || ' ' || COALESCE((SELECT group_concat(value, ' ') FROM json_each(NEW.payload, '$.files')), '')
        || ' ' || COALESCE(json_extract(NEW.payload, '$.url'), '') || ' ' || COALESCE(json_extract(NEW.payload, '$.app'), ''));
END;
CREATE TRIGGER events_fts_delete AFTER DELETE ON events BEGIN
    DELETE FROM events_fts WHERE rowid = OLD.seq;
END;
CREATE TRIGGER events_fts_update AFTER UPDATE OF title, payload ON events BEGIN
    DELETE FROM events_fts WHERE rowid = OLD.seq;
    INSERT INTO events_fts (rowid, title, details) VALUES (NEW.seq, NEW.title,
        COALESCE(json_extract(NEW.payload, '$.body'), '') || ' ' || COALESCE(json_extract(NEW.payload, '$.branch'), '')
        || ' ' || COALESCE((SELECT group_concat(value, ' ') FROM json_each(NEW.payload, '$.files')), '')
        || ' ' || COALESCE(json_extract(NEW.payload, '$.url'), '') || ' ' || COALESCE(json_extract(NEW.payload, '$.app'), ''));
END;

CREATE VIRTUAL TABLE claims_fts USING fts5 (
    text, content = 'claim_versions', content_rowid = 'seq', tokenize = 'unicode61 remove_diacritics 2');
CREATE TRIGGER claims_fts_insert AFTER INSERT ON claim_versions BEGIN
    INSERT INTO claims_fts (rowid, text) VALUES (NEW.seq, NEW.text);
END;
CREATE TRIGGER claims_fts_delete AFTER DELETE ON claim_versions BEGIN
    INSERT INTO claims_fts (claims_fts, rowid, text) VALUES ('delete', OLD.seq, OLD.text);
END;

CREATE VIRTUAL TABLE artifacts_fts USING fts5 (
    title, content = 'artifacts', content_rowid = 'seq', tokenize = 'unicode61 remove_diacritics 2');
CREATE TRIGGER artifacts_fts_insert AFTER INSERT ON artifacts BEGIN
    INSERT INTO artifacts_fts (rowid, title) VALUES (NEW.seq, NEW.title);
END;
CREATE TRIGGER artifacts_fts_delete AFTER DELETE ON artifacts BEGIN
    INSERT INTO artifacts_fts (artifacts_fts, rowid, title) VALUES ('delete', OLD.seq, OLD.title);
END;
CREATE TRIGGER artifacts_fts_update AFTER UPDATE OF title ON artifacts BEGIN
    INSERT INTO artifacts_fts (artifacts_fts, rowid, title) VALUES ('delete', OLD.seq, OLD.title);
    INSERT INTO artifacts_fts (rowid, title) VALUES (NEW.seq, NEW.title);
END;

-- Settings -----------------------------------------------------------------

-- My choices that aren't an allowlist: 'app_usage.mode' is titles, apps or time.
CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    changed_at  TEXT NOT NULL
) STRICT;

-- Retention and audit ------------------------------------------------------

-- Days to keep each kind of data; NULL keeps it until I delete it.
CREATE TABLE retention (
    item_type   TEXT PRIMARY KEY CHECK (item_type IN
                    ('git_repo', 'claude_code', 'firefox', 'app_usage', 'calendar', 'notes_folder',
                     'session_note', 'transcript', 'unconfirmed_claim', 'confirmed_claim', 'audio', 'audit')),
    days        INTEGER CHECK (days IS NULL OR days > 0)
) STRICT;
INSERT INTO retention (item_type, days) VALUES
    ('git_repo', 90), ('claude_code', 90), ('firefox', 90), ('app_usage', 90), ('calendar', 90),
    ('notes_folder', 90), ('session_note', 90), ('transcript', 90), ('unconfirmed_claim', 90),
    ('confirmed_claim', NULL), ('audio', 30), ('audit', 90);

-- What was collected, changed or deleted, and when. Ids and counts only, never content.
CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL,
    actor       TEXT NOT NULL CHECK (actor IN ('collector', 'claude', 'me', 'retention')),
    action      TEXT NOT NULL CHECK (action IN
                    ('collect', 'propose', 'revise', 'set_status', 'label', 'unlabel', 'link',
                     'delete', 'expire', 'settings', 'read_confidential')),
    item_type   TEXT NOT NULL,
    item_id     TEXT,
    count       INTEGER NOT NULL DEFAULT 1
) STRICT;
CREATE INDEX audit_log_by_time ON audit_log (at);
