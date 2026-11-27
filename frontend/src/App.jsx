import { useEffect, useState } from "react";
import { Icon } from "./components/Icon.jsx";
import { Audit } from "./views/Audit.jsx";
import { Claims } from "./views/Claims.jsx";
import { Confidential } from "./views/Confidential.jsx";
import { Events } from "./views/Events.jsx";
import { Online } from "./views/Online.jsx";
import { Overview } from "./views/Overview.jsx";
import { Projects } from "./views/Projects.jsx";
import { Retention } from "./views/Retention.jsx";
import { Sources } from "./views/Sources.jsx";
import { Wiki } from "./views/Wiki.jsx";

// [id, name, icon, view]; the groups are only for the sidebar.
const GROUPS = [
  ["Work", [
    ["overview", "Overview", "overview", Overview],
    ["wiki", "Wiki", "book", Wiki],
    ["claims", "Claims", "check", Claims],
    ["projects", "Projects", "folder", Projects],
    ["activity", "Activity", "pulse", Events],
  ]],
  ["Sources", [
    ["sources", "Sources", "database", Sources],
    ["online", "Online sources", "globe", Online],
  ]],
  ["Privacy", [
    ["confidential", "Confidential", "lock", Confidential],
    ["retention", "Retention", "clock", Retention],
    ["audit", "Audit trail", "list", Audit],
  ]],
];
const SECTIONS = GROUPS.flatMap(([, items]) => items);

// The hash is the section, then an optional path inside it: #wiki/atlas.
function current() {
  const [id, ...rest] = window.location.hash.slice(1).split("/");
  const section = SECTIONS.some(([s]) => s === id) ? id : "overview";
  return { section, route: section === id ? decodeURIComponent(rest.join("/")) : "" };
}

export function App() {
  const [where, setWhere] = useState(current);
  useEffect(() => {
    const follow = () => { setWhere(current()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  const go = (id) => { window.location.hash = id; };
  const [, , , View] = SECTIONS.find(([id]) => id === where.section);

  return (
    <div className="shell">
      <aside className="rail" aria-label="Sections">
        <p className="wordmark"><span className="brand-mark" aria-hidden="true" />Work layer</p>
        <nav>
          {GROUPS.map(([group, items]) => (
            <div className="nav-group" key={group}>
              <p className="nav-title">{group}</p>
              <ul>
                {items.map(([id, name, icon]) => (
                  <li key={id}>
                    <a href={`#${id}`} aria-current={id === where.section ? "page" : undefined}>
                      <Icon name={icon} />{name}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <p className="rail-foot">Open only on this laptop, at 127.0.0.1. Run <code>pwi open</code> to sign in again.</p>
      </aside>
      <main id="main">
        <View go={go} route={where.route} />
      </main>
    </div>
  );
}
