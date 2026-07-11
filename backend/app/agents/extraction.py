"""ExtractionAgent — builds the prompt (schema + lessons + critic feedback +
masked document) and calls the LLM through the gateway.

On re-entry from the CriticAgent, the previous attempt and the critique are
included, so the two agents effectively hold a conversation until the critic
is satisfied or the iteration budget is exhausted.
"""
import json

from ..schemas import TERM_SHEET_FIELDS
from ..services import llm_client

SYSTEM_PREAMBLE = """You are an expert equity-derivatives middle-office analyst.
Extract the trade economics from the structured-product term sheet below
(FCN / BEN / autocallable notes with knock-in and knock-out features).

Rules:
- Respond with ONLY a JSON object: {"fields": {...}} — no prose, no code fences.
- Use exactly the field names given. Use null when a field is absent.
- Dates must be YYYY-MM-DD. Percentages as plain numbers (80 not "80%").
- Sensitive entities are masked as tokens like [CPTY_1]; return those tokens
  verbatim — never guess the real name behind a token.
"""


def build_prompt(masked_text: str, lessons_block: str,
                 critique: str = "", previous_fields: dict | None = None) -> str:
    schema_lines = "\n".join(f"- {name}: {desc}" for name, desc in TERM_SHEET_FIELDS.items())
    parts = [SYSTEM_PREAMBLE, "FIELDS TO EXTRACT:\n" + schema_lines]
    if lessons_block:
        parts.append(
            "<LESSONS>\nLessons learned from past sales corrections on similar "
            "documents. Apply them where relevant:\n" + lessons_block + "\n</LESSONS>")
    if critique and previous_fields is not None:
        parts.append(
            "<CRITIQUE>\nYour previous attempt was reviewed by a validation "
            "agent and rejected. Previous attempt:\n"
            + json.dumps(previous_fields, default=str)
            + "\nReviewer feedback — fix these issues:\n" + critique + "\n</CRITIQUE>")
    parts.append("<TERM_SHEET>\n" + masked_text + "\n</TERM_SHEET>")
    return "\n\n".join(parts)


def extraction_node(state: dict) -> dict:
    iteration = state.get("iteration", 0) + 1
    prompt = build_prompt(
        state["masked_text"],
        state.get("lessons_block", ""),
        critique=state.get("critique", ""),
        previous_fields=state.get("fields") if state.get("critique") else None,
    )
    raw = llm_client.complete(prompt)
    parsed = llm_client.parse_json_response(raw)
    fields = parsed.get("fields", parsed)
    overrides = parsed.get("lesson_overrides_applied", [])

    field_meta = {}
    for name in fields:
        field_meta[name] = {
            "source": "lesson" if name in overrides else "llm",
            "edited": False,
        }

    filled = sum(1 for v in fields.values() if v not in (None, "", []))
    summary = (f"Attempt {iteration}: extracted {filled}/{len(fields)} fields "
               f"via {llm_client.llm_mode()} LLM"
               + (f", applied lesson overrides on {overrides}" if overrides else "")
               + (" (re-run after critic feedback)" if state.get("critique") else "") + ".")
    return {
        "fields": fields,
        "field_meta": field_meta,
        "iteration": iteration,
        "critique": "",
        "trace": [{"agent": "ExtractionAgent", "summary": summary,
                   "detail": {"iteration": iteration, "llm_mode": llm_client.llm_mode()}}],
    }
