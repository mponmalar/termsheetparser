"""LLM client — routes prompts to one of three interchangeable providers,
selected by TSP_LLM_PROVIDER (see config.py):

  gateway   The bank's internal Bedrock gateway URL (HTTP + API key).
            Contract: Anthropic messages-API shape —
                POST {BEDROCK_GATEWAY_URL}
                Headers: {BEDROCK_AUTH_HEADER}: Bearer {BEDROCK_API_KEY}
                Body: {"model", "max_tokens", "messages":[{"role":"user",...}]}
            If your gateway wraps Bedrock invoke-model instead, only
            _call_gateway needs adjusting.

  bedrock   Direct AWS Bedrock via boto3 (bedrock-runtime Converse API).
            Auth is the standard AWS credential chain (env keys, AWS_PROFILE,
            ~/.aws, instance/ECS role) — SigV4, no API key in this app.
            Region from BEDROCK_REGION / AWS_REGION; optional VPC endpoint
            via BEDROCK_ENDPOINT_URL.

  mock      Deterministic offline extractor with the identical prompt/JSON
            contract, used for dev and CI.

  auto      gateway if BEDROCK_GATEWAY_URL is set, else bedrock if an AWS
            region is configured, else mock.

IMPORTANT: only *masked* text ever reaches this module. The MaskingAgent
runs strictly before the ExtractionAgent in the graph, and the raw text is
never placed in the prompt — this holds for every provider.
"""
import json
import logging

import httpx

from ..config import (BEDROCK_API_KEY, BEDROCK_AUTH_HEADER,
                      BEDROCK_ENDPOINT_URL, BEDROCK_GATEWAY_URL,
                      BEDROCK_MODEL_ID, BEDROCK_REGION,
                      BEDROCK_TIMEOUT_SECONDS, LLM_MAX_TOKENS, LLM_PROVIDER)
from . import mock_llm

log = logging.getLogger("tsp.llm")

VALID_PROVIDERS = ("gateway", "bedrock", "mock", "auto")


def resolve_provider(setting: str = None,
                     gateway_url: str = None,
                     region: str = None) -> str:
    """Turn the configured setting into a concrete provider name.

    Explicit settings win; 'auto' prefers the gateway (the safer, bank-side
    path), then direct Bedrock if an AWS region is configured, else mock.
    """
    setting = (LLM_PROVIDER if setting is None else setting).strip().lower()
    gateway_url = BEDROCK_GATEWAY_URL if gateway_url is None else gateway_url
    region = BEDROCK_REGION if region is None else region

    if setting not in VALID_PROVIDERS:
        raise ValueError(
            f"TSP_LLM_PROVIDER={setting!r} is invalid; expected one of {VALID_PROVIDERS}")
    if setting != "auto":
        if setting == "gateway" and not gateway_url:
            raise ValueError("TSP_LLM_PROVIDER=gateway but BEDROCK_GATEWAY_URL is not set")
        if setting == "bedrock" and not region:
            raise ValueError(
                "TSP_LLM_PROVIDER=bedrock but no region configured "
                "(set BEDROCK_REGION or AWS_REGION)")
        return setting
    if gateway_url:
        return "gateway"
    if region:
        return "bedrock"
    return "mock"


def llm_mode() -> str:
    """Concrete provider in use — surfaced in the GUI, stats and audit rows."""
    return resolve_provider()


# --------------------------------------------------------------- providers --
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


_bedrock_client = None


def _get_bedrock_client():
    """Lazily build (and cache) the boto3 bedrock-runtime client.

    boto3 is an optional dependency: it is only imported when the direct
    provider is actually selected, so gateway/mock deployments don't need it.
    """
    global _bedrock_client
    if _bedrock_client is None:
        try:
            import boto3
            from botocore.config import Config as BotoConfig
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "TSP_LLM_PROVIDER=bedrock requires boto3 — pip install boto3") from exc
        kwargs = {
            "region_name": BEDROCK_REGION,
            "config": BotoConfig(
                read_timeout=BEDROCK_TIMEOUT_SECONDS,
                connect_timeout=min(BEDROCK_TIMEOUT_SECONDS, 15),
                retries={"max_attempts": 3, "mode": "adaptive"},
            ),
        }
        if BEDROCK_ENDPOINT_URL:
            kwargs["endpoint_url"] = BEDROCK_ENDPOINT_URL
        _bedrock_client = boto3.client("bedrock-runtime", **kwargs)
    return _bedrock_client


def parse_converse_response(data: dict) -> str:
    """Extract the text from a Bedrock Converse API response."""
    blocks = (data.get("output", {}).get("message", {}) or {}).get("content", [])
    text = "".join(b.get("text", "") for b in blocks if "text" in b)
    if not text:
        raise ValueError(f"Empty Converse response: {json.dumps(data)[:200]}")
    return text


def _call_bedrock_direct(prompt: str) -> str:
    """Direct AWS call using the model-agnostic Converse API, so switching
    BEDROCK_MODEL_ID between Anthropic/Titan/etc. needs no code change."""
    client = _get_bedrock_client()
    resp = client.converse(
        modelId=BEDROCK_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": LLM_MAX_TOKENS, "temperature": 0.0},
    )
    return parse_converse_response(resp)


_PROVIDER_FNS = {
    "gateway": _call_gateway,
    "bedrock": _call_bedrock_direct,
    "mock": mock_llm.complete,
}


def complete(prompt: str) -> str:
    provider = resolve_provider()
    log.debug("LLM call via provider=%s model=%s", provider, BEDROCK_MODEL_ID)
    return _PROVIDER_FNS[provider](prompt)


# ------------------------------------------------------------------ parsing --
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
