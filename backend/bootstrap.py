"""
bootstrap.py — One-shot setup for SQLite + ChromaDB indexes.

Called automatically on FastAPI startup and available as a CLI:
    python backend/bootstrap.py
    python backend/bootstrap.py --force   # Force full re-index

Phase 3: chunks are tagged with a 'category' metadata field derived from
         keyword matching, enabling per-category filtered retrieval.

Phase 4/5: the knowledge/ directory is scanned for all supported document
           formats (.txt, .pdf, .md). Add new files there and re-run
           bootstrap to include them in the index.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")   # Phase 4/5 source dir
CHROMA_PATH = os.path.join(BASE_DIR, "chroma_store")
FAQ_COLLECTION = "railway_faq"
STATION_COLLECTION = "railway_stations"

CHUNK_SIZE = 400
CHUNK_OVERLAP = 80


# ── Phase 3: Category detection ───────────────────────────────────────────────

def _detect_category(text: str) -> str:
    """
    Assign a category label to a chunk based on keyword matching.
    First match wins; 'general' is the fallback.
    Keywords are centralised in rag/constants.py.
    """
    from rag.constants import CATEGORY_KEYWORDS

    text_lower = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return category
    return "general"


# ── Phase 4/5: Text chunker (works on any raw string) ────────────────────────

def _chunk_text(raw: str) -> list[str]:
    """
    Split raw document text into overlapping chunks.
    Paragraph boundaries are preferred; long paragraphs are slid over.
    """
    paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip()]
    chunks = []

    for para in paragraphs:
        if len(para) < 20:
            continue
        if len(para) <= CHUNK_SIZE:
            chunks.append(para)
        else:
            start = 0
            while start < len(para):
                end = start + CHUNK_SIZE
                chunks.append(para[start:end])
                start += CHUNK_SIZE - CHUNK_OVERLAP

    return chunks


# ── FAQ index ─────────────────────────────────────────────────────────────────

def ensure_faq_index(force: bool = False) -> bool:
    """
    Build the railway FAQ Chroma collection from all documents in
    the knowledge/ directory. Each chunk is tagged with its source
    filename, chunk index, and detected category (Phase 3).
    """
    import chromadb
    from sentence_transformers import SentenceTransformer
    from rag.document_loader import load_knowledge_dir

    os.makedirs(CHROMA_PATH, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    existing = {c.name for c in client.list_collections()}

    # Skip rebuild if index is populated and force is False
    if FAQ_COLLECTION in existing and not force:
        collection = client.get_collection(FAQ_COLLECTION)
        if collection.count() > 0:
            print("[Bootstrap] FAQ index already ready.")
            return True

    # Load all documents from the knowledge directory (Phase 4/5)
    documents = load_knowledge_dir(KNOWLEDGE_DIR)
    if not documents:
        print(f"[Bootstrap] No documents found in: {KNOWLEDGE_DIR}")
        return False

    # Chunk every document and collect per-chunk metadata (Phase 3)
    all_chunks: list[str] = []
    all_metadata: list[dict] = []
    chunk_id_counter = 0

    for doc in documents:
        chunks = _chunk_text(doc["content"])
        for chunk in chunks:
            category = _detect_category(chunk)
            all_chunks.append(chunk)
            all_metadata.append({
                "source": doc["source"],
                "chunk_index": chunk_id_counter,
                "category": category,         # Phase 3
            })
            chunk_id_counter += 1

    if not all_chunks:
        print("[Bootstrap] No chunks to index.")
        return False

    print(f"[Bootstrap] Embedding {len(all_chunks)} chunks from {len(documents)} document(s)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = model.encode(all_chunks, show_progress_bar=True, batch_size=32)

    # Replace the existing collection
    if FAQ_COLLECTION in existing:
        client.delete_collection(FAQ_COLLECTION)

    collection = client.create_collection(name=FAQ_COLLECTION)
    collection.add(
        ids=[f"chunk_{i}" for i in range(len(all_chunks))],
        documents=all_chunks,
        embeddings=embeddings.tolist(),
        metadatas=all_metadata,
    )

    # Print category breakdown so it's easy to verify in CI / terminal
    from collections import Counter
    cats = Counter(m["category"] for m in all_metadata)
    print(f"[Bootstrap] Indexed {len(all_chunks)} chunks — category breakdown:")
    for cat, count in sorted(cats.items()):
        print(f"  {cat:20s}: {count}")

    return True


# ── Station index (unchanged) ─────────────────────────────────────────────────

def ensure_station_index(force: bool = False) -> bool:
    """Index stations from SQLite into Chroma for fuzzy name resolution."""
    import chromadb
    from database import Session, Station

    os.makedirs(CHROMA_PATH, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(name=STATION_COLLECTION)

    if not force and collection.count() > 0:
        print("[Bootstrap] Station index already ready.")
        return True

    with Session() as db:
        stations = db.query(Station).all()

    if not stations:
        print("[Bootstrap] No stations in database — run init_db first.")
        return False

    docs, ids, metadata = [], [], []
    for st in stations:
        docs.append(f"{st.code} {st.name} {st.city}")
        ids.append(st.code)
        metadata.append({"code": st.code, "name": st.name, "city": st.city})

    collection.upsert(ids=ids, documents=docs, metadatas=metadata)
    print(f"[Bootstrap] Stations indexed ({len(stations)} stations).")
    return True


# ── Entry points ──────────────────────────────────────────────────────────────

def run_bootstrap(force: bool = False) -> None:
    """Initialize SQLite and ensure all Chroma indexes exist."""
    from database import init_db

    print("[Bootstrap] Starting...")
    init_db()
    ensure_faq_index(force=force)
    ensure_station_index(force=force)
    print("[Bootstrap] Complete.")


if __name__ == "__main__":
    sys.path.insert(0, BASE_DIR)
    force = "--force" in sys.argv
    run_bootstrap(force=force)

