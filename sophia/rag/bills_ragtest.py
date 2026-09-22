import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "ai-services", "rag-server"))

from bills_corpus import DOCUMENTS, IDS, METADATAS
from corpus import add_documents
from query import ask, retrieve

total = add_documents("bills", ids=IDS, documents=DOCUMENTS, metadatas=METADATAS)
print(total, "documents stored")

question = "Which bill is overdue?"

for document, distance in retrieve("bills", question, k=2):
    print(document.id, document.page_content)

print(ask("bills", question))
