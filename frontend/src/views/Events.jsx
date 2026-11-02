import { useState } from "react";
import { EVENT_NAMES, when } from "../api.js";
import { DeleteDialog } from "../components/DeleteDialog.jsx";
import { Loading, Page, Problem, Redacted, label, useAction, useLoad } from "../components/ui.jsx";

export function Events() {
  const projects = useLoad("projects");
  const [project, setProject] = useState("");
  const [day, setDay] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [deleting, setDeleting] = useState(null);
  const params = new URLSearchParams({ ...(project && { project }), ...(day && { day }), ...(search && { q: search }) });
  const list = useLoad(`events?${params}`);
  const labelling = useAction(() => list.reload());

  return (
    <Page title="Activity" intro="Commits, pushes and Claude Code sessions, newest first. Only metadata is kept: never code or prompts.">
      <form className="filters" onSubmit={(e) => { e.preventDefault(); setSearch(query); }}>
        <label>
          Project
          <select value={project} onChange={(e) => setProject(e.target.value)}>
            <option value="">All</option>
            {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label>
          Day
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        </label>
        <label className="grow">
          Words
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="a commit message, a file name" />
        </label>
        <button type="submit" className="button">Search</button>
      </form>
      <Problem message={labelling.error} />
      <Loading state={list} empty="Nothing found for these filters.">
        <table className="table">
          <thead>
            <tr><th>When</th><th>What</th><th>Project</th><th><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {list.data?.map((e) => (
              <tr key={e.event_id} className={e.source_enabled ? "" : "off"}>
                <td className="nowrap">{when(e.at)}</td>
                <td>
                  <span className="quiet">{EVENT_NAMES[e.type] || e.type}</span>{" "}
                  {e.confidential ? <Redacted>{e.title || e.event_id}</Redacted> : e.title || <code>{e.event_id}</code>}
                  <div className="quiet">
                    {e.actor && `by ${e.actor}, `}
                    {e.files_changed !== undefined && `${e.files_changed} files, +${e.insertions} −${e.deletions}`}
                    {e.prompts !== undefined && `${e.prompts} prompts, until ${when(e.until).slice(11)}`}
                    {e.commits !== undefined && e.commits !== null && `${e.commits} commits`}
                    {e.gone && ", no longer in the source"}
                    {!e.source_enabled && ", from a source that's off"}
                  </div>
                </td>
                <td>{e.project}</td>
                <td className="actions">
                  {!e.labelled && (
                    <button type="button" className="link" onClick={() => labelling.run(() => label("event", e.event_id))}>
                      Mark confidential
                    </button>
                  )}
                  <button type="button" className="link danger" onClick={() => setDeleting(e)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.data?.length === 200 && <p className="quiet">Showing the newest 200. Narrow it down with a project, a day or words.</p>}
      </Loading>
      {deleting && (
        <DeleteDialog
          items={[{ type: "event", id: deleting.event_id }]}
          what={`this ${(EVENT_NAMES[deleting.type] || "event").toLowerCase()}`}
          onClose={() => setDeleting(null)}
          onDeleted={() => { setDeleting(null); list.reload(); }}
        />
      )}
    </Page>
  );
}
