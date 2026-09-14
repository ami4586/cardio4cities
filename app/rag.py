"""
Conversational retrieval (the "Ask" tab).

Two independent retrievals happen on every substantive question, both
scoped to one city:
  1. Chroma semantic search over extracted page chunks -> excerpt-level
     evidence, each with its source_url.
  2. Graphiti/Neo4j graph search -> entities & relationships already
     extracted from this city's verified facts, queried live at chat time
     (non-negotiable #5's "genuinely used at query time").

Small talk (greetings, thanks, etc.) is detected up front and answered
without touching either store or the LLM -- there's nothing to retrieve for
"hi", and running the full pipeline on it would be wasted latency and a
wall of irrelevant text for the user.

Every result carries a `mode` so the UI can decide how to present it
(e.g. a quiet caption for the no-API-key fallback, never a debug string
inside the answer body itself) and a `generated_at` timestamp.
"""

import asyncio
import re
from datetime import datetime, timezone

from google.genai import types

from agents.llm_client import get_client, DEFAULT_MODEL
from stores.vector_store import query_city
from stores.graph_store import search_related_facts

SYSTEM_INSTRUCTION = """You are answering questions about a city's cardiovascular health \
landscape for a City Lead preparing to meet government stakeholders. You will be given \
numbered source excerpts. Answer using ONLY information in those excerpts.

Rules:
- Format your answer as short bullet points (2-6 bullets), not paragraphs.
- Each bullet states one fact and cites which source number(s) support it, like [1] or [2][3].
- Keep it concise -- this is briefing material someone will skim before a meeting, not an essay.
- If the excerpts don't contain enough information to answer, say so in one bullet. Never guess \
or fill gaps with outside knowledge."""

GREETING_PATTERN = re.compile(
    r"^(hi+|hello+|hey+|yo+|sup|greetings|good\s?(morning|afternoon|evening)|howdy)(\s+there)?[\s!.,]*$",
    re.IGNORECASE,
)


def _now_label() -> str:
    return datetime.now(timezone.utc).strftime("%b %d, %Y · %H:%M UTC")


def _is_greeting(question: str) -> bool:
    return bool(GREETING_PATTERN.match(question.strip()))


def _greeting_response(city_name: str) -> dict:
    answer = (
        f"Hi! I'm the research assistant for **{city_name}**.\n\n"
        f"I can help with:\n"
        f"- Answering questions about verified cardiovascular health findings for {city_name}\n"
        f"- Showing exactly which source backs each answer\n"
        f"- Telling you plainly when something isn't known yet, instead of guessing\n\n"
        f"Try asking something like *\"What hypertension programmes exist?\"* or "
        f"*\"Who are the key health stakeholders?\"*"
    )
    return {"answer": answer, "sources": [], "related_facts": [], "mode": "greeting", "generated_at": _now_label()}


def _format_raw_excerpts(docs: list[str], metas: list[dict]) -> str:
    lines = []
    for i, (doc, meta) in enumerate(zip(docs, metas), start=1):
        excerpt = doc.strip()
        if len(excerpt) > 220:
            excerpt = excerpt[:220].rsplit(" ", 1)[0] + "…"
        topic = (meta.get("topic") or "general").replace("_", " ")
        lines.append(f"- **{topic.capitalize()}** — {excerpt} _[source {i}]_")
    return "\n".join(lines)


def answer_question(city_name: str, question: str, n_results: int = 5) -> dict:
    if _is_greeting(question):
        return _greeting_response(city_name)

    chroma_results = query_city(city_name, question, n_results=n_results)
    docs = (chroma_results.get("documents") or [[]])[0]
    metas = (chroma_results.get("metadatas") or [[]])[0]

    related_facts = asyncio.run(search_related_facts(city_name, question))

    if not docs:
        return {
            "answer": f"- No researched information found yet for **{city_name}** on this question.\n"
                      f"- Run the research pipeline for this city first, or try a different question.",
            "sources": [],
            "related_facts": related_facts,
            "mode": "no_data",
            "generated_at": _now_label(),
        }

    sources = [
        {"n": i + 1, "source_url": m.get("source_url"), "topic": m.get("topic"), "retrieved_at": m.get("retrieved_at")}
        for i, m in enumerate(metas)
    ]

    client = get_client()
    if client is None:
        answer = _format_raw_excerpts(docs, metas)
        return {"answer": answer, "sources": sources, "related_facts": related_facts, "mode": "raw_excerpts", "generated_at": _now_label()}

    numbered_context = "\n\n".join(
        f"[{i + 1}] (topic: {m.get('topic')}, source: {m.get('source_url')})\n{d}"
        for i, (d, m) in enumerate(zip(docs, metas))
    )
    prompt = f"Question: {question}\n\nSource excerpts:\n{numbered_context}"

    try:
        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION, temperature=0),
        )
        answer = response.text
        mode = "synthesized"
    except Exception:
        answer = _format_raw_excerpts(docs, metas)
        mode = "raw_excerpts"

    return {"answer": answer, "sources": sources, "related_facts": related_facts, "mode": mode, "generated_at": _now_label()}
