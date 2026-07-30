import assert from "node:assert/strict";
import test from "node:test";

import {
  APPROVED_ALPECCA_RUNTIME_ASSET_BASE,
  defaultAlpeccaArtBaseForHost,
  houseHostCarriesBundledArt,
  normalizeApprovedAlpeccaArtBase,
} from "./assetRouting.ts";

const remote = `${APPROVED_ALPECCA_RUNTIME_ASSET_BASE}/`;

test("local and private House hosts keep using bundled runtime art", () => {
  for (const host of ["localhost", "127.0.0.1", "192.168.1.50", "10.0.0.4", "172.20.4.8", "alpecca.local"]) {
    assert.equal(houseHostCarriesBundledArt(host), true, host);
    assert.equal(defaultAlpeccaArtBaseForHost(host, remote), "", host);
  }
});

test("public tunnel and hosted House URLs use the Hugging Face runtime assets", () => {
  for (const host of ["hawk-editorials-barry-removed.trycloudflare.com", "house.pages.dev", "example.com"]) {
    assert.equal(houseHostCarriesBundledArt(host), false, host);
    assert.equal(
      defaultAlpeccaArtBaseForHost(host, remote),
      APPROVED_ALPECCA_RUNTIME_ASSET_BASE,
      host,
    );
  }
});

test("art-base overrides accept only the exact reviewed Hugging Face revision", () => {
  assert.equal(
    normalizeApprovedAlpeccaArtBase(`${APPROVED_ALPECCA_RUNTIME_ASSET_BASE}/?download=true#ignored`),
    APPROVED_ALPECCA_RUNTIME_ASSET_BASE,
  );
  assert.equal(
    normalizeApprovedAlpeccaArtBase(
      "https://huggingface.co/datasets/CREATORJD/alpecca-runtime-assets/resolve/main/runtime-assets",
    ),
    "",
  );
  assert.equal(normalizeApprovedAlpeccaArtBase("https://example.com/alpecca"), "");
  assert.equal(normalizeApprovedAlpeccaArtBase("javascript:alert(1)"), "");
});
