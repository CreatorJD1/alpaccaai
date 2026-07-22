# P14 Release-Soak Evidence Harness

`scripts/release_soak/` is an inert observer for a bounded subset of P14. It
reads content-free status captures, optionally probes the exact public
`GET /healthz` contract, observes the public mobile continuity lane, and emits
an honest JSON report.

It does not run tests or builds, import `server.py`, acquire the singleton lock,
inspect process command lines, start or stop processes, call model endpoints,
load credentials, deploy, publish, restore, sync, or send Discord traffic. The
network surface is limited to credential-free, proxy-disabled, redirect-free
requests: the configured `/healthz`, public discovery JSON, one selected public
endpoint `/healthz`, and public APK metadata. Public requests require HTTPS;
HTTP is accepted only for a loopback `/healthz`. The APK uses `HEAD` and its body
is never downloaded.

Every report keeps `phase.completion_claim` and
`assessment.p14_completion_claim` false. Even
`assessment.status = "observed_checks_passed"` means only that all nine checks
passed during the recorded window. It does not cover the remaining P14 canary,
failover, resource, database-growth, embodiment, secret-scan, deployment, asset,
PDF, or documentation gates.

## Checks

The harness records `pass`, `fail`, or `unknown` for:

1. Exactly-one-CoreMind evidence from a fresh external process inventory.
2. Exact Alpecca `/healthz` identity and HTTP health.
3. Chat-model availability from runtime status and/or Brain Graph evidence. A
   ready runtime with a structured reason-model field must report the approved
   `qwen3.5:9b` release model.
4. Compact Vault snapshot and recovery-archive freshness, including outbox bounds.
5. Exactly one Discord bridge from process inventory and/or Brain Graph evidence.
6. Public discovery schema, expiry, canonical selection, and current endpoint health.
7. Public APK `HEAD` content type, length bound, and ETag metadata.
8. Fresh structured test-result receipts.
9. Fresh structured build-result receipts.

Missing, stale, malformed, future-dated, secret-shaped, or conflicting evidence
does not pass. Singleton lock metadata is diagnostic only: reading an owner PID
does not prove that the OS lock is held or that no ungoverned process exists.

## Mobile Continuity

The CLI defaults to the reviewed credential-free objects:

- Discovery: `https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/alpecca-endpoint.json`
- APK: `https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/AlpeccaLauncher-v2.1.2.apk`

The published v2.1.2 artifact was separately verified as 1,211,336 bytes with
SHA-256
`163284BD14725F91BB3BEFBEF93D0D77DD1E9A34196FE691F923C4F25DE8C6EA`.
That digest is publication evidence, not a claim produced by this harness.

Discovery must contain exactly the version-1 public shape with `service`,
`version`, `updatedAt`, and one to four endpoint rows. Rows contain only `url`,
`kind`, `priority`, and `expiresAt`. Named endpoints use zero expiry. Quick
endpoints must be unexpired, later than `updatedAt`, and no more than 24 hours
after it. Candidate origins must be credential-free HTTPS with no query or
fragment. At most one selected endpoint is checked per observation using the
exact `{"service":"alpecca","version":1}` health identity.

Only a selected `.loca.lt` endpoint receives
`bypass-tunnel-reminder: alpecca-release-soak`. This is LocalTunnel's non-secret
warning-page bypass, not authorization. It is not sent to R2, Cloudflare, APK,
or other endpoint hosts. No request carries cookies, bearer values, passwords,
or other credentials.

The APK observation issues one `HEAD` request and requires status 200 without a
redirect, media type `application/vnd.android.package-archive`, a positive
content length no larger than 128 MiB, and a bounded ETag. This checks public
distribution metadata only; it does not download, install, execute, attest, or
publish the APK, and it does not independently recompute the published SHA-256.

## Run

Protected status endpoints must be captured through an already-approved trusted
path. Do not place a cookie, bearer value, token, or URL query parameter in this
harness. A status capture can wrap an endpoint response with an observation time:

```json
{
  "schema": "alpecca.release-soak.status-capture.v1",
  "kind": "runtime",
  "observed_at": "2026-07-15T20:00:00Z",
  "payload": {
    "models": {
      "chat_ready": true,
      "reason": "qwen3.5:9b"
    }
  }
}
```

Allowed capture kinds are `runtime`, `brain_graph`, and `vault`. Raw endpoint
JSON is also accepted; `observed_at` or Brain Graph `observedAt` is preferred.
Without either field, the file modification time is reported as the weaker time
basis. Each input is capped at 256 KiB and rejected if it contains secret-shaped
field names such as `token`, `password`, `authorization`, or `api_key`.

A separate approved, read-only inventory path may produce this strict process
status shape. The harness itself does not enumerate processes:

```json
{
  "schema": "alpecca.release-soak.process-status.v1",
  "observed_at": "2026-07-15T20:00:00Z",
  "coremind": {"count": 1, "pids": [1234]},
  "discord_bridge": {"count": 1, "pids": [5678]}
}
```

Example invocation:

```powershell
python -m scripts.release_soak `
  --process-status tmp\release-soak-process.json `
  --runtime-status tmp\release-soak-runtime.json `
  --brain-graph tmp\release-soak-brain-graph.json `
  --vault-status tmp\release-soak-vault.json `
  --test-result tmp\release-soak-core-tests.json `
  --build-result tmp\release-soak-house-build.json `
  --observations 60 `
  --interval-seconds 60 `
  --output tmp\release-soak-report.json
```

The reviewed mobile URLs are automatic CLI defaults. Use
`--no-mobile-discovery` or `--no-mobile-apk` to disable one, or
`--offline-evidence-only` to disable every network observation. Observation
count, interval, total duration, input count, input size, response size, request
count, artifact-size metadata, and network timeout all have hard upper bounds.
JSON goes to stdout unless `--output` is provided. Exit code `0` means all
harness checks passed, `1` means failed or unknown evidence, and `2` means
invalid command configuration or a report-write failure. No exit code is a P14
completion decision.

## Result Receipts

Tests and builds run outside this harness. Their bounded receipts contain no
command line or output text:

```json
{
  "schema": "alpecca.release-soak.result.v1",
  "kind": "test",
  "name": "core suite",
  "started_at": "2026-07-15T19:55:00Z",
  "finished_at": "2026-07-15T19:59:00Z",
  "exit_code": 0,
  "counts": {"passed": 359, "failed": 0, "skipped": 2}
}
```

For a build, set `kind` to `build`; `counts` may be empty or contain bounded
`failed`, `errors`, and `warnings` totals. Receipts are reported claims, not
cryptographic attestations. Invalid, stale, or empty test evidence stays
`unknown` or `fail`; it is never inferred successful from a file's existence.
