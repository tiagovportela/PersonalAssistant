import { useCallback, useEffect, useState } from "react";
import { api, STATUS_NAMES } from "../api.js";

// Loads one API path; `reload` fetches it again after a change.
export function useLoad(path) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true }));
    api(path)
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((e) => setState({ loading: false, data: null, error: e.message }));
  }, [path]);
  useEffect(reload, [reload]);
  return { ...state, reload };
}

export function Page({ title, intro, actions, children }) {
  return (
    <section className="page">
      <header className="page-head">
        <div>
          <h1>{title}</h1>
          {intro && <p className="intro">{intro}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

export function Problem({ message }) {
  if (!message) return null;
  return <p className="problem" role="alert">{message}</p>;
}

export function Loading({ state, empty, children }) {
  if (state.error) return <Problem message={state.error} />;
  if (state.loading && !state.data) return <p className="quiet">Loading…</p>;
  if (empty && (!state.data || state.data.length === 0)) return <p className="empty">{empty}</p>;
  return children;
}

export function ClaimStatus({ status }) {
  return <span className={`status status-${status}`}>{STATUS_NAMES[status] || status}</span>;
}

// A confidential item is shown as a redaction bar until I choose to read it.
export function Redacted({ children, label = "Show" }) {
  const [shown, setShown] = useState(false);
  if (shown) return <span className="unredacted">{children}</span>;
  return (
    <button type="button" className="redacted" onClick={() => setShown(true)} aria-label={`${label} confidential text`}>
      <span aria-hidden="true">{children}</span>
    </button>
  );
}

// Runs one action, keeps its error next to the button, and calls `done` on success.
export function useAction(done) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const run = async (work) => {
    setBusy(true);
    setError(null);
    try {
      const result = await work();
      done?.(result);
      return result;
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

export async function label(type, id) {
  return api("labels", { method: "POST", body: { type, id: String(id) } });
}
