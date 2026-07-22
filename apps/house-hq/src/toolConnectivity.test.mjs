import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  HOUSE_READ_TOOLS,
  buildToolLibrarySnapshot,
  houseReadToolControl,
} from "./toolConnectivity.ts";

test("every source control is tied to a bounded read endpoint", () => {
  assert.deepEqual(HOUSE_READ_TOOLS.map(({ id, endpoint, method }) => ({ id, endpoint, method })), [
    { id: "self", endpoint: "/introspect", method: "GET" },
    { id: "memory", endpoint: "/memories/search", method: "GET" },
    { id: "journal", endpoint: "/journal", method: "GET" },
    { id: "studio", endpoint: "/growth", method: "GET" },
    { id: "home", endpoint: "/home/state", method: "GET" },
  ]);
  assert.equal(houseReadToolControl("memory", "live").disabled, false);
  assert.match(houseReadToolControl("memory", "offline").title, /unavailable/i);
  assert.equal(houseReadToolControl("missing", "live").disabled, true);
});

test("tool library reports backend executable tools and Parlor honestly", () => {
  assert.deepEqual(buildToolLibrarySnapshot({
    growth: { executable_tools: ["self_status", "memory_search"] },
    home: { location: "parlor", rooms: [{ id: "parlor" }, { id: "library" }] },
    runtime: { senses: { actions: true } },
  }), {
    currentRoom: "parlor",
    parlorKnown: true,
    parlorCurrent: true,
    actuatorEnabled: true,
    executableTools: ["memory_search", "self_status"],
  });
});

test("visible system actions all have a frontend handler and Tools no longer opens Soul", () => {
  const source = fs.readFileSync(fileURLToPath(new URL("./main.ts", import.meta.url)), "utf8");
  const visible = new Set([...source.matchAll(/data-system-action="([^"]+)"/g)].map((match) => match[1]));
  const handled = new Set([...source.matchAll(/action === "([^"]+)"/g)].map((match) => match[1]));
  assert.deepEqual([...visible].filter((action) => !handled.has(action)), []);
  assert.match(source, /nav === "tools" \? "tools"/);
  assert.doesNotMatch(source, /nav === "tools" \? "soul"/);
});
