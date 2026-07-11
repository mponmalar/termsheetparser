"""LLM client — routes prompts to the bank's Bedrock gateway URL, or to the
deterministic MockLLM when no gateway is configured.

Contract with the gateway (Anthropic messages-API shape, which Bedrock's
Claude models and most bank LLM gateways expose):

    POST {BEDROCK_GATEWAY_URL}
    Headers: {BEDROCK_AUTH_HEADER}: Bearer {BEDROCK_API_KEY}
    Body: {"model": ..., "max_tokens": ..., "messages":[{"role":"user","content": prompt}]}

If your gateway wraps Bedrock's `invoke-model` instead, only
`_call_gateway` needs adjusting.

IMPORTANT: only *masked* text ever reaches this module. The MaskingAgent
runs strictly before the ExtractionAgent in the graph, and the raw text is
never placed in the prompt.
"""
import json
import logging

import httpx

from ..config import (BEDROCK_API_KEY, BEDROCK_AUTH_HEADER,
                      BEDROCK_GATEWAY_URL, BEDROCK_MODEL_ID,
                      BEDROCK_TIMEOUT_SECONDS, LLM_MAX_TOKENS)
from . import mock_llm

log = logging.getLogger("tsp.llm")


def llm_mode() -> str:
    return "bedrock" if BEDROCK_GATEWAY_URL else "mock"


def _call_gateway(prompt: str) -> str:
    headers = {"Content-Type": "application/json"}
    if BEDROCK_API_KEY:
        headers[BEDROCK_AUTH_HEADER] = f"Bearer {BEDROCK_API_KEY}"
    body = {
        "model": BEDROCK_MODEL_ID,
        "max_tokens": LLM_MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    with httpx.Client(timeout=BEDROCK_TIMEOUT_SECONDS) as client:
        resp = client.post(BEDROCK_GATEWAY_URL, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
    # messages API: {"content":[{"type":"text","text": ...}]}
    if isinstance(data.get("content"), list):
        return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
    # some gateways: {"completion": "..."} or {"output": "..."}
    return data.get("completion") or data.get("output") or json.dumps(data)


def complete(prompt: str) -> str:
    if BEDROCK_GATEWAY_URL:
        return _call_gateway(prompt)
    return mock_llm.complete(prompt)


def parse_json_response(text: str) -> dict:
    """LLMs sometimes wrap JSON in prose or code fences; recover robustly."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in LLM response: {text[:200]}")
    return json.loads(text[start:end + 1])
