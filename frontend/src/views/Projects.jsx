import { Fragment, useState } from "react";
import { api } from "../api.js";
import { Loading, Page, Problem, label, useAction, useLoad } from "../components/ui.jsx";

const PLACES = {
  github_repo: ["GitHub", "owner/repo"],
  notion: ["Notion", "a page or database link"],
  drive_folder: ["Drive", "a folder link or path"],
  gmail_query: ["Gmail", "a search, e.g. label:billing"],
  chat_space: ["Chat", "a space name"],
  calendar_match: ["Calendar", "a word in meeting titles"],
  repo_path: ["Folder", ""],
};

function Places({ project, onChanged }) {
  const [kind, setKind] = useState("notion");
  const [value, setValue] = useState("");
  const changing = useAction(() => { setValue(""); onChanged(); });
  const add = (event) => {
    event.preventDefault();
    changing.run(() => api(`projects/${encodeURIComponent(project.id)}/aliases`, { method: "POST", body: { kind, value } }));
  };
  const remove = (a) => changing.run(() => api(`aliases/${a.kind}/${encodeURIComponent(a.value)}`, { method: "DELETE" }));

  return (
    <div className="places">
      <ul>
        {project.aliases.map((a) => (
          <li key={`${a.kind}:${a.value}`}>
            <span className="quiet">{PLACES[a.kind]?.[0] || a.kind}</span> <code>{a.value}</code>
            {a.added_by === "claude" && <span className="quiet"> added by Claude</span>}
            {a.kind !== "repo_path" && a.kind !== "git_remote" && a.kind !== "claude_code_cwd" && (
              <> <button type="button" className="link" onClick={() => remove(a)}>Remove</button></>
            )}
          </li>
        ))}
      </ul>
      <form className="row" onSubmit={add}>
        <select aria-label="Where" value={kind} onChange={(e) => setKind(e.target.value)}>
          {Object.entries(PLACES).filter(([k]) => k !== "repo_path").map(([k, [name]]) => <option key={k} value={k}>{name}</option>)}
        </select>
        <input aria-label="Value" value={value} onChange={(e) => setValue(e.target.value)} placeholder={PLACES[kind][1]} spellCheck="false" />
        <button type="submit" className="button" disabled={!value.trim() || changing.busy}>Add</button>
      </form>
      <Problem message={changing.error} />
    </div>
  );
}

function ProjectRow({ project, open, onToggle, onChanged }) {
  const [name, setName] = useState(project.name);
  const saving = useAction(onChanged);
  const save = (changes) => saving.run(() => api(`projects/${encodeURIComponent(project.id)}`, { method: "PUT", body: changes }));
  const online = project.aliases.filter((a) => a.kind in PLACES && a.kind !== "repo_path").length;

  return (
    <Fragment>
      <tr>
        <td>
          <input
            className="inline-edit"
            aria-label={`Name of ${project.id}`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => name.trim() && name !== project.name && save({ name })}
          />
          <div className="quiet">
            <code>{project.id}</code>.{" "}
            <button type="button" className="link" aria-expanded={open} onClick={onToggle}>
              {open ? "Hide places" : `Where it lives (${online} online)`}
            </button>
          </div>
          <Problem message={saving.error} />
        </td>
        <td>
          <select aria-label={`Status of ${project.name}`} value={project.status} onChange={(e) => save({ status: e.target.value })}>
            <option value="active">Active</option>
            <option value="paused">Paused</option>
            <option value="done">Done</option>
          </select>
        </td>
        <td className="nowrap">{project.last_activity_day || "no activity"}</td>
        <td className="number">{project.events.toLocaleString()}</td>
        <td className="number">{project.claims}</td>
        <td className="actions">
          {project.confidential ? (
            <span className="quiet">Confidential</span>
          ) : (
            <button type="button" className="link" onClick={() => saving.run(() => label("project", project.id))}>
              Mark confidential
            </button>
          )}
        </td>
      </tr>
      {open && (
        <tr className="detail">
          <td colSpan={6}><Places project={project} onChanged={onChanged} /></td>
        </tr>
      )}
    </Fragment>
  );
}

export function Projects() {
  const list = useLoad("projects");
  const [open, setOpen] = useState(null);
  return (
    <Page
      title="Projects"
      intro="Each repository becomes a project. Name them as you say them, and note where each lives online so Claude looks in the right place."
    >
      <Loading state={list} empty="No projects yet: they appear when you add a repository.">
        <table className="table">
          <thead>
            <tr><th>Project</th><th>Status</th><th>Last activity</th><th>Events</th><th>Claims</th><th><span className="sr-only">Confidential</span></th></tr>
          </thead>
          <tbody>
            {list.data?.map((p) => (
              <ProjectRow key={p.id} project={p} open={open === p.id}
                onToggle={() => setOpen(open === p.id ? null : p.id)} onChanged={list.reload} />
            ))}
          </tbody>
        </table>
      </Loading>
    </Page>
  );
}
