"""IngestionAgent — turns an uploaded PDF / Word file into clean text.

PDF   : pdfplumber (layout-aware, also pulls tables row-by-row)
DOCX  : python-docx (paragraphs + tables)
Fallback: raw bytes decoded as UTF-8 (for .txt term sheets in tests)
"""
from pathlib import Path

import pdfplumber
from docx import Document as DocxDocument


def _parse_pdf(path: Path) -> str:
    parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            parts.append(text)
            for table in page.extract_tables():
                for row in table:
                    cells = [c.strip() for c in row if c]
                    if cells:
                        parts.append(" | ".join(cells))
    return "\n".join(parts)


def _parse_docx(path: Path) -> str:
    doc = DocxDocument(path)
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def parse_document(path: str | Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix in (".docx", ".doc"):
        return _parse_docx(path)
    return path.read_text(encoding="utf-8", errors="replace")


def ingestion_node(state: dict) -> dict:
    """LangGraph node."""
    text = parse_document(state["file_path"])
    return {
        "raw_text": text,
        "trace": [{
            "agent": "IngestionAgent",
            "summary": f"Parsed {Path(state['file_path']).name}: "
                       f"{len(text)} chars, {text.count(chr(10)) + 1} lines.",
        }],
    }
