"""Day 4 sanity check: can we reach the OpenAI embeddings API with the key in .env?"""
import math
import os

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

load_dotenv()  # copies OPENAI_API_KEY from .env into the environment, where OpenAIEmbeddings looks for it
if not os.getenv("OPENAI_API_KEY"):
    raise SystemExit("OPENAI_API_KEY is not set. Add it to .env (never to code or a committed file).")

embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vector = embeddings.embed_query("When should I have my first prenatal visit?")

# ||a|| = sqrt(a1^2 + a2^2 + ...). OpenAI documents its embeddings as normalized, so this should be ~1.
length = math.sqrt(sum(value * value for value in vector))

print(f"dimensions:     {len(vector)}")
print(f"vector length:  {length:.4f}")
print(f"first 5 values: {[round(value, 4) for value in vector[:5]]}")
print("\nDay 4 check passed: OpenAI embeddings are reachable.")
