"""
Shared state object passed between every node in the LangGraph workflow.

Kept as a TypedDict (not a class) because LangGraph merges partial updates
returned by each node into this single object as the graph runs.
"""

from typing import TypedDict, List, Dict, Any


class ResearchState(TypedDict):
    # Input
    city_name: str

    # Set by the orchestrator: what we're researching this pass
    topics: List[str]

    # Set by the search agent: raw candidate URLs before any vetting
    candidate_urls: List[Dict[str, Any]]

    # Set by crawlability agent: which URLs are safe to fetch, and why
    crawlable_urls: List[Dict[str, Any]]

    # Set by extraction agent: raw text pulled from allowed sources
    raw_findings: List[Dict[str, Any]]

    # Set by fact-checking agent: claims that passed verification
    verified_facts: List[Dict[str, Any]]

    # Set by fact-checking agent: claims that could NOT be verified —
    # this is what triggers the loop back to the orchestrator
    flagged_gaps: List[Dict[str, Any]]

    # Accumulated evidence trail: every verified fact keeps its source_url
    citations: List[Dict[str, Any]]

    # How many times the orchestrator has re-planned in response to gaps.
    # Used to prevent an infinite research loop.
    replan_count: int


def initial_state(city_name: str) -> ResearchState:
    return ResearchState(
        city_name=city_name,
        topics=[],
        candidate_urls=[],
        crawlable_urls=[],
        raw_findings=[],
        verified_facts=[],
        flagged_gaps=[],
        citations=[],
        replan_count=0,
    )
