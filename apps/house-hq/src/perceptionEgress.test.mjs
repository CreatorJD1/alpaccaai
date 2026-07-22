import assert from "node:assert/strict";
import test from "node:test";

import {
  canExecutePerceptionEgress,
  normalizePerceptionEgressStatus,
  stagedPerceptionEgress,
} from "./perceptionEgress.ts";

test("normalizes only content-free egress status fields", () => {
  const status = normalizePerceptionEgressStatus({
    available: true,
    secret: "must-not-surface",
    routes: [{
      route_id: "vision-cloud",
      provider: "ollama-cloud",
      deployment: "primary",
      model: "vision:cloud",
      processing_location: "provider-managed",
      destination_class: "managed-model-api",
      transport_route: "https://hidden.example/api",
      max_bytes_per_use: 2048,
    }],
    requests: [{
      request_id: "request_one",
      state: "approved",
      route_id: "vision-cloud",
      provider: "ollama-cloud",
      model: "vision:cloud",
      byte_count: 512,
      payload_hmac: "hidden",
    }],
  });
  assert.equal(status.available, true);
  assert.equal(status.routes[0].routeId, "vision-cloud");
  assert.equal(status.routes[0].transportRoute, undefined);
  assert.equal(status.requests[0].payloadHmac, undefined);
});

test("execution requires the approved request and same staged route", () => {
  const staged = stagedPerceptionEgress({
    operation_id: "op_example",
    request: { request_id: "request_one", route_id: "vision-cloud" },
  }, "data:image/png;base64,AAAA");
  assert.ok(staged);
  const request = {
    requestId: "request_one",
    state: "approved",
    routeId: "vision-cloud",
  };
  assert.equal(canExecutePerceptionEgress(request, staged), true);
  assert.equal(canExecutePerceptionEgress({ ...request, state: "pending" }, staged), false);
  assert.equal(canExecutePerceptionEgress({ ...request, requestId: "request_two" }, staged), false);
  assert.equal(canExecutePerceptionEgress({ ...request, routeId: "other" }, staged), false);
});

test("rejects malformed stage responses and non-image browser data", () => {
  assert.equal(stagedPerceptionEgress({}, "data:image/png;base64,AAAA"), null);
  assert.equal(stagedPerceptionEgress({
    operation_id: "op_example",
    request: { request_id: "request_one", route_id: "vision-cloud" },
  }, "data:text/plain;base64,AAAA"), null);
});
