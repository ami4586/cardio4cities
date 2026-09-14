"""
Search & extraction agent.

Fetches every URL the crawlability agent marked "allowed" and pulls out the
actual article content -- not just whatever BeautifulSoup happens to scrape.

Uses trafilatura (a library purpose-built for isolating main article content
from arbitrary web pages) as the primary extractor, since naive tag-based
boilerplate stripping (removing <nav>/<footer>/<header>) misses a lot of
real-world sites where navigation, phone-number lists, and menus aren't
wrapped in those semantic tags at all -- trafilatura uses content-density
heuristics instead of relying on the page author having used semantic HTML
correctly. Falls back to the old BeautifulSoup approach if trafilatura
can't extract enough text (some page layouts genuinely confuse it).

Each finding keeps a clean `page_title` (the article's own headline)
separate from the body text, so the UI and PDF report can show the title as
an actual heading instead of it running straight into the first sentence.
"""

import json
from datetime import datetime, timezone

import requests
import trafilatura
from bs4 import BeautifulSoup

from agents.state import ResearchState
from stores.vector_store import upsert_chunks

USER_AGENT = "CARDIO4CitiesResearchBot/0.1 (+https://www.cardio4cities.org/)"
CHUNK_SIZE = 800
TIMEOUT = 8
MIN_TRAFILATURA_CHARS = 100  # below this, treat trafilatura's result as a miss and fall back


def _fetch_html(url: str) -> str:
    resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.text


def _extract_with_trafilatura(html: str) -> tuple[str, str] | None:
    """Returns (title, body_text) or None if trafilatura couldn't get enough usable text."""
    result = trafilatura.extract(
        html, output_format="json", with_metadata=True,
        include_comments=False, include_tables=False,
    )
    if not result:
        return None
    data = json.loads(result)
    text = (data.get("text") or "").strip()
    if len(text) < MIN_TRAFILATURA_CHARS:
        return None
    title = (data.get("title") or "").strip()

    # trafilatura's body text commonly repeats the article's own headline as
    # its first line (since an <h1> reads as body content too) -- strip that
    # duplicate so the title isn't shown once as a heading and then again as
    # the first bullet of the body.
    if title:
        first_line, _, rest = text.partition("\n")
        if first_line.strip().lower() == title.lower():
            text = rest.strip()

    return title, text


def _extract_with_beautifulsoup(html: str) -> tuple[str, str]:
    """Old boilerplate-stripping fallback -- used only when trafilatura misses."""
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return title, text


def _chunk(text: str, size: int = CHUNK_SIZE) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size) if text[i:i + size].strip()]


def extraction_node(state: ResearchState) -> ResearchState:
    findings = []
    retrieved_at = datetime.now(timezone.utc).isoformat()
    allowed = [c for c in state["crawlable_urls"] if c["status"] == "allowed"]

    for item in allowed:
        url, topic = item["url"], item["topic"]
        try:
            html = _fetch_html(url)
        except Exception as exc:
            print(f"[extraction] Failed to fetch {url}: {exc}")
            continue

        extracted = _extract_with_trafilatura(html)
        if extracted is not None:
            title, text = extracted
            method = "trafilatura"
        else:
            title, text = _extract_with_beautifulsoup(html)
            method = "beautifulsoup-fallback"

        chunks = _chunk(text)
        if not chunks:
            print(f"[extraction] {url} returned no usable text")
            continue

        upsert_chunks(state["city_name"], topic, url, chunks, retrieved_at)

        findings.append({
            "topic": topic,
            "page_title": title or None,
            "text": chunks[0][:600],
            "source_url": url,
            "chunk_count": len(chunks),
            "retrieved_at": retrieved_at,
        })
        print(f"[extraction] {url} -> {len(chunks)} chunk(s) via {method} (topic: {topic})")

    state["raw_findings"] = state.get("raw_findings", []) + findings
    print(f"[extraction] Produced {len(findings)} finding(s) from {len(allowed)} allowed source(s)")
    return state
