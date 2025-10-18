"""
Create Pinecone hybrid search index via API
Run this once to create the index with sparse + dense vector support
"""
from pinecone import Pinecone, ServerlessSpec
from config import settings

# Initialize Pinecone
pc = Pinecone(api_key=settings.PINECONE_API_KEY)

# Index name
index_name = "smartdrive"

# Delete old index if exists
try:
    pc.delete_index(index_name)
    print(f"✅ Deleted old index: {index_name}")
except:
    print(f"ℹ️  No existing index to delete")

# Create new hybrid index
print(f"\n🔨 Creating hybrid search index: {index_name}")
print(f"   Dimensions: 2048 (Voyage AI)")
print(f"   Metric: dotproduct")
print(f"   Type: Serverless (AWS us-east-1)")
print(f"   Hybrid: Dense + Sparse vectors ✓")

pc.create_index(
    name=index_name,
    dimension=2048,
    metric="dotproduct",
    spec=ServerlessSpec(
        cloud="aws",
        region="us-east-1"
    )
)

print(f"\n✅ Index created successfully!")
print(f"   Host: {pc.describe_index(index_name).host}")
print(f"\n⚠️  Note: Pinecone serverless indexes support sparse vectors by default!")
print(f"   You can now upload dense + sparse vectors to this index.")
