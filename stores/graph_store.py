"""
Graph store: Graphiti on top of the Neo4j Graph Database Sandbox.

Non-negotiable #5: knowledge graph built with Graphiti, hosted on Neo4j
Sandbox, genuinely used at query time (not just written to and ignored).

Uses Gemini (not the OpenAI default) because it's the only other provider
Graphiti's own docs recommend for reliable structured-output entity
extraction, and Google AI Studio's free tier means this doesn't require a
paid key -- consistent with agents/llm_client.py's choice for the same
reason. Requires the same GOOGLE_API_KEY plus Neo4j Sandbox credentials.

Each verified fact becomes one Graphiti "episode": Graphiti's own LLM call
extracts entities (people, organizations, programmes, policies) and
relationships from the text and writes them into Neo4j, merging with
whatever's already there for this city rather than duplicating it.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from graphiti_core.driver.neo4j_driver import Neo4jDriver
from graphiti_core.llm_client.gemini_client import GeminiClient, LLMConfig
from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient

_INDEX_MARKER = Path(__file__).parent / ".graph_indices_built"

_graphiti = None


def get_graphiti() -> Graphiti | None:
    """Returns a cached Graphiti client, or None if required env vars are missing."""
    global _graphiti

    api_key = os.environ.get("GOOGLE_API_KEY")
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")

    if not all([api_key, uri, user, password]):
        return None

    if _graphiti is None:
        llm_config = LLMConfig(api_key=api_key, model="gemini-2.5-flash")

        # IMPORTANT: some Aura instances (like this project's) do NOT use the
        # classic default database name "neo4j" -- check your instance's own
        # Developer Hub Python snippet for the `database_=` value it passes
        # to execute_query(), and set NEO4J_DATABASE to match. Getting this
        # wrong fails silently at first write with a DatabaseNotFound error,
        # not at connection time, so it's easy to miss until store_report runs.
        database = os.environ.get("NEO4J_DATABASE", "neo4j")
        driver = Neo4jDriver(uri, user, password, database=database)

        _graphiti = Graphiti(
            graph_driver=driver,
            llm_client=GeminiClient(config=llm_config),
            embedder=GeminiEmbedder(config=GeminiEmbedderConfig(api_key=api_key, embedding_model="embedding-001")),
            cross_encoder=GeminiRerankerClient(config=llm_config),
        )

    return _graphiti


async def ensure_indices(graphiti: Graphiti) -> None:
    """Builds Neo4j indices/constraints once. Safe to call again, but skipped after the first success."""
    if _INDEX_MARKER.exists():
        return
    await graphiti.build_indices_and_constraints()
    _INDEX_MARKER.touch()


async def add_verified_fact(city_name: str, topic: str, claim_text: str, source_url: str, retrieved_at: str) -> dict:
    """
    Writes one verified fact into the graph as a Graphiti episode.
    Returns a small summary dict for logging -- how many entities/edges Graphiti extracted.
    """
    graphiti = get_graphiti()
    if graphiti is None:
        return {"skipped": True, "reason": "GOOGLE_API_KEY / NEO4J_* env vars not set"}

    await ensure_indices(graphiti)

    try:
        reference_time = datetime.fromisoformat(retrieved_at)
    except ValueError:
        reference_time = datetime.now(timezone.utc)

    result = await graphiti.add_episode(
        name=f"{city_name}-{topic}-{source_url}",
        episode_body=claim_text,
        source=EpisodeType.text,
        source_description=f"CARDIO4Cities extraction: {source_url}",
        reference_time=reference_time,
        group_id=city_name.lower().replace(" ", "-"),
    )

    return {
        "skipped": False,
        "entities": len(result.nodes),
        "edges": len(result.edges),
    }


async def search_related_facts(city_name: str, query: str, num_results: int = 5) -> list[dict]:
    """
    Queries the graph at chat time -- this is what makes non-negotiable #5's
    "genuinely used at query time" true, rather than just written-to-and-ignored.
    """
    graphiti = get_graphiti()
    if graphiti is None:
        return []

    group_id = city_name.lower().replace(" ", "-")
    try:
        edges = await graphiti.search(query, group_ids=[group_id], num_results=num_results)
    except Exception as exc:
        print(f"[graph_store] search failed: {exc}")
        return []

    return [{"fact": e.fact, "valid_at": str(e.valid_at) if e.valid_at else None} for e in edges]


async def close_graphiti() -> None:
    global _graphiti
    if _graphiti is not None:
        await _graphiti.close()
        _graphiti = None
