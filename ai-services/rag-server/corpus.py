from database import get_collection


def add_documents(feature, ids, documents, metadatas=None):
    """Store a feature's documents in its collection and return the new total."""
    collection = get_collection(feature)
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return collection.count()
