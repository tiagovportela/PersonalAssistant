# Third-party code reviews (Phase 0)

The brief (§10) requires third-party code I run to be reviewed, pinned to an exact version and checksum-verified, with no automatic updates. These are the reviews, done on 2 November 2026 by reading the source.

## Focused Window D-Bus (GNOME Shell extension)

[flexagoon/focused-window-dbus](https://github.com/flexagoon/focused-window-dbus), reviewed at commit `c70038ebd2a669ae36d578abcb8b332224a88dcf` (16 Oct 2026). Needed for app usage (Phase 4), because Wayland doesn't let other programs see the active window.

**Verdict: acceptable, installed by hand at the reviewed commit.**

- **What it is:** one 120-line JavaScript file plus metadata, MIT licence, no dependencies.
- **What it does:** adds a `Get` method and a `FocusChanged` signal on the session bus, at `/org/gnome/shell/extensions/FocusedWindow`. Both return the focused window's title, app id (`wm_class`), process id, size and position, and flags such as maximised.
- **What it doesn't do:** no network access, no files, no settings, and nothing that moves, closes or types into windows. It only reads.
- **Privacy:** any program running as you on the session bus can call `Get` or listen to `FocusChanged`, so window titles (email subjects, document names) become visible to them. Wayland normally hides those. Sandboxed Flatpak apps can't reach `org.gnome.Shell` by default; ordinary programs you run can already read much more. The layer will store only the title (redacted) and app id, as the brief says.
- **Gaps worth knowing:** `FocusChanged` fires only when the focused *app* changes, not when you switch between two windows of the same app or when a title changes. So the layer should poll `Get` every 10 seconds, as the brief plans, and use the signal only as a hint. The `display` field always serialises as `{}`, which is harmless.
- **Compatibility:** declares GNOME Shell 49, 50 and 51. The company laptop runs GNOME Shell 50.1, so it's supported. It won't run on GNOME 46 (the dev PC).

**Pinning.** Extensions from extensions.gnome.org can update themselves, which the brief rules out. Install it by hand from the reviewed commit, and check the files against these checksums:

```
de7ab71d0c22a3c43b8acefda75cab44b55b6db5585fc858ce04025149a02ee7  extension.js
1552abe743a17d164571370b20d820406cfeb044e2833b3e1d0ca2f8d3071101  metadata.json
```

`pwi app-usage on` does this step (Phase 4): the files are kept unchanged in [`third_party/focused-window-dbus`](../third_party/focused-window-dbus), checked against these checksums before every install, and installed under the identifier `focused-window-dbus-pinned@pwi.local`, which extensions.gnome.org doesn't know, so GNOME never replaces them with an update. `pwi app-usage off` removes it again, since it exposes window titles to other programs on the session bus.

## Google Chat MCP servers

The brief plans Google Chat "through an open-source local server I run", read-only in spirit: the layer never sends messages or acts on my behalf. Four candidates were reviewed:

| Server | Language | Problems |
|---|---|---|
| [chy168/google-chat-mcp-server](https://github.com/chy168/google-chat-mcp-server) (`d0c8f04`) | Python | Leftover demo tools that call third parties: `fetch_weather` puts its argument into a URL on `api.weather.com`, and `get_ip_my_address` calls `http://outian.net/` in plain HTTP. Either could carry data out of the laptop if a message tricked Claude into calling it. Tools to send, edit and delete messages and add reactions. Asks for `chat.messages` (write) and `directory.readonly` (the whole company directory). Stores the refresh token in `token.json` in the working folder with default permissions. Dependencies unpinned (`>=`), and it requires Python below 3.14. |
| [ArnaudKleinveld/google-chat-mcp](https://github.com/ArnaudKleinveld/google-chat-mcp) (`3cd3277`) | TypeScript | Hard-codes write, delete, import and space-creation scopes. Signs in only with a service account (needs a Workspace admin) or a raw access token that expires within an hour, so not my own sign-in in practice. |
| [nguyenvanduocit/google-chat-mcp](https://github.com/nguyenvanduocit/google-chat-mcp) (`792df6a`) | Go | The cleanest: tokens saved owner-only, secret scanning in CI. But it requests every Chat scope including writes, has send, delete and upload tools, and its HTTP server listens on every network interface (`:3003`), not just this laptop. |
| [siva010928/multi-chat-mcp-server](https://github.com/siva010928/multi-chat-mcp-server) (`83291c7`) | Python | Requests `chat.messages` and `chat.messages.create` (write); built to post into conversations. |

**Verdict: none is acceptable as it stands.** Every one can send messages, and the scope it asks Google for allows it, so the only real control would be Claude Desktop's tool permissions.

The safeguard that matters is the **OAuth scope**: if the sign-in only grants `chat.spaces.readonly`, `chat.messages.readonly` and `chat.memberships.readonly`, Google itself refuses any write, whatever the server's code does. Two ways to get there:

1. **A small read-only Chat reader in the layer** (recommended). Standard library only, like the rest of the service: list spaces and read messages within the allowlist, with only the three read-only scopes, the refresh token in GNOME Keyring, and no copies stored. The same Google sign-in serves the Calendar reading planned for Phase 3, as the brief's "user sign-in" decision intends.
2. **Fork the Go server** and patch it: read-only scopes, remove the send, delete and upload tools, and listen on 127.0.0.1 only. It works, but means maintaining a Go fork and its dependencies.

**Decided (2 Nov 2026): option 1.** The layer reads Google Chat itself (`service/chat.py`, `service/google_signin.py`), with only read-only scopes, so no third-party Chat server is installed.

Either way, the Google Cloud project needs the Chat API enabled and an OAuth client of type *Desktop app*. A Workspace admin may have to allow that client, so check before building.

### Google's official Chat MCP server (assessed 3 Nov 2026, not adopted)

Google offers a hosted Chat MCP server ([guide](https://developers.google.com/workspace/chat/api/guides/configure-mcp-server)), at `https://chatmcp.googleapis.com/mcp/v1`, added in Claude as a custom connector.

- **Tools:** five read (`search_conversations`, `list_messages`, `search_messages`, `list_memberships`, `get_notification_settings`) and four write (`send_message`, `mark_as_read`, `mark_as_unread`, `update_notification_settings`). Its server-side search is better than the layer's.
- **Scopes:** besides the read-only ones, it asks for `chat.messages.create`, `chat.users.readstate` and `chat.users.spacesettings`, so Google would allow it to post and change state. Write tools can be turned off in Claude's connector settings, but that's a setting, not a refusal by Google.
- **Allowlist:** like other connectors, only followed by instruction, not enforced.
- **Availability:** Google Workspace Developer Preview Program; an admin must enable the Chat API and the Chat MCP API, and the OAuth client must be marked for an AI-powered agent.

**Decision:** keep the layer's reader, which can't write by construction and enforces the allowlist. Revisit when Google's server leaves preview, especially if it can be used with read-only scopes only.
