// Every call goes to the service that served this page; the session cookie signs it in.
export async function api(path, { method = "GET", body } = {}) {
  const response = await fetch(`/api/${path}`, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `The service answered ${response.status}.`);
  }
  return data;
}

export const STATUS_NAMES = {
  proposed: "Unconfirmed",
  supported: "Verified",
  disputed: "Disputed",
  retracted: "Retracted",
  superseded: "Superseded",
};

export const EVENT_NAMES = {
  "git.commit": "Commit",
  "git.merge": "Merge",
  "git.push": "Push",
  "claude_code.session": "Claude Code session",
  "firefox.visit": "Page",
  "app.focus": "Window",
  "app.active": "Active",
  "app.idle": "Idle",
};

// Times from Claude-facing data carry their own offset ("2026-11-02T20:46+01:00"): show them as they are.
export function when(iso) {
  if (!iso) return "";
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)}`;
}

// Store times are UTC ("2026-11-02T20:46:32Z"): show them in this laptop's time.
export function whenUtc(text) {
  if (!text) return "never";
  const moment = new Date(text);
  const sameYear = moment.getFullYear() === new Date().getFullYear();
  return moment.toLocaleString(undefined, {
    ...(sameYear ? {} : { year: "numeric" }), month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}
