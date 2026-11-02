import { api, whenUtc } from "../api.js";
import { Loading, Page, Problem, useAction, useLoad } from "../components/ui.jsx";

export function Overview({ go }) {
  const status = useLoad("status");
  const collecting = useAction(() => status.reload());
  const cleaning = useAction(() => status.reload());
  const s = status.data;
  const failing = s?.sources.filter((x) => x.enabled && x.last_status === "error") || [];
  const lastRun = s?.sources.map((x) => x.last_run_at).filter(Boolean).sort().at(-1);

  return (
    <Page
      title="What the layer holds"
      intro="Everything here stays on this laptop. Claude sees it only when it answers one of your questions."
      actions={
        <>
          <button type="button" className="button" disabled={collecting.busy} onClick={() => collecting.run(() => api("collect", { method: "POST" }))}>
            {collecting.busy ? "Collecting…" : "Collect now"}
          </button>
          <button type="button" className="button" disabled={cleaning.busy} onClick={() => cleaning.run(() => api("cleanup", { method: "POST" }))}>
            {cleaning.busy ? "Cleaning up…" : "Apply retention now"}
          </button>
        </>
      }
    >
      <Problem message={collecting.error || cleaning.error} />
      <Loading state={status}>
        {s && (
          <>
            {failing.length > 0 && (
              <div className="notice" role="status">
                <p>
                  {failing.length === 1 ? "One source" : `${failing.length} sources`} failed to collect:{" "}
                  {failing.map((x) => x.name).join(", ")}.
                </p>
                <button type="button" className="link" onClick={() => go("sources")}>See sources</button>
              </div>
            )}
            <dl className="facts">
              <div>
                <dt>Sources collected</dt>
                <dd>{s.sources.filter((x) => x.enabled).length}</dd>
                <dd className="quiet">last collected {whenUtc(lastRun)}</dd>
              </div>
              <div>
                <dt>Events</dt>
                <dd>{s.events.toLocaleString()}</dd>
                <dd className="quiet">commits, pushes and sessions</dd>
              </div>
              <div>
                <dt>Waiting for you to confirm</dt>
                <dd>{s.claims.proposed + s.claims.disputed}</dd>
                <dd className="quiet">{s.claims.supported} verified, {s.claims.retracted} retracted</dd>
              </div>
              <div>
                <dt>Confidential labels</dt>
                <dd>{s.confidential_labels}</dd>
                <dd className="quiet">hidden from Claude unless you ask</dd>
              </div>
            </dl>
            <h2>This installation</h2>
            <table className="table compact">
              <tbody>
                <tr><th scope="row">Version</th><td>{s.version}, Python {s.python}</td></tr>
                <tr><th scope="row">Store</th><td><code>{s.store.path}</code>, {(s.store.bytes / 1048576).toFixed(1)} MB, schema {s.store.schema_version}</td></tr>
                <tr><th scope="row">Retention last applied</th><td>{whenUtc(s.last_retention_at)}</td></tr>
                <tr><th scope="row">Session notes</th><td>{s.session_notes}</td></tr>
              </tbody>
            </table>
          </>
        )}
      </Loading>
    </Page>
  );
}
