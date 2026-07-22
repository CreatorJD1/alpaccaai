# Ubuntu Fallback Core Plan

Status: PREPARED - implementation gated after current stage closure and source audit

## Objective

Provide Alpecca with a persistent Ubuntu application VM: a phone-accessible
desktop where the creator can install apps for Alpecca, Alpecca can operate
approved applications, and a standby core can preserve approved communication
when the creator laptop is offline. It must never create two active Alpeccas.

The VM workspace and the Alpecca core have separate lifecycles. The desktop may
stay online continuously while only one local-or-cloud core owns Alpecca's mind
and communication channels.

## Non-Negotiable Invariant

Exactly one runtime may hold the **Alpecca leader lease**. Only the lease holder
may generate replies, connect the Discord bot, deliver notifications, accept
commitments, or write authoritative continuity state.

## Architecture

1. **Global lease authority**
   - A Cloudflare Durable Object or equivalently linearizable lease service is
     the single lease authority.
   - Every grant returns a monotonically increasing fencing epoch.
   - Writes, Discord sends, and vault snapshots include the epoch; stale epochs
     are rejected server-side.
2. **Local primary**
   - The laptop is preferred while its signed heartbeat is healthy.
   - It renews a short lease and publishes encrypted, bounded continuity
     checkpoints to the existing Mindscape Vault.
3. **Ubuntu standby**
   - A systemd-managed service runs in `standby` with model, desktop, and
     dependencies warm but all conversational egress disabled.
   - After a 90-second missed-primary grace period, it requests leadership,
     verifies the newest encrypted snapshot, and only then enables one portal.
4. **Permanent desktop**
   - Ubuntu uses a minimal Xfce session with noVNC or Apache Guacamole behind a
     private Cloudflare Tunnel and creator authentication. Raw VNC is never
     exposed publicly.
   - The desktop workspace and Alpecca service use separate Unix users and
     least-privilege systemd units.
   - A phone PWA opens the desktop stream, app catalog, files, task status, and
     Brain Garden from one stable HTTPS address.
5. **Application catalog**
   - Creator-approved APT and Flatpak sources supply desktop applications.
   - The creator can browse, install, update, disable, and remove applications
     from the phone UI. Every package operation shows source, version, disk
     impact, requested permissions, and an audit receipt.
   - Alpecca may request an app but cannot silently install packages or add a
     repository. Installation requires the creator's approval lease.
   - Installed apps are automatically registered as bounded computer-use tools
     and appear as plugin nodes in the Brain Garden.
6. **Remote workspace bridge**
   - While the laptop is primary, local Alpecca may operate the cloud desktop
     through a signed, expiring workspace lease without starting a cloud mind.
   - If Ubuntu later becomes leader, it reuses the same persistent desktop and
     installed apps after continuity restore.
7. **Failback**
   - Laptop recovery does not preempt the cloud leader automatically.
   - Creator approval initiates drain, final snapshot, lease release, epoch
     advance, and local resume in that order.

## Model And State

- The approved model family remains `qwen3.5:9b`; retired `qwen3:8b` paths are
  not reintroduced.
- The cloud model may use a compatible local Ollama/llama.cpp host or a bounded
  provider adapter, but identity, memory, policy, and audit state remain in the
  same encrypted continuity contract.
- Raw secrets never enter snapshots. Ubuntu receives deployment secrets from
  its host secret store.

## Required Safeguards

- Lease renewal interval: 10 seconds; lease duration: 35 seconds.
- Failover grace: at least 90 seconds plus successful vault verification.
- Fencing epoch checked by every side-effect adapter.
- Discord token is usable only by the current epoch holder.
- One active WebSocket/voice portal across both hosts.
- Audit events for lease request, grant, denial, loss, drain, restore, and
  every rejected stale write.
- Cloud runtime starts fail-closed if lease authority or vault verification is
  unavailable.
- Pagefile or swap changes remain creator-approved and are not part of
  automatic failover.

## Delivery Gates

1. Package the existing core for Ubuntu without changing local behavior.
2. Add lease client and server-side epoch enforcement while both runtimes stay
   non-conversational in test.
3. Prove split-brain rejection with network partitions and delayed packets.
4. Prove encrypted snapshot restore into a disposable database.
5. Run a creator-observed failover/failback drill with Discord and House HQ.
6. Enable production standby only after all stale-writer tests pass.

This plan provides continuity and a remote desktop. It does not claim that a
cloud VM prevents every outage; provider, network, and lease-authority failures
remain visible operational risks.
