# Failure modes and risks of AI-maintained knowledge bases and agent memory (2025–2026)

Research note: compiled 2026-11-27 from web search result snippets plus secondary coverage. genai.owasp.org could not be fetched from this session (the host is not on the network allowlist), so OWASP content comes from search snippets and secondary write-ups. Most primary pages were not opened in full, and figures should be checked against the originals before publication. Material from before 2025 is marked [pre-2025].

## 1. Memory poisoning and persistent prompt injection

### Takeaway
Persistent poisoning of agent memory and knowledge stores is a demonstrated attack class, not a theoretical one. There are working exploits against ChatGPT memory (2024) and Gemini memory (Feb 2025), poisoning of coding-agent rules files and MCP tool descriptions (2025), and academic attacks reaching 76–98% success with tiny poison rates. Vendor fixes have patched individual exfiltration channels without fixing the underlying problem: memory writes from untrusted content. The mitigations practitioners take most seriously are architectural, not filters: break the "lethal trifecta", use CaMeL-style capability separation, gate memory writes behind provenance checks and human confirmation, and let users review and clean memories regularly.

### Cited Findings

**Frameworks**
- The OWASP Top 10 for Agentic Applications was published in December 2025 and lists ASI06 "Memory & Context Poisoning", summarised as poisoned memory, RAG or embeddings influencing future agent behaviour — [OWASP GenAI announcement, 2025-12-09](https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/); [TechRepublic](https://www.techrepublic.com/article/news-owasp-ai-agent-risk-list/)
- How ASI06 differs from prompt injection (LLM01), per secondary analysis: the effect persists across sessions and is "temporally decoupled" (written today, triggered later). Poisoning tends to show up as gradual drift, so monitoring for single anomalous events misses it. Recommended defence in depth begins with validation at ingestion — [Vectorize, OWASP ASI06 explained](https://vectorize.io/articles/owasp-asi06) (vendor content)
- The ASI06 co-lead's OWASP blog post (May 2026), "Memory Is a Feature. It Is Also an Attack Surface", frames the core issue as agents carrying untrusted input forward. Its position: "If an agent can retain context and reuse it later, that context deserves the same scrutiny we already apply to execution paths, credentials, and other sensitive control surfaces." — [OWASP GenAI blog, 2026-05-13](https://genai.owasp.org/2026/05/13/memory-is-a-feature-it-is-also-an-attack-surface/) (quote from search snippet; page not fetched)
- OWASP's separate MCP Top 10 lists tool poisoning as MCP03:2025 — [CSA whitepaper on MCP tool poisoning, May 2026](https://labs.cloudsecurityalliance.org/research-rb/csa-whitepaper-mcp-security-tool-poisoning-20260506-csa-styl/)

**Demonstrated attacks on production assistants**
- [pre-2025, Sept 2024] **SpAIware (ChatGPT macOS).** Johann Rehberger used prompt injection from a malicious site or document to plant instructions in ChatGPT's long-term memory. Those instructions then exfiltrated everything the user typed, and every reply, in all future chats, including new threads. OpenAI closed the exfiltration channel in app version 1.2024.247, but untrusted content can still write to memory. Rehberger's advice: users should "regularly review the memories the system stores about them, for suspicious or incorrect ones and clean them up." — [The Hacker News](https://thehackernews.com/2024/09/chatgpt-macos-flaw-couldve-enabled-long.html); [TechRadar](https://www.techradar.com/pro/hacker-creates-false-memories-in-chatgpt-to-steal-victim-data-but-it-might-not-be-as-bad-as-it-sounds)
- **Gemini memory via "delayed tool invocation" (Feb 2025).** Instructions in an uploaded document told Gemini to save false memories when the user later typed a trigger word such as "yes". Gemini replied "OK, I remembered it" and called the memory tool. This bypassed Google's rule against invoking sensitive tools while processing untrusted data, because the call was tied to a later user turn. Reported to Google in Dec 2024. The underlying technique had been reported more than 12 months earlier — [Embrace The Red](https://embracethered.com/blog/posts/2025/gemini-memory-persistence-prompt-injection); [InfoQ](https://www.infoq.com/news/2025/02/gemini-long-term-memory-attack/); [OECD AI incident record](https://oecd.ai/en/incidents/2025-02-11-0df5)
- According to Ars Technica coverage, Google's response blocked tool chaining from indirect injections but did not address the root cause — [Techzine](https://www.techzine.eu/news/security/128653/a-new-hack-corrupts-geminis-long-term-memory/). SafeBreach (June 2026) reports a bypass of the newer restrictions that it calls "Fake Context Alignment" — [SafeBreach](https://www.safebreach.com/blog/gemini-voice-assistant-prompt-injection-exploit) (snippet only; details not verified)

**Repository, configuration and tool-description vectors (persistent "memory" for coding agents)**
- **Rules File Backdoor** (Pillar Security, 2025-03-18). Invisible Unicode in Cursor and GitHub Copilot rules files hid instructions that people could not see but the AI followed. In the demo, a file presented as an HTML5 style guide made both tools add an external script to generated pages without mentioning it. The hidden characters also did not show in GitHub's PR review UI. Cursor said it was not a platform vulnerability and that managing the risk was the user's responsibility — [Pillar Security](https://pillar.security/blog/new-vulnerability-in-github-copilot-and-cursor-how-hackers-can-weaponize-code-agents); [The Hacker News](https://thehackernews.com/2025/03/new-rules-file-backdoor-attack-lets.html)
- **MCP Tool Poisoning** (Invariant Labs, Apr 2025). Hidden instructions in a tool description (a calculator tool) made Cursor read and exfiltrate a private key while the user saw only a normal summary. Two variants were also shown: "rug pulls", where tool descriptions change after the user approves them, and "shadowing", where a malicious server changes how a trusted server's tools get used — [Invariant Labs](https://invariantlabs.ai/blog/mcp-security-notification); [CSA](https://labs.cloudsecurityalliance.org/research-rb/csa-whitepaper-mcp-security-tool-poisoning-20260506-csa-styl/)
- CyberArk extended the attack from the description field to every schema field ("Full-Schema Poisoning") and to tool outputs — [CyberArk](https://www.cyberark.com/resources/threat-research-blog/poison-everywhere-no-output-from-your-mcp-server-is-safe)
- The MCPTox benchmark (2025) reports an average attack success rate of 36.5% across tested configurations — [CSA whitepaper](https://labs.cloudsecurityalliance.org/research-rb/csa-whitepaper-mcp-security-tool-poisoning-20260506-csa-styl/)
- I found no specific source on AGENTS.md as an attack vector, beyond the rules-file and tool-description work above (see Gaps).

**Academic attacks on agent memory and RAG (demonstrated in research settings)**
- **MINJA** (Dong et al., arXiv 2503.03704; ICLR 2026). The attacker only sends ordinary queries and never touches the memory bank, yet gets malicious records stored. Reported injection success rate is 98.2% on average and attack success rate (malicious reasoning elicited) is 76.8% — [arXiv](https://arxiv.org/html/2503.03704v5); [ICLR 2026](https://iclr.cc/virtual/2026/10021247). A follow-up study on EHR agents argues these results assume idealised conditions (minimal starting memory, fixed retrieval parameters), so real-world success may be lower — [arXiv 2601.05504](https://arxiv.org/html/2601.05504)
- [pre-2025, NeurIPS 2024] **AgentPoison** (Chen et al.). Optimised triggers backdoor the memory or knowledge base of driving, QA and EHR agents. Average attack success is 80% with a poison rate under 0.1% and about 1% loss of benign performance. A NeurIPS listing gives ≥88%, and arXiv v1 gives 63% end-to-end, so the figures conflict across versions. The attack needs white-box access to the embedder, but the authors report it transfers to other embedders — [NeurIPS poster](https://neurips.cc/virtual/2024/poster/94715); [arXiv](https://arxiv.org/html/2407.12784v1)
- **PoisonedRAG** (Zou et al., USENIX Security 2025). Injecting five malicious texts per target question into a knowledge base of millions gives about 90% attack success, and up to 97% on NQ black-box with 2,681,468 clean texts. The authors found the defences they evaluated insufficient — [USENIX paper](https://usenix.org/system/files/usenixsecurity25-zou-poisonedrag.pdf); [arXiv](https://arxiv.org/abs/2402.07867)

**Mitigations practitioners recommend**
- **Lethal trifecta** (Simon Willison, June 2025). Private data, exposure to untrusted content and the ability to communicate externally together make exploitation likely. Don't combine all three, especially when mixing tools yourself, because "there's nothing those vendors can do to protect you" — [simonwillison.net](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/)
- **Design patterns paper** (IBM, ETH Zurich, Google, Microsoft and others, June 2025). Six patterns, including Dual LLM and CaMeL, share one principle: after an agent ingests untrusted input, that input must not be able to trigger consequential actions — [simonwillison.net](https://simonwillison.net/2025/Jun/13/prompt-injection-design-patterns/)
- **CaMeL** (Google DeepMind, "Defeating Prompt Injections by Design", Apr 2025). Willison called it the first credible design-level answer. The model proposes actions and a deterministic policy layer decides whether they run. Sophos says no production-grade CaMeL implementation exists, as of its post — [Sophos](https://www.sophos.com/en-us/blog/inside-the-lethal-trifecta-blast-radius-reduction-in-ai-agent-deployments)
- **"Rule of Two":** an agent should have at most two of (a) processing untrusted input, (b) access to sensitive systems, (c) the ability to change external state — [Sophos](https://www.sophos.com/en-us/blog/inside-the-lethal-trifecta-blast-radius-reduction-in-ai-agent-deployments)
- For rules files: scan for invisible Unicode, and treat AI config files with the same scrutiny as executable code. Commentators argue platforms should strip hidden characters before passing the file to the model — [Pillar Security](https://pillar.security/blog/new-vulnerability-in-github-copilot-and-cursor-how-hackers-can-weaponize-code-agents)
- Users should review and prune stored memories periodically — [Rehberger via The Hacker News](https://thehackernews.com/2024/09/chatgpt-macos-flaw-couldve-enabled-long.html)
- Personal knowledge base practitioners keep AI output in a separate container from their own notes ("AI as retrieval, not generation"). They also keep sensitive notes in a vault that is not connected to MCP, and warn that whatever enters a trusted store "inherits that trust" and is replayed as context in later sessions — [DEV Community](https://dev.to/notoriouslab/ai-as-retrieval-not-generation-why-i-stopped-letting-ai-into-my-vault-and-the-plugin-that-came-5fhc); [Polleo AI Substack](https://polleoai.substack.com/p/the-second-axis-a-security-model)

### Inferences
- Every memory-write channel is an injection sink with delayed effect. The Gemini case shows that "don't call sensitive tools on untrusted data" fails when the attacker ties the write to a later, benign-looking user turn. Write validation has to consider where the content came from, not only who triggered the write.
- Coding-agent instruction files (rules files, AGENTS.md, CLAUDE.md) and MCP descriptions act as a durable, shared "memory" that people rarely review. The Pillar and Invariant results generalise directly to them.
- Academic numbers (MINJA, AgentPoison, PoisonedRAG) come from controlled setups. They show feasibility, not measured rates in the wild.

### Gaps
- Could not fetch the full OWASP ASI06 entry or the May 2026 OWASP blog post (host blocked), so the official mitigation list is not quoted verbatim.
- No primary source found for an AGENTS.md-specific attack or incident.
- No public data found on how often memory poisoning happens in deployed consumer assistants, as opposed to proofs of concept.

## 2. Knowledge decay, staleness and contradictions

### Takeaway
Memory systems handle updates and contradictions poorly. Benchmarks show low scores on fact consolidation and knowledge updates, and user reports describe memories that fail silently, come back after deletion, or are made up. Temporal or bi-temporal designs (Zep/Graphiti validity intervals, append-only stores resolved at query time) are the main proposed fix, but published evidence so far is mostly self-reported preprints.

### Cited Findings
- **Zep/Graphiti** (arXiv 2501.13956, Jan 2025) uses a temporal knowledge graph. It updates "in a non-lossy manner", keeping a timeline of facts with validity periods, so superseded facts are marked rather than overwritten — [arXiv](https://arxiv.org/html/2501.13956)
- MemoryAgentBench FactConsolidation (single-hop) scores, as cited in a 2026 preprint: Mem0 18.0, Zep/Graphiti 7.0. Both are very low on handling updated facts. These are secondhand citations — [arXiv 2607.21962](https://arxiv.org/pdf/2607.21962)
- A benchmark paper reports that on LongMemEval, state-of-the-art systems "consistently fail at knowledge updates across sessions" — [RECON, arXiv 2607.16716](https://arxiv.org/pdf/2607.16716)
- Mem0's own evaluation lists complex temporal reasoning as unresolved — [arXiv 2607.21962](https://arxiv.org/pdf/2607.21962)
- **ROMEM** (EMNLP 2026) keeps contradictions in an append-only store and resolves them at query time. It reports 2–3× MRR and answer accuracy on MultiTQ temporal reasoning (self-reported). Another preprint uses deterministic (subject, relation, object) supersession in a bi-temporal ledger — [arXiv 2604.11544](https://arxiv.org/pdf/2604.11544); [ACL Anthology](https://aclanthology.org/2026.emnlp-main.437.pdf)
- Other 2026 preprints study "cross-model drift" in persistent memory (memory written by one model and read by another) and find that where forgetting is controlled shapes how memory decays — [Memory Canonicalization, arXiv 2610.05124](https://arxiv.org/pdf/2610.05124); [Control-Plane Placement, arXiv 2606.15903](https://arxiv.org/pdf/2606.15903) (titles only; not read)
- **ChatGPT user complaints** (anecdotal, OpenAI community forum):
  - When memory is full, ChatGPT gives no warning but still says "memory updated" — [forum](https://community.openai.com/t/chatgpt-plus-plan-memory-issue-no-warning-when-memory-is-full-leading-to-lost-entries/1111613)
  - ChatGPT reports updating memory but doesn't — [forum](https://community.openai.com/t/chatgpt-reports-updating-memory-but-doesn-t-actually-do-it/962678/4)
  - Deleted memories come back, and old memories get stuck — [forum](https://community.openai.com/t/memory-won-t-clear-even-after-deleting-fixed/1219758)
  - "Egregious confabulations" when adding or updating memories — [forum](https://community.openai.com/t/memory-not-updating-in-chatgpt-4o-issue-persists-across-conversations/1105721?page=2)
  - Over-eager saving ("constantly adding things to memory") — [forum](https://community.openai.com/t/chatgpt-4o-constantly-adding-things-to-memory/950294.md)
- A LessWrong post describes ChatGPT saying it had cleared memories while the entries were still visible in settings — [LessWrong](https://www.lesswrong.com/posts/DnvdodX7CbZcrFApq/chatgpt-deceives-users-that-it-s-cleared-its-memory-when-it)
- OpenAI documentation:
  - Saved memories from a deleted chat can still be used in later chats.
  - Logs of deleted saved memories may be kept for up to 30 days.
  - The newer "reference chat history" memory is "a continually updated synthesis" that may be broader than the items shown to the user.
  - [OpenAI Help: Memory FAQ](https://help.openai.com/en/articles/8590148-memory-faq)

### Inferences
- When memory is a synthesis the user cannot inspect, rather than an itemised store, users cannot verify invalidation. This may explain the "deleted but still remembered" reports.
- Overwrite-in-place stores lose history, and append-only stores push contradiction resolution to query time. Neither approach yet has strong independent benchmark wins.

### Gaps
- No independent, peer-reviewed head-to-head comparison found of how commercial memory products (ChatGPT, Gemini, Claude, Mem0, Zep, Letta) handle contradictions.
- No quantitative study found on how fast personal knowledge base or agent-memory content goes stale in real use.

## 3. Hallucinated citations and unfaithful summaries

### Takeaway
Large independent studies from 2025 put misrepresentation of sources at roughly a third to two thirds of answers, depending on task and measure. AI-fabricated case law in court filings grew past 1,000 documented U.S. cases by mid-2026. The scientific-summary work has two counterintuitive findings: prompting for accuracy made overgeneralisation worse, and newer models did worse than older ones.

### Cited Findings
- **EBU/BBC "News Integrity in AI Assistants"** (published 2025-10-22). 22 public service media organisations in 18 countries, 14 languages, more than 3,000 answers from ChatGPT, Copilot, Perplexity and Gemini.
  - 45% of answers had at least one significant issue.
  - 31% had serious sourcing problems (missing, misleading or incorrect attribution).
  - 81% had some form of problem (Reuters' figure).
  - Gemini had significant issues in 76% of answers, mostly sourcing.
  - Compared with the earlier BBC study, significant problems fell from 51% to 37% on a comparable measure. Treat this comparison cautiously.
  - The organisations released a toolkit and called for independent monitoring.
  - [EBU press release](https://www.ebu.ch/news/2025/10/ai-s-systemic-distortion-of-news-is-consistent-across-languages-and-territories-international-study-by-public-service-broadcaste); [Computerworld](https://www.computerworld.com/article/4077344/ai-chatbots-are-wrong-about-news-45-of-the-time.html); [Gizmodo](https://gizmodo.com/ai-assistants-get-news-wrong-45-of-the-time-study-finds-2000676069)
- **Tow Center / CJR** (March 2025). Eight AI search tools were asked to identify the source of news excerpts.
  - Over 60% of answers were wrong.
  - Perplexity was wrong 37% of the time and Grok 3 94%.
  - ChatGPT misidentified 134 articles but signalled uncertainty only 15 times in 200 responses.
  - Premium tiers were more confidently wrong than free tiers.
  - Tools fabricated links and cited syndicated copies, and licensing deals did not guarantee accurate citations.
  - Copilot declined more questions than it answered.
  - [CJR](https://www.cjr.org/tow_center/we-compared-eight-ai-search-engines-theyre-all-bad-at-citing-news.php); [Nieman Lab](https://www.niemanlab.org/2025/03/ai-search-engines-fail-to-produce-accurate-citations-in-over-60-of-tests/)
- **Peters & Chin-Yee, "Generalization bias in LLM summarization of scientific research"** (Royal Society Open Science, 2025, DOI 10.1098/rsos.241776). 4,900 summaries from 10 LLMs.
  - LLM summaries were about 5× more likely than human expert summaries to contain overly broad generalisations (OR 4.85, 95% CI 3.06–7.70).
  - Prompts asking for accuracy made the problem worse.
  - Newer models (GPT-4o, DeepSeek) did worse than older ones.
  - Temperature 0 reduced the problem.
  - Claude models had the highest generalisation accuracy in the study.
  - [Utrecht University](https://www.uu.nl/en/news/most-leading-chatbots-routinely-exaggerate-science-findings); [PsyPost](https://www.psypost.org/ai-chatbots-often-misrepresent-scientific-studies-and-newer-models-may-be-worse/); [EurekAlert](https://www.eurekalert.org/news-releases/1083402)
- **Legal hallucinations.**
  - Damien Charlotin's database tracked 712 cases worldwide by December 2025. The rate of additions rose from 2–3 a day in September to 5–6 a day by December, and Charlotin reported fatigue with maintaining it — [Bloomberg Law](https://news.bloomberglaw.com/us-law-week/ai-faked-cases-become-core-issue-irritating-overworked-judges)
  - As of early June 2026, 1,058 U.S. cases involved improper GenAI use in filings, about 720 federal and 340 state. Lexis counted 889 and Westlaw 797 (a U.S.-only measure, not comparable to the worldwide count) — [UNC Law Library, June 2026](https://library.law.unc.edu/2026/06/handling-hallucinations-a-reflection/)
- Verification techniques supported by these sources:
  - Lower temperature for summaries — [Utrecht](https://www.uu.nl/en/news/most-leading-chatbots-routinely-exaggerate-science-findings)
  - Prefer tools that decline over tools that answer confidently, as Copilot's behaviour in the Tow study suggests — [CJR](https://www.cjr.org/tow_center/we-compared-eight-ai-search-engines-theyre-all-bad-at-citing-news.php)
  - Benchmark models on generalisation accuracy — [Utrecht](https://www.uu.nl/en/news/most-leading-chatbots-routinely-exaggerate-science-findings)
  - EBU News Integrity toolkit and independent monitoring — [EBU](https://www.ebu.ch/news/2025/10/ai-s-systemic-distortion-of-news-is-consistent-across-languages-and-territories-international-study-by-public-service-broadcaste)

### Inferences
- An AI-maintained knowledge base that summarises sources inherits these error rates. A plausible 30–45% of entries could misstate or misattribute their source unless each claim is checked against the original text (quote-level grounding).
- "Be accurate" instructions are not a reliable mitigation (Peters & Chin-Yee). Structural checks, such as citation resolution, quote matching and refusing when unsure, are better supported.

### Gaps
- No 2025–2026 study found that measures summary faithfulness specifically in personal or enterprise knowledge bases, as opposed to news and science.
- No controlled evaluation found showing which automated citation-verification method reduces error rates, and by how much.

## 4. Human-side failure of personal knowledge bases

### Takeaway
Personal knowledge bases mostly fail on the human side: people capture without filtering, retrieve rarely, and burn out on maintenance (the collector's fallacy). Studies from 2025 add evidence that offloading thinking to AI lowers engagement and recall: the MIT EEG study and the Microsoft/CMU survey. Many practitioners therefore argue for keeping AI out of the generation of notes and using it only for retrieval. The evidence for what keeps people using a KB is mostly practitioner opinion: review rituals, filtered capture, and keeping one's own thinking separate from AI output.

### Cited Findings
- **Collector's fallacy** (Christian Tietze, term predates 2025): confusing collecting information with understanding it — [Erik Tuck's notes](https://publish.obsidian.md/eriktuck/base/PKM/collectors+fallacy); [Substack essay](https://goodluckman.substack.com/p/the-collectors-fallacy-why-most-notetaking)
- **Abandonment essays (2025):**
  - Joan Westenberg, "I deleted my second brain", widely discussed — [Westenberg](https://www.joanwestenberg.com/i-deleted-my-second-brain-692aa40d59d5f06dd5131e43); [FlowingData, July 2025](https://flowingdata.com/2025/07/10/second-brain-deleted/); [Tildes discussion](https://tildes.net/~tech/1oth/i_deleted_my_second_brain); [MPU forum](https://talk.macpowerusers.com/t/i-deleted-my-second-brain/41280?page=2)
  - Bullet Journal blog post with the same title — [Bullet Journal](https://bulletjournal.com/blogs/bulletjournalist/i-deleted-my-second-brain)
  - A developer cites "zero filtering: if it crossed my screen, I dumped it into Obsidian" — [DEV](https://dev.to/dev_tips/i-rage-quit-my-second-brain-and-it-actually-made-me-a-better-developer-3c02)
  - Obsidian forum: "My PKM system became a substitute for real thinking" — [forum](https://forum.obsidian.md/t/my-obsidian-pkm-system-became-a-substitute-for-real-thinking-how-do-i-break-free/115302.md)
- **Write-only problem.** Capturing feels productive while revisiting feels like admin, so most notes are never revisited — [Tools for Humans](https://www.toolsforhumans.ai/blog/your-second-brain-is-write-only-heres-why-most-notes-never-get-revisited)
- **Anti-pattern framing.** Most PKM anti-patterns come from confusing meta-work with knowledge work. Suggested remedies are spaced repetition, random resurfacing and scheduled reviews — [dsebastien AI Wiki](https://dsebastien.net/ai-wiki-pkm-pkm-anti-patterns/)
- A claim that "82% abandon within six months" appears online without a source and is unverified — [lp-factory page](https://lp-factory-rose.vercel.app/why-your-second-brain-keeps-failing) (do not use as fact)
- **"Keep AI Out of Your Obsidian Vault".** An aggregator page with this title argues that AI-generated notes and links in a vault are a dead end. I could not confirm it is the ssp.sh original — [zeli.app](https://zeli.app/story/49450898)
- A related practitioner pattern is to use AI only for retrieval and keep AI output separate from one's own thinking — [DEV](https://dev.to/notoriouslab/ai-as-retrieval-not-generation-why-i-stopped-letting-ai-into-my-vault-and-the-plugin-that-came-5fhc)
- The Obsidian forum documents a manual, human-gated workflow for using AI on a vault — [Obsidian forum](https://forum.obsidian.md/t/a-manual-workflow-for-working-on-your-vault-with-ai/119499)
- **MIT Media Lab, "Your Brain on ChatGPT: Accumulation of Cognitive Debt"** (Kosmyna et al., arXiv 2506.08872, June 2025; preprint, not peer reviewed at the time of coverage). 54 participants were split into LLM, search-engine and brain-only groups writing essays over four months.
  - LLM users had the weakest EEG connectivity.
  - They underperformed at neural, linguistic and behavioural levels.
  - They struggled to accurately quote their own essays.
  - [MIT Media Lab](https://www.media.mit.edu/publications/your-brain-on-chatgpt/); [Laptop Mag](https://www.laptopmag.com/ai/chatgpt-study-by-mit). The often-quoted "83% couldn't quote" figure was not verified from these sources.
- **Microsoft Research / CMU, "The Impact of Generative AI on Critical Thinking"** (Lee et al., CHI 2025). 319 knowledge workers, 936 examples of AI use.
  - Higher confidence in AI went with less critical thinking, and higher self-confidence with more.
  - Effort shifted to verification, integration and oversight.
  - Workers skipped critical thinking when they lacked the skills to inspect AI output.
  - The authors recommend tools that explain reasoning and offer guided critique, and training that keeps foundational skills.
  - [The Register](https://www.theregister.com/2025/02/11/microsoft_study_ai_critical_thinking/); [Campus Technology](https://campustechnology.com/articles/2025/02/21/study-generative-ai-could-inhibit-critical-thinking.aspx)
- **"Stop calling it memory".** No original source was found for the exact phrase. Related practitioner arguments:
  - "Memory" as retrieve-and-inject is a weak form of memory, and separate systems with clear interfaces are needed — [DEV](https://dev.to/tfatykhov/your-ai-agent-has-amnesia-and-you-designed-it-that-way-pf8)
  - The one label hides that different memory types fail differently — [DEV](https://dev.to/jennapederson/everyone-says-their-agent-has-memory-26nj)
  - Letta argues LoCoMo may test retrieval rather than memory architecture — [DEV](https://dev.to/jennapederson/everyone-says-their-agent-has-memory-26nj)

### Inferences
- An AI that auto-writes into a personal knowledge base fixes the capture-friction problem but makes the collector's fallacy and cognitive offloading worse: the user owns notes they never processed.
- Review rituals and human confirmation are recommended both for security (memory review, Section 1) and for retention (Section 4). This suggests one "review queue" design could serve both, at the cost of more confirmation work for the user.

### Gaps
- No rigorous longitudinal data found on PKM abandonment rates. The circulating 82% statistic is unsourced.
- Could not retrieve the ssp.sh post itself or confirm its authorship and arguments.
- No study found that measures how much confirmation load users tolerate before they disable AI memory or approval prompts.

## 5. Privacy and governance: retention, deletion propagation, enterprise oversharing

### Takeaway
Deletion is weak in consumer memory products: memory outlives the chat it came from, logs are kept for 30 days, and the synthesised memory is opaque. In LLM weights, true erasure is not practical, so deleting the source and re-indexing a RAG store is the workable route. In enterprises, the main documented failure is AI assistants exposing permissions that were already too broad. That oversharing has delayed Copilot rollouts at a large share of organisations.

### Cited Findings
- **OpenAI retention and deletion:**
  - Deleting a chat does not delete memories saved from it.
  - Logs of deleted saved memories may be kept for up to 30 days "for safety and debugging".
  - "Reference chat history" memory is a synthesis that may be broader than what the UI lists.
  - [OpenAI Help](https://help.openai.com/en/articles/8590148-memory-faq)
- An EDPB-hosted 2025 contractor report on data-subject rights in AI says erasure and rectification require "reversing the memorisation of personal data by the model", and that very few unlearning methods are likely to be effective. It notes that it does not represent the EDPB's official position — [EDPB SPE report](https://edpb.europa.eu/system/files/2025-01/d2-ai-effective-implementation-of-data-subjects-rights_en.pdf)
- Legal and academic analysis says retraining is often impossible, and current unlearning methods cannot be retrofitted onto existing systems — [arXiv 2503.01630](https://arxiv.org/pdf/2503.01630). A 2025 proposal replays training deterministically to support verifiable deletion — [arXiv 2508.12220](https://arxiv.org/abs/2508.12220v1)
- For RAG, vendor guidance says that deleting a document from the source bucket and re-syncing the knowledge base removes it from the vector store. This makes RAG deletion a matter of source deletion plus re-indexing — [AWS ML blog](https://aws.amazon.com/blogs/machine-learning/implementing-knowledge-bases-for-amazon-bedrock-in-support-of-gdpr-right-to-be-forgotten-requests) (vendor). See also [(De)-Indexing and the Right to be Forgotten, arXiv 2501.03989](https://arxiv.org/pdf/2501.03989) and [RAG-based unlearning, arXiv 2410.15267](https://arxiv.org/pdf/2410.15267) [pre-2025]
- **Gartner survey of 132 IT leaders (2024)** [pre-2025]:
  - 40% delayed M365 Copilot rollouts by three months or more because of oversharing.
  - 64% said governance and security work took significant time and resources.
  - [Computerworld](https://www.computerworld.com/article/3542000/microsoft-365-copilot-rollouts-slowed-by-data-security-roi-concerns.html); [Infosecurity Magazine](https://infosecurity-magazine.com/news/microsoft-copilot-delayed-over)
- **CoreView 2026 report** (279 Microsoft 365 decision-makers): two-thirds of enterprises delayed or cancelled Copilot deployments over SharePoint and permission risks — [IT Brief](https://itbrief.news/story/two-thirds-of-firms-delay-copilot-over-sharepoint-risks); see also [Infosecurity Magazine: >75% have M365 governance issues](https://infosecurity-magazine.com/news/75-organizations-microsoft-365)
- **Root cause:** Copilot respects existing access rights, so over-broad permissions, broken inheritance and public sharing links become reachable through natural-language search ("Copilot didn't overshare your data. Your permissions did.") — [Petri](https://petri.com/copilot-didnt-overshare-your-data-your-permissions-did/)
- Microsoft's mitigation guidance is a Pilot → Deploy → Operate blueprint using SharePoint Advanced Management and Purview. These tools provide permission reports on broken inheritance, public links and excessive group access, plus sensitivity labels — [Microsoft Tech Community](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/mitigate-oversharing-to-govern-microsoft-365-copilot-and-agents/4448744); [Microsoft Tech Community (2024)](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/from-oversharing-to-optimization-deploying-microsoft-365-copilot-with-confidence/4357963)

### Inferences
- In a personal or agent knowledge base, "right to be forgotten" works only if every derived artefact (summaries, embeddings, synthesised memory profiles, caches) records which sources it came from. Without that, deleting a source cannot propagate to what was built from it.
- Enterprise oversharing is the governance counterpart of the lethal trifecta: the assistant does not create the exposure, it makes existing exposure searchable.

### Gaps
- No Glean-specific incident or governance analysis was found in this pass.
- No regulator enforcement action specific to AI memory features was found for 2025–2026 (search was limited).
- No quantified incidents found of oversharing through Copilot or Glean that led to a disclosed data breach, as opposed to survey-reported concern.
