# Alpecca Ubuntu App VM Scaffold

This directory is an inert, policy-testable scaffold for the persistent Ubuntu
workspace described in `docs/UBUNTU_FALLBACK_CORE_PLAN.md`. It does not deploy a
VM, create users, install packages, start a desktop or Alpecca runtime, obtain
credentials, or enable a cloud Alpecca.

## Safety boundary

- The desktop and future core use separate Unix identities:
  `alpecca-workspace` and `alpecca-core`.
- Every systemd unit has `ConditionPathExists=/etc/alpecca/enable-*`. No enable
  marker is included or created here.
- The cloud core defaults to `standby`, with all conversational egress off.
- Raw VNC and noVNC are loopback-only. The Cloudflare file is a credential-free
  placeholder for creator-authenticated private ingress.
- `alpecca-cloud-supervisor`, `verify-app-approval`,
  `alpecca-app-workflow`, and `render-workspace-cloud-init` are dry-run
  policy/render CLIs. They compute
  deterministic output and write only to stdout or stderr.
- The CLIs do not read environment variables or credential stores, use the
  network, spawn processes, mutate files, run package managers, or control
  services. Every result has `executable: false`.
- The package apply helper remains absent. No verifier result is an execution
  token or permission to install, update, disable, or remove software.

The desktop can exist independently of leadership. Desktop availability is not
evidence that a cloud core may act, and this scaffold cannot create a second
Alpecca.

## Provider-neutral workspace renderer

`alpecca_ubuntu_vm/workspace_template.py` renders the reviewed
`config/workspace-template.json` as a `#cloud-config` document. The body is JSON,
which is valid YAML, so no YAML package or executable is required. The CLI does
not accept a provider, endpoint, credential, output path, or arbitrary manifest.
It reads only the reviewed files in this directory and prints the result.

If an operator later supplies the rendered document to cloud-init outside this
repository, that separate action is designed to:

1. Preserve the image's `default` login user.
2. Create locked, non-login `alpecca-workspace` and `alpecca-core` system users
   with persistent homes under `/var/lib`.
3. Update the Ubuntu package index without upgrading the image, then install the
   exact reviewed prerequisites: `ca-certificates`, `dbus-x11`, `flatpak`,
   `novnc`, `tigervnc-standalone-server`, `tigervnc-tools`, `websockify`,
   `xauth`, and `xfce4`. No Flatpak remote is configured.
4. Copy only the display, Xfce session, and noVNC gateway units to
   `/etc/systemd/system` as mode `0644` files.
5. Write a non-secret activation contract under `/etc/alpecca`.

The rendered document has no `bootcmd`, `runcmd`, provider metadata, private
ingress implementation, daemon reload, service enable, or service start. It does
not copy the cloud-core, app-operation, or provider-specific tunnel units.

TigerVNC requires both `/etc/alpecca/enable-desktop` and the externally injected
`/run/secrets/alpecca-vnc-password`. Neither path is created by the template.
VNC remains on `127.0.0.1:5900`; noVNC/websockify remains on
`127.0.0.1:6080`. Phone access therefore still requires a separately reviewed
private ingress adapter, creator authentication, and out-of-band ingress
credentials. The activation contract records those unfinished requirements.

Changing a package, service source, listener, user, secret path, marker, or
output-safety flag makes rendering fail closed. The generator never provisions
infrastructure or contacts a cloud API. Applying its output is a separate future
operation and is not performed by this repository.

## Pure supervisor policy

`alpecca_ubuntu_vm/supervisor.py` evaluates caller-supplied observations. A
`leader-ready` dry-run decision requires all of the following:

1. The caller says its monotonic state passed a future external integrity check.
2. A future lease adapter says the grant was authenticated by an available,
   linearizable authority.
3. The primary-missed grace period has elapsed.
4. The latest vault snapshot is verified, restored, identified, not from the
   future, and not ahead of the grant epoch.
5. The lease holder matches this node, its lifetime is at most 35 seconds, it is
   currently valid, and its epoch is newer than retained fenced state.

The state machine retains `highestFencingEpoch` after any denial. Reusing a
different lease at that epoch is stale. A same-ID renewal must keep the same
epoch and cannot move issue or expiry time backwards. Evaluation time is always
explicit; moving it behind `lastEvaluatedAt` fails closed.

`validate_fencing_epoch()` separately requires the exact active lease ID, exact
highest epoch, an unexpired lease, intact state, and no clock rollback. A local
pass is only a test result. Production side-effect stores and transports must
also reject stale epochs at their own trust boundaries.

The `grantAuthenticated` and `stateIntegrityVerified` booleans are interfaces
for future trusted adapters. The CLI does not prove either claim. Until those
adapters and a rollback-resistant state store exist, production activation is
prohibited.

## Composite continuity ownership gate

`alpecca_ubuntu_vm/continuity_lease.py` wraps the supervisor policy with the
local-authority evidence required for a cloud takeover. A raw `leader-ready`
result is necessary but is never sufficient continuity authorization.

The composite evaluator always returns `standby` while a verified local-owner
heartbeat is fresh or its ownership lease is active. Takeover eligibility
requires both signals to be expired, an exact creator activation marker whose
verified approval was issued only after both expiries, and a cloud candidate
lease issued after that activation with a strictly newer fencing epoch. The
candidate must also pass every existing supervisor and vault gate at the same
explicit evaluation time and cloud node ID.

Heartbeat and local-lease evidence is bounded to 35 seconds. Creator activation
is bounded to 300 seconds and must name `/etc/alpecca/enable-cloud-core`; the
marker's mere presence is insufficient without the separately supplied
integrity and creator-approval verdicts. These booleans are future adapter
interfaces, not claims authenticated by this repository.

Even `takeover-eligible` means only that the supplied JSON passed a pure policy
simulation. The result always has `wouldStartAlpecca: false`, `executable:
false`, and an empty side-effect list. A denied evaluation returns no proposed
supervisor successor state. The evaluator never creates or reads the marker.

## Pure app-operation policy

`alpecca_ubuntu_vm/app_verifier.py` checks an exact operation, external creator
approval verdict, catalog, idempotency ledger, and explicit time. A new request
can reach only `would-reserve`, which returns a proposed next ledger without
writing it.

The operation digest binds the creator principal, one-use approval ID, expiry,
manager, action, source, package, version, disk estimate, and sorted permission
set. The approval must bind that digest and operation ID, be issued to
`CreatorJD`, be currently valid, be one-use, and not outlive the request.

The approval field `verification.verifier=external-creator-verifier` represents
the output of a future separately trusted creator-authentication adapter. It is
not a signature and is not authenticated by the dry-run CLI. This skeleton
tests downstream policy only.

`ledgerIntegrityVerified` is likewise a future adapter assertion. Both new and
replayed requests fail closed when it is false. Proposed reservation IDs start
with `dry-run:` and cannot be consumed by any implementation in this scaffold.

Catalog entries are exact objects. `config/app-catalog.json` remains the empty
deny-all verifier baseline. The new workflow reads only
`config/reviewed-app-install-catalog.json`, a small reviewed install-only
allowlist for the Ubuntu desktop; every other operation remains denied. Empty
arrays deny every operation. The supported entry shapes are:

```json
{
  "apt": {
    "allowedRepositories": [
      {"id": "reviewed-main", "source": "EXACT_SOURCE"}
    ],
    "allowedPackages": [
      {
        "package": "EXACT_PACKAGE",
        "repository": "reviewed-main",
        "versions": ["EXACT_VERSION"],
        "actions": ["install", "update", "disable", "remove"],
        "maxEstimatedDiskBytes": 0,
        "allowedPermissions": []
      }
    ]
  },
  "flatpak": {
    "allowedRemotes": [
      {"name": "reviewed-remote", "source": "EXACT_SOURCE"}
    ],
    "allowedApplications": [
      {
        "applicationId": "EXACT_APPLICATION_ID",
        "remote": "reviewed-remote",
        "versions": ["EXACT_VERSION"],
        "actions": ["install", "update", "disable", "remove"],
        "maxEstimatedDiskBytes": 0,
        "allowedPermissions": []
      }
    ]
  }
}
```

The proposed ledger reserves both the operation ID and approval ID. Replaying
the same digest is an `idempotent-noop`; changing a reserved operation ID or
reusing an approval ID is denied. A future executor would need an atomic,
rollback-resistant reservation store before any package action. No such store
or executor is implemented here.

## Dry-run CLI

Both entry points require `--dry-run`. They accept `-` for stdin or an explicit
JSON file and use no implicit current time.

```powershell
python .\deploy\ubuntu-app-vm\bin\alpecca-cloud-supervisor evaluate --dry-run `
  --input .\deploy\ubuntu-app-vm\contracts\supervisor-observation.example.json

python .\deploy\ubuntu-app-vm\bin\alpecca-cloud-supervisor validate-fence `
  --dry-run --input .\deploy\ubuntu-app-vm\contracts\fence-check.example.json

python .\deploy\ubuntu-app-vm\bin\alpecca-cloud-supervisor evaluate-continuity `
  --dry-run --input .\deploy\ubuntu-app-vm\contracts\continuity-takeover.example.json

python .\deploy\ubuntu-app-vm\bin\verify-app-approval verify --dry-run `
  --input .\deploy\ubuntu-app-vm\contracts\app-verification.example.json

python .\deploy\ubuntu-app-vm\bin\alpecca-app-workflow catalog --dry-run

python .\deploy\ubuntu-app-vm\bin\alpecca-app-workflow propose --dry-run `
  --input .\deploy\ubuntu-app-vm\contracts\app-proposal-request.example.json

python .\deploy\ubuntu-app-vm\bin\alpecca-app-workflow desktop-status --dry-run `
  --input .\deploy\ubuntu-app-vm\contracts\desktop-readiness.example.json

python .\deploy\ubuntu-app-vm\bin\render-workspace-cloud-init render --dry-run
```

Exit code `0` means the simulated policy is eligible or already idempotently
reserved. Exit code `3` is a well-formed policy denial. Exit code `2` is malformed
input or a CLI/read error. No exit code authorizes an operational action.

## Layout

- `alpecca_ubuntu_vm/`: pure supervisor, fence, app-verifier, app workflow,
  noVNC evidence, and JSON helpers.
- `bin/`: dry-run-only policy and template-rendering entry points.
- `config/runtime.env.example`: fail-closed standby and dry-run defaults.
- `config/workspace-template.json`: exact reviewed Ubuntu workspace manifest.
- `config/cloudflared-desktop.yml.example`: private loopback ingress placeholder.
- `config/app-catalog.json`: empty deny-all verifier baseline.
- `config/reviewed-app-install-catalog.json`: deterministic install-only
  APT/Flatpak workflow allowlist; all unlisted operations are denied.
- `docs/APP_INSTALL_AND_NOVNC_STATUS.md`: exact workflow and honesty boundary.
- `tests/`: focused dry-run catalog, approval, fencing, and noVNC evidence tests.
- `contracts/leader-lease-contract.json`: lease, vault, and fence requirements.
- `contracts/continuity-ownership-lease-contract.json`: composite local-owner
  heartbeat, expiry, creator activation, and cloud takeover requirements.
- `contracts/continuity-takeover.example.json`: runnable inert takeover input.
- `contracts/app-approval-contract.json`: approval, allowlist, and replay rules.
- `contracts/app-operation.example.json`: non-executable request shape.
- `contracts/app-verification.example.json`: runnable credential-free dry run.
- `contracts/fence-check.example.json`: runnable exact-epoch fence dry run.
- `contracts/supervisor-observation.example.json`: runnable dry-run policy input.
- `systemd/`: inert core, desktop, gateway, tunnel, and app-operation units.

## Verification

```powershell
python -m pytest -q tests -k ubuntu_app_vm
```

The tests cover dual-node contention, local heartbeat and ownership-lease
precedence, creator activation ordering, authority loss, vault gates, expiry,
clock rollback, delayed epochs, exact fence checks, catalog dimensions,
approval binding and expiry, replay, conflicts, malformed state, locked
workspace users, reviewed packages, loopback listeners, template drift, and CLI
dry-run guards.

## Future activation gates

1. Implement authenticated lease and creator-verdict adapters without placing
   secrets in this repository or policy JSON.
2. Implement rollback-resistant supervisor state and atomic app reservation
   storage in a separate reviewed boundary.
3. Implement server-side epoch rejection for every continuity write, portal,
   Discord send, notification, commitment, and vault snapshot.
4. Prove lease partition, stale-epoch rejection, disposable vault restore, and
   creator-observed failover/failback.
5. Add and review any package executor separately. It must consume exactly one
   atomic reservation and emit an audit receipt.
6. Provision infrastructure and create enable markers only after every delivery
   gate in the source plan passes.

The workspace cloud-init must likewise be reviewed and applied by an external
operator. After it completes, that operator must inject the VNC secret, install
and configure one private creator-authenticated ingress adapter, create the
desktop marker, and explicitly enable/start the three desktop units. None of
those activation steps is implemented by the renderer.

The repository policy CLIs must not be installed as operational service helpers.
Their required subcommands and `--dry-run` flag intentionally make the current
systemd placeholder invocations fail closed.
