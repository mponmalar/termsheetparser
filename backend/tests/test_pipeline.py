"""End-to-end tests over the real sample term sheets in /samples.

Runs entirely offline via the MockLLM (BEDROCK_GATEWAY_URL unset), which
honours the exact same prompt contract as the Bedrock gateway.
"""
import os
import tempfile

os.environ["TSP_DATA_DIR"] = tempfile.mkdtemp(prefix="tsp_test_")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
client = TestClient(app)


def upload_and_wait(filename: str) -> dict:
    path = SAMPLES / filename
    with path.open("rb") as fh:
        resp = client.post("/api/documents", files={"file": (filename, fh)})
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["document_id"]
    # TestClient runs BackgroundTasks synchronously, so the pipeline is done.
    detail = client.get(f"/api/documents/{doc_id}").json()
    assert detail["status"] == "PENDING_REVIEW", detail["status"]
    return detail


# ------------------------------------------------------------------ masking
def test_masking_hides_counterparties_and_pii():
    detail = upload_and_wait("FCN_Citi_WorstOf_3Stock_USD.pdf")
    masked = detail["masked_preview"]
    assert "Citi" not in masked
    assert "amanda.lee" not in masked
    assert "6432 1188" not in masked
    assert "[CPTY_" in masked and "[EMAIL_" in masked
    assert detail["mask_token_count"] >= 4
    # economics must NOT be masked
    assert "9.20" in masked and "NVDA" in masked


# ----------------------------------------------------------------- pipeline
@pytest.mark.parametrize("filename,expect", [
    ("FCN_Citi_WorstOf_3Stock_USD.pdf",
     dict(product_type="FCN", notional_currency="USD", notional_amount=2000000,
          coupon_rate_pa=9.2, strike_pct=80.0, knock_in_barrier_pct=60.0,
          knock_out_barrier_pct=100.0, maturity_date="2027-07-13",
          n_underlyings=3, autocall=True)),
    ("BEN_UBS_WorstOf_2Stock_SGD.pdf",
     dict(product_type="BEN", notional_currency="SGD", notional_amount=1500000,
          coupon_rate_pa=6.8, strike_pct=100.0, knock_in_barrier_pct=75.0,
          maturity_date="2027-01-15", n_underlyings=2)),
    ("Phoenix_JPMorgan_Autocall_HKD.pdf",
     dict(product_type="Phoenix", notional_currency="HKD", notional_amount=8000000,
          coupon_rate_pa=11.5, knock_in_barrier_pct=55.0,
          knock_out_barrier_pct=100.0, n_underlyings=3, autocall=True)),
    ("FCN_StandardChartered_Single_TSLA_USD.docx",
     dict(product_type="FCN", notional_currency="USD", notional_amount=750000,
          coupon_rate_pa=12.75, strike_pct=85.0, knock_out_barrier_pct=103.0,
          n_underlyings=1)),
])
def test_extraction_end_to_end(filename, expect):
    detail = upload_and_wait(filename)
    fields = detail["extraction"]["fields"]
    n = expect.pop("n_underlyings")
    assert len(fields["underlyings"]) == n
    for key, want in expect.items():
        assert fields[key] == want, f"{filename}: {key}={fields[key]!r}, want {want!r}"
    # counterparty restored locally after unmasking
    assert "[CPTY_" not in str(fields.get("counterparty"))


def test_agent_trace_shows_all_agents():
    detail = upload_and_wait("BEN_UBS_WorstOf_2Stock_SGD.pdf")
    agents = {t["agent"] for t in detail["agent_trace"]}
    assert {"IngestionAgent", "MaskingAgent", "MemoryAgent",
            "ExtractionAgent", "CriticAgent", "FinalizerAgent"} <= agents


# ------------------------------------------------------------ learning loop
def test_manual_edit_creates_lesson_and_agents_learn():
    """The core requirement: sales edits a field -> a Lesson is stored ->
    re-processing the (similar) document applies the lesson automatically."""
    detail = upload_and_wait("FCN_Citi_WorstOf_3Stock_USD.pdf")
    ext = detail["extraction"]

    # 1. Sales corrects a field in the GUI
    resp = client.patch(f"/api/extractions/{ext['id']}/fields", json={
        "edits": {"coupon_frequency": "Quarterly"},
        "edited_by": "sales.demo",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["lessons_created"], "edit must create a lesson"
    assert body["extraction"]["fields"]["coupon_frequency"] == "Quarterly"
    assert body["extraction"]["field_meta"]["coupon_frequency"]["edited"] is True

    lessons = client.get("/api/lessons").json()
    assert any(l["field_name"] == "coupon_frequency" and not l["superseded"]
               for l in lessons)

    # 2. Re-process: MemoryAgent recalls the lesson, extraction now honours it
    doc_id = detail["id"]
    client.post(f"/api/documents/{doc_id}/reprocess")
    detail2 = client.get(f"/api/documents/{doc_id}").json()
    fields2 = detail2["extraction"]["fields"]
    assert fields2["coupon_frequency"] == "Quarterly", \
        "agents must apply the learned correction on the next run"
    assert detail2["extraction"]["lessons_used"], "lesson ids must be recorded"
    meta2 = detail2["extraction"]["field_meta"]
    assert meta2["coupon_frequency"]["source"] == "lesson"


# ----------------------------------------------------------- approve + Murex
def test_approve_queues_murex_payload():
    detail = upload_and_wait("FCN_StandardChartered_Single_TSLA_USD.docx")
    ext_id = detail["extraction"]["id"]
    resp = client.post(f"/api/extractions/{ext_id}/approve",
                       json={"approved_by": "sales.demo"})
    assert resp.status_code == 200
    payload = resp.json()["murex_payload"]
    assert payload["header"]["typology"] == "EQD_FIXED_COUPON_NOTE"
    assert payload["economics"]["notional"] == 750000
    assert payload["economics"]["currency"] == "USD"
    assert payload["settlement"]["maturityDate"] == "2027-04-16"

    # edits are locked after approval
    resp = client.patch(f"/api/extractions/{ext_id}/fields",
                        json={"edits": {"coupon_rate_pa": 1}})
    assert resp.status_code == 409

    queue = client.get("/api/publish-queue").json()
    assert any(q["extraction_id"] == ext_id and q["status"] == "QUEUED" for q in queue)


def test_stats_endpoint():
    stats = client.get("/api/stats").json()
    assert stats["llm_mode"] == "mock"
    assert stats["documents"] >= 1
