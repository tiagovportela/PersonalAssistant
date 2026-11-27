import { useEffect, useMemo, useRef, useState } from "react";
import { api, whenUtc } from "../api.js";
import { Graph } from "../components/Graph.jsx";
import { Icon } from "../components/Icon.jsx";
import { Label, LabelBar, LABELS, Modal, Snippet, Sources } from "../components/WikiParts.jsx";
import { Loading, Page, Problem, useAction, useLoad } from "../components/ui.jsx";

const KINDS = ["project", "topic", "person"];
const KIND_ONE = { project: "Project", person: "Person", topic: "Topic" };
const KIND_MANY = { project: "Projects", person: "People", topic: "Topics" };
const PROBLEM_NAMES = {
  not_written: "Not written", stale: "Stale", lost_evidence: "Evidence gone", disputed: "Cites disputed claims",
  file_changed: "Cited file changed", diagram_stale: "Diagram out of date", broken_link: "Broken link",
  orphan: "Nothing links here", topic_one_project: "Topic with one project", near_budget: "Near its size limit",
};
const pageHref = (id, section) => `#wiki/${encodeURIComponent(id)}${section ? `/${encodeURIComponent(section)}` : ""}`;
const by = (who) => (who === "me" ? "you" : "Claude");
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export function Wiki({ route }) {
  if (route) {
    const [id, section] = route.split("/");
    return <WikiPage key={id} id={id} section={section} />;
  }
  return <WikiHome />;
}

// The wiki at a glance ----------------------------------------------------------------------------------

function Search() {
  const [text, setText] = useState("");
  const [found, setFound] = useState(null);
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    const q = text.trim();
    if (q.length < 2) { setFound(null); return undefined; }
    let current = true;
    const timer = setTimeout(() => {
      api(`wiki-search?q=${encodeURIComponent(q)}`)
        .then((d) => current && setFound({ results: d.results }))
        .catch((e) => current && setFound({ error: e.message }));
    }, 200);
    return () => { current = false; clearTimeout(timer); };
  }, [text]);
  const results = found?.results || [];
  return (
    <div className="w-search" ref={box}
      onBlur={(e) => { if (!box.current.contains(e.relatedTarget)) setOpen(false); }}
      onKeyDown={(e) => { if (e.key === "Escape") { setOpen(false); box.current.querySelector("input").focus(); } }}>
      <Icon name="search" />
      <input type="search" value={text} placeholder="Search the wiki" aria-label="Search the wiki" autoComplete="off"
        aria-expanded={open && Boolean(found)} aria-controls="wiki-results"
        onChange={(e) => { setText(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} />
      {open && found && (
        <div className="popover w-results" id="wiki-results" role="region" aria-label="Search results" aria-live="polite">
          {found.error && <p className="problem">{found.error}</p>}
          {!found.error && results.length === 0 && <p>Nothing matches “{text.trim()}”.</p>}
          {results.map((r, i) => (
            <a key={i} href={pageHref(r.page, r.section)} onClick={() => setOpen(false)}>
              <strong>{r.title}</strong>{r.heading ? <span className="quiet"> · {r.heading}</span> : null}
              {r.stale && <span className="w-state stale">stale</span>}
              <span className="snippet"><Snippet text={r.snippet || r.summary} /></span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function Finding({ f, withPage }) {
  return (
    <li className="w-row">
      <span className="w-row-main">
        <span>
          {withPage && <><a href={pageHref(f.page, f.section)}>{f.page}</a> · </>}
          <strong>{PROBLEM_NAMES[f.problem] || f.problem}</strong>
          {f.section && <span className="quiet"> in {f.section}</span>}
        </span>
        <span className="quiet">{f.detail}</span>
      </span>
    </li>
  );
}

function Catalog({ pages }) {
  return (
    <div className="w-catalog">
      {KINDS.map((kind) => {
        const entries = pages.filter((p) => p.kind === kind);
        return (
          <div key={kind}>
            <h3><span className={`kind-dot ${kind}`} aria-hidden="true" />{KIND_MANY[kind]} <span className="count">{entries.length}</span></h3>
            {entries.length === 0 ? <p className="quiet small">None yet.</p> : (
              <ul className="w-rows">
                {entries.map((p) => (
                  <li key={p.page} className="w-row">
                    <span className="w-row-main">
                      <a href={pageHref(p.page)}>{p.title}</a>
                      <span className="quiet">{p.summary || (p.version ? "" : "Not written yet")}</span>
                    </span>
                    <span className="w-row-meta">
                      {p.confidential && <span className="w-state" title="Confidential: Claude never sees it"><Icon name="lock" label="Confidential" /></span>}
                      {p.has_notes && <Icon name="note" label="Has your notes" />}
                      {p.stale && <span className="w-state stale">stale</span>}
                      {p.version ? <span className="num">v{p.version}</span> : null}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

function WikiHome() {
  const wiki = useLoad("wiki");
  const [kind, setKind] = useState("all");
  const [everything, setEverything] = useState(false);
  const building = useAction(wiki.reload);
  const data = wiki.data;
  const shown = useMemo(() => {
    if (!data) return { nodes: [], edges: [] };
    const nodes = data.graph.nodes.filter((n) => kind === "all" || n.kind === kind);
    const ids = new Set(nodes.map((n) => n.id));
    return { nodes, edges: data.graph.edges.filter((e) => ids.has(e.from) && ids.has(e.to)) };
  }, [data, kind]);
  const findings = data?.lint.findings || [];
  const written = data?.pages.filter((p) => p.version > 0) || [];
  const recent = [...written].sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || "")).slice(0, 6);

  return (
    <Page
      title="Wiki"
      intro="What Claude knows about your work, one page per project, person and topic, every statement labelled with what it rests on."
      actions={<Search />}
    >
      <Loading state={wiki}>
        {data && (
          <div className="bento">
            <section className="panel w-metrics" aria-label="The wiki in numbers">
              <div className="w-metric">
                <p className="w-metric-label">Pages written</p>
                <p className="w-metric-value">{written.length}</p>
                <p className="quiet small">of {plural(data.pages.length, "page")}</p>
              </div>
              <div className="w-metric">
                <p className="w-metric-label">Stale</p>
                <p className="w-metric-value">{data.pages.filter((p) => p.stale).length}</p>
                <p className="quiet small">behind their evidence</p>
              </div>
              <div className="w-metric">
                <p className="w-metric-label">Needs attention</p>
                <p className="w-metric-value">{findings.length}</p>
                <p className="quiet small">{findings.length ? "findings to fix" : "nothing to fix"}</p>
              </div>
              <div className="w-metric">
                <p className="w-metric-label">Searches that missed</p>
                <p className="w-metric-value">{data.misses.length}</p>
                <p className="quiet small">pages worth writing</p>
              </div>
              <div className="w-metric wide">
                <p className="w-metric-label">What the text rests on</p>
                <LabelBar counts={data.labels} />
              </div>
            </section>

            <section className="panel w-map" aria-labelledby="map-title">
              <div className="panel-head">
                <h2 id="map-title"><Icon name="globe" />Map</h2>
                <div className="segmented" role="group" aria-label="Show on the map">
                  {["all", ...KINDS].map((k) => (
                    <button key={k} type="button" className="segment" aria-pressed={kind === k} onClick={() => setKind(k)}>
                      {k === "all" ? "All" : KIND_MANY[k]}
                    </button>
                  ))}
                </div>
              </div>
              <Graph nodes={shown.nodes} edges={shown.edges} href={(id) => pageHref(id)} />
              <ul className="legend">
                {KINDS.map((k) => <li key={k}><span className={`kind-dot ${k}`} aria-hidden="true" />{KIND_ONE[k]}</li>)}
                <li><span className="kind-dot ring" aria-hidden="true" />Stale</li>
                <li><span className="kind-dot faint" aria-hidden="true" />Not written yet</li>
              </ul>
            </section>

            <section className="panel" aria-labelledby="attention-title">
              <div className="panel-head">
                <h2 id="attention-title"><Icon name="alert" />Needs attention <span className="count">{findings.length}</span></h2>
              </div>
              {findings.length === 0 ? <p className="empty">Nothing: every page is current and its evidence stands.</p> : (
                <>
                  <ul className="w-rows">
                    {(everything ? findings : findings.slice(0, 6)).map((f, i) => <Finding key={i} f={f} withPage />)}
                  </ul>
                  {findings.length > 6 && (
                    <button type="button" className="link small" onClick={() => setEverything(!everything)}>
                      {everything ? "Show fewer" : `Show all ${findings.length}`}
                    </button>
                  )}
                </>
              )}
            </section>

            <section className="panel" aria-labelledby="recent-title">
              <div className="panel-head"><h2 id="recent-title"><Icon name="history" />Recently updated</h2></div>
              {recent.length === 0 ? <p className="empty">No page written yet. The compile run writes them, or ask Claude to.</p> : (
                <ul className="w-rows">
                  {recent.map((p) => (
                    <li key={p.page} className="w-row">
                      <span className="w-row-main">
                        <a href={pageHref(p.page)}>{p.title}</a>
                        <span className="quiet">v{p.version} by {by(p.written_by)}</span>
                      </span>
                      <span className="w-row-meta nowrap">{whenUtc(p.updated_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="panel w-wide" aria-labelledby="pages-title">
              <div className="panel-head"><h2 id="pages-title"><Icon name="book" />Pages</h2></div>
              <Catalog pages={data.pages} />
            </section>

            <section className="panel w-span2" aria-labelledby="misses-title">
              <div className="panel-head">
                <h2 id="misses-title"><Icon name="search" />Searches that found nothing</h2>
                <span className="quiet small">kept 90 days</span>
              </div>
              {data.misses.length === 0 ? <p className="empty">None recorded.</p> : (
                <ul className="w-rows">
                  {data.misses.slice(0, 8).map((m, i) => (
                    <li key={i} className="w-row">
                      <span className="w-row-main"><span>“{m.query}”</span>{m.project_id && <span className="quiet">in {m.project_id}</span>}</span>
                      <span className="w-row-meta nowrap">{whenUtc(m.at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="panel" aria-labelledby="site-title">
              <div className="panel-head"><h2 id="site-title"><Icon name="out" />Site for agents</h2></div>
              <p className="small">
                Plain HTML, Markdown, JSON and the diagrams as SVG and PNG, for agents that read files. Start at{" "}
                <code>llms.txt</code>; open it with <code>pwi wiki open</code>.
              </p>
              <dl className="pairs">
                <dt>Folder</dt><dd className="mono">{data.site.path}</dd>
                <dt>Built</dt>
                <dd>{data.site.built ? `${whenUtc(data.site.built_at)}${data.site.seconds ? ` in ${data.site.seconds} s` : ""}` : "Not yet"}</dd>
              </dl>
              <p className="quiet small">It rebuilds itself within a minute of any change.</p>
              <button type="button" className="button" disabled={building.busy}
                onClick={() => building.run(() => api("wiki/build", { method: "POST" }))}>
                <Icon name="refresh" />{building.busy ? "Building…" : "Rebuild now"}
              </button>
              <Problem message={building.error} />
            </section>
          </div>
        )}
      </Loading>
    </Page>
  );
}

// One page ------------------------------------------------------------------------------------------------

// A diagram's node that stands for a page opens it.
function followPageLinks(event) {
  const node = event.target.closest?.("[data-page]");
  if (node) { window.location.hash = pageHref(node.getAttribute("data-page")); }
}

function Figure({ b }) {
  if (b.kind === "diagram") {
    const d = b.diagram;
    return (
      <figure className="w-figure" id={b.id}>
        <div className="w-figure-head">
          <div>
            <p className="w-figure-title">{d.title}</p>
            {d.caption && <p className="quiet small">{d.caption}</p>}
          </div>
          <span className="w-figure-meta"><Label label={b.label} /><Sources cites={b.cites} /></span>
        </div>
        {/* SVG drawn and escaped by the service (diagrams.py) */}
        <div className="drawing" onClick={followPageLinks} dangerouslySetInnerHTML={{ __html: b.svg }} />
        <details className="as-text">
          <summary>Diagram as text</summary>
          <ul>{(b.text_lines || []).map((line, i) => <li key={i}>{line}</li>)}</ul>
        </details>
      </figure>
    );
  }
  return (
    <figure className="w-figure" id={b.id}>
      <div className="w-figure-head">
        <p className="w-figure-title">{b.caption || b.image.path}</p>
        <span className="w-figure-meta"><Label label={b.label} /><Sources cites={b.cites} /></span>
      </div>
      {b.src ? <img src={b.src} alt={b.caption || b.image.path} loading="lazy" />
        : <p className="quiet small">{b.image.path} couldn't be read from {b.image.repo}.</p>}
    </figure>
  );
}

function Statement({ b, as: Tag = "div" }) {
  return (
    <Tag className="statement" id={b.id}>
      {/* HTML escaped by the service (wiki_render.inline): only the allowed marks are tags */}
      <span className="st-text" dangerouslySetInnerHTML={{ __html: b.html }} />
      <span className="st-meta"><Label label={b.label} /><Sources cites={b.cites} /></span>
    </Tag>
  );
}

function Written({ blocks }) {
  const out = [];
  let run = [];
  const flush = () => {
    if (run.length) out.push(<ul className="bullets" key={`ul-${run[0].id}`}>{run.map((b) => <Statement key={b.id} b={b} as="li" />)}</ul>);
    run = [];
  };
  for (const b of blocks) {
    if (b.kind === "diagram" || b.kind === "image") { flush(); out.push(<Figure key={b.id} b={b} />); }
    else if (b.style === "bullet") run.push(b);
    else { flush(); out.push(<Statement key={b.id} b={b} />); }
  }
  flush();
  return out;
}

function ClaimRow({ c }) {
  const mine = c.direction === "mine";
  const who = c.direction ? (mine ? c.counterparty : c.owner) || "someone" : null;
  const when = (c.due_at || c.about_day || "").slice(0, 10);
  return (
    <li className="w-row">
      <span className="w-row-main">
        <span>{c.text}</span>
        {who && <span className="who">{mine ? "You owe" : "Owed to you by"} {who}</span>}
      </span>
      <span className="w-row-meta">
        {when && <span className={`date${c.overdue ? " overdue" : ""}`}>{c.overdue ? "overdue · " : ""}{when}</span>}
        <Label label={c.label} />
      </span>
    </li>
  );
}

function initials(name) {
  return String(name).split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
}

function Generated({ s }) {
  const items = s.items || [];
  if (!items.length) return <p className="quiet small">{s.summary}</p>;
  if (s.id === "decisions") {
    const months = {};
    items.forEach((c) => { const m = (c.about_day || "").slice(0, 7) || "undated"; (months[m] ||= []).push(c); });
    return (
      <ol className="timeline">
        {Object.keys(months).sort().reverse().map((m) => (
          <li key={m}>
            <p className="month">{m}</p>
            <ul className="w-rows">{months[m].map((c) => <ClaimRow key={c.claim_id} c={c} />)}</ul>
          </li>
        ))}
      </ol>
    );
  }
  if (s.id === "commitments" || s.id === "open-work") {
    return <ul className="w-rows">{items.map((c) => <ClaimRow key={c.claim_id} c={c} />)}</ul>;
  }
  if (s.id === "where-it-lives") {
    return (
      <dl className="pairs">
        {items.map((a, i) => (
          <div key={i} className="pair">
            <dt>{a.kind.replaceAll("_", " ")}</dt>
            <dd>{String(a.value).startsWith("https://")
              ? <a href={a.value} target="_blank" rel="noopener noreferrer">{a.value}</a> : <span className="mono">{a.value}</span>}</dd>
          </div>
        ))}
      </dl>
    );
  }
  if (s.id === "repo-map" && s.svgs) {
    return s.svgs.map((svg, i) => <div key={i} className="drawing" dangerouslySetInnerHTML={{ __html: svg }} />);
  }
  if (s.id === "activity" && s.svg) {
    return <div className="drawing" dangerouslySetInnerHTML={{ __html: s.svg }} />;
  }
  return (
    <ul className="w-rows">
      {items.map((i, n) => {
        const name = i.title || i.person || i.project || i.page;
        const counts = ["claims", "commits"].filter((k) => i[k]).map((k) => plural(i[k], k.slice(0, -1))).join(", ");
        return (
          <li key={n} className="w-row">
            <span><span className="avatar" aria-hidden="true">{initials(name)}</span>{i.page ? <a href={pageHref(i.page)}>{name}</a> : name}</span>
            {counts && <span className="w-row-meta">{counts}</span>}
          </li>
        );
      })}
    </ul>
  );
}

function Section({ s }) {
  return (
    <section className="w-section" id={`sec-${s.id}`} aria-labelledby={`h-${s.id}`}>
      <div className="w-section-head">
        <h2 id={`h-${s.id}`}>{s.heading}</h2>
        <span className="w-source">{s.source === "generated" ? "From your data" : "Written"}</span>
      </div>
      {s.source === "generated" && s.items?.length > 0 && s.summary && <p className="w-summary">{s.summary}</p>}
      {s.source === "generated" ? <Generated s={s} /> : <Written blocks={s.blocks || []} />}
    </section>
  );
}

function Diff({ page, from, to }) {
  const diff = useLoad(`wiki/${encodeURIComponent(page)}/diff?from=${from}&to=${to}`);
  const changed = diff.data?.sections.filter((s) => s.change !== "same") || [];
  return (
    <Loading state={diff}>
      <div className="w-diff">
        {diff.data && changed.length === 0 && <p className="quiet">No change in the text.</p>}
        {changed.map((s) => (
          <div key={s.id}>
            <p><strong>{s.heading}</strong> <span className="quiet small">{s.change}</span></p>
            <ul>
              {s.lines.filter((l) => l.op !== " ").map((l, i) => (
                <li key={i} className={l.op === "+" ? "added" : "removed"}>
                  <span className="sr-only">{l.op === "+" ? "Added: " : "Removed: "}</span>{l.text}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Loading>
  );
}

function Notes({ p, onSaved }) {
  const [text, setText] = useState(p.notes?.text || "");
  const saving = useAction(onSaved);
  const save = (e) => {
    e.preventDefault();
    saving.run(() => api(`wiki/${encodeURIComponent(p.page)}/notes`, { method: "PUT", body: { text } }));
  };
  return (
    <form className="panel w-notes" onSubmit={save} aria-labelledby="notes-title">
      <h3 id="notes-title"><Icon name="note" />Your notes</h3>
      <textarea rows={4} value={text} maxLength={4000} onChange={(e) => setText(e.target.value)}
        aria-describedby="notes-help" placeholder="What Claude should know about this page" />
      <p id="notes-help" className="quiet small">Claude reads them as yours, verified, and never changes them.</p>
      <button type="submit" className="button" disabled={saving.busy || text === (p.notes?.text || "")}>
        {saving.busy ? "Saving…" : "Save notes"}
      </button>
      {p.notes && <span className="quiet small"> Saved {whenUtc(p.notes.changed_at)}</span>}
      <Problem message={saving.error} />
    </form>
  );
}

function Versions({ p, onChanged }) {
  const [compare, setCompare] = useState(null);
  const changing = useAction(onChanged);
  const restore = (version) =>
    changing.run(() => api(`wiki/${encodeURIComponent(p.page)}/restore`, { method: "POST", body: { version } }));
  const older = (v) => p.versions.find((x) => x.version < v)?.version;
  return (
    <section className="panel" aria-labelledby="versions-title">
      <h3 id="versions-title"><Icon name="history" />Versions <span className="count">{p.versions.length}</span></h3>
      <ul className="w-rows w-versions">
        {p.versions.map((v, i) => (
          <li key={v.version}>
            <span className="w-row-main">
              <span><strong className="num">v{v.version}</strong>{i === 0 && <span className="quiet"> · current</span>}</span>
              <span className="quiet">{v.reason} · {whenUtc(v.written_at)} by {by(v.written_by)}</span>
            </span>
            <span className="w-version-actions">
              {older(v.version) && <button type="button" className="link" onClick={() => setCompare(v.version)}>Changes</button>}
              {i > 0 && <button type="button" className="link" disabled={changing.busy} onClick={() => restore(v.version)}>Restore</button>}
            </span>
          </li>
        ))}
      </ul>
      <Problem message={changing.error} />
      {compare && (
        <Modal title={`What changed in v${compare}`} onClose={() => setCompare(null)} wide>
          <p className="quiet small">From v{older(compare)} to v{compare}.</p>
          <Diff page={p.page} from={older(compare)} to={compare} />
          <div className="dialog-actions"><button type="button" className="button" onClick={() => setCompare(null)}>Close</button></div>
        </Modal>
      )}
    </section>
  );
}

function DeletePage({ p }) {
  const [asking, setAsking] = useState(false);
  const deleting = useAction(() => { window.location.hash = "wiki"; });
  if (!p.versions.length) return null;
  return (
    <>
      <button type="button" className="link danger small" onClick={() => setAsking(true)}><Icon name="trash" /> Delete this page…</button>
      {asking && (
        <Modal title={`Delete ${p.title}?`} onClose={() => setAsking(false)}>
          <p>All {plural(p.versions.length, "version")} go, and this can't be undone. {p.kind === "project" && "The project's page goes back to not written."}</p>
          <Problem message={deleting.error} />
          <div className="dialog-actions">
            <button type="button" className="button" onClick={() => setAsking(false)}>Cancel</button>
            <button type="button" className="button danger" disabled={deleting.busy}
              onClick={() => deleting.run(() => api(`wiki/${encodeURIComponent(p.page)}`, { method: "DELETE" }))}>
              {deleting.busy ? "Deleting…" : "Delete page"}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

function WikiPage({ id, section }) {
  const page = useLoad(`wiki/${encodeURIComponent(id)}`);
  const p = page.data;
  const v = p?.view;
  useEffect(() => {
    if (p && section) document.getElementById(`sec-${section}`)?.scrollIntoView({ block: "start" });
  }, [p, section]);
  const labels = useMemo(() => {
    const counts = {};
    (v?.sections || []).forEach((s) => LABELS.forEach((l) => { counts[l] = (counts[l] || 0) + (s.labels?.[l] || 0); }));
    return counts;
  }, [v]);
  const local = useMemo(() => {
    if (!v) return null;
    const nodes = [{ id: v.page, title: v.title, kind: v.kind }];
    const edges = [];
    for (const [list, out] of [[v.links || [], true], [v.linked_from || [], false]]) {
      for (const l of list) {
        if (!nodes.some((n) => n.id === l.page)) nodes.push({ id: l.page, title: l.title || l.page, kind: l.type });
        edges.push(out ? { from: v.page, to: l.page } : { from: l.page, to: v.page });
      }
    }
    return { nodes, edges };
  }, [v]);
  const sections = v?.content || [];

  return (
    <section className="page">
      <p className="crumbs"><a href="#wiki"><Icon name="back" />Wiki</a>{p && <span aria-hidden="true">/</span>}{p && KIND_MANY[p.kind]}</p>
      <Loading state={page}>
        {p && (
          <>
            <header className="w-head">
              <p className="eyebrow">{KIND_ONE[p.kind]} page</p>
              <h1>{p.title}</h1>
              {v?.summary && <p className="lede">{v.summary}</p>}
              <p className="w-meta">
                {p.versions.length > 0
                  ? <span>v{p.versions[0].version} · updated {whenUtc(p.versions[0].written_at)} by {by(p.versions[0].written_by)}</span>
                  : <span>Not written yet</span>}
                {v?.built_from?.length > 0 && (
                  <span>built from {v.built_from.map((b) => <code key={b.repo}>{b.repo}@{b.commit.slice(0, 8)}</code>)}</span>
                )}
                {v?.key_terms?.length > 0 && <span>key terms: {v.key_terms.join(", ")}</span>}
              </p>
            </header>
            {p.confidential && (
              <div className="w-notice" role="note"><Icon name="lock" /><p><strong>Confidential.</strong> Claude never sees this page or its project; only you do, here.</p></div>
            )}
            {v?.stale?.is_stale && (
              <div className="w-notice warn" role="note"><Icon name="alert" /><p><strong>Stale.</strong> {(v.stale.why || []).join(" ")}</p></div>
            )}
            <div className="w-page">
              <article className="panel w-article" aria-label={p.title}>
                {v ? sections.map((s) => <Section key={s.id} s={s} />)
                  : p.sections.length > 0 ? p.sections.map((s) => (
                    <section key={s.id} className="w-section" id={`sec-${s.id}`}>
                      <div className="w-section-head"><h2>{s.heading}</h2></div>
                      <ul className="bullets">{s.lines.map((l, i) => <li key={i} className="statement">{l}</li>)}</ul>
                    </section>
                  )) : <p className="empty">Not written yet. The compile run writes it, or ask Claude to.</p>}
                {v && sections.length === 0 && <p className="empty">Not written yet. The compile run writes it, or ask Claude to.</p>}
              </article>

              <aside className="w-rail" aria-label="About this page">
                {(v ? sections : p.sections).length > 1 && (
                  <nav className="panel" aria-labelledby="toc-title">
                    <h3 id="toc-title"><Icon name="list" />Contents</h3>
                    <ul className="toc">
                      {(v ? sections : p.sections).map((s) => <li key={s.id}><a href={pageHref(p.page, s.id)}>{s.heading}</a></li>)}
                    </ul>
                  </nav>
                )}
                {v && (
                  <section className="panel" aria-labelledby="evidence-title">
                    <h3 id="evidence-title"><Icon name="check" />Evidence</h3>
                    <LabelBar counts={labels} />
                  </section>
                )}
                {p.lint.length > 0 && (
                  <section className="panel" aria-labelledby="lint-title">
                    <h3 id="lint-title"><Icon name="alert" />Needs attention <span className="count">{p.lint.length}</span></h3>
                    <ul className="w-rows">{p.lint.map((f, i) => <Finding key={i} f={f} />)}</ul>
                  </section>
                )}
                <Notes key={p.notes?.changed_at || "none"} p={p} onSaved={page.reload} />
                {local && local.nodes.length > 1 && (
                  <section className="panel" aria-labelledby="links-title">
                    <h3 id="links-title"><Icon name="globe" />Linked pages</h3>
                    <Graph nodes={local.nodes} edges={local.edges} size="local" here={v.page} href={(x) => pageHref(x)}
                      label={`Pages linked with ${p.title}`} />
                    <ul className="links">
                      {(v.links || []).map((l) => <li key={`o-${l.page}`}><Icon name="out" label="Links to" /><a href={pageHref(l.page)}>{l.title || l.page}</a></li>)}
                      {(v.linked_from || []).map((l) => <li key={`i-${l.page}`}><Icon name="in" label="Linked from" /><a href={pageHref(l.page)}>{l.title || l.page}</a></li>)}
                    </ul>
                  </section>
                )}
                {p.versions.length > 0 && <Versions p={p} onChanged={page.reload} />}
                <DeletePage p={p} />
              </aside>
            </div>
          </>
        )}
      </Loading>
    </section>
  );
}
