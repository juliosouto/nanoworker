import os

from utils.file_utils import get_temp_file_path
from utils.security_utils import require_permission

_MAX_PDF_CHARS = 15000


@require_permission('PERM_FS')
def pdf_to_text(pdf_path: str, max_pages: int = None) -> str:
    """
    Extracts the text content of a local PDF file.
    Use this tool to read PDFs downloaded with download_file_from_url (contracts, reports, articles).
    
    Args:
        pdf_path: ABSOLUTE path of the PDF file.
        max_pages: Optional maximum number of pages to read (from the beginning). If omitted, reads all pages.
    
    Returns:
        str: The extracted text (truncated at 15000 characters), or an error message.
    """
    try:
        if not pdf_path or not os.path.isfile(pdf_path):
            return f"Error: PDF file not found: {pdf_path}"

        try:
            from pypdf import PdfReader
        except ImportError:
            return "Error: the 'pypdf' library is not installed in this environment."

        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)

        limit = total_pages
        if max_pages is not None:
            try:
                limit = min(total_pages, max(1, int(max_pages)))
            except (TypeError, ValueError):
                limit = total_pages

        chunks = []
        chars = 0
        for i in range(limit):
            page_text = (reader.pages[i].extract_text() or "").strip()
            if not page_text:
                continue
            chunks.append(f"--- Page {i + 1} ---\n{page_text}")
            chars += len(page_text)
            if chars > _MAX_PDF_CHARS:
                break

        text = "\n\n".join(chunks)
        if not text:
            return (
                f"No extractable text found in {pdf_path} ({total_pages} pages). "
                f"It may be a scanned/image-only PDF."
            )

        truncated = len(text) > _MAX_PDF_CHARS
        if truncated:
            text = text[:_MAX_PDF_CHARS]

        return (
            f"PDF: {pdf_path} ({total_pages} pages, showing {min(limit, total_pages)})."
            + (" [TEXT TRUNCATED]" if truncated else "")
            + "\n\n"
            + text
        )
    except Exception as e:
        return f"Error extracting PDF text: {str(e)}"