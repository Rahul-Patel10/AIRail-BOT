import os
import json
import chromadb
from flashrank import Ranker, RerankRequest
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMA_PATH = os.path.join(BASE_DIR, "chroma_store")
COLLECTION = "railway_faq"

def _get_llm():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    return ChatGroq(
        model=os.environ.get("GROQ_MODEL", "llama3-8b-8192"),
        groq_api_key=api_key,
        temperature=0.2,
    )

def search_faq(query: str, top_k: int = 5) -> list[dict]:
    if not os.path.exists(CHROMA_PATH):
        return []

    client = chromadb.PersistentClient(path=CHROMA_PATH)
    try:
        collection = client.get_collection(name=COLLECTION)
    except Exception:
        return []

    results = collection.query(query_texts=[query], n_results=15)
    documents = results.get("documents", [[]])[0]
    
    candidates = [{"text": doc} for doc in documents]
    if not candidates:
        return []

    ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir=os.path.join(BASE_DIR, ".flashrank_cache"))
    request = RerankRequest(query=query, passages=candidates)
    reranked = ranker.rerank(request)

    cleaned_results = []
    for doc in reranked[:top_k]:
        cleaned_doc = {}
        for k, v in doc.items():
            if hasattr(v, "item"):
                cleaned_doc[k] = v.item()
            else:
                cleaned_doc[k] = v
        cleaned_results.append(cleaned_doc)

    return cleaned_results

RAG_SYSTEM = """
You are AIrail, an Indian Railways and IRCTC policy assistant.

You have access to official railway and IRCTC documents, FAQs, and policy content. These documents are your primary source of truth.

## How to Use the Documents

Every answer must be grounded in the provided documents. Do not answer from general knowledge when the documents are available.

If the documents contain exact numbers, charges, deadlines, time windows, or rules, reproduce them precisely. Do not paraphrase or approximate them.

If the question is only partially covered, answer what is supported and clearly say what is not covered. Never fabricate missing policy details.

If the documents do not contain the answer, say so honestly and suggest checking the official IRCTC or Indian Railways source.

## How to Reason

Before answering, identify all relevant rule sections that may apply. Some questions involve multiple overlapping policies, such as cancellation + tatkal + refund rules. Reconcile the relevant points before responding.

## How to Respond

- Be thorough, precise, and easy to follow
- Use bullet points or short sections for clarity
- Preserve important deadlines, amounts, and conditions exactly
- Keep the tone helpful and clear
- Mention the source document at the end when appropriate

## What You Do Not Do

- Never guess a policy rule
- Never approximate charges or time windows
- Never present general knowledge as official policy
- Never leave the user without a next step if the documents are insufficient
"""

def run(user_message: str, history: list[dict], trace_steps: list[str]) -> dict:
    llm = _get_llm()
    trace_steps.append(f"[RAG] Searching FAQ for: {user_message}")
    
    faq_results = search_faq(user_message)
    if faq_results:
        context_str = "\n\n".join([f"Document {i+1}:\n{doc.get('text', '')}" for i, doc in enumerate(faq_results)])
        trace_steps.append(f"[RAG] Retrieved {len(faq_results)} relevant chunks.")
    else:
        context_str = "No relevant FAQ documents found."
        trace_steps.append("[RAG] No FAQ documents found.")

    try:
        if llm is None:
            raise Exception("LLM not available. Please set GROQ_API_KEY.")
        format_resp = llm.invoke([
            SystemMessage(content=RAG_SYSTEM),
            HumanMessage(content=f"User asked: \"{user_message}\"\n\nContext:\n{context_str}\n\nWrite a helpful markdown response.")
        ])
        final_text = format_resp.content
    except Exception as e:
        final_text = (
            "**(Offline Fallback Mode Activated - AI Quota Reached)**\n\n"
            "I found the following FAQ text that might help:\n\n" +
            (faq_results[0].get('text', 'No documents found.') if faq_results else "No documents found.")
        )
        trace_steps.append(f"[RAG] Formatting failed: {e}")

    return {
        "response": final_text,
        "intent": "rag",
        "trace_steps": trace_steps,
        "raw_data": faq_results,
        "sources": [
            {
                "source": doc.get("source", "railway_faq.txt"),
                "text": doc.get("text", ""),
                "chunk_index": idx + 1,
                "chroma_score": doc.get("chroma_score", doc.get("score", 0)),
                "rerank_score": doc.get("rerank_score", doc.get("score", 0)),
            }
            for idx, doc in enumerate(faq_results)
        ]
    }
