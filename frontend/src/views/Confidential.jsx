import { api, whenUtc } from "../api.js";
import { Loading, Page, Problem, Redacted, useAction, useLoad } from "../components/ui.jsx";

const TYPE_NAMES = { project: "Project", source: "Source", event: "Event", claim: "Claim", artifact: "Online item" };

export function Confidential() {
  const list = useLoad("labels");
  const removing = useAction(() => list.reload());

  return (
    <Page
      title="Confidential"
      intro="Labelled items never reach Claude unless you ask for one by name, and you approve it. Only here can a label be removed."
    >
      <Problem message={removing.error} />
      <Loading state={list} empty="Nothing is labelled confidential. Mark items from Projects, Claims or Activity.">
        <table className="table">
          <thead>
            <tr><th>Item</th><th>Labelled</th><th><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {list.data?.map((l) => (
              <tr key={`${l.type}:${l.id}`}>
                <td>
                  <span className="quiet">{TYPE_NAMES[l.type] || l.type}</span> <Redacted>{l.name}</Redacted>
                </td>
                <td>{l.set_by === "me" ? "by you" : "by Claude, with your approval"}, {whenUtc(l.set_at)}</td>
                <td className="actions">
                  <button
                    type="button"
                    className="link"
                    disabled={removing.busy}
                    onClick={() => removing.run(() => api(`labels/${encodeURIComponent(l.type)}/${encodeURIComponent(l.id)}`, { method: "DELETE" }))}
                  >
                    Remove label
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Loading>
    </Page>
  );
}
