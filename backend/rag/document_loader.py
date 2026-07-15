"""
rag/document_loader.py — Multi-format Document Loader (Phase 4 & 5)
====================================================================
Loads all supported document formats from the knowledge directory and
returns a unified list of (source, content) pairs for indexing.

Supported formats
-----------------
.txt   Plain-text documents. Loaded as-is.
.md    Markdown files. Treated as plain text (markup is preserved in
       chunks but does not affect embedding quality).
.pdf   PDF files. Text is extracted page-by-page with pypdf.
       Install: pip install pypdf

Design
------
- Sorted scan of the knowledge directory ensures a deterministic
  chunk ordering across re-indexes.
- Each document is returned as {"source": filename, "content": raw_text}
  so the caller can chunk and tag the content independently.
- Failures for individual files are logged and skipped so a single bad
  PDF does not block the entire index.
"""

import os
from pathlib import Path

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}


# ── Format-specific loaders ───────────────────────────────────────────────────

def _load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _load_markdown(path: str) -> str:
    return _load_text(path)   # Treat markdown as plain text for now


def _load_pdf(path: str) -> str:
    try:
        import pypdf
    except ImportError as exc:
        raise ImportError(
            "pypdf is required to load PDF files. "
            "Install it with:  pip install pypdf"
        ) from exc

    reader = pypdf.PdfReader(path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text and text.strip():
            pages.append(text.strip())

    return "\n\n".join(pages)


# ── Dispatcher ────────────────────────────────────────────────────────────────

def load_document(path: str) -> str:
    """
    Load a single document and return its raw text content.

    Parameters
    ----------
    path : str
        Absolute or relative path to the file.

    Returns
    -------
    str
        Full text of the document.

    Raises
    ------
    ValueError
        If the file extension is not in ``SUPPORTED_EXTENSIONS``.
    """
    ext = Path(path).suffix.lower()
    if ext == ".txt":
        return _load_text(path)
    elif ext == ".md":
        return _load_markdown(path)
    elif ext == ".pdf":
        return _load_pdf(path)
    else:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )


# ── Directory scanner ─────────────────────────────────────────────────────────

def load_knowledge_dir(knowledge_dir: str) -> list[dict]:
    """
    Scan a directory and load all supported documents.

    Parameters
    ----------
    knowledge_dir : str
        Path to the directory containing knowledge documents.

    Returns
    -------
    list[dict]
        Each item is ``{"source": filename, "content": raw_text}``.
        Files that fail to load are skipped with a warning.
    """
    knowledge_path = Path(knowledge_dir)

    if not knowledge_path.exists():
        print(f"[Loader] Knowledge directory not found: {knowledge_dir}")
        return []

    documents = []
    candidates = sorted(knowledge_path.iterdir())   # Deterministic order

    for file_path in candidates:
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        try:
            content = load_document(str(file_path))
            if not content.strip():
                print(f"[Loader] Skipped (empty): {file_path.name}")
                continue

            documents.append({
                "source": file_path.name,
                "content": content,
            })
            print(f"[Loader] Loaded: {file_path.name}  ({len(content):,} chars)")

        except Exception as exc:
            print(f"[Loader] ERROR loading {file_path.name}: {exc}")

    print(f"[Loader] Total documents loaded: {len(documents)}")
    return documents
