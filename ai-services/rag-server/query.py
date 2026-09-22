import os

from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from database import client

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

prompt = ChatPromptTemplate.from_template(
    "Answer the question using only the context below.\n"
    "If the answer is not in the context, say you do not know.\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}"
)


def retrieve(feature, question, k=3, where=None):
    """Return the k documents closest to the question, each paired with its distance."""
    vector_store = Chroma(client=client, collection_name=feature)
    return vector_store.similarity_search_with_score(question, k=k, filter=where)


def ask(feature, question, k=3):
    """Answer the question using the documents retrieved for it."""
    documents = [document for document, distance in retrieve(feature, question, k)]
    context = "\n".join(document.page_content for document in documents)
    llm = ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_URL)
    chain = prompt | llm
    response = chain.invoke({"context": context, "question": question})
    return {"answer": response.content, "sources": [document.id for document in documents]}
