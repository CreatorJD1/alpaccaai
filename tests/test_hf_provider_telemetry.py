from __future__ import annotations

from types import SimpleNamespace

from alpecca import mind as mind_mod


def _response(*, prompt_tokens: int, completion_tokens: int, finish_reason: str = "stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="hosted response"),
            finish_reason=finish_reason,
        )],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def _bare_llm(primary, fallback=None):
    llm = object.__new__(mind_mod._LLM)
    llm._backend = "hf"
    llm._hf = primary
    llm._hf_fallback = fallback
    llm._hf_retry_after = 0.0
    llm._hf_last_error = ""
    llm._last_call = {}
    return llm


def test_hf_response_records_content_free_provider_usage(monkeypatch) -> None:
    class Hosted:
        def chat_completion(self, **_kwargs):
            return _response(prompt_tokens=27_321, completion_tokens=41)

    monkeypatch.setattr(mind_mod, "CLOUD_NUM_CTX", 30_000)
    monkeypatch.setattr(mind_mod, "HF_MODEL", "Qwen/Qwen3.5-9B")
    llm = _bare_llm(Hosted())

    assert llm._generate_hf("system content", "user content") == "hosted response"

    use = llm.last_call()
    route = use["route"]
    assert use["backend"] == "hf"
    assert route["served_route"] == "cloud"
    assert route["provider_requested_num_ctx"] == 30_000
    assert route["provider_response_received"] is True
    assert route["provider_prompt_tokens"] == 27_321
    assert route["provider_output_tokens"] == 41
    assert route["provider_done"] is True
    assert route["provider_done_reason"] == "stop"
    assert "system content" not in str(route)
    assert "user content" not in str(route)


def test_hosted_fallback_records_usage_under_the_cloud_route(monkeypatch) -> None:
    class PaymentRequired(RuntimeError):
        response = SimpleNamespace(status_code=402)

    class Depleted:
        def chat_completion(self, **_kwargs):
            raise PaymentRequired("credits depleted")

    class Fallback:
        def chat_completion(self, **_kwargs):
            return _response(
                prompt_tokens=28_765,
                completion_tokens=29,
                finish_reason="length",
            )

    monkeypatch.setattr(mind_mod, "CLOUD_NUM_CTX", 30_000)
    monkeypatch.setattr(mind_mod, "HF_MODEL", "Qwen/Qwen3.5-9B")
    monkeypatch.setattr(
        mind_mod,
        "HF_FALLBACK_MODEL",
        "@cf/google/gemma-4-26b-a4b-it",
    )
    llm = _bare_llm(Depleted(), Fallback())

    assert llm._generate_hf("system", "user") == "hosted response"

    use = llm.last_call()
    route = use["route"]
    assert use["backend"] == "hosted-fallback"
    assert use["model"] == "@cf/google/gemma-4-26b-a4b-it"
    assert route["served_route"] == "cloud"
    assert route["provider_requested_num_ctx"] == 30_000
    assert route["provider_prompt_tokens"] == 28_765
    assert route["provider_output_tokens"] == 29
    assert route["provider_done"] is True
    assert route["provider_done_reason"] == "length"
