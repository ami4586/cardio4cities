# CARDIO4Cities — full pipeline 

LangGraph research pipeline + Streamlit UI: research a city, read a
citation-backed report, ask follow-up questions grounded in what was
actually verified.

## Folder structure

```
cardio4cities/
├── agents/
│   ├── state.py          # shared ResearchState
│   ├── orchestrator.py   # plans topics, replans on flagged gaps
│   ├── search.py         # DuckDuckGo (ddgs) query per topic -> candidate URLs
│   ├── crawlability.py   # robots.txt + X-Robots-Tag check, writes to SQLite before fetch
│   ├── extraction.py     # fetches allowed pages, chunks, embeds to Chroma
│   ├── llm_client.py     # shared Gemini client for the pipeline's own LLM calls
│   ├── fact_checker.py   # Gemini verifies claim-vs-excerpt + national-vs-city mismatch; heuristic fallback
│   └── store_report.py   # writes to SQLite + Chroma + Neo4j/Graphiti; persists unresolved gaps
├── stores/
│   ├── db.py             # SQLite: city_profile, sources, claims, gaps, agent_runs
│   ├── vector_store.py   # Chroma client, upsert_chunks(), query_city()
│   └── graph_store.py    # Graphiti wrapper (Gemini-backed), + search_related_facts() for query-time use
├── app/
│   ├── graph.py           # LangGraph wiring
│   ├── main.py             # CLI entry point
│   ├── report.py           # NEW: builds the downloadable markdown report from SQLite
│   ├── rag.py               # NEW: Chroma + Graphiti retrieval -> Gemini-synthesized, cited answer
│   └── streamlit_app.py     # NEW: the UI — trigger research, Report tab, Ask tab
├── .streamlit/config.toml
├── .env.example
├── requirements.txt
└── README.md
```

## Run locally

```bash
python3 -m venv venv && source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill in GOOGLE_API_KEY + NEO4J_*
export $(cat .env | xargs)

streamlit run app/streamlit_app.py
```

Opens at `http://localhost:8501`. Enter a city in the sidebar, click **Run
research pipeline** (takes 1–3 minutes for real search + crawl + extract +
fact-check + graph writes), then use the **Report** and **Ask** tabs.

You can also still run the pipeline headless from the CLI, e.g. for
generating the one required example output file:

```bash
python -m app.main "Nairobi"
python -c "from app.report import generate_report; open('nairobi_report.md','w').write(generate_report('Nairobi'))"
```

## What the Ask tab actually does (trustworthiness, live)

Every question triggers two real retrievals, not one:
1. **Chroma** semantic search over extracted chunks — the excerpt-level evidence, each tagged with its `source_url`.
2. **Neo4j via Graphiti** (`search_related_facts`) — queries the graph *at chat time*, not just at ingestion time. This is what makes non-negotiable #5's "genuinely used at query time" true rather than a graph that's written to once and never touched again.

Gemini then synthesizes an answer using only the retrieved excerpts, citing
source numbers, and is instructed to say "not enough information" rather
than guess. If `GOOGLE_API_KEY` isn't set, you still get the raw retrieved
excerpts with sources — no silent failure.

## Deployment (Streamlit Community Cloud, free)

1. Push this repo to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io), connect the repo, set:
   - **Main file path:** `app/streamlit_app.py`
3. In the app's **Settings → Secrets**, paste:
   ```toml
   GOOGLE_API_KEY = "..."
   NEO4J_URI = "neo4j+s://....databases.neo4j.io"
   NEO4J_USER = "neo4j"
   NEO4J_PASSWORD = "..."
   ```
   (`streamlit_app.py` mirrors `st.secrets` into `os.environ` at startup, so the rest of the codebase needs no changes to run there.)
4. Deploy. You'll get a URL like `https://your-app.streamlit.app` — that's the URL the non-negotiable asks for.

### Known limitation to state plainly in your demo
Streamlit Community Cloud's filesystem is **ephemeral** — SQLite (`stores/cardio4cities.db`) and the local Chroma directory reset on redeploy or app sleep/wake. Neo4j (external, via Graphiti) is unaffected since it's not on Streamlit's filesystem. For a persistent demo across multiple sessions, either: (a) re-run research for your demo city right before presenting, or (b) point Chroma/SQLite at a hosted equivalent (e.g. a small Postgres + a hosted vector DB) — noted here as a deliberate scope cut, not an oversight.

Also: Neo4j **Sandbox** instances (as opposed to AuraDB) expire after a few days by default — if your Sandbox session might lapse before the interview, recreate it the morning of, or use a free AuraDB instance instead (same Graphiti code, just a different URI).

## Tested so far

Verified directly, without live credentials, from my build sandbox:
- `generate_report()` against real SQLite fixture data — correct verified findings, gaps, and source registry sections.
- `answer_question()`'s no-API-key fallback path against mocked Chroma results — returns raw cited excerpts correctly.
- The full Streamlit app boots and serves (HTTP 200, no exceptions in server logs) against that same fixture data.
- Every prior hour's live-network claim (crawlability, extraction, Graphiti imports) as documented in their respective sections above.

**Not testable from my sandbox** (needs your own keys/instances): the Gemini-synthesized answer path, the live Graphiti graph search at chat time, and the actual deployment step. Run through all three yourself before presenting.
