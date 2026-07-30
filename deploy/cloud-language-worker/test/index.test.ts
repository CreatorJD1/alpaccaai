import { describe, expect, it, vi } from "vitest";

import {
  CONTEXT_WINDOW_TOKENS,
  MAX_BODY_BYTES,
  MODEL,
  handleRequest,
} from "../src/index";
import type { ModelRunner } from "../src/index";

const SECRET = "test-only-language-secret-000000000000000000";

function completion(content = "Hello from the cloud."): ChatCompletionsOutput {
  return {
    id: "completion-test",
    object: "chat.completion",
    created: 1,
    model: MODEL,
    choices: [{
      index: 0,
      message: { role: "assistant", content, refusal: null },
      finish_reason: "stop",
      logprobs: null,
    }],
  };
}

function post(body: Record<string, unknown>, secret = SECRET): Request {
  return new Request("https://language.example/v1/chat/completions", {
    method: "POST",
    headers: {
      authorization: `Bearer ${secret}`,
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
}

describe("Alpecca cloud language boundary", () => {
  it("publishes a content-free health contract", async () => {
    const runner = vi.fn<ModelRunner>();
    const response = await handleRequest(
      new Request("https://language.example/healthz"),
      SECRET,
      runner,
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      service: "alpecca-cloud-language",
      version: 1,
      ready: true,
      model: MODEL,
      contextWindowTokens: CONTEXT_WINDOW_TOKENS,
      modality: "text-only",
    });
    expect(runner).not.toHaveBeenCalled();
  });

  it("rejects missing credentials before reading or running a prompt", async () => {
    const runner = vi.fn<ModelRunner>();
    const response = await handleRequest(
      post({ model: MODEL, messages: [{ role: "user", content: "secret" }] }, "wrong"),
      SECRET,
      runner,
    );
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "unauthorized" });
    expect(runner).not.toHaveBeenCalled();
  });

  it("accepts a 30k-class text context and returns OpenAI chat shape", async () => {
    const content = "shared-context-token ".repeat(30_000);
    const runner = vi.fn<ModelRunner>(async () => completion("continuous reply"));
    const response = await handleRequest(
      post({
        model: MODEL,
        messages: [
          { role: "system", content: "You are Alpecca." },
          { role: "user", content },
        ],
        max_tokens: 9_999,
        temperature: 9,
        chat_template_kwargs: { enable_thinking: true },
      }),
      SECRET,
      runner,
    );
    expect(response.status).toBe(200);
    expect((await response.json() as ChatCompletionsOutput).choices[0]?.message.content)
      .toBe("continuous reply");
    expect(runner).toHaveBeenCalledOnce();
    const [, input] = runner.mock.calls[0] ?? [];
    expect(input?.max_tokens).toBe(2_048);
    expect(input?.temperature).toBe(2);
    expect(input?.chat_template_kwargs).toEqual({ enable_thinking: false });
  });

  it("preserves bounded function tools and tool results", async () => {
    const runner = vi.fn<ModelRunner>(async () => completion());
    const response = await handleRequest(
      post({
        model: MODEL,
        messages: [
          { role: "user", content: "Recall it." },
          {
            role: "assistant",
            content: null,
            tool_calls: [{
              id: "call-1",
              type: "function",
              function: { name: "memory_search", arguments: "{}" },
            }],
          },
          { role: "tool", tool_call_id: "call-1", content: "result" },
        ],
        tools: [{
          type: "function",
          function: {
            name: "memory_search",
            description: "Search shared memory",
            parameters: { type: "object", properties: {} },
          },
        }],
        tool_choice: "auto",
      }),
      SECRET,
      runner,
    );
    expect(response.status).toBe(200);
    const [, input] = runner.mock.calls[0] ?? [];
    expect(input?.tools).toHaveLength(1);
    expect(input?.messages).toHaveLength(3);
  });

  it("rejects model substitution and multimodal prompt parts", async () => {
    const runner = vi.fn<ModelRunner>(async () => completion());
    const wrongModel = await handleRequest(
      post({ model: "other", messages: [{ role: "user", content: "hello" }] }),
      SECRET,
      runner,
    );
    expect(wrongModel.status).toBe(400);
    expect(await wrongModel.json()).toEqual({ error: "model_not_allowed" });

    const image = await handleRequest(
      post({
        model: MODEL,
        messages: [{ role: "user", content: [{ type: "image_url", image_url: { url: "x" } }] }],
      }),
      SECRET,
      runner,
    );
    expect(image.status).toBe(400);
    expect(await image.json()).toEqual({ error: "message_invalid" });
    expect(runner).not.toHaveBeenCalled();
  });

  it("rejects a declared oversized request before model execution", async () => {
    const runner = vi.fn<ModelRunner>(async () => completion());
    const request = post({ model: MODEL, messages: [{ role: "user", content: "hello" }] });
    request.headers.set("content-length", String(MAX_BODY_BYTES + 1));
    const response = await handleRequest(request, SECRET, runner);
    expect(response.status).toBe(413);
    expect(await response.json()).toEqual({ error: "request_too_large" });
    expect(runner).not.toHaveBeenCalled();
  });
});
