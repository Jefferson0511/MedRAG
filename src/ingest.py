"""Index the corpus: load -> chunk -> estimate cost -> embed -> store in pgvector.

Rebuilds the table from scratch on every run, so the database always matches the current
loader and chunker. Model, table, and connection settings live in vectorstore.py.
"""
import uuid
from pathlib import Path

import tiktoken
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_postgres import PGEngine, PGVectorStore

from chunker import chunk_documents
from loader import load_corpus
from vectorstore import EMBEDDING_MODEL, METADATA_COLUMNS, TABLE_NAME, VECTOR_SIZE, connection_url, open_store

PRICE_PER_MILLION_TOKENS = 0.02  # USD, checked on OpenAI's model page on 2026-09-29

# Q4 from the eval spec, used as a smoke test after indexing.
SMOKE_TEST_QUERY = "What is the recommended timing for the first prenatal visit per ACOG?"


def chunk_id(chunk: Document) -> str:
    """Deterministic ID: the same chunk gets the same ID on every run, so eval logs stay comparable."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{chunk.metadata['source']}#{chunk.metadata['chunk_index']}"))


def estimate_cost(chunks: list[Document]) -> tuple[int, float]:
    """Count real tokens with OpenAI's tokenizer and return (total_tokens, estimated_usd)."""
    encoding = tiktoken.encoding_for_model(EMBEDDING_MODEL)
    token_counts = [len(encoding.encode(chunk.page_content)) for chunk in chunks]
    total = sum(token_counts)
    print(f"{len(chunks)} chunks, {total} tokens total, largest chunk {max(token_counts)} tokens (model limit 8192)")
    return total, total / 1_000_000 * PRICE_PER_MILLION_TOKENS


def build_store(chunks: list[Document]) -> PGVectorStore:
    """Recreate the table, then embed and insert every chunk."""
    engine = PGEngine.from_connection_string(url=connection_url())
    engine.init_vectorstore_table(
        table_name=TABLE_NAME,
        vector_size=VECTOR_SIZE,
        metadata_columns=METADATA_COLUMNS,
        overwrite_existing=True,  # drop and rebuild: the DB always matches the current code
    )
    store = open_store(engine)
    # embeds in batches via embed_documents, then inserts one row per chunk
    store.add_documents(chunks, ids=[chunk_id(chunk) for chunk in chunks])
    return store


if __name__ == "__main__":
    load_dotenv()
    chunks = chunk_documents(load_corpus(Path("data/raw")))

    total_tokens, cost = estimate_cost(chunks)
    answer = input(f"Embed {len(chunks)} chunks ({total_tokens} tokens) for about ${cost:.5f}? [y/N] ")
    if answer.strip().lower() != "y":
        raise SystemExit("Cancelled, nothing was embedded or stored.")

    store = build_store(chunks)
    print(f"Stored {len(chunks)} chunks in table {TABLE_NAME}.\n")

    print(f"Smoke test (Q4): {SMOKE_TEST_QUERY}")
    for rank, (doc, score) in enumerate(store.similarity_search_with_score(SMOKE_TEST_QUERY, k=5), start=1):
        meta = doc.metadata
        print(f"  #{rank} distance={score:.4f} | {meta['header']} | pages {meta['page_start']}-{meta['page_end']}")
