import numpy as np
import logging
from typing import Optional, Dict, List
import aiohttp
from sentence_transformers import SentenceTransformer
from pinecone_text.sparse import BM25Encoder
from config import settings

logger = logging.getLogger(__name__)

class EmbeddingProvider:
    """
    Handles embedding generation using either local models, API endpoints, or Pinecone inference.

    Supports:
    - Local: sentence-transformers models (default: all-MiniLM-L6-v2)
    - API: OpenAI-compatible embedding endpoints
    - Pinecone: Pinecone's integrated inference API
    - Voyage: Voyage AI embeddings (32K token context, 2048 dims)
    """

    def __init__(self, init_bm25=False):
        self.provider_type = settings.EMBEDDING_PROVIDER
        self._local_model = None
        self._session = None
        self._bm25_encoder = None

        if self.provider_type == "local":
            self._init_local_model()
        elif self.provider_type == "api":
            self._validate_api_config()
        elif self.provider_type == "pinecone":
            self._validate_pinecone_config()
        elif self.provider_type == "voyage":
            self._validate_voyage_config()
        else:
            raise ValueError(f"Invalid EMBEDDING_PROVIDER: {self.provider_type}. Must be 'local', 'api', 'pinecone', or 'voyage'")

        # Optionally initialize BM25 encoder at startup to preload NLTK data
        if init_bm25:
            self._init_bm25_encoder()

    def _init_bm25_encoder(self):
        """Initialize BM25 encoder and preload NLTK data"""
        try:
            import sys
            import os
            from io import StringIO

            logger.info("Preloading NLTK data and initializing BM25 encoder...")

            # Suppress NLTK download messages by redirecting stdout
            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                import nltk
                # Download required NLTK data silently
                nltk.download('punkt_tab', quiet=True)
                nltk.download('stopwords', quiet=True)
                # Initialize encoder (this also triggers NLTK internally)
                self._bm25_encoder = BM25Encoder.default()
            finally:
                # Restore stdout
                sys.stdout = old_stdout

            logger.info("BM25 encoder initialized successfully")
        except Exception as e:
            logger.warning(f"Could not preload BM25 encoder: {e}")
            # Not critical, will lazy-load later if needed
            self._bm25_encoder = None

    def _init_local_model(self):
        """Initialize local sentence-transformer model"""
        try:
            logger.info(f"Loading local embedding model: {settings.EMBEDDING_MODEL}")
            self._local_model = SentenceTransformer(settings.EMBEDDING_MODEL)
            logger.info(f"Local embedding model loaded successfully (dim: {self._local_model.get_sentence_embedding_dimension()})")
        except Exception as e:
            logger.error(f"Failed to load local embedding model: {e}")
            raise RuntimeError(f"Could not initialize local embedding model: {e}")

    def _validate_api_config(self):
        """Validate API configuration"""
        if not settings.EMBEDDING_API_URL:
            raise ValueError("EMBEDDING_API_URL required for API provider")
        if not settings.EMBEDDING_API_KEY:
            raise ValueError("EMBEDDING_API_KEY required for API provider")
        logger.info(f"Using API embedding provider: {settings.EMBEDDING_API_URL}")

    def _validate_pinecone_config(self):
        """Validate Pinecone inference configuration"""
        if not settings.PINECONE_API_KEY:
            raise ValueError("PINECONE_API_KEY required for Pinecone inference")
        logger.info(f"Using Pinecone inference with model: {settings.EMBEDDING_MODEL}")

    def _validate_voyage_config(self):
        """Validate Voyage AI configuration"""
        if not settings.VOYAGE_API_KEY:
            raise ValueError("VOYAGE_API_KEY required for Voyage AI")
        logger.info(f"Using Voyage AI with model: {settings.VOYAGE_MODEL}")

    def get_embedding_sync(self, text: str) -> Optional[np.ndarray]:
        """
        Synchronous wrapper for get_embedding (for non-async contexts like onedrive_crawler).

        Args:
            text: Text to embed

        Returns:
            Normalized embedding vector as numpy array, or None on error
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.get_embedding(text))

    async def get_embedding(self, text: str) -> Optional[np.ndarray]:
        """
        Get embedding for text using configured provider.

        Args:
            text: Text to embed

        Returns:
            Normalized embedding vector as numpy array, or None on error
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for embedding")
            return None

        try:
            if self.provider_type == "local":
                return await self._get_local_embedding(text)
            elif self.provider_type == "api":
                return await self._get_api_embedding(text)
            elif self.provider_type == "pinecone":
                return await self._get_pinecone_embedding(text)
            elif self.provider_type == "voyage":
                return await self._get_voyage_embedding(text)
            else:
                logger.error(f"Invalid embedding provider: {self.provider_type}")
                return None
        except Exception as e:
            logger.error(f"Error getting embedding: {e}", exc_info=True)
            return None

    async def _get_local_embedding(self, text: str) -> np.ndarray:
        """Get embedding from local sentence-transformer model"""
        if not self._local_model:
            raise RuntimeError("Local model not initialized")

        max_len = 512
        truncated = text[:max_len * 4]

        if len(text) > len(truncated):
            logger.debug(f"Truncated text from {len(text)} to {len(truncated)} chars")

        try:
            embedding = self._local_model.encode(
                truncated,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True
            )

            embedding = embedding.astype(np.float32)
            logger.debug(f"Generated local embedding (dim: {len(embedding)})")
            return embedding

        except Exception as e:
            logger.error(f"Local embedding generation failed: {e}")
            raise

    async def _get_pinecone_embedding(self, text: str) -> Optional[np.ndarray]:
        """
        Get embedding from Pinecone's inference API.

        Args:
            text: Text to embed

        Returns:
            Normalized embedding vector or None on error
        """
        if not self._session:
            self._session = aiohttp.ClientSession()

        url = "https://api.pinecone.io/embed"

        headers = {
            "Api-Key": settings.PINECONE_API_KEY,
            "Content-Type": "application/json",
            "X-Pinecone-API-Version": "2025-04"
        }

        # Add dimension parameter for llama-text-embed-v2 for high-quality embeddings
        params = {"input_type": "passage"}
        if settings.EMBEDDING_MODEL == "llama-text-embed-v2":
            params["dimension"] = 1024  # High-quality 1024-dim embeddings for better search

        data = {
            "model": settings.EMBEDDING_MODEL,
            "parameters": params,
            "inputs": [{"text": text}]
        }

        try:
            async with self._session.post(
                url,
                json=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=settings.EMBEDDING_TIMEOUT)
            ) as response:

                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Pinecone inference API error {response.status}: {error_text}")
                    return None

                result = await response.json()

                if not result.get("data") or len(result["data"]) == 0:
                    logger.error(f"Invalid Pinecone inference response: {result}")
                    return None

                embedding_list = result["data"][0].get("values")

                if not embedding_list or not isinstance(embedding_list, list):
                    logger.error("Invalid Pinecone inference response: missing values array")
                    return None

                embedding = np.array(embedding_list, dtype=np.float32)

                norm = np.linalg.norm(embedding)
                if norm > 1e-6:
                    embedding = embedding / norm
                else:
                    logger.warning("Embedding has near-zero norm, cannot normalize")

                logger.debug(f"Generated Pinecone embedding (dim: {len(embedding)})")
                return embedding

        except aiohttp.ClientError as e:
            logger.error(f"Pinecone inference API request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in Pinecone inference: {e}", exc_info=True)
            return None

    async def _get_api_embedding(self, text: str) -> Optional[np.ndarray]:
        """Get embedding from OpenAI-compatible API"""
        if not self._session:
            self._session = aiohttp.ClientSession()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.EMBEDDING_API_KEY}"
        }

        data = {
            "input": text,
            "model": settings.EMBEDDING_MODEL
        }

        try:
            async with self._session.post(
                settings.EMBEDDING_API_URL,
                json=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=settings.EMBEDDING_TIMEOUT)
            ) as response:

                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Embedding API error {response.status}: {error_text}")
                    return None

                result = await response.json()

                if not result.get("data") or len(result["data"]) == 0:
                    logger.error("Invalid embedding API response: missing data")
                    return None

                embedding_list = result["data"][0].get("embedding")

                if not embedding_list or not isinstance(embedding_list, list):
                    logger.error("Invalid embedding API response: missing embedding array")
                    return None

                embedding = np.array(embedding_list, dtype=np.float32)

                norm = np.linalg.norm(embedding)
                if norm > 1e-6:
                    embedding = embedding / norm
                else:
                    logger.warning("Embedding has near-zero norm, cannot normalize")

                logger.debug(f"Generated API embedding (dim: {len(embedding)})")
                return embedding

        except aiohttp.ClientError as e:
            logger.error(f"Embedding API request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in API embedding: {e}", exc_info=True)
            return None

    async def _get_voyage_embedding(self, text: str) -> Optional[np.ndarray]:
        """
        Get embedding from Voyage AI API.

        Supports:
        - 32,000 token context window (128K chars!)
        - 2048 dimensions for maximum quality
        - voyage-3-large model optimized for long documents

        Args:
            text: Text to embed (up to 32K tokens)

        Returns:
            Normalized embedding vector or None on error
        """
        if not self._session:
            self._session = aiohttp.ClientSession()

        url = "https://api.voyageai.com/v1/embeddings"

        headers = {
            "Authorization": f"Bearer {settings.VOYAGE_API_KEY}",
            "Content-Type": "application/json"
        }

        data = {
            "input": [text],
            "model": settings.VOYAGE_MODEL,
            "input_type": "document",  # For indexing documents
            "output_dimension": 2048  # Maximum quality
        }

        try:
            async with self._session.post(
                url,
                json=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=settings.EMBEDDING_TIMEOUT)
            ) as response:

                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Voyage AI API error {response.status}: {error_text}")
                    return None

                result = await response.json()

                if not result.get("data") or len(result["data"]) == 0:
                    logger.error(f"Invalid Voyage AI response: {result}")
                    return None

                embedding_list = result["data"][0].get("embedding")

                if not embedding_list or not isinstance(embedding_list, list):
                    logger.error("Invalid Voyage AI response: missing embedding array")
                    return None

                embedding = np.array(embedding_list, dtype=np.float32)

                # Voyage embeddings are already normalized
                norm = np.linalg.norm(embedding)
                if norm > 1e-6:
                    embedding = embedding / norm
                else:
                    logger.warning("Embedding has near-zero norm, cannot normalize")

                logger.debug(f"Generated Voyage AI embedding (dim: {len(embedding)})")
                return embedding

        except aiohttp.ClientError as e:
            logger.error(f"Voyage AI API request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in Voyage AI embedding: {e}", exc_info=True)
            return None

    def get_sparse_embedding_sync(self, text: str) -> Optional[Dict[str, List]]:
        """
        Generate BM25 sparse embedding for hybrid search (synchronous).

        Args:
            text: Text to encode

        Returns:
            Dict with 'indices' and 'values' for sparse vector, or None on error
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for sparse embedding")
            return None

        try:
            # Lazy-load BM25 encoder
            if self._bm25_encoder is None:
                logger.info("Initializing BM25 encoder for sparse embeddings...")
                self._bm25_encoder = BM25Encoder.default()
                logger.info("BM25 encoder initialized")

            # Generate sparse embedding
            sparse_vector = self._bm25_encoder.encode_documents([text])[0]

            # Convert to Pinecone format
            result = {
                "indices": sparse_vector["indices"].tolist() if hasattr(sparse_vector["indices"], 'tolist') else sparse_vector["indices"],
                "values": sparse_vector["values"].tolist() if hasattr(sparse_vector["values"], 'tolist') else sparse_vector["values"]
            }

            logger.debug(f"Generated sparse embedding ({len(result['indices'])} terms)")
            return result

        except Exception as e:
            logger.error(f"Error generating sparse embedding: {e}", exc_info=True)
            return None

    async def get_sparse_embedding(self, text: str) -> Optional[Dict[str, List]]:
        """Async wrapper for sparse embedding generation"""
        return self.get_sparse_embedding_sync(text)

    async def close(self):
        """Close any open sessions"""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("Closed embedding API session")

    def __del__(self):
        """Cleanup on deletion - best effort only"""
        # Don't try to close sessions during interpreter shutdown
        # as event loop and other imports may no longer be available
        pass
