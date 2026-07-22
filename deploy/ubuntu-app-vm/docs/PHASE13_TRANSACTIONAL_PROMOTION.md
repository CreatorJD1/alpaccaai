# Phase 13 Transactional Promotion Lane

`alpecca_ubuntu_vm/transactional_promotion.py` is a pure, dry-run state
machine for evaluating a standby promotion transaction. It has no CLI,
executor, persistence adapter, system probe, network client, service manager,
or process launcher.

The evaluator accepts caller-supplied state and one event, then returns a
deterministic decision, a proposed next state, and a content-free receipt. It
never writes the proposed state. Every result explicitly reports that no VM,
desktop, tunnel, Discord bridge, model server, game, or CoreMind was started.

## State progression

The only successful forward path is:

```text
passive-standby
  -> restore-staged
  -> restore-verified
  -> lease-acquired
  -> desktop-standby-eligible
  -> coremind-promotion-eligible
  -> released
```

`coremind-promotion-eligible` is not a running or speaking state. The state
machine stops before activation. `rollback-release` can release the exact held
lease from any of the three post-acquisition phases and retains the highest
fence epoch so an older lease cannot become valid again.

## Transition contracts

1. `stage-passive-restore` requires an authenticated passive-vault archive, a
   vault that reports no active CoreMind, an isolated staging target, a
   verified restore receipt, and a CreatorJD approval.
2. `verify-restored-snapshot` requires exact snapshot identity and digest,
   authenticated manifest evidence, complete files, successful SQLite
   integrity evidence, and an inactive staging runtime.
3. `acquire-continuity-lease` accepts only an authenticated grant from a
   caller-asserted available, linearizable authority. The authority must
   report no prior active lease, no speaking CoreMind, no conflicting owner,
   and an unambiguous exact grant. The granted epoch must be strictly greater
   than both the state high-water mark and the authority high-water mark.
4. `qualify-desktop-standby` requires the exact unexpired lease, verified
   loopback-only desktop definitions, prepared creator ingress, and evidence
   that the desktop runtime remains stopped. It emits eligibility only.
5. `qualify-coremind-promotion` requires exactly one active lease, held by the
   candidate at the exact lease ID and epoch, plus verified former-primary
   fencing, zero known speaking CoreMinds, no conflicting owner identities,
   and a desktop that remains in standby.
6. `rollback-release` requires authenticated, unambiguous authority evidence
   that the exact lease is no longer active and that no speaking CoreMind
   remains. Its receipt binds the snapshot digest, lease ID, lease epoch,
   authority release ID, event digest, and previous-state digest.

Malformed input, out-of-order transitions, clock rollback, expired leases,
stale or unknown epochs, duplicate event IDs, reused approval IDs, ambiguous
ownership, or competing speakers fail closed without changing the proposed
state.

## Approval binding

Every creator-approved transition requires a purpose-specific, externally
verified, one-use approval for `CreatorJD`. The approval is bound to:

- the exact transition purpose;
- the exact `sha256:` snapshot digest;
- the exact lease epoch;
- its bounded validity interval; and
- its unique approval ID.

The restore approval uses the snapshot's source epoch. Lease acquisition,
desktop standby, and CoreMind promotion approvals use the newly granted lease
epoch. Integrity verification needs no creator approval because it cannot
activate anything. Rollback/release is deliberately not approval-gated so a
fail-safe demotion cannot be blocked; it still requires exact authenticated
release evidence.

Approval and event consumption exist only in the returned proposed state.
Production replay protection therefore still requires an external monotonic,
rollback-resistant store.

## Single-speaker invariant

This policy can designate at most one promotion candidate: the holder of the
single exact active lease. Promotion is rejected unless the external evidence
reports zero existing speaking CoreMinds, the former primary is fenced and
verified stopped, and ownership is unambiguous. The evaluator itself starts no
speaker, so every state it emits has zero speakers started by this lane.

This is an eligibility invariant, not evidence that live runtime enforcement
already exists. A production speech gate must revalidate the same lease and
fence before any CoreMind output and stop output immediately on lease loss.

## Exact external live gates remaining

Phase 13 remains blocked until all of these external gates have live evidence:

1. **Passive-vault restore executor:** restore a real encrypted vault archive
   into a non-live isolated target and emit an authenticated immutable receipt.
2. **Independent integrity collector:** verify the real snapshot digest,
   archive authentication, manifest, file completeness, SQLite integrity, and
   staging-runtime inactivity, then protect that evidence against tampering.
3. **Creator approval authority:** authenticate CreatorJD and issue
   purpose-specific one-use approvals bound to the exact snapshot digest and
   epoch, with consumption recorded in a monotonic rollback-resistant store.
4. **Production lease authority:** provide linearizable, authenticated,
   atomic acquire/renew/release operations with a durable fence high-water mark
   in a separate failure domain and no ambiguous simultaneous owner.
5. **Primary fencing and speech witness:** conclusively fence the current local
   owner, verify its CoreMind has stopped speaking, and make every local and
   standby speech path deny output on missing, expired, superseded, or
   mismatched lease evidence.
6. **Ubuntu runtime readiness:** provision the actual VM and desktop stack,
   collect integrity-protected standby evidence, and validate private
   creator-authenticated HTTPS ingress. No service, desktop, VM, or tunnel has
   been activated by this lane.
7. **Promotion executor integration:** add a separately reviewed executor that
   atomically consumes the accepted transaction, rechecks the live fence, and
   starts exactly one CoreMind. No such executor is present here.
8. **Release and failover soak:** exercise real lease expiry, partition,
   renewal failure, crash recovery, rollback, and primary return; obtain
   authenticated release receipts and time-correlated proof that speaking
   intervals never overlap.

## Focused verification

```powershell
python -m pytest -q .\deploy\ubuntu-app-vm\tests\test_transactional_promotion.py
```

The test suite covers the complete dry-run transaction, deterministic purity,
stale fences, exact approval binding, duplicate approval and event rejection,
ambiguous ownership, competing speakers, lease expiry, and rollback/release.
