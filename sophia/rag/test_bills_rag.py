import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "ai-services", "rag-server"))

import pytest

import query
from bills_corpus import DOCUMENTS, IDS, METADATAS
from corpus import add_documents
from database import client


@pytest.fixture
def feature():
    """Fill a throwaway collection with the bills and delete it afterwards."""
    add_documents("bills-ragtest", IDS, DOCUMENTS, METADATAS)
    yield "bills-ragtest"
    client.delete_collection(name="bills-ragtest")


def test_add_documents_does_not_duplicate(feature):
    """Adding the same ids again keeps five documents."""
    assert add_documents(feature, IDS, DOCUMENTS, METADATAS) == 5


def test_retrieve_finds_the_overdue_bill(feature):
    """The overdue question returns Home internet first, with its distance."""
    results = query.retrieve(feature, "Which bill is overdue?", k=2)
    document, distance = results[0]
    assert document.id == "bill-7"
    assert distance >= 0


def test_retrieve_finds_the_music_subscription(feature):
    """The music question returns Spotify first."""
    results = query.retrieve(feature, "How much is my music subscription?", k=2)
    assert results[0][0].id == "bill-3"


def test_retrieve_where_keeps_only_matching_metadata(feature):
    """Filtering on type keeps bills out of a subscriptions-only search."""
    results = query.retrieve(feature, "Which bill is overdue?", k=5, where={"type": "subscription"})
    assert [document.metadata["type"] for document, distance in results] == ["subscription"] * 3
