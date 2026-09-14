"""
Orchestrator agent.

Responsible for deciding WHAT to research next. On the first pass it lays out
the topic checklist for a new city. If the fact-checking agent has flagged
gaps, this node re-plans a narrower follow-up pass instead of starting over.

STUB NOTE: topic planning and gap-driven replanning are hard-coded here.
Replace with an LLM call that reads city_name (+ flagged_gaps on replan
passes) and returns a topic list.
"""

from agents.state import ResearchState

DEFAULT_TOPICS = [
    "cardiovascular_health_landscape",
    "existing_healthcare_programmes",
    "major_policy_initiatives",
    "relevant_stakeholders",
]


def orchestrator_node(state: ResearchState) -> ResearchState:
    if state.get("flagged_gaps"):
        state["replan_count"] = state.get("replan_count", 0) + 1
        # dict.fromkeys preserves first-seen order while deduping
        gap_topics = list(dict.fromkeys(g["topic"] for g in state["flagged_gaps"]))
        print(
            f"[orchestrator] Replanning (pass {state['replan_count']}) "
            f"to re-research: {gap_topics}"
        )
        state["topics"] = gap_topics
        # Gaps are consumed once the orchestrator has acted on them; the
        # fact-checker will repopulate this list if the retry also fails.
        state["flagged_gaps"] = []
    else:
        print(f"[orchestrator] New city: planning research for '{state['city_name']}'")
        state["topics"] = list(DEFAULT_TOPICS)

    return state
