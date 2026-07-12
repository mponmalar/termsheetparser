"""LLM client — routes prompts to one of four interchangeable providers,
selected by TSP_LLM_PROVIDER (see config.py):

  gateway     The bank's internal Bedrock gateway URL (HTTP + API key,
              Anthropic messages-API shape).

  bedrock_key Direct AWS Bedrock REST API using a long-term Bedrock API key
              (generated in AWS Console → Bedrock → API keys). No IAM/SigV4
              needed. Uses the Converse REST endpoint:
                POST https://bedrock-runtime.{region}.amazonaws.com
                     /model/{modelId}/converse
              Set BEDROCK_API_KEY to the long-term key value.

  bedrock     Direct AWS Bedrock via boto3 (SigV4 / IAM credential chain).
              Needs BEDROCK_REGION + AWS IAM credentials (env keys,
              AWS_PROFILE, ~/.aws/credentials, or instance role).

  mock        Deterministic offline extractor (dev / CI).

  auto        bedrock_key if BEDROCK_API_KEY+BEDROCK_REGION set,
              gateway if BEDROCK_GATEWAY_URL set,
              bedrock if BEDROCK_REGION set (IAM credentials assumed),
              else mock.

IMPORTANT: only *masked* text ever reaches this module.
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

VALID_PROVIDERS = ("gateway", "bedrock_key", "bedrock", "mock", "auto")


def resolve_provider(setting: str = None,
                     gateway_url: str = None,
                     api_key: str = None,
                     region: str = None) -> str:
    setting   = (LLM_PROVIDER      if setting     is None else setting).strip().lower()
    gateway_url = BEDROCK_GATEWAY_URL if gateway_url is None else gateway_url
    api_key   = BEDROCK_API_KEY    if api_key     is None else api_key
    region    = BEDROCK_REGION     if region      is None else region

    if setting not in VALID_PROVIDERS:
        raise ValueError(
            f"TSP_LLM_PROVIDER={setting!r} is invalid; expected one of {VALID_PROVIDERS}")

    if setting != "auto":
        if setting == "gateway" and not gateway_url:
            raise ValueError("TSP_LLM_PROVIDER=gateway but BEDROCK_GATEWAY_URL is not set")
        if setting == "bedrock_key" and not api_key:
            raise ValueError("TSP_LLM_PROVIDER=bedrock_key but BEDROCK_API_KEY is not set")
        if setting == "bedrock_key" and not region:
            raise ValueError("TSP_LLM_PROVIDER=bedrock_key but BEDROCK_REGION is not set")
        if setting == "bedrock" and not region:
            raise ValueError("TSP_LLM_PROVIDER=bedrock but BEDROCK_REGION is not set")
        return setting

    # auto resolution — order of preference:
    # 1. Bedrock long-term API key (simplest, no IAM setup)
    if api_key and region:
        return "bedrock_key"
    # 2. Bank gateway (HTTP + its own key)
    if gateway_url:
        return "gateway"
    # 3. Direct boto3 / IAM
    if region:
        return "bedrock"
    # 4. Offline mock
    return "mock"


def llm_mode() -> str:
    return resolve_provider()


# --------------------------------------------------------- provider: gateway
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
    if isinstance(data.get("content"), list):
        return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
    return data.get("completion") or data.get("output") or json.dumps(data)


# ------------------------------------------------- provider: bedrock_key
def _call_bedrock_key(prompt: str) -> str:
    """AWS Bedrock long-term API key → REST Converse endpoint, no SigV4."""
    base = (BEDROCK_ENDPOINT_URL.rstrip("/")
            if BEDROCK_ENDPOINT_URL
            else f"https://bedrock-runtime.{BEDROCK_REGION}.amazonaws.com")
    url = f"{base}/model/{BEDROCK_MODEL_ID}/converse"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BEDROCK_API_KEY}",
    }
    body = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": LLM_MAX_TOKENS, "temperature": 0.0},
    }
    with httpx.Client(timeout=BEDROCK_TIMEOUT_SECONDS) as client:
        resp = client.post(url, headers=headers, json=body)
        if not resp.is_success:
            raise RuntimeError(
                f"Bedrock API key call failed {resp.status_code}: {resp.text[:400]}")
        data = resp.json()
    return parse_converse_response(data)


# ------------------------------------------------- provider: bedrock (boto3)
_bedrock_client = None


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        try:
            import boto3
            from botocore.config import Config as BotoConfig
        except ImportError as exc:
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
    blocks = (data.get("output", {}).get("message", {}) or {}).get("content", [])
    text = "".join(b.get("text", "") for b in blocks if "text" in b)
    if not text:
        raise ValueError(f"Empty Converse response: {json.dumps(data)[:200]}")
    return text


def _call_bedrock_direct(prompt: str) -> str:
    client = _get_bedrock_client()
    resp = client.converse(
        modelId=BEDROCK_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": LLM_MAX_TOKENS, "temperature": 0.0},
    )
    return parse_converse_response(resp)


_PROVIDER_FNS = {
    "gateway":     _call_gateway,
    "bedrock_key": _call_bedrock_key,
    "bedrock":     _call_bedrock_direct,
    "mock":        mock_llm.complete,
}


def complete(prompt: str) -> str:
    provider = resolve_provider()
    log.debug("LLM call via provider=%s model=%s", provider, BEDROCK_MODEL_ID)
    return _PROVIDER_FNS[provider](prompt)


def parse_json_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in LLM response: {text[:200]}")
    return json.loads(text[start:end + 1])
