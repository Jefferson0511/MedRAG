"""Index the corpus: load -> chunk -> estimate cost -> embed -> store in pgvector.

Rebuilds the table from scratch on every run, so the database always matches the current
loader and chunker. The table name includes the embedding model, because vectors from
different models live in different spaces and must never share a table.
"""
import os
import uuid
from pathlib import Path
from urllib.parse import quote_plus

import tiktoken
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import Column, PGEngine, PGVectorStore

from chunker import chunk_documents
from loader import load_corpus

EMBEDDING_MODEL = "text-embedding-3-small"
VECTOR_SIZE = 1536  # must match the model's output length exactly; pgvector rejects anything else
TABLE_NAME = "chunks_te3small"
PRICE_PER_MILLION_TOKENS = 0.02  # USD, checked on OpenAI's model page on 2026-09-29

# Metadata stored as real Postgres columns (fast filtering, readable with plain SQL).
METADATA_COLUMNS = [
    Column("source", "TEXT"),
    Column("org", "TEXT"),
    Column("title", "TEXT"),
    Column("section_category", "TEXT"),
    Column("section_heading", "TEXT"),
    Column("header", "TEXT"),
    Column("chunk_index", "INTEGER"),
    Column("start_index", "INTEGER"),
    Column("page_start", "INTEGER"),
    Column("page_end", "INTEGER"),
]

# Q4 from the eval spec, used as a smoke test after indexing.
SMOKE_TEST_QUERY = "What is the recommended timing for the first prenatal visit per ACOG?"


def connection_url() -> str:
    """Postgres URL for SQLAlchemy, built from the same .env values as scripts/check_db.py."""
    # +asyncpg: PGEngine runs async internally even for *_sync calls, and psycopg's async mode can't use
    # Windows' default ProactorEventLoop. asyncpg can. quote_plus escapes characters like @ or / in the password.
    return (
        f"postgresql+asyncpg://{os.getenv('POSTGRES_USER')}:{quote_plus(os.getenv('POSTGRES_PASSWORD', ''))}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}/{os.getenv('POSTGRES_DB')}"
    )


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
    store = PGVectorStore.create_sync(
        engine=engine,
        table_name=TABLE_NAME,
        embedding_service=OpenAIEmbeddings(model=EMBEDDING_MODEL),
        metadata_columns=[column.name for column in METADATA_COLUMNS],  # which metadata keys map to columns
    )
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
        print(f"  #{rank} score={score:.4f} | {meta['header']} | pages {meta['page_start']}-{meta['page_end']}")
