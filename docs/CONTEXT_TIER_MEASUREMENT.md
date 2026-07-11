# Context Tier Measurement

Last updated: **2026-07-10**

## Phase 6E-6F Checkpoint

Phase 6E adds bounded, evidence-only host-resource observation and context-tier
measurement. Phase 6F consumes only fresh advisory host pressure to defer
optional maintenance before a coordinator lease. It does not promote a model
tier or change the machine.

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

## One-Tier Harness

`scripts\measure_context_tier.py` is a JSON-only, one-tier measurement harness.
Its default invocation is a side-effect-free dry run at the 8,192-token tier:

```powershell
python scripts\measure_context_tier.py
```

A real request requires both flags below. `--execute` without an explicit
`--tier N` is rejected, and `--all` is intentionally unsupported.

```powershell
python scripts\measure_context_tier.py --execute --tier 16384
```

The only allowed tiers are `8192`, `16384`, `24576`, `32768`, and `49152`.
When execution is explicitly requested, the harness validates the approved local
`qwen3.5:9b` model and a direct loopback Ollama HTTP base URL, then makes at most
one non-streaming, non-thinking `/api/generate` request using a deterministic,
non-private synthetic needle prompt. It captures before, during, and after
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

No real model tier was run in this documentation checkpoint, and no tier was
promoted.

## Remaining Phase 6 Work

Phase 6 remains **PARTIAL**. The next separate integration is grounded
host-pressure-to-Soul state wiring with no automatic behavior. Neither it nor
Phase 6F authorizes a pagefile mutation; pagefile work remains blocked behind
the separate Phase 7 creator-approval gate.
