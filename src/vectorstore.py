"""Shared vector store configuration, so ingest and retrieval can never disagree on model or table."""
import os
from urllib.parse import quote_plus

from langchain_openai import OpenAIEmbeddings
from langchain_postgres import Column, PGEngine, PGVectorStore

EMBEDDING_MODEL = "text-embedding-3-small"
VECTOR_SIZE = 1536  # must match the model's output length exactly; pgvector rejects anything else
TABLE_NAME = "chunks_te3small"  # model name in the table name: vectors from different models never mix

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


def connection_url() -> str:
    """Postgres URL for SQLAlchemy, built from the same .env values as scripts/check_db.py."""
    # +asyncpg: PGEngine runs async internally even for *_sync calls, and psycopg's async mode can't use
    # Windows' default ProactorEventLoop. asyncpg can. quote_plus escapes characters like @ or / in the password.
    return (
        f"postgresql+asyncpg://{os.getenv('POSTGRES_USER')}:{quote_plus(os.getenv('POSTGRES_PASSWORD', ''))}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}/{os.getenv('POSTGRES_DB')}"
    )


def open_store(engine: PGEngine | None = None) -> PGVectorStore:
    """Connect to the existing chunks table (read/write) without recreating it."""
    return PGVectorStore.create_sync(
        engine=engine or PGEngine.from_connection_string(url=connection_url()),
        table_name=TABLE_NAME,
        embedding_service=OpenAIEmbeddings(model=EMBEDDING_MODEL),
        metadata_columns=[column.name for column in METADATA_COLUMNS],  # which metadata keys map to columns
    )
