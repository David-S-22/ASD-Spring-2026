import logging
import os
import sys

# Prioritize local directory for imports
sys.path.insert(0, os.path.dirname(__file__))

from pathlib import Path
from typing import Dict, List, Optional
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownTextSplitter, RecursiveCharacterTextSplitter
from pypdf import PdfReader
from database import client, get_collection

logger = logging.getLogger(__name__)

SOURCES_DIR = Path(__file__).resolve().parent / "sources"


def add_documents(feature: str, ids: List[str], documents: List[str], metadatas: Optional[List[dict]] = None) -> int:
    """Store a feature's documents in its collection and return the new total."""
    collection = get_collection(feature)
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return collection.count()


def refresh(feature: str, ids: List[str], documents: List[str], metadatas: Optional[List[dict]] = None) -> int:
    """Rebuild the feature's collection from exactly these documents."""
    if feature in [collection.name for collection in client.list_collections()]:
        client.delete_collection(name=feature)
    return add_documents(feature, ids, documents, metadatas)


def load_markdown_chunks(folder: Path, feature: str) -> List[Document]:
    """Load non-hidden Markdown files from folder and chunk using LangChain."""
    md_docs = [
        Document(
            page_content=f.read_text(encoding="utf-8", errors="replace"),
            metadata={"source": f.name, "feature": feature, "doc_type": "markdown"},
        )
        for f in folder.glob("[!.]*.md")
    ]
    if not md_docs:
        return []
    return MarkdownTextSplitter().split_documents(md_docs)


def load_pdf_chunks(folder: Path, feature: str) -> List[Document]:
    """Load non-hidden PDF files page-by-page from folder and chunk using LangChain."""
    pdf_docs: List[Document] = []
    for pdf_file in folder.glob("[!.]*.pdf"):
        try:
            reader = PdfReader(str(pdf_file))
            for page_idx, page in enumerate(reader.pages):
                text = (page.extract_text() or "").strip()
                if text:
                    pdf_docs.append(
                        Document(
                            page_content=text,
                            metadata={
                                "source": pdf_file.name,
                                "feature": feature,
                                "doc_type": "pdf",
                                "page": page_idx + 1,
                            },
                        )
                    )
        except Exception as e:
            logger.warning(f"Failed to load or parse PDF {pdf_file}: {e}")
            continue
    if not pdf_docs:
        return []
    return RecursiveCharacterTextSplitter().split_documents(pdf_docs)


def load_folder_chunks(feature: str, folder: Path) -> List[Document]:
    """Combine chunks from non-hidden Markdown and PDF documents in folder."""
    return load_markdown_chunks(folder, feature) + load_pdf_chunks(folder, feature)


def ingest_folder(feature: str, folder_path: Path | str, rebuild: bool = True) -> int:
    """Ingest non-hidden documents from a folder into its ChromaDB collection using LangChain."""
    folder = Path(folder_path)
    if rebuild and feature in [c.name for c in client.list_collections()]:
        client.delete_collection(name=feature)

    if not folder.is_dir() or folder.name.startswith("."):
        get_collection(feature)
        return 0

    chunks = load_folder_chunks(feature, folder)
    if chunks:
        chunk_counts: Dict[str, int] = {}
        ids = []
        for chunk in chunks:
            src = chunk.metadata.get("source", "doc")
            idx = chunk_counts.get(src, 0)
            chunk_counts[src] = idx + 1
            ids.append(f"{feature}_{src}_{idx}")

        vector_store = Chroma(client=client, collection_name=feature)
        vector_store.add_documents(chunks, ids=ids)
    else:
        get_collection(feature)

    return get_collection(feature).count()


def ingest_sources(sources_dir: Optional[Path | str] = None, rebuild: bool = True) -> Dict[str, int]:
    """Scan sources/<feature-name> folders and ingest each into its own collection."""
    target_dir = Path(sources_dir or SOURCES_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    for folder in sorted(target_dir.glob("[!.]*")):
        if folder.is_dir():
            results[folder.name] = ingest_folder(folder.name, folder, rebuild=rebuild)

    return results
