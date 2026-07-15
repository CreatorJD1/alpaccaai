# Alpecca Continuity Lease Worker

This package is Alpecca's cross-host singleton lease authority. It contains one
SQLite-backed Durable Object instance selected only with
`IDENTITY.getByName("identity")`. The Worker coordinates ownership; it does not
contain or run a model, CoreMind, private continuity data, credentials, or art.

The package is not deployed by repository tests or build scripts.

## Invariants

- At most one unexpired lease is active.
- Every new acquisition receives a fencing epoch strictly greater than all
  retained epochs.
- Renewal keeps the exact lease ID and epoch, and refreshes `issuedAt` and
  `expiresAt` with a lifetime no greater than 35 seconds, except when the
  cloud-failback rule below denies renewal.
- Release and observed expiry clear the active lease and published endpoint,
  then advance `highestFencingEpoch` immediately. The next acquisition advances
  it again.
- A fresh local heartbeat reserves the next acquisition for its `ownerNodeId`.
  It never revokes an active lease early, but it denies renewal to an active
  `cloud-standby:*` holder owned by another node. The cloud holder therefore
  fails closed at its existing expiry, after which the local owner can acquire
  a newer fence. A `local-primary:*` holder remains renewable.
- Endpoint publication requires the exact active
  `{holderNodeId, leaseId, fencingEpoch}` tuple and an HTTPS URL without
  credentials, query parameters, or a fragment.
- Every accepted or denied state transition produces a bounded JSON audit
  entry in the same SQLite Durable Object.

Downstream side-effect adapters must still reject requests unless the lease ID,
holder, epoch, and expiry match current authority state. An epoch by itself is
not sufficient authorization.

## Authentication

Every route, including health and status, requires:

```text
Authorization: Bearer <LEASE_AUTH_TOKEN>
```

`LEASE_AUTH_TOKEN` is declared as a required Wrangler secret. No value belongs
in `wrangler.jsonc`, source, logs, URLs, or this README. Configure it in the
target Cloudflare environment before a deliberate deployment. A missing secret
fails closed.

The authenticated role convention is the case-sensitive node ID prefix:

- `local-primary:<stable-node-id>` identifies the local primary.
- `cloud-standby:<stable-node-id>` identifies a cloud standby.

The bearer authenticates the caller, and the prefix supplies its role; requests
do not carry a separate role field. Provisioned clients must use the correct
prefix. In particular, the forced-failback renewal rule applies only to the
exact `cloud-standby:` prefix.

## API

All responses are JSON with `cache-control: no-store`. Mutation bodies must be
`application/json`, are limited to 4 KiB, reject unknown fields, and may include
an optional bounded `requestId` for audit correlation.

| Method | Path | Body or result |
| --- | --- | --- |
| `GET` | `/health` | Authenticated SQLite/authority health. |
| `GET` | `/v1/status` | Highest epoch, active lease, local heartbeat, endpoint, and recent audit. |
| `POST` | `/v1/heartbeat/local` | `{ownerNodeId, ttlSeconds?, requestId?}`; TTL defaults to 35 and must be 1-35. |
| `POST` | `/v1/lease/acquire` | `{holderNodeId, ttlSeconds?, requestId?}`. |
| `POST` | `/v1/lease/renew` | `{holderNodeId, leaseId, fencingEpoch, ttlSeconds?, requestId?}`; a fresh other-node local heartbeat denies `cloud-standby:*` renewal. |
| `POST` | `/v1/lease/release` | `{holderNodeId, leaseId, fencingEpoch, requestId?}`. |
| `PUT` | `/v1/endpoint` | `{holderNodeId, leaseId, fencingEpoch, endpoint, requestId?}`. |
| `GET` | `/v1/endpoint` | Current endpoint, or `null` when none is active. |
| `GET` | `/v1/audit?limit=50` | Newest JSON audit entries; limit is 1-100. |

A successful acquisition or renewal returns this lease view:

```json
{
  "leaseId": "2f8fcd67-829b-47f7-bc66-f30f70333b7f",
  "holderNodeId": "windows-primary",
  "fencingEpoch": 1,
  "issuedAt": "2026-07-15T20:00:00.000Z",
  "expiresAt": "2026-07-15T20:00:35.000Z",
  "ttlRemainingSeconds": 35
}
```

Contention and stale-fence failures return HTTP `409` with `decision: "denied"`
and a stable reason. Invalid input returns `400`, missing or invalid bearer
authentication returns `401`, and authority clock or epoch failures fail closed
with `503`.

## Local verification

From this directory:

```powershell
npm.cmd install
npm.cmd run check
npm.cmd run build:dry-run
```

`check` regenerates Wrangler bindings, runs strict TypeScript checks, and runs
the Worker integration tests under the Cloudflare Vitest pool. The tests cover
bearer enforcement, body bounds, 35-second TTL enforcement, local-primary
preference, concurrent contention, exact-fence renewal, expiry/release fencing,
cloud-to-local failback, endpoint publication, audit JSON, and Durable Object
eviction persistence.

`build:dry-run` invokes `wrangler deploy --dry-run`; it validates and bundles
locally without deploying.
