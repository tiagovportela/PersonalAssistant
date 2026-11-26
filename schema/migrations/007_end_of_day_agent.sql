-- Schema 6 -> 7: the end-of-day agent (docs/end_of_day_agent.md).
-- A commitment records who it's promised to (counterparty), next to who owes it (owner).
-- The agent's runs, and the reviews it posts to my direct message with the layer's Chat app,
-- are kept so a click on a card can be checked against what was shown. The views are
-- recreated to read the counterparty. store.py runs this in one transaction and backs the
-- store up first.

ALTER TABLE claim_versions ADD COLUMN counterparty TEXT;

DROP VIEW IF EXISTS claims_for_claude;
DROP VIEW IF EXISTS current_claims;

CREATE VIEW current_claims AS
SELECT c.id, COALESCE(v.type, c.type) AS type, c.type AS proposed_type, c.created_at AS first_proposed_at,
       v.version, v.status, v.text, v.project_id, v.about_day, v.due_at, v.owner, v.counterparty,
       v.confidence, v.method, v.changed_by, v.reason, v.created_at AS version_at, v.seq
FROM claims c
JOIN claim_versions v ON v.claim_id = c.id
WHERE v.version = (SELECT MAX(version) FROM claim_versions WHERE claim_id = c.id);

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

CREATE TABLE eod_runs (
    id          INTEGER PRIMARY KEY,
    day         TEXT NOT NULL,                  -- the workday it's about
    kind        TEXT NOT NULL CHECK (kind IN ('run', 'finish')),
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL CHECK (status IN ('running', 'ok', 'failed')),
    detail      TEXT                            -- turns and duration, or the error; never work content
) STRICT;
CREATE INDEX eod_runs_by_day ON eod_runs (day, kind);

CREATE TABLE review_batches (
    id               TEXT PRIMARY KEY,          -- 'rvb_' + random
    day              TEXT NOT NULL,
    space            TEXT NOT NULL,             -- my direct message with the Chat app
    posted_at        TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('open', 'answered', 'replaced')),
    notes_updated_at TEXT                       -- when the finish run last rewrote the day's notes
) STRICT;

CREATE TABLE review_messages (
    name        TEXT PRIMARY KEY,               -- spaces/.../messages/...
    batch_id    TEXT NOT NULL REFERENCES review_batches(id) ON DELETE CASCADE,
    stale       INTEGER NOT NULL DEFAULT 0 CHECK (stale IN (0, 1))  -- its card doesn't show the latest answers yet
) STRICT;

CREATE TABLE review_items (
    id          TEXT PRIMARY KEY,               -- 'rvi_' + random; the card's buttons carry it
    batch_id    TEXT NOT NULL REFERENCES review_batches(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,               -- the number shown on the card
    claim_id    TEXT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,               -- the version shown; a click applies only while it's current
    message     TEXT REFERENCES review_messages(name) ON DELETE SET NULL,
    answer      TEXT CHECK (answer IN ('confirmed', 'corrected', 'disputed', 'retracted', 'changed', 'moved')),
    answered_at TEXT,
    UNIQUE (batch_id, position)
) STRICT;
CREATE INDEX review_items_by_claim ON review_items (claim_id);

UPDATE schema_version SET version = 7;
