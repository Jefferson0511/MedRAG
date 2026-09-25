"""Day 1 sanity check: can Python reach Postgres, and does pgvector work?"""
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

conninfo = (
    f"host={os.getenv('POSTGRES_HOST')} "
    f"port={os.getenv('POSTGRES_PORT')} "
    f"dbname={os.getenv('POSTGRES_DB')} "
    f"user={os.getenv('POSTGRES_USER')} "
    f"password={os.getenv('POSTGRES_PASSWORD')}"
)

with psycopg.connect(conninfo) as conn:
    with conn.cursor() as cur:
        # 1. Enable the pgvector extension (safe to run repeatedly)
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector';")
        print(f"pgvector version: {cur.fetchone()[0]}")

        # 2. Tiny preview of what Day 5 will do at scale:
        #    store vectors, then find the closest ones to a query vector.
        cur.execute("CREATE TEMP TABLE demo (id int, label text, v vector(3));")
        cur.execute("""
            INSERT INTO demo VALUES
              (1, 'exact match',   '[1, 2, 3]'),
              (2, 'very similar',  '[1, 2, 2.9]'),
              (3, 'very different','[3, -2, 1]');
        """)
        # <=> is pgvector's cosine distance operator: smaller = more similar
        cur.execute("""
            SELECT label, round((v <=> '[1, 2, 3]')::numeric, 4) AS distance
            FROM demo ORDER BY distance;
        """)
        print("\nClosest to [1, 2, 3]:")
        for label, dist in cur.fetchall():
            print(f"  {label:<15} distance = {dist}")

print("\nDay 1 check passed: Postgres + pgvector are working.")
