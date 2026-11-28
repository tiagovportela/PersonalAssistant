# Improvement plan: the layer at the 2026 state of the art (proposal for brief v0.9)

A plan to bring the whole layer (collection, claims, search, the knowledge wiki, the end-of-day agent, the evaluation and the planned meeting pipeline) to the level of what was published between 1 February and 27 November 2026, and to work the way Anthropic, OpenAI and Google DeepMind say they work. Nothing here is built. Each step that changes a rule of the brief says so, and waits for my decision.

It rests on three things:
- **My docs:** brief v0.6, architecture v0.2, [`end_of_day_agent.md`](end_of_day_agent.md), [`knowledge_wiki.md`](knowledge_wiki.md), the contracts and the schema.
- **The code** at commit `e76ddc0`.
- **The literature report:** [`reports/Frontier methods since February 2026.md`](../reports/Frontier%20methods%20since%20February%202026.md), with its notes in `research_notes/`. Every source in it is dated 1 February 2026 or later. The report says how strong each finding is; this plan repeats that only where a decision depends on it.

**Limits of the evidence.** OpenAI's and Google's sites and the labs' system cards couldn't be opened, so their material comes from search snippets, OpenAI's Cookbook repository and Anthropic's summaries. Many papers were read as abstracts only, and all are preprints. Nothing published in the window tests Portuguese and English work data, a store that mixes Git, sessions, browsing and app usage, or a person confirming memory. So almost no published number transfers to my layer directly, and step 1 below is what turns each recommendation into a measurement.

## What the evidence says, in five lines

1. **Raw, dated records stay the source of truth, and stay searchable.** Four independent studies found that memory structures built by a model give no consistent gain over well-ranked search of the raw records. A compiled wiki helps most alongside search: 61% with both, against 53% for search alone and 48% for the wiki alone, in Anthropic's own small test.
2. **The model proposes; code decides.** Which value is current, what a citation points to, how long something took, where a claim came from and what may be written are decided by code. Failures in every area cluster where a model was left to decide one of these.
3. **A citation that exists isn't a citation that supports.** In cited reports from 14 models, over 94% of links were valid, while only 24% to 77% of citations supported their sentence.
4. **Controls outside the model hold; filters and click-approvals don't.** Tool allowlists and origin labels held under adaptive attack. A content screen caught none of 360 plainly worded false facts. People approve 93% to 97% of prompts and caught 13.6% of planted dangerous ones.
5. **The labs measure before they change anything.** Written thresholds, repeated runs, a baseline arm, graders checked against a person, and every prompt or model change treated as a release.

## The layer after the plan

![The layer after the plan: sources pass through an intake step that cleans text and records origin; the store keeps raw records with origin, verdicts, a search log and run records; agents reach it only through checked tools; a checker run and a notes check sit before what I see; an evaluation band gates every change.](sota_plan.svg)

Plain boxes exist today; green ones are added or changed by the plan. A local embedding model for search isn't drawn, since step 4 adopts one only if my own search set shows it helps.

## Where the layer stands

### Already in line with the evidence

| What the layer does | What the evidence says |
|---|---|
| Events, claims and evidence are the store; wiki pages are a view, with labels worked out at read time | The best-supported finding of the report. |
| An agent searching a ranked keyword index (FTS5) | The design the strongest independent retrieval study favours at this size: 90.1 against 81.3 for a single keyword search, and dense retrieval behind both. |
| One wiki page per run, one writer per page | Anthropic kept 57 of 57 facts this way, against 41 of 57 with several agents writing one shared table. |
| Exact tool lists per unattended run, no shell or web tools, no delete tools, a compile run with no connectors | The class of control that held under adaptive attack. |
| Code draws the Chat cards, the wiki's HTML and the diagrams | A card drawn by code from the stored record cut forged approvals from 0.54 to 0.03. |
| Computer time, counts and due dates are computed in SQL (`get_day`, `get_week`) | An LLM-written day summary answered 66% to 80% of questions right; a ledger computed by code, 98.4%. |
| Versions for every change, and a `base_version` check on wiki writes | Matches the labs' own memory stores (immutable versions, a precondition on writes). |
| Deletion by me in the frontend, with a decision per claim | Deletion run by the owner in code is the workable route; no agent memory system passed more than 1.5% of forget requests. |
| Meaning-based search waits for a measurement | Hybrid search beats a strong keyword baseline by 0.008 to 0.051, and makes 8% to 21% of queries worse. |

### Gaps

| # | Gap | Where |
|---|---|---|
| G1 | **No automatic evaluation.** The 5-day evaluation is by hand, runs once, and matches labels to claims by word overlap. Nothing replays the end-of-day agent or the compile run on a fixed day and grades it, so a prompt edit or a new model can't be compared with the last one. | `service/evaluation.py` |
| G2 | **Runs don't record what ran.** `eod_runs` and `wiki_runs` keep turns and duration. They don't keep the model, Claude Code's version, the instructions' version, tokens or cost, and the runs don't pin a model. | `service/eod.py:282` (`claude_argv`), migrations 7 and 9 |
| G3 | **A citation is checked for existence only.** `check_cites` checks that the claim, event, commit and path exist. Claims aren't checked against their evidence either. | `service/wiki.py:702`, `service/writes.py` |
| G4 | **A statement's label is its best citation,** and several items from one source chain (a commit, the session that made it, the message announcing it) count as several. | `Reader.judge`, `service/wiki.py:140` |
| G5 | **Contradictions come from word overlap.** The evidence puts this family of signal near chance (0.59), and nothing retires an old value by rule. Claims have no "true from" or "replaced by" of their own. | `service/contradictions.py` |
| G6 | **Search ranks four indexes by their raw scores in one list.** BM25 scores from different indexes aren't comparable, so a claim and a commit are ordered by accident. Only searches with no result are recorded. | `service/reads.py:598` |
| G7 | **Where evidence came from isn't recorded as trust.** A claim resting on a mail someone sent me and one resting on my own commit look the same, on a card and to the wiki. Cards show evidence titles, not the passage. | `service/review.py:90`, `evidence` table |
| G8 | **The vault's notes are written by Claude with no check by code.** Obsidian loads remote images, so a note with an image address built from my data would send it out when I open the note. The agent reads private data and untrusted mail, chat and documents in one run. | `contracts/agent/end_of_day.md` |
| G9 | **Connector tools are allowed by the words in their names** (`fetch` and `download` count as reading), not from a fixed list, and nothing notices when a connector changes a tool's description. | `service/tool_rules.py` |
| G10 | **Hidden text reaches Claude.** Repository files, chat messages and commit messages aren't stripped of HTML comments or invisible Unicode. | `service/repos.py`, `service/chat.py` |
| G11 | **Secrets are found by patterns only.** A rule-based detector reached 0.07 recall on high-sensitivity categories in an independent benchmark. | `service/redact.py` |
| G12 | **Up to 25 confirmations a day, one click each.** The evidence on per-item approval is the weakest point of the design, and the wiki's long-term content depends on it. | `service/review.py` |
| G13 | **Unconfirmed claims expire silently at 90 days.** | `service/retention.py` |
| G14 | **Copies outlive a delete:** the vault's notes and the Chat cards. Already known; nothing tests it. | `end_of_day_agent.md` |
| G15 | **Tests run by hand,** with no run on push. | no CI |
| G16 | **Meetings (Phase 3) aren't built,** and the speech choice was made on read Brazilian sentences. | `docs/whisper_benchmark.md` |
| G17 | **Backup is still open** (brief §15). | |

## The plan

Six steps, in this order. Step 1 comes first because it decides whether each later step earned its place. Steps 2 and 3 are independent of each other.

### Step 1. Measure (2 to 3 weeks)

The labs' minimum, from Anthropic's November 2026 guidance: write down what's measured and the pass mark before running, check the grader against a person, repeat each case, keep a baseline, compare versions on the same items.

1. **Record what ran** (G2). Each run stores the model, Claude Code's version, the commit of the instructions, turns, tokens, cost, tools denied and how it ended. Pin the model in `claude_argv`; a model change becomes my decision.
2. **Log every search** (G6), not only misses: the query, kinds, the ids returned, and which of them Claude opened next (`get_evidence`, `get_wiki_page`). Redacted, under retention, shown in the frontend, deleted with what it points to. This is the source of real test queries: made-up queries were found to be twice as long as real ones and to pick different winners.
3. **A frozen copy of the store** for tests, made by `pwi eval snapshot`, kept in `~/.local/share/pwi/evaluation`, under retention and deletion like the rest.
4. **Five test sets,** all from my own data:

   | Set | Size | Built from | Measures |
   |---|---|---|---|
   | Search | 200 to 400 queries | the search log, each with a line on what should come back | recall and rank, by language and by kind of question |
   | Claims | about 100 pairs | my confirm, correct and retract history, plus blind labels | does the evidence support the claim; false commitments; wrong owner or date |
   | Wiki | 25 questions or more | my real "why" and "where does it stand" questions | answered from the wiki alone, search alone, and both; facts kept from the sources; page size against its sources |
   | Numbers | 60 questions | SQL written apart from the tools | durations, counts and dates in `get_day` and `get_week`, with questions about things that didn't happen |
   | Attacks | 30 cases | planted through each real channel: a README, a commit message, a chat message, a mail, a document | written, passed the checks, reached a wiki statement, changed a later answer: each counted apart |

5. **Three levels** for each change: the tools called directly; a plain loop over the tools; the real `claude -p` run with its tool list. A score at one level doesn't transfer to another.
6. **Rules for every run of the suite:** 3 repeats, the spread reported; a baseline arm (for the wiki: the same questions with the wiki turned off); the pass mark written before the run; the same grader for both sides of a comparison.
7. **Check the grader.** Any Claude grader is compared with my blind labels on about 100 items, with agreement corrected for chance, before its numbers count. Where code can decide, code decides.
8. **Unit tests on every push** (G15), in GitHub Actions. They hold no work data. The five sets never leave the laptop.

*Done when* `pwi eval run` gives a table for the current system, and I've set the pass marks from it, as the brief's §16 says.

### Step 2. Make statements trustworthy (3 to 4 weeks)

1. **Check support, not existence** (G3):
   - **Narrower citations.** A file citation gains a line range, an event or message citation a short quote. Code checks that the quote is in the source.
   - **A checker run.** After the end-of-day agent and after each compile run, a second headless run reads each new claim or statement beside its evidence, and answers supported, contradicted or not found, with the passage that says so. Code checks that the passage is in the evidence; a verdict without one counts as not found.
   - **The checker is another Claude model than the writer's,** pinned by id. It gets no tools: the layer hands it the claim and its quoted evidence, so text in the evidence can't make it do anything. Its verdict is stored per citation, marked *same family*, since a model checking its own family shares some of its blind spots.
   - **Shadow mode first.** Its verdicts are stored and compared with my blind labels, and don't reorder my review until agreement passes the mark set in step 1.
   - **Later, if my company allows the data to go there:** two checkers from other model families (a Google model and an OpenAI model, through GitHub Copilot CLI, reviewed and pinned). Both supported passes; both not found or contradicted goes to the top of my review; a disagreement comes to me with both verdicts. No third model reconciles them, since the disagreement is the signal.
   - **What happens next.** Not found and contradicted go to the top of my review and stay out of the wiki. The check is against the evidence itself, not the claim text: one study found citations 0.86 precise against a summary and 0.12 against the sources.
   - **Later, by measurement:** a small local model as the first pass for short quotes. In English they match a frontier grader (0.88 to 0.90 against 0.87); nothing tests them in Portuguese, so the claims set decides.
2. **Record where evidence came from** (G7). Code, not Claude, sets an origin on each piece of evidence when it's saved: *mine* (my commits, my sessions, messages I sent, documents I edited), *others'* (messages and documents from other people, repository files by other authors), *web* (pages I visited). A summary can't raise it.
3. **Change the label rule** (G4). A statement's label is capped by its weakest citation; items from one chain count once; a statement resting only on others' or web evidence says so. This settles "Labels" in the wiki doc's *Not verified yet* list.
4. **Retire old values by rule** (G5):
   - a decision or fact can carry a subject and a relation (*billing-service · retry policy*), and `true_from`;
   - a new claim on the same pair retires the old one by rule, keeps it for history, and both show the pointer;
   - Claude proposes the pair, and a proposed merge or replacement is a card for me, since a wrong merge silently removes a current value;
   - `search` and the wiki show only the current value by default: a stale statement beside the current one cut accuracy from 100% to 44.6%;
   - word overlap stays only as a hint, tested against look-alike pairs that don't conflict.
5. **Three lookups before a commitment is saved**, since they explain the false ones in the one study that counted them: was the request already answered (60%), is it someone else's (28%), is there a request at all (13%). The owner comes from who sent the message, not from its text. The commitment keeps the speaker's words as its quote. `owner` and `due_at` stay optional, since a required field invites an invented value.
6. **The wiki after each compile:**
   - probe the new version with questions drawn from its sources, and put back what was dropped (unchecked compilation failed badly in 53% to 60% of cases; probing recovered 80% of the loss);
   - count the facts kept;
   - refuse a page that grows past its sources;
   - rebuild `status` from the current claims each time, not from its last text.
7. **No silent expiry** (G13). A week before unconfirmed claims expire, the review lists them once: confirm, or let go.

*Done when* the claims and wiki sets show the share of unsupported statements, before and after, with the same grader.

### Step 3. Close the security and privacy gaps (2 to 3 weeks)

1. **Clean text before Claude sees it** (G10). Strip HTML comments and invisible Unicode (zero-width, tag block, variation selectors, direction marks) in `read_repo`, `chat_messages`, commit messages and `validate.py`, and count what was removed in the result. Removing HTML comments alone took one measured attack to zero.
2. **Check the vault's notes by code** (G8). After each run, before anything else reads them: no remote images, no raw HTML, links only to addresses that appear in the day's evidence. A day that fails stays in a holding folder and is listed under *Needs your attention*.
3. **Fix the tool list** (G9). `pwi eod check` stores the exact connector tools I accepted, with a hash of each description. A new tool or a changed description is denied until I accept it. Name rules remain only as the first suggestion.
4. **Cards that carry their evidence** (G7, G12). Each card shows the claim, its origin and the quoted passage, all from the stored record.
5. **A second pass for secrets** (G11). Patterns stay first. A small local classifier, reviewed and pinned (OpenAI's Privacy Filter is Apache-2.0 and has a secret category), runs second on what's stored and on what `read_repo` returns. Measured on my data before it's adopted: its 96% is the vendor's own figure. *Changes the brief's one-local-model rule.*
6. **A forget test** (G14). A test deletes a planted item, then looks for it in every tool, each index, the wiki, the static site, the search log and the test copies. It reports the vault notes and Chat cards that still hold it. The layer then edits those cards and lists those notes for me.
7. **The attack set from step 1 runs on every change** to instructions, tool lists or models.
8. **Decide the backup** (G17): where it goes, and where its key lives.

*Done when* the attack set and the forget test pass, repeated 3 times.

### Step 4. Better search, in the order the evidence supports (1 to 2 weeks, then a decision)

1. **Fix the ranking** (G6). Rank each index by itself and merge by rank, so claims, commits, pages and wiki sections compete fairly.
2. **Controls for the agent:** the text around a hit, ids to leave out because they were already seen, current claims only by default with the *replaced by* pointer, and duplicates folded.
3. **Exact terms in queries.** The `search` instructions ask for identifiers, file names, error text and names beside the Portuguese and English wording. Exact rare terms added 0.11 to 0.19 to keyword search for code.
4. **Keywords and questions for every claim, session note and wiki section,** written by the run that saves them and indexed in their own column beside the exact text. One study measured +8.7 recall points for keyword search, and +24.4 where the question used words the text lacked. This is what `key_terms` already does for pages.
5. **Then decide on a local embedding model,** with the search set:
   - try one small model with a permissive licence and a measured Portuguese score (bekko-embedding-v1-a25m, granite-embedding-97m-multilingual-r2 or mDenseOn), in `bench/`, as Whisper was;
   - adopt it only if it leads keyword search by 0.04 nDCG@10 or more on my queries, and the merged ranking beats the better of the two;
   - vectors in the same SQLite file, with no approximate index at this size;
   - *it would change the standard-library-only install and the one-local-model rule.*

*Done when* the search set shows the gain of each of 1 to 4, and 5 is decided either way.

### Step 5. Run the agents the way the labs run theirs (2 weeks)

1. **A contract per run.** Each run ends with a short structured report that code reads. Code checks the result, not Claude's account of it: every claim has evidence, the notes passed their check, the page passes `wiki_lint`, the counts match the store.
2. **Budgets and clean failure.** A cap on turns and cost per run; `--permission-prompts none`; a `StopFailure` hook so a run that died on an API error is recorded as such; a check of `mcp_server_errors` at start, so a run without the layer's tools stops at once.
3. **Fewer, better questions for me** (G12). This is the brief's main bottleneck:
   - cards ordered by risk: checker verdict, origin, a date or an owner, a proposed replacement;
   - one card per project for the low-risk items that passed every check, confirmed together, each still opened with a click;
   - individual cards for commitments, replacements and anything resting on others' evidence;
   - a known-wrong card now and then, if I turn it on, to measure how carefully I'm reviewing;
   - a daily cap that follows my real confirmation rate.

   Only I verify; that doesn't change.
4. **Instructions are releases.** A change to `contracts/` runs the suite at the third level before it's installed, with the result kept beside the commit. A line added to instructions gets tested with and without. Anthropic traced a quality drop to one system-prompt line that had passed weeks of testing.
5. **A model change is a release too:** rerun the suite with the same grader, then remove the instructions and checks the new model no longer needs, one at a time.
6. **Smaller tool results.** Results are JSON indented by two spaces, up to 40,000 characters. Compact JSON, and the second level of the suite to check that Claude still picks the right tool among 24 (the wiki doc's open question).
7. **Keep the transcript of a failed run,** locally, under the audit trail's retention, so failures can be read and turned into test cases.

*Done when* a prompt or model change can't be installed without a suite result.

### Step 6. Meetings, built on the evidence (the brief's Phase 3)

1. **Gate each track with voice-activity detection before transcribing.** Whisper large-v3-turbo wrote text on every clip confirmed to hold no speech, and with two tracks each one is silent while the other side talks.
2. **Choose the model on my own recordings.** Parakeet TDT 0.6B v3 against large-v3-turbo, on European Portuguese, English and mixed segments scored apart. On English meeting speech Parakeet scored 9.4% to 11.4% errors against 13.9% to 16.1% for turbo. No source since February tests Portuguese and English mixed in one meeting, so only my recordings can decide.
3. **No free rewriting of transcripts by a model.** Text-only correction broke 13% to 32% of transcripts that were right. Corrections are limited to a glossary of names and project terms.
4. **A transcript is others' evidence** (step 2), and claims from it go through the checker and the three commitment lookups.

## What I shouldn't build

| Idea | Why not |
|---|---|
| A memory product or a knowledge graph in place of claims | No consistent gain over raw records in independent studies; one system chose the right update operation 20% of the time. |
| Nightly rewriting of wiki prose | Rewritten memory degraded over time and fell below having none in one study. |
| A reranker, static embeddings, a router per query, graph search | Each failed to help, or hurt, in the studies read. |
| A classifier that blocks injected text | At real attack rates its alarms are nearly all false; it suits a flag for my review. |
| Sub-agents for search | 41.8% of failures were silent and confident at the hand-off. |
| Interrupting me with proactive help | 26.7% acceptance while I'm working, against 97.8% for work done while I'm away. |
| Trusting a public memory benchmark to pick a design | The grader alone moves scores by up to 7.2 points. |

## What changes in the brief (v0.8 → v0.9), for me to decide

| v0.8 | Proposed |
|---|---|
| Standard library only; the only local model is speech-to-text. | Up to three more local models, each only if my own test set shows it earns its place, each reviewed and pinned: a checker for short quotes (step 2), a detector for secrets (step 3), an embedding model (step 4). |
| Searches aren't kept, except misses. | Every search is logged, redacted, under retention and deletion. |
| The evaluation is five hand-labelled days. | A frozen copy of the store and five test sets, kept locally under the same rules. |
| A statement's label is its best citation. | Its weakest, with origin shown. |
| Claims are confirmed one by one. | Low-risk claims that passed every check can be confirmed together, per project. |
| Unconfirmed claims expire after 90 days. | They're listed once before they go. |
| The model for unattended runs is Claude Code's default. | Pinned; a change is a release. |

## Order and effort

| Step | Depends on | Effort | New dependency |
|---|---|---|---|
| 1. Measure | nothing | 2 to 3 weeks | none |
| 2. Trust | 1 | 3 to 4 weeks | none at first |
| 3. Security and privacy | 1 (attack set) | 2 to 3 weeks | none, until the secrets detector |
| 4. Search | 1 (search log) | 1 to 2 weeks | none, until the embedding decision |
| 5. Agents | 1 | 2 weeks | none |
| 6. Meetings | 2, 3 | the brief's Phase 3 | a speech model, already planned |

Three parts need nothing from step 1 and could go first: cleaning text (step 3.1), the notes check (step 3.2) and the ranking fix (step 4.1).

## Open questions

- **Checker model.** Decided for now: another Claude model than the writer's. Open: may claims and their evidence go to Google and OpenAI models through GitHub Copilot CLI, and does Copilot CLI run unattended with every tool off and a chosen model?
- **The search log.** Is keeping every query acceptable under my company's policy, as the audit trail is?
- **Planted wrong cards.** Do I want them?
- **The MCP revision of 28 July 2026** removes the handshake and sessions. The service already works without a handshake per connection; when Claude Desktop for Linux moves to it, the bridge and `handlers.py` need checking.
