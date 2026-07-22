# Alpecca Release Secret Scan

`scripts/release_secret_scan.py` is the bounded P1 release gate for plaintext
secrets. It is credential-free: it does not read environment variables,
Credential Manager, browser storage, network services, or deployment state.
It never rotates, revokes, or publishes anything.

## Scope

Every run scans both of these inputs:

1. every path returned by `git ls-files --cached`; and
2. every regular file under the built `apps/house-hq/dist` tree.

The distribution is intentionally scanned separately because it is ignored by
Git. A missing/empty distribution, a missing `dist/index.html`, a symlink,
an unreadable file, an escaping path, a changing file, a failed Git listing, or
an unavailable Git `HEAD` makes the gate fail closed. Binary assets are streamed
through the same detectors rather than silently excluded. No size-based skip is
used.

## Receipt

The JSON receipt contains:

- UTC generation time and repository commit hash;
- scanned file/byte/finding/error counts per scope;
- an aggregate inventory digest per scope;
- detector names, byte offsets, and SHA-256 path identities for findings;
- `result`, `release_ready`, and an explicit claim; and
- a digest of the receipt itself.

It does **not** contain matched bytes, source excerpts, environment values,
exception text, credentials, or raw file paths. A finding or scan error always
sets `release_ready` to `false` and `claim` to `not_release_ready`.

## Commands

Build House HQ first, then run the gate from the repository root:

```powershell
npm.cmd run house:build
python scripts\release_secret_scan.py --receipt output\release-secret-scan.json --pretty
```

The process exits `0` only for a complete, zero-finding Git-defined scan. It
exits `1` for findings, missing build output, scan errors, or any other state
that cannot support a release claim.

To inspect the receipt without writing a file:

```powershell
python scripts\release_secret_scan.py --dry-run --pretty
```

`--dry-run` changes only persistence. It still performs the complete scan and
prints the content-free receipt to standard output.

## Test Fixtures

The Python API accepts an explicit `tracked_paths` sequence for isolated test
fixtures. Fixture scans exercise the same detectors and distribution rules, but
they can never claim release readiness because Git did not define their source
scope. This prevents a narrow test fixture from being mistaken for a release
receipt.

Focused verification:

```powershell
python -m pytest -q tests\test_release_secret_scan.py
```

The tests cover source and built-bundle findings, chunk-boundary matching,
missing and malformed distributions, path escape and symlink rejection,
content-free output, deterministic receipt hashing, real Git scope, dry-run,
and atomic receipt writing.
