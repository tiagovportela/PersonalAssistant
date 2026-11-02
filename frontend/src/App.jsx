import { useEffect, useState } from "react";
import { Audit } from "./views/Audit.jsx";
import { Claims } from "./views/Claims.jsx";
import { Confidential } from "./views/Confidential.jsx";
import { Events } from "./views/Events.jsx";
import { Overview } from "./views/Overview.jsx";
import { Projects } from "./views/Projects.jsx";
import { Retention } from "./views/Retention.jsx";
import { Sources } from "./views/Sources.jsx";

const SECTIONS = [
  ["overview", "Overview", Overview],
  ["sources", "Sources", Sources],
  ["projects", "Projects", Projects],
  ["claims", "Claims", Claims],
  ["activity", "Activity", Events],
  ["confidential", "Confidential", Confidential],
  ["retention", "Retention", Retention],
  ["audit", "Audit trail", Audit],
];

function current() {
  const hash = window.location.hash.slice(1);
  return SECTIONS.some(([id]) => id === hash) ? hash : "overview";
}

export function App() {
  const [section, setSection] = useState(current);
  useEffect(() => {
    const follow = () => setSection(current());
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  const go = (id) => { window.location.hash = id; };
  const [, , View] = SECTIONS.find(([id]) => id === section);

  return (
    <div className="shell">
      <nav className="rail" aria-label="Sections">
        <p className="wordmark">Work layer</p>
        <ul>
          {SECTIONS.map(([id, name]) => (
            <li key={id}>
              <a href={`#${id}`} aria-current={id === section ? "page" : undefined}>{name}</a>
            </li>
          ))}
        </ul>
        <p className="rail-foot">Open only on this laptop, at 127.0.0.1. Run <code>pwi open</code> to sign in again.</p>
      </nav>
      <main id="main">
        <View go={go} />
      </main>
    </div>
  );
}
