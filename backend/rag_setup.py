"""
rag_setup.py — Build a local ChromaDB vector store from FAQ data
================================================================
Usage:
    python backend/rag_setup.py
    python backend/rag_setup.py --test
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from bootstrap import ensure_faq_index, CHROMA_PATH, FAQ_COLLECTION


def query_test(query: str = "What is the refund for a Tatkal ticket?"):
    import chromadb
    from flashrank import Ranker, RerankRequest

    print(f"\n[RAG] Test query: '{query}'")

    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_collection(name=FAQ_COLLECTION)
    results = collection.query(
        query_texts=[query],
        n_results=10,
        include=["documents", "metadatas", "distances"],
    )

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    candidates = [
        {
            "text":         doc,
            "source":       meta.get("source",      "unknown") if isinstance(meta, dict) else "unknown",
            "category":     meta.get("category",    "general") if isinstance(meta, dict) else "general",
            "chunk_index":  meta.get("chunk_index",  0)        if isinstance(meta, dict) else 0,
            "chroma_score": round(1.0 - (float(dist) / 2.0), 4) if dist is not None else 0.0,
        }
        for doc, meta, dist in zip(documents, metadatas, distances)
    ]

    print("[RAG] Reranking with FlashRank (local CPU cross-encoder)...")
    ranker = Ranker(
        model_name="ms-marco-MiniLM-L-12-v2",
        cache_dir=os.path.join(BASE_DIR, ".flashrank_cache"),
    )
    request = RerankRequest(query=query, passages=[{"text": c["text"]} for c in candidates])
    reranked = ranker.rerank(request)

    print("\n[RAG] Top 3 results after reranking:")
    encoding = sys.stdout.encoding or 'utf-8'
    for i, r in enumerate(reranked[:3]):
        # Merge metadata back for display
        meta = next((c for c in candidates if c["text"] == r["text"]), {})
        print(f"\n  [{i+1}] Rerank: {r['score']:.4f}  |  Chroma: {meta.get('chroma_score', '?')}  |  Category: {meta.get('category', '?')}")
        # Safe encoding/decoding to avoid print crash on Windows console
        safe_text = r['text'][:200].encode(encoding, errors='replace').decode(encoding)
        print(f"       {safe_text}...")


if __name__ == "__main__":
    if "--test" in sys.argv:
        query_test()
    else:
        ensure_faq_index(force=True)
        query_test()
