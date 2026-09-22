from langchain_chroma import Chroma

from database import client


def retrieve(feature, question, k=3, where=None):
    """Return the k documents closest to the question, each paired with its distance."""
    vector_store = Chroma(client=client, collection_name=feature)
    return vector_store.similarity_search_with_score(question, k=k, filter=where)
