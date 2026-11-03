-- Schema 4 -> 5: activity (Phase 4). Adds a settings table, for the app-usage mode,
-- and search over a Firefox visit's address and an app span's app name. Older events
-- have neither field, so the search index needs no rebuild. store.py runs this in one
-- transaction and backs the store up first.

CREATE TABLE settings (
    key         TEXT PRIMARY KEY,               -- 'app_usage.mode'
    value       TEXT NOT NULL,
    changed_at  TEXT NOT NULL
) STRICT;

DROP TRIGGER events_fts_insert;
DROP TRIGGER events_fts_update;
CREATE TRIGGER events_fts_insert AFTER INSERT ON events BEGIN
    INSERT INTO events_fts (rowid, title, details) VALUES (NEW.seq, NEW.title,
        COALESCE(json_extract(NEW.payload, '$.body'), '') || ' ' || COALESCE(json_extract(NEW.payload, '$.branch'), '')
        || ' ' || COALESCE((SELECT group_concat(value, ' ') FROM json_each(NEW.payload, '$.files')), '')
        || ' ' || COALESCE(json_extract(NEW.payload, '$.url'), '') || ' ' || COALESCE(json_extract(NEW.payload, '$.app'), ''));
END;
CREATE TRIGGER events_fts_update AFTER UPDATE OF title, payload ON events BEGIN
    DELETE FROM events_fts WHERE rowid = OLD.seq;
    INSERT INTO events_fts (rowid, title, details) VALUES (NEW.seq, NEW.title,
        COALESCE(json_extract(NEW.payload, '$.body'), '') || ' ' || COALESCE(json_extract(NEW.payload, '$.branch'), '')
        || ' ' || COALESCE((SELECT group_concat(value, ' ') FROM json_each(NEW.payload, '$.files')), '')
        || ' ' || COALESCE(json_extract(NEW.payload, '$.url'), '') || ' ' || COALESCE(json_extract(NEW.payload, '$.app'), ''));
END;

UPDATE schema_version SET version = 5;
