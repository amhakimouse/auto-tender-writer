import fitz  # PyMuPDF
from loguru import logger

def extract_text(file_bytes: bytes) -> str:
    """
    Extracts text from PDF bytes using PyMuPDF.
    Handles multiple pages and basic cleaning.
    """
    try:
        logger.info("Extracting text from PDF ({} bytes)", len(file_bytes))
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text_parts = []
        for i in range(len(doc)):
            page = doc.load_page(i)
            text_parts.append(page.get_text())
        
        full_text = "\n".join(text_parts)
        if not full_text.strip():
            logger.warning("Extracted text is empty. PDF might be scanned/image-only.")
        
        return full_text
    except Exception as e:
        logger.error("Failed to extract text from PDF: {error}", error=str(e))
        raise ValueError(f"Could not parse PDF: {str(e)}")
