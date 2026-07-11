"""Agent orchestration with LangGraph.

    upload
      │
      ▼
 ┌───────────┐   ┌──────────┐   ┌─────────┐   ┌───────────┐
 │ Ingestion │──▶│ Masking  │──▶│ Memory  │──▶│ Extraction│◀──┐
 └───────────┘   └──────────┘   └─────────┘   └─────┬─────┘   │ critique
                                                    ▼         │ (≤ N loops)
                                              ┌──────────┐    │
                                              │  Critic  │────┘
                                              └────┬─────┘
                                            accepted│
                                                    ▼
                                              ┌───────────┐
                                              │ Finalizer │──▶ PENDING_REVIEW
                                              └───────────┘

The Extraction ⇄ Critic edge is a conditional loop: the critic writes
feedback into `state.critique`, the extractor re-runs with that feedback in
its prompt. Every step appends to `state.trace`, which is persisted as
AgentRun rows so the GUI can replay the agent conversation.
"""
import time

from langgraph.graph import END, START, StateGraph

from ..db.database import SessionLocal
from ..db.models import AgentRun, Document
from .critic import critic_node, critic_router
from .extraction import extraction_node
from .finalizer import finalize_node
from .ingestion import ingestion_node
from .masking import masking_node
from .memory import memory_node
from .state import PipelineState


def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("ingest", ingestion_node)
    g.add_node("mask", masking_node)
    g.add_node("memory", memory_node)
    g.add_node("extract", extraction_node)
    g.add_node("critic", critic_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "mask")
    g.add_edge("mask", "memory")
    g.add_edge("memory", "extract")
    g.add_edge("extract", "critic")
    g.add_conditional_edges("critic", critic_router,
                            {"extract": "extract", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile()


PIPELINE = build_graph()


def run_pipeline(document_id: int, file_path: str) -> dict:
    """Execute the full agent graph for one document and persist the audit
    trail. Returns the final state."""
    started = time.time()
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        doc.status = "PROCESSING"
        db.commit()
    finally:
        db.close()

    try:
        final = PIPELINE.invoke({"document_id": document_id, "file_path": file_path})
    except Exception as exc:
        db = SessionLocal()
        try:
            doc = db.get(Document, document_id)
            doc.status = "FAILED"
            db.add(AgentRun(document_id=document_id, agent="Pipeline",
                            summary=f"Pipeline failed: {exc}"))
            db.commit()
        finally:
            db.close()
        raise

    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        doc.raw_text = final.get("raw_text")
        doc.masked_text = final.get("masked_text")
        doc.mask_map = final.get("mask_map")
        for step in final.get("trace", []):
            db.add(AgentRun(document_id=document_id, agent=step["agent"],
                            summary=step["summary"], detail=step.get("detail", {}),
                            duration_ms=0))
        db.add(AgentRun(document_id=document_id, agent="Pipeline",
                        summary=f"Completed in {time.time() - started:.2f}s "
                                f"after {final.get('iteration', 1)} extraction attempt(s).",
                        detail={"iterations": final.get("iteration", 1)}))
        db.commit()
    finally:
        db.close()
    return final
