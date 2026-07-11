"""MaskingAgent — removes sensitive data BEFORE any text approaches the LLM.

The bank's constraint: counterparty identities and personal/account data must
not cross the office network boundary. This agent runs entirely locally:

* Counterparty / dealer legal names  -> [CPTY_1], [CPTY_2] ...
* Email addresses                    -> [EMAIL_1] ...
* Phone numbers                      -> [PHONE_1] ...
* Account / IBAN-like numbers        -> [ACCT_1] ...
* Person names on contact lines      -> [PERSON_1] ...
* SWIFT/BIC codes                    -> [BIC_1] ...

A reversible `mask_map` (token -> original) is stored ONLY in the local DB
and used by the FinalizerAgent to restore values after the LLM responds.
Underlying tickers, barriers, dates and economics are deliberately NOT
masked — they are the payload the LLM must extract.
"""
import re
from ..config import KNOWN_COUNTERPARTIES

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<![\d.%])(?:\+\d{1,3}[\s-]?)?(?:\(\d{1,4}\)[\s-]?)?\d{4}[\s-]\d{4}(?:[\s-]\d{2,4})?(?![\d.%])")
ACCT_RE = re.compile(r"\b(?:A/?C|Acct|Account|IBAN)[\s#:.]*([A-Z]{0,2}\d{8,24})\b", re.I)
BIC_RE = re.compile(r"\b(?:SWIFT|BIC)[\s#:.]*([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b", re.I)
CONTACT_LINE_RE = re.compile(
    r"^(?P<label>\s*(?:Contact|Sales(?:\s+Contact|person)?|Trader|Attn|Attention|Prepared by|Marketing Contact)\s*[:\-]\s*)(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})",
    re.M,
)


class MaskingResult(dict):
    @property
    def masked_text(self): return self["masked_text"]
    @property
    def mask_map(self): return self["mask_map"]


def mask_text(text: str, extra_counterparties: list[str] | None = None) -> MaskingResult:
    mask_map: dict[str, str] = {}
    counters = {"CPTY": 0, "EMAIL": 0, "PHONE": 0, "ACCT": 0, "PERSON": 0, "BIC": 0}
    value_to_token: dict[str, str] = {}

    def token_for(kind: str, value: str) -> str:
        key = (kind, value.lower())
        if key in value_to_token:
            return value_to_token[key]
        counters[kind] += 1
        tok = f"[{kind}_{counters[kind]}]"
        mask_map[tok] = value
        value_to_token[key] = tok
        return tok

    masked = text

    # 1. Structured PII first (emails, BICs, accounts, phones) so that
    #    counterparty-name masking cannot corrupt these patterns from inside
    #    (e.g. the "citi" in amanda.lee@citi-sales.example.com or CITISGSG).
    masked = EMAIL_RE.sub(lambda m: token_for("EMAIL", m.group(0)), masked)
    masked = BIC_RE.sub(lambda m: m.group(0).replace(m.group(1), token_for("BIC", m.group(1))), masked)
    masked = ACCT_RE.sub(lambda m: m.group(0).replace(m.group(1), token_for("ACCT", m.group(1))), masked)
    masked = PHONE_RE.sub(lambda m: token_for("PHONE", m.group(0)), masked)

    # 2. Counterparty legal names — longest names first so "Standard
    #    Chartered Bank" wins over "Standard Chartered". Word boundaries
    #    prevent matches inside longer tokens.
    names = sorted(set(KNOWN_COUNTERPARTIES + (extra_counterparties or [])),
                   key=len, reverse=True)
    for name in names:
        pattern = re.compile(
            r"\b" + re.escape(name)
            + r"(\s+(?:Global Markets|Chase|Financial Company|Securities))*"
            + r"(\s+(?:AG|N\.A\.|PLC|LLC|Ltd\.?|Limited|Bank|Holdings(?:\s+Inc\.?)?|Inc\.?|SA|SE|plc|Pte\.?(?:\s+Ltd\.?)?|\(Singapore\)(?:\s+Limited)?|\(Asia Pacific\)(?:\s+Limited)?|Singapore Branch|Hong Kong Branch|London Branch))*\b",
            re.IGNORECASE)

        def repl(m, _name=name):
            return token_for("CPTY", m.group(0))

        masked = pattern.sub(repl, masked)

    # 3. Person names on labelled contact lines
    masked = CONTACT_LINE_RE.sub(
        lambda m: m.group("label") + token_for("PERSON", m.group("name")), masked)

    return MaskingResult(masked_text=masked, mask_map=mask_map)


def unmask_value(value, mask_map: dict[str, str]):
    """Restore mask tokens inside an extracted value (local only)."""
    if not isinstance(value, str):
        return value
    for tok, original in mask_map.items():
        if tok in value:
            value = value.replace(tok, original)
    return value


def masking_node(state: dict) -> dict:
    result = mask_text(state["raw_text"])
    kinds = {}
    for tok in result.mask_map:
        kind = tok.strip("[]").rsplit("_", 1)[0]
        kinds[kind] = kinds.get(kind, 0) + 1
    summary = ("Masked " + ", ".join(f"{v} {k.lower()} token(s)" for k, v in kinds.items())
               if kinds else "No sensitive entities detected.")
    return {
        "masked_text": result.masked_text,
        "mask_map": result.mask_map,
        "trace": [{"agent": "MaskingAgent", "summary": summary,
                   "detail": {"token_count": len(result.mask_map)}}],
    }
