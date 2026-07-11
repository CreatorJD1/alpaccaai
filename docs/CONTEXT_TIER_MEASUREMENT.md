# Context Tier Measurement

Last updated: **2026-07-10**

## Phase 6E-6H Checkpoint

Phase 6E adds bounded, evidence-only host-resource observation and context-tier
measurement. Phase 6F consumes only fresh advisory host pressure to defer
optional maintenance before a coordinator lease. Phase 6H adds an execute-only,
read-only host preflight to the measurement harness. None of these steps
promotes a model tier or changes the machine.

`alpecca.host_resources.HostResourceSampler` is read-only. It samples available
host CPU, RAM, Windows commit, VRAM, disk, battery, and thermal signals and
returns explicit unknown or partial states when a probe is unavailable. It does
not read pagefile configuration, use the registry, request elevation, apply a
policy, alter system settings, or mutate the pagefile.

`GET /system/resources` returns the shared sampler snapshot. Its host-pressure
assessment and advisory are machine-level evidence, distinct from Mindpage's
per-request context pressure. Phase 6F consumes only fresh advisory host pressure
to defer optional maintenance before a coordinator lease. Chat and TTS behavior
are unchanged. Unknown or unavailable host data allows work. It performs no
automatic context reduction, pagefile action, configuration change, or system
action.

Phase 6G projects the cached shared host assessment into the Soul snapshot as
separate `host_pressure` evidence. This projection is assessment-only: raw host
telemetry and advisory data never reach the Soul snapshot. Unknown, invalid, or
unavailable data remains `null`. It is observational only, makes no LLM or
system call, and does not change seven-agent Soul deliberation, urgency, or
actions.

## One-Tier Harness

`scripts\measure_context_tier.py` is a JSON-only, one-tier measurement harness.
Its default invocation is a side-effect-free dry run at the 8,192-token tier;
it does not instantiate a host sampler or make an Ollama request:

```powershell
python scripts\measure_context_tier.py
```

A real request requires both flags below. `--execute` without an explicit
`--tier N` is rejected, and `--all` is intentionally unsupported.

```powershell
python scripts\measure_context_tier.py --execute --tier 16384
```

The only allowed tiers are `8192`, `16384`, `24576`, `32768`, and `49152`.
Only `--execute --tier N` captures the read-only before-sample and evaluates the
host preflight. Known high or critical host pressure, RAM/commit/disk headroom
below fixed thresholds, or a low unplugged battery block the run before any
Ollama HTTP request, with a request count of zero. The fixed execute thresholds
are:

- Host assessment: `high` or `critical` blocks.
- RAM headroom: at least 6 GiB and 20%.
- Commit headroom: at least 8 GiB and 20%.
- Disk headroom: at least 10 GiB and 10%.
- Battery: blocks only at or below 25% when not charging.

Unknown, invalid, or partial telemetry remains explicit preflight evidence; it
does not fabricate a block.

The harness validates the approved local `qwen3.5:9b` model and a direct
loopback Ollama HTTP base URL before preflight. When preflight permits execution,
it makes at most one non-streaming, non-thinking `/api/generate` request using a
deterministic, non-private synthetic needle prompt. It captures during and after
read-only host samples when available.

## Manual Gates And Non-Goals

Every report is evidence only and marks automatic promotion as false. A completed
measurement never persists a model-context selection, application configuration,
pagefile, registry, other system settings, or file change. It does not download
a model or run a tier sweep.

Any later context-tier decision requires manual review of the report, including
marker verification, request and Ollama timing, token telemetry, host samples,
and explicit unknowns. A later promotion remains a separately approved decision;
the harness cannot make it automatically.

On 2026-07-10, a real-machine execute invocation was blocked by critical host
pressure before any Ollama request. No real `qwen3.5:9b` inference or
context-tier measurement completed, and no tier was promoted.

## Remaining Phase 6 Work

Phase 6 remains **PARTIAL**. The next gated action is to clear resources and
re-run preflight, then separately authorize one 8,192 measurement. No direct
pagefile mutation is authorized in Phase 6; pagefile work remains blocked behind
the separate Phase 7 creator-approval gate.
