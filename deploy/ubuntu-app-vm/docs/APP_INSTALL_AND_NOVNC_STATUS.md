# Ubuntu App VM: Catalog, Approval Receipts, and noVNC Evidence

This slice is executable only as a deterministic **dry-run policy tool**. It
does not contain an installer, package-manager runner, service controller,
CoreMind launcher, cloud provisioner, network client, or credential adapter.

## Reviewed catalog

`config/app-catalog.json` remains the original empty deny-all verifier baseline.
`config/reviewed-app-install-catalog.json` is also deny-by-default and permits
new workflow proposals for four exact identities:

- APT: `file-roller` and `xterm` from the logical Ubuntu 24.04 Noble main
  source.
- Flatpak: `org.libreoffice.LibreOffice` and `org.mozilla.firefox` from the
  official Flathub repository descriptor.

The APT `ubuntu-noble` value is a reviewed release-channel label, not a resolved
`.deb` artifact version. The Flatpak `stable` value is a branch, not a commit.
No executor exists. A future executor must resolve immutable package metadata,
put it into a new proposal schema, and obtain a fresh CreatorJD approval before
any real install can be considered.

Catalog order and identifiers are deterministic. Anything not listed, any
unlisted permission, an excessive disk estimate, a second candidate version,
or an action other than `install` is denied.

## Proposal and receipt flow

1. `catalog` reads only the checked-in reviewed catalog.
2. `propose` binds app identity, estimate, requested permissions, approval ID,
   expiry, catalog digest, continuity lease ID, and fencing epoch into a stable
   operation and proposal digest.
3. An external creator-authentication adapter must produce the existing
   one-use approval object for principal `CreatorJD`. This repository does not
   authenticate or manufacture that verdict.
4. `receipt` re-derives the proposal, runs the existing app verifier, validates
   the exact active lease and epoch through `validate_fencing_epoch()`, and
   requires the receipt time to equal the fence-check time.
5. A passing receipt says only `policyEligible: true`. It still reports
   `executorImplemented: false`, `executable: false`, `wouldInstall: false`,
   empty commands, no files written, no services enabled or started, and
   `coreMindStarted: false`.

The proposed next ledger is emitted only when both approval and fence gates
pass. It is not persisted. A future implementation still needs an atomic,
rollback-resistant reservation store and a separately reviewed executor.

```powershell
python .\deploy\ubuntu-app-vm\bin\alpecca-app-workflow catalog --dry-run

python .\deploy\ubuntu-app-vm\bin\alpecca-app-workflow propose --dry-run `
  --input .\deploy\ubuntu-app-vm\contracts\app-proposal-request.example.json
```

There is intentionally no `install`, `apply`, `enable`, `start`, or `run-core`
subcommand.

## noVNC readiness evidence

`desktop-status` evaluates a caller-supplied observation containing package,
unit, activation-marker, VNC-secret-presence, loopback listener, HTTPS ingress,
creator-authentication, and exact continuity-fence evidence.

```powershell
python .\deploy\ubuntu-app-vm\bin\alpecca-app-workflow desktop-status --dry-run `
  --input .\deploy\ubuntu-app-vm\contracts\desktop-readiness.example.json
```

The evaluator does not inspect the current machine. Its output therefore says
`evidenceSource: caller-supplied-observation` and `independentlyProbed: false`.
An external, integrity-protected collector is still required for production.
The readiness states distinguish desktop visibility from CoreMind leadership:

- `phone-ready-fenced`: phone desktop evidence and the exact continuity fence
  both pass.
- `phone-ready-desktop-only`: the desktop may be visible, but app operations and
  CoreMind remain fenced.
- `desktop-active-no-phone-ingress`: local noVNC evidence passes but private,
  authenticated phone ingress is incomplete.
- `desktop-defined-standby`, `not-ready`, `evidence-unverified`, or
  `evidence-invalid`: one or more required layers are missing or untrusted.

Desktop readiness never grants leadership. The tool never starts CoreMind.

## Focused verification

```powershell
python -m pytest -q .\deploy\ubuntu-app-vm\tests
```
