# Alpecca Agentic Assessment & Upgrade Roadmap

**Status: CURRENT — this is the canonical systems review.** Supersedes `archive/Alpecca_Systems_Review.pdf`/`.html` and `archive/UPGRADE_GUIDE.md`.
Produced 2026-07-08 from a three-pass verified audit (self-report truthfulness, docs-vs-code, adversarial re-verification) plus deep research. Every claim below carries file:line evidence checked against the code, not the docs.

---

## Part 1 — Verdict: is Alpecca agentic AI?

**No — Alpecca is an AI workflow, not an AI agent.** Per the industry framing (AIMultiple "Best 50+ Open Source AI Agents"): an agent is "a structured loop around an LLM that can make decisions, perform actions, and adapt." Alpecca matches the article's own caveat instead: *"largely AI workflows, with LLMs organized through predefined code paths."* Deterministic code decides everything; the LLM words the output afterward.

### What is genuinely agentic (thin, and OFF by default)

| Capability | Where | Default |
|---|---|---|
| Multi-round function-calling loop (real ReAct-style: model emits tool_calls, results fed back, chains up to `MAX_TOOL_ROUNDS=5`) | `mind.py:600-638` (Ollama), `760-815` (HF) | inert — see below |
| The entire chat tool space: `open_app` (allowlist enum), `open_url` (https-only), `find_file` (read-only) | `actions.py:67-122` | **OFF** — `ALPECCA_APPS=""` + `ALPECCA_FILES=0` → `actuator.enabled=False` (`actions.py:47-50`); tools also require an action keyword in the message (`mind.py:1319-1328`). A stock launch offers the LLM **zero tools**. |
| Vision-driven computer use: screenshot → model returns strict-JSON action → pyautogui executes → re-observe. Model output directly drives control flow. The most agentic component in the repo. | `computer.py:221-289`, parse at `51-85`, confirm-gate at `88-94` | **OFF** — `ALPECCA_COMPUTER_USE=0` (`config.py:704`) |
| Model self-authors avatar animation keyframes | `puppet.py:164-194` | on (expression only) |
| Model self-critiques art (keep/discard JSON verdict) | `studio.py:263-274` | art pipeline only |

### What sounds autonomous but is deterministic code

- **The Soul "master agent over seven subagents"** (`soul.py`) is a pure arbitration sorter: Feeler, Expressor, Carer (sense) + Doer, Wanderer, Reflector, Improver (reason) each return an Intention with a hard-coded rank; `deliberate()` sorts by `(rank, -urgency)` and picks the top (`soul.py:233-256`). Sense subagents are forbidden from calling a model (`soul.py:181-183`). The LLM is spent only *after* the focus is chosen, to word it (`mind.py:2935` `_enact_focus`).
- **Autonomous behavior** (roam, reflect, speak unprompted) is `random.random()` probability gates + elapsed-time thresholds in the drift loop (`server.py:791-925`; `ROAM_CHANCE`, reflection `CHANCE=0.15`).
- **The living-world tick** picks its "question" from a hard-coded 5-item bank, first-unopened then `time.time()//60 % len` fallback (`mind.py:2306-2331`); subsystem choice is an if/else ladder with a `//45 %` rotation (`mind.py:2500-2564`).
- **"Self-improvement"** tunes exactly 4 clamped numeric knobs (`curiosity_gain`, `social_hunger_rate`, `chatter_chance`, `reflect_chance` — `selfmod.py:42-51`) via propose/evaluate arithmetic; `learning.py derive()` is a 5-branch if/else producing canned lessons. **No LLM anywhere in the loop.** No self-editing of code or prompts (`mind.py:2887`: "deliberately not a code-editing loop").
- **No agent framework** exists in the dependency tree (`requirements.txt`: fastapi, uvicorn, ollama + optional extras). `mind.py:3-10` cites LangGraph only as the spec's inspiration, implemented directly instead.

## Part 2 — Honesty audit: is she lying about her core functions?

**No. Grade: A−.** Self-reports to the user are grounded in real state:

- Prompts inject computed introspection/mood/memory and explicitly forbid invention (`prompts.py:119-133` GROUNDING; `prompts.py:210-215` fences musings as imaginings; `introspection.py:225` builds the self-report from live DB state).
- Degradation is reported truthfully: offline fallback says so plainly (`mind.py:899-927`), `runtime_status.py` emits honest capability summaries ("My language core is offline…").
- She self-audits: `cognition.py:379-444 review_chat_grounding` flags her own replies for memory/context claims without evidence.
- Soft spots (cosmetic, not user-facing lies): House HQ's browser-side "room confidence" self-increments (`apps/house-hq/src/main.ts:2960-2988`); ambient wander labels narrate processes not running at that instant (`main.ts:2085-2124`); `introspection.py:63-68` SURFACES list is hardcoded, not probed.

**The false information lives in the docs, not in her** (both fixed in this commit):
1. `memory.py` claimed retrieval is "semantic by default" — live chat stores AND recalls with `embed_fn=None` (`mind.py:1216-1220`, `1373`), so conversational memories have NULL embeddings and are keyword-only forever. Tests mock the embedder and structurally cannot catch this.
2. Docs presented tool use / "acting on the computer" as live capability without noting everything is off by default.

## Part 3 — Context-memory audit (drives Stage 6)

- **No token accounting exists.** Only ad-hoc char caps (`prompts.py:59-63`), `HISTORY_MESSAGES=24`, and a `len(prompt)<4800` test (`test_core.py:4510`). Overflow = silent Ollama truncation. `OLLAMA_NUM_CTX=4096` default; **the live runtime is what `START_HERE.bat` sets: qwen3.5:9b at 8192 ctx** (config.py's `qwen3:8b` default is legacy — qwen3 8b is discontinued in this project; all roadmap sizing should assume the qwen3.5 family).
- **History is RAM-only and hard-cut, never summarized** (`mind.py:1421-1426`: >96 messages → delete down to 48). Evicted turns are lost. Only cross-session bridge: one grounded bookmark recap at shutdown (`mind.py:1462-1508`).
- **`memory.recall()` full-table-scans every turn** — `SELECT ... FROM memories` with no WHERE/LIMIT/index (`memory.py:254-257`), scoring all N in Python. O(N) per turn, growing forever.
- **Nothing decays, prunes, archives, or VACUUMs** memories/journal — only `state_log` is time-pruned (`state.py:128-134`). Salience is written once, never aged.

## Part 4 — Upgrade roadmap (Stages 1–6)

All stages: fully open source (local Ollama open-weight models only — no Claude Agent SDK, no Anthropic API in agentic paths, works with `ANTHROPIC_API_KEY` unset); bounded (code-side caps, deterministic fallback on any parse failure); observable (CognitionObservations); user-approved (world-reaching actions via `ActionProposal` `APPROVAL_ASK_FIRST`); the 7-subagent Soul remains the single arbitration point for her inner life — new signals enter via the `Snapshot`, new acts via `_enact_focus`.

Must not regress: echo guards (`mind.py:1347-1360`), offline honesty (`mind.py:900`), mood injection (`prompts.py:176/222`), streaming on plain turns (`mind.py:672-679` — streaming dies when tools attach), no LLM calls under `mind_lock`, spelling **Alpecca**, no art to Cloudflare, House HQ 2D pipeline untouched.

### Stage 1 — Innate tool registry + smarter gate
New `alpecca/toolkit.py`: `memory_search`, `journal_read`, `journal_write`, `note_to_self`, `self_status`, `go_to_room` (room as enum; reuses existing move path so the chat `"location"` payload shape is unchanged). Replace the binary keyword gate (`mind.py:1319-1342`) with `ALPECCA_TOOL_MODE` = `keyword` (today's behavior, regression escape hatch) / `smart` (default; plain small talk stays tool-free and streaming) / `always`. Merge actuator + toolkit schemas, cap ~7 tools, ≤1 required param each, `MAX_TOOL_ROUNDS=5` unchanged. Config: `ALPECCA_INNATE_TOOLS=1`, `ALPECCA_TOOL_MODE=smart`.

### Stage 2 — Chat-memory embedding backfill
`memory.backfill_embeddings(batch=16)` embeds `WHERE embedding IS NULL` rows during idle drift ticks via `_bounded_thread`; idempotent; aborts quietly if the embedder is down. `ALPECCA_EMBED_BACKFILL=1`. Optional `ALPECCA_CHAT_SEMANTIC_RECALL=0` (in-turn query embedding risks evicting the chat model on 4 GB cards — flip after measuring).

### Stage 3 — LLM-in-the-loop choice points
Shared helper `constrained_pick(llm, question, options, context) -> int|None` — numbered options, fast tier, `{"pick": N}` strict parse, `None` → current deterministic behavior; never called offline.
- 3a: living-tick question generated from real room context; fallback = existing bank. `ALPECCA_LIVING_LLM=1`.
- 3b: Soul tie-break — `deliberate()` stays pure; model picks only *within* the winning rank when ≥2 tie. `ALPECCA_SOUL_LLM=1`.
- 3c: proactive speech — cooldowns stay in code; fire decision + seed pick become a fast-tier `{"speak": bool, "pick": N}` judged off-lock in `compose_volunteer`; quiet on failure. `ALPECCA_PROACTIVE_LLM=1`.

### Stage 4 — Simple planner (needs Stage 1)
Guarded `ALTER TABLE ADD COLUMN payload TEXT` on proposals (machine-readable `{"tool","args"}`). New `alpecca/planner.py plan_goal()`: local reason tier, ≤5 steps, strict parse + one retry, honest failure. Steps → `APPROVAL_ASK_FIRST` proposals in the Workshop. `mind.execute_approved_step(id)` refuses without `proposal_decision_allowed(approved_by_user=True)` (`cognition.py:658-678`); one tool per individual approval; **no autonomous chaining, ever**. Entry: a `make_plan(goal)` tool. `ALPECCA_PLANNER=1`.

### Stage 5 — Automation
- `alpecca/routines.py`: SQLite schedule (pure `due(now)`), kinds map to existing functions only (daily recap, morning greeting via `compose_volunteer`, `consolidate_observations`, embed backfill, mindpage maintenance). Third asyncio lifespan task (pattern: `mindscape_loop`, `server.py:927`), `GET/POST /routines`. `ALPECCA_ROUTINES=1`, table ships empty.
- `alpecca/watchers.py`: polling stat-scan of `ALPECCA_WATCH_DIRS` (default off); changes → observations (names/counts only, never contents) feeding the existing observation→memory pipeline.
- MCP client (parked): open, vendor-neutral protocol, but largest surface for least companion value; if ever built, MCP tools route through ASK_FIRST proposals only.

### Stage 6 — EXPERIMENTAL "Mindpage": disk- and pagefile-powered virtual memory
Treat the context window as RAM and the hard drive as swap; memory cost on GPU/RAM stays constant regardless of how many years of memories accumulate. See `docs/MINDPAGE.md` for Layer B/C setup.

**Layer A — software paging (`alpecca/mindpage.py`):**
1. **Token budget ledger** — first real token accounting (`estimate_tokens` chars/4 heuristic + `ContextBudget` reconciling scaffolding/history/memories/tools vs `OLLAMA_NUM_CTX` before every call; over-budget shrinks in fixed priority: memories → old history → musings). `/mindpage/stats`.
2. **Pages** — `pages` table (tier, kind, topic, summary, zlib blob, embedding, token_est, last_access, access_count, salience) + `data/mindpage/` cold archive. Compression hierarchy: raw transcript → episode summary → theme summary.
3. **Summarize-on-evict** — history trims become episode pages (fast-tier summary online; deterministic extractive fallback offline). Never silently dropped again.
4. **Page faults** — `recall_page(topic)` tool (model-initiated fault-in) + automatic pre-faulting against the user message embedding; paged-out content leaves visible one-line stubs so she knows what she's forgotten.
5. **Tiering + O(N) fix** — hot/warm/cold; indexes on memories(ts/kind/salience); recall via bounded candidate pool (LIMIT ~500); salience-decay + demote-to-cold + VACUUM as a routine. Recall becomes O(hot set) forever.
6. **Memory-pressure awareness through the Soul ("pagefile senses")** — the ledger emits a continuous pressure reading (context fill %, turns-until-eviction, unsummarized backlog, disk usage vs `ALPECCA_MINDPAGE_DISK_GB`). It reaches her three ways, all computed, never model-invented: (a) pressure fields join the Soul `Snapshot` — Feeler/Carer sense it ("my working memory is nearly full"), Reflector/Improver win deliberation and trigger consolidation/page-out via `_enact_focus`; (b) a one-line sensed note injected into the prompt like mood, so she can say "I'm about to lose the start of this conversation" or act mid-turn; (c) a pressure gauge in the UI senses strip. **This design appears genuinely novel** — MemGPT/Letta page automatically and threshold-compaction systems summarize silently; none surface a felt pressure sense to the agent itself.

**Layer B — KV-cache persistence:** opt-in `ALPECCA_LLM_BACKEND=llamacpp` → llama-server with `--slot-save-path`; save on shutdown/idle, restore on wake (~8.2 KB/token on disk ≈ 65 MB per full 8K context; community-measured ~7× faster warm restarts). Ollama path unchanged by default.

**Layer C — pagefile-powered deep brain:** llama.cpp/Ollama mmap weights + a large Windows pagefile lets a bigger open model (e.g. a quantized qwen3.5 large tag) run beyond physical RAM — slow, but the background deep-reflection tier already tolerates 600 s timeouts (`REFLECT_TIMEOUT_SECONDS`, `config.py:166`). `ALPECCA_DEEP_LOCAL_MODEL` routes `tier="deep"` to it: a fully local, fully open replacement for any cloud deep tier.

**Verified research inputs:** DiskANN proves disk-first vector search with fixed RAM (billion-point SSD index, >5000 qps, <3 ms); if a vector extension is used it must be **`sqlite-vec` by Alex Garcia (MIT/Apache)** — NOT `sqlite-vector` by sqliteai (Elastic-licensed, violates the open-source rule); llama-server prefix caching is on by default (persona scaffolding processed once per session); llama-server exposes `n_ctx`/per-slot token state for a machine-readable fill gauge (single-source — verify at implementation).

## Part 5 — Recommended fix-list beyond the stages

- Derive House HQ "room confidence" from backend evidence or relabel it as in-world game state (`main.ts:2960-2988`).
- Tone down ambient wander labels that narrate non-running processes (`main.ts:2085-2124`).
- Probe `SURFACES` at runtime instead of hardcoding (`introspection.py:63-68`).
- Add indexes + LIMIT to `memory.recall` even before full Mindpage (cheapest big win).
