import os
import chromadb
from rag.constants import (
    COLLECTION_NAME,
    CHROMA_FOLDER,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHROMA_PATH = os.path.join(
    BASE_DIR,
    CHROMA_FOLDER,
)




def get_collection():
    """
    Returns the ChromaDB collection.
    """

    if not os.path.exists(CHROMA_PATH):
        return None

    client = chromadb.PersistentClient(path=CHROMA_PATH)

    try:
        return client.get_collection(name=COLLECTION_NAME)

    except Exception:
        return None