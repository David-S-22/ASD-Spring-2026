"""Check the committed bills corpus through the shared server's own loader and retrieval."""
import os
import sys
from pathlib import Path

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "ai-services", "rag-server"))

import pytest

corpus = pytest.importorskip("corpus")

import query
from database import client

SOURCES_BILLS = Path(__file__).resolve().parents[2] / "ai-services" / "rag-server" / "sources" / "bills"
FEATURE = "bills-ragtest"


@pytest.fixture
def feature():
    """Ingest the committed folder into a throwaway collection and delete it afterwards."""
    corpus.ingest_folder(FEATURE, SOURCES_BILLS)
    yield FEATURE
    client.delete_collection(name=FEATURE)


def test_each_bill_file_is_exactly_one_chunk():
    """The loader yields one chunk per committed file, so no bill is split or merged."""
    chunks = corpus.load_markdown_chunks(SOURCES_BILLS, "bills")
    assert sorted(chunk.metadata["source"] for chunk in chunks) == sorted(path.name for path in SOURCES_BILLS.glob("*.md"))


def test_retrieve_finds_the_overdue_bill(feature):
    """The overdue question returns Home internet first, with its distance."""
    results = query.retrieve(feature, "Which bill is overdue?", k=2)
    chunk, distance = results[0]
    assert chunk.metadata["source"] == "bill-7-home-internet.md"
    assert distance >= 0


def test_retrieve_finds_the_music_subscription(feature):
    """The music question returns Spotify first."""
    results = query.retrieve(feature, "How much is my music subscription?", k=2)
    assert results[0][0].metadata["source"] == "bill-3-spotify.md"
