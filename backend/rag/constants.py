"""
Central configuration for the Railway Assistant RAG pipeline.
Keeping these values here avoids hardcoded constants across modules.
"""

# -------------------------------
# ChromaDB
# -------------------------------

COLLECTION_NAME = "railway_faq"

CHROMA_FOLDER = "chroma_store"

# Directory scanned by the document loader (Phase 4/5)
KNOWLEDGE_DIR = "knowledge"


# -------------------------------
# Retrieval
# -------------------------------

INITIAL_RETRIEVAL_COUNT = 15

FINAL_TOP_K = 5

# Phase 7 — Similarity Threshold
# FlashRank cross-encoder scores run 0 → 1.
# Documents whose rerank score is below this value are dropped before
# being sent to the LLM, preventing low-confidence hallucination.
# Tune this value: lower → more permissive, higher → stricter.
RERANK_SCORE_THRESHOLD = 0.30


# -------------------------------
# FlashRank
# -------------------------------

FLASHRANK_MODEL = "ms-marco-MiniLM-L-12-v2"

FLASHRANK_CACHE = ".flashrank_cache"


# -------------------------------
# Phase 3 — Metadata Categories
# -------------------------------
# Maps a category label → keywords found in chunk text.
# Used at index time to tag each chunk, and at query time to pre-filter
# the vector store so only the most relevant category is searched.
# Order matters: first match wins. "general" is the fallback.

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "tatkal": [
        "tatkal", "premium tatkal", "pt quota", "last-minute", "10:00 am", "11:00 am"
    ],
    "cancellation": [
        "cancel", "cancellation", "clerkage", "no refund on cancellation"
    ],
    "refund": [
        "refund", "tdr", "ticket deposit", "refund policy", "refund amount",
        "refund for", "money back", "credited back"
    ],
    "pnr": [
        "pnr", "waitlist", "wl", "rac", "cnf", "reservation against cancellation",
        "chart", "pqwl", "rlwl", "gnwl", "booking status"
    ],
    "concession": [
        "concession", "senior citizen", "elderly", "disabled", "handicap",
        "child fare", "child ticket", "children", "student"
    ],
    "baggage": [
        "baggage", "luggage", "parcel", "free luggage", "excess luggage",
        "prohibited", "banned items", "pets", "animals"
    ],
    "food": [
        "food", "meal", "catering", "pantry", "rajdhani", "shatabdi",
        "e-catering", "dinner", "breakfast"
    ],
    "classes": [
        "sleeper", "1a", "2a", "3a", "cc", "2s", "general coach",
        "travel class", "unreserved", "chair car"
    ],
    "quota": [
        "quota", "defence quota", "ladies quota", "emergency quota",
        "eq quota", "drm", "special train"
    ],
}