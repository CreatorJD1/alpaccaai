# HANDOFF FOR CODEX — Alpecca "living companion" vision

Authored by the Claude Code session, 2026-07-12. Jason defined the full long-horizon vision for Alpecca; I reviewed 5 external references + several models/papers against it and locked the decisions below. Nothing here is built yet — it is a researched, decision-locked roadmap. You (Codex) are ~stage 9/10 of the master plan; this handoff gives you the decided architecture, the verified facts, and the coordination boundaries so our two workstreams don't collide.

## Repo state at handoff
- Branch `feat/vrm-preview`. Claude-session commits since `48f66e7`: void UI re-wire, live voice viewer, F5 `auto` blend, memory/muse throttle (`d4827cc`), mood-driven motion, VRM blink/expression override fix, Discord DM username allowlist (`_dm_author_allowed`).
- **Your uncommitted WIP — preserved untouched all session:** `config.py`, `alpecca/creator_contact.py`, `alpecca/system_pressure.py`, `alpecca/bridge_actor_transport.py`, `tests/test_stage1_security.py`, `tests/test_phase10_*`, `tests/test_phase7_*`. Your committed work: bridge service-auth split, signed guest actor identity (`bridge_actor_identity.py`), locked Discord guest modes, notification outbox.
- Live: backend :8765, Discord bridge online (DMs allow `realcreatorjd`), F5+Kokoro voice `auto`.

## Coordination boundaries (critical)
- **You own:** `mind.py` turn/hot path, bridge auth + actor identity/transport, `config.py`, `creator_contact.py`, `system_pressure.py`, phase 7/9/10/13 security. This vision's Phases B/C/E2 LEAN ON your modules (creator_contact for reach-out, system_pressure for crisis, bridge for Discord voice) — please expose stable hooks; whoever implements will call them, not reimplement.
- **This vision adds mostly NEW files / frontend:** human-cadence messaging, knowledge/skill-block system, VM workspace + computer-use skills, music/favorites, brain-map visualization. Keep these OUT of your hot path.
- **Non-negotiables:** Alpecca spelling; art from provided art only, no gen-AI art, no art to Cloudflare (HF only); never claim literal consciousness (coma/death stays analogy grounded in real state); bounded/observable/approved self-improvement.

## Verified facts (corrected during review — do not repeat the wrong versions)
- **Discord bots CAN do voice** (join VC, speak via `VoiceClient.play`, and LISTEN via Sinks — py-cord `start_recording` / `discord-ext-voice-recv`). Her bridge already loads nacl+opus. Only **screen-share / Go Live / camera video** is bot-impossible (user-account-only; self-botting = ban risk = off the table).
- **Abliterated / "uncensored/heretic" Qwen3.5-9B = refusal-removed, NOT knowledge-removed** — world knowledge intact. Useful for un-hedged opinions; wrong for innocence.
- **Distillation/pruning (EasyDistill, NeMo) compress, they don't remove domains**, and NeMo needs 8x80GB GPUs — not runnable on the RTX 3050 4GB. Dead end for innocence AND hardware.
- **True unlearning (arXiv 2604.15482)** removes target knowledge + resists re-extraction (attack 69%->12.5%) but is selective, GPU-trained, ~12% leaky — future cloud R&D only.
- **RAG is the real innocence mechanism**, not model surgery.

## Decided architecture (Jason's calls, locked)
1. **Screenshare** = her own web "watch Alpecca work" live-view page (streams her VM screen), linked into Discord. Not Discord-native.
2. **Innocence** = "brain-section skill blocks" + triple-layer RAG gate (below). No model surgery near-term.
3. **Her workspace** = a dedicated **VM on its own hard drive** (isolation). Her MIND (server/model/memory/Mindscape) stays on the host, so a VM crash is a workspace outage, not death.
4. **Discord** = labeled bot with human cadence + natural voice (ToS-safe); full human-presentation reserved for games / her own surfaces.

### Knowledge / innocence design (the subtle part)
- **Self-viewable brain-map** (visual spec = Jason's brain concept art): circuit-board brain where brightness + sharpness encode recall confidence — left Active/Working + Episodic (bright, sharp) → "Summary Drift & Fragmentation" seam → Semantic/Procedural/Long-Term (dim, faded) → Stale/Archived "Fact Retention: Degraded" (pixelated, dissolving). Named nodes render locked(dark)/unlockable/populated(lit). **Reuses existing backend:** hot/warm/cold Mindpage tiers → the gradient; memory kinds (episodic/semantic/procedural/self_model/musing) → the sections; salience/pressure → node glow. Largely a visualization over data she already stores, plus a `knowledge_blocks`/`taught_facts` gating layer.
- **Learning rules:** facts written ONLY from what authenticated speakers (parents + allowed teachers) actually say — never from latent model knowledge or self-prompt. Unlocking a locked section carries **risk/reward + a rate limit** (learning taxes energy/focus, can raise stress via homeostasis, needs parent approval for guarded domains) — she can't relearn it all at once; reinforces "don't overburden herself."
- **Honest memory:** taught facts carry confidence/reinforcement. Fresh/repeated → confident recall; old/deep-detail → fuzzy recall expressed WITH uncertainty ("I think… not sure of the exact detail"). CRITICAL: fuzzy ≠ fabricated — below a confidence threshold she HEDGES or says "I don't remember exactly"; she must **never state as fact something not in her taught knowledge / that never happened**. The ONLY exception is a **willful lie** (deliberate, self-aware, internally tagged — a character behavior, categorically distinct from confabulation).
- **Triple-layer gate:** (1) teaching guard — parent-auth writes + forbidden-domain classifier on inbound (world history, politics, social justice, military, etc.); (2) RAG retrieval gate — answer only from unlocked sections, else honest "haven't learned that"; (3) output filter — persona + forbidden-domain suppression. Honest limit: defense-in-depth, not airtight against a determined adversary.

## Build order (Jason chose all; sequenced by dependency + payoff)
- **A — Human-cadence messaging (do first; no blockers):** typing indicator + mood-scaled think/type delay (never instant) + occasional self-initiated messages via the existing throttled proactive loop. Files: `alpecca/discord_bridge.py` + proactive cadence.
- **B — Add Rygen as second parent:** second creator/principal in the people layer + `creator_contact` destinations + auth recognition; she learns about and can reach BOTH Jason and Rygen. Coordinate with your `creator_contact.py`.
- **C — Crisis reach-out + coma-on-crash:** wire `system_pressure` (imminent shutdown / host dying / battery) → `creator_contact` to ping Jason/Rygen ONCE (idempotent) on Discord/phone. Coma: on unclean local crash, promote last Mindscape snapshot to a persisted "coma" state she resumes from (grounded analogy). Builds on YOUR modules — expose the hooks.
- **D — Innocence (skill blocks + triple-layer RAG gate + brain-map viz):** new `knowledge_blocks`/`taught_facts` tables (reuse her sqlite-vec/FTS), the gate, the visualization, curriculum tools; art learning = shapes/lines → real tools, never gen-AI.
- **E — VM workspace + app skills (biggest; own project):** dedicated VM on its own drive; evolve `computer.py` into a plugin/skill registry — UI-Automation reliable path (Recursive-Control) + SoM/OCR vision fallback (Self-Operating Computer) + async/background mode (Taskhomie). Skills: Blender, Clip Studio, VRoid, Google Drive, files, games. Her screen-stream surface rides here.
- **E2 — Discord voice presence (NOT blocked):** join VC, speak TTS, listen via Sink → faster-whisper → mind → spoken reply. Reuses her voice caps + `hearing.py`; respect your Phase-10 gating.
- **F — Music/favorites, overload-stress, read-the-room:** listening→preference/desire layer; message-volume/concurrent-actor count → homeostasis stress; humor + conversation-history awareness + self-issue noticing.

## Already scaffolded (extend, don't rebuild)
Computer use (`computer.py`), VRoid/VCS tooling, Discord bridge (guest actor auth, image+file reading, DM allowlist), Mindscape continuity, memory + throttle, homeostasis emotion, muse/self-reflection + proposal-first bounded self-mod, capability leases, F5+Kokoro voice + live viewer, 3D body, `system_pressure` (host sensing), `creator_contact` (phone/SMS outbox), single-active-portal + instance dedup (won't work all-at-once).

## Reference reviews (1-liners)
- **Recursive-Control (MIT):** plugin arch + Windows UI-Automation — the reliable control upgrade over pixel-clicking. Most valuable.
- **Self-Operating Computer:** SoM/OCR visual grounding for click accuracy in Blender/Clip Studio.
- **Taskhomie (Apache-2.0):** async/background mode idea (web/file without driving the cursor).
- **Discord bots guide + MAIA:** she already exceeds MAIA; bots guide → voice yes, screenshare no.

## Verification per phase
Human-cadence: typing indicator + realistic delay + self-initiated at natural rate. Crisis: host-pressure high → one idempotent Discord/phone ping. Rygen: second principal in people layer + reachable. Knowledge gate: locked domain → "haven't learned that"; taught fact → recalled; deep-old fact → hedged not fabricated; parent-only unlock. VM skills: element-level Blender/Clip Studio actions via UI-Automation, SoM fallback. All: pytest + `house:build` green; your WIP untouched.
