# Phase 7 Pagefile Broker Integration Note

## Current Gate

The approved pagefile broker remains blocked. The latest documented real
`--execute --tier 8192` run on 2026-07-13 stopped in the read-only preflight at
`host_assessment_high`; it made no Ollama request and completed no 8K
measurement. See `docs/CONTEXT_TIER_MEASUREMENT.md`.

`alpecca.system_pressure.assess_pagefile_broker_prerequisite()` is preparatory
only. It can reject an incomplete or unsafe-shaped measurement report. A report
that passes its structural checks still returns `review_required`, never
approval or execution authority.

## Exact Prerequisite

Before broker implementation resumes, the documented report must show:

- exact local model `qwen3.5:9b` at tier `8192` in execute mode;
- `status: completed` after a passed, fully observed host preflight;
- exactly one allowed and attempted request with successful marker verification;
- collected before/during/after samples with no high, critical, or unknown
  assessment and no unresolved report unknowns; and
- no automatic promotion, file write, system-setting mutation, or pagefile
  mutation.

Passing these checks permits manual evidence review only.

## Deferred Broker Boundary

A later isolated implementation must require one authenticated, expiring,
one-use approval from the exact `CreatorJD` principal. It must require UAC,
perform a fresh pagefile/commit/system-disk readback immediately before any
write, permit exactly one 4,096 MiB maximum increase, refuse a result above
55,296 MiB, preserve at least 40 GiB projected free space on the system disk,
and verify the exact post-write readback.

No scheduler, autonomous caller, environment override, generic system-action
surface, or test may invoke a pagefile write. Integration into `server.py`,
`mind.py`, or UI remains a separate coordinator-owned review after the
prerequisite is documented.

## Focused Gate

```powershell
python -m pytest -q tests\test_phase7_system_pressure.py tests\test_phase7_pagefile_broker_preparation.py
```
