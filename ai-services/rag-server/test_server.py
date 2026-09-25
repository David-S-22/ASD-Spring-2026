import io
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pytest
from pypdf import PdfReader

from corpus import (
    ingest_folder,
    ingest_sources,
    load_folder_chunks,
    load_markdown_chunks,
    load_pdf_chunks,
)
from database import client
from query import retrieve
from server import app

FEATURE = "servertest"
IDS = ["a", "b", "c"]
DOCUMENTS = ["The internet bill is overdue.", "Spotify is a music subscription.", "Rent is paid on the first of the month."]
METADATAS = [{"topic": "bills"}, {"topic": "music"}, {"topic": "bills"}]


def make_simple_pdf(text: str) -> bytes:
    content = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode("latin1")
    length = len(content)
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
        b"4 0 obj << /Length " + str(length).encode("latin1") + b" >> stream\n"
        + content + b"\nendstream endobj\n"
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000244 00000 n \n"
        b"0000000348 00000 n \n"
        b"trailer << /Size 6 /Root 1 0 R >>\n"
        b"startxref\n424\n%%EOF"
    )


@pytest.fixture
def http():
    """A test client over a small refreshed corpus."""
    test_client = app.test_client()
    test_client.post("/refresh", json={"feature": FEATURE, "ids": IDS, "documents": DOCUMENTS, "metadatas": METADATAS})
    yield test_client
    client.delete_collection(name=FEATURE)


def test_health_lists_the_collection(http):
    """Health names every collection in the store."""
    body = http.get("/health").get_json()
    assert body["ok"] is True
    assert FEATURE in body["collections"]


def test_refresh_replaces_the_documents(http):
    """Refreshing with one document leaves exactly one document."""
    body = http.post("/refresh", json={"feature": FEATURE, "ids": ["a"], "documents": ["Only one document now."]}).get_json()
    assert body["total"] == 1


def test_retrieve_returns_the_closest_document_with_its_distance(http):
    """The overdue question finds the internet bill first."""
    body = http.post("/retrieve", json={"feature": FEATURE, "question": "Which bill is overdue?", "k": 1}).get_json()
    assert body["results"][0]["id"] == "a"
    assert body["results"][0]["text"] == DOCUMENTS[0]
    assert body["results"][0]["distance"] >= 0


def test_retrieve_where_filters_on_metadata(http):
    """A where filter keeps only documents whose metadata matches."""
    body = http.post("/retrieve", json={"feature": FEATURE, "question": "Which bill is overdue?", "where": {"topic": "music"}}).get_json()
    assert [result["id"] for result in body["results"]] == ["b"]


def test_startup_ingestion_billing_collection(http):
    """Sources/billing is ingested on startup into its own 'billing' collection."""
    body = http.get("/health").get_json()
    assert "billing" in body["collections"]

    # Verify retrieval from billing collection
    res = http.post("/retrieve", json={"feature": "billing", "question": "Which bill is overdue?", "k": 1}).get_json()
    assert len(res["results"]) >= 1
    assert "internet" in res["results"][0]["text"].lower() or "overdue" in res["results"][0]["text"].lower()
    assert res["results"][0]["metadata"]["feature"] == "billing"
    assert res["results"][0]["metadata"]["doc_type"] == "markdown"


def test_sources_refresh_route(http):
    """The /sources/refresh endpoint re-ingests sources and returns counts."""
    res = http.post("/sources/refresh").get_json()
    assert res["ok"] is True
    assert "billing" in res["sources"]
    assert res["sources"]["billing"] >= 1


def test_chunk_and_ingest_markdown_and_pdf(tmp_path):
    """Chunking and ingesting both md and pdf files across feature directories."""
    feature_name = "test_custom_feature"
    feature_dir = tmp_path / feature_name
    feature_dir.mkdir()

    # Markdown document
    md_file = feature_dir / "guide.md"
    md_file.write_text(
        "# Account Guide\n\n## Subscriptions\nNetflix costs $20 monthly.\n\n## Bills\nElectricity is $150 quarterly.",
        encoding="utf-8",
    )

    # PDF document
    pdf_file = feature_dir / "policy.pdf"
    pdf_file.write_bytes(make_simple_pdf("Late payment incurs a ten dollar penalty fee."))

    try:
        # Ingest using ingest_sources with temporary sources_dir
        results = ingest_sources(sources_dir=tmp_path)
        assert feature_name in results
        assert results[feature_name] >= 2

        # Check collection was created and retrieval works for MD content
        res_md = retrieve(feature_name, "How much does Netflix cost?", k=1)
        assert len(res_md) >= 1
        doc_md, dist_md = res_md[0]
        assert "Netflix" in doc_md.page_content
        assert doc_md.metadata["doc_type"] == "markdown"
        assert doc_md.metadata["source"] == "guide.md"

        # Check retrieval for PDF content
        res_pdf = retrieve(feature_name, "What is the penalty for late payment?", k=1)
        assert len(res_pdf) >= 1
        doc_pdf, dist_pdf = res_pdf[0]
        assert "penalty" in doc_pdf.page_content.lower()
        assert doc_pdf.metadata["doc_type"] == "pdf"
        assert doc_pdf.metadata["source"] == "policy.pdf"
        assert doc_pdf.metadata["page"] == 1

    finally:
        if feature_name in [c.name for c in client.list_collections()]:
            client.delete_collection(name=feature_name)


def test_empty_feature_folder(tmp_path):
    """An empty feature folder creates an empty collection without error."""
    empty_feature = "test_empty_feature"
    (tmp_path / empty_feature).mkdir()

    try:
        results = ingest_sources(sources_dir=tmp_path)
        assert results[empty_feature] == 0
        assert empty_feature in [c.name for c in client.list_collections()]
    finally:
        if empty_feature in [c.name for c in client.list_collections()]:
            client.delete_collection(name=empty_feature)


def test_hidden_files_and_folders_are_ignored(tmp_path):
    """Hidden files (starting with dot) and hidden folders must be ignored."""
    feature_name = "test_hidden_filter"
    feature_dir = tmp_path / feature_name
    feature_dir.mkdir()

    # Visible file
    (feature_dir / "visible.md").write_text("# Visible Doc\nThis should be loaded.", encoding="utf-8")
    # Hidden files
    (feature_dir / ".hidden.md").write_text("# Secret\nThis must NOT be loaded.", encoding="utf-8")
    (feature_dir / ".DS_Store").write_text("junk", encoding="utf-8")
    # Hidden folder
    hidden_folder = tmp_path / ".hidden_feature"
    hidden_folder.mkdir()
    (hidden_folder / "doc.md").write_text("# Secret in hidden folder", encoding="utf-8")

    try:
        results = ingest_sources(sources_dir=tmp_path)
        # Hidden folder should not be in results
        assert ".hidden_feature" not in results
        # Only visible file chunk should be ingested
        assert results[feature_name] == 1
        res = retrieve(feature_name, "Secret", k=2)
        for doc, _ in res:
            assert doc.metadata["source"] != ".hidden.md"
            assert "Secret" not in doc.page_content
    finally:
        if feature_name in [c.name for c in client.list_collections()]:
            client.delete_collection(name=feature_name)


def test_load_markdown_chunks_standalone(tmp_path):
    """load_markdown_chunks correctly chunks markdown files and attaches metadata."""
    folder = tmp_path / "md_test"
    folder.mkdir()
    (folder / "file.md").write_text("# Title\nParagraph one.\n\n## Subtitle\nParagraph two.", encoding="utf-8")

    chunks = load_markdown_chunks(folder, "md_feature")
    assert len(chunks) >= 1
    assert chunks[0].metadata["source"] == "file.md"
    assert chunks[0].metadata["feature"] == "md_feature"
    assert chunks[0].metadata["doc_type"] == "markdown"


def test_load_pdf_chunks_standalone(tmp_path):
    """load_pdf_chunks correctly chunks pdf files and preserves page numbers."""
    folder = tmp_path / "pdf_test"
    folder.mkdir()
    (folder / "sample.pdf").write_bytes(make_simple_pdf("First page statement text."))

    chunks = load_pdf_chunks(folder, "pdf_feature")
    assert len(chunks) >= 1
    assert chunks[0].metadata["source"] == "sample.pdf"
    assert chunks[0].metadata["feature"] == "pdf_feature"
    assert chunks[0].metadata["doc_type"] == "pdf"
    assert chunks[0].metadata["page"] == 1
