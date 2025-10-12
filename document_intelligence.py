"""Azure Document Intelligence integration for enhanced form/table extraction"""
import os
from io import BytesIO

# Configuration
AZURE_FORM_RECOGNIZER_KEY = os.getenv("AZURE_FORM_RECOGNIZER_KEY")
AZURE_FORM_RECOGNIZER_ENDPOINT = os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT")
USE_DOCUMENT_INTELLIGENCE = os.getenv("USE_DOCUMENT_INTELLIGENCE", "selective").lower()
USE_FORM_RECOGNIZER = bool(AZURE_FORM_RECOGNIZER_KEY and AZURE_FORM_RECOGNIZER_ENDPOINT)

form_recognizer_client = None

if USE_FORM_RECOGNIZER and USE_DOCUMENT_INTELLIGENCE != "never":
    try:
        from azure.ai.formrecognizer import DocumentAnalysisClient
        from azure.core.credentials import AzureKeyCredential

        form_recognizer_client = DocumentAnalysisClient(
            endpoint=AZURE_FORM_RECOGNIZER_ENDPOINT,
            credential=AzureKeyCredential(AZURE_FORM_RECOGNIZER_KEY)
        )
        print(f"📋 Azure Document Intelligence enabled (mode: {USE_DOCUMENT_INTELLIGENCE})")
        print("✅ Document Intelligence ready\n")
    except ImportError:
        print("⚠️  azure-ai-formrecognizer not installed - run: pip install azure-ai-formrecognizer\n")
    except Exception as e:
        print(f"⚠️  Document Intelligence init failed: {e}\n")


def should_use_document_intelligence(file_name):
    """Determine if we should use Document Intelligence for this file"""
    if not form_recognizer_client or USE_DOCUMENT_INTELLIGENCE == "never":
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
    if not form_recognizer_client:
        return None

    try:
        print(f"      📋 Using Document Intelligence (5-15 seconds)...")
        poller = form_recognizer_client.begin_analyze_document(
            "prebuilt-document", document=BytesIO(file_bytes)
        )
        result = poller.result()

        # Extract all text with structure
        text_parts = []

        # Extract content from pages
        for page in result.pages:
            text_parts.append(f"=== Page {page.page_number} ===")
            for line in page.lines:
                text_parts.append(line.content)

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
