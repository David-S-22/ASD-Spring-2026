import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "ai-services", "rag-server"))

from corpus import add_documents
from query import ask, retrieve

total = add_documents(
    "bills",
    ids=["bill-3", "bill-4", "bill-6", "bill-7", "bill-9"],
    documents=[
        "Spotify from Spotify AU is a monthly subscription of $13.99. It was billed on 2026-08-16 and its status is paid.",
        "Netflix is a monthly subscription of $20.99. It is billed on 2026-09-02 and its status is due.",
        "GymCo is a monthly subscription of $24.99. It is billed on 2026-09-03 and its status is due.",
        "Home internet from FibreLink is a monthly bill of $79.00. It was billed on 2026-08-15 and its status is overdue.",
        "Electricity from Sparkwell Energy is a monthly bill of $142.00. It is billed on 2026-09-10 and its status is paid.",
    ],
    metadatas=[
        {"type": "subscription"},
        {"type": "subscription"},
        {"type": "subscription"},
        {"type": "bill"},
        {"type": "bill"},
    ],
)
print(total, "documents stored")

question = "Which bill is overdue?"

for document in retrieve("bills", question, k=2):
    print(document.id, document.page_content)

print(ask("bills", question))
