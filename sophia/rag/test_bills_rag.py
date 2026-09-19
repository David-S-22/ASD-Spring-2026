import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "ai-services", "rag-server"))

import pytest
from langchain_core.language_models import FakeListChatModel

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
    """The overdue question returns Home internet first."""
    documents = query.retrieve(feature, "Which bill is overdue?", k=2)
    assert documents[0].id == "bill-7"


def test_retrieve_finds_the_music_subscription(feature):
    """The music question returns Spotify first."""
    documents = query.retrieve(feature, "How much is my music subscription?", k=2)
    assert documents[0].id == "bill-3"


def test_ask_returns_answer_and_sources(feature, monkeypatch):
    """ask passes the model's reply through and lists the retrieved ids."""
    monkeypatch.setattr(query, "ChatOllama", lambda **kwargs: FakeListChatModel(responses=["Home internet"]))
    result = query.ask(feature, "Which bill is overdue?", k=2)
    assert result["answer"] == "Home internet"
    assert result["sources"][0] == "bill-7"
