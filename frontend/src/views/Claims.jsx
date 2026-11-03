import { Fragment, useState } from "react";
import { STATUS_NAMES, api, whenUtc } from "../api.js";
import { DeleteDialog } from "../components/DeleteDialog.jsx";
import { ClaimStatus, Loading, Page, Problem, Redacted, label, useAction, useLoad } from "../components/ui.jsx";

const TYPE_NAMES = { decision: "Decision", commitment: "Commitment", blocker: "Blocker", fact: "Fact", session_note: "Session note" };

function History({ claimId }) {
  const history = useLoad(`claims/${encodeURIComponent(claimId)}`);
  return (
    <Loading state={history}>
      <ol className="history">
        {history.data?.versions.map((v) => (
          <li key={v.version}>
            <p>
              <ClaimStatus status={v.status} /> <span className="quiet">{TYPE_NAMES[v.type]}</span>{" "}
              {v.changed_by === "me" ? "by you" : "by Claude"}, {whenUtc(v.created_at)}
              {v.reason && <span className="quiet"> ({v.reason})</span>}
            </p>
            <p>{v.text}</p>
            {v.evidence.length > 0 && (
              <ul className="evidence">
                {v.evidence.map((e) => (
                  <li key={e.id}>
                    {e.expired_at ? <span className="quiet">Deleted evidence</span>
                      : e.event_id ? <>{e.event_title || e.event_id} <code>{e.event_id}</code></>
                        : <>{e.artifact_title || e.artifact_id} {e.url && <span className="quiet">{e.url}</span>}</>}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </Loading>
  );
}

const EDITABLE_TYPES = ["decision", "commitment", "blocker", "fact"];
const FIELDS = ["type", "text", "project", "about_day", "due_at", "owner"];

// My edit becomes a new version; the old ones stay in the history.
function ClaimEditor({ claim, projects, onSaved, onCancel }) {
  const start = Object.fromEntries(FIELDS.map((f) => [f, claim[f] || ""]));
  const [form, setForm] = useState({ ...start, status: "supported", reason: "" });
  const saving = useAction(onSaved);
  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value });
  const changed = FIELDS.filter((f) => form[f] !== start[f]);
  const save = (e) => {
    e.preventDefault();
    const body = Object.fromEntries(changed.map((f) => [f, form[f]]));
    if (form.status !== claim.status || changed.length) body.status = form.status;
    if (form.reason.trim()) body.reason = form.reason;
    saving.run(() => api(`claims/${encodeURIComponent(claim.claim_id)}`, { method: "PUT", body }));
  };
  const note = claim.type === "session_note";
  return (
    <form className="claim-edit" onSubmit={save}>
      <label className="wide">
        Text
        <textarea value={form.text} onChange={set("text")} rows={3} />
      </label>
      <label>
        Type
        <select value={form.type} onChange={set("type")} disabled={note}>
          {(note ? ["session_note"] : EDITABLE_TYPES).map((t) => <option key={t} value={t}>{TYPE_NAMES[t]}</option>)}
        </select>
      </label>
      <label>
        Project
        <select value={form.project} onChange={set("project")}>
          <option value="">No project</option>
          {projects?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      <label>
        Day it's about
        <input type="date" value={form.about_day} onChange={set("about_day")} />
      </label>
      <label>
        Due
        <input value={form.due_at} onChange={set("due_at")} placeholder="YYYY-MM-DD" spellCheck="false" />
      </label>
      <label>
        Owner
        <input value={form.owner} onChange={set("owner")} placeholder="me, or their email" />
      </label>
      <label>
        Status after saving
        <select value={form.status} onChange={set("status")}>
          {Object.entries(STATUS_NAMES).map(([value, name]) => <option key={value} value={value}>{name}</option>)}
        </select>
      </label>
      <label className="wide">
        Why (optional)
        <input value={form.reason} onChange={set("reason")} placeholder="e.g. it was a commitment, not a decision" />
      </label>
      <div className="wide row">
        <button type="submit" className="button primary" disabled={saving.busy}>
          {saving.busy ? "Saving…" : "Save as a new version"}
        </button>
        <button type="button" className="button" onClick={onCancel}>Cancel</button>
      </div>
      <Problem message={saving.error} />
    </form>
  );
}

export function Claims() {
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const params = new URLSearchParams({ ...(status && { status }), ...(search && { q: search }) });
  const list = useLoad(`claims?${params}`);
  const labelling = useAction(() => list.reload());
  const projects = useLoad("projects");
  const [editing, setEditing] = useState(null);
  const setting = useAction(() => list.reload());
  const setStatusOf = (c, value) =>
    setting.run(() => api(`claims/${encodeURIComponent(c.claim_id)}`, { method: "PUT", body: { status: value } }));

  return (
    <Page title="Claims" intro="What Claude saved about your work: decisions, commitments, blockers, facts and session notes.">
      <form className="filters" onSubmit={(e) => { e.preventDefault(); setSearch(query); }}>
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any</option>
            {Object.entries(STATUS_NAMES).map(([value, name]) => <option key={value} value={value}>{name}</option>)}
          </select>
        </label>
        <label className="grow">
          Words
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="cache, decisão, release" />
        </label>
        <button type="submit" className="button">Search</button>
      </form>
      <Problem message={labelling.error || setting.error} />
      <Loading state={list} empty={search || status ? "No claims match." : "Claude hasn't saved any claims yet."}>
        <table className="table">
          <thead>
            <tr><th>Claim</th><th>Status</th><th>Project</th><th>Changed</th><th><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {list.data?.map((c) => (
              <Fragment key={c.claim_id}>
                <tr className={c.status === "retracted" ? "off" : ""}>
                  <td>
                    <span className="quiet">{TYPE_NAMES[c.type]}</span>{" "}
                    {c.labelled || c.hidden_from_claude ? <Redacted>{c.text}</Redacted> : c.text}
                    <div className="quiet">
                      {c.evidence} piece{c.evidence === 1 ? "" : "s"} of evidence
                      {c.hidden_from_claude && ", hidden from Claude"}.{" "}
                      <button type="button" className="link" aria-expanded={open === c.claim_id}
                        onClick={() => setOpen(open === c.claim_id ? null : c.claim_id)}>
                        {open === c.claim_id ? "Hide history" : `History (${c.version} version${c.version === 1 ? "" : "s"})`}
                      </button>
                    </div>
                  </td>
                  <td><ClaimStatus status={c.status} /></td>
                  <td>{c.project || ""}</td>
                  <td className="nowrap">{whenUtc(c.changed_at)}</td>
                  <td className="actions">
                    <div className="action-list">
                      {c.status !== "supported" && c.status !== "retracted" && (
                        <button type="button" className="link" onClick={() => setStatusOf(c, "supported")}>Confirm</button>
                      )}
                      {c.status !== "retracted" && (
                        <button type="button" className="link" onClick={() => setStatusOf(c, "retracted")}>Retract</button>
                      )}
                      <button type="button" className="link" aria-expanded={editing === c.claim_id}
                        onClick={() => setEditing(editing === c.claim_id ? null : c.claim_id)}>
                        Edit
                      </button>
                      {!c.labelled && (
                        <button type="button" className="link" onClick={() => labelling.run(() => label("claim", c.claim_id))}>
                          Mark confidential
                        </button>
                      )}
                      <button type="button" className="link danger" onClick={() => setDeleting(c)}>Delete</button>
                    </div>
                  </td>
                </tr>
                {editing === c.claim_id && (
                  <tr className="detail">
                    <td colSpan={5}>
                      <ClaimEditor
                        claim={c}
                        projects={projects.data}
                        onSaved={() => { setEditing(null); list.reload(); }}
                        onCancel={() => setEditing(null)}
                      />
                    </td>
                  </tr>
                )}
                {open === c.claim_id && (
                  <tr className="detail">
                    <td colSpan={5}><History claimId={c.claim_id} /></td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </Loading>
      {deleting && (
        <DeleteDialog
          items={[{ type: "claim", id: deleting.claim_id }]}
          what="this claim and all its versions"
          onClose={() => setDeleting(null)}
          onDeleted={() => { setDeleting(null); list.reload(); }}
        />
      )}
    </Page>
  );
}
