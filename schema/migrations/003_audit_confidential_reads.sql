-- Schema 2 -> 3: the audit trail also records each confidential item Claude was
-- shown through read_confidential. SQLite can't change a CHECK in place, so the
-- table is rebuilt with its rows. store.py runs this in one transaction and backs
-- the store up first.

CREATE TABLE audit_log_v3 (
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
INSERT INTO audit_log_v3 SELECT * FROM audit_log;
DROP TABLE audit_log;
ALTER TABLE audit_log_v3 RENAME TO audit_log;
CREATE INDEX audit_log_by_time ON audit_log (at);

UPDATE schema_version SET version = 3;
