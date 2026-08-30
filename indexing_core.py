"""Shared, non-interactive indexing operations.

The parser implementation remains in the manual crawler for now, but this module
is the only entry point used by background sync. Importing it performs no I/O.
"""

from contextlib import redirect_stdout
import logging
import sys

logger = logging.getLogger(__name__)


def _crawler():
    """Load the parser module only when indexing is actually requested."""
    import onedrive_crawler
    return onedrive_crawler


def configure(index, embedding_provider, document_storage, *, extract_zip_contents=False):
    """Inject clients into the existing parser/upsert implementation."""
    _crawler().configure_dependencies(
        index,
        embedding_provider,
        document_storage,
        extract_zip_contents=extract_zip_contents,
    )


def extract_file(token, item):
    """Download and extract one Graph drive item without interactive prompts."""
    # Legacy parser progress output must not reach MCP stdout.
    with redirect_stdout(sys.stderr):
        return _crawler().extract_text_from_file(token, item)


def process_files(files_data, index, embedding_provider, document_storage):
    """Store extracted files in Azure and upsert their hybrid vectors."""
    configure(index, embedding_provider, document_storage)
    with redirect_stdout(sys.stderr):
        _crawler().upload_to_pinecone(files_data, check_existing=False)


def generate_vector_id(file_path):
    return _crawler().generate_vector_id(file_path)
