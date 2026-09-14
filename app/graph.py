"""
LangGraph orchestration.

Wires the six agents into a single state machine:

    orchestrator -> search -> crawlability -> extraction -> fact_checker --+--> store_report -> END
         ^                                                                  |
         +--------------------------- (gaps found) ------------------------+

The conditional edge out of fact_checker is what turns "the fact-checker can
conclude something is unsupported" into an actual workflow consequence
(non-negotiable #4), rather than a value that just sits unused in the state.
"""

from langgraph.graph import StateGraph, END

from agents.state import ResearchState
from agents.orchestrator import orchestrator_node
from agents.search import search_node
from agents.crawlability import crawlability_node
from agents.extraction import extraction_node
from agents.fact_checker import fact_checker_node
from agents.store_report import store_report_node

MAX_REPLANS = 1  # stop the loop after one retry so a demo run always terminates


def route_after_fact_check(state: ResearchState) -> str:
    if state["flagged_gaps"] and state["replan_count"] < MAX_REPLANS:
        return "orchestrator"
    return "store_report"


def build_graph():
    builder = StateGraph(ResearchState)

    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node("search", search_node)
    builder.add_node("crawlability", crawlability_node)
    builder.add_node("extraction", extraction_node)
    builder.add_node("fact_checker", fact_checker_node)
    builder.add_node("store_report", store_report_node)

    builder.set_entry_point("orchestrator")
    builder.add_edge("orchestrator", "search")
    builder.add_edge("search", "crawlability")
    builder.add_edge("crawlability", "extraction")
    builder.add_edge("extraction", "fact_checker")

    builder.add_conditional_edges(
        "fact_checker",
        route_after_fact_check,
        {"orchestrator": "orchestrator", "store_report": "store_report"},
    )

    builder.add_edge("store_report", END)

    return builder.compile()


graph = build_graph()
