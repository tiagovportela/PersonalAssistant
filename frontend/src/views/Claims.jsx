import { Fragment, useState } from "react";
import { STATUS_NAMES, whenUtc } from "../api.js";
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
              <ClaimStatus status={v.status} /> {v.changed_by === "me" ? "by you" : "by Claude"}, {whenUtc(v.created_at)}
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

export function Claims() {
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const params = new URLSearchParams({ ...(status && { status }), ...(search && { q: search }) });
  const list = useLoad(`claims?${params}`);
  const labelling = useAction(() => list.reload());

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
      <Problem message={labelling.error} />
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
                    {!c.labelled && (
                      <button type="button" className="link" onClick={() => labelling.run(() => label("claim", c.claim_id))}>
                        Mark confidential
                      </button>
                    )}
                    <button type="button" className="link danger" onClick={() => setDeleting(c)}>Delete</button>
                  </td>
                </tr>
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
