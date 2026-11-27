import { useState } from "react";
import { api, whenUtc } from "../api.js";
import { Loading, Page, Problem, useAction, useLoad } from "../components/ui.jsx";

const KIND_NAMES = { project: "Project", person: "Person", topic: "Topic" };
const PROBLEM_NAMES = {
  not_written: "Not written", stale: "Stale", lost_evidence: "Evidence gone", disputed: "Cites disputed claims",
  file_changed: "Cited file changed", diagram_stale: "Diagram out of date", broken_link: "Broken link",
  orphan: "Nothing links here", topic_one_project: "Topic with one project", near_budget: "Near its size limit",
};

function Diff({ page, from, to }) {
  const diff = useLoad(`wiki/${encodeURIComponent(page)}/diff?from=${from}&to=${to}`);
  return (
    <Loading state={diff}>
      <div className="wiki-diff">
        {diff.data?.sections.filter((s) => s.change !== "same").map((s) => (
          <div key={s.id}>
            <p><strong>{s.heading}</strong> <span className="quiet">{s.change}</span></p>
            <ul>
              {s.lines.filter((l) => l.op !== " ").map((l, i) => (
                <li key={i} className={l.op === "+" ? "added" : "removed"}>{l.op} {l.text}</li>
              ))}
            </ul>
          </div>
        ))}
        {diff.data && diff.data.sections.every((s) => s.change === "same") && <p className="quiet">No change in the text.</p>}
      </div>
    </Loading>
  );
}

function Notes({ page, onSaved }) {
  const [text, setText] = useState(page.notes?.text || "");
  const saving = useAction(onSaved);
  const save = (event) => {
    event.preventDefault();
    saving.run(() => api(`wiki/${encodeURIComponent(page.page)}/notes`, { method: "PUT", body: { text } }));
  };
  return (
    <form onSubmit={save} className="wiki-notes">
      <label>
        My notes <span className="quiet">— Claude reads them as mine, verified, and never changes them</span>
        <textarea rows={4} value={text} maxLength={4000} onChange={(e) => setText(e.target.value)} />
      </label>
      <button type="submit" className="button" disabled={saving.busy || text === (page.notes?.text || "")}>Save notes</button>
      {page.notes && <span className="quiet small"> Saved {whenUtc(page.notes.changed_at)}</span>}
      <Problem message={saving.error} />
    </form>
  );
}

function PageDetail({ id, onClose, onChanged }) {
  const page = useLoad(`wiki/${encodeURIComponent(id)}`);
  const [compare, setCompare] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const changing = useAction(() => { page.reload(); onChanged(); });
  const restore = (version) => changing.run(() => api(`wiki/${encodeURIComponent(id)}/restore`, { method: "POST", body: { version } }));
  const remove = () => changing.run(async () => {
    await api(`wiki/${encodeURIComponent(id)}`, { method: "DELETE" });
    onClose();
  });
  const p = page.data;
  return (
    <section className="wiki-detail" aria-label={`Wiki page ${id}`}>
      <p><button type="button" className="link" onClick={onClose}>← All pages</button></p>
      <Loading state={page}>
        {p && (
          <>
            <h2>{p.title} <span className="quiet small">{KIND_NAMES[p.kind]} page{p.confidential ? ", confidential: Claude never sees it" : ""}</span></h2>
            {p.lint.length > 0 && (
              <ul className="wiki-lint">
                {p.lint.map((f, i) => <li key={i}><strong>{PROBLEM_NAMES[f.problem] || f.problem}</strong>{f.section && <span className="quiet"> in {f.section}</span>}: {f.detail}</li>)}
              </ul>
            )}
            <Notes key={p.notes?.changed_at || "none"} page={p} onSaved={page.reload} />
            <h3>Versions</h3>
            {p.versions.length === 0 ? <p className="empty">Not written yet. The compile run writes it, or ask Claude to.</p> : (
              <table className="table">
                <thead><tr><th>Version</th><th>Written</th><th>Why</th><th></th></tr></thead>
                <tbody>
                  {p.versions.map((v, i) => (
                    <tr key={v.version}>
                      <td className="nowrap">v{v.version}{i === 0 && <span className="quiet"> current</span>}</td>
                      <td className="nowrap">{whenUtc(v.written_at)} <span className="quiet">by {v.written_by === "me" ? "you" : "Claude"}</span></td>
                      <td>{v.reason} <span className="quiet small">{v.blocks} blocks</span></td>
                      <td className="nowrap">
                        {i + 1 < p.versions.length && (
                          <button type="button" className="link" onClick={() => setCompare(compare === v.version ? null : v.version)}>
                            {compare === v.version ? "Hide changes" : "Changes"}
                          </button>
                        )}
                        {i > 0 && <> <button type="button" className="link" disabled={changing.busy} onClick={() => restore(v.version)}>Restore</button></>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {compare && (
              <Diff page={id} from={p.versions.find((v) => v.version < compare)?.version || compare} to={compare} />
            )}
            {p.sections.length > 0 && (
              <>
                <h3>Current text</h3>
                <div className="wiki-text">
                  {p.sections.map((s) => (
                    <div key={s.id}><p><strong>{s.heading}</strong></p><ul>{s.lines.map((l, i) => <li key={i}>{l}</li>)}</ul></div>
                  ))}
                </div>
              </>
            )}
            {p.versions.length > 0 && (
              <p className="danger-zone">
                {confirming ? (
                  <>
                    Delete {p.title} with all {p.versions.length} versions? This can't be undone.{" "}
                    <button type="button" className="button danger" disabled={changing.busy} onClick={remove}>Delete page</button>{" "}
                    <button type="button" className="link" onClick={() => setConfirming(false)}>Cancel</button>
                  </>
                ) : <button type="button" className="link" onClick={() => setConfirming(true)}>Delete this page…</button>}
              </p>
            )}
            <Problem message={changing.error} />
          </>
        )}
      </Loading>
    </section>
  );
}

export function Wiki() {
  const wiki = useLoad("wiki");
  const [open, setOpen] = useState(null);
  const building = useAction(wiki.reload);
  const build = () => building.run(() => api("wiki/build", { method: "POST" }));
  const data = wiki.data;
  const findings = data?.lint.findings || [];

  if (open) return <Page title="Wiki"><PageDetail id={open} onClose={() => setOpen(null)} onChanged={wiki.reload} /></Page>;
  return (
    <Page
      title="Wiki"
      intro="The knowledge wiki Claude writes: one page per project, person and topic. Versions, restore and delete happen here; the static site is for reading."
      actions={<button type="button" className="button" onClick={build} disabled={building.busy}>{building.busy ? "Building…" : "Rebuild the site"}</button>}
    >
      <Problem message={building.error} />
      <Loading state={wiki}>
        {data && (
          <>
            <p className="quiet small">
              Static site: <code>{data.site.path}</code>{" "}
              {data.site.built ? `built ${whenUtc(data.site.built_at)}${data.site.seconds ? ` in ${data.site.seconds}s` : ""}; ` : "not built yet; "}
              open it with <code>pwi wiki open</code>.
            </p>
            <table className="table">
              <thead><tr><th>Page</th><th>Kind</th><th>Version</th><th>Updated</th></tr></thead>
              <tbody>
                {data.pages.map((p) => (
                  <tr key={p.page}>
                    <td>
                      <button type="button" className="link" onClick={() => setOpen(p.page)}><strong>{p.title}</strong></button>
                      {p.stale && <span className="status status-disputed"> stale</span>}
                      {p.confidential && <span className="quiet"> confidential</span>}
                      {p.has_notes && <span className="quiet"> · notes</span>}
                      {p.summary && <div className="quiet small">{p.summary}</div>}
                    </td>
                    <td>{KIND_NAMES[p.kind]}</td>
                    <td className="nowrap">{p.version ? `v${p.version}` : <span className="quiet">not written</span>}</td>
                    <td className="nowrap">{p.updated_at ? <>{whenUtc(p.updated_at)} <span className="quiet">by {p.written_by === "me" ? "you" : "Claude"}</span></> : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h2>What needs fixing <span className="quiet small">({findings.length})</span></h2>
            {findings.length === 0 ? <p className="empty">Nothing: every page is current and its evidence stands.</p> : (
              <ul className="wiki-lint">
                {findings.map((f, i) => (
                  <li key={i}>
                    <button type="button" className="link" onClick={() => setOpen(f.page)}>{f.page}</button>{" "}
                    <strong>{PROBLEM_NAMES[f.problem] || f.problem}</strong>{f.section && <span className="quiet"> in {f.section}</span>}: {f.detail}
                  </li>
                ))}
              </ul>
            )}
            <h2>Searches that found nothing <span className="quiet small">(kept 90 days)</span></h2>
            {data.misses.length === 0 ? <p className="empty">None recorded.</p> : (
              <table className="table">
                <tbody>
                  {data.misses.map((m, i) => (
                    <tr key={i}><td className="nowrap">{whenUtc(m.at)}</td><td>{m.query}</td><td className="quiet">{m.project_id || ""}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </Loading>
    </Page>
  );
}
