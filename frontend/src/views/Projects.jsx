import { useState } from "react";
import { api } from "../api.js";
import { Loading, Page, Problem, label, useAction, useLoad } from "../components/ui.jsx";

function ProjectRow({ project, onChanged }) {
  const [name, setName] = useState(project.name);
  const saving = useAction(onChanged);
  const save = (changes) => saving.run(() => api(`projects/${encodeURIComponent(project.id)}`, { method: "PUT", body: changes }));
  const github = project.aliases.find((a) => a.kind === "github_repo");

  return (
    <tr>
      <td>
        <input
          className="inline-edit"
          aria-label={`Name of ${project.id}`}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => name.trim() && name !== project.name && save({ name })}
        />
        <div className="quiet"><code>{project.id}</code>{github && <> on GitHub as <code>{github.value}</code></>}</div>
        <Problem message={saving.error} />
      </td>
      <td>
        <select aria-label={`Status of ${project.name}`} value={project.status} onChange={(e) => save({ status: e.target.value })}>
          <option value="active">Active</option>
          <option value="paused">Paused</option>
          <option value="done">Done</option>
        </select>
      </td>
      <td>{project.last_activity_day || "no activity"}</td>
      <td className="number">{project.events.toLocaleString()}</td>
      <td className="number">{project.claims}</td>
      <td>
        {project.confidential ? (
          <span className="quiet">Confidential</span>
        ) : (
          <button type="button" className="link" onClick={() => saving.run(() => label("project", project.id))}>
            Mark confidential
          </button>
        )}
      </td>
    </tr>
  );
}

export function Projects() {
  const list = useLoad("projects");
  return (
    <Page title="Projects" intro="Each repository becomes a project. Rename them so Claude and you use the same names.">
      <Loading state={list} empty="No projects yet: they appear when you add a repository.">
        <table className="table">
          <thead>
            <tr><th>Project</th><th>Status</th><th>Last activity</th><th>Events</th><th>Claims</th><th><span className="sr-only">Confidential</span></th></tr>
          </thead>
          <tbody>
            {list.data?.map((p) => <ProjectRow key={p.id} project={p} onChanged={list.reload} />)}
          </tbody>
        </table>
      </Loading>
    </Page>
  );
}
