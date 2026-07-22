export type PerceptionEgressRequest = {
  requestId: string;
  state: "pending" | "approved" | "denied" | "consumed" | "expired";
  routeId: string;
  provider: string;
  deployment: string;
  model: string;
  processingLocation: string;
  destinationClass: string;
  byteCount: number;
  expiresAt: number;
};

export type PerceptionEgressRoute = {
  routeId: string;
  provider: string;
  deployment: string;
  model: string;
  processingLocation: string;
  destinationClass: string;
  maxBytesPerUse: number;
};

export type PerceptionEgressStatus = {
  available: boolean;
  reason: string;
  requests: PerceptionEgressRequest[];
  routes: PerceptionEgressRoute[];
};

export type StagedPerceptionEgress = {
  requestId: string;
  operationId: string;
  routeId: string;
  imageDataUrl: string;
};

const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};

const text = (value: unknown): string => typeof value === "string" ? value.trim() : "";
const number = (value: unknown): number => typeof value === "number" && Number.isFinite(value) ? value : 0;

export function normalizePerceptionEgressStatus(value: unknown): PerceptionEgressStatus {
  const source = record(value);
  const requests = Array.isArray(source.requests) ? source.requests : [];
  const routes = Array.isArray(source.routes) ? source.routes : [];
  return {
    available: source.available === true,
    reason: text(source.reason),
    requests: requests.map((item) => {
      const request = record(item);
      const rawState = text(request.state);
      const state = ["pending", "approved", "denied", "consumed", "expired"].includes(rawState)
        ? rawState as PerceptionEgressRequest["state"]
        : "expired";
      return {
        requestId: text(request.request_id),
        state,
        routeId: text(request.route_id),
        provider: text(request.provider),
        deployment: text(request.deployment),
        model: text(request.model),
        processingLocation: text(request.processing_location),
        destinationClass: text(request.destination_class),
        byteCount: number(request.byte_count),
        expiresAt: number(request.expires_at),
      };
    }).filter((item) => item.requestId && item.routeId),
    routes: routes.map((item) => {
      const route = record(item);
      return {
        routeId: text(route.route_id),
        provider: text(route.provider),
        deployment: text(route.deployment),
        model: text(route.model),
        processingLocation: text(route.processing_location),
        destinationClass: text(route.destination_class),
        maxBytesPerUse: number(route.max_bytes_per_use),
      };
    }).filter((item) => item.routeId),
  };
}

export function stagedPerceptionEgress(
  value: unknown,
  imageDataUrl: string,
): StagedPerceptionEgress | null {
  const stage = record(value);
  const request = record(stage.request);
  const requestId = text(request.request_id);
  const operationId = text(stage.operation_id);
  const routeId = text(request.route_id);
  if (!requestId || !operationId || !routeId || !imageDataUrl.startsWith("data:image/")) return null;
  return { requestId, operationId, routeId, imageDataUrl };
}

export function canExecutePerceptionEgress(
  request: PerceptionEgressRequest,
  staged: StagedPerceptionEgress | null,
): boolean {
  return Boolean(
    staged
    && request.state === "approved"
    && request.requestId === staged.requestId
    && request.routeId === staged.routeId,
  );
}
