"""
bootstrap.py — One-shot setup for SQLite + ChromaDB indexes.

Called automatically on FastAPI startup and available as a CLI:
    python backend/bootstrap.py
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAQ_PATH = os.path.join(BASE_DIR, "data", "railway_faq.txt")
CHROMA_PATH = os.path.join(BASE_DIR, "chroma_store")
FAQ_COLLECTION = "railway_faq"
STATION_COLLECTION = "railway_stations"

CHUNK_SIZE = 400
CHUNK_OVERLAP = 80


def _load_and_chunk_faq(filepath: str) -> list[str]:
    with open(filepath, "r", encoding="utf-8") as f:
        raw = f.read()

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


def ensure_faq_index(force: bool = False) -> bool:
    """Build the railway FAQ Chroma collection if missing or empty."""
    import chromadb

    if not os.path.exists(FAQ_PATH):
        print(f"[Bootstrap] FAQ file not found: {FAQ_PATH}")
        return False

    os.makedirs(CHROMA_PATH, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    existing = {c.name for c in client.list_collections()}
    if FAQ_COLLECTION in existing and not force:
        collection = client.get_collection(FAQ_COLLECTION)
        if collection.count() > 0:
            print("[Bootstrap] FAQ index already ready.")
            return True

    from sentence_transformers import SentenceTransformer

    print("[Bootstrap] Building FAQ index...")
    chunks = _load_and_chunk_faq(FAQ_PATH)
    if not chunks:
        print("[Bootstrap] No FAQ chunks to index.")
        return False

    model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = model.encode(chunks, show_progress_bar=False, batch_size=32)

    if FAQ_COLLECTION in existing:
        client.delete_collection(FAQ_COLLECTION)

    collection = client.create_collection(name=FAQ_COLLECTION)
    collection.add(
        ids=[f"chunk_{i}" for i in range(len(chunks))],
        documents=chunks,
        embeddings=embeddings.tolist(),
        metadatas=[{"source": "railway_faq.txt", "chunk_index": i} for i in range(len(chunks))],
    )

    print(f"[Bootstrap] FAQ indexed ({len(chunks)} chunks).")
    return True


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
