"""RAG over the "Procedure_admission" document.

Indexing: extract text -> chunks (~800 chars, paragraph boundaries) -> embeddings (nomic-embed-text) -> DB.
Retrieval: cosine similarity (+ a small lexical bonus), top-k chunks returned to the agent.
"""

import logging
import re
from pathlib import Path

import numpy as np
from django.conf import settings
from django.db import transaction

from ..models import DocumentChunk
from . import llm
from .text import stem, tokens

logger = logging.getLogger("admissions")

SUPPORTED = {".pdf", ".docx", ".txt", ".md"}
CHUNK_SIZE = 800


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        text = "\n\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
        # Word bullets are extracted as private-use symbols (e.g. U+F0B7): turn them into "-"
        return re.sub(r"[•▪●]\s*", "- ", text)
    if suffix == ".docx":
        import docx

        document = docx.Document(str(path))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        return "\n".join(parts)
    return path.read_text(encoding="utf-8", errors="ignore")


def chunk_text(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n(?=\s*[-•*●]|\s*\d+[.)])", text) if p.strip()]
    chunks, current = [], ""
    for p in paragraphs:
        if current and len(current) + len(p) > CHUNK_SIZE:
            chunks.append(current)
            current = ""
        current = f"{current}\n{p}".strip()
    if current:
        chunks.append(current)
    return chunks


@transaction.atomic
def ingest_directory(directory: Path | None = None) -> dict:
    directory = Path(directory or settings.DOCUMENTS_DIR)
    files = sorted(p for p in directory.glob("*") if p.suffix.lower() in SUPPORTED)
    report = {"files": [], "chunks": 0}
    DocumentChunk.objects.all().delete()
    for path in files:
        chunks = chunk_text(extract_text(path))
        vectors = llm.embed(chunks) if chunks else []
        DocumentChunk.objects.bulk_create(
            DocumentChunk(source=path.name, chunk_index=i, text=c, embedding=vectors[i],
                          embedding_model=settings.LLM_EMBED_MODEL)
            for i, c in enumerate(chunks)
        )
        report["files"].append({"name": path.name, "chunks": len(chunks)})
        report["chunks"] += len(chunks)
    return report


def retrieve(query: str, k: int | None = None) -> list[dict]:
    chunks = list(DocumentChunk.objects.exclude(embedding=None))
    if not chunks:
        return []
    q = np.array(llm.embed([query])[0], dtype=np.float32)
    m = np.array([c.embedding for c in chunks], dtype=np.float32)
    cosines = (m @ q) / (np.linalg.norm(m, axis=1) * np.linalg.norm(q) + 1e-9)
    q_stems = {stem(t) for t in tokens(query)}
    scored = []
    for c, cos in zip(chunks, cosines):
        lexical = len(q_stems & {stem(t) for t in tokens(c.text)}) / len(q_stems) if q_stems else 0
        scored.append({"chunk": c, "score": round(0.8 * float(cos) + 0.2 * lexical, 3)})
    scored.sort(key=lambda s: s["score"], reverse=True)
    return [s for s in scored[: k or settings.RAG_TOP_K] if s["score"] >= settings.RAG_MIN_SCORE]
