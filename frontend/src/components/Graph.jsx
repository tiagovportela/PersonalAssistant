import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { forceLayout } from "../lib/forceLayout.js";

const KIND_NAMES = { project: "Project", person: "Person", topic: "Topic" };

function short(text, size = 24) {
  return text.length > size ? `${text.slice(0, size - 1)}…` : text;
}

// A map of wiki pages: each page a dot coloured by kind (and named in its tooltip and label, never by colour alone),
// each link a line. Hovering or focusing a page brings its neighbours forward; Enter or a click opens it.
// It's laid out at the width it's shown at, so text keeps its size: no scaling.
export function Graph({ nodes, edges, size = "full", here, href, label = "Map of wiki pages" }) {
  const box = useRef(null);
  const [W, setW] = useState(size === "full" ? 880 : 300);
  const H = size === "full" ? (W < 520 ? 380 : 520) : 240;
  useLayoutEffect(() => {
    const measure = () => { const w = Math.round(box.current?.clientWidth || 0); if (w > 0) setW(w); };
    measure();
    const watch = new ResizeObserver(measure);
    if (box.current) watch.observe(box.current);
    return () => watch.disconnect();
  }, []);
  const { points, links } = useMemo(() => forceLayout(nodes, edges, W, H), [nodes, edges, W, H]);
  const [focus, setFocus] = useState(null);
  const [tip, setTip] = useState(null);
  const near = useMemo(() => {
    if (!focus) return null;
    const ids = new Set([focus]);
    links.forEach((e) => { if (e.from === focus) ids.add(e.to); if (e.to === focus) ids.add(e.from); });
    return ids;
  }, [focus, links]);

  const show = (n, x, y) => { setFocus(n.id); setTip({ n, x, y }); };
  const hide = () => { setFocus(null); setTip(null); };

  return (
    <div className="graph-box" ref={box}>
      {nodes.length === 0 ? <p className="empty">No pages to show.</p> : (
      <svg className={`graph ${size}${focus ? " focused" : ""}`} viewBox={`0 0 ${W} ${H}`} width={W} height={H}
        role="group" aria-label={label}>
        <g>
          {links.map((e) => {
            const a = points.get(e.from), b = points.get(e.to);
            const lit = focus && (e.from === focus || e.to === focus);
            return <line key={`${e.from}>${e.to}`} className={lit ? "near" : undefined} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />;
          })}
        </g>
        <g>
          {nodes.map((n) => {
            const p = points.get(n.id);
            const r = Math.min(14, 6 + p.degree * 1.5);
            const left = p.x > W * 0.72;
            const name = `${n.title} (${KIND_NAMES[n.kind] || n.kind}${n.stale ? ", stale" : ""}${n.compiled === false ? ", not written yet" : ""})`;
            const classes = ["node", n.kind, n.id === here && "here", n.stale && "stale", n.compiled === false && "unwritten",
              near?.has(n.id) && "near"].filter(Boolean).join(" ");
            return (
              <a key={n.id} href={href(n.id)} className={classes} aria-label={name}
                onMouseEnter={(e) => show(n, e.clientX, e.clientY)} onMouseMove={(e) => setTip({ n, x: e.clientX, y: e.clientY })}
                onMouseLeave={hide} onBlur={hide}
                onFocus={(e) => { const rect = e.currentTarget.getBoundingClientRect(); show(n, rect.right, rect.top); }}>
                <circle cx={p.x} cy={p.y} r={r} />
                <text x={left ? p.x - r - 6 : p.x + r + 6} y={p.y + 4} className={left ? "end" : undefined}>{short(n.title)}</text>
              </a>
            );
          })}
        </g>
      </svg>
      )}
      {tip && (
        <div className="tooltip" role="tooltip" style={{ left: `${tip.x + 14}px`, top: `${tip.y + 14}px` }}>
          <strong>{tip.n.title}</strong>
          <span>
            {KIND_NAMES[tip.n.kind] || tip.n.kind}
            {tip.n.compiled === false ? " · not written yet" : ""}
            {tip.n.stale ? " · stale" : ""}
            {near ? ` · ${near.size - 1} linked` : ""}
          </span>
        </div>
      )}
    </div>
  );
}
