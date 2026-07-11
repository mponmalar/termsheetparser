"""MemoryAgent — the self-learning half of the system.

Retrieval (before extraction):
    Pull every non-superseded Lesson from the DB, rank by similarity to the
    incoming masked document, and format the top-k as a <LESSONS> block that
    the ExtractionAgent injects into the LLM prompt. This is how a manual
    edit made on Monday changes the extraction produced on Tuesday.

Recording (after a manual edit — called from the API layer):
    `record_correction_lesson` converts a sales edit into a durable Lesson
    with the masked document fingerprint, so similar future documents recall
    it. Older lessons for the same (field, similar context) are superseded
    rather than deleted, keeping the full learning history auditable.
"""
from ..config import LESSON_MIN_SIMILARITY, LESSON_TOP_K
from ..db.database import SessionLocal
from ..db.models import Lesson
from ..services.similarity import rank_lessons


def _fingerprint(masked_text: str, chars: int = 1200) -> str:
    return masked_text[:chars]


def load_ranked_lessons(masked_text: str) -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(Lesson).filter(Lesson.superseded == False).all()  # noqa: E712
        lessons = [{
            "id": r.id, "field_name": r.field_name,
            "document_fingerprint": r.document_fingerprint,
            "lesson_text": r.lesson_text, "source": r.source,
        } for r in rows]
        ranked = rank_lessons(_fingerprint(masked_text), lessons,
                              top_k=LESSON_TOP_K, min_similarity=LESSON_MIN_SIMILARITY)
        out = []
        for lesson, score in ranked:
            lesson["score"] = round(score, 4)
            out.append(lesson)
        # bump usage counters
        ids = [l["id"] for l in out]
        if ids:
            db.query(Lesson).filter(Lesson.id.in_(ids)).update(
                {Lesson.times_applied: Lesson.times_applied + 1},
                synchronize_session=False)
            db.commit()
        return out
    finally:
        db.close()


def format_lessons_block(lessons: list[dict]) -> str:
    if not lessons:
        return ""
    lines = []
    for i, l in enumerate(lessons, 1):
        lines.append(f"{i}. [{l.get('field_name') or 'general'}] {l['lesson_text']}")
    return "\n".join(lines)


def record_correction_lesson(masked_text: str, field_name: str,
                             wrong_value, right_value,
                             corrected_by: str = "sales") -> int:
    """Turn a manual GUI edit into a lesson. Returns the lesson id."""
    lesson_text = (
        f"On a previous similar term sheet, the extraction for field "
        f"'{field_name}' was '{wrong_value}' but the sales desk corrected it "
        f"to '{right_value}'. For documents like this, field '{field_name}' "
        f"should be '{right_value}' — re-check the source text carefully for "
        f"this field before answering."
    )
    db = SessionLocal()
    try:
        fp = _fingerprint(masked_text)
        # supersede older lessons for the same field with a near-identical fingerprint
        db.query(Lesson).filter(
            Lesson.field_name == field_name,
            Lesson.document_fingerprint == fp,
            Lesson.superseded == False,  # noqa: E712
        ).update({Lesson.superseded: True}, synchronize_session=False)

        lesson = Lesson(source="correction", field_name=field_name,
                        document_fingerprint=fp,
                        wrong_value=str(wrong_value), right_value=str(right_value),
                        lesson_text=lesson_text)
        db.add(lesson)
        db.commit()
        return lesson.id
    finally:
        db.close()


def memory_node(state: dict) -> dict:
    lessons = load_ranked_lessons(state["masked_text"])
    block = format_lessons_block(lessons)
    summary = (f"Recalled {len(lessons)} lesson(s) from past corrections "
               f"(best match {lessons[0]['score']:.2f})." if lessons
               else "No relevant past lessons yet — first document of its kind.")
    return {
        "lessons": lessons,
        "lessons_block": block,
        "trace": [{"agent": "MemoryAgent", "summary": summary,
                   "detail": {"lesson_ids": [l["id"] for l in lessons]}}],
    }
