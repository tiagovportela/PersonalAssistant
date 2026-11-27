# End-of-day agent (brief v0.7 addendum)

At 19:30 on workdays an agent reads my day, saves what it finds as claims, writes the day into my Obsidian vault, and asks me to confirm the claims in Google Chat. When I've answered, it rewrites the notes with my answers.

## What changes in the brief (v0.6 → v0.7)

| v0.6 | v0.7 |
|---|---|
| End-of-day review: optional, and I start it whenever I want. | The agent starts on its own at the time I set (`pwi eod setup --at`). The review in Claude Desktop stays, and covers what the Chat review doesn't (contradictions, open questions). |
| Out of scope: sending messages or taking actions on my behalf. | The layer posts to one place only: my direct message with its own Chat app, as the app. It sends nothing as me and nothing to anyone else. Claude never sends anything: connector tools that change things are denied. |
| Data leaves my machine only when Claude Desktop pulls context to answer one of my questions. | It also leaves when the agent runs: Claude Code, signed in to the company Team account, reads the layer and the connectors I allow, as Claude Desktop does. The claims shown in Chat go to Google Chat, where the work messages they come from already are. |
| Only I confirm a claim: Claude Desktop asks me to approve each `set_claim_status`. | Also my click on a card in my Chat DM, which the layer checks itself (below). |
| Notes: the layer is the only store. | The day's notes are also written to the vault's notes folder, as Markdown. Deleting something in the frontend doesn't remove it from the vault, and the vault has no retention. Confidential items never reach the notes, because Claude never sees them. |

## How it runs

```
19:30  pwi-eod.timer → pwi eod run
         collect → claude -p in <vault>/Work, with the agent's instructions
           Claude: session notes · get_day · connectors · propose_claim · writes Daily/<day>/
         the layer posts the unconfirmed claims to my Chat DM, as cards
         then pwi-wiki.service: the wiki's compile run (docs/knowledge_wiki.md)
later  my clicks → Google Chat → Pub/Sub → the service pulls them, checks them, records them as mine
         all answered → pwi-eod-finish.service → claude -p rewrites Daily/<day>/ with my answers
08:30  pwi-eod-finish.timer: the same, for answers that came late
```

- **Missed runs.** The timers are persistent: a run missed while the laptop was off happens at the next login. Before noon, `pwi eod run` is about the last workday.
- **Re-runs.** A day that ran is skipped unless `--force`. A re-run rewrites the day's folder whole.

## The tools Claude gets

At each run the layer starts Claude Code once just to read the tools it has, then builds an exact list:
- the layer's tools, except `set_claim_status`, `add_confidential_label` and `read_confidential`, and `propose_wiki_update`: the wiki has its own run;
- connector tools whose names say they read (search, get, list, read, fetch, find, query, view, download) and none of the words that change something (create, update, send, delete, share, request, merge, comment…). Anything unclear is denied;
- `Edit` (which also covers `Write`) only inside the notes folder, which is also the working directory, so Claude can't read the rest of the vault either;
- no `Bash`, `WebFetch`, `WebSearch`, subagents or `Artifact`.

`Edit` and `Write` are never denied outright, since a deny would override the folder rule; `--block Edit` turns note writing off, and `--allow` can't make edits allowed everywhere.

The run is in `dontAsk` mode: anything not on the list is denied instead of waiting for an approval. claude.ai connectors can still be connecting when Claude Code reports its tools at startup, so their tools may be missing from that list. A `PreToolUse` hook on MCP tools (`service/eod_hook.py`) therefore decides each MCP call as it happens, by the same naming rules (`service/tool_rules.py`) and my overrides. It fails closed, and the deny list still applies on top. `pwi eod check` shows the list; `--allow TOOL` and `--block TOOL` change one tool. `ANTHROPIC_API_KEY` is removed from the run's environment, because Claude Code doesn't load claude.ai connectors with one.

The finish run gets only `get_day` and `Edit` inside that day's folder.

## The Chat review

The layer's Chat app is a service account in my Google Cloud project, with the `chat.bot` and `pubsub` scopes only. It's a separate identity from my read-only sign-in, which stays read-only. Google Chat publishes the app's events to a Pub/Sub topic, and the service pulls them (a long request that ends as soon as I click), so nothing on the laptop listens on the network.

The review lives in my direct message with the app. The layer records that DM when I open it, and refuses to work in a shared space. Each claim is a card with Confirm, Save correction (with a text box), Dispute and Retract; at most 30 claims per review, 5 per card, about the oldest day first, and the next ones follow once these are answered.

A click changes a claim only if:
1. Google Chat says it came from me: `users/<id>` of the Google account my read-only sign-in belongs to, a person, with my email;
2. in my DM with the app;
3. on a card the layer posted, for an item of that card;
4. for the version of the claim the card showed, still unconfirmed or disputed. If the claim changed since, the card says so and the claim goes to the next review.

Anything else is dropped and logged. An answer is recorded like an edit in the frontend: a new version by me (`changed_by` me, reason *confirmed in the Chat review*), and in the audit trail as mine. Confirm and Save correction make the claim verified. A click delivered twice is applied once.

- **Confidential since posting.** Cards are drawn through `claims_shareable`, the same confidential filter Claude's views use (it keeps retracted claims, so a retracted card still shows what I retracted). A claim labelled confidential after its card was posted is marked *hidden* at the listener's next pass, and its card is redrawn without it. The finish run's prompt names it by its id only, so its line is taken out of the notes.
- **Nothing lost on a failure.** A Pub/Sub event is acknowledged only once handled. One that failed (a locked store, Google unreachable) is delivered again, and handling is idempotent; one that fails 5 times is dropped and logged. A review is marked answered only once its closing message or its continuation is posted; otherwise the listener's next pass finishes it, and the custom message ids keep a retry from posting twice.
- **The notes rewrite** marks exactly the answers it was given as in the notes. An answer that comes in while Claude rewrites stays due for the next rewrite.

## The notes

[`contracts/agent/end_of_day.md`](../contracts/agent/end_of_day.md) is the agent's instructions, and its notes layout. In short:

```
Work/Daily/<day>/<day> Executive summary.md   the day, commitments both ways, decisions, risks, what needs me
Work/Daily/<day>/<day> <Project>.md           one per project: summary, what I did, claims, sources
Work/Projects/<Project>.md                    hubs, created once, then mine
Work/People/<Full Name>.md
Work/Sources/<Title>.md                       a doc, sheet, deck, Notion page, PR, artifact or meeting
```

- **The graph.** Obsidian's graph comes from links, so every daily note links its summary, project, people and sources, and each summary links the previous one. Hubs have `aliases` (a person's first name and email) for Obsidian's autocomplete. Links use the full name, as `[[Ana Silva|Ana]]` when shorter, since an alias doesn't make `[[Ana]]` reach the note.
- **Tags.** Nested tags give the graph's groups and filters: `pwi/<kind>`, `project/<id>`, `person/<first-last>`, `source/<kind>`, `topic/<theme>`. Each claim line also carries `claim/<type>`, `status/<label>`, `commitment/mine|theirs` and a block id `^clm-<id>`, so the finish run can find it and the summary can link to it. To see tags as nodes, turn on *Tags* in the graph view's filters. Colour groups such as `path:Work/People` and `tag:#source` help.

## Setting it up

On the laptop, once Claude Code is installed and signed in (`claude`, with the Team account) and the connectors are added on claude.ai:

```bash
pwi eod setup --vault ~/Obsidian/MyVault      # --folder Work --at 19:30 --days Mon..Fri
pwi eod check                                 # the tools it gets; is the layer connected?
pwi eod run                                   # a first run now, to see the notes
```

**The Chat app**, in the Google Cloud project that already has the layer's OAuth client:

1. **Billing.** Pub/Sub needs a billing account linked to the project. The review is a few kilobytes a day, inside Pub/Sub's free 10 GiB a month, so it costs nothing, but the account must be linked.
2. **Pub/Sub.** Enable the Pub/Sub API. Create a topic, e.g. `pwi-chat-events`, and give `chat-api-push@system.gserviceaccount.com` the *Pub/Sub Publisher* role on it. Create a pull subscription to it, also named `pwi-chat-events`.
3. **Service account.** Create one, e.g. `pwi-chat-app`, with no project roles. On the subscription, give it *Pub/Sub Subscriber*. Under Keys, add a JSON key. If the organization blocks key creation (`iam.disableServiceAccountKeyCreation`, on by default for organizations created since May 2024), an admin has to allow it for this project.
4. **Google Chat API, Configuration** (the same page the read-only sign-in needed). Turn **interactive features** on; Functionality: *Receive 1:1 messages* on, *Join spaces and group conversations* off; Connection settings: **Cloud Pub/Sub**, with the topic from step 2; Visibility: only me. The read-only sign-in keeps working as before.
5. **Workspace admin.** Google Chat must allow users to install Chat apps (Admin console, Apps, Google Workspace, Google Chat, Chat apps).
6. On the laptop: `pwi chat-app connect ~/Downloads/<key>.json` (and `--subscription NAME` if it isn't `pwi-chat-events`), then delete the downloaded key. In Google Chat, start a direct message with the app: it answers with a welcome, and the layer records the DM.

**If the Chat app isn't possible** (no billing account, keys not allowed, or Chat apps blocked), the fallback is an incoming webhook in a space with only me: the layer posts the review as text, and I reply with numbers (*1 ok, 2 no, 3 = new text*), read through the existing read-only sign-in. It isn't built yet; it shares the review's checks and recording, and only the posting and the reading of answers differ.

## Not verified yet

- The Chat event format (`common.invokedFunction`, `common.parameters`, `common.formInputs`, and the older `action.actionMethodName`) comes from Google's documentation as I know it; Google's developer site wasn't reachable when this was built, so the parser accepts both forms. The first real click checks it: `journalctl --user -u pwi` logs each event's outcome.
- That Claude Code headless loads the claude.ai connectors, and their tool names (`mcp__claude_ai_<Name>__<tool>`): `pwi eod check` shows what's there.
