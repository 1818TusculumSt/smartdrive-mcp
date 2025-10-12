import os
import json
from mcp.server import Server
from mcp.types import Tool, TextContent
from pinecone import Pinecone
from embeddings import EmbeddingProvider
from config import settings
from document_storage import DocumentStorage

# Don't load .env - use environment vars from Claude config
# load_dotenv()  # REMOVE THIS LINE

# Initialize
app = Server("smartdrive-mcp")
pc = Pinecone(api_key=settings.PINECONE_API_KEY)
index = pc.Index(
    name=settings.PINECONE_INDEX_NAME,
    host=settings.PINECONE_HOST
)
embedding_provider = EmbeddingProvider()
document_storage = DocumentStorage()

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools"""
    return [
        Tool(
            name="search_onedrive",
            description="Hybrid search across OneDrive documents using both semantic and keyword matching. Returns relevant file snippets based on your query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., '1099 tax forms', 'project proposal')"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (default: 5)",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls"""
    if name == "search_onedrive":
        query = arguments["query"]
        top_k = arguments.get("top_k", 5)

        # Generate dense query embedding (semantic)
        query_embedding = await embedding_provider.get_embedding(query)

        if query_embedding is None:
            return [TextContent(
                type="text",
                text="❌ Failed to generate dense embedding for query."
            )]

        query_embedding = query_embedding.tolist()

        # Generate sparse query embedding (keyword/BM25) for hybrid search
        sparse_query_embedding = await embedding_provider.get_sparse_embedding(query)

        # Search Pinecone with hybrid search (dense + sparse)
        query_params = {
            "vector": query_embedding,
            "top_k": top_k,
            "namespace": "smartdrive",
            "include_metadata": True
        }

        # Add sparse vector if generated successfully
        if sparse_query_embedding:
            query_params["sparse_vector"] = sparse_query_embedding

        results = index.query(**query_params)

        # Format results
        if not results.matches:
            return [TextContent(
                type="text",
                text="No matching documents found."
            )]

        output = f"🔍 Found {len(results.matches)} results for: '{query}'\n\n"

        # Group results by doc_id to show full documents (not just chunks)
        doc_results = {}
        for match in results.matches:
            meta = match.metadata
            doc_id = meta.get('doc_id')

            if doc_id and doc_id not in doc_results:
                # First time seeing this document - retrieve full text from Azure Blob
                full_text = document_storage.retrieve_document(doc_id)

                if full_text:
                    doc_results[doc_id] = {
                        "file_name": meta.get('file_name', 'Unknown'),
                        "file_path": meta.get('file_path', 'Unknown'),
                        "modified": meta.get('modified', 'Unknown'),
                        "score": match.score,  # Use score from first matching chunk
                        "full_text": full_text
                    }

        # Format output with full documents
        for i, (doc_id, doc_info) in enumerate(doc_results.items(), 1):
            output += f"**Result {i}** (Score: {doc_info['score']:.3f})\n"
            output += f"📄 **File:** {doc_info['file_name']}\n"
            output += f"📁 **Path:** {doc_info['file_path']}\n"
            output += f"📅 **Modified:** {doc_info['modified']}\n"
            output += f"📝 **Content:**\n{doc_info['full_text']}\n\n"
            output += "---\n\n"

        return [TextContent(type="text", text=output)]
    
    raise ValueError(f"Unknown tool: {name}")

if __name__ == "__main__":
    import asyncio
    import mcp.server.stdio
    
    async def main():
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )
    
    asyncio.run(main())
