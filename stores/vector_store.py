"""
Vector store (Chroma).

Holds chunked page text with source/topic/city metadata, so semantic
questions ("what programmes exist for hypertension?") can be answered with
a citation trail back to source_url — this is what the vector store is FOR,
as opposed to the relational store (transactional facts) or the graph store
(entities and relationships).

Uses Chroma's default local embedding function (all-MiniLM via onnxruntime).
Note: on first use, Chroma downloads that small model from the internet —
after that it's cached locally and works offline.
"""

import hashlib
from pathlib import Path

import chromadb

CHROMA_PATH = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "city_research"

_client = None
_collection = None


def get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        _collection = _client.get_or_create_collection(name=COLLECTION_NAME)
    return _collection


def upsert_chunks(city_name: str, topic: str, source_url: str, chunks: list[str], retrieved_at: str) -> None:
    if not chunks:
        return
    collection = get_collection()
    ids = [hashlib.sha1(f"{source_url}-{i}".encode()).hexdigest() for i in range(len(chunks))]
    metadatas = [
        {"source_url": source_url, "city": city_name, "topic": topic, "retrieved_at": retrieved_at}
        for _ in chunks
    ]
    collection.upsert(documents=chunks, metadatas=metadatas, ids=ids)


def query_city(city_name: str, question: str, n_results: int = 5):
    """Semantic search scoped to one city — used by the future Q&A agent."""
    collection = get_collection()
    return collection.query(query_texts=[question], n_results=n_results, where={"city": city_name})
