"""Azure Document Intelligence integration for enhanced form/table extraction"""
import os
import logging
from io import BytesIO

logger = logging.getLogger(__name__)

# Configuration
AZURE_FORM_RECOGNIZER_KEY = os.getenv("AZURE_FORM_RECOGNIZER_KEY")
AZURE_FORM_RECOGNIZER_ENDPOINT = os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT")
USE_DOCUMENT_INTELLIGENCE = os.getenv("USE_DOCUMENT_INTELLIGENCE", "selective").lower()
USE_FORM_RECOGNIZER = bool(AZURE_FORM_RECOGNIZER_KEY and AZURE_FORM_RECOGNIZER_ENDPOINT)

form_recognizer_client = None

def _get_form_recognizer_client():
    """Create the optional client on first extraction, not at import time."""
    global form_recognizer_client
    if form_recognizer_client is not None or not USE_FORM_RECOGNIZER:
        return form_recognizer_client
    try:
        from azure.ai.formrecognizer import DocumentAnalysisClient
        from azure.core.credentials import AzureKeyCredential
        form_recognizer_client = DocumentAnalysisClient(
            endpoint=AZURE_FORM_RECOGNIZER_ENDPOINT,
            credential=AzureKeyCredential(AZURE_FORM_RECOGNIZER_KEY)
        )
        logger.info("Azure Document Intelligence enabled (mode: %s)", USE_DOCUMENT_INTELLIGENCE)
    except ImportError:
        logger.warning("azure-ai-formrecognizer is not installed")
    except Exception:
        logger.exception("Document Intelligence initialization failed")
    return form_recognizer_client


def should_use_document_intelligence(file_name):
    """Determine if we should use Document Intelligence for this file"""
    client = _get_form_recognizer_client()
    if not client or USE_DOCUMENT_INTELLIGENCE == "never":
        return False

    if USE_DOCUMENT_INTELLIGENCE == "always":
        return True

    # Selective mode: use for tax documents, invoices, forms
    file_lower = file_name.lower()
    keywords = ['tax', '1040', 'w2', 'w-2', '1099', 'invoice', 'receipt', 'form', 'return']
    return any(keyword in file_lower for keyword in keywords)


def extract_with_document_intelligence(file_bytes):
    """Extract text using Azure Document Intelligence (better for forms/tables)

    Args:
        file_bytes: PDF file content as bytes

    Returns:
        Extracted text or None if failed
    """
    client = _get_form_recognizer_client()
    if not client:
        return None

    try:
        print(f"      📋 Using Document Intelligence (5-15 seconds)...")
        poller = client.begin_analyze_document(
            "prebuilt-document", document=BytesIO(file_bytes)
        )
        result = poller.result(timeout=120)  # 2 minute timeout

        # Extract all text with structure
        text_parts = []

        # Extract content from pages with progress indicator
        total_pages = len(result.pages)
        for page in result.pages:
            print(f"      📄 Page {page.page_number}/{total_pages}...", end=" ", flush=True)
            text_parts.append(f"=== Page {page.page_number} ===")
            for line in page.lines:
                text_parts.append(line.content)
            print("✓")

        # Extract tables if present
        if result.tables:
            text_parts.append("\n=== Tables ===")
            for table_idx, table in enumerate(result.tables, 1):
                text_parts.append(f"\nTable {table_idx} ({table.row_count}x{table.column_count}):")
                for cell in table.cells:
                    text_parts.append(f"Row {cell.row_index}, Col {cell.column_index}: {cell.content}")

        # Extract key-value pairs if present
        if result.key_value_pairs:
            text_parts.append("\n=== Form Fields ===")
            for kv in result.key_value_pairs:
                key = kv.key.content if kv.key else "Unknown"
                value = kv.value.content if kv.value else "N/A"
                text_parts.append(f"{key}: {value}")

        extracted_text = "\n".join(text_parts)
        print(f"      ✅ Document Intelligence complete!")
        return extracted_text

    except Exception as e:
        print(f"      ⚠️ Document Intelligence failed: {e}")
        return None
