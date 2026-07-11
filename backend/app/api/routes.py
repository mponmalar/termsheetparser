"""REST API consumed by the sales front end.

Flow:  POST /documents (upload) → agents run → GET /documents/{id}
       PATCH /extractions/{id}/fields (manual edit → lesson recorded)
       POST /extractions/{id}/approve → queued for Murex
"""
import shutil
import uuid
from pathlib import Path

from fastapi import (APIRouter, BackgroundTasks, Depends, HTTPException,
                     UploadFile)
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.graph import run_pipeline
from ..agents.memory import record_correction_lesson
from ..config import UPLOAD_DIR
from ..db.database import get_session
from ..db.models import (AgentRun, Correction, Document, Extraction, Lesson,
                         PublishRecord)
from ..schemas import TERM_SHEET_FIELDS
from ..services.llm_client import llm_mode
from ..services.murex import queue_for_murex

router = APIRouter(prefix="/api")

ALLOWED_SUFFIXES = {".pdf", ".docx", ".doc", ".txt"}


# ---------------------------------------------------------------- documents
@router.post("/documents")
async def upload_document(file: UploadFile, background: BackgroundTasks,
                          db: Session = Depends(get_session)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Unsupported file type '{suffix}'. "
                                 f"Allowed: {sorted(ALLOWED_SUFFIXES)}")
    stored = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    with stored.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    doc = Document(filename=file.filename, stored_path=str(stored),
                   content_type=file.content_type)
    db.add(doc)
    db.commit()

    background.add_task(run_pipeline, doc.id, str(stored))
    return {"document_id": doc.id, "status": "PROCESSING",
            "message": "Agents are parsing the term sheet."}


@router.get("/documents")
def list_documents(db: Session = Depends(get_session)):
    docs = db.query(Document).order_by(Document.id.desc()).all()
    return [{
        "id": d.id, "filename": d.filename, "status": d.status,
        "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
        "extraction_id": d.extractions[-1].id if d.extractions else None,
    } for d in docs]


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_session)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    extraction = doc.extractions[-1] if doc.extractions else None
    return {
        "id": doc.id, "filename": doc.filename, "status": doc.status,
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        "masked_preview": (doc.masked_text or "")[:4000],
        "mask_token_count": len(doc.mask_map or {}),
        "agent_trace": [{
            "agent": r.agent, "summary": r.summary, "detail": r.detail,
            "at": r.started_at.isoformat() if r.started_at else None,
        } for r in doc.agent_runs],
        "extraction": _extraction_payload(extraction) if extraction else None,
    }


def _extraction_payload(e: Extraction) -> dict:
    return {
        "id": e.id, "fields": e.fields, "field_meta": e.field_meta or {},
        "field_descriptions": TERM_SHEET_FIELDS,
        "critic_iterations": e.critic_iterations,
        "critic_notes": e.critic_notes or [],
        "lessons_used": e.lessons_used or [],
        "llm_mode": e.llm_mode,
        "approved": e.approved, "approved_by": e.approved_by,
        "approved_at": e.approved_at.isoformat() if e.approved_at else None,
    }


# --------------------------------------------------------------- extraction
class FieldEdits(BaseModel):
    edits: dict          # {field_name: new_value}
    edited_by: str = "sales"


@router.patch("/extractions/{extraction_id}/fields")
def edit_fields(extraction_id: int, body: FieldEdits,
                db: Session = Depends(get_session)):
    """Manual correction from the GUI. Every edit is persisted as a
    Correction AND converted into a Lesson — this is the learning signal."""
    e = db.get(Extraction, extraction_id)
    if not e:
        raise HTTPException(404, "Extraction not found")
    if e.approved:
        raise HTTPException(409, "Extraction already approved; edits are locked.")

    doc = db.get(Document, e.document_id)
    fields = dict(e.fields)
    meta = dict(e.field_meta or {})
    lesson_ids = []

    for name, new_value in body.edits.items():
        if name not in TERM_SHEET_FIELDS:
            raise HTTPException(400, f"Unknown field '{name}'")
        old_value = fields.get(name)
        if old_value == new_value:
            continue
        db.add(Correction(extraction_id=e.id, field_name=name,
                          old_value=str(old_value), new_value=str(new_value),
                          corrected_by=body.edited_by))
        lesson_ids.append(record_correction_lesson(
            doc.masked_text or "", name, old_value, new_value, body.edited_by))
        fields[name] = new_value
        m = dict(meta.get(name, {}))
        m.update({"edited": True, "source": "manual"})
        meta[name] = m

    e.fields = fields
    e.field_meta = meta
    db.add(AgentRun(document_id=doc.id, agent="MemoryAgent",
                    summary=f"Recorded {len(lesson_ids)} lesson(s) from manual "
                            f"edits by {body.edited_by}: "
                            f"{', '.join(body.edits.keys())}.",
                    detail={"lesson_ids": lesson_ids}))
    db.commit()
    return {"extraction": _extraction_payload(e), "lessons_created": lesson_ids}


class Approval(BaseModel):
    approved_by: str = "sales"


@router.post("/extractions/{extraction_id}/approve")
def approve(extraction_id: int, body: Approval,
            db: Session = Depends(get_session)):
    from datetime import datetime, timezone
    e = db.get(Extraction, extraction_id)
    if not e:
        raise HTTPException(404, "Extraction not found")
    if e.approved:
        raise HTTPException(409, "Already approved.")

    e.approved = True
    e.approved_by = body.approved_by
    e.approved_at = datetime.now(timezone.utc)
    doc = db.get(Document, e.document_id)
    doc.status = "APPROVED"
    record = queue_for_murex(db, e)
    db.add(AgentRun(document_id=doc.id, agent="PublisherAgent",
                    summary=f"Approved by {body.approved_by}; trade payload "
                            f"queued for Murex.",
                    detail={"publish_record": True}))
    db.commit()
    return {"extraction_id": e.id, "publish_record_id": record.id,
            "murex_payload": record.payload, "status": "QUEUED_FOR_MUREX"}


@router.post("/documents/{doc_id}/reprocess")
def reprocess(doc_id: int, background: BackgroundTasks,
              db: Session = Depends(get_session)):
    """Re-run the agent graph — used after edits to demonstrate that the
    agents now apply the recorded lessons on the same/similar document."""
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    doc.status = "PROCESSING"
    db.commit()
    background.add_task(run_pipeline, doc.id, doc.stored_path)
    return {"document_id": doc.id, "status": "PROCESSING"}


# ------------------------------------------------------------------ learning
@router.get("/lessons")
def list_lessons(db: Session = Depends(get_session)):
    rows = db.query(Lesson).order_by(Lesson.id.desc()).limit(200).all()
    return [{
        "id": l.id, "field_name": l.field_name, "source": l.source,
        "wrong_value": l.wrong_value, "right_value": l.right_value,
        "lesson_text": l.lesson_text, "times_applied": l.times_applied,
        "superseded": l.superseded,
        "created_at": l.created_at.isoformat() if l.created_at else None,
    } for l in rows]


@router.get("/stats")
def stats(db: Session = Depends(get_session)):
    total_docs = db.query(Document).count()
    total_extractions = db.query(Extraction).count()
    total_corrections = db.query(Correction).count()
    active_lessons = db.query(Lesson).filter(Lesson.superseded == False).count()  # noqa: E712
    approved = db.query(Extraction).filter(Extraction.approved == True).count()  # noqa: E712
    queued = db.query(PublishRecord).count()
    fields_per_extraction = len(TERM_SHEET_FIELDS)
    denom = total_extractions * fields_per_extraction
    return {
        "llm_mode": llm_mode(),
        "documents": total_docs,
        "extractions": total_extractions,
        "corrections": total_corrections,
        "active_lessons": active_lessons,
        "approved": approved,
        "queued_for_murex": queued,
        "field_accuracy_pct": round(100 * (1 - total_corrections / denom), 2) if denom else None,
    }


@router.get("/publish-queue")
def publish_queue(db: Session = Depends(get_session)):
    rows = db.query(PublishRecord).order_by(PublishRecord.id.desc()).all()
    return [{
        "id": r.id, "extraction_id": r.extraction_id, "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "payload": r.payload,
    } for r in rows]
