# State of the art (2025–2026) in agent memory and knowledge-base retrieval

Scope note: compiled 2026-11-27. Numbers are labelled **[vendor]** (self-reported by the system's maker), **[paper]** (peer-reviewed or arXiv by authors of the method, still self-interested), or **[independent]**. Items marked **[background, not re-verified this session]** come from well-known foundational papers recalled from prior knowledge; their canonical arXiv URLs are given but the numbers were not re-fetched here. Two vendor sites (mem0.ai, agentsystems.blog) were blocked by the session network, so their content is known only through search-engine summaries.

## 1. Agent memory systems and memory benchmarks (LongMemEval, LoCoMo, newer)

### Takeaway
Memory-system leaderboard numbers are not comparable across vendors: each uses different answer models, judges, retrieval budgets and LoCoMo scoring rules, and the public Zep/Mem0/Letta dispute shows scores for the same system swinging by 15–25 points depending on who configures it. The most durable lesson is that simple designs (a filesystem of text files with grep-like tools; a client-side file memory tool) score in the same range as specialised memory layers.

### Cited Findings
**Benchmarks (background)**
- LoCoMo: original paper's baselines were low, e.g. GPT-4-turbo 32.1% overall — [search summary of LoCoMo sources](https://agentsystems.blog/agent-memory-benchmark); paper: [LoCoMo, arXiv 2402.17753](https://arxiv.org/abs/2402.17753) [background]
- LongMemEval (500 questions; abilities: information extraction, multi-session reasoning, temporal reasoning, knowledge updates, abstention); the paper reported that commercial chat assistants and long-context LLMs show roughly a 30% accuracy drop on sustained-interaction memory — [LongMemEval, arXiv 2410.10813](https://arxiv.org/abs/2410.10813) [background, not re-verified this session]

**Zep / Graphiti**
- Zep is a memory service built on Graphiti, a temporally-aware knowledge-graph engine; it uses a bi-temporal model (one timeline for when events happened, a second for when data was ingested), enabling fact validity intervals and invalidation of superseded facts — [Zep paper, arXiv 2501.13956](https://arxiv.org/html/2501.13956) [paper]
- Zep claims Deep Memory Retrieval (DMR) 94.8% vs MemGPT 93.4%, and on LongMemEval "accuracy improvements of up to 18.5%" with ~90% lower response latency versus a full-context baseline — [arXiv 2501.13956](https://arxiv.org/abs/2501.13956v1); [Zep blog](https://blog.getzep.com/state-of-the-art-agent-memory/) [paper/vendor]. Caveat: DMR is near-saturated (both >93%), so it discriminates poorly.
- Older Zep LongMemEval figure: 71.2% with GPT-4o — cited in competitor comparisons [vendor] — [Mem0 comparison page](https://mem0.ai/library/agent-memory/zep-vs-mem0-which-ai-memory-layer-should-you-choose)
- A newer table credits Zep Cloud with LoCoMo 94.7% (1,459/1,540) and LongMemEval 90.2% (451/500) using GPT-5.4 as answerer and grader [vendor/claimed] — [search summary](https://mem0.ai/blog/state-of-ai-agent-memory-2026)

**Mem0**
- Mem0 paper (April 2025) claimed ~26% relative improvement over OpenAI memory on LoCoMo LLM-judge score, ~91% lower p95 latency and ~90% fewer tokens than full-context — [Mem0, arXiv 2504.19413](https://arxiv.org/abs/2504.19413) [paper; background, not re-verified this session]. Mem0's best graph variant was 68.5% on LoCoMo per Letta's citation of it — [Letta blog](https://www.letta.com/blog/benchmarking-ai-agent-memory)
- 2026 self-reported figures: LoCoMo 92.5, LongMemEval 94.4 at ~6,900 tokens/query; an earlier version of the same page said 91.6 / 93.4 [vendor] — [Mem0 State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- An independent test of Mem0's open-source edition reportedly scored 32.4% on LongMemEval, far below the managed platform's claim [independent, blog, small] — [DEV Community](https://dev.to/everest_an/-i-benchmarked-ai-agent-memory-in-2026-and-the-numbers-tell-a-different-story-than-the-marketing-2ae4)

**The Zep vs Mem0 dispute (2025)**
- Zep's "Lies, Damn Lies, & Statistics" post argued Mem0 misconfigured Zep in its LoCoMo runs; Zep corrected its own earlier calculation error and reported 75.14% ± 0.17 on LoCoMo, ~10% above Mem0 — [Zep blog](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/)
- Mem0's CTO responded that Zep's real score is 58.44% rather than 84%, alleging errors including inclusion of the adversarial category — [Zep blog / issue thread as summarised](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/); [Atlan comparison](https://atlan.com/know/zep-vs-mem0/)
- Zep's best single-retrieval LoCoMo configuration: 80.32% at 189 ms, up to 83% at higher cost [vendor] — [Mem0 comparison page (summary)](https://mem0.ai/blog/zep-vs-mem0-which-ai-memory-layer-should-you-choose)

**Letta / MemGPT**
- Letta (Aug 12, 2025): a plain Letta agent using a filesystem (files + search tools) scored 74.0% on LoCoMo with GPT-4o-mini, above Mem0's reported 68.5% graph variant; Letta attributes this to models being heavily post-trained on filesystem operations, and said Mem0 did not respond to requests on how its numbers were computed — [Letta, Benchmarking AI Agent Memory](https://www.letta.com/blog/benchmarking-ai-agent-memory) [vendor]. Not re-run against Mem0's newer pipeline — [Towards AI](https://pub.towardsai.net/mem0-vs-zep-vs-letta-a-folder-of-text-files-shouldnt-beat-the-61k-star-memory-layer-9d7e65c5799c)
- Sleep-time compute (Letta + UC Berkeley, Apr 2025): pre-computing over context "offline" reduces the test-time compute needed for equal accuracy by ~5x on Stateful GSM-Symbolic and Stateful AIME; it is most effective when queries are predictable from context; shipped as sleep-time agents in Letta 0.7.0 — [arXiv 2504.13171](https://arxiv.org/html/2504.13171v1); [Letta blog](https://letta.com/blog/sleep-time-compute) [paper]
- No standardized Letta LongMemEval result found — [search summary](https://agentsystems.blog/agent-memory-benchmark)

**Independent cross-system checks (small)**
- One independent comparison (single Gemini model as answerer and grader, 42 LongMemEval questions): Mem0 64.3%, Letta 70.0%, Graphiti 63.6% (on the 11 it finished); author judged Mem0 and Letta statistically tied — [search summary of DEV/independent post](https://dev.to/everest_an/-i-benchmarked-ai-agent-memory-in-2026-and-the-numbers-tell-a-different-story-than-the-marketing-2ae4)
- In a 2026 paper's own harness: Letta evidence + Qwen reader 66.23% on LoCoMo, frozen Zep evidence 59.29%; authors warn these are not universal rankings — [MemStrata, arXiv 2610.05343](https://arxiv.org/pdf/2610.05343) [paper]; the same paper claims 95% LongMemEval-500 and 90.91% LoCoMo-1540 "source-aware accuracy" with a local quantized 27B reader

**Anthropic memory tool**
- Sept 29, 2025: memory tool (file-based, entirely client-side via tool calls; developer controls storage) + context editing (clears stale tool calls/results near token limits). On an internal agentic-search eval, memory tool + context editing improved performance 39% over baseline; context editing alone 29%. In a 100-turn web-search eval, context editing let agents finish workflows that otherwise failed from context exhaustion while cutting token use 84% — [Anthropic, Managing context](https://www.anthropic.com/news/context-management) [vendor]. Some secondary coverage wrongly attaches the 84% to the combination — [The Decoder](https://the-decoder.com/?p=27732)

### Inferences
- A local, file/wiki-based store queried through tools is architecturally close to the Letta filesystem agent and Anthropic's memory tool — the two designs with the most credible "simple beats complex" evidence.
- Temporal validity (Zep's bi-temporal edges) addresses LongMemEval's knowledge-update and temporal-reasoning categories; a versioned wiki with page history and "as of" dates can provide similar signal if the retrieval tools expose it.
- Any self-built eval should fix answerer and judge models and report per-category scores, because cross-vendor numbers differ by tens of points from setup alone.

### Gaps
- Could not fetch mem0.ai or agentsystems.blog (blocked by session network); their full tables are known only via summaries.
- No verified 2025–26 numbers found for LangMem, A-MEM ([arXiv 2502.12110](https://arxiv.org/abs/2502.12110)), Cognee, MemOS ([arXiv 2507.03724](https://arxiv.org/abs/2507.03724)) or OpenAI memory beyond being baselines in others' papers.
- No information gathered on newer memory benchmarks (e.g., BEAM, MemoryAgentBench) in this session.

## 2. RAG vs long context

### Takeaway
Effective context is much shorter than advertised context: on tasks that need non-literal matching, most models lose half their short-context accuracy by 32K tokens, and degradation worsens with semantically similar distractors. Long context beats RAG only for strong frontier models at moderate lengths (≤~100K) on corpora that fit; retrieval remains needed for precision, cost, and large corpora.

### Cited Findings
- Lost in the Middle (2023): U-shaped accuracy — information at the start or end of context is used best, the middle worst — [arXiv 2307.03172](https://arxiv.org/abs/2307.03172) [background, not re-verified this session]
- RULER (2024): synthetic tasks beyond needle retrieval; only about half of models claiming 32K+ contexts maintain satisfactory performance at 32K — [arXiv 2404.06654](https://arxiv.org/abs/2404.06654) [background, not re-verified this session]
- NoLiMa (ICML 2025): needles with minimal lexical overlap with the question; at 32K, 11 of 13 models fall below 50% of their short-context score (v2 said 10 of 12); GPT-4o drops from 99.3% to 69.7%; noticeable drops already at 2K–8K; NoLiMa-Hard: Llama 3.3 70B (no CoT) falls to 8.9 at 32K. "Effective length" = longest context retaining ≥85% of base score — [arXiv 2502.05167](https://arxiv.org/html/2502.05167v3); [HF dataset card](https://huggingface.co/datasets/amodaresi/NoLiMa)
- Chroma "Context Rot" (July 14, 2025; Hong, Troynikov, Huber): models do not use context uniformly; reliability declines as input grows even on trivial tasks (e.g., repeating words); topically related distractors hurt more; degradation accelerates when question–answer semantic similarity is low; NIAH overstates long-context ability; code open-sourced — [Chroma Research](https://research.trychroma.com/context-rot). Caveat: Chroma sells a vector DB (conflict of interest noted by commentators) — [Hamel Husain notes](https://hamel.dev/notes/llm/rag/p6-context_rot.html)
- Databricks long-context RAG study (2,000+ experiments, 13–20 models, 4 RAG datasets; Nov 2024): Llama-3.1-405B degrades after 32K tokens, GPT-4-0125-preview after 64K; GPT-4o/4o-mini, o1, Claude 3.5 Sonnet, Claude 3 Opus, Gemini 1.5 Pro keep improving up to ~100K; failure modes include refusals (Claude 3.5 copyright refusals 3.7% at 16K → 49.5% at 64K) and summarising instead of answering — [Databricks blog](https://www.databricks.com/blog/long-context-rag-performance-llms); [arXiv 2411.03538](https://arxiv.org/html/2411.03538v1) [background-ish, late 2024]
- Follow-up: o1 models improved consistently up to 128K on Databricks' benchmark — [Databricks part 2](https://www.databricks.com/de/blog/long-context-rag-capabilities-openai-o1-and-google-gemini)
- Memory-system counterpoint: Zep reports ~90% lower latency vs full-context on LongMemEval while improving accuracy up to 18.5% — [arXiv 2501.13956](https://arxiv.org/abs/2501.13956v1) [paper]

### Inferences
- For an agent-facing wiki, returning a few short, highly relevant pages (not whole dumps) is supported by NoLiMa/Context Rot; keyword-only search is vulnerable precisely where NoLiMa bites (low lexical overlap between question and answer).

### Gaps
- No 2026 independent replication of Context Rot on the newest frontier models was gathered; LongBench v2 and Google's long-context-vs-RAG work were not covered in this session.

## 3. Retrieval techniques: hybrid, reranking, contextual retrieval, multilingual, agentic search, graph RAG

### Takeaway
The best-documented gains come from (a) adding context to chunks before indexing, (b) combining BM25 with dense retrieval, and (c) reranking — each measurably cuts retrieval failures. Graph-based RAG helps multi-hop/synthesis but costs 40–400x more tokens per query and loses to plain reranked vector RAG on simple fact retrieval. For code, agentic grep is competitive; semantic search adds a modest increment.

### Cited Findings
**Contextual Retrieval (Anthropic, Sept 2024)**
- Metric: top-20 retrieval failure rate (whether the golden chunk is in the top 20). Contextual Embeddings alone: 5.7% → 3.7% (−35%); Contextual Embeddings + Contextual BM25: 5.7% → 2.9% (−49%); plus Cohere reranking: −67% (≈1.9%) — [Anthropic Engineering](https://www.anthropic.com/engineering/contextual-retrieval); 1.9% figure via [secondary write-up](https://medium.com/almond-ai/responding-to-anthropics-contextual-retrieval-for-rag-apps-why-context-is-not-all-you-need-af503985aa55) [vendor]. Caveat: measures retrieval of a single golden chunk, not answer quality — [same critique](https://medium.com/almond-ai/responding-to-anthropics-contextual-retrieval-for-rag-apps-why-context-is-not-all-you-need-af503985aa55)

**Hybrid / multilingual (Portuguese)**
- 2026 Portuguese legal-retrieval study: RRF yields robust gains over BM25 and over part of the dense baselines, though not dominating reranking on every dataset; an 8B RRF configuration led Recall@10 — [ACL Anthology, STIL 2026](https://aclanthology.org/2026.stil-1.34.pdf)
- 2026 Portuguese clinical preprint (500 queries): dense-only retrieval failed on 22.2% of queries; BM25 and hybrid return statistically distinct sets (McNemar p<0.001), i.e., complementary — [DEV Community write-up](https://dev.to/nomad-link-id/two-retrieval-methods-are-better-than-one-evidence-from-500-clinical-queries-4g41) [preprint, single domain]
- MTEB-PT (2026): Portuguese benchmark from 14 MMTEB datasets, 17 models; global MTEB rank only moderately predicts Portuguese rank (Spearman ρ=0.75 over 55 models; one model ranks 3rd globally but 49th on Portuguese) — [MTEB-PT](https://huggingface.co/papers/2607.04071.md)
- Reported MMTEB Retrieval averages: bge-m3 54.6, multilingual-e5-large 53.7 (one 2026 paper's numbers, not the official leaderboard) — [arXiv 2607.25180](https://arxiv.org/pdf/2607.25180)
- BGE-M3's combined dense+sparse+multi-vector ("All") retrieval outperforms dense-only on MKQA Recall@20 — [mGTE paper, arXiv 2407.19669](https://arxiv.org/pdf/2407.19669); on Hindi-BEIR NDCG@10: BGE-M3 47.29, mE5 39.93, BM25 36.50 — [arXiv 2408.09437](https://arxiv.org/pdf/2408.09437) [2024 background]

**Agentic search vs vector search (code)**
- Cursor (Nov 2025): trained a dedicated embedding model on agent search traces; semantic search combined with grep gives 12.5% higher accuracy answering codebase questions than grep alone [vendor, methodology not public] — [Cursor blog](https://cursor.com/blog/semsearch); [Cursor docs](https://cursor.com/docs/agent/tools/search.md)
- Claude Code: early versions used a local vector DB; Boris Cherny reportedly said iterative agentic search was simpler and worked better, citing index staleness among reasons; no published benchmark — [AI Engineer talk summary](https://ai.engineer/talks/UM6sFg_jdlE-rag-is-dead-right-kuba-rogut); [labuladong explainer](https://labuladong.online/en/interview/agent/coding-agent-rag/)

**GraphRAG / LightRAG / HippoRAG**
- HippoRAG 2 (2025) reports consistent improvements over strong standard RAG on factual, multi-hop and associative tasks [paper] — [arXiv 2502.14802](https://arxiv.org/html/2502.14802)
- RAG vs GraphRAG systematic evaluation (Han et al., Feb 2025): GraphRAG trails vanilla RAG by 13.4% accuracy on Natural Questions and up to 16.6% on time-sensitive queries; graph methods help on multi-hop — [arXiv 2502.11371](https://arxiv.org/abs/2502.11371) (numbers via [secondary summary](https://vc.ru/ai/3041552-retrieval-augmented-generation-benchmark-graphrag))
- GraphRAG-Bench (ICLR 2026): basic RAG matches GraphRAG on simple fact retrieval (novel corpus: reranked vector RAG 60.92 vs MS-GraphRAG 49.29). Prompt tokens/query: vanilla RAG ~879, HippoRAG2 ~1,008, MS-GraphRAG local ~38,707, LightRAG ~100,832, MS-GraphRAG global ~331,375 — [arXiv 2506.05690](https://arxiv.org/pdf/2506.05690v3); cost analysis and LightRAG discrepancy (LightRAG paper claims <100 tokens for retrieval) — [beri.net](https://www.beri.net/article/graphrag-vs-vector-rag-indexing-query-cost-lightrag-lazygraphrag-2026)

### Inferences
- A BM25-only wiki forgoes the documented 35–49% failure reduction from contextual/dense signals; the cheapest compatible upgrade within SQLite is "contextual BM25" (prepending LLM-written page/section context to each indexed chunk), which Anthropic shows contributes on its own.
- Agent-driven iterative keyword search (multiple FTS5 queries with reformulation) partially compensates for lexical mismatch, per the Claude Code/Letta-filesystem experience, but Cursor's +12.5% suggests semantic search still adds value, especially for bilingual PT/EN content where query and page languages differ.
- HippoRAG 2-style graphs are the only graph approach with near-vanilla token cost; full GraphRAG/LightRAG costs are hard to justify for a personal wiki.

### Gaps
- No primary-source numbers gathered on ColBERT/late-interaction 2025 results, or on cross-lingual (PT query → EN doc) BM25 failure rates.

## 4. Compiled / "wiki" knowledge as a memory layer

### Takeaway
LLM-compiled wikis (Karpathy's LLM Wiki, DeepWiki, RAPTOR-style summary trees, STORM) are a popular 2026 pattern, but evidence on their factual accuracy is thin; the main quantitative support is RAPTOR's +20 points on QuALITY from hierarchical summaries, and commentators note they trade provenance and freshness for convenience.

### Cited Findings
- Karpathy "LLM Wiki" gist (April 2026): the LLM reads raw sources and maintains a persistent, interlinked set of markdown pages (compiled once, updated incrementally) between the user and sources; navigates via an index file of one-line summaries rather than embeddings; periodic "lint" pass checks for stale/contradictory entries — [Karpathy gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f); [VentureBeat](https://venturebeat.com/data/karpathy-shares-llm-knowledge-base-architecture-that-bypasses-rag-with-an)
- Commentary: spawned 30+ implementations; suits smaller personal corpora; very large corpora (~10M+ tokens) still need retrieval; RAG remains better when sources change often or exact provenance to raw text is required — [Analytics Vidhya](https://www.analyticsvidhya.com/blog/2026/04/llm-wiki-by-andrej-karpathy/); [Atlan](https://atlan.com/know/llm-wiki-vs-rag-knowledge-base/); [MindStudio](https://www.mindstudio.ai/blog/karpathy-llm-wiki-pattern-knowledge-base-without-rag)
- RAPTOR (ICLR 2024): recursively cluster chunks and summarise into a tree; with GPT-4, +20% absolute accuracy over prior best on QuALITY — [arXiv 2401.18059](https://arxiv.org/abs/2401.18059); [ICLR](https://iclr.cc/virtual/2024/poster/19034) [background]
- STORM (Stanford, 2024): generates Wikipedia-like articles with citations via perspective-guided question asking — [arXiv 2402.14207](https://arxiv.org/abs/2402.14207) [background, not re-verified this session; citation-accuracy numbers not retrieved]

### Inferences
- A cited, versioned wiki directly addresses the commentators' two main criticisms of LLM wikis (lost provenance, staleness), provided each claim keeps a pointer to the raw source and lint/verification runs on updates.

### Gaps
- No independent accuracy measurements found for DeepWiki/Devin wiki or Google Code Wiki; STORM/Co-STORM citation recall/precision numbers not retrieved this session.

## 5. Citation faithfulness and attribution evaluation

### Takeaway
Citations produced by LLMs are often unsupported: background studies found roughly half of generative-search sentences lack full citation support, and 2026 audits find 3–13% hallucinated URLs and only ~51% fully-correct references. NLI/LLM-based verification and multi-model agreement sharply raise accuracy.

### Cited Findings
- Liu et al. 2023 (verifiability of generative search engines): only ~51.5% of generated sentences fully supported by citations; ~74.5% of citations support their sentence — [arXiv 2304.09848](https://arxiv.org/abs/2304.09848) [background, not re-verified this session]
- ALCE (Gao et al., 2023): benchmark for generation with citations, measuring citation recall/precision with an NLI model (TRUE/T5-XXL); best models lacked complete citation support about half the time on ELI5 — [arXiv 2305.14627](https://arxiv.org/abs/2305.14627) [background, not re-verified this session]
- 2026 URL-citation study: 3–13% of citation URLs hallucinated, 5–18% non-resolving overall — [arXiv 2604.03173](https://arxiv.org/pdf/2604.03173)
- 2026 reference-accuracy study: overall field accuracy 83.6% but only 50.9% of entries fully correct; accuracy 27.7 points lower for recent vs popular papers — [arXiv 2604.03159](https://arxiv.org/html/2604.03159v1)
- 2026 cross-model audit (10 commercial LLMs): consensus of ≥3 models raises citation accuracy from 16.5% to 95.6%; within-model repetition raises it from 28.6% to 88.9% — [arXiv 2603.03299](https://arxiv.org/abs/2603.03299v1)
- Estimated 146,932 hallucinated citations in 2025 scholarly literature — [arXiv 2605.07723](https://arxiv.org/abs/2605.07723)

### Inferences
- A wiki whose citations point to stored sources (not free-text URLs) eliminates the fabricated-reference class; the remaining risk is "real source, unsupported claim", which ALCE-style NLI checks target.

### Gaps
- No 2025–26 ALCE leaderboard numbers or production "cite-then-verify" pipeline rates retrieved.

## 6. Evaluation practices for knowledge bases

### Takeaway
Practice converges on golden question sets with retrieval metrics (recall@k / failure rate@k) plus LLM-as-judge answer scoring; the memory-benchmark disputes show that judge choice, answer model and category inclusion must be fixed and reported.

### Cited Findings
- Anthropic's retrieval metric: top-20 retrieval failure rate of a golden chunk — [Anthropic](https://www.anthropic.com/engineering/contextual-retrieval)
- LoCoMo/LongMemEval scores vary by answerer/judge (e.g., Zep Cloud's 2026 figures use GPT-5.4 as both) and by adversarial-category inclusion — [Zep blog](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/); [Mem0 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- RAGAS: reference-free metrics (faithfulness, answer relevance, context precision/recall) using LLM judges — [arXiv 2309.15217](https://arxiv.org/abs/2309.15217) [background, not re-verified this session]
- NoLiMa-style "effective length" (≥85% of base score) is a useful threshold for deciding how much retrieved context to return — [NoLiMa dataset card](https://huggingface.co/datasets/amodaresi/NoLiMa)

### Inferences
- A minimal eval for the wiki: 50–200 golden PT/EN questions with known source pages; report recall@5/@20 for FTS5 alone vs with contextual prefixes, plus judge-scored answer accuracy and citation-support rate.

### Gaps
- No quantitative evidence gathered on LLM-as-judge agreement with humans for KB QA in 2025–26.
