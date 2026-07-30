import { timingSafeEqual } from "node:crypto";

const MODEL = "@cf/google/gemma-4-26b-a4b-it" as const;
const CONTEXT_WINDOW_TOKENS = 256_000;
const MAX_BODY_BYTES = 2 * 1024 * 1024;
const MAX_MESSAGES = 512;
const MAX_TEXT_CHARACTERS = 900_000;
const MAX_TOOLS = 64;
const MAX_OUTPUT_TOKENS = 2_048;
const MIN_SECRET_CHARACTERS = 32;
const MAX_SECRET_CHARACTERS = 512;

export type ModelRunner = (
  model: typeof MODEL,
  input: ChatCompletionsInput,
) => Promise<ChatCompletionsOutput>;

class RequestProblem extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(code);
  }
}

function jsonResponse(
  body: Record<string, unknown>,
  status = 200,
): Response {
  return Response.json(body, {
    status,
    headers: {
      "cache-control": "no-store",
      "content-type": "application/json; charset=utf-8",
      "x-content-type-options": "nosniff",
    },
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function boundedString(value: unknown, maximum: number): string | null {
  if (typeof value !== "string" || value.length > maximum) {
    return null;
  }
  return value;
}

function normalizeToolCall(value: unknown): ChatCompletionMessageToolCall | null {
  if (!isRecord(value) || value.type !== "function") {
    return null;
  }
  const id = boundedString(value.id, 128);
  const fn = value.function;
  if (!id || !isRecord(fn)) {
    return null;
  }
  const name = boundedString(fn.name, 128);
  const args = boundedString(fn.arguments, 64 * 1024);
  if (!name || args === null) {
    return null;
  }
  return {
    id,
    type: "function",
    function: { name, arguments: args },
  };
}

function normalizeMessage(value: unknown): ChatCompletionMessageParam | null {
  if (!isRecord(value) || typeof value.role !== "string") {
    return null;
  }
  if (value.role === "system" || value.role === "developer") {
    const content = boundedString(value.content, MAX_TEXT_CHARACTERS);
    return content === null ? null : { role: value.role, content };
  }
  if (value.role === "user") {
    // This language route is deliberately text-only. Images, audio, files, and
    // screen-derived multimodal payloads need their own explicit consent path.
    const content = boundedString(value.content, MAX_TEXT_CHARACTERS);
    return content === null ? null : { role: "user", content };
  }
  if (value.role === "assistant") {
    const content = value.content === null
      ? null
      : boundedString(value.content, MAX_TEXT_CHARACTERS);
    if (content === null && value.content !== null && value.content !== undefined) {
      return null;
    }
    if (value.tool_calls === undefined) {
      return { role: "assistant", content };
    }
    if (!Array.isArray(value.tool_calls) || value.tool_calls.length > MAX_TOOLS) {
      return null;
    }
    const toolCalls = value.tool_calls.map(normalizeToolCall);
    if (toolCalls.some((call) => call === null)) {
      return null;
    }
    return {
      role: "assistant",
      content,
      tool_calls: toolCalls.filter(
        (call): call is ChatCompletionMessageToolCall => call !== null,
      ),
    };
  }
  if (value.role === "tool") {
    const content = boundedString(value.content, MAX_TEXT_CHARACTERS);
    const toolCallId = boundedString(value.tool_call_id, 128);
    return content === null || !toolCallId
      ? null
      : { role: "tool", content, tool_call_id: toolCallId };
  }
  if (value.role === "function") {
    const content = boundedString(value.content, MAX_TEXT_CHARACTERS);
    const name = boundedString(value.name, 128);
    return content === null || !name
      ? null
      : { role: "function", content, name };
  }
  return null;
}

function normalizeTool(value: unknown): ChatCompletionTool | null {
  if (!isRecord(value) || value.type !== "function" || !isRecord(value.function)) {
    return null;
  }
  const name = boundedString(value.function.name, 128);
  const description = value.function.description === undefined
    ? undefined
    : boundedString(value.function.description, 4_096);
  if (!name || description === null) {
    return null;
  }
  const parameters = value.function.parameters;
  if (parameters !== undefined && !isRecord(parameters)) {
    return null;
  }
  return {
    type: "function",
    function: {
      name,
      ...(description === undefined ? {} : { description }),
      ...(parameters === undefined ? {} : { parameters }),
    },
  };
}

function normalizeInput(value: unknown): ChatCompletionsInput {
  if (!isRecord(value) || !Array.isArray(value.messages)) {
    throw new RequestProblem(400, "invalid_request");
  }
  if (value.model !== MODEL) {
    throw new RequestProblem(400, "model_not_allowed");
  }
  if (value.stream === true) {
    throw new RequestProblem(400, "streaming_not_supported");
  }
  if (value.messages.length < 1 || value.messages.length > MAX_MESSAGES) {
    throw new RequestProblem(400, "message_count_invalid");
  }
  const messages = value.messages.map(normalizeMessage);
  if (messages.some((message) => message === null)) {
    throw new RequestProblem(400, "message_invalid");
  }
  const normalizedMessages = messages.filter(
    (message): message is ChatCompletionMessageParam => message !== null,
  );
  const textCharacters = normalizedMessages.reduce((total, message) => {
    const content = "content" in message ? message.content : "";
    return total + (typeof content === "string" ? content.length : 0);
  }, 0);
  if (textCharacters > MAX_TEXT_CHARACTERS) {
    throw new RequestProblem(413, "context_too_large");
  }

  const maxTokens = Number.isInteger(value.max_tokens)
    ? Math.max(1, Math.min(MAX_OUTPUT_TOKENS, Number(value.max_tokens)))
    : 768;
  const temperature = typeof value.temperature === "number" && Number.isFinite(value.temperature)
    ? Math.max(0, Math.min(2, value.temperature))
    : 0.8;
  const input: ChatCompletionsInput = {
    messages: normalizedMessages,
    max_tokens: maxTokens,
    temperature,
    stream: false,
    // Gemma 4 enables reasoning by default. Keep this compatibility route on
    // visible final-answer tokens so small replies cannot be consumed entirely
    // by the model's reasoning budget. Callers cannot override this boundary.
    chat_template_kwargs: { enable_thinking: false },
  };

  if (value.tools !== undefined) {
    if (!Array.isArray(value.tools) || value.tools.length > MAX_TOOLS) {
      throw new RequestProblem(400, "tools_invalid");
    }
    const tools = value.tools.map(normalizeTool);
    if (tools.some((tool) => tool === null)) {
      throw new RequestProblem(400, "tools_invalid");
    }
    input.tools = tools.filter((tool): tool is ChatCompletionTool => tool !== null);
    if (value.tool_choice !== undefined) {
      if (!(["auto", "none", "required"] as const).includes(
        value.tool_choice as "auto" | "none" | "required",
      )) {
        throw new RequestProblem(400, "tool_choice_invalid");
      }
      input.tool_choice = value.tool_choice as "auto" | "none" | "required";
    }
  }
  return input;
}

async function readBoundedJson(request: Request): Promise<unknown> {
  const declared = request.headers.get("content-length");
  if (declared !== null) {
    const declaredBytes = Number(declared);
    if (!Number.isInteger(declaredBytes) || declaredBytes < 1) {
      throw new RequestProblem(400, "content_length_invalid");
    }
    if (declaredBytes > MAX_BODY_BYTES) {
      throw new RequestProblem(413, "request_too_large");
    }
  }
  if (request.body === null) {
    throw new RequestProblem(400, "body_required");
  }
  const chunks: Uint8Array[] = [];
  const reader = request.body.getReader();
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      total += value.byteLength;
      if (total > MAX_BODY_BYTES) {
        await reader.cancel("request_too_large");
        throw new RequestProblem(413, "request_too_large");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new RequestProblem(400, "json_invalid");
  }
}

async function secretsMatch(provided: string, expected: string): Promise<boolean> {
  const encoded = new TextEncoder();
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoded.encode(provided)),
    crypto.subtle.digest("SHA-256", encoded.encode(expected)),
  ]);
  return timingSafeEqual(
    new Uint8Array(providedHash),
    new Uint8Array(expectedHash),
  );
}

async function isAuthorized(request: Request, secret: string): Promise<boolean> {
  const header = request.headers.get("authorization");
  if (!header || !header.startsWith("Bearer ") || header.includes(",")) {
    return false;
  }
  const provided = header.slice("Bearer ".length);
  if (
    provided.length < MIN_SECRET_CHARACTERS
    || provided.length > MAX_SECRET_CHARACTERS
  ) {
    return false;
  }
  return secretsMatch(provided, secret);
}

function textCharacterCount(input: ChatCompletionsInput): number {
  return input.messages.reduce((total, message) => {
    const content = "content" in message ? message.content : "";
    return total + (typeof content === "string" ? content.length : 0);
  }, 0);
}

export async function handleRequest(
  request: Request,
  authSecret: string,
  runModel: ModelRunner,
): Promise<Response> {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/healthz") {
    return jsonResponse({
      service: "alpecca-cloud-language",
      version: 1,
      ready: authSecret.length >= MIN_SECRET_CHARACTERS,
      model: MODEL,
      contextWindowTokens: CONTEXT_WINDOW_TOKENS,
      modality: "text-only",
    });
  }
  if (request.method !== "POST" || url.pathname !== "/v1/chat/completions") {
    return jsonResponse({ error: "not_found" }, 404);
  }
  if (
    authSecret.length < MIN_SECRET_CHARACTERS
    || authSecret.length > MAX_SECRET_CHARACTERS
  ) {
    return jsonResponse({ error: "service_unavailable" }, 503);
  }
  if (!(await isAuthorized(request, authSecret))) {
    return jsonResponse({ error: "unauthorized" }, 401);
  }

  const requestId = crypto.randomUUID();
  const started = Date.now();
  try {
    const input = normalizeInput(await readBoundedJson(request));
    const result = await runModel(MODEL, input);
    console.log(JSON.stringify({
      event: "language_completion",
      requestId,
      model: MODEL,
      messages: input.messages.length,
      textCharacters: textCharacterCount(input),
      durationMs: Date.now() - started,
      ok: true,
    }));
    return new Response(JSON.stringify(result), {
      status: 200,
      headers: {
        "cache-control": "no-store",
        "content-type": "application/json; charset=utf-8",
        "x-content-type-options": "nosniff",
        "x-request-id": requestId,
      },
    });
  } catch (error) {
    if (error instanceof RequestProblem) {
      return jsonResponse({ error: error.code }, error.status);
    }
    console.error(JSON.stringify({
      event: "language_completion",
      requestId,
      model: MODEL,
      durationMs: Date.now() - started,
      ok: false,
      errorType: error instanceof Error ? error.name : "UnknownError",
    }));
    return jsonResponse({ error: "language_provider_unavailable" }, 503);
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    return handleRequest(
      request,
      env.LANGUAGE_AUTH_SECRET,
      async (model, input) => env.AI.run(model, input),
    );
  },
} satisfies ExportedHandler<Env>;

export { CONTEXT_WINDOW_TOKENS, MAX_BODY_BYTES, MODEL };
