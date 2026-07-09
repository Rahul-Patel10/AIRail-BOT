import os
import chromadb
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHROMA_PATH = os.path.join(BASE_DIR, "chroma_store")

client = chromadb.PersistentClient(path=CHROMA_PATH)

collection = client.get_or_create_collection(
    name="search_context"
)


def save_search_context(
    session_id: str,
    source: str = None,
    destination: str = None,
    travel_date: str = None,
    train_no: str = None,
    train_name: str = None,
    last_action: str = None,
    selected_train: str = None,
    selected_station: str = None,
    departure_after: str = None,
    departure_before: str = None,
    arrival_after: str = None,
    arrival_before: str = None,
):
    collection.upsert(
        ids=[session_id],
        documents=[
            f"{source or ''} {destination or ''} {travel_date or ''} {departure_after or ''}"
        ],
        metadatas=[
            {
                "source": source or "",
                "destination": destination or "",
                "travel_date": travel_date or "",
                "train_no": train_no or "",
                "train_name": train_name or "",
                "last_action": last_action or "",
                "selected_train": selected_train or "",
                "selected_station": selected_station or "",
                "departure_after": departure_after or "",
                "departure_before": departure_before or "",
                "arrival_after": arrival_after or "",
                "arrival_before": arrival_before or "",
                "updated_at": datetime.utcnow().isoformat()
            }
        ]
    )


def get_search_context(session_id: str):
    result = collection.get(ids=[session_id])

    if not result["ids"]:
        return None

    metadata = dict(result["metadatas"][0] or {})
    return {key: (value or "") for key, value in metadata.items()}