"""
Relational store (SQLite).

Holds the structured, transactional side of the system: which sources exist
and their crawl status, individual claims and their verification status,
one row per researched city, and a log of every agent run. This is deliberately
separate from the vector store (semantic content) and the graph store
(entities + relationships) — see docs/ARCHITECTURE.md for the full rationale.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "cardio4cities.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS city_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_name TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL,          -- allowed | blocked | unknown
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_name TEXT NOT NULL,
    page_title TEXT,
    claim_text TEXT NOT NULL,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL,          -- verified | unsupported
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_url) REFERENCES sources(url)
);

CREATE TABLE IF NOT EXISTS gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_name TEXT NOT NULL,
    topic TEXT NOT NULL,
    claim_text TEXT,
    source_url TEXT,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def insert_city_profile(conn: sqlite3.Connection, city_name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO city_profile (city_name, created_at) VALUES (?, ?)",
        (city_name, _now()),
    )
    conn.commit()


def insert_source(conn: sqlite3.Connection, url: str, status: str) -> None:
    conn.execute(
        """INSERT INTO sources (url, status, checked_at) VALUES (?, ?, ?)
           ON CONFLICT(url) DO UPDATE SET status=excluded.status, checked_at=excluded.checked_at""",
        (url, status, _now()),
    )
    conn.commit()


def insert_claim(conn: sqlite3.Connection, city_name: str, claim_text: str, source_url: str, status: str, page_title: str | None = None) -> None:
    conn.execute(
        "INSERT INTO claims (city_name, page_title, claim_text, source_url, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (city_name, page_title, claim_text, source_url, status, _now()),
    )
    conn.commit()


def insert_gap(conn: sqlite3.Connection, city_name: str, topic: str, claim_text: str, source_url: str, reason: str) -> None:
    conn.execute(
        "INSERT INTO gaps (city_name, topic, claim_text, source_url, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (city_name, topic, claim_text, source_url, reason, _now()),
    )
    conn.commit()


def log_agent_run(conn: sqlite3.Connection, agent_name: str, message: str) -> None:
    conn.execute(
        "INSERT INTO agent_runs (agent_name, message, created_at) VALUES (?, ?, ?)",
        (agent_name, message, _now()),
    )
    conn.commit()
