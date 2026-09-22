import os

from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from database import client

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODELS = {
    "generation": os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
    "review": os.getenv("OLLAMA_REVIEW_MODEL", "llama3.1:8b"),
    "reasoning": os.getenv("OLLAMA_REASONING_MODEL", "deepseek-r1:8b"),
}

answer_prompt = ChatPromptTemplate.from_template(
    "Answer the question using only the context below.\n"
    "If the answer is not in the context, say you do not know.\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}"
)

review_prompt = ChatPromptTemplate.from_template(
    "Check the answer against the context below.\n"
    "Say whether the context supports the answer, and point out any part of the answer the context does not support.\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}\n\n"
    "Answer: {answer}"
)


def retrieve(feature, question, k=3, where=None):
    """Return the k documents closest to the question, each paired with its distance."""
    vector_store = Chroma(client=client, collection_name=feature)
    return vector_store.similarity_search_with_score(question, k=k, filter=where)


def context_of(documents):
    """Join the documents into the context block the prompts expect."""
    return "\n".join(document.page_content for document in documents)


def ask(feature, question, k=3, role="generation"):
    """Answer the question from the retrieved documents with the model for the role."""
    documents = [document for document, distance in retrieve(feature, question, k)]
    reasoning = True if role == "reasoning" else None
    llm = ChatOllama(model=MODELS[role], base_url=OLLAMA_URL, reasoning=reasoning)
    chain = answer_prompt | llm
    response = chain.invoke({"context": context_of(documents), "question": question})
    return {
        "answer": response.content,
        "reasoning": response.additional_kwargs.get("reasoning_content", ""),
        "model": MODELS[role],
        "sources": [document.id for document in documents],
    }


def review(feature, question, answer, k=3):
    """Check an answer against the retrieved documents with the review model."""
    documents = [document for document, distance in retrieve(feature, question, k)]
    llm = ChatOllama(model=MODELS["review"], base_url=OLLAMA_URL)
    chain = review_prompt | llm
    response = chain.invoke({"context": context_of(documents), "question": question, "answer": answer})
    return {"review": response.content, "model": MODELS["review"], "sources": [document.id for document in documents]}
