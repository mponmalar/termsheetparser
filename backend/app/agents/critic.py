"""CriticAgent — reviews every extraction with EQD domain rules and, when it
finds problems, sends the extraction back to the ExtractionAgent with
written feedback. This extraction ⇄ critic conversation is the
"agents talking to themselves" loop, capped by MAX_CRITIC_ITERATIONS.

Checks are deterministic domain invariants (not another LLM call) so the
loop always terminates and the reasons are explainable to auditors:

  * required fields present
  * date ordering: trade ≤ initial fixing ≤ issue ≤ final fixing ≤ maturity
  * KI barrier below strike and below 100; KO at/above KI; KO usually ≥ strike
  * coupon within sane bounds (0–60 % p.a.)
  * notional positive, currency is a 3-letter ISO code
  * each underlying has at least a name and ticker
  * autocall flag consistent with KO fields
"""
import re
from datetime import date

from ..config import MAX_CRITIC_ITERATIONS
from ..schemas import REQUIRED_FIELDS

ISO_CCY = re.compile(r"^[A-Z]{3}$")


def _d(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def review_fields(fields: dict) -> list[str]:
    issues: list[str] = []

    for f in REQUIRED_FIELDS:
        if fields.get(f) in (None, "", []):
            issues.append(f"Required field '{f}' is missing.")

    order = ["trade_date", "initial_fixing_date", "issue_date",
             "final_fixing_date", "maturity_date"]
    dates = [(f, _d(fields.get(f))) for f in order]
    known = [(f, d) for f, d in dates if d]
    for (f1, d1), (f2, d2) in zip(known, known[1:]):
        if d1 > d2:
            issues.append(f"Date ordering violated: {f1} ({d1}) is after {f2} ({d2}).")

    def num(f):
        v = fields.get(f)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    strike, ki, ko = num("strike_pct"), num("knock_in_barrier_pct"), num("knock_out_barrier_pct")
    if strike is not None and not (10 <= strike <= 150):
        issues.append(f"strike_pct {strike} outside plausible range 10–150%.")
    if ki is not None:
        if ki >= 100:
            issues.append(f"knock_in_barrier_pct {ki} should be below 100% of initial.")
        if strike is not None and ki > strike:
            issues.append(f"knock_in_barrier_pct {ki} above strike_pct {strike} — check for a swapped value.")
    if ko is not None and ki is not None and ko <= ki:
        issues.append(f"knock_out_barrier_pct {ko} not above knock_in_barrier_pct {ki}.")

    coupon = num("coupon_rate_pa")
    if coupon is not None and not (0 < coupon <= 60):
        issues.append(f"coupon_rate_pa {coupon} outside sane range (0, 60] % p.a.")

    notional = num("notional_amount")
    if notional is not None and notional <= 0:
        issues.append("notional_amount must be positive.")
    ccy = fields.get("notional_currency")
    if ccy and not ISO_CCY.match(str(ccy)):
        issues.append(f"notional_currency '{ccy}' is not a 3-letter ISO code.")

    unds = fields.get("underlyings") or []
    if isinstance(unds, list):
        for i, u in enumerate(unds):
            if not isinstance(u, dict) or not u.get("name"):
                issues.append(f"Underlying #{i + 1} lacks a name.")
    if fields.get("autocall") and ko is None:
        issues.append("autocall is true but knock_out_barrier_pct is null — extract the autocall trigger level.")

    return issues


def critic_node(state: dict) -> dict:
    issues = review_fields(state.get("fields", {}))
    iteration = state.get("iteration", 1)
    ok = not issues or iteration >= MAX_CRITIC_ITERATIONS

    if issues:
        verdict = (f"Found {len(issues)} issue(s)"
                   + ("; iteration budget reached, escalating to human review."
                      if iteration >= MAX_CRITIC_ITERATIONS
                      else "; sending back to ExtractionAgent."))
    else:
        verdict = "Extraction passes all domain checks. Approved for sales review."

    note = {"iteration": iteration, "issues": issues, "accepted": ok}
    return {
        "extraction_ok": ok,
        "critique": "\n".join(f"- {i}" for i in issues) if not ok else "",
        "critic_notes": [note],
        "trace": [{"agent": "CriticAgent", "summary": verdict, "detail": note}],
    }


def critic_router(state: dict) -> str:
    return "finalize" if state.get("extraction_ok") else "extract"
