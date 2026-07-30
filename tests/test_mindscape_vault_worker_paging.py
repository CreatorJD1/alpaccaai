from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "deploy" / "mindscape-vault-worker" / "worker.js"


def test_worker_pages_encrypted_event_envelopes_with_a_bounded_cursor(
    tmp_path: Path,
) -> None:
    module_path = tmp_path / "worker.mjs"
    shutil.copyfile(WORKER, module_path)
    runner = tmp_path / "runner.mjs"
    runner.write_text(
        """
import { timingSafeEqual } from "node:crypto";
import { pathToFileURL } from "node:url";

Object.defineProperty(globalThis.crypto.subtle, "timingSafeEqual", {
  value: (left, right) => timingSafeEqual(Buffer.from(left), Buffer.from(right)),
});

const worker = (await import(pathToFileURL(process.argv[2]).href)).default;
const scope = "a".repeat(32);
const token = "t".repeat(24);

function envelope(segmentId, createdAt) {
  return {
    schema: "alpecca.continuity.events.v1",
    kind: "events",
    algorithm: "AES-256-GCM",
    scope,
    key_id: "b".repeat(24),
    segment_id: segmentId,
    created_at: createdAt,
    event_count: 1,
    compression: "zlib",
    nonce: "c".repeat(16),
    ciphertext: "d".repeat(24),
    ciphertext_sha256: "e".repeat(64),
    plaintext_sha256: "f".repeat(64),
  };
}

const firstEnvelope = envelope("1".repeat(32), 1_700_000_001);
const secondEnvelope = envelope("2".repeat(32), 1_700_000_002);
const records = new Map([
  ["events-newer", secondEnvelope],
  ["events-older", firstEnvelope],
]);
let listCalls = 0;
const env = {
  MINDSCAPE_VAULT_TOKEN: token,
  MINDSCAPE_VAULT_ARCHIVE: {
    async list(options) {
      listCalls += 1;
      if (options.include[0] !== "customMetadata") {
        throw new Error("unexpected bounded list options");
      }
      const page = (listCalls - 1) % 2;
      if (page === 0) {
        if (options.limit !== 1000 || options.cursor !== undefined) {
          throw new Error("unexpected first R2 list page");
        }
        return {
          truncated: true,
          cursor: "r2-next",
          delimitedPrefixes: [],
          objects: [
            { key: "events-newer", customMetadata: {
              kind: "events", scope, created_at: String(secondEnvelope.created_at),
            } },
          ],
        };
      }
      if (options.limit !== 999 || options.cursor !== "r2-next") {
        throw new Error("unexpected second R2 list page");
      }
      return {
        truncated: false,
        delimitedPrefixes: [],
        objects: [
          { key: "events-older", customMetadata: {
            kind: "events", scope, created_at: String(firstEnvelope.created_at),
          } },
        ],
      };
    },
    async get(key) {
      const value = records.get(key);
      return value ? { json: async () => value } : null;
    },
  },
};

async function request(query, authorization = `Bearer ${token}`) {
  const response = await worker.fetch(new Request(
    `https://vault.example/v1/events/latest?${query}`,
    { headers: {
      authorization,
      "x-alpecca-mindscape-vault-scope": scope,
    } },
  ), env);
  return { status: response.status, body: await response.json() };
}

const first = await request("cursor=0&limit=1");
const second = await request("cursor=1&limit=1");
const invalid = await request("cursor=1&limit=0");
const denied = await request("cursor=0&limit=1", "Bearer wrong");
console.log(JSON.stringify({ first, second, invalid, denied, listCalls }));
""".strip()
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        ["node", str(runner), str(module_path)],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["first"]["status"] == 200
    assert payload["first"]["body"]["next_cursor"] == 1
    assert payload["first"]["body"]["envelopes"][0]["segment_id"] == "1" * 32
    assert payload["second"]["status"] == 200
    assert payload["second"]["body"]["next_cursor"] is None
    assert payload["second"]["body"]["envelopes"][0]["segment_id"] == "2" * 32
    assert payload["invalid"] == {
        "status": 400,
        "body": {"ok": False, "error": "invalid event page"},
    }
    assert payload["denied"] == {
        "status": 401,
        "body": {"ok": False, "error": "unauthorized"},
    }
    assert payload["listCalls"] == 4
