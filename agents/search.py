"""
Search agent.

Replaces the fake-URL logic that lived inside the old crawlability stub.
For each topic the orchestrator planned, runs one DuckDuckGo query and
collects candidate URLs. Nothing is fetched or trusted here — this node
only produces a list of *candidates* for the crawlability agent to vet.

Uses the `ddgs` package (the current name for the library formerly called
`duckduckgo-search` — that package was renamed upstream in 2025).
"""

from ddgs import DDGS

from agents.state import ResearchState

RESULTS_PER_TOPIC = 3


def search_node(state: ResearchState) -> ResearchState:
    candidates = []
    seen_urls = set()

    with DDGS() as ddgs:
        for topic in state["topics"]:
            query = f"{state['city_name']} {topic.replace('_', ' ')}"
            try:
                results = ddgs.text(query, max_results=RESULTS_PER_TOPIC)
            except Exception as exc:
                print(f"[search] Query failed for '{query}': {exc}")
                results = []

            for r in results:
                url = r.get("href") or r.get("url") or r.get("link")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    candidates.append({"url": url, "topic": topic})

    state["candidate_urls"] = candidates
    print(f"[search] Found {len(candidates)} candidate URL(s) across {len(state['topics'])} topic(s)")
    return state
