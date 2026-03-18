"""Groq LLM service.

Calls Groq's hosted Llama 3.1 70B model for answer generation.
"""

from __future__ import annotations

from typing import Any, cast

from groq import Groq

from app.config import get_settings

SYSTEM_PROMPT = """You are an expert assistant for US construction companies.
Answer questions accurately using ONLY the provided context documents.
If the context does not contain enough information, say so clearly.
Always cite which document(s) your answer comes from.
Be concise, professional, and safety-conscious."""


def _client() -> Groq:
    return Groq(api_key=get_settings().GROQ_API_KEY)


def generate_answer(
    query: str,
    context_chunks: list[dict],
    conversation_history: list[dict] | None = None,
) -> str:
    """Generate a RAG answer given query + retrieved context chunks.

    ``context_chunks`` should be dicts with at least ``text`` and ``filename`` keys.
    ``conversation_history`` is a list of ``{"role": ..., "content": ...}`` dicts.
    """
    settings = get_settings()

    # Build context block
    context_parts: list[str] = []
    for i, chunk in enumerate(context_chunks, 1):
        src = chunk.get("filename", "unknown")
        context_parts.append(f"[Source {i}: {src}]\n{chunk['text']}")
    context_block = "\n\n---\n\n".join(context_parts)

    # Assemble messages
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    if conversation_history:
        # Keep last N turns to stay within token limits
        messages.extend(conversation_history[-6:])

    messages.append(
        {
            "role": "user",
            "content": (
                f"Context documents:\n\n{context_block}\n\n"
                f"---\n\nQuestion: {query}"
            ),
        }
    )

    resp = _client().chat.completions.create(
        model=settings.LLM_MODEL,
        messages=cast(Any, messages),
        max_tokens=settings.LLM_MAX_TOKENS,
        temperature=settings.LLM_TEMPERATURE,
    )

    return resp.choices[0].message.content or ""
