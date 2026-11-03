-- Schema 5 -> 6: a claim's type can change (I correct it in the frontend), so each version
-- records its type. claims.type keeps the type first proposed, which the metrics judge
-- Claude's proposals by; older versions have NULL here, meaning that type. The views are
-- recreated to read the current type from the version. store.py runs this in one
-- transaction and backs the store up first.

ALTER TABLE claim_versions ADD COLUMN type TEXT CHECK (type IS NULL OR type IN ('decision', 'commitment', 'blocker', 'fact', 'session_note'));

DROP VIEW IF EXISTS claims_for_claude;
DROP VIEW IF EXISTS current_claims;

CREATE VIEW current_claims AS
SELECT c.id, COALESCE(v.type, c.type) AS type, c.type AS proposed_type, c.created_at AS first_proposed_at,
       v.version, v.status, v.text, v.project_id, v.about_day, v.due_at, v.owner,
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

UPDATE schema_version SET version = 6;
