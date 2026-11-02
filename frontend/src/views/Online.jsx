import { useState } from "react";
import { api, whenUtc } from "../api.js";
import { Loading, Page, Problem, useAction, useLoad } from "../components/ui.jsx";

const CONNECTORS = {
  github: ["GitHub", "Pull requests, reviews, CI and releases", "acme organisation"],
  google_calendar: ["Google Calendar", "Meetings and their attendees", "work calendar only"],
  notion: ["Notion", "Tasks, deadlines and pages", "Engineering teamspace"],
  gmail: ["Gmail", "Requests, promises and decisions in threads", "label:work"],
  google_chat: ["Google Chat", "Requests, promises and decisions in spaces", "Billing team, Data guild"],
  google_drive: ["Google Drive", "Documents you write or edit", "Work/Projects folder"],
};

function Connector({ connector, onSaved }) {
  const [name, what, example] = CONNECTORS[connector.provider];
  const [scope, setScope] = useState(connector.scope || "");
  const saving = useAction(onSaved);
  const save = (changes) => saving.run(() => api(`connectors/${connector.provider}`, { method: "PUT", body: changes }));

  return (
    <tr className={connector.enabled ? "" : "off"}>
      <td>
        <strong>{name}</strong>
        <div className="quiet">{what}</div>
        {connector.through_layer && (
          <div className="small">
            {connector.signed_in_as
              ? <>Read by the layer itself, signed in as {connector.signed_in_as}, read-only.</>
              : <>Read by the layer itself. Sign in first with <code>pwi google connect CLIENT_JSON</code>.</>}
            {connector.signed_in_as && !connector.token_in_keyring && (
              <span className="quiet"> The sign-in is in a file; install libsecret-tools to keep it in GNOME Keyring.</span>
            )}
          </div>
        )}
      </td>
      <td>
        <label className="switch">
          <input type="checkbox" checked={!!connector.enabled} onChange={(e) => save({ enabled: e.target.checked })} />
          <span>{connector.enabled ? "Allowed" : "Off"}</span>
        </label>
      </td>
      <td>
        <form className="row scope" onSubmit={(e) => { e.preventDefault(); save({ scope }); }}>
          <input
            aria-label={`What Claude may read in ${name}`}
            value={scope}
            onChange={(e) => setScope(e.target.value)}
            placeholder={`e.g. ${example}`}
          />
          <button type="submit" className="button" disabled={saving.busy || scope === (connector.scope || "")}>Save</button>
        </form>
        <div className="quiet small">
          {connector.scope ? "" : "Empty means everything you can see there. "}Changed {whenUtc(connector.changed_at)}.
        </div>
        <Problem message={saving.error} />
      </td>
    </tr>
  );
}

export function Online() {
  const list = useLoad("connectors");
  return (
    <Page
      title="Online sources"
      intro="Claude reads these live through its connectors when it answers you; the layer keeps no copy. It uses only the ones you allow, within the scope you write here, plus each project's aliases."
    >
      <Loading state={list}>
        <table className="table">
          <thead><tr><th>Source</th><th>Claude may use it</th><th>Only within</th></tr></thead>
          <tbody>
            {list.data?.map((c) => <Connector key={`${c.provider}:${c.changed_at}`} connector={c} onSaved={list.reload} />)}
          </tbody>
        </table>
      </Loading>
      <p className="quiet">
        Connectors themselves are set up in Claude Desktop. This page only tells Claude which of them it may use for your work.
        Google Chat is the exception: the layer reads it itself, so this page is enforced, not just followed.
      </p>
    </Page>
  );
}
