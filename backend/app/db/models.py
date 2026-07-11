"""Database schema.

Design notes
------------
* SQLite by default so the demo is zero-setup; the same models run on
  PostgreSQL. In production we recommend PostgreSQL + pgvector so the
  lesson store can use true vector similarity (see docs/ARCHITECTURE.md).
* The learning loop is anchored on `Lesson`: every manual edit by sales
  produces one lesson row that the MemoryAgent retrieves for future
  extractions. Lessons are never deleted, only superseded, so the audit
  trail of "what the agents learned and when" is complete.
"""
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey,
                        Integer, String, Text)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


class Document(Base):
    """One uploaded term sheet (PDF or Word)."""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    filename = Column(String(512), nullable=False)
    stored_path = Column(String(1024), nullable=False)
    content_type = Column(String(128))
    uploaded_by = Column(String(128), default="sales")
    uploaded_at = Column(DateTime, default=utcnow)

    raw_text = Column(Text)            # full parsed text (stays inside the bank)
    masked_text = Column(Text)         # what was actually sent to the LLM
    mask_map = Column(JSON)            # token -> original value (never leaves the box)

    status = Column(String(32), default="UPLOADED")
    # UPLOADED -> PROCESSING -> PENDING_REVIEW -> APPROVED -> PUBLISHED | FAILED

    extractions = relationship("Extraction", back_populates="document",
                               order_by="Extraction.id")
    agent_runs = relationship("AgentRun", back_populates="document",
                              order_by="AgentRun.id")


class Extraction(Base):
    """One structured extraction produced by the agent graph for a document.

    `fields` is the canonical JSON of the term sheet economics. `field_meta`
    carries per-field provenance: confidence, whether a lesson influenced it,
    whether sales edited it.
    """
    __tablename__ = "extractions"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    created_at = Column(DateTime, default=utcnow)

    fields = Column(JSON, nullable=False)         # {field_name: value}
    field_meta = Column(JSON, default=dict)       # {field_name: {confidence, source, edited}}
    critic_iterations = Column(Integer, default=0)
    critic_notes = Column(JSON, default=list)     # critique history (agent conversation)
    lessons_used = Column(JSON, default=list)     # lesson ids injected into the prompt
    llm_mode = Column(String(32), default="mock") # "bedrock" | "mock"

    approved = Column(Boolean, default=False)
    approved_by = Column(String(128))
    approved_at = Column(DateTime)

    document = relationship("Document", back_populates="extractions")
    corrections = relationship("Correction", back_populates="extraction")


class Correction(Base):
    """A single manual field edit made by sales in the review GUI."""
    __tablename__ = "corrections"

    id = Column(Integer, primary_key=True)
    extraction_id = Column(Integer, ForeignKey("extractions.id"), nullable=False)
    field_name = Column(String(128), nullable=False)
    old_value = Column(Text)
    new_value = Column(Text)
    corrected_by = Column(String(128), default="sales")
    corrected_at = Column(DateTime, default=utcnow)

    extraction = relationship("Extraction", back_populates="corrections")


class Lesson(Base):
    """What the agents learn. One lesson per correction (or per critic
    insight worth remembering). The MemoryAgent retrieves the top-k lessons
    most similar to the incoming document and injects them into the
    extraction prompt as few-shot guidance.
    """
    __tablename__ = "lessons"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=utcnow)
    source = Column(String(32), default="correction")   # correction | critic | approval
    field_name = Column(String(128))
    document_fingerprint = Column(Text)   # masked text snippet used for similarity
    wrong_value = Column(Text)
    right_value = Column(Text)
    lesson_text = Column(Text, nullable=False)          # human/LLM-readable guidance
    times_applied = Column(Integer, default=0)
    superseded = Column(Boolean, default=False)


class AgentRun(Base):
    """Audit trail of the agent conversation for a document — every node
    step, its input summary, output summary and timing. Rendered in the GUI
    so sales can see the agents 'talking to each other'."""
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    agent = Column(String(64), nullable=False)
    started_at = Column(DateTime, default=utcnow)
    duration_ms = Column(Integer, default=0)
    summary = Column(Text)
    detail = Column(JSON, default=dict)

    document = relationship("Document", back_populates="agent_runs")


class PublishRecord(Base):
    """Approved trades queued for Murex. The Murex connector (later phase)
    drains this table and books via MxML / Murex REST."""
    __tablename__ = "publish_queue"

    id = Column(Integer, primary_key=True)
    extraction_id = Column(Integer, ForeignKey("extractions.id"), nullable=False)
    payload = Column(JSON, nullable=False)     # Murex-shaped trade payload
    status = Column(String(32), default="QUEUED")   # QUEUED -> SENT -> ACKED | ERROR
    created_at = Column(DateTime, default=utcnow)
    sent_at = Column(DateTime)
    murex_trade_id = Column(String(64))
    error = Column(Text)
