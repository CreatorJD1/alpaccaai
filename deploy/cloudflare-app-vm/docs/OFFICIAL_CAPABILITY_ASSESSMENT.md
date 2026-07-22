# Official Cloudflare Capability Assessment

Assessment date: 2026-07-15

## Decision

**Blocked under the requested constraints.** A private Linux GUI is technically
plausible on Sandbox/Containers, but it cannot currently be deployed from this
host with both zero spend and no local Docker.

## Evidence

- [Sandbox getting started](https://developers.cloudflare.com/sandbox/get-started/)
  says Sandbox deploy builds the container with Docker and explicitly requires
  Docker to be running locally for `wrangler deploy`.
- [Containers pricing](https://developers.cloudflare.com/containers/pricing/)
  lists `N/A` for the Free plan and included Container usage only with the USD 5
  per month Workers Paid plan. It also documents metered memory, CPU, disk,
  network, Workers, Durable Objects, and logs.
- [Sandbox pricing](https://developers.cloudflare.com/sandbox/platform/pricing/)
  says Sandbox inherits Containers pricing and also bills Workers, Durable
  Objects, and optional Workers Logs.
- [Container limits](https://developers.cloudflare.com/containers/platform-details/limits/)
  documents Linux instance sizes from 256 MiB through 12 GiB. A useful XFCE and
  browser workspace would require more than the smallest tier; no resource size
  is represented here as cost-free.
- [Sandbox lifecycle](https://developers.cloudflare.com/sandbox/concepts/sandboxes/)
  says a sleeping or restarted sandbox starts a fresh container. Local files
  are therefore not continuity storage.
- [R2 mounts](https://developers.cloudflare.com/sandbox/guides/mount-buckets/)
  and [backup/restore](https://developers.cloudflare.com/sandbox/guides/backup-restore/)
  provide the supported persistence paths. This design uses an R2 Standard
  prefix for desktop data and R2 backup handles for `/workspace` snapshots.
- [R2 pricing](https://developers.cloudflare.com/r2/pricing/) documents a free
  monthly Standard tier but metered storage and operations beyond it. R2's free
  tier does not make Containers free and cannot guarantee zero billing.
- [Durable Objects](https://developers.cloudflare.com/durable-objects/concepts/what-are-durable-objects/)
  provide globally unique coordination and strongly consistent transactional
  storage. The design uses one fixed object name for lease serialization.
- [Access JWT validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)
  says a Worker behind Access must still validate the JWT. The ingress contract
  therefore requires signature, issuer, audience, expiry, and exact creator
  identity checks at the Worker before any desktop proxying.
- [Worker custom domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/)
  require an active Cloudflare zone. This repository's handoff says that zone
  and named-hostname gate is not complete, so it remains an evidence blocker.

## Intended architecture after blockers are resolved

1. A creator-authenticated HTTPS Worker validates the Access JWT itself.
2. One fixed Durable Object ID owns the only desktop lease and monotonically
   increments the fencing epoch on a new acquisition.
3. The Durable Object routes to at most one Sandbox/Container instance with
   `max_instances: 1`; the container runs desktop components only.
4. noVNC is proxied after authentication. Raw VNC binds only to loopback.
5. R2 Standard is mounted at a narrow `/persistent` prefix. `/workspace`
   snapshots use Sandbox backup/restore, and backup handles are committed only
   while the exact desktop fence is current.
6. Readiness requires an external probe proving HTTPS auth denial/allow,
   noVNC WebSocket success, R2 round trip, one desktop process set, current
   lease fence, and zero prohibited processes.

This architecture is a plan, not deployed evidence. The preflight reports every
unproven item as blocked and never treats config-file presence as readiness.
