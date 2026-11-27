// Outline icons, 16 px, drawn in the current colour, so they follow text and states.
const PATHS = {
  overview: <><rect x="2" y="2" width="5" height="5" rx="1.5" /><rect x="9" y="2" width="5" height="5" rx="1.5" /><rect x="2" y="9" width="5" height="5" rx="1.5" /><rect x="9" y="9" width="5" height="5" rx="1.5" /></>,
  book: <><path d="M3 2.5h7.5a2 2 0 0 1 2 2v9H5a2 2 0 0 1-2-2Z" /><path d="M3 11.5a2 2 0 0 1 2-2h7.5" /></>,
  check: <><circle cx="8" cy="8" r="5.5" /><path d="m5.5 8 1.75 1.75L10.5 6.5" /></>,
  folder: <path d="M2 4.5a1 1 0 0 1 1-1h3.25L7.75 5H13a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1Z" />,
  pulse: <path d="M2 8h2.5l1.5-4 3 8 1.5-4H14" />,
  database: <><ellipse cx="8" cy="4" rx="5" ry="1.75" /><path d="M3 4v8c0 .97 2.24 1.75 5 1.75s5-.78 5-1.75V4" /><path d="M3 8c0 .97 2.24 1.75 5 1.75S13 8.97 13 8" /></>,
  globe: <><circle cx="8" cy="8" r="5.5" /><path d="M2.5 8h11M8 2.5c1.6 1.6 2.25 3.5 2.25 5.5S9.6 11.9 8 13.5C6.4 11.9 5.75 10 5.75 8S6.4 4.1 8 2.5" /></>,
  lock: <><rect x="3.5" y="7" width="9" height="6.5" rx="1.5" /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" /></>,
  clock: <><circle cx="8" cy="8" r="5.5" /><path d="M8 5v3l2 1.5" /></>,
  list: <path d="M5.5 4.5h8M5.5 8h8M5.5 11.5h8M2.5 4.5h.01M2.5 8h.01M2.5 11.5h.01" />,
  search: <><circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5 14 14" /></>,
  alert: <><path d="M8 2.5 14 13H2Z" /><path d="M8 6.5v3M8 11.5v.01" /></>,
  sources: <><path d="M4 2.5h6l2.5 2.5v8.5H4Z" /><path d="M6.5 8h4M6.5 10.5h4" /></>,
  commit: <><circle cx="8" cy="8" r="2.5" /><path d="M2 8h3.5M10.5 8H14" /></>,
  out: <><path d="M9 3h4v4" /><path d="M13 3 7.5 8.5" /><path d="M11 9.5V13H3V5h3.5" /></>,
  in: <><path d="M7 13H3V9" /><path d="m3 13 5.5-5.5" /><path d="M5 6.5V3h8v8H9.5" /></>,
  note: <><path d="M3 2.5h10v11H3Z" /><path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3" /></>,
  history: <><path d="M2.5 8a5.5 5.5 0 1 0 1.6-3.9" /><path d="M2.5 2.5v2.5H5" /><path d="M8 5.5V8l1.75 1.25" /></>,
  back: <path d="M10 3.5 5.5 8l4.5 4.5" />,
  refresh: <><path d="M13 3v3h-3" /><path d="M13 6a5 5 0 1 0 .5 4" /></>,
  trash: <><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.5 9h6l.5-9" /></>,
};

export function Icon({ name, label }) {
  return (
    <svg className="icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden={label ? undefined : "true"}
      role={label ? "img" : undefined} aria-label={label} focusable="false">
      {PATHS[name]}
    </svg>
  );
}
