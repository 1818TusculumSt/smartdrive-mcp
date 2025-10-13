from pydantic_settings import BaseSettings
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    """
    Configuration settings loaded from environment variables.

    For MCP servers, these are set in Claude Desktop's config file.
    """

    # Pinecone Configuration
    PINECONE_API_KEY: str
    PINECONE_INDEX_NAME: str = "smartdrive"
    PINECONE_HOST: Optional[str] = None

    # Microsoft/OneDrive Configuration
    MICROSOFT_CLIENT_ID: Optional[str] = None
    MICROSOFT_TENANT_ID: Optional[str] = None

    # Embedding Provider Configuration
    EMBEDDING_PROVIDER: str = "local"  # Options: "local", "api", "pinecone", or "voyage"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_API_URL: Optional[str] = None
    EMBEDDING_API_KEY: Optional[str] = None

    # Voyage AI Configuration
    VOYAGE_API_KEY: Optional[str] = None
    VOYAGE_MODEL: str = "voyage-3-large"

    # Azure OCR Configuration
    AZURE_VISION_KEY: Optional[str] = None
    AZURE_VISION_ENDPOINT: Optional[str] = None
    OCR_STRICT_MODE: bool = True

    # Azure Document Intelligence Configuration
    AZURE_FORM_RECOGNIZER_KEY: Optional[str] = None
    AZURE_FORM_RECOGNIZER_ENDPOINT: Optional[str] = None
    USE_DOCUMENT_INTELLIGENCE: str = "selective"  # Options: "never", "selective", "always"

    # Azure Blob Storage Configuration (for RAG document storage)
    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = None
    AZURE_STORAGE_CONTAINER_NAME: str = "documents"

    # Performance Settings
    EMBEDDING_TIMEOUT: int = 30

    class Config:
        case_sensitive = True
        extra = "ignore"
        env_file = ".env"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._validate_settings()

    def _validate_settings(self):
        """Validate settings and log warnings for potential issues"""

        # Validate embedding provider
        if self.EMBEDDING_PROVIDER not in ["local", "api", "pinecone", "voyage"]:
            logger.warning(
                f"Invalid EMBEDDING_PROVIDER '{self.EMBEDDING_PROVIDER}'. "
                f"Defaulting to 'local'. Valid options: 'local', 'api', 'pinecone', 'voyage'"
            )
            self.EMBEDDING_PROVIDER = "local"

        # Validate API embedding config
        if self.EMBEDDING_PROVIDER == "api":
            if not self.EMBEDDING_API_URL:
                raise ValueError(
                    "EMBEDDING_API_URL is required when EMBEDDING_PROVIDER='api'"
                )
            if not self.EMBEDDING_API_KEY:
                raise ValueError(
                    "EMBEDDING_API_KEY is required when EMBEDDING_PROVIDER='api'"
                )

        # Validate Pinecone embedding config
        if self.EMBEDDING_PROVIDER == "pinecone":
            if not self.PINECONE_API_KEY:
                raise ValueError(
                    "PINECONE_API_KEY is required when EMBEDDING_PROVIDER='pinecone'"
                )

        # Validate Voyage AI embedding config
        if self.EMBEDDING_PROVIDER == "voyage":
            if not self.VOYAGE_API_KEY:
                raise ValueError(
                    "VOYAGE_API_KEY is required when EMBEDDING_PROVIDER='voyage'"
                )

        # Log configuration
        logger.info("Configuration loaded successfully")
        logger.info(f"  Embedding Provider: {self.EMBEDDING_PROVIDER}")
        logger.info(f"  Embedding Model: {self.EMBEDDING_MODEL}")
        logger.info(f"  Pinecone Index: {self.PINECONE_INDEX_NAME}")


# Initialize settings singleton
try:
    settings = Settings()
except Exception as e:
    logger.error(f"Failed to load settings: {e}")
    raise
