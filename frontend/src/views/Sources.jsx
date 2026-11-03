import { useState } from "react";
import { api, whenUtc } from "../api.js";
import { DeleteDialog } from "../components/DeleteDialog.jsx";
import { Loading, Page, Problem, useAction, useLoad } from "../components/ui.jsx";

const KIND_NAMES = {
  git_repo: "Git repository",
  claude_code: "Claude Code sessions",
  firefox: "Firefox history",
  app_usage: "App usage",
};
const MODES = {
  titles: ["App names and window titles", "Shows which document or page had your attention."],
  apps: ["App names only", "No window titles are stored."],
  time: ["Active and idle time only", "Nothing about which apps you use."],
};

function FirefoxRow({ firefox, onChanged }) {
  const adding = useAction(onChanged);
  const on = firefox.sources.find((s) => s.enabled);
  return (
    <tr className={on ? "" : "off"}>
      <td>
        <strong>Firefox history</strong>
        <div className="quiet">
          Every page you open, read from a copy of Firefox's history each hour. Secret-looking parts of addresses
          (tokens, codes, keys, sessions) are removed, and local addresses such as this page are never stored.
        </div>
      </td>
      <td>
        {on ? (
          <span>On</span>
        ) : (
          <button
            type="button"
            className="button"
            disabled={adding.busy || !firefox.detected_profile}
            onClick={() => adding.run(() => api("firefox", { method: "POST" }))}
          >
            {adding.busy ? "Turning on…" : "Read Firefox history"}
          </button>
        )}
      </td>
      <td className="small">
        {on ? <code>{on.locator}</code> : firefox.detected_profile ? <>Profile found: <code>{firefox.detected_profile}</code></> : "No Firefox profile with history was found. Open Firefox once, then reload this page."}
        {on && <div className="quiet">Turn it off, or delete what was read, in the table below.</div>}
        <Problem message={adding.error} />
      </td>
    </tr>
  );
}

function AppUsageRow({ usage, onChanged }) {
  const [result, setResult] = useState(null);
  const saving = useAction((r) => { setResult(r); onChanged(); });
  const save = (body) => saving.run(() => api("app-usage", { method: "PUT", body }));
  const gnome = usage.gnome;
  const extension = gnome.running
    ? "The window extension is running."
    : gnome.installed
      ? "The window extension is installed; log out and back in once so GNOME loads it."
      : gnome.supported
        ? "The window extension isn't installed yet; it's installed when you turn this on."
        : `GNOME Shell ${gnome.gnome_shell || "wasn't found"}: the reviewed window extension supports ${gnome.supported_versions.join(", ")}, so only active and idle time can be recorded.`;
  return (
    <tr className={usage.on ? "" : "off"}>
      <td>
        <strong>App usage</strong>
        <div className="quiet">
          Every 10 seconds: the focused window and the time since your last input, saved every 5 minutes. Never what you
          type, the clipboard or the screen. Private browsing and password manager windows keep no title.
        </div>
      </td>
      <td>
        <label className="switch">
          <input type="checkbox" checked={!!usage.on} disabled={saving.busy} onChange={(e) => save({ enabled: e.target.checked, mode: usage.mode })} />
          <span>{usage.on ? "On" : "Off"}</span>
        </label>
      </td>
      <td>
        <fieldset className="modes">
          <legend className="sr-only">What to record</legend>
          {usage.modes.map((m) => (
            <label key={m} className="choice">
              <input
                type="radio"
                name="app-usage-mode"
                checked={usage.mode === m}
                disabled={saving.busy}
                onChange={() => save({ enabled: usage.on, mode: m })}
              />
              <span>{MODES[m][0]} <span className="quiet small">{MODES[m][1]}</span></span>
            </label>
          ))}
        </fieldset>
        <p className="small">{extension}</p>
        {usage.on && usage.fallback && <p className="small problem">{usage.fallback}</p>}
        {usage.on && usage.average_sample_ms != null && (
          <p className="quiet small">
            Recording {MODES[usage.mode_in_use]?.[0].toLowerCase()}; {usage.average_sample_ms} ms per sample, last saved {whenUtc(usage.last_sample_at)}.
          </p>
        )}
        {result?.todo?.map((step) => <p key={step} className="notice small">{step}</p>)}
        <Problem message={result?.problem || saving.error} />
      </td>
    </tr>
  );
}

function OnThisLaptop({ onChanged }) {
  const state = useLoad("activity-sources");
  const changed = () => { state.reload(); onChanged(); };
  return (
    <>
      <h2>Firefox and app usage</h2>
      <Loading state={state}>
        {state.data && (
          <table className="table">
            <thead><tr><th>Source</th><th>Collecting</th><th>Details</th></tr></thead>
            <tbody>
              <FirefoxRow firefox={state.data.firefox} onChanged={changed} />
              <AppUsageRow usage={state.data.app_usage} onChanged={changed} />
            </tbody>
          </table>
        )}
      </Loading>
    </>
  );
}

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
      intro="Only what you add here is read. A folder adds every Git repository in it; add it again to pick up new ones. Firefox history and app usage are turned on just below."
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
      <OnThisLaptop onChanged={list.reload} />
      <h2>Everything collected</h2>
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
