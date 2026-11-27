-- Schema 7 -> 8: the knowledge wiki (docs/knowledge_wiki.md): pages, their versions, sections,
-- statements, citations and links; my notes on a page; searches that found nothing; and their search
-- indexes. The audit trail can record what read_repo read, and retention covers past wiki versions and
-- search misses. SQLite can't change a CHECK in place, so audit_log and retention are rebuilt with their
-- rows. store.py runs this in one transaction and backs the store up first.

-- The knowledge wiki (docs/knowledge_wiki.md) ------------------------------
-- One page per project, person and recurring topic. Claude writes a page's compiled sections
-- through propose_wiki_update, and every version is kept. A section is a list of statements;
-- each statement cites claims, events, commits (or a file at a commit) and other pages. Labels
-- aren't stored: the layer works them out from the citations each time a page is read, and
-- hides a statement whose evidence is gone or confidential.

CREATE TABLE wiki_pages (
    id          TEXT PRIMARY KEY,               -- a slug: the project's id, or one made from the title
    kind        TEXT NOT NULL CHECK (kind IN ('project', 'person', 'topic')),
    title       TEXT NOT NULL,
    project_id  TEXT UNIQUE REFERENCES projects(id) ON DELETE CASCADE,  -- project pages
    email       TEXT UNIQUE,                    -- person pages, lower case
    created_at  TEXT NOT NULL,
    CHECK ((kind = 'project') = (project_id IS NOT NULL)),
    CHECK ((kind = 'person') = (email IS NOT NULL))
) STRICT;

-- Append-only, like claim versions. built_from: {"<source id>": "<commit>"}, the repositories read.
CREATE TABLE wiki_versions (
    seq         INTEGER PRIMARY KEY,            -- stable rowid for the search index
    page_id     TEXT NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL CHECK (version >= 1),
    summary     TEXT,
    key_terms   TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(key_terms)),
    built_from  TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(built_from)),
    written_by  TEXT NOT NULL CHECK (written_by IN ('claude', 'me')),
    reason      TEXT,
    written_at  TEXT NOT NULL,
    UNIQUE (page_id, version)
) STRICT;

CREATE TRIGGER wiki_versions_numbered BEFORE INSERT ON wiki_versions
WHEN NEW.version <> COALESCE((SELECT MAX(version) FROM wiki_versions WHERE page_id = NEW.page_id), 0) + 1
BEGIN
    SELECT RAISE(ABORT, 'wiki versions must be numbered 1, 2, 3, ... with no gaps');
END;

CREATE TRIGGER wiki_versions_append_only BEFORE UPDATE ON wiki_versions
BEGIN
    SELECT RAISE(ABORT, 'wiki versions are append-only; add a new version instead');
END;

CREATE VIEW wiki_current AS
SELECT v.* FROM wiki_versions v
WHERE v.version = (SELECT MAX(version) FROM wiki_versions WHERE page_id = v.page_id);

CREATE TABLE wiki_sections (
    seq         INTEGER PRIMARY KEY,
    page_id     TEXT NOT NULL,
    version     INTEGER NOT NULL,
    section_id  TEXT NOT NULL,
    position    INTEGER NOT NULL,
    heading     TEXT NOT NULL,
    summary     TEXT,
    UNIQUE (page_id, version, section_id),
    FOREIGN KEY (page_id, version) REFERENCES wiki_versions (page_id, version) ON DELETE CASCADE
) STRICT;

CREATE TABLE wiki_statements (
    seq         INTEGER PRIMARY KEY,            -- stable rowid for the search index
    section_seq INTEGER NOT NULL REFERENCES wiki_sections(seq) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    style       TEXT NOT NULL CHECK (style IN ('paragraph', 'bullet')),
    text        TEXT NOT NULL
) STRICT;
CREATE INDEX wiki_statements_by_section ON wiki_statements (section_seq, position);

-- What a statement rests on: exactly one of a claim, an event, a commit (in a repository, optionally
-- one file), or another page. Claims and events have no foreign keys: when one is deleted, its
-- citation is gone, and the statement shows without it, or not at all.
CREATE TABLE wiki_citations (
    statement_seq INTEGER NOT NULL REFERENCES wiki_statements(seq) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    claim_id    TEXT,
    event_id    TEXT,
    source_id   INTEGER,                        -- the repository a commit is in
    commit_sha  TEXT,
    path        TEXT,
    page_id     TEXT,
    section_id  TEXT,
    PRIMARY KEY (statement_seq, position),
    CHECK ((claim_id IS NOT NULL) + (event_id IS NOT NULL) + (commit_sha IS NOT NULL) + (page_id IS NOT NULL) = 1),
    CHECK ((commit_sha IS NULL) = (source_id IS NULL)),
    CHECK (path IS NULL OR commit_sha IS NOT NULL),
    CHECK (section_id IS NULL OR page_id IS NOT NULL)
) STRICT;
CREATE INDEX wiki_citations_by_claim ON wiki_citations (claim_id);

-- The pages a statement links to, from [[page]] in its text or a page citation.
CREATE TABLE wiki_links (
    statement_seq INTEGER NOT NULL REFERENCES wiki_statements(seq) ON DELETE CASCADE,
    target      TEXT NOT NULL,
    PRIMARY KEY (statement_seq, target)
) STRICT;
CREATE INDEX wiki_links_to ON wiki_links (target);

-- My notes on a page: edited only in the frontend, read by Claude as mine.
CREATE TABLE wiki_notes (
    page_id     TEXT PRIMARY KEY REFERENCES wiki_pages(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    changed_at  TEXT NOT NULL
) STRICT;

-- Searches that found nothing in the layer, so the evaluation can tell whether keyword search is
-- too weak. This is content, under retention ('search_miss'), not part of the audit trail.
CREATE TABLE search_misses (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL,
    query       TEXT NOT NULL,                  -- redacted
    kinds       TEXT NOT NULL CHECK (json_valid(kinds)),
    project_id  TEXT
) STRICT;
CREATE INDEX search_misses_by_time ON search_misses (at);

-- Search covers the current version of each page only; wiki.py moves the rows when it saves a
-- version. wiki_fts has one row per statement, keyed on wiki_statements.seq; wiki_pages_fts has
-- a page's title, key terms and summary, keyed on wiki_versions.seq.
CREATE VIRTUAL TABLE wiki_fts USING fts5 (
    heading, text, tokenize = 'unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE wiki_pages_fts USING fts5 (
    title, key_terms, summary, tokenize = 'unicode61 remove_diacritics 2');
CREATE TRIGGER wiki_statements_fts_delete AFTER DELETE ON wiki_statements BEGIN
    DELETE FROM wiki_fts WHERE rowid = OLD.seq;
END;
CREATE TRIGGER wiki_versions_fts_delete AFTER DELETE ON wiki_versions BEGIN
    DELETE FROM wiki_pages_fts WHERE rowid = OLD.seq;
END;

CREATE TABLE audit_log_v8 (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL,
    actor       TEXT NOT NULL CHECK (actor IN ('collector', 'claude', 'me', 'retention')),
    action      TEXT NOT NULL CHECK (action IN
                    ('collect', 'propose', 'revise', 'set_status', 'label', 'unlabel', 'link',
                     'delete', 'expire', 'settings', 'read_confidential', 'read_repo')),
    item_type   TEXT NOT NULL,
    item_id     TEXT,
    count       INTEGER NOT NULL DEFAULT 1
) STRICT;
INSERT INTO audit_log_v8 SELECT * FROM audit_log;
DROP TABLE audit_log;
ALTER TABLE audit_log_v8 RENAME TO audit_log;
CREATE INDEX audit_log_by_time ON audit_log (at);

CREATE TABLE retention_v8 (
    item_type   TEXT PRIMARY KEY CHECK (item_type IN
                    ('git_repo', 'claude_code', 'firefox', 'app_usage', 'calendar', 'notes_folder',
                     'session_note', 'transcript', 'unconfirmed_claim', 'confirmed_claim', 'audio', 'audit',
                     'wiki_version', 'search_miss')),
    days        INTEGER CHECK (days IS NULL OR days > 0)
) STRICT;
INSERT INTO retention_v8 SELECT * FROM retention;
DROP TABLE retention;
ALTER TABLE retention_v8 RENAME TO retention;
INSERT OR IGNORE INTO retention (item_type, days) VALUES ('wiki_version', 90), ('search_miss', 90);

UPDATE schema_version SET version = 8;
