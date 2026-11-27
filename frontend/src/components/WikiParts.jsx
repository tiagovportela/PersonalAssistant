import { useEffect, useRef } from "react";
import { Icon } from "./Icon.jsx";

export const LABELS = ["verified", "repo", "unconfirmed", "disputed"];
export const LABEL_HELP = {
  verified: "Confirmed by you, or your own notes",
  repo: "Read from a repository at a commit",
  unconfirmed: "Proposed by Claude, not confirmed yet",
  disputed: "Cites a claim you disputed",
};

// A statement's label: a dot and the word, so it never rests on colour alone.
export function Label({ label }) {
  if (!LABELS.includes(label)) return null;
  return (
    <span className={`label ${label}`} title={LABEL_HELP[label]}>
      <span className="dot" aria-hidden="true" />{label}
    </span>
  );
}

// How much of the text rests on what: one rounded bar, and the numbers beside each label.
export function LabelBar({ counts }) {
  const total = LABELS.reduce((sum, l) => sum + (counts[l] || 0), 0);
  let x = 0;
  return (
    <div className="label-bar">
      {total > 0 ? (
        <svg viewBox="0 0 100 8" preserveAspectRatio="none" aria-hidden="true">
          {LABELS.map((l) => {
            const w = (100 * (counts[l] || 0)) / total;
            const seg = w > 0 && <rect key={l} className={`seg ${l}`} x={x} y="0" width={w} height="8" />;
            x += w;
            return seg;
          })}
        </svg>
      ) : <p className="quiet small">No statements yet.</p>}
      <ul className="legend">
        {LABELS.map((l) => (
          <li key={l}><Label label={l} /><span className="num">{counts[l] || 0}</span></li>
        ))}
      </ul>
    </div>
  );
}

function citeParts(c) {
  if (c.claim_id) return ["check", `claim ${c.claim_id}`, null, c.label];
  if (c.event_id) return ["pulse", `event ${c.event_id}`, null];
  if (c.commit) return ["commit", `${c.repo}@${c.commit.slice(0, 8)}${c.path ? `:${c.path}` : ""}`, c.url];
  if (c.page) return ["book", `page ${c.page}`, `#wiki/${encodeURIComponent(c.page)}`];
  return ["sources", JSON.stringify(c), null];
}

// What a statement rests on, in a popover that closes on Escape or a click elsewhere.
export function Sources({ cites }) {
  const box = useRef(null);
  useEffect(() => {
    const close = (e) => {
      const d = box.current;
      if (d?.open && (e.key === "Escape" || (e.type === "mousedown" && !d.contains(e.target)))) {
        d.open = false;
        if (e.key === "Escape") d.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, []);
  if (!cites?.length) return null;
  return (
    <details className="sources" ref={box}>
      <summary aria-label={`${cites.length} source${cites.length === 1 ? "" : "s"}`}>
        <Icon name="sources" />{cites.length}
      </summary>
      <ul className="popover">
        {cites.map((c, i) => {
          const [icon, text, url, label] = citeParts(c);
          return (
            <li key={i}>
              <Icon name={icon} />
              {url ? <a className="mono" href={url} {...(url.startsWith("https://") ? { target: "_blank", rel: "noopener noreferrer" } : {})}>{text}</a>
                : <span className="mono">{text}</span>}
              {label && <Label label={label} />}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

// A search snippet: the store marks matches with « », shown here as highlights.
export function Snippet({ text }) {
  return (
    <>
      {(text || "").split(/(«[^»]*»)/).map((part, i) => (part.startsWith("«") ? <mark key={i}>{part.slice(1, -1)}</mark> : part))}
    </>
  );
}

// A modal dialog: opens on mount, closes on Escape, and gives focus back.
export function Modal({ title, onClose, children, wide }) {
  const ref = useRef(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return (
    <dialog ref={ref} className={`dialog${wide ? " wide" : ""}`} onClose={onClose} aria-labelledby="modal-title">
      <h2 id="modal-title">{title}</h2>
      {children}
    </dialog>
  );
}
