"""
CARDIO4Cities demo UI.

Three things a City Lead needs, per the case study's functional
expectations: trigger research on a new city, read a report with evidence,
and ask follow-up questions that stay grounded in what was actually found.

Design: sidebar acts as the control panel (research trigger + navigation),
main canvas is a single view at a time (Report or Ask) rather than tabs --
this is what lets the chat input pin to the bottom of the page the way
ChatGPT/Claude's own input does, since Streamlit's chat_input only anchors
reliably when it isn't nested inside a tab container.

Run with: streamlit run app/streamlit_app.py
"""

import sys
import os
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from agents.state import initial_state
from app.graph import graph
from app.report import generate_report, generate_report_pdf, get_report_data
from app.rag import answer_question
from stores.db import get_connection
from stores.graph_store import close_graphiti

st.set_page_config(page_title="CARDIO4Cities Research", page_icon="🫀", layout="wide")

# Streamlit Cloud secrets (st.secrets) aren't automatically exposed as
# os.environ vars, but llm_client.py and graph_store.py read os.environ --
# so mirror them across once at startup. Harmless locally where secrets.toml
# doesn't exist.
try:
    for _k, _v in st.secrets.items():
        os.environ.setdefault(_k, str(_v))
except Exception:
    pass

# ---- Design tokens ----------------------------------------------------
# A civic/clinical palette, deliberately not the generic SaaS defaults:
# deep teal as the single bold accent (trust, clinical calm), a muted
# brick-red reserved ONLY for uncertainty/gaps (never decorative), a warm
# paper background rather than stark white or dark mode. Source Serif for
# headings (report/document feel), IBM Plex Sans for UI (civic-data-tool
# feel), IBM Plex Mono for source URLs and timestamps only.
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,500;8..60,600;8..60,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

    :root {
        --c4c-ink: #1C2B2E;
        --c4c-primary: #0B5D6E;
        --c4c-primary-dark: #08434F;
        --c4c-warn: #B3452C;
        --c4c-warn-bg: #FBEEE9;
        --c4c-ok: #3F6B4C;
        --c4c-ok-bg: #EEF3EC;
        --c4c-border: #DFDACD;
        --c4c-muted: #6B6A63;
    }

    html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
    h1, h2, h3 { font-family: 'Source Serif 4', serif !important; color: var(--c4c-ink); }
    .c4c-mono { font-family: 'IBM Plex Mono', monospace; font-size: 0.82rem; color: var(--c4c-muted); }

    section[data-testid="stSidebar"] {
        background-color: var(--c4c-primary-dark);
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] .stMarkdown {
        color: #F2F0E9 !important;
    }
    section[data-testid="stSidebar"] .stTextInput input,
    section[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] > div {
        background-color: #F7F5EF;
        color: var(--c4c-ink);
    }

    .c4c-card {
        border: 1px solid var(--c4c-border);
        border-radius: 6px;
        padding: 0.9rem 1.1rem;
        margin-bottom: 0.7rem;
        background: #FFFFFF;
    }
    .c4c-gap-card {
        border: 1px solid #E7C9BC;
        border-left: 3px solid var(--c4c-warn);
        border-radius: 6px;
        padding: 0.9rem 1.1rem;
        margin-bottom: 0.7rem;
        background: var(--c4c-warn-bg);
    }
    .c4c-badge {
        display: inline-block;
        font-size: 0.75rem;
        font-weight: 500;
        padding: 0.1rem 0.55rem;
        border-radius: 999px;
        margin-bottom: 0.4rem;
    }
    .c4c-badge-allowed { background: var(--c4c-ok-bg); color: var(--c4c-ok); }
    .c4c-badge-blocked { background: var(--c4c-warn-bg); color: var(--c4c-warn); }
    .c4c-badge-unknown { background: #F1EFE8; color: var(--c4c-muted); }
    </style>
    """,
    unsafe_allow_html=True,
)


def get_researched_cities() -> list[str]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT city_name FROM city_profile ORDER BY created_at DESC").fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


# ---- Sidebar: control panel --------------------------------------------
with st.sidebar:
    st.markdown("### 🫀 CARDIO4Cities")
    st.caption("City research assistant")
    st.markdown("---")

    st.markdown("**Research a city**")
    new_city = st.text_input("City name", placeholder="e.g. Lagos", label_visibility="collapsed")
    if st.button("Run research pipeline", type="primary", use_container_width=True, disabled=not new_city):
        with st.spinner(f"Researching {new_city} — planning, searching, crawling, extracting, verifying..."):
            final_state = graph.invoke(initial_state(new_city))
            asyncio.run(close_graphiti())
        st.success(
            f"Done. {len(final_state['verified_facts'])} verified finding(s), "
            f"{len(final_state['flagged_gaps'])} unresolved gap(s)."
        )
        st.rerun()

    st.markdown("---")
    cities = get_researched_cities()
    if not cities:
        st.info("No cities researched yet. Enter one above to get started.")
        st.stop()

    st.markdown("**View a researched city**")
    selected_city = st.selectbox("City", cities, label_visibility="collapsed")

    st.markdown("---")
    view = st.segmented_control(
        "View", ["📄 Report", "💬 Ask"], default="📄 Report", required=True, label_visibility="collapsed"
    )

# ---- Main canvas: one view at a time (not tabs) -------------------------
# Single-view-at-a-time, chosen from the sidebar, is what lets the Ask
# view's st.chat_input sit at the true top level of the script rather than
# nested inside a tab -- which is what keeps it pinned to the bottom of the
# page like ChatGPT/Claude's own input, instead of rendering inline.

st.title("City Research Assistant")

if view == "📄 Report":
    data = get_report_data(selected_city)
    st.header(selected_city)
    if data["first_researched"]:
        st.caption(f"First researched {data['first_researched']}")

    st.subheader("Verified findings")
    if not data["claims"]:
        st.info(f'No verified findings yet — run the pipeline for "{selected_city}" first.')
    for c in data["claims"]:
        title_html = f"<div style='font-family:Source Serif 4, serif; font-weight:600; font-size:1.05rem; color:var(--c4c-primary); margin-bottom:0.35rem;'>{c['page_title']}</div>" if c["page_title"] else ""
        bullets = c["bullets"] or [c["text"]]
        bullets_html = "".join(f"<li style='margin-bottom:0.2rem;'>{b}</li>" for b in bullets)
        st.markdown(
            f"""<div class="c4c-card">{title_html}
            <ul style="margin:0 0 0.4rem 1.1rem; padding:0;">{bullets_html}</ul>
            <div class="c4c-mono">source: {c['source_url']} · verified {c['created_at']}</div>
            </div>""",
            unsafe_allow_html=True,
        )

    st.subheader("Known gaps & uncertainty")
    st.caption("We surface what we don't know rather than inventing it.")
    if not data["gaps"]:
        st.markdown('<div class="c4c-card">No unresolved gaps recorded for this city.</div>', unsafe_allow_html=True)
    for g in data["gaps"]:
        source_line = f"<br>attempted source: {g['source_url']}" if g["source_url"] else ""
        st.markdown(
            f"""<div class="c4c-gap-card"><strong>{g['topic'].replace('_', ' ')}</strong><br>
            {g['reason']}
            <div class="c4c-mono" style="margin-top:0.4rem;">{source_line}</div>
            </div>""",
            unsafe_allow_html=True,
        )

    st.subheader("Source registry")
    st.caption("Every source's crawlability status, recorded before any content was fetched.")

    allowed_sources = [s for s in data["sources"] if s["status"] == "allowed"]
    other_sources = [s for s in data["sources"] if s["status"] != "allowed"]

    if "source_filter" not in st.session_state:
        st.session_state.source_filter = "allowed"

    col1, col2 = st.columns(2)
    with col1:
        if st.button(f"✅ Allowed ({len(allowed_sources)})", use_container_width=True,
                      type="primary" if st.session_state.source_filter == "allowed" else "secondary"):
            st.session_state.source_filter = "allowed"
            st.rerun()
    with col2:
        if st.button(f"⛔ Blocked / Unknown ({len(other_sources)})", use_container_width=True,
                      type="primary" if st.session_state.source_filter == "other" else "secondary"):
            st.session_state.source_filter = "other"
            st.rerun()

    shown = allowed_sources if st.session_state.source_filter == "allowed" else other_sources
    if not shown:
        st.caption("Nothing in this category yet.")
    for s in shown:
        badge_class = f"c4c-badge-{s['status']}" if s["status"] in ("allowed", "blocked") else "c4c-badge-unknown"
        st.markdown(
            f"""<span class="c4c-badge {badge_class}">{s['status']}</span>
            <span class="c4c-mono">{s['url']}</span>""",
            unsafe_allow_html=True,
        )

    st.markdown("---")
    pdf_bytes = generate_report_pdf(selected_city)
    st.download_button(
        "Download full report (.pdf)",
        data=pdf_bytes,
        file_name=f"{selected_city.lower().replace(' ', '_')}_report.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

else:  # Ask view
    st.caption(f"Answers are grounded only in what was actually verified for {selected_city}.")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = {}
    history = st.session_state.chat_history.setdefault(selected_city, [])

    for msg in history:
        avatar = "🫀" if msg["role"] == "assistant" else "🙂"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                if msg.get("timestamp"):
                    st.caption(msg["timestamp"])
                refs = msg.get("sources") or msg.get("related_facts")
                if refs:
                    with st.expander(f"📚 References ({len(msg.get('sources', []))} source(s), {len(msg.get('related_facts', []))} graph fact(s))"):
                        if msg.get("sources"):
                            st.markdown("**Sources**")
                            for s in msg["sources"]:
                                st.markdown(f"`[{s['n']}]` {s['source_url']}")
                                st.caption(f"topic: {s['topic']} · retrieved: {s['retrieved_at']}")
                        if msg.get("related_facts"):
                            st.markdown("**Related graph facts**")
                            for f in msg["related_facts"]:
                                st.markdown(f"- {f['fact']}" + (f" _(valid at {f['valid_at']})_" if f["valid_at"] else ""))
                if msg.get("mode") == "raw_excerpts":
                    st.caption("⚙️ AI synthesis isn't configured for this deployment — showing retrieved excerpts directly.")

    question = st.chat_input(f"Ask something about {selected_city}...")
    if question:
        history.append({"role": "user", "content": question})
        with st.chat_message("user", avatar="🙂"):
            st.markdown(question)

        with st.chat_message("assistant", avatar="🫀"):
            with st.spinner("Searching evidence..."):
                result = answer_question(selected_city, question)
            st.markdown(result["answer"])
            st.caption(result["generated_at"])

            refs = result["sources"] or result["related_facts"]
            if refs:
                with st.expander(f"📚 References ({len(result['sources'])} source(s), {len(result['related_facts'])} graph fact(s))"):
                    if result["sources"]:
                        st.markdown("**Sources**")
                        for s in result["sources"]:
                            st.markdown(f"`[{s['n']}]` {s['source_url']}")
                            st.caption(f"topic: {s['topic']} · retrieved: {s['retrieved_at']}")
                    if result["related_facts"]:
                        st.markdown("**Related graph facts**")
                        for f in result["related_facts"]:
                            st.markdown(f"- {f['fact']}" + (f" _(valid at {f['valid_at']})_" if f["valid_at"] else ""))
            if result["mode"] == "raw_excerpts":
                st.caption("⚙️ AI synthesis isn't configured for this deployment — showing retrieved excerpts directly.")

        history.append({
            "role": "assistant",
            "content": result["answer"],
            "timestamp": result["generated_at"],
            "sources": result["sources"],
            "related_facts": result["related_facts"],
            "mode": result["mode"],
        })
