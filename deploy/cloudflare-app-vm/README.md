# Cloudflare App VM Readiness Lane

This package evaluates whether a private, browser-accessible Linux desktop can
be deployed on Cloudflare without violating Alpecca's cost and continuity
constraints. It is intentionally **preflight-only**. It does not contain a
Wrangler deployment, a container image, or any command that creates cloud
resources.

The assessment checked on 2026-07-15 is blocked for two independent reasons:

1. Cloudflare Containers has no Free plan allocation. Containers require the
   Workers Paid plan (documented as USD 5/month) and can incur metered Container,
   Worker, Durable Object, R2, egress, and logging usage.
2. Cloudflare's Sandbox deployment workflow requires Docker to be running on
   the machine that invokes `wrangler deploy`. This Windows host has no Docker
   command or daemon.

The Sandbox/Containers platform appears technically capable of running Linux,
XFCE/noVNC, WebSockets, a single Durable Object coordinator, and R2-mounted or
R2-backed state. That technical capability does not satisfy the requested
zero-spend and no-local-Docker constraints.

## Run the preflight

```powershell
python deploy\cloudflare-app-vm\bin\cloudflare-desktop-preflight --dry-run
```

The command performs local inspection only and prints content-free JSON. It
never authenticates to Cloudflare, installs Wrangler, builds an image, starts
Alpecca, or deploys a resource. Optional `--account-evidence` and
`--runtime-evidence` files must be independently produced and reviewed; their
presence can satisfy evidence gaps but cannot erase the no-Free-tier blocker.

## Safety boundary

- One desktop lease holder at a time, coordinated by one named Durable Object.
- Monotonic fencing epoch on every new holder acquisition.
- Desktop-only process allowlist; CoreMind, models, Discord, and the autonomous
  game are prohibited.
- Creator ingress requires Cloudflare Access plus origin-side JWT signature,
  issuer, audience, expiry, and exact creator identity validation.
- noVNC is never exposed directly. VNC remains loopback-only in the container.
- R2 Standard is the persistence target; the container filesystem is ephemeral.
- Reviewed app catalog is read from `deploy/ubuntu-app-vm/config/` and remains
  deny-by-default. This lane cannot install packages.
- All proposed deployment commands remain absent until cost, entitlement,
  domain, Access, and build-host evidence passes a separate creator review.

See [docs/OFFICIAL_CAPABILITY_ASSESSMENT.md](docs/OFFICIAL_CAPABILITY_ASSESSMENT.md)
for sources and the exact deployment blockers.

## Tests

```powershell
python -m pytest -q deploy\cloudflare-app-vm\tests
```
