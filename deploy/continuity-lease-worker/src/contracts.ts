export const AUTHORITY_NAME = "identity";
export const SCHEMA_VERSION = 1;
export const MAX_TTL_SECONDS = 35;
export const DEFAULT_TTL_SECONDS = 35;
export const MAX_REQUEST_BYTES = 4 * 1024;
export const MAX_AUDIT_ENTRIES = 4_096;
export const DEFAULT_AUDIT_LIMIT = 50;
export const MAX_AUDIT_LIMIT = 100;

export type JsonPrimitive = boolean | number | string | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export interface JsonObject {
  [key: string]: JsonValue;
}

export type AuthorityAction =
  | "health"
  | "status"
  | "heartbeat"
  | "acquire"
  | "renew"
  | "release"
  | "publish-endpoint"
  | "get-endpoint"
  | "audit";

export interface AuthorityCommand {
  action: AuthorityAction;
  payload: JsonObject;
  auditLimit?: number;
}

export interface AuthorityReply {
  status: number;
  body: JsonObject;
}

export interface AuthorityRpcReply {
  status: number;
  bodyJson: string;
}
