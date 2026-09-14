"""
Store & report agent.

Terminal node in the graph. Persists verified facts to all three datastores:
  - SQLite: transactional record (city_profile, claims, agent_runs)
  - Neo4j/Graphiti: entities + relationships extracted from each verified fact
  - Chroma: already populated by the extraction agent (nothing to do here)

Graphiti writes are async; this node runs them via asyncio.run() since
LangGraph nodes here are plain sync functions. If GOOGLE_API_KEY or the
Neo4j Sandbox credentials aren't set, graph writes are skipped with a clear
log line instead of crashing the whole pipeline -- SQLite + Chroma still work
on their own, which matters when demoing pieces independently.
"""

import asyncio

from agents.state import ResearchState
from stores.db import get_connection, insert_city_profile, insert_source, insert_claim, insert_gap, log_agent_run
from stores.graph_store import add_verified_fact


async def _write_all_facts_to_graph(state: ResearchState) -> list[dict]:
    results = []
    for fact in state["verified_facts"]:
        result = await add_verified_fact(
            city_name=state["city_name"],
            topic=fact["topic"],
            claim_text=fact["text"],
            source_url=fact["source_url"],
            retrieved_at=fact.get("retrieved_at", ""),
        )
        results.append(result)
    return results


def store_report_node(state: ResearchState) -> ResearchState:
    conn = get_connection()
    try:
        insert_city_profile(conn, state["city_name"])

        for c in state["crawlable_urls"]:
            insert_source(conn, c["url"], c["status"])

        for fact in state["verified_facts"]:
            insert_claim(conn, state["city_name"], fact["text"], fact["source_url"], fact["status"], fact.get("page_title"))

        # Anything still flagged when the loop ends (max replans hit and it
        # still failed) is a genuine, permanent gap -- persist it so the
        # report can say "we don't know this" instead of staying silent.
        for gap in state["flagged_gaps"]:
            insert_gap(conn, state["city_name"], gap["topic"], gap.get("claim"), gap.get("source_url"), gap["reason"])

        log_agent_run(
            conn,
            "store_report",
            f"Stored {len(state['verified_facts'])} verified fact(s) and {len(state['flagged_gaps'])} unresolved gap(s) for {state['city_name']}",
        )
    finally:
        conn.close()

    print(f"[store_report] Wrote {len(state['verified_facts'])} verified fact(s) to SQLite")

    graph_results = asyncio.run(_write_all_facts_to_graph(state))
    if graph_results and graph_results[0].get("skipped"):
        print(f"[store_report] Graph write skipped: {graph_results[0]['reason']}")
    else:
        total_entities = sum(r.get("entities", 0) for r in graph_results)
        total_edges = sum(r.get("edges", 0) for r in graph_results)
        print(f"[store_report] Graphiti extracted {total_entities} entities and {total_edges} relationships into Neo4j")

    return state
