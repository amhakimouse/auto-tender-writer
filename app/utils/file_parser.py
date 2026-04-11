"""
app/utils/file_parser.py

PDF text extraction utilities.

This module handles extracting text from uploaded PDF files for LLM processing.
It supports multiple backends for robust extraction.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    pass


def extract_text_from_pdf(file_path: Path | str) -> str:
    """
    Extract text content from a PDF file.

    Uses pdfplumber as the primary extraction method with fallback options.

    Args:
        file_path: Path to the PDF file

    Returns:
        Extracted text content as a single string

    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If text extraction fails
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    if not path.is_file():
        raise ValueError(f"Path is not a file: {path}")

    # Try pdfplumber first (primary method)
    try:
        import pdfplumber

        text_parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

        extracted_text = "\n\n".join(text_parts)

        if extracted_text.strip():
            logger.debug(
                "Extracted {chars} chars from {pages} pages using pdfplumber",
                chars=len(extracted_text),
                pages=len(pdf.pages),
            )
            return extracted_text

        logger.warning(
            "pdfplumber returned empty text for {path}, trying fallback",
            path=path,
        )

    except ImportError:
        logger.warning(
            "pdfplumber not installed, trying fallback extraction",
        )
    except Exception as exc:
        logger.error(
            "pdfplumber extraction failed: {error}, trying fallback",
            error=str(exc),
        )

    # Fallback: PyMuPDF (fitz)
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(path)
        text_parts = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            if text:
                text_parts.append(text)

        doc.close()
        extracted_text = "\n\n".join(text_parts)

        if extracted_text.strip():
            logger.debug(
                "Extracted {chars} chars using PyMuPDF fallback",
                chars=len(extracted_text),
            )
            return extracted_text

        logger.warning("PyMuPDF also returned empty text")

    except ImportError:
        logger.error(
            "No PDF extraction library available. "
            "Install pdfplumber: pip install pdfplumber"
        )
    except Exception as exc:
        logger.error("PyMuPDF extraction failed: {error}", error=str(exc))

    # If all methods fail
    raise ValueError(
        f"Failed to extract text from PDF: {path}. "
        "Ensure pdfplumber is installed: pip install pdfplumber"
    )


def extract_text_from_pdf_bytes(file_content: bytes) -> str:
    """
    Extract text from PDF bytes (in-memory).

    Useful for extracting text without writing to disk first.

    Args:
        file_content: Raw bytes of the PDF file

    Returns:
        Extracted text content
    """
    import tempfile

    # Write to temporary file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = Path(tmp.name)

    try:
        return extract_text_from_pdf(tmp_path)
    finally:
        # Cleanup
        try:
            tmp_path.unlink()
        except Exception:
            pass


def get_pdf_metadata(file_path: Path | str) -> dict:
    """
    Get metadata about a PDF file.

    Args:
        file_path: Path to the PDF file

    Returns:
        Dictionary with page count, file size, etc.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    metadata = {
        "file_path": str(path),
        "file_size_bytes": path.stat().st_size,
        "page_count": 0,
    }

    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            metadata["page_count"] = len(pdf.pages)

    except ImportError:
        try:
            import fitz

            doc = fitz.open(path)
            metadata["page_count"] = len(doc)
            doc.close()
        except ImportError:
            pass

    return metadata
