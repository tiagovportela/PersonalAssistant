import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { ClaimStatus, Problem } from "./ui.jsx";

const CHOICES = [
  ["keep", "Keep", "Its evidence will show as deleted"],
  ["retract", "Retract", "Claude won't use it again"],
  ["delete", "Delete", "Removed with the evidence"],
];

// Deleting evidence asks what happens to every claim that relies on it: nothing is decided for me.
export function DeleteDialog({ items, what, onClose, onDeleted }) {
  const dialog = useRef(null);
  const [impact, setImpact] = useState(null);
  const [decisions, setDecisions] = useState({});
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    dialog.current?.showModal();
    api("impact", { method: "POST", body: { items } })
      .then(setImpact)
      .catch((e) => setError(e.message));
  }, [items]);

  const affected = impact?.affected_claims || [];
  const undecided = affected.filter((c) => !decisions[c.claim_id]).length;

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      const done = await api("delete", { method: "POST", body: { items, decisions } });
      onDeleted(done);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <dialog ref={dialog} className="dialog" onClose={onClose} aria-labelledby="delete-title">
      <h2 id="delete-title">Delete {what}?</h2>
      <p>
        This can't be undone.
        {impact && impact.events > 0 && ` ${impact.events} event${impact.events === 1 ? "" : "s"} will be deleted.`}
      </p>
      {affected.length > 0 && (
        <>
          <p>
            {affected.length === 1 ? "One claim relies" : `${affected.length} claims rely`} on this evidence. Decide what
            happens to each.
          </p>
          <ul className="decisions">
            {affected.map((c) => (
              <li key={c.claim_id}>
                <p className="claim-text">
                  {c.text} <ClaimStatus status={c.status} />
                </p>
                <p className="quiet">
                  {c.evidence_removed} of {c.evidence_total} pieces of evidence deleted
                </p>
                <fieldset>
                  <legend className="sr-only">What happens to this claim</legend>
                  {CHOICES.map(([value, name, hint]) => (
                    <label key={value} className="choice">
                      <input
                        type="radio"
                        name={c.claim_id}
                        value={value}
                        checked={decisions[c.claim_id] === value}
                        onChange={() => setDecisions({ ...decisions, [c.claim_id]: value })}
                      />
                      <span>{name}</span>
                      <span className="quiet">{hint}</span>
                    </label>
                  ))}
                </fieldset>
              </li>
            ))}
          </ul>
        </>
      )}
      <Problem message={error} />
      <div className="dialog-actions">
        <button type="button" className="button" onClick={() => dialog.current.close()}>
          Cancel
        </button>
        <button type="button" className="button danger" onClick={remove} disabled={!impact || undecided > 0 || busy}>
          {undecided > 0 ? `Decide ${undecided} more` : busy ? "Deleting…" : "Delete"}
        </button>
      </div>
    </dialog>
  );
}
