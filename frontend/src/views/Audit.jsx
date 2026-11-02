import { whenUtc } from "../api.js";
import { Loading, Page, useLoad } from "../components/ui.jsx";

const ACTORS = { collector: "Collector", claude: "Claude", me: "You", retention: "Retention" };
const ACTIONS = {
  collect: "collected", propose: "proposed", revise: "revised", set_status: "changed the status of", label: "labelled",
  unlabel: "removed the label from", link: "linked", delete: "deleted", expire: "expired", settings: "changed settings for",
  read_confidential: "read the confidential",
};

export function Audit() {
  const list = useLoad("audit?limit=300");
  return (
    <Page title="Audit trail" intro="What was collected, changed, read or deleted, and by whom. Ids and counts only, never content.">
      <Loading state={list} empty="Nothing has happened yet.">
        <table className="table compact">
          <thead><tr><th>When</th><th>What happened</th></tr></thead>
          <tbody>
            {list.data?.map((a) => (
              <tr key={a.id}>
                <td className="nowrap">{whenUtc(a.at)}</td>
                <td>
                  {ACTORS[a.actor] || a.actor} {ACTIONS[a.action] || a.action} {a.count > 1 ? `${a.count} ` : ""}
                  {a.item_type.replace(/_/g, " ")}
                  {a.item_id && <> <code>{a.item_id}</code></>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Loading>
    </Page>
  );
}
