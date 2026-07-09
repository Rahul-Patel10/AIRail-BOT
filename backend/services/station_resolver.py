import os

import chromadb

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

CHROMA_PATH = os.path.join(BASE_DIR, "chroma_store")

client = chromadb.PersistentClient(path=CHROMA_PATH)

collection = client.get_or_create_collection(
    name="railway_stations"
)


def resolve_station_with_chroma(query, db=None):
    """Resolve a station name/code via Chroma, with optional SQL fallback."""
    if not query or not str(query).strip():
        return None

    try:
        result = collection.query(
            query_texts=[str(query).strip()],
            n_results=1
        )

        if result.get("ids") and result["ids"][0] and result.get("metadatas") and result["metadatas"][0]:
            metadata = result["metadatas"][0][0]
            if isinstance(metadata, dict) and metadata.get("code"):
                return metadata
    except Exception:
        pass

    if db is None:
        return None

    from database import Station

    term = f"%{str(query).strip()}%"
    station = (
        db.query(Station)
        .filter(
            (Station.code.ilike(term))
            | (Station.name.ilike(term))
            | (Station.city.ilike(term))
        )
        .first()
    )

    if not station:
        return None

    return {
        "code": station.code,
        "name": station.name,
        "city": station.city,
    }
