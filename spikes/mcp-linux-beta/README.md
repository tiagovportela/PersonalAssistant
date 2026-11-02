# Spike: Claude Desktop Linux beta + local MCP

Throwaway code for the first Phase 0 check: can the Claude Desktop Linux beta use a local context server through the planned service + bridge design? It answers three questions:

1. Does Claude Desktop start a local MCP server?
2. Does it show MCP prompts?
3. Can one tool stay on "ask every time" while another is always allowed?

## Pieces

| File | Role |
|---|---|
| `service.py` | Long-running service. Speaks MCP on `$XDG_RUNTIME_DIR/pwi-spike/mcp.sock` (owner-only). One read tool (`get_status`), one write tool (`propose_claim`), one prompt (`daily_briefing`). Saves claims in `spike.db`. Standard library only. |
| `bridge.py` | What Claude Desktop starts. Copies stdio to the socket and back. Reconnects when the service restarts, and answers requests with a JSON-RPC error while the service is away. |
| `test_pipe.py` | End-to-end test through the bridge, using a private service, socket and database. |

The service runs as a transient systemd user unit, so Claude Desktop never starts it. That unit disappears on logout or reboot. To start it again:

```bash
systemd-run --user --unit=pwi-spike --property=Restart=on-failure /usr/bin/python3 -I /home/tiago/Projects/PersonalAssistant/spikes/mcp-linux-beta/service.py
```

Logs: `journalctl --user -u pwi-spike -f` (service) and `~/.config/Claude/logs/mcp*.log` (Claude Desktop).

## Already verified (2 Nov 2026)

`python3 -I test_pipe.py` passes 16 checks: the protocol handshake, both tools, the prompt, error handling, socket permissions, and the bridge's behaviour when the service is down, restarts mid-session, or stdin closes. The entry is registered in `~/.config/Claude/claude_desktop_config.json` under `mcpServers.pwi-spike`, and the original file is backed up next to it as `.bak-before-pwi-spike`.

## Checklist in Claude Desktop

Claude Desktop reads `mcpServers` only at launch, so **quit it completely and reopen it** first.

1. **Server starts.** Settings → Developer lists `pwi-spike` as running, and the service journal shows `connection N opened` with Claude Desktop's client info.
2. **Read tool.** In a new chat: *"Use pwi-spike to get the spike status."* Claude calls `get_status` and shows a `service_pid`.
3. **Write tool asks.** *"Save a decision: we use SQLite for the store."* Claude Desktop asks for approval before `propose_claim` runs.
4. **Prompts.** Look for `pwi-spike` → *Daily briefing (spike)* in the chat box's attach/"+" menu. Run it. The answer should end with *"Prompt served by pwi-spike (pid …)"*. If prompts don't appear, the architecture's `get_instructions` fallback is needed.
5. **Per-tool approval sticks.** In the connector's tool permissions, set `get_status` to always allow and `propose_claim` to ask every time. Quit and reopen Claude Desktop. Both settings should still be there, and only `propose_claim` should ask.
6. **Service restart.** Run `systemctl --user restart pwi-spike`, then ask for the status again. Record whether Claude Desktop reconnects on its own or only after an app restart. If it doesn't reconnect, the real bridge needs retry logic, which isn't in the architecture yet.

## Results

| # | Check | Result | Notes |
|---|---|---|---|
| 1 | Server starts | ✅ 2 Nov | Desktop 4.29.0 launches the bridge at startup, negotiates protocol 2025-11-25, and calls `tools/list` and `prompts/list`. It opens **two** connections: `claude-ai` (chat) and `local-agent-mode-pwi-spike` (Code/Cowork, which never asks for prompts). The real service must handle several clients at once. Closing the window doesn't quit the app; a config change needs Ctrl+Q or Quit from the tray. |
| 2 | Read tool | ✅ 2 Nov | Works from chat and from the Code tab, wrapped as `<data>`. The tools also appear in Claude Code sessions inside Desktop. |
| 3 | Write tool asks | ✅ 2 Nov | Desktop asked for approval, then `propose_claim` saved claim 1. |
| 4 | Prompts shown | ❌ 2 Nov | Desktop calls `prompts/list` and gets `daily_briefing` back, but the chat's "+" menu doesn't show it. **Use `get_instructions` for all six experiences.** |
| 5 | Per-tool approval sticks | ✅ 2 Nov | "Always allow" on `get_status` and "ask" on `propose_claim` both survived a full quit and reopen. |
| 6 | Service restart | ❌ 2 Nov | The restart closes the socket and the bridge exits. Desktop logs "Server disconnected", never relaunches the bridge, and tool calls fail with a generic "Tool execution failed" until Desktop itself restarts. **The bridge must reconnect on its own** (see below). Reconnecting bridge built on 2 Nov. **Retest ✅:** across two service restarts, both Claude Desktop connections were back within about 0.15 s, and the next `tools/call` succeeded with no new `initialize`. Claude Desktop logged no disconnect. |

### What check 6 means for the design

The service will restart (crashes, upgrades, systemd `Restart=on-failure`), so the bridge can't simply exit when the socket closes. It needs a little logic after all, which `bridge.py` now has:

- It keeps stdio open and retries the socket with backoff (0.2 s up to 2 s) until the service is back.
- A request that arrives while the service is down waits up to 5 s (`PWI_BRIDGE_WAIT`) for it. After that, the request gets a JSON-RPC error (`-32000`, "not reachable"). A request that was in flight when the service went away gets "restarted before answering". Claude can report either one clearly instead of a generic failure.
- The service doesn't need a fresh `initialize` for each connection, so a reconnect is invisible to Claude Desktop. The same wait also covers a login race, where Claude Desktop starts before the service.

## Contracts test

With `PWI_SPIKE_CONTRACTS=1`, the service serves the 17 Phase 1 tools from `contracts/tools.py` instead of the spike's two. Each call returns a stub that echoes its arguments and says there's no data yet. The journal logs every call as `stub <tool> <arguments>`, so the arguments Claude actually built can be checked.

```bash
systemd-run --user --unit=pwi-spike --property=Restart=on-failure --setenv=PWI_SPIKE_CONTRACTS=1 /usr/bin/python3 -I /home/tiago/Projects/PersonalAssistant/spikes/mcp-linux-beta/service.py
```

Claude Desktop reads the tool list only at startup, so quit it with Ctrl+Q and reopen it first.

| # | Check | How | Result |
|---|---|---|---|
| A | All 17 tools load | Settings → Developer shows no error, and the connector lists 17 tools | ✅ Desktop logged "Connected to pwi-spike (17 tools)". |
| B | Approval settings | Set `set_claim_status`, `add_confidential_label` and `read_confidential` to ask every time | Set by hand; not visible in logs. |
| C | Instructions come first | *"Give me yesterday's briefing."* Claude calls `get_instructions` before `get_day`, then says there's no data instead of inventing a briefing | ✅ `get_instructions(daily_briefing)`, then `get_day(2026-11-01)`, in all three runs. |
| D | Local evidence | *"Save a decision: we chose SQLite for the store, based on commit abc123."* Claude calls `propose_claim` with `evidence: [{"event_id": …}]` | ❌ Called with `type` and `text` only. No evidence, although it's `required`. |
| E | Online evidence | *"Save a commitment: I'll send the status update by Friday, from the Notion task https://www.notion.so/example-123."* Claude uses the `artifact` + `read_at` form of evidence | ❌ No evidence. The Notion URL ended up inside `text`. |
| F | Approval prompts | *"Confirm claim clm_test1."* and *"Show me the confidential project pwi."* Both ask before running | No calls reached the service. Either the approvals were declined or Claude didn't call the tools; the logs can't tell which. |

**Finding: Claude Desktop simplifies input schemas.** The schema Claude receives (seen through a Code session in Desktop) keeps `type`, `properties`, `enum`, `minimum`/`maximum`, `description` and `required`. It drops `oneOf` (each evidence item became an empty object), `minItems`, `minLength`, `pattern`, `format` and `additionalProperties`. Nothing enforces `required` either. So the contracts have to change:
- **Flatten evidence** into one object type with optional fields, so nothing depends on `oneOf`.
- **Say the rules in descriptions**, which survive.
- **Validate every call in the service**, returning a tool error that says exactly what's missing, so Claude retries with evidence.

## Clean up

```bash
systemctl --user stop pwi-spike
```

Then delete the `pwi-spike` entry from `mcpServers` in `~/.config/Claude/claude_desktop_config.json`. Don't restore the backup, because Claude Desktop rewrites its preferences in that file.

### Retest after the fix (2 Nov 2026)

With flat evidence, rules in descriptions, and validation in the service (`contracts/validate.py`):

| # | Result |
|---|---|
| D | ✅ Claude's first `propose_claim` still had no evidence and was **rejected**. Claude then called `search("abc123", kinds: git)`, found nothing (stub), and saved no claim. Validation, not the schema, is what stops unsupported claims. |
| E | No `propose_claim` call reached the service for the Notion commitment, so nothing unsupported was saved. Whether Claude asked first or explained that it had no evidence isn't visible in the logs. |
| F | ✅ `set_claim_status(clm_test1, supported)` and `read_confidential(project pwi)` both showed an approval prompt in Claude Desktop, then ran once approved. |
