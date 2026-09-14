"""
Crawlability detection agent.

Non-negotiable #3: nothing gets crawled until this agent has classified it,
and the result is written to SQLite immediately — before the extraction
agent fetches anything.

Two checks, both lightweight (no page body is downloaded here):
  1. robots.txt — the standard, authoritative signal. Uses urllib's
     RobotFileParser, which only ever fetches the robots.txt file itself.
  2. X-Robots-Tag response header via a HEAD request — an increasing number
     of sites now use `noai` / `noimageai` directives here specifically to
     opt out of AI/automated use, separate from robots.txt.

A URL is:
  - "blocked"  if robots.txt disallows it, OR the header opts out
  - "unknown"  if neither check could be completed (network/timeout errors)
  - "allowed"  otherwise
"""

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from agents.state import ResearchState
from stores.db import get_connection, insert_source

USER_AGENT = "CARDIO4CitiesResearchBot/0.1 (+https://www.cardio4cities.org/)"
BLOCKING_HEADER_TOKENS = ("noai", "noimageai", "none")
TIMEOUT = 6


def _check_robots(url: str):
    """Returns True/False, or None if robots.txt couldn't be read."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return None


def _check_headers(url: str):
    """Returns (ok, raw_header) via a HEAD request; ok=None if unreachable."""
    try:
        resp = requests.head(
            url, timeout=TIMEOUT, allow_redirects=True, headers={"User-Agent": USER_AGENT}
        )
        header_val = resp.headers.get("X-Robots-Tag", "").lower()
        blocked = any(token in header_val for token in BLOCKING_HEADER_TOKENS)
        return (not blocked), (header_val or None)
    except requests.RequestException as exc:
        return None, str(exc)


def crawlability_node(state: ResearchState) -> ResearchState:
    conn = get_connection()
    checked = []

    for item in state["candidate_urls"]:
        url, topic = item["url"], item["topic"]

        robots_ok = _check_robots(url)
        headers_ok, header_detail = _check_headers(url)

        if robots_ok is False:
            status, reason = "blocked", "disallowed by robots.txt"
        elif headers_ok is False:
            status, reason = "blocked", f"X-Robots-Tag opt-out: {header_detail}"
        elif robots_ok is None and headers_ok is None:
            status, reason = "unknown", f"could not verify: {header_detail}"
        else:
            status, reason = "allowed", "robots.txt permits; no blocking header found"

        # Written immediately — before extraction ever touches this URL.
        insert_source(conn, url, status)
        checked.append({"url": url, "topic": topic, "status": status, "reason": reason})

    conn.close()

    state["crawlable_urls"] = checked
    allowed = sum(1 for c in checked if c["status"] == "allowed")
    blocked = sum(1 for c in checked if c["status"] == "blocked")
    unknown = sum(1 for c in checked if c["status"] == "unknown")
    print(f"[crawlability] allowed={allowed} blocked={blocked} unknown={unknown} — statuses written to SQLite")
    return state
