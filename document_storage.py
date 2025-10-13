"""
Azure Blob Storage module for storing full document text.

This separates vector embeddings (Pinecone) from actual document content (Azure Blob),
enabling proper RAG architecture without metadata size limits.
"""

import os
import hashlib
import logging
from typing import Optional
from azure.storage.blob import BlobServiceClient, ContentSettings
from config import settings

logger = logging.getLogger(__name__)


class DocumentStorage:
    """Handles storing and retrieving full document text in Azure Blob Storage"""

    def __init__(self):
        """Initialize Azure Blob Storage client"""
        # Try config settings first, then fall back to environment variables
        connection_string = settings.AZURE_STORAGE_CONNECTION_STRING or os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        container_name = settings.AZURE_STORAGE_CONTAINER_NAME or os.getenv("AZURE_STORAGE_CONTAINER_NAME", "documents")

        if not connection_string:
            raise ValueError("AZURE_STORAGE_CONNECTION_STRING not found in config or environment")

        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        self.container_name = container_name
        self.container_client = self.blob_service_client.get_container_client(container_name)

        # Ensure container exists
        try:
            self.container_client.get_container_properties()
            logger.info(f"Connected to Azure Blob container: {container_name}")
        except Exception as e:
            logger.error(f"Failed to connect to container '{container_name}': {e}")
            raise

    def generate_doc_id(self, file_path: str) -> str:
        """
        Generate a unique document ID from file path.

        Args:
            file_path: OneDrive file path (e.g., "/Documents/taxes.pdf")

        Returns:
            Unique document ID (e.g., "doc_abc123def456")
        """
        # Use SHA256 hash of file path for deterministic, unique IDs
        hash_obj = hashlib.sha256(file_path.encode('utf-8'))
        hash_hex = hash_obj.hexdigest()[:16]  # First 16 chars of hash
        return f"doc_{hash_hex}"

    def store_document(self, file_path: str, text: str) -> str:
        """
        Store full document text in Azure Blob Storage.

        Args:
            file_path: OneDrive file path
            text: Full extracted text from document

        Returns:
            Document ID
        """
        doc_id = self.generate_doc_id(file_path)
        blob_name = f"{doc_id}.txt"

        try:
            blob_client = self.container_client.get_blob_client(blob_name)

            # Upload text with UTF-8 encoding
            blob_client.upload_blob(
                text.encode('utf-8'),
                overwrite=True,
                content_settings=ContentSettings(content_type='text/plain; charset=utf-8')
            )

            logger.debug(f"Stored document {doc_id} ({len(text)} chars)")
            return doc_id

        except Exception as e:
            logger.error(f"Failed to store document {doc_id}: {e}")
            raise

    def retrieve_document(self, doc_id: str) -> Optional[str]:
        """
        Retrieve full document text from Azure Blob Storage.

        Args:
            doc_id: Document ID (e.g., "doc_abc123")

        Returns:
            Full document text, or None if not found
        """
        blob_name = f"{doc_id}.txt"

        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            download_stream = blob_client.download_blob()
            text = download_stream.readall().decode('utf-8')

            logger.debug(f"Retrieved document {doc_id} ({len(text)} chars)")
            return text

        except Exception as e:
            logger.error(f"Failed to retrieve document {doc_id}: {e}")
            return None

    def delete_document(self, doc_id: str) -> bool:
        """
        Delete document from Azure Blob Storage.

        Args:
            doc_id: Document ID

        Returns:
            True if deleted, False if failed
        """
        blob_name = f"{doc_id}.txt"

        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            blob_client.delete_blob()
            logger.debug(f"Deleted document {doc_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete document {doc_id}: {e}")
            return False

    def document_exists(self, doc_id: str) -> bool:
        """
        Check if document exists in Azure Blob Storage.

        Args:
            doc_id: Document ID

        Returns:
            True if exists, False otherwise
        """
        blob_name = f"{doc_id}.txt"

        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            return blob_client.exists()
        except Exception as e:
            logger.error(f"Failed to check if document {doc_id} exists: {e}")
            return False

    def delete_documents_by_doc_ids(self, doc_ids: list) -> int:
        """
        Delete multiple documents from Azure Blob Storage by doc_id.

        Args:
            doc_ids: List of document IDs to delete

        Returns:
            Number of documents successfully deleted
        """
        deleted_count = 0

        for doc_id in doc_ids:
            if self.delete_document(doc_id):
                deleted_count += 1

        logger.info(f"Deleted {deleted_count}/{len(doc_ids)} documents from Azure Blob")
        return deleted_count
