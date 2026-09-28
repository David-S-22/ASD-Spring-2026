import os

import requests

from bills_corpus import DOCUMENTS, IDS, METADATAS

RAG_SERVER_URL = os.getenv("RAG_SERVER_URL", "http://localhost:5003")
FEATURE = "bills"
QUESTION = "Which bill is overdue?"

refreshed = requests.post(f"{RAG_SERVER_URL}/refresh", json={"feature": FEATURE, "ids": IDS, "documents": DOCUMENTS, "metadatas": METADATAS}).json()
print(refreshed["total"], "documents stored")

retrieved = requests.post(f"{RAG_SERVER_URL}/retrieve", json={"feature": FEATURE, "question": QUESTION, "k": 2}).json()
for result in retrieved["results"]:
    print(result["id"], round(result["distance"], 3), result["text"])
