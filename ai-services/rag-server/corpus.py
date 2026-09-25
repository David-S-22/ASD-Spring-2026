from database import client, get_collection


def add_documents(feature, ids, documents, metadatas=None):
    """Store a feature's documents in its collection and return the new total."""
    collection = get_collection(feature)
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return collection.count()


def refresh(feature, ids, documents, metadatas=None):
    """Rebuild the feature's collection from exactly these documents."""
    if feature in [collection.name for collection in client.list_collections()]:
        client.delete_collection(name=feature)
    return add_documents(feature, ids, documents, metadatas)
