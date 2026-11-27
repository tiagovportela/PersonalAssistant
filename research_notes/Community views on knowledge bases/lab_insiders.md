# Lab insiders (Anthropic, OpenAI, Google DeepMind, alumni) on knowledge bases, memory and context for agents, 2025-2026

Scope note: research done 2026-11-27 with a budget of about 15 tool calls. Pages read directly: Anthropic "Effective context engineering" (Sep 2025), Anthropic "Effective harnesses for long-running agents" (Nov 2025), and Karpathy's LLM Wiki gist (Apr 2026). Everything else comes from search-result summaries and is marked "(via summary)". Items marked "(background, from prior knowledge, not re-verified)" are older pieces I did not open in this session. The network blocked karpathy.bearblog.dev and blog.google, so I could not fetch the Karpathy blog or the Google "Release Notes" long-context page. Both hosts need to be allowed before anyone can check them.

## Anthropic: context engineering, memory tool, context editing, Skills, agentic search, long-running harnesses

### Takeaway
Anthropic's official line, from Sep 2025 to Nov 2025, is that context is a scarce "attention budget" that degrades as it grows ("context rot"). Its recommended pattern is a hybrid: put a small, curated file (CLAUDE.md) in context up front, then retrieve "just in time" with grep/glob and tools instead of embedding-based pre-retrieval. To get past one context window, it recommends compaction, structured notes kept outside the window (memory tool, progress files, git), and sub-agents. Its Nov 2025 harness post says compaction alone "isn't sufficient".

### Cited Findings
- **"Effective context engineering for AI agents"** (Anthropic Engineering, Sep 29, 2025; authors Prithvi Rajasekaran, Ethan Dixon, Carly Ryan, Jeremy Hadfield, Applied AI team) — [Anthropic](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
  - Context rot: as context grows, "the model's ability to accurately recall information from that context decreases."
  - LLMs have an "attention budget", and every new token "depletes this budget by some amount."
  - The post contrasts "embedding-based pre-inference time retrieval" with agents that load data at runtime, "Rather than pre-processing all relevant data up front."
  - Claude Code as the hybrid model: CLAUDE.md "files are naively dropped into context up front," while "glob and grep allow it to navigate its environment and retrieve files just-in-time."
  - Compaction "is the practice of taking a conversation nearing the context window limit", summarizing it and starting a new window with the summary.
  - Structured note-taking: "the agent regularly writes notes persisted to memory outside of the context window," and the notes are pulled back in later.
  - Sub-agents: "specialized sub-agents can handle focused tasks with clean context windows," and each returns "a condensed, distilled summary of its work."
  - Memory tool: a file-based tool in public beta that "makes it easier to store and consult information outside the context window."
- **Context editing + memory tool launch** (Anthropic news, Sep/Oct 2025). Context editing "automatically clears stale tool calls and results" near token limits. The memory tool is file-based storage outside the window. Anthropic's own reported results: memory tool plus context editing was +39% over baseline, and context editing alone was +29%. In a 100-turn web-search eval, token use fell 84% (via summary). Sources disagree on whether the 84% belongs to context editing alone or to the combination: [Anthropic news](https://www.anthropic.com/news/context-management); [Claude blog](https://claude.com/blog/context-management); the combination attribution is in [The Decoder](https://the-decoder.com/anthropic-claims-context-engineering-beats-prompt-engineering-when-managing-ai-agents/). A third-party critic notes the post publishes no baseline task set, model or methodology: [Towards AI](https://pub.towardsai.net/what-context-editing-actually-clears-and-what-it-costs-53f580a7e62e).
- **"Effective harnesses for long-running agents"** (Anthropic Engineering, Nov 26, 2025; Justin Young) — [Anthropic](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
  - "compaction isn't sufficient". Even a frontier model looping across context windows from a high-level prompt falls short of a production-quality app.
  - An initializer agent creates `init.sh`, "a claude-progress.txt file that keeps a log of what agents have done," and an initial git commit.
  - A JSON feature list (200+ items for a claude.ai clone, all starting as failing) where agents may only flip `passes`: "It is unacceptable to remove or edit tests because this could lead to missing or buggy functionality." JSON was chosen because the model is less likely to alter it inappropriately than Markdown.
  - Git as memory: it lets the model "revert bad code changes and recover working states of the code base." Git history plus the progress file orients a fresh context window.
  - Named failure modes: "Claude declares victory on the entire project too early"; sessions ending with undocumented state; features marked done without testing; setup overhead.
- **Agent Skills / progressive disclosure** ("Equipping agents for the real world with Agent Skills", Anthropic Engineering, Oct 16, 2025). The post calls progressive disclosure "the core design principle that makes Agent Skills flexible and scalable". At runtime only the name and description from the YAML frontmatter are in context, and the full SKILL.md and linked files load on demand (via summary; authors Barry Zhang, Keith Lazuka, Mahesh Murag per a third-party site, not confirmed on Anthropic's page) — [Anthropic](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills); [bdtechtalks](https://bdtechtalks.com/2025/10/20/anthropic-agent-skills/)
- **Boris Cherny (Claude Code creator) on agentic search vs RAG** (second-hand; I did not retrieve the original X reply or podcast). Reported wording: early Claude Code used "RAG + a local vector db" but "agentic search generally works better... It outperformed everything. By a lot." He reportedly said the evidence was "just 'vibes' – internal vibes," and cited indexing, staleness and security overhead: "at the cost of latency and tokens, you now have really awesome search without the security downsides." Sources place it variously in an X reply to Ethan Lipnik and in a Latent Space podcast appearance (May 2025) — [OfficeChai](https://officechai.com/ai/claude-researcher-explains-how-agentic-search-performed-better-than-rag-for-code-generation/); [Huxiu](https://www.huxiu.com/article/4871341.html); [smartscope summary](https://smartscope.blog/en/ai-development/practices/rag-debate-agentic-search-code-exploration/)
  - Counterpoint (practitioner commentary, not lab staff): agentic search costs more tokens and latency, does poorly on conceptual queries that need more than literal string matches, and Cursor still uses embeddings. The switch "does not establish that semantic retrieval is unsuitable for every coding agent" — [smartscope](https://smartscope.blog/en/ai-development/practices/rag-debate-agentic-search-code-exploration/); [AI Engineer talk listing, "RAG is dead, right?"](https://ai.engineer/talks/UM6sFg_jdlE-rag-is-dead-right-kuba-rogut)
- **Claude consumer memory** (Sep 2025). Simon Willison describes Claude's design as recalling "by only referring to your raw conversation history. There are no AI-generated summaries or compressed profiles—just real-time searches through your actual past chats." He says this "helps address my big complaint about ChatGPT memory" — [Simon Willison](https://simonwillison.net/2025/Sep/12/claude-memory/)
- Background, from prior knowledge, not re-verified: "Contextual Retrieval" (Anthropic, Sep 2024) adds chunk-specific context before embedding plus contextual BM25, and Anthropic reported large cuts in failed retrievals (about 49%, about 67% with reranking). It also advised that for knowledge bases under about 200k tokens you can skip RAG and put everything in the prompt with caching. "Building effective agents" (Erik Schluntz and Barry Zhang, Dec 2024) favors simple composable patterns over frameworks, with the "augmented LLM" (retrieval, tools, memory) as the building block — [Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval); [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)

### Inferences
- Anthropic has moved its retrieval advice from "better embeddings" (Contextual Retrieval, 2024) to "agent-driven, file-system-based just-in-time retrieval plus persistent notes" (2025). Embeddings are treated as optional, not foundational.
- Across these posts, the agent's long-term memory is plain files: CLAUDE.md, memory-tool directories, claude-progress.txt, JSON feature lists, git history, SKILL.md. This is the same design Karpathy's LLM Wiki takes up (see below).

### Gaps
- I did not retrieve Cherny's exact primary tweet or podcast wording. The quotes above are second-hand.
- I did not open the Skills post itself to confirm its authors or exact quotes.
- I found no Anthropic statement on memory poisoning specifically, beyond the general "context rot" framing.

## OpenAI: ChatGPT memory, Agents SDK, RAG vs long context

### Takeaway
OpenAI leadership pitches memory as lifelong personalization. Altman says ChatGPT "can now reference all your past conversations" and imagines a model with a "trillion tokens of context" holding your whole life. Willison (an outside practitioner) is the most-cited critic: he sees it as an opaque "dossier" that harms precise prompting.

### Cited Findings
- Sam Altman, Apr 10, 2025: "We have greatly improved memory in chatgpt -- it can now reference all your past conversations!" OpenAI framed the goal as "AI systems that get to know you over your life, and become extremely useful and personalized." ChatGPT saves both what users ask it to remember and "insights it gleans from your conversations" (via summary) — [Engadget](https://www.engadget.com/ai/chatgpt-can-now-remember-All-your-past-conversations-134642785.html); [Decrypt](https://decrypt.co/314380)
- Sam Altman at a Sequoia event, May 2025 (second-hand): his ideal is a small reasoning model with "a trillion tokens of context that you put your whole life into", and "your life just keeps appending to the context" — [TechCrunch](https://techcrunch.com/2025/05/15/sam-altmans-goal-for-chatgpt-to-remember-your-whole-life-is-both-exciting-and-disturbing)
- Simon Willison, May 21, 2025, "I really don't like ChatGPT's new memory dossier": the feature is "effectively collecting a dossier on our previous interactions, and applying that information to every future chat." Based on Johann Rehberger's investigation, ChatGPT maintains "a detailed summary of your previous conversations", which is injected into each new chat. Willison had guessed it was RAG, so this was a correction. His example: an image prompt for his dog in a pelican costume picked up an unwanted Half Moon Bay sign from memory — [Simon Willison](https://simonwillison.net/2025/May/21/chatgpt-new-memory/); [Axios](https://www.axios.com/2025/07/11/chatgpt-memory-update)
- An OpenAI page at openai.com/index/chatgpt-memory-dreaming showed up in search results, but I did not read it (see Gaps) — [OpenAI](https://openai.com/index/chatgpt-memory-dreaming)

### Inferences
- The two labs disagree on design. As described by Willison, OpenAI uses synthesized profile summaries injected automatically, while Claude searches raw history on demand. This is the main design split in consumer memory.

### Gaps
- I found nothing in this session on Joanne Jang's memory statements, Agents SDK session memory, deep research citation grounding, file search, or OpenAI staff statements on RAG vs long context. These need follow-up.
- I do not know the content of the "chatgpt-memory-dreaming" post. It may describe a background memory-consolidation feature.

## Google DeepMind: long context vs RAG, needle-in-a-haystack, NotebookLM

### Takeaway
DeepMind's long-context lead, Nikolay Savinov, presents long context and RAG as complements rather than rivals. He keeps RAG for enterprise-scale corpora and emphasizes context caching for cost (via summary).

### Cited Findings
- Nikolay Savinov (Google DeepMind research scientist), "Deep Dive into Long Context", Google AI: Release Notes podcast with Logan Kilpatrick, May 2, 2025. He reportedly says RAG won't be eliminated, that the two will be "synergistic", that RAG stays useful for large enterprise knowledge bases, and that long context should be combined with RAG once data exceeds a few million tokens. He also says context caching can cut input token costs "by up to a factor of four". The episode has a chapter on "Difficulty of attending to the whole context" (23:26) (all via summary; exact wording not verified) — [Google blog](https://blog.google/technology/google-deepmind/release-notes-podcast-long-context/); [episode listing](https://ppacc.player.fm/series/google-ai-release-notes/deep-dive-into-long-context)
- Context rot evidence from outside the labs: Chroma's "Context Rot" report (Kelly Hong, Anton Troynikov, Jeff Huber; Jul 14, 2025) found models including GPT-4.1, Claude 4, Gemini 2.5 and Qwen3 degrade as input grows, even on simple tasks. It separates "distractors" from irrelevant context, and found shuffled haystacks sometimes outperform coherent ones (via summary; the model count of 18 is unconfirmed) — [Chroma](https://research.trychroma.com/context-rot); [GitHub](https://github.com/chroma-core/context-rot)

### Inferences
- In practice Anthropic and DeepMind agree that a bigger window does not give perfect recall. Anthropic names it "context rot", and Savinov acknowledges the difficulty of attending to the whole context. Neither treats long context as a full replacement for retrieval.

### Gaps
- I found no 2025-2026 quotes from Jeff Dean or Oriol Vinyals on long context vs retrieval.
- I did not retrieve material from Steven Johnson or Raiza Martin on NotebookLM. Note that Karpathy's gist explicitly groups NotebookLM with RAG systems that rediscover knowledge on every query (see next section).
- I did not cover Gemini docs' 1M-2M token claims or Google's own needle-in-a-haystack caveats.

## Alumni and adjacent voices: Karpathy, Willison, LangChain, Weng and others

### Takeaway
Karpathy (ex-OpenAI) popularized "context engineering" in Jun 2025. In Apr 2026 he published the "LLM Wiki" pattern: the LLM compiles a persistent, interlinked markdown wiki (schema in CLAUDE.md/AGENTS.md) instead of RAG re-deriving knowledge on every query. LangChain offers the semantic/episodic/procedural memory taxonomy.

### Cited Findings
- Andrej Karpathy on X, Jun 25, 2025, endorsing "context engineering" over "prompt engineering": "the delicate art and science of filling the context window with just the right information for the next step." He presents it as one small piece of a larger software layer that orchestrates LLM calls — [Moda Labs (quotes tweet x.com/karpathy/status/1937902205765607626)](https://moda-labs.github.io/context-engineering/research/01-definitions-and-framings.html); [Simon Willison](https://simonwillison.net/2025/jun/27/context-engineering/); [The Decoder](https://the-decoder.com/shopify-ceo-and-ex-openai-researcher-agree-that-context-engineering-beats-prompt-engineering/)
- Karpathy, "LLM Wiki" gist (created Apr 4, 2026; read directly) — [GitHub gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
  - "the LLM incrementally builds and maintains a persistent wiki". Knowledge is "compiled once and then kept current, not re-derived on every query", making it "a persistent, compounding artifact."
  - RAG critique: with RAG "the LLM is rediscovering knowledge from scratch on every question". He names NotebookLM, ChatGPT file uploads and most RAG systems as working this way.
  - Three layers: raw sources ("your curated collection of source documents", which the LLM reads but never modifies); the wiki ("The LLM owns this layer entirely"); and a schema document "(e.g. CLAUDE.md for Claude Code or AGENTS.md for Codex)", which is "what makes the LLM a disciplined wiki maintainer rather than a generic chatbot."
  - Operations: ingest ("A single source might touch 10-15 wiki pages"); query ("good answers can be filed back into the wiki as new pages"); lint ("contradictions between pages, stale claims that newer sources have superseded").
  - index.md "works surprisingly well at moderate scale (~100 sources, ~hundreds of pages)" and "avoids the need for embedding-based RAG infrastructure". But "as the wiki grows you want proper search" (he suggests qmd). log.md is "an append-only record of what happened and when."
  - "Obsidian is the IDE; the LLM is the programmer; the wiki is the codebase." He says the idea is "related in spirit to Vannevar Bush's Memex (1945)."
  - Reception: 30+ implementations reported within weeks (via summary) — [Analytics Vidhya](https://www.analyticsvidhya.com/blog/2026/04/llm-wiki-by-andrej-karpathy/); [R&D World one-month review](https://www.rdworldonline.com/is-karpathys-viral-llm-wiki-helpful-mostly-yes-one-month-in/)
- LangChain LangMem (launch post, 2025). Semantic memory is facts and relationships that ground responses. Episodic memory is past interactions, often distilled into few-shot examples. Procedural memory is "internalized knowledge of how to perform tasks", implemented by agents rewriting their own prompts. The search did not confirm that Harrison Chase personally authored or is quoted in this framing — [LangChain blog](https://blog.langchain.com/langmem-sdk-launch); [LangMem concepts](https://langchain-ai.github.io/langmem/concepts/conceptual_guide)
- Simon Willison (practitioner, not lab staff) tracks memory under an "llm-memory" tag. He critiques ChatGPT's dossier (May 2025), praises Claude's raw-history search (Sep 2025), and has written on project-scoped memory (Aug 2025) — [tag page](https://simonwillison.net/tags/llm-memory/); [project memory](https://simonwillison.net/2025/Aug/22/project-memory/)
- Background, from prior knowledge, not re-verified: Lilian Weng's "LLM Powered Autonomous Agents" (Jun 2023) maps human memory onto agents: sensory memory as embeddings, short-term as in-context, long-term as an external vector store with MIPS retrieval. That taxonomy predates the 2025 shift toward file-based memory — [Lil'Log](https://lilianweng.github.io/posts/2023-06-23-agent/)

### Inferences
- There is broad agreement (Anthropic engineering posts, Karpathy, Willison) that the best agent memory is human-readable, file-based and curated (markdown plus a schema/CLAUDE.md file), with search added only as scale requires. Embedding-first RAG is the thing they push back on.
- On compilation vs on-demand retrieval, the two camps disagree. Karpathy wants knowledge pre-compiled into a wiki at ingest time. Cherny and Anthropic favor just-in-time retrieval from raw files at query time. Anthropic's notes, progress files and memory tool sit in between.
- Altman's "trillion-token life context" is the strongest long-context-maximalist vision. Anthropic's "attention budget" and Chroma's context rot findings argue against just appending everything.

### Gaps
- I found nothing for John Schulman, Jason Wei or Shunyu Yao on memory or knowledge bases in 2025-2026.
- Karpathy's "LLM OS" framing ("LLM is the CPU, context window is RAM") is from 2023 talks (background). I did not verify any 2025-2026 restatement.
- Drew Breunig's "How Long Contexts Fail" taxonomy (poisoning, distraction, confusion, clash) was only referenced second-hand. He is not a lab insider, but his taxonomy is widely cited.

## Failure modes named by these sources

### Takeaway
The failure modes named in these sources are context rot and attention dilution (Anthropic, Chroma, Savinov), distractors (Chroma), stale or contaminating memory (Willison on ChatGPT, Karpathy's lint for "stale claims"), premature victory and undocumented state in long runs (Anthropic harness post), and stale embedding indexes with security overhead (Cherny, second-hand).

### Cited Findings
- Recall falls as context grows ("context rot"), and every token "depletes" an attention budget — [Anthropic](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Distractors that are topically related to the question but do not answer it hurt more than irrelevant text — [Chroma](https://research.trychroma.com/context-rot)
- Stale tool results bloat context, which context editing automatically clears — [Anthropic news](https://www.anthropic.com/news/context-management)
- Memory contaminates unrelated tasks (the pelican costume picking up a Half Moon Bay sign), and auto-summarized profiles are opaque — [Simon Willison](https://simonwillison.net/2025/May/21/chatgpt-new-memory/)
- Wikis drift into contradictions and superseded claims, so they need periodic "lint" — [Karpathy gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- Long-running agents declare victory too early, leave state undocumented, and edit tests; JSON lists with restricted edits and git commits are the countermeasures — [Anthropic](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- Vector indexes go stale as code changes and carry privacy/security overhead (Cherny, second-hand) — [OfficeChai](https://officechai.com/ai/claude-researcher-explains-how-agentic-search-performed-better-than-rag-for-code-generation/)

### Inferences
- "Memory poisoning" in the security sense (prompt injection written into persistent memory) was not directly addressed by any lab insider source I found. Rehberger, an independent security researcher, is the person investigating ChatGPT memory, per Willison.

### Gaps
- I found no lab statements on hallucinated citations in deep research products (OpenAI deep research, Gemini Deep Research) in this session.
