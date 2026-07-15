import os

from flashrank import Ranker
from flashrank import RerankRequest
from rag.constants import (
    FLASHRANK_MODEL,
    FLASHRANK_CACHE,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


CACHE = os.path.join(
    BASE_DIR,
    FLASHRANK_CACHE,
)

ranker = Ranker(
    model_name=FLASHRANK_MODEL,
    cache_dir=CACHE,
)


def rerank_documents(
    query,
    candidates,
    top_k,
):

    request = RerankRequest(
        query=query,
        passages=candidates,
    )

    reranked = ranker.rerank(request)

    cleaned = []

    for doc in reranked[:top_k]:

        cleaned_doc = {}

        for k, v in doc.items():

            if hasattr(v, "item"):
                cleaned_doc[k] = v.item()

            else:
                cleaned_doc[k] = v

        cleaned.append(cleaned_doc)

    return cleaned