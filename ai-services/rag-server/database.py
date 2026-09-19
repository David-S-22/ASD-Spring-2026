import os

import chromadb

CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma")

client = chromadb.PersistentClient(path=CHROMA_PATH)


def get_collection(feature):
    """Return the feature's collection, creating it the first time."""
    return client.get_or_create_collection(name=feature)
