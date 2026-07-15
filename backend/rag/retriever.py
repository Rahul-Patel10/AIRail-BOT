"""
rag/retriever.py — Vector Retrieval with Metadata Filtering and Threshold
=========================================================================
Orchestrates the full retrieval pipeline for a single query:

    ChromaDB vector search   (Phase 3: optional category filter)
            │
            ▼
    FlashRank re-ranking
            │
            ▼
    Similarity threshold     (Phase 7: drop low-confidence chunks)
            │
            ▼
    List[dict] with text, source, category, and scores
"""

from rag.loader import get_collection
from rag.reranker import rerank_documents
from rag.constants import (
    INITIAL_RETRIEVAL_COUNT,
    FINAL_TOP_K,
    RERANK_SCORE_THRESHOLD,
)


def search_faq(
    query: str,
    top_k: int = FINAL_TOP_K,
    metadata_filter: dict | None = None,
) -> list[dict]:
    """
    Retrieve and rerank FAQ chunks relevant to ``query``.

    Parameters
    ----------
    query : str
        The (possibly rewritten) search query.
    top_k : int
        Maximum number of results to return after reranking.
    metadata_filter : dict, optional
        ChromaDB ``where`` filter — e.g. ``{"category": "refund"}``.
        When None, the entire collection is searched (Phase 3 passthrough).

    Returns
    -------
    list[dict]
        Each item contains: text, source, category, chunk_index,
        chroma_score (1 − L2 distance), rerank_score, score.
        Empty list when nothing passes the similarity threshold.
    """
    collection = get_collection()
    if collection is None:
        return []

    # ── Step 1: Vector search ─────────────────────────────────────────────────
    query_kwargs: dict = {
        "query_texts": [query],
        "n_results": INITIAL_RETRIEVAL_COUNT,
        "include": ["documents", "metadatas", "distances"],
    }

    # Phase 3: narrow search to a specific category when the caller provides one
    if metadata_filter:
        query_kwargs["where"] = metadata_filter

    results = collection.query(**query_kwargs)

    documents  = results.get("documents",  [[]])[0]
    metadatas  = results.get("metadatas",  [[]])[0] or [{}] * len(documents)
    distances  = results.get("distances",  [[]])[0] or [None] * len(documents)

    if not documents:
        return []

    # Convert ChromaDB L2 distances → rough similarity score (0–1).
    # all-MiniLM-L6-v2 produces normalised vectors so L2 distance ≤ 2.
    candidates = [
        {
            "text":         doc,
            "source":       meta.get("source",      "unknown"),
            "category":     meta.get("category",    "general"),
            "chunk_index":  meta.get("chunk_index",  0),
            "chroma_score": round(1.0 - (dist / 2.0), 4) if dist is not None else 0.0,
        }
        for doc, meta, dist in zip(documents, metadatas, distances)
    ]

    # ── Step 2: FlashRank re-ranking ──────────────────────────────────────────
    reranked = rerank_documents(query, candidates, top_k)

    # ── Step 3: Similarity threshold (Phase 7) ────────────────────────────────
    # Drop chunks whose cross-encoder score is below the configured threshold.
    # This prevents the LLM from receiving low-confidence context and
    # hallucinating an answer from it.
    above_threshold = [
        doc for doc in reranked
        if doc.get("score", 0.0) >= RERANK_SCORE_THRESHOLD
    ]

    return above_threshold