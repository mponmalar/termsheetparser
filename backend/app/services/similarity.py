"""Similarity search over stored lessons.

Demo/default: TF-IDF + cosine (scikit-learn) — no model downloads, fully
offline, good enough for term-sheet dialects which are highly template-like.

Production: swap `rank_lessons` for a pgvector query using embeddings from
the bank's Bedrock gateway (Titan / Cohere embeddings). The interface is a
single function so the swap is one file.
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def rank_lessons(query_text: str, lessons: list[dict], top_k: int,
                 min_similarity: float = 0.0) -> list[tuple[dict, float]]:
    """Return [(lesson, score)] for the top_k lessons most similar to the
    incoming (masked) document text. Each lesson dict must contain
    'document_fingerprint' and 'lesson_text'."""
    if not lessons:
        return []
    corpus = [(l.get("document_fingerprint") or "") + " " + (l.get("lesson_text") or "")
              for l in lessons]
    try:
        vec = TfidfVectorizer(stop_words="english", max_features=5000)
        matrix = vec.fit_transform(corpus + [query_text])
    except ValueError:
        return []
    sims = cosine_similarity(matrix[-1], matrix[:-1]).ravel()
    order = sims.argsort()[::-1][:top_k]
    return [(lessons[i], float(sims[i])) for i in order if sims[i] >= min_similarity]
