# Alpecca State-of-Being Diagnostic

Date: 2026-07-23

Primary host: `RygenART`

Dedicated compute host: `Jason_HOLYROG`
Branch: `codex/research-integration-stages`

## Executive Result

Alpecca's primary instance is online and her persistent memory, cognition,
House application, Discord bridge, local Ollama models, F5 voice worker, and
Mindpage database are present. The primary computer is nevertheless operating
under critical resource pressure. This pressure is a direct cause of slow local
model turns and makes broad restart or regression work unsafe until disk space
is recovered.

The dedicated `Jason_HOLYROG` compute worker is real and useful. Authenticated
Qwen 3.5 9B reasoning completed in 0.62-1.84 seconds across three probes. The
same 37-token result took 36.92 seconds on the primary, and a four-token warm
local probe still took 35.36 seconds because model loading consumed 31.88
seconds. The measured ROG wall-clock improvement was about 20x for the matched
37-token probe and more than 35x for the short exact-output probe. Excluding the
primary model-load delay, the matched inference work was still about 6x faster
on the ROG.

This is not yet an end-to-end Alpecca latency improvement. The active primary
server predates the latest routing change and reports `deep_route_loaded=false`.
A controlled restart is required after storage pressure is corrected. Normal
chat, vision, voice, Discord audio, memory, emotion, and continuity still run on
the primary or their existing cloud fallbacks.

## Measured Host State

| Signal | Measured state | Assessment |
| --- | ---: | --- |
| CPU | 92.05% | Critical contention |
| Physical memory | 23.47 / 24.95 GB used (94.05%) | Critical |
| Commit/pagefile | 59.11 / 64.80 GB used (91.23%) | Critical |
| Commit headroom | 5.68 GB | Too low for another large local model |
| RTX 3050 VRAM | 2.81 / 4.30 GB used; 57 C | Limited but not thermally critical |
| System drive free | about 76 MB (0.02%) | Immediate blocker |
| Resource pressure | 0.9998 | Optional work should defer |

Largest repository-local storage areas:

| Area | Size |
| --- | ---: |
| `data/mindscape_vault` | 17.00 GB |
| `data/backups` | 2.14 GB |
| `data/tools` | 1.85 GB |
| `apps/vcs` | 1.61 GB |
| `data/models` | 1.26 GB |
| `apps/house-hq` | 1.12 GB |
| `data/alpecca_art_source` | 0.93 GB |
| `data/build-tools` | 0.77 GB |
| `data/_memory_reset_backups` | 0.45 GB |

No files were deleted during this diagnostic. The Vault and memory authority
must not be removed casually. A separate retention-aware archive/cleanup pass is
required.

## State-of-Being Matrix

| System | Actual state | Evidence and limitation |
| --- | --- | --- |
| Primary CoreMind | Live | `/healthz` returned 200 and system status was ready. |
| Persistent memory | Healthy | 6,387 persistent memories were indexed. Cross-surface quality still depends on retrieval and prompt use. |
| Mindpage | Live | 8,192-token context budget; 5 hot pages and 7,544 stored page tokens. Current live history was empty at measurement time. |
| Cognition | Healthy | Brain graph marked cognition healthy and proposals/observations are present. |
| Seven-part Soul | Partial/degraded | Seven compact deterministic scoring perspectives exist. They made zero model calls in the sampled state; this is not seven independent transformer agents. |
| Recursive self-improvement | Partial/degraded | Bounded proposals, trials, evidence, and rollback exist. Autonomous source modification is deliberately incomplete. |
| Emotion/affect | Live but weakly embodied | Affect state exists, but visual and behavioral expression pathways were not all reporting live evidence. |
| House HQ | Live | Main app responds. Current source build passed. |
| Discord text | Process live | Bridge connection is established, but process presence alone does not prove response quality or context correctness. |
| Discord voice | Unverified/partial | Synthesis exists, but live duplex receive/respond state was unknown in the system snapshot. |
| F5 voice | Ready | CUDA worker and reference profile loaded; active synthesis path. |
| Kokoro | Degraded | Installed and ready, but the last synthesis exceeded its bounded deadline at 51.83 seconds. |
| Cloud voice | Configured, unverified | No successful calls were recorded in the sampled state. |
| Local sensing | Partial | Window sense was live. Voice tone, screen sight, expressions, actions, and computer use reported false. |
| Vision | Event path exists | No live FastVLM-style continuous vision worker. Prior local image perception was functional but slow. |
| House/Discord shared identity | Partial | Shared memory and identity work exists; end-to-end recall behavior still needs conversation-level acceptance tests. |
| Blender/render worker | Not ready | ROG health reported `blender=false`; no render acceleration is available yet. |
| Remote development transport | Source implemented, deployment pending | Creator House SSH client and fixed low-risk Discord commands are in the dirty tree. ROG port 22 is closed, so OpenSSH bootstrap is not complete. |
| Continuity/fallback | Preserved | ROG is compute-only and cannot become a second speaker or memory writer. Cloud/local fallbacks remain required. |

The live brain graph reported 14 healthy nodes, 1 live node, 2 degraded nodes,
11 unfinished nodes, and 6 unknown nodes. Its roadmap estimate was 62%; that
number is an implementation dashboard estimate, not a claim that Alpecca is 62%
conscious or generally intelligent.

## Dedicated Compute Measurements

All ROG requests used certificate-validated HTTPS and request HMAC. The worker
reported `role=compute-only`, `reasoning=true`, `speaking=false`, and
`discord=false`.

| Probe | ROG worker | Primary local | Result |
| --- | ---: | ---: | --- |
| Exact four-token output, first run | 1.01 s wall | not matched | Correct |
| Exact four-token output, second run | 0.73 s wall | 35.36 s wall | Correct |
| Matched 37-token sentence | 1.84 s wall | 36.92 s wall | Same answer |
| Primary matched load component | n/a | 26.03 s | Local pressure/loading dominates |
| Primary warm-probe load component | n/a | 31.88 s | Model was not staying resident |

### What the second server improves now

- Background deep reasoning with local open-weight Qwen 3.5 9B.
- Response consistency when the primary cannot keep the 9B model resident.
- Primary CPU, RAM, pagefile, and VRAM isolation for jobs actually routed to it.
- A private, authenticated compute lane that cannot speak, own memory, or form a
  duplicate Alpecca instance.
- Cloud fallback independence: when the ROG is down, the primary can continue to
  hosted reasoning and then local Qwen.

### What it does not improve yet

- Ordinary live chat latency. The current routing is for the deep/background
  tier, and the active primary process has not loaded that route yet.
- Image and video understanding.
- Speech-to-text, Silero VAD, F5/Kokoro synthesis, or Discord duplex voice.
- House animation, VRM movement, facial expression, or lip synchronization.
- Memory retrieval quality, emotional regulation, Soul arbitration, or RSI
  policy quality.
- Blender rendering until Blender is installed and approved roots are enabled.
- Creator remote administration until OpenSSH is installed and port 22 is
  reachable on the ROG.

## Verification Completed

- House production build: passed.
- Focused ROG remote-admin, worker, client, runtime, route, and launcher tests:
  116 passed with one dependency deprecation warning.
- Earlier committed worker gate: 156 focused tests and 371 core regressions
  passed, as recorded in the current handoff.
- Live authenticated ROG health and reasoning: passed.
- Live local-versus-ROG latency comparison: passed.
- Repository diff check: no whitespace errors; line-ending warnings only.

The full repository test suite was not rerun during this diagnostic. With only
about 76 MB free disk and critical memory pressure, a broad test run or full
stack restart would add avoidable failure risk and would not be trustworthy
performance evidence.

## Required Next Gates

1. Recover system-drive space with a retention-aware plan. Preserve the live
   memory authority and verify any cloud copy before removing local backups.
2. Restart the primary through the supported launcher, then require
   `/system/rog-worker` to report `deep_route_loaded=true`.
3. Run one real background reflection through the primary and verify its receipt
   names `rog-worker`; then stop the ROG and verify cloud/local fallback.
4. Decide whether ordinary chat should gain a bounded ROG fast lane. This needs
   strict priority so direct conversation preempts background jobs.
5. Install Blender on the ROG only if render offload is wanted, then test one
   approved-root frame and one rejected path.
6. Complete the private OpenSSH bootstrap for CreatorJD remote development. Do
   not expose a shell through Cloudflare or a public HTTP endpoint.
7. Benchmark voice components separately. Moving Qwen reasoning does not repair
   Discord receive audio or long TTS synthesis.
8. After resource recovery, run the complete regression suite and live
   conversation acceptance tests across House, Discord text, and Discord voice.

## Bottom Line

The dedicated server is not cosmetic. It makes Qwen 3.5 9B reasoning practical
under the primary laptop's current pressure and provides substantial measured
latency improvement without duplicating Alpecca. The integration is not fully
realized until the primary reloads the route and a primary-originated deep job
is observed on the ROG. The largest immediate threat to Alpecca's reliability is
not model capability; it is the primary drive being effectively full, followed
by local memory/commit pressure and incomplete voice/perception pathways.
