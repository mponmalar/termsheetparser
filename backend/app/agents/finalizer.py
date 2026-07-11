"""FinalizerAgent — the last node. Runs strictly inside the bank network:

1. Restores masked tokens ([CPTY_1] → real counterparty) in the extracted
   values, using the local mask_map that never left the box.
2. Persists the Extraction with per-field provenance and the full critic
   conversation, and flips the Document to PENDING_REVIEW for sales.
"""
from ..db.database import SessionLocal
from ..db.models import Document, Extraction
from ..schemas import MASKABLE_FIELDS
from ..services.llm_client import llm_mode
from .masking import unmask_value


def finalize_node(state: dict) -> dict:
    fields = dict(state.get("fields", {}))
    mask_map = state.get("mask_map", {})
    restored = []
    for f in MASKABLE_FIELDS:
        if f in fields and isinstance(fields[f], str):
            new = unmask_value(fields[f], mask_map)
            if new != fields[f]:
                restored.append(f)
                fields[f] = new

    db = SessionLocal()
    try:
        extraction = Extraction(
            document_id=state["document_id"],
            fields=fields,
            field_meta=state.get("field_meta", {}),
            critic_iterations=state.get("iteration", 1),
            critic_notes=state.get("critic_notes", []),
            lessons_used=[l["id"] for l in state.get("lessons", [])],
            llm_mode=llm_mode(),
        )
        db.add(extraction)
        doc = db.get(Document, state["document_id"])
        doc.status = "PENDING_REVIEW"
        db.commit()
        extraction_id = extraction.id
    finally:
        db.close()

    return {
        "fields": fields,
        "trace": [{"agent": "FinalizerAgent",
                   "summary": f"Unmasked {len(restored)} field(s) locally and saved "
                              f"extraction #{extraction_id}. Awaiting sales review.",
                   "detail": {"extraction_id": extraction_id, "restored_fields": restored}}],
    }
