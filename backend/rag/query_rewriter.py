"""
rag/query_rewriter.py — History-Aware Query Rewriter
=====================================================
Converts vague follow-up questions into standalone search queries
by resolving pronouns and implicit references against the conversation
history, before the query reaches the vector store.

Why this matters
----------------
Without this, a retriever sees only the raw user message:
  "What about cancellation?" → poor vector match

With this, the retriever sees a complete, resolvable query:
  "What is the Tatkal ticket cancellation policy?" → precise match

Design
------
- Uses a small, zero-temperature LLM call constrained to ≤ 64 tokens.
- Only looks at the last 3 exchanges (6 messages) to stay focused on the
  active topic and avoid pulling in stale context from much earlier.
- Falls back silently to the original message on any error (LLM
  unavailable, timeout, empty response) so retrieval is never blocked.
- Returns a (query, was_rewritten) tuple so the caller can log whether
  rewriting actually changed anything — useful for the Agent Trace panel.

Fast-path optimisations
-----------------------
- If there is no history, the message is already standalone → skip LLM.
- Truncates assistant messages to 300 chars; we only need the topic, not
  the full formatted answer.
"""

import os
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv

load_dotenv()

# ── Prompt ────────────────────────────────────────────────────────────────────

_REWRITER_SYSTEM = """You are a search query rewriter for an Indian Railways assistant.

Task: Given a short conversation history and the user's latest message, rewrite the message into a complete, self-contained search query that can retrieve relevant documents from a knowledge base — WITHOUT needing the conversation history.

Rules:
1. If the message is already self-contained and specific, return it unchanged.
2. Resolve pronouns (it, that, this, they, those) and implicit references (also, what about, same, and the) using the conversation history.
3. Keep the rewritten query concise — under 20 words.
4. Stay strictly in the Indian Railways / IRCTC domain.
5. Return ONLY the rewritten query string. No explanation, no quotes, no JSON, no punctuation changes unless needed.

Examples:
  History: User asked about Tatkal booking rules.
  Message: "What about cancellation?"
  Output:  What is the Tatkal ticket cancellation policy?

  History: User asked about refund policy.
  Message: "And for senior citizens?"
  Output:  What is the refund policy for senior citizens?

  History: User asked about baggage allowance in Sleeper class.
  Message: "What about in AC?"
  Output:  What is the baggage allowance in AC class?

  History: (none)
  Message: "How do I cancel my ticket?"
  Output:  How do I cancel my ticket?
"""

# ── LLM factory ───────────────────────────────────────────────────────────────

def _get_rewriter_llm():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    return ChatGroq(
        model=os.environ.get("GROQ_MODEL", "llama3-8b-8192"),
        groq_api_key=api_key,
        temperature=0.0,   # Fully deterministic — we want consistent rewrites
        max_tokens=64,     # A standalone query should never be this long
    )

# ── Public interface ──────────────────────────────────────────────────────────

def rewrite_query(user_message: str, history: list[dict]) -> tuple[str, bool]:
    """
    Rewrite a user message into a standalone retrieval query.

    Parameters
    ----------
    user_message : str
        The raw latest message from the user.
    history : list[dict]
        Full conversation history in ``[{"role": "user"|"assistant", "content": "..."}]``
        format. Only the last 6 entries (3 exchanges) are used.

    Returns
    -------
    (rewritten_query, was_rewritten) : tuple[str, bool]
        ``rewritten_query`` is the query to pass to the retriever.
        ``was_rewritten`` is True if the query was actually changed.
    """

    # Fast path: nothing to resolve without prior context
    if not history:
        return user_message, False

    llm = _get_rewriter_llm()
    if llm is None:
        return user_message, False

    # Use only the last 3 exchanges to keep context tight
    recent = history[-6:]

    context_lines = []
    for msg in recent:
        role = "User" if msg["role"] == "user" else "Assistant"
        # Truncate long assistant turns — topic matters, full answer does not
        content = msg["content"][:300] if msg["role"] == "assistant" else msg["content"]
        context_lines.append(f"{role}: {content}")

    context = "\n".join(context_lines)

    prompt = (
        f"Conversation history:\n{context}\n\n"
        f"User's latest message: {user_message}\n\n"
        "Rewrite the latest message into a standalone search query:"
    )

    try:
        response = llm.invoke([
            SystemMessage(content=_REWRITER_SYSTEM),
            HumanMessage(content=prompt),
        ])

        rewritten = response.content.strip().strip('"').strip("'")

        # Guard: empty or suspiciously long → not a valid rewrite
        if not rewritten or len(rewritten) > 200:
            return user_message, False

        was_rewritten = rewritten.lower() != user_message.lower()
        return rewritten, was_rewritten

    except Exception:
        # Never let a rewriter failure block retrieval
        return user_message, False
