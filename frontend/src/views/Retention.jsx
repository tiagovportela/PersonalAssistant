import { useState } from "react";
import { api } from "../api.js";
import { Loading, Page, Problem, useAction, useLoad } from "../components/ui.jsx";

// In the order they matter now; the last ones aren't collected yet.
const KINDS = [
  ["git_repo", "Git activity", "Commits, merges, pushes and working-tree states"],
  ["claude_code", "Claude Code session index", "When sessions ran and their titles; Claude Code keeps the files 30 days"],
  ["session_note", "Session notes you haven't confirmed", "Counted from the day they're about"],
  ["unconfirmed_claim", "Unconfirmed claims", "Counted from Claude's last change"],
  ["confirmed_claim", "Verified claims", "Their evidence may expire sooner; Claude says so"],
  ["audit", "Audit trail", "What was collected, changed or deleted, never the content"],
  ["transcript", "Meeting transcripts", "Not collected yet"],
  ["audio", "Meeting audio", "Not collected yet"],
  ["notes_folder", "Meeting notes folder", "Not collected yet"],
  ["calendar", "Calendar", "Not collected yet"],
  ["firefox", "Firefox history", "Not collected yet"],
  ["app_usage", "App usage", "Not collected yet"],
];

function Setting({ kind, name, hint, days, onSaved }) {
  const [value, setValue] = useState(days === null ? "" : String(days));
  const [keep, setKeep] = useState(days === null);
  const saving = useAction(onSaved);
  const changed = keep ? days !== null : String(days) !== value;
  const save = (event) => {
    event.preventDefault();
    saving.run(() => api(`retention/${kind}`, { method: "PUT", body: { days: keep ? null : Number(value) } }));
  };

  return (
    <tr>
      <td>
        <strong>{name}</strong>
        <div className="quiet">{hint}</div>
      </td>
      <td>
        <form className="retention" onSubmit={save}>
          <label className="days">
            <input type="number" min="1" max="3650" value={value} disabled={keep} required={!keep}
              onChange={(e) => setValue(e.target.value)} aria-label={`Days to keep ${name.toLowerCase()}`} />
            days
          </label>
          <label className="choice">
            <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />
            Until I delete it
          </label>
          <button type="submit" className="button" disabled={!changed || saving.busy}>Save</button>
        </form>
        <Problem message={saving.error} />
      </td>
    </tr>
  );
}

export function Retention() {
  const list = useLoad("retention");
  const days = Object.fromEntries((list.data || []).map((r) => [r.item_type, r.days]));

  return (
    <Page title="Retention" intro="How long each kind of data is kept. Older data is deleted once a day, when the laptop is idle.">
      <Loading state={list}>
        <table className="table">
          <thead><tr><th>Kind of data</th><th>Keep it for</th></tr></thead>
          <tbody>
            {KINDS.filter(([kind]) => kind in days).map(([kind, name, hint]) => (
              <Setting key={`${kind}:${days[kind]}`} kind={kind} name={name} hint={hint} days={days[kind]} onSaved={list.reload} />
            ))}
          </tbody>
        </table>
      </Loading>
    </Page>
  );
}
