"""Murex publisher (phase 2 stub).

Maps the approved extraction into a Murex-friendly trade payload and queues
it. The actual transport (MxML exchange / Murex REST booking API) is a
later phase; the queue table decouples review/approval from booking so the
connector can be added without touching this application.
"""
from datetime import datetime, timezone

from ..db.models import PublishRecord

PRODUCT_TYPOLOGY = {
    "FCN": "EQD_FIXED_COUPON_NOTE",
    "BEN": "EQD_BONUS_ENHANCED_NOTE",
    "ELN": "EQD_EQUITY_LINKED_NOTE",
    "Autocallable": "EQD_AUTOCALLABLE",
    "Phoenix": "EQD_PHOENIX_AUTOCALL",
}


def build_murex_payload(extraction) -> dict:
    f = extraction.fields
    return {
        "header": {
            "sourceSystem": "TERMSHEET_PARSER",
            "externalRef": f"TSP-{extraction.id}",
            "typology": PRODUCT_TYPOLOGY.get(f.get("product_type"), "EQD_STRUCTURED_NOTE"),
            "counterparty": f.get("counterparty"),
            "tradeDate": f.get("trade_date"),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        },
        "economics": {
            "notional": f.get("notional_amount"),
            "currency": f.get("notional_currency"),
            "couponRatePct": f.get("coupon_rate_pa"),
            "couponFrequency": f.get("coupon_frequency"),
            "strikePct": f.get("strike_pct"),
            "knockInPct": f.get("knock_in_barrier_pct"),
            "knockInObservation": f.get("knock_in_observation"),
            "knockOutPct": f.get("knock_out_barrier_pct"),
            "knockOutObservation": f.get("knock_out_observation"),
            "autocall": f.get("autocall"),
            "firstAutocallDate": f.get("first_autocall_date"),
            "basketType": f.get("basket_type"),
            "underlyings": f.get("underlyings"),
        },
        "settlement": {
            "issueDate": f.get("issue_date"),
            "finalFixingDate": f.get("final_fixing_date"),
            "maturityDate": f.get("maturity_date"),
            "settlementType": f.get("settlement_type"),
            "settlementCurrency": f.get("settlement_currency") or f.get("notional_currency"),
        },
    }


def queue_for_murex(db, extraction) -> PublishRecord:
    record = PublishRecord(extraction_id=extraction.id,
                           payload=build_murex_payload(extraction))
    db.add(record)
    return record
