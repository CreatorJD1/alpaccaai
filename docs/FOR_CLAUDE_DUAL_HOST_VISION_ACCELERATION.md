# Claude Dual-Host Vision Acceleration Work Order

Updated: 2026-07-24

This work order is for two concurrent Claude sessions. The RygenART session
owns source integration. The `Jason_HOLYROG` session owns model installation,
GPU measurement, and worker deployment. Do not let either machine start a
second CoreMind, Discord bridge, memory writer, tunnel, or continuity lease.

## Goal and acceptance gate

Make one Discord or House image available to Alpecca as a verified description
in **under 30 seconds end to end** while preserving her existing local
`qwen3.5:9b` path and `gemma4:cloud` fallback.

Promotion requires all of the following on `Jason_HOLYROG`:

- the model is resident before the timed run;
- five consecutive requests complete in 30 seconds or less, with p95 no more
  than 30 seconds;
- the same Discord screenshot is used for every candidate;
- the answer identifies the Discord surface, reads the central visible
  message correctly, and does not invent absent people, text, or actions;
- an authenticated RygenART-to-HolyROG request also completes within 30
  seconds, not only a direct Ollama request;
- worker failure still falls back to RygenART local vision without dropping
  the image turn.

Cold model loading is measured separately. Production must preload the chosen
model and keep it resident so cold load is not hidden inside a user turn.

## Candidate order

1. `qwen3-vl:4b` is the first candidate. The official Ollama artifact is about
   3.3 GB, accepts text and images, and the upstream Qwen model is Apache-2.0.
   It is the best fit for the existing Ollama/Qwen runtime and the RTX 4060
   Laptop GPU's 8 GB VRAM.
2. `qwen3-vl:2b` is the latency fallback. The official Ollama artifact is about
   1.9 GB. Promote it only if it passes the same screenshot-reading accuracy
   gate; speed alone is insufficient.
3. `gemma3:4b` is a comparison only. Its official Ollama artifact is about
   3.3 GB and supports images, but it uses Gemma terms rather than Apache-2.0.
   Do not select it unless it materially beats Qwen on measured latency and
   quality and its terms are recorded.

Do not install FastVLM, Moonshine, Graphiti, Mem0, Letta, or another agent
framework for this stage. They do not solve this bounded screenshot path with
less integration work than the existing Ollama worker.

## Session A: Claude on RygenART

Start from the shared branch and preserve unrelated dirty files:

```powershell
cd C:\Users\Jason\Documents\GitHub\alpaccaai
git fetch origin
git switch codex/research-integration-stages
git pull --ff-only
```

Implement a fourth bounded compute-worker operation, `POST /v1/vision`:

- add request/response schemas to `alpecca/rog_worker_server.py` and
  `alpecca/rog_worker_client.py`;
- reuse the existing HMAC, nonce replay fence, TLS identity, request ID, job
  semaphore, and fail-closed validation;
- accept only PNG, JPEG, or WebP pixels; reject redirects, URLs, SVG, HTML,
  archives, and oversized or malformed payloads;
- resize/re-encode on RygenART before transfer, cap the long edge at 1600 px,
  cap encoded pixels at 2 MiB, and never persist raw image bytes;
- make the worker model an allowlisted setting named
  `ALPECCA_ROG_WORKER_VISION_MODEL`, defaulting to `qwen3-vl:4b` only after the
  benchmark passes;
- cap output at 512 tokens and disable thinking for this low-latency path;
- return model, elapsed milliseconds, request ID, and description; never
  return chain-of-thought;
- add `vision_ready` and `vision_model` to authenticated health without
  changing the worker's compute-only, non-speaking role;
- route `alpecca/vision.py` through the private authenticated worker first
  when explicitly enabled, then the existing RygenART local path, then the
  existing consent-governed cloud path;
- label receipts `private-holyrog`, not `local`, because pixels crossed the
  private tailnet even though they did not enter a public provider;
- preserve attachment provenance and the rule that an unverified description
  cannot become a claimed visual fact.

Required tests:

```powershell
python -m pytest -q tests\test_rog_worker_server.py tests\test_rog_worker_client.py tests\test_phase9_local_inference.py tests\test_discord_media.py
```

Add tests for malformed base64, MIME/magic mismatch, decompression limits,
request size, model allowlist, timeout, replay, response size, unavailable
worker fallback, processing-location receipt, and successful private-worker
description. Do not change Discord or House behavior beyond choosing this
faster inference backend.

## Session B: Claude on Jason_HOLYROG through TeamViewer

Keep this machine compute-only. Do not copy the TLS private key or worker
secret into chat, source, logs, or benchmark output.

1. Pull the same branch without changing source-owned files.
2. Confirm the GPU is the RTX 4060 Laptop GPU with 8 GB and confirm Ollama is
   current enough for Qwen3-VL.
3. Install and benchmark candidates in this order:

```powershell
ollama pull qwen3-vl:4b
ollama pull qwen3-vl:2b
```

Install `gemma3:4b` only if both Qwen candidates fail the latency or accuracy
gate. Do not remove `qwen3.5:9b`; it remains Alpecca's reasoning model.

4. Copy the test screenshot privately to
   `D:\AlpeccaResearch\vision-bench\discord-test.png`. Do not commit it.
5. For each model, record one cold run and five resident warm runs using the
   exact prompt below. Set `keep_alive` to at least 30 minutes and cap output
   at 512 tokens.

```text
Describe this image for Alpecca. Identify the app or surface, read the central
visible message as accurately as possible, distinguish observed details from
uncertainty, and do not infer actions or identities that are not visible.
Return a concise factual description only.
```

6. Save machine-local results to
   `D:\AlpeccaResearch\vision-bench\results.json` with model digest, Ollama
   version, GPU name, cold seconds, five warm seconds, peak VRAM, answer text,
   and pass/fail reasons. Do not commit machine paths or private image content.
7. When Session A's endpoint lands, pull it, add the selected model to the
   worker allowlist, restart only `Alpecca ROG Compute Server`, and run the
   authenticated end-to-end benchmark from RygenART.

## Promotion decision

Promote the smallest model that passes both latency and accuracy. Expected
order is `qwen3-vl:4b`, then `qwen3-vl:2b`. If neither passes, keep the current
120-second local path operational and report the failed measurements; do not
declare the under-30-second target complete.

After promotion, update `PROJECT_CONTEXT.md` and `HANDOFF.md` with measured
numbers, exact model digest, test counts, fallback evidence, and whether the
result was direct-Ollama or authenticated end to end.

