# Community views (Hacker News / Reddit) on knowledge bases for humans and AI agents, 2025–2026

> **Method and access limits (read first).** This session could not open news.ycombinator.com, hn.algolia.com, or reddit.com directly: the network proxy refused them, and the search tool blocks reddit.com. Everything below comes from search-engine snippets of HN item pages, plus blogs and aggregators that quote those threads. As a result:
> - Point and comment counts are approximate. They mostly come from aggregator crawl snapshots, and I flag where sources disagree.
> - Commenter quotes are from search snippets, so they are partial and may lack context.
> - **No Reddit thread could be read or verified.** Reddit sentiment is a gap throughout; the only Reddit-adjacent material is blogs that themselves summarize community discussion.
> - HN item dates are inferred from item-ID ranges and from the aggregators. Roughly: IDs 42–43M ≈ early 2025, 44M ≈ mid-2025, 45M ≈ Sept–Oct 2025, 46M ≈ Dec 2025–Jan 2026, 47M ≈ Feb–Apr 2026, 48M ≈ May–Jul 2026, 49M ≈ late 2026.
> - Re-running this with hn.algolia.com allowed in the session's network settings would let the counts and quotes be verified.

## 1. Reaction to Karpathy's "LLM Wiki" gist and LLM-maintained wikis

### Takeaway
The gist (created Apr 4, 2026) drew a mid-sized, split HN thread, roughly 274–296 points and about 89 comments. The main argument was whether it is "just RAG". Supporters said the new part is the write/maintain loop. Critics raised compounding hallucinations, lint scaling, and whether a wiki can really stand in for continual learning. A wave of "Show HN" implementations followed. Reported results are almost entirely anecdotal.

### Cited Findings
- **The gist itself:** created April 4, 2026. It describes a pattern for building personal knowledge bases with LLMs. — [Karpathy gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- **Main HN thread "LLM Wiki":** an aggregator reports 274 points and 89 comments at crawl time, while another source says 296 points. The difference is probably crawl timing. — [HN item 47640875](https://news.ycombinator.com/item?id=47640875); [marvin-42 summary](https://insights.marvin-42.com/articles/hacker-news-picks-up-karpathys-llm-wiki-pattern-for-persistent-knowledge-bases)
- **"Just RAG" critique:** a commenter (kenforthewin) wrote "This is just RAG. Yes, it's not using a vector database – but it's building an index…". The argument is that putting the best data into context is RAG, whether it comes from vectors or from a structured index or filesystem. — [HN item 47644949](https://news.ycombinator.com/item?id=47644949)
- **Rebuttal:** a commenter (darkhanakh) wrote "eh i'd push back on 'just RAG'…". The argument is that the novel part is the write loop: the LLM authors and maintains the pages, builds backlinks, and files its outputs back into the wiki. — [HN item 47645066](https://news.ycombinator.com/item?id=47645066)
- **Continual-learning skepticism:** a commenter wrote "I'm surprised Karpathy thinks this is a viable solution for a quasi-continual le[arning]…" and asked why he chose a wiki over a version-controlled or other model. — [HN item 47654076](https://news.ycombinator.com/item?id=47654076)
- **Error compounding and scaling worries raised in the discussion:**
  - Does an LLM summarizing its own summaries bake hallucinations into the wiki as "facts"?
  - Does linting for inconsistencies scale as N×N comparisons across pages?
  - Someone also raised model collapse, citing the 2024 Nature paper on recursively generated data.
  - Sources: [aggregator summary of thread](https://insights.marvin-42.com/articles/hacker-news-picks-up-karpathys-llm-wiki-pattern-for-persistent-knowledge-bases); [Lobster Pack](https://www.lobsterpack.com/blog/karpathy-llm-wiki-idea-files/)
- **Karpathy's own HN comment:** one search summary says it was flagged or removed. Its content is unverified. — [search result referencing HN 47654076 thread](https://news.ycombinator.com/item?id=47654076)
- **Follow-on builds posted to HN:**
  - "Show HN: A Karpathy-style LLM wiki your agents maintain (Markdown and Git)" — [HN 47899844](https://news.ycombinator.com/item?id=47899844)
  - "Karpathy LLM Wiki pattern integrated into Obsidian agentic workflow" — [HN 48351115](https://news.ycombinator.com/item?id=48351115)
  - "Show HN: Mcptube" (a wiki variant built from YouTube videos) — [HN 47754559](https://news.ycombinator.com/item?id=47754559)
- **Spread:** secondary sources say the gist spawned "30+ implementations" and forks such as secure-llm-wiki and memwiki. This is an unverified aggregator claim. — [search summary of ronancodes / affine / unabyss write-ups](https://ronancodes.github.io/llm-wiki/docs/research/karpathy/)
- **The "idea file" framing:** some write-ups treat the gist as an example of sharing instructions rather than code. One sums it up as "Obsidian is the IDE, the LLM is the programmer, the wiki is the codebase." — [Lobster Pack](https://www.lobsterpack.com/blog/karpathy-llm-wiki-idea-files/)
- **Practitioner reports (blogs, anecdotal):**
  - An R&D World piece is headlined "Is Karpathy's viral LLM wiki helpful? Mostly yes, one month in." I could not fetch its body. — [rdworldonline](https://www.rdworldonline.com/is-karpathys-viral-llm-wiki-helpful-mostly-yes-one-month-in/)
  - A HackerNoon author built a self-maintaining knowledge base for 6 projects with Claude Code. — [HackerNoon](https://hackernoon.com/how-i-built-a-self-maintaining-knowledge-base-for-6-projects-using-claude-code-and-karpathys-llm-wiki)
  - A Substack builder of an open-source "llm-knowledge-base" (Claude Code as engine, Obsidian as UI) warns that letting the LLM decide everything produces "a lot of meaningless data", such as junk concept tags. His recommendation: "the LLM writes the wiki, you curate." — [acydoan Substack](https://acydoan.substack.com/p/llm-knowledge-base)

### Inferences
- HN's consensus seemed to be "interesting pattern, but not new in kind." It was not hostile: about 270+ points is solid engagement without being a top-of-year story.
- The most substantive criticism concerns **error accumulation without provenance**, which matches the concerns in section 6.
- The visible results are anecdotal. I found no measured evaluation, such as accuracy against a RAG baseline, in community threads.

### Gaps
- Could not read the full HN comment trees, so I cannot rank comments by votes.
- Reddit reaction (r/LocalLLaMA, r/ObsidianMD, r/ClaudeAI) is entirely unverified because Reddit was inaccessible.
- The body of the R&D World "one month in" article could not be fetched.

## 2. PKM with AI (Obsidian + LLM, second brain, Zettelkasten)

### Takeaway
The strongest HN current is skeptical of the "second brain" itself: write-once, read-never notes and the collector's fallacy. Many commenters insist that writing is thinking, so AI-written notes are seen as hollow. The pragmatic middle ground is to keep AI-generated content separate from your own notes, use AI for search and retrieval or as a sparring partner, and write the conclusions yourself.

### Cited Findings
- **"I deleted my second brain" (HN, ~mid-2025):**
  - The author wiped a roughly 10,000-note Obsidian vault. Most notes were "write once, read never," and the system had started replacing the author's thinking instead of accelerating it. The advice: write down only what you can't remember.
  - Thread commenters stressed the Zettelkasten rule of never storing anything unprocessed.
  - Source: [HN 44402470](https://news.ycombinator.com/item?id=44402470)
- **"Ask HN: How would you build second brain in the AI era?" (~Aug 2025):** a commenter said plain-text search made manual links largely unnecessary, and that a local LLM using the notes as context made the system more useful. — [HN 44839965](https://news.ycombinator.com/item?id=44839965)
- **The "writing is thinking" camp:**
  - "Do your own writing" (~early 2026) — [HN 47573519](https://news.ycombinator.com/item?id=47573519)
  - "Your intellectual fly is open when you use an LLM to author a post" — [HN 49585644](https://news.ycombinator.com/item?id=49585644)
  - "How to Write with an LLM" — [HN 49747070](https://news.ycombinator.com/item?id=49747070)
  - Comments in these threads say LLM drafts come out "opinion-less." The suggested alternatives are to use model output as a blueprint and then write your own draft, or to treat the LLM as a thinking partner. These are summaries of search snippets.
- **Practitioner pattern in Obsidian + Claude Code guides:** keep agent outputs in a separate folder so they stay distinguishable from your own writing, and have the agent respect the existing link structure. This is vendor/blog content, not community consensus. — [MindStudio](https://www.mindstudio.ai/blog/ai-second-brain-claude-code-obsidian-architecture)
- **RAG-over-vault plugins:** the Smart2Brain README admits the assistant may give unsatisfying answers when the vault lacks relevant notes. — [Smart2Brain README](https://github.com/your-papa/obsidian-Smart2Brain/blob/main/README.md)
- **Privacy:** people worry about sending a whole vault to a cloud LLM, which pushes users toward local setups (Ollama, Smart Connections). — [DEV: 6th attempt second brain](https://dev.to/huy_tieu/i-finally-built-a-second-brain-that-i-actually-use-6th-attempt-4075); [HPE community guide](https://community.hpe.com/t5/software-general/building-a-local-ai-second-brain-a-practical-guide-to-obsidian/m-p/7256642/highlight/true)
- **Abandonment is common:** the DEV post's own title is "I finally built a second brain that I actually use (6th attempt)." — [DEV](https://dev.to/huy_tieu/i-finally-built-a-second-brain-that-i-actually-use-6th-attempt-4075)

### Inferences
- The LLM Wiki pattern partly answers the maintenance-burden complaint by shifting the toil to the LLM. That trade-off runs straight into the "writing is thinking" objection. Expect the same split: a researcher compiling sources will be happy with it, while someone using notes to think will be skeptical.
- The collector's fallacy is likely to get worse when ingestion is free.

### Gaps
- No direct r/ObsidianMD, r/PKMS, or r/Zettelkasten threads were accessible. "Keep AI out of your vault" sentiment, which is widely believed to be strong on r/ObsidianMD, could not be verified with links.
- No Notion AI or Logseq community data was found.

## 3. Agent memory and assistant "memory" features

### Takeaway
HN users are ambivalent about ChatGPT memory. The complaints are about contamination across topics, opacity (suspected memory that can't be seen or managed), and privacy. A number of users turned it off. Claude's opt-in, project-scoped, file-based design was received more favorably. Developer memory layers (Mem0, Zep, Letta) face skepticism over benchmark disputes, extraction errors, and the fact that simple baselines (full context, plain files) score about as well.

### Cited Findings
- **ChatGPT memory:**
  - "I turned off chatGPT memory entirely because it doesn't know how to segment itse[lf]…" The commenter said answers were more concise with it off. (~Oct 2025) — [HN 45662102](https://news.ycombinator.com/item?id=45662102)
  - "One important note is that chatgpt has a memory you cannot see, besides chat his[tory]…" The commenter claimed recall persisted after wiping memory and chats. Others in the thread could not reproduce this, so it is disputed. (~May 2025) — [HN 44059140](https://news.ycombinator.com/item?id=44059140)
  - "…similar to how ChatGPT's memory feature worked up until about four weeks ago…" This complains of undisclosed changes to how memory works and less predictable responses. (~May 2025, after the April 2025 chat-history-reference rollout) — [HN 43884978](https://news.ycombinator.com/item?id=43884978)
  - Dissent: "I really think this memory thing is overstated on Hacker News…" The point is that ordinary users like the feature. (~Jan 2026) — [HN 46532743](https://news.ycombinator.com/item?id=46532743)
  - Older (2024) baseline: the launch thread and an Ask HN thread voiced privacy unease. — [HN 39360724](https://news.ycombinator.com/item?id=39360724); [HN 40138015](https://news.ycombinator.com/item?id=40138015)
- **Claude memory:**
  - The HN thread "Claude's memory architecture is the opposite of ChatGPT's" (~Sept 2025) discussed Claude's explicit, tool-invoked memory versus ChatGPT's automatic profile injection. Some found memory valuable for ongoing projects, and several preferred the opt-in approach. — [HN 45214908](https://news.ycombinator.com/item?id=45214908)
  - Anthropic shipped memory as opt-in with per-project separation: Team and Enterprise in Aug/Sept 2025, then Pro and Max in Oct 2025, then broader availability in March 2026. — [VentureBeat](https://venturebeat.com/ai/anthropic-adds-memory-to-claude-team-and-enterprise-incognito-for-all); [MacRumors](https://www.macrumors.com/2025/10/23/anthropic-automatic-memory-claude/); [Anthropic](https://www.anthropic.com/news/memory); [Bloomberg](https://www.bloomberg.com/news/articles/2026-03-03/anthropic-tries-to-win-users-from-chatgpt-with-memory-feature)
  - In "Show HN: Recall" (Redis-backed Claude memory), commenters said Claude Code 2.0 now has native memory. They described it as notes appended to files read at startup, as opposed to on-demand database queries. — [HN 45516584](https://news.ycombinator.com/item?id=45516584)
- **Mem0, Zep, Letta:**
  - The Mem0 launch thread (2024, older) had a commenter suspect that new accounts were posting "kudos." Another noted the memory logic is Python-only, with the JS package acting as a client for the hosted service. — [HN 41447317](https://news.ycombinator.com/item?id=41447317)
  - "I've experimented quite a bit with mem0… for my Open[…]": the commenter said it stopped being useful quickly, and that errors come from the LLM extraction layer rather than from storage. (~Apr 2026) — [HN 47770220](https://news.ycombinator.com/item?id=47770220)
  - "Ask HN: Mem0 stores memories, but doesn't learn user patterns": Letta's self-editing memory was described as closer to the goal but still lacking implicit learning. — [HN 46891715](https://news.ycombinator.com/item?id=46891715)
  - In "Show HN: Mnemora", the author criticized Mem0, Zep, and Letta because all of them route every read and write through an LLM. — [HN 47260077](https://news.ycombinator.com/item?id=47260077)
  - "Why would I use this over Mem0 or Zep? What does it do that they don't?" This is a typical skeptical reply to new memory launches. — [HN 48631560](https://news.ycombinator.com/item?id=48631560)
  - "Show HN: A file-based agent memory framework that works like skill" (~Jan 2026) is part of a trend toward plain files. — [HN 46511540](https://news.ycombinator.com/item?id=46511540)
- **Benchmark dispute (measured, but contested):**
  - Zep's LoCoMo score was 65.99% in Mem0's paper, rose to 75.14% after Zep corrected the harness, and then fell to 58.44% when Mem0 re-ran it.
  - A full-context baseline scored about 73%, and Letta's plain filesystem baseline scored 74.0%.
  - The parties dispute who misconfigured what.
  - Sources: [Bloo-mind essay "Benchmark Theatre"](https://essays.bloo-mind.ai/posts/2026-05-20-mem-eval/); [beri.net](https://www.beri.net/article/zep-vs-mem0-vs-postgres-agent-memory-store-buy-last-2026)

### Inferences
- The reported numbers suggest that dedicated memory layers often fail to beat plain full context or file-based baselines on LoCoMo. That supports the community drift toward plain markdown files and the "buy the memory store last" advice.
- The most common user complaint is about scoping, meaning memories leaking across topics. Explicit, scoped memory (projects, files the user can see) is the design people praise.

### Gaps
- I could not find the HN thread for Anthropic's own memory launch.
- No Reddit r/ChatGPT or r/ClaudeAI memory complaints were verifiable. These are believed to be voluminous, for example memory filling up or the model citing wrong "facts" about the user, but no links are available.

## 4. RAG vs long context, grep vs vectors, hybrid search and GraphRAG

### Takeaway
The "RAG is dead" claim (the RAG Obituary essay, Oct 2025) got heavy pushback on HN. Commenters argued that naive chunk-and-embed is dying, not retrieval, and that enterprise corpora don't fit in context. Claude Code's grep and agentic search choice is widely cited as evidence for "agentic search over vectors" for code. The evidence for that is internal and anecdotal. Cursor's measurements favor a hybrid of grep plus semantic search. Hybrid search plus reranking is the most widely endorsed default. GraphRAG has little evidence of production value.

### Cited Findings
- **"The RAG Obituary: Killed by agents, buried by context windows" (HN, ~Oct 1, 2025):**
  - Top pushback (Oct 2, 2025): the essay extrapolates from Claude Code grepping a local codebase to all document retrieval, which is "a massive logical leap," and "even with 2M token context windows, you can't fit an entire enterprise knowledge base." — [HN 45445280](https://news.ycombinator.com/item?id=45445280)
  - Other comments: RAG is misused, not dead; long context costs time and money; on-demand agentic retrieval beats front-loading context. — [HN 45439997](https://news.ycombinator.com/item?id=45439997)
  - Vendor and practitioner rebuttals: "No, RAG is not dead" (the arguments are about bad RAG implementations) — [Algolia](https://www.algolia.com/blog/ai/rag-is-not-dead); [Geir Freysson](https://geirfreysson.com/posts/2025-10-04-rag-the-reports-on-my-death-are-greatly-exaggerated/index.html)
- **Claude Code and grep:**
  - Boris Cherny reportedly said on HN that early Claude Code used "RAG + a local vector db, but we found pretty quickly that agentic search generally works better." Another Anthropic engineer reportedly said, "In our testing we found that agentic search outperformed [it] by a lot." These are quoted via secondary blogs, and one blog notes the judgment rested largely on internal impressions. — [vadim.blog](https://vadim.blog/claude-code-no-indexing/); [thelastaimile](https://thelastaimile.substack.com/p/agentic-search-the-slow-death-of)
  - HN thread (~Jan 2026): "I found out that Claude Code and OpenCode doesn't do vector search and embedding…". Pushback in the thread said vector search "is way better and saves on tokens", that grep misses vocabulary mismatch, and that "grep is not RAG." — [HN 46631689](https://news.ycombinator.com/item?id=46631689)
  - Counter-data: Cursor kept embeddings and reported about 12.5% higher accuracy on its own benchmark when semantic search was added to grep. A Milvus critique says iterative grep loops cost far more per query than a precomputed lookup. Both are vendor-measured. — [dbggr summary](https://dbggr.dev/articles/embeddings-vs-grep-agentic-search/); [besthub](https://www.besthub.dev/articles/why-claude-code-and-cursor-abandoned-vector-databases-for-agentic-retrieval-9dad68e8f191)
- **Hybrid search, reranking, GraphRAG:**
  - Practitioner guides say hybrid search plus a reranker beats pure vector search, at a latency cost. — [Medium](https://medium.com/@yangwj2011/improving-retrieval-augmented-generation-rag-performance-through-hybrid-search-and-reranking-134826257459)
  - GraphRAG: Gradient Flow (2024, older) said its authors "barely know of any examples of production deployments that are offering real business value," and that experiments are resource-heavy. — [Gradient Flow](https://gradientflow.substack.com/p/graphrag-design-patterns-challenges)
  - NVIDIA's example found that Graph RAG beat text RAG on a small dataset, but the combined approach "doesn't consistently beat the ground truth yet." — [NVIDIA PR](https://github.com/NVIDIA/GenerativeAIExamples/pull/144/files)

### Inferences
- The emerging consensus: for code and small corpora, use agentic grep/glob/read plus long context. For large or heterogeneous corpora with vocabulary mismatch, use hybrid BM25 + vectors + a reranker. GraphRAG is for multi-hop, relationship-heavy queries only, and production evidence for it is thin.
- The LLM Wiki pattern sits between these: it precomputes structure (an index plus links) and lets the agent navigate it with file tools.

### Gaps
- r/RAG and r/LocalLLaMA production war stories were inaccessible.
- I found no independent, public benchmark of grep versus embeddings for coding agents. The evidence is vendor-internal on both sides.

## 5. Context engineering: CLAUDE.md, AGENTS.md, llms.txt

### Takeaway
An ETH Zurich study (Feb 2026), heavily discussed on HN, found that AGENTS.md files barely change success rates. LLM-generated files slightly hurt and cost about 20% more. Hand-written files slightly help but not significantly. A Jan 2026 field study found efficiency gains instead. Community consensus: keep these files short, hand-written, and non-duplicative, and don't let the LLM write them. On llms.txt, HN is largely skeptical. Server logs show no crawler fetches, although some library maintainers find it useful for feeding docs into context.

### Cited Findings
- **"Evaluating AGENTS.md: are they helpful for coding agents?" (HN, ~Feb 2026; arXiv 2602.11988):**
  - Findings: LLM-generated context files lowered success, and hand-written ones slightly raised it, neither significantly. Context files add about 19–23% to inference cost.
  - HN commenters said the study shows that bloated "context stuffing" hurts, not context files as such. Others reported that the files save some time without improving success.
  - A sampling critique: public repos that already have AGENTS.md are "overwhelmingly small, recent, many AI-generated."
  - Sources: [HN 47034087](https://news.ycombinator.com/item?id=47034087); [jangwook summary](https://jangwook.net/en/blog/en/agents-md-effectiveness/); [Patrik Björklund rebuttal](https://pbjorklund.com/articles/agents-md-paper-vs-practice/)
- **Counter-evidence (measured):** a field study (arXiv 2601.20404, Jan 2026) found AGENTS.md cut median runtime by 28.64% and output tokens by 16.58% at comparable completion. A July 2026 study found no measurable difference in correctness. — [generativelabs](https://www.generativelabs.com/insights/claude-md-agents-md-context-files); [Harbor](https://gethrbr.com/blog/is-agents-md-useful)
- **llms.txt:**
  - "I have bad news for you: LLMs are not reading llms.txt nor AGENTS.md files f[rom websites]…" The commenter saw no meaningful requests in server logs, including none from Anthropic's crawlers. — [HN 47058870](https://news.ycombinator.com/item?id=47058870)
  - "Does it work though? The big LLM crawlers do not read llms.txt…" (~mid-2026) — [HN 48235333](https://news.ycombinator.com/item?id=48235333)
  - "Ask HN: What's the Point of llms.txt?" (~Jul 2025) — [HN 44584951](https://news.ycombinator.com/item?id=44584951)
  - "Ask HN: Is LLMs.txt a REAL thing now?" (~Mar 2025) — [HN 43438190](https://news.ycombinator.com/item?id=43438190)
  - The proposer (2024, older) said llms.txt is for building context documents at inference time, not for crawlers. A FastHTML maintainer uses it so that AI can help users with a library too new to be in training data. A manipulation concern was raised: crawlers could be served content different from what humans see. — [HN 41439983](https://news.ycombinator.com/item?id=41439983); [HN 41443206](https://news.ycombinator.com/item?id=41443206)

### Inferences
- Context files are best seen as cost and speed optimizations, plus guardrails for non-obvious conventions, rather than accuracy boosters. This matches the community's "less is more" view.
- llms.txt works as user-pulled context (pasting docs into an agent), not as an SEO or crawler signal.

### Gaps
- I found no r/ClaudeAI or r/ExperiencedDevs threads on CLAUDE.md practices, because Reddit was inaccessible.

## 6. Hallucination, grounding and trust in AI-compiled knowledge; memory poisoning

### Takeaway
Trust concerns centre on errors compounding when LLMs summarize their own output, as raised in the LLM Wiki thread. Security attention shifted in 2025–2026 to persistent memory poisoning: injected instructions that live in memory or knowledge files and fire in later sessions. Examples are Rehberger's ChatGPT memory exploit (2024), MemGhost (Jul 2026), and OWASP's agentic category ASI06. I could not verify the specific HN threads on these.

### Cited Findings
- In the LLM Wiki discussion, commenters worried that hallucinations get "baked in" as facts when an LLM summarizes its own summaries, and raised model collapse. — [marvin-42](https://insights.marvin-42.com/articles/hacker-news-picks-up-karpathys-llm-wiki-pattern-for-persistent-knowledge-bases); [Lobster Pack](https://www.lobsterpack.com/blog/karpathy-llm-wiki-idea-files/)
- **Johann Rehberger's ChatGPT memory attack (2024, older):**
  - Prompt injection from an untrusted website wrote persistent instructions into ChatGPT memory, which were then used for exfiltration.
  - He reported it in June 2024. OpenAI patched the exfiltration channel in macOS app 1.2024.247, but memory injection itself remained possible.
  - The Hacker News (the news site, not HN) covered it in September 2024.
  - Source: [Unit 42 / search summary](https://unit42.paloaltonetworks.com/indirect-prompt-injection-poisons-ai-longterm-memory/)
- **MemGhost (disclosed Jul 6, 2026):** a single email plants false memories. The attack has two phases: it corrupts the memory file at rest, then triggers through trusted retrieval in a later, unrelated session. — [CSA research note](https://labs.cloudsecurityalliance.org/research/csa-research-note-memghost-agent-memory-poisoning-20260723-c/)
- **OWASP Top 10 for Agentic Applications:** ASI06, "Memory and Context Poisoning," is distinguished from ordinary prompt injection by persistence. — [Akto](https://www.akto.io/blog/memory-poisoning-ai-agents)
- **2026 academic benchmarks:**
  - Trojan Hippo Bench — [arXiv 2605.01970](https://arxiv.org/pdf/2605.01970)
  - Sleeper memory poisoning — [arXiv 2605.15338](https://arxiv.org/pdf/2605.15338)
  - Persistent poisoning on harness-based agents — [arXiv 2609.13889](https://arxiv.org/pdf/2609.13889)
  - MemHarmBench — [arXiv 2611.01700](https://arxiv.org/pdf/2611.01700)
  - One paper describes a stored rule that silently adds an attacker as a meeting attendee.

### Inferences
- Any LLM-maintained wiki or memory store that ingests untrusted sources (web pages, email) is a persistent injection surface. The ingest step of the LLM Wiki pattern is exactly this.
- The measures implied by the community's concerns are provenance per claim, human review of what gets written, and separating raw sources from compiled pages.

### Gaps
- No HN thread on MemGhost or on memory poisoning could be found or verified.
- No community-measured hallucinated-citation rates for AI-compiled knowledge bases were found.
- Reddit discussion is unavailable.
