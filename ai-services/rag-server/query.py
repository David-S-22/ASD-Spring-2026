import logging

from langchain_chroma import Chroma

from database import client

logger = logging.getLogger(__name__)


def _vector_store(feature):
    return Chroma(client=client, collection_name=feature, create_collection_if_not_exists=False)


def _is_missing_segment_error(exc: Exception) -> bool:
    text = str(exc)
    return "Nothing found on disk" in text or "hnsw segment reader" in text


def _recover_feature_collection(feature: str) -> bool:
    from corpus import SOURCES_DIR, ingest_folder

    feature_dir = SOURCES_DIR / feature
    if not feature_dir.is_dir():
        return False
    ingest_folder(feature, feature_dir, rebuild=True)
    return True


def retrieve(feature, question, k=3, where=None):
    """Return the k documents closest to the question, each paired with its distance."""
    vector_store = _vector_store(feature)
    try:
        return vector_store.similarity_search_with_score(question, k=k, filter=where)
    except Exception as exc:
        if not _is_missing_segment_error(exc):
            raise
        logger.warning("Recovering Chroma collection '%s' after missing on-disk segment: %s", feature, exc)
        if not _recover_feature_collection(feature):
            raise RuntimeError(f"Collection '{feature}' is corrupted and cannot be rebuilt from sources.") from exc
        return _vector_store(feature).similarity_search_with_score(question, k=k, filter=where)
