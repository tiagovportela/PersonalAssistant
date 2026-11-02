import { useState } from "react";
import { api, whenUtc } from "../api.js";
import { DeleteDialog } from "../components/DeleteDialog.jsx";
import { Loading, Page, Problem, useAction, useLoad } from "../components/ui.jsx";

const KIND_NAMES = { git_repo: "Git repository", claude_code: "Claude Code sessions" };

export function Sources() {
  const list = useLoad("sources");
  const [path, setPath] = useState("");
  const [added, setAdded] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const adding = useAction((result) => {
    setAdded(result);
    setPath("");
    list.reload();
  });
  const toggling = useAction(() => list.reload());

  const add = (event) => {
    event.preventDefault();
    adding.run(() => api("sources", { method: "POST", body: { path } }));
  };

  return (
    <Page
      title="Sources"
      intro="Only what you add here is read. A folder adds every Git repository in it; add it again to pick up new ones."
    >
      <form className="add-form" onSubmit={add}>
        <label htmlFor="path">Repository or folder</label>
        <div className="row">
          <input id="path" value={path} onChange={(e) => setPath(e.target.value)} placeholder="~/Projects" spellCheck="false" />
          <button type="submit" className="button primary" disabled={adding.busy || !path.trim()}>
            {adding.busy ? "Adding…" : "Add"}
          </button>
        </div>
        <Problem message={adding.error} />
        {added && (
          <p className="quiet" role="status">
            {added.filter((a) => a.status.startsWith("allowlisted")).length} added, {added.length} found.
          </p>
        )}
      </form>
      <Problem message={toggling.error} />
      <Loading state={list} empty="Nothing is collected yet. Add a repository, or a folder such as ~/Projects.">
        <table className="table">
          <thead>
            <tr><th>Source</th><th>Events</th><th>Last collected</th><th>Collecting</th><th><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {list.data?.map((s) => (
              <tr key={s.id} className={s.enabled ? "" : "off"}>
                <td>
                  <strong>{s.name}</strong> <span className="quiet">{KIND_NAMES[s.kind] || s.kind}</span>
                  <div><code>{s.locator}</code></div>
                  {s.last_status === "error" && <p className="problem small">{s.last_error}</p>}
                </td>
                <td className="number">{s.events.toLocaleString()}</td>
                <td>{whenUtc(s.last_run_at)}</td>
                <td>
                  <label className="switch">
                    <input
                      type="checkbox"
                      checked={!!s.enabled}
                      onChange={(e) => toggling.run(() => api(`sources/${s.id}`, { method: "PUT", body: { enabled: e.target.checked } }))}
                    />
                    <span>{s.enabled ? "On" : "Off"}</span>
                  </label>
                </td>
                <td>
                  <button type="button" className="link danger" onClick={() => setDeleting(s)}>Delete with its data</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Loading>
      {deleting && (
        <DeleteDialog
          items={[{ type: "source", id: String(deleting.id) }]}
          what={`${deleting.name} and everything collected from it`}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setDeleting(null);
            list.reload();
          }}
        />
      )}
    </Page>
  );
}
