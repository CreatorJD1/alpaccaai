import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const main = fs.readFileSync(path.join(here, "main.ts"), "utf8");

test("the signed Android House surface keeps mobile provenance and bounded capabilities", () => {
  assert.match(main, /surface:\s*"house-hq"\s*\|\s*"mobile"/);
  assert.match(
    main,
    /value\?\.surface === "house-hq" \|\| value\?\.surface === "mobile"/,
  );
  assert.match(
    main,
    /connection\.surface === "mobile"[\s\S]*purpose === "file_source_ref"[\s\S]*purpose === "screen_share"/,
  );
  assert.match(main, /available only from the primary House desktop/);
});
