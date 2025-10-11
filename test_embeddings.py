"""Test script to verify Pinecone embedding provider works"""
import asyncio
import sys
from embeddings import EmbeddingProvider
from config import settings

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

async def test_embeddings():
    print(f"Testing embedding provider: {settings.EMBEDDING_PROVIDER}")
    print(f"Model: {settings.EMBEDDING_MODEL}\n")

    provider = EmbeddingProvider()

    test_text = "This is a test document about machine learning and artificial intelligence."
    print(f"Test text: {test_text}\n")

    print("Generating embedding...")
    embedding = await provider.get_embedding(test_text)

    if embedding is None:
        print("FAILED: Could not generate embedding!")
        return False

    print(f"SUCCESS: Generated embedding!")
    print(f"Dimension: {len(embedding)}")
    print(f"Sample values: {embedding[:5]}")
    print(f"L2 norm: {(embedding ** 2).sum() ** 0.5:.4f}")

    await provider.close()
    return True

if __name__ == "__main__":
    success = asyncio.run(test_embeddings())
    if success:
        print("\nAll tests passed!")
    else:
        print("\nTests failed!")
