"""Shared state flowing through the LangGraph pipeline."""
import operator
from typing import Annotated, Any, TypedDict


class PipelineState(TypedDict, total=False):
    # inputs
    document_id: int
    file_path: str

    # ingestion
    raw_text: str

    # masking
    masked_text: str
    mask_map: dict[str, str]

    # memory
    lessons: list[dict]          # [{id, lesson_text, score}]
    lessons_block: str           # formatted for the prompt

    # extraction / critic loop
    fields: dict[str, Any]
    field_meta: dict[str, dict]
    critique: str                # feedback fed back into re-extraction
    critic_notes: Annotated[list, operator.add]   # conversation history
    iteration: int
    extraction_ok: bool

    # audit trail (each node appends)
    trace: Annotated[list, operator.add]
