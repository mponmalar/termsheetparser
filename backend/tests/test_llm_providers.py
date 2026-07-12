"""Tests for the switchable LLM provider layer (gateway / direct Bedrock / mock)."""
import pytest

from backend.app.services import llm_client


# ------------------------------------------------------- provider resolution
def test_auto_prefers_gateway_when_url_set():
    assert llm_client.resolve_provider("auto", gateway_url="https://gw", region="ap-southeast-1") == "gateway"


def test_auto_falls_back_to_direct_bedrock_when_region_set():
    assert llm_client.resolve_provider("auto", gateway_url="", region="ap-southeast-1") == "bedrock"


def test_auto_falls_back_to_mock_when_nothing_configured():
    assert llm_client.resolve_provider("auto", gateway_url="", region="") == "mock"


def test_explicit_provider_wins_over_auto_detection():
    # both configured, user forces direct bedrock
    assert llm_client.resolve_provider("bedrock", gateway_url="https://gw", region="ap-southeast-1") == "bedrock"
    # both configured, user forces mock (e.g. UAT without LLM spend)
    assert llm_client.resolve_provider("mock", gateway_url="https://gw", region="ap-southeast-1") == "mock"


def test_explicit_provider_with_missing_config_fails_loudly():
    with pytest.raises(ValueError, match="BEDROCK_GATEWAY_URL"):
        llm_client.resolve_provider("gateway", gateway_url="", region="")
    with pytest.raises(ValueError, match="BEDROCK_REGION"):
        llm_client.resolve_provider("bedrock", gateway_url="", region="")
    with pytest.raises(ValueError, match="invalid"):
        llm_client.resolve_provider("banana", gateway_url="", region="")
    with pytest.raises(ValueError, match="BEDROCK_API_KEY"):
        llm_client.resolve_provider("bedrock_key", gateway_url="", api_key="", region="ap-southeast-1")


# ------------------------------------------------- direct Bedrock (Converse)
def test_parse_converse_response_extracts_text():
    resp = {"output": {"message": {"role": "assistant",
                                   "content": [{"text": '{"product_type": "FCN"}'}]}},
            "stopReason": "end_turn"}
    assert llm_client.parse_converse_response(resp) == '{"product_type": "FCN"}'


def test_parse_converse_response_rejects_empty():
    with pytest.raises(ValueError):
        llm_client.parse_converse_response({"output": {"message": {"content": []}}})


def test_direct_bedrock_call_uses_converse_api(monkeypatch):
    """complete() routed to the bedrock provider must call Converse with the
    configured model and pass the (masked) prompt through untouched."""
    calls = {}

    class FakeBedrockRuntime:
        def converse(self, **kwargs):
            calls.update(kwargs)
            return {"output": {"message": {"content": [{"text": '{"ok": true}'}]}}}

    monkeypatch.setattr(llm_client, "_get_bedrock_client", lambda: FakeBedrockRuntime())
    monkeypatch.setattr(llm_client, "resolve_provider", lambda *a, **k: "bedrock")

    out = llm_client.complete("MASKED PROMPT [CPTY_1]")
    assert out == '{"ok": true}'
    assert calls["modelId"] == llm_client.BEDROCK_MODEL_ID
    assert calls["messages"] == [{"role": "user", "content": [{"text": "MASKED PROMPT [CPTY_1]"}]}]
    assert calls["inferenceConfig"]["temperature"] == 0.0


def test_default_environment_resolves_to_mock():
    # In the CI/dev environment nothing is configured -> offline mock.
    assert llm_client.llm_mode() == "mock"
