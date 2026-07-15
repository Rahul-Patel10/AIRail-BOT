import os
import json
from langchain_groq import ChatGroq

from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
)
from dotenv import load_dotenv
from rag.retriever import search_faq
from rag.query_rewriter import rewrite_query
from rag.constants import CATEGORY_KEYWORDS

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

# ============================================================
# LLM
# ============================================================

def _get_llm():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    return ChatGroq(
        model=os.environ.get("GROQ_MODEL", "llama3-8b-8192"),
        groq_api_key=api_key,
        temperature=0.2,
    )

# ============================================================
# SYSTEM PROMPT
# ============================================================

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

# ── Phase 3 helper ───────────────────────────────────────────────────────────

def _detect_query_category(query: str) -> str | None:
    """
    Keyword-match the query against CATEGORY_KEYWORDS.
    Returns a category label (e.g. 'refund') or None if unclear.
    None tells the retriever to search the full collection (safe default).
    """
    text = query.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return None


# ============================================================
# MAIN RAG AGENT
# ============================================================

def run(user_message: str, history: list[dict], trace_steps: list[str]) -> dict:
    llm = _get_llm()

    # ── Phase 2: History-aware query rewriting ────────────────────────────
    # Resolve pronouns / implicit references before hitting the vector store.
    # Falls back silently to the original message on any failure.
    retrieval_query, was_rewritten = rewrite_query(user_message, history)

    if was_rewritten:
        trace_steps.append(
            f"[RAG] Query rewritten for retrieval:\n"
            f"  Original : {user_message}\n"
            f"  Rewritten: {retrieval_query}"
        )
    else:
        trace_steps.append(f"[RAG] Query is self-contained — no rewrite needed.")

    trace_steps.append(f"[RAG] Searching FAQ for: {retrieval_query}")
    # ─────────────────────────────────────────────────────────────────────

    # ── Phase 3: Metadata category filter ────────────────────────────────
    # Narrow vector search to the most relevant category when the query
    # is clearly about one topic. Falls back to full-collection search
    # when the category cannot be determined.
    detected_category = _detect_query_category(retrieval_query)
    metadata_filter = {"category": detected_category} if detected_category else None

    if detected_category:
        trace_steps.append(f"[RAG] Category detected: '{detected_category}' — applying metadata filter.")
    else:
        trace_steps.append("[RAG] No specific category detected — searching full knowledge base.")
    # ─────────────────────────────────────────────────────────────────────

    faq_results = search_faq(retrieval_query, metadata_filter=metadata_filter)

    # ── Phase 7: Similarity threshold ────────────────────────────────────
    # If no results passed the threshold, try again without the category
    # filter (the query category detector may have been too specific).
    if not faq_results and metadata_filter:
        trace_steps.append(
            f"[RAG] No results above threshold in '{detected_category}' — "
            "retrying without category filter."
        )
        faq_results = search_faq(retrieval_query)
    # ─────────────────────────────────────────────────────────────────────

    if faq_results:
        context_str = "\n\n".join([f"Document {i+1}:\n{doc.get('text', '')}" for i, doc in enumerate(faq_results)])
        trace_steps.append(f"[RAG] Retrieved {len(faq_results)} relevant chunks.")
    else:
        context_str = "No relevant FAQ documents found."
        trace_steps.append("[RAG] No chunks passed the similarity threshold.")

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
