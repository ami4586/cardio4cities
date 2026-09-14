"""
Shared Gemini client for the pipeline's own LLM calls (fact-checking).

Deliberately separate from Graphiti's internal LLM client (stores/graph_store.py)
even though both use Gemini and the same GOOGLE_API_KEY -- the fact-checker's
prompt and output schema are specific to CARDIO4Cities and have nothing to do
with Graphiti's entity-extraction prompts, so keeping them as two independent
clients means the fact-checker doesn't accidentally depend on Graphiti version
internals, and vice versa.

Uses Gemini because Graphiti's docs specifically call it out as one of the two
providers (with OpenAI) that reliably supports structured JSON output -- and
Google AI Studio issues a free API key with a real free tier, unlike the
Anthropic API. Get one at https://aistudio.google.com/apikey
"""

import os

from google import genai

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

_client = None


def get_client() -> genai.Client | None:
    """Returns a cached Gemini client, or None if GOOGLE_API_KEY isn't set."""
    global _client
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None
    if _client is None:
        _client = genai.Client(api_key=api_key)
    return _client
