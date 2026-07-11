"""Canonical extraction schema for EQD structured products
(FCN — Fixed Coupon Note, BEN — Bonus Enhanced Note, and autocallable
variants with knock-out / knock-in features).

Every field carries a description that is embedded verbatim into the LLM
prompt, so improving a description here immediately improves extraction.
"""

TERM_SHEET_FIELDS = {
    # --- identification -----------------------------------------------------
    "product_type":        "Product type. One of: FCN (Fixed Coupon Note), BEN (Bonus Enhanced Note), ELN, Autocallable, Phoenix. Infer from the title and coupon/payoff language.",
    "issuer":              "Issuer of the note (the entity issuing the security).",
    "counterparty":        "The counterparty / dealer who sent the term sheet. Will appear masked as [CPTY_x]; return the mask token as-is.",
    "isin":                "ISIN of the note if stated, else null.",

    # --- dates ----------------------------------------------------------------
    "trade_date":          "Trade date in YYYY-MM-DD.",
    "initial_fixing_date": "Initial fixing / strike date in YYYY-MM-DD.",
    "issue_date":          "Issue / settlement date in YYYY-MM-DD.",
    "final_fixing_date":   "Final fixing / final valuation date in YYYY-MM-DD.",
    "maturity_date":       "Maturity / redemption date in YYYY-MM-DD.",

    # --- economics --------------------------------------------------------------
    "notional_amount":     "Notional amount as a plain number without separators (e.g. 1000000).",
    "notional_currency":   "Notional currency ISO code (USD, SGD, HKD, EUR ...).",
    "denomination":        "Denomination / minimum trading size as a plain number, else null.",
    "coupon_rate_pa":      "Coupon rate per annum as a percentage number (e.g. 8.5 means 8.5% p.a.).",
    "coupon_frequency":    "Coupon payment frequency: Monthly, Quarterly, Semi-Annually, Annually, or At Maturity.",
    "strike_pct":          "Strike level as percent of initial fixing (e.g. 80 means 80%).",

    # --- underlyings ------------------------------------------------------------
    "underlyings":         "JSON array of underlying shares/indices. Each item: {name, ticker, exchange, initial_price, strike_price}. Use null for unknown members.",
    "basket_type":         "Worst-of, Best-of, Single, or Basket.",

    # --- barriers ---------------------------------------------------------------
    "knock_in_barrier_pct":   "Knock-in (KI) barrier as percent of initial (e.g. 60 means 60%). Null if no KI.",
    "knock_in_observation":   "KI observation style: Daily Close, Continuous (American), At Expiry (European), or null.",
    "knock_out_barrier_pct":  "Knock-out / autocall (KO) barrier as percent of initial (e.g. 100). Null if no KO.",
    "knock_out_observation":  "KO observation frequency: Daily Close, Monthly, Quarterly, or null.",
    "autocall":               "true if the note has an autocall feature, else false.",
    "first_autocall_date":    "First possible autocall / KO observation date YYYY-MM-DD, or null (non-call period end).",

    # --- settlement ---------------------------------------------------------------
    "settlement_type":     "Cash, Physical, or Cash/Physical election.",
    "settlement_currency": "Settlement currency ISO code.",
    "business_day_convention": "e.g. Modified Following, Following, or null.",
    "calculation_agent":   "Calculation agent. May be masked as [CPTY_x]; return the token as-is.",
    "governing_law":       "Governing law if stated, else null.",
}

REQUIRED_FIELDS = [
    "product_type", "trade_date", "maturity_date",
    "notional_amount", "notional_currency",
    "coupon_rate_pa", "strike_pct", "underlyings",
]

# Fields whose value may legitimately contain a mask token and must be
# restored from the local mask map before display / booking.
MASKABLE_FIELDS = ["counterparty", "issuer", "calculation_agent"]
