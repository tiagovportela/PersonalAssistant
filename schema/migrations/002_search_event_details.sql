-- Schema 1 -> 2: search also covers a commit's message body and file paths, and a
-- push's branch, not just event titles. Rebuilds events_fts from the events table.
-- store.py runs this in one transaction and backs the store up first.

DROP TRIGGER events_fts_insert;
DROP TRIGGER events_fts_delete;
DROP TRIGGER events_fts_update;
DROP TABLE events_fts;

CREATE VIRTUAL TABLE events_fts USING fts5 (
    title, details, tokenize = 'unicode61 remove_diacritics 2');
CREATE TRIGGER events_fts_insert AFTER INSERT ON events BEGIN
    INSERT INTO events_fts (rowid, title, details) VALUES (NEW.seq, NEW.title,
        COALESCE(json_extract(NEW.payload, '$.body'), '') || ' ' || COALESCE(json_extract(NEW.payload, '$.branch'), '')
        || ' ' || COALESCE((SELECT group_concat(value, ' ') FROM json_each(NEW.payload, '$.files')), ''));
END;
CREATE TRIGGER events_fts_delete AFTER DELETE ON events BEGIN
    DELETE FROM events_fts WHERE rowid = OLD.seq;
END;
CREATE TRIGGER events_fts_update AFTER UPDATE OF title, payload ON events BEGIN
    DELETE FROM events_fts WHERE rowid = OLD.seq;
    INSERT INTO events_fts (rowid, title, details) VALUES (NEW.seq, NEW.title,
        COALESCE(json_extract(NEW.payload, '$.body'), '') || ' ' || COALESCE(json_extract(NEW.payload, '$.branch'), '')
        || ' ' || COALESCE((SELECT group_concat(value, ' ') FROM json_each(NEW.payload, '$.files')), ''));
END;

INSERT INTO events_fts (rowid, title, details)
SELECT seq, title,
       COALESCE(json_extract(payload, '$.body'), '') || ' ' || COALESCE(json_extract(payload, '$.branch'), '')
       || ' ' || COALESCE((SELECT group_concat(value, ' ') FROM json_each(payload, '$.files')), '')
FROM events;

UPDATE schema_version SET version = 2;
