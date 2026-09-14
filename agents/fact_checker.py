"""
Fact-checking agent (Hour 3: real LLM verification).

Non-negotiable #4: independent of the agent that produced the finding, able
to conclude something is unsupported or missing, WITH a real consequence in
the graph (routes back to the orchestrator).
Non-negotiable #8: never present national data as city data without flagging it.

This agent sends each claim excerpt + its source_url to Gemini (a model that
did NOT produce the extraction) and asks a structured yes/no/why question:
does this excerpt actually support a city-specific claim, or does it look
like national/country-level data being passed off as city-level?

Falls back to the Hour 2 heuristic (length + error-page pattern check) if
GOOGLE_API_KEY isn't set, or if the API call fails for any reason -- so a
missing key degrades the demo instead of crashing it.
"""

from pydantic import BaseModel
from google.genai import types

from agents.state import ResearchState
from agents.llm_client import get_client, DEFAULT_MODEL

MIN_EXCERPT_LEN = 80
ERROR_SIGNALS = (
    "page not found", "404", "access denied",
    "enable javascript", "captcha", "are you a robot",
)

SYSTEM_INSTRUCTION = """You are an independent fact-checking agent in a city health-research \
pipeline. You did NOT write the excerpt you are given -- another agent extracted it from a \
webpage, and your only job is to judge it critically.

Given a city name, a topic, and a text excerpt from a source page, decide:
1. supported: does the excerpt contain real, specific information relevant to the topic for \
THIS city (not just a page that loaded but says nothing substantive)?
2. national_vs_city_mismatch: does the excerpt describe national/country-wide statistics or \
programmes being presented as if they were specific to this one city, without saying so?
3. reason: one short sentence explaining your verdict.

Be skeptical. If the excerpt is vague, promotional, unrelated to the topic, or clearly about \
the whole country rather than the city, mark it unsupported or flag the mismatch."""


class FactCheckVerdict(BaseModel):
    supported: bool
    national_vs_city_mismatch: bool
    reason: str


def _llm_verdict(city_name: str, topic: str, excerpt: str, source_url: str) -> FactCheckVerdict | None:
    client = get_client()
    if client is None:
        return None

    prompt = (
        f"City: {city_name}\n"
        f"Topic: {topic}\n"
        f"Source URL: {source_url}\n"
        f"Excerpt:\n{excerpt}"
    )
    try:
        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=FactCheckVerdict,
                temperature=0,
            ),
        )
        return FactCheckVerdict.model_validate_json(response.text)
    except Exception as exc:
        print(f"[fact_checker] Gemini call failed, falling back to heuristic: {exc}")
        return None


def _heuristic_verdict(excerpt: str) -> FactCheckVerdict:
    too_short = len(excerpt) < MIN_EXCERPT_LEN
    looks_broken = any(sig in excerpt.lower() for sig in ERROR_SIGNALS)
    supported = not (too_short or looks_broken)
    reason = (
        "heuristic fallback: looked like usable content"
        if supported
        else "heuristic fallback: too short or looked like an error/JS-only page"
    )
    # The heuristic can't detect national-vs-city mismatches -- only the LLM path can.
    return FactCheckVerdict(supported=supported, national_vs_city_mismatch=False, reason=reason)


def fact_checker_node(state: ResearchState) -> ResearchState:
    verified, gaps = [], []
    using_llm = get_client() is not None
    print(f"[fact_checker] Mode: {'Gemini LLM verification' if using_llm else 'heuristic fallback (no GOOGLE_API_KEY)'}")

    for finding in state["raw_findings"]:
        excerpt = finding["text"].strip()
        verdict = _llm_verdict(state["city_name"], finding["topic"], excerpt, finding["source_url"])
        if verdict is None:
            verdict = _heuristic_verdict(excerpt)

        if not verdict.supported or verdict.national_vs_city_mismatch:
            gaps.append({
                "topic": finding["topic"],
                "claim": excerpt,
                "source_url": finding["source_url"],
                "reason": verdict.reason,
                "national_vs_city_mismatch": verdict.national_vs_city_mismatch,
            })
        else:
            verified.append({**finding, "status": "verified", "verdict_reason": verdict.reason})

    state["verified_facts"] = state.get("verified_facts", []) + verified
    state["flagged_gaps"] = gaps
    state["citations"] = state.get("citations", []) + [
        {"source_url": f["source_url"], "topic": f["topic"]} for f in verified
    ]

    # Findings have now been adjudicated -- clear them so a replanned pass
    # starts from a clean extraction rather than re-checking old ones.
    state["raw_findings"] = []

    print(f"[fact_checker] Verified {len(verified)}, flagged {len(gaps)} gap(s)")
    return state
