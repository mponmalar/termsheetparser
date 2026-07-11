"""Unit tests for the MaskingAgent and CriticAgent in isolation."""
import os
import tempfile

os.environ.setdefault("TSP_DATA_DIR", tempfile.mkdtemp(prefix="tsp_unit_"))

from backend.app.agents.critic import review_fields  # noqa: E402
from backend.app.agents.masking import mask_text, unmask_value  # noqa: E402


def test_mask_counterparty_and_roundtrip():
    text = ("Counterparty: UBS AG Singapore Branch\n"
            "Contact: John Tan\nEmail: john.tan@example.com\n"
            "Phone: +65 6888 1234\nSWIFT: UBSWSGSGXXX\n"
            "Coupon Rate: 8.00% p.a.")
    res = mask_text(text)
    assert "UBS" not in res.masked_text
    assert "john.tan@example.com" not in res.masked_text
    assert "6888 1234" not in res.masked_text
    assert "8.00%" in res.masked_text          # economics untouched
    # round trip
    tok = next(t for t in res.mask_map if t.startswith("[CPTY_"))
    assert "UBS" in unmask_value(tok, res.mask_map)


def test_mask_same_entity_same_token():
    text = "Issuer: Citigroup Global Markets\nCalculation Agent: Citigroup Global Markets"
    res = mask_text(text)
    toks = [t for t in res.mask_map if t.startswith("[CPTY_")]
    assert len(toks) == 1


GOOD = {
    "product_type": "FCN", "trade_date": "2026-07-06",
    "initial_fixing_date": "2026-07-06", "issue_date": "2026-07-13",
    "final_fixing_date": "2027-07-06", "maturity_date": "2027-07-13",
    "notional_amount": 2000000, "notional_currency": "USD",
    "coupon_rate_pa": 9.2, "strike_pct": 80,
    "knock_in_barrier_pct": 60, "knock_out_barrier_pct": 100,
    "autocall": True, "underlyings": [{"name": "NVIDIA Corp", "ticker": "NVDA"}],
}


def test_critic_accepts_valid_extraction():
    assert review_fields(GOOD) == []


def test_critic_flags_date_order_and_barriers():
    bad = dict(GOOD, maturity_date="2026-01-01",          # before trade date
               knock_in_barrier_pct=110,                  # KI above 100
               notional_currency="US DOLLAR")             # not ISO
    issues = review_fields(bad)
    text = " ".join(issues)
    assert "Date ordering" in text
    assert "knock_in_barrier_pct" in text
    assert "ISO" in text


def test_critic_flags_missing_required():
    issues = review_fields({"product_type": "FCN"})
    assert any("notional_amount" in i for i in issues)
    assert any("underlyings" in i for i in issues)
