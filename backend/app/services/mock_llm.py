"""MockLLM — deterministic term-sheet extractor used when no Bedrock
gateway is configured (local dev, CI, and this repo's test suite).

It emulates the real LLM contract exactly: takes the same prompt the
ExtractionAgent builds (masked text + lessons + optional critique) and
returns the same JSON schema, so the entire agent graph, critic loop,
learning loop, GUI and tests run end-to-end offline.

It also honours lessons: if a lesson states a field's correct value, the
mock applies the override — which lets the test suite prove that "agents
learn from manual edits" without a live model.
"""
import json
import re

# label/value separator: colon, pipe, or plain whitespace (PDF tables often
# render label and value with no punctuation at all)
SEP = r"\s*[:|]?\s*"
DATE_RE = r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}


def _norm_date(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if re.match(r"\d{4}-\d{2}-\d{2}$", raw):
        return raw
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", raw)
    if m:
        month = MONTHS.get(m.group(2).lower())
        if month:
            return f"{m.group(3)}-{month:02d}-{int(m.group(1)):02d}"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return raw


def _find(text: str, *patterns: str, flags=re.I | re.M) -> str | None:
    for p in patterns:
        m = re.search(p, text, flags)
        if m:
            return m.group(1).strip()
    return None


def _num(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw.replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def extract_fields(masked_text: str) -> dict:
    t = masked_text

    title_zone = "\n".join(t.splitlines()[:12])
    product_type = None
    if re.search(r"fixed coupon note|\bFCN\b", title_zone, re.I):
        product_type = "FCN"
    elif re.search(r"bonus enhanced note|\bBEN\b", title_zone, re.I):
        product_type = "BEN"
    elif re.search(r"phoenix", title_zone, re.I):
        product_type = "Phoenix"
    elif re.search(r"autocall", title_zone, re.I):
        product_type = "Autocallable"
    elif re.search(r"equity[- ]linked note|\bELN\b", title_zone, re.I):
        product_type = "ELN"

    issuer = _find(t, r"^Issuer" + SEP + r"(\S.+)$")
    counterparty = _find(t, r"^(?:Counterparty|Dealer|Distributor|Arranger)" + SEP + r"(\S.+)$")
    if not counterparty:
        m = re.search(r"\[CPTY_\d+\]", t)
        counterparty = m.group(0) if m else None

    trade_date = _norm_date(_find(t, r"^Trade Date" + SEP + DATE_RE))
    initial_fixing = _norm_date(_find(t, r"^(?:Initial Fixing Date|Strike Date|Initial Valuation Date)" + SEP + DATE_RE))
    issue_date = _norm_date(_find(t, r"^(?:Issue Date|Settlement Date)" + SEP + DATE_RE))
    final_fixing = _norm_date(_find(t, r"^(?:Final Fixing Date|Final Valuation Date|Valuation Date)" + SEP + DATE_RE))
    maturity = _norm_date(_find(t, r"^(?:Maturity Date|Redemption Date)" + SEP + DATE_RE))

    cur_amt = _find(t, r"^(?:Notional(?: Amount)?|Aggregate Nominal Amount|Issue Size)" + SEP + r"([A-Z]{3}\s*[\d,]+(?:\.\d+)?)")
    notional_amount, notional_currency = None, None
    if cur_amt:
        m = re.match(r"([A-Z]{3})\s*([\d,]+(?:\.\d+)?)", cur_amt)
        if m:
            notional_currency, notional_amount = m.group(1), _num(m.group(2))

    denomination = _num(_find(t, r"^(?:Denomination|Specified Denomination|Minimum Trading Size)" + SEP + r"(?:[A-Z]{3}\s*)?([\d,]+)"))
    coupon = _num(_find(t, r"^(?:Coupon(?: Rate)?|Interest Rate)\b.*?([\d.]+)\s*%"))
    coupon_freq = _find(t, r"^(?:Coupon Frequency|Coupon Payment(?: Dates?| Frequency)?|Interest Payment)" + SEP + r"(Monthly|Quarterly|Semi-?Annually|Annually|At Maturity)")
    strike = _num(_find(t, r"^Strike(?: Level| Price| Percentage)?\b.*?([\d.]+)\s*%"))

    ki = _num(_find(t, r"^(?:Knock[- ]?In(?: Barrier| Level| Price)?|KI(?: Barrier)?|Kick[- ]?in Level|Barrier Level)\b.*?([\d.]+)\s*%"))
    ki_obs = _find(t, r"^(?:Knock[- ]?In Observation|KI Observation|Barrier Observation|Barrier Event Determination)" + SEP + r"(\S.+)$")
    ko = _num(_find(t, r"^(?:Knock[- ]?Out(?: Barrier| Level| Price)?|KO(?: Barrier)?|Autocall (?:Barrier|Level|Trigger)|Early Redemption (?:Level|Trigger))\b.*?([\d.]+)\s*%"))
    ko_obs = _find(t, r"^(?:Knock[- ]?Out Observation|KO Observation|Autocall Observation(?: Frequency| Dates)?)" + SEP + r"(\S.+)$")
    autocall = bool(re.search(r"autocall|auto-call|early redemption event|knock[- ]?out event", t, re.I))
    first_ac = _norm_date(_find(t, r"^(?:First (?:Autocall|Call|KO Observation) Date|Non[- ]?Call Period(?: End)?)" + SEP + DATE_RE))

    settlement_type = _find(t, r"^Settlement(?: Type| Method)?" + SEP + r"(Cash(?:\s*/\s*Physical)?(?:\s+or\s+Physical)?|Physical)")
    settlement_ccy = _find(t, r"^Settlement Currency" + SEP + r"([A-Z]{3})\b")
    bdc = _find(t, r"^Business Day Convention" + SEP + r"(\S.+)$")
    calc_agent = _find(t, r"^Calculation Agent" + SEP + r"(\S.+)$")
    law = _find(t, r"^Governing Law" + SEP + r"(\S.+)$")
    isin = _find(t, r"^ISIN" + SEP + r"([A-Z]{2}[A-Z0-9]{9}\d)")

    basket_type = None
    m = re.search(r"^Basket Type" + SEP + r"(Worst-?Of|Best-?Of|Single|Basket)", t, re.I | re.M)
    if m:
        basket_type = m.group(1).title().replace("of", "of")
        basket_type = {"Worst-Of": "Worst-of", "Worstof": "Worst-of",
                       "Best-Of": "Best-of"}.get(basket_type, basket_type)
    elif re.search(r"worst[- ]of|worst performing", t, re.I):
        basket_type = "Worst-of"
    elif re.search(r"best[- ]of", t, re.I):
        basket_type = "Best-of"

    # Underlyings: table rows like "Alphabet Inc | GOOGL UW | NASDAQ | 175.50 | 140.40"
    underlyings = []
    for m in re.finditer(
            r"^([A-Z][\w.&' ()-]{2,40}?)\s*\|\s*([A-Z0-9./ ]{1,15})\s*\|\s*([A-Za-z ]{2,20})\s*\|\s*([\d,.]+)\s*\|\s*([\d,.]+)\s*$",
            t, re.M):
        name = m.group(1).strip()
        if name.lower() in ("underlying", "underlying shares", "name", "share"):
            continue
        underlyings.append({
            "name": name,
            "ticker": m.group(2).strip(),
            "exchange": m.group(3).strip(),
            "initial_price": _num(m.group(4)),
            "strike_price": _num(m.group(5)),
        })
    if not underlyings:
        for m in re.finditer(r"^Underlying(?:s| Shares?)?" + SEP + r"(\S.+?)\s*\(([A-Z0-9. ]{1,15})\)", t, re.M):
            underlyings.append({"name": m.group(1).strip(), "ticker": m.group(2).strip(),
                                "exchange": None, "initial_price": None, "strike_price": None})
    if not basket_type:
        basket_type = "Single" if len(underlyings) == 1 else ("Worst-of" if underlyings else None)

    return {
        "product_type": product_type,
        "issuer": issuer,
        "counterparty": counterparty,
        "isin": isin,
        "trade_date": trade_date,
        "initial_fixing_date": initial_fixing,
        "issue_date": issue_date,
        "final_fixing_date": final_fixing,
        "maturity_date": maturity,
        "notional_amount": notional_amount,
        "notional_currency": notional_currency,
        "denomination": denomination,
        "coupon_rate_pa": coupon,
        "coupon_frequency": coupon_freq,
        "strike_pct": strike,
        "underlyings": underlyings,
        "basket_type": basket_type,
        "knock_in_barrier_pct": ki,
        "knock_in_observation": ki_obs,
        "knock_out_barrier_pct": ko,
        "knock_out_observation": ko_obs,
        "autocall": autocall,
        "first_autocall_date": first_ac,
        "settlement_type": settlement_type,
        "settlement_currency": settlement_ccy,
        "business_day_convention": bdc,
        "calculation_agent": calc_agent,
        "governing_law": law,
    }


LESSON_OVERRIDE_RE = re.compile(
    r"field '(?P<field>\w+)' should be '(?P<value>[^']*)'", re.I)


def apply_lessons(fields: dict, lessons_block: str) -> tuple[dict, list[str]]:
    """Honour explicit lesson overrides so the offline learning loop is
    observably effective in tests and demos."""
    applied = []
    for m in LESSON_OVERRIDE_RE.finditer(lessons_block or ""):
        field, value = m.group("field"), m.group("value")
        if field in fields:
            try:
                cast = json.loads(value)
            except (ValueError, TypeError):
                cast = value
            fields[field] = cast
            if field not in applied:
                applied.append(field)
    return fields, applied


def complete(prompt: str) -> str:
    """Mimic the messages-API text completion: return a JSON string."""
    doc = prompt.split("<TERM_SHEET>", 1)[-1].split("</TERM_SHEET>", 1)[0]
    lessons = ""
    if "<LESSONS>" in prompt:
        lessons = prompt.split("<LESSONS>", 1)[1].split("</LESSONS>", 1)[0]
    fields = extract_fields(doc)
    fields, applied = apply_lessons(fields, lessons)
    return json.dumps({"fields": fields, "lesson_overrides_applied": applied})
