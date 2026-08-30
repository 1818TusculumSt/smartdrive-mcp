import os
import sys
import json
import logging
import asyncio
import argparse
import contextlib
from mcp.server import Server
from mcp.types import Tool, TextContent
from pinecone import Pinecone
from embeddings import EmbeddingProvider
from config import settings
from document_storage import DocumentStorage
from delta_sync import sync_all

# Configure logging to stderr (keep stdout clean for Uvicorn access logs)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)

logger = logging.getLogger(__name__)

# Silence noisy Azure SDK logging
logging.getLogger('azure').setLevel(logging.WARNING)
logging.getLogger('azure.core.pipeline.policies.http_logging_policy').setLevel(logging.WARNING)

# Don't load .env in the server - use environment vars from the host/systemd/Docker env
# load_dotenv()  # intentionally not called

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
        ),
        Tool(
            name="read_document",
            description="Retrieve the full text of a specific document from Azure Blob Storage using its document ID. Use this when you need the complete content of a document that was found in search results.",
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "Document ID (e.g., 'doc_abc123def456') obtained from search results"
                    }
                },
                "required": ["doc_id"]
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

        # Add sparse vector if generated successfully AND non-empty
        # Pinecone requires sparse vectors to have at least one value
        if sparse_query_embedding and len(sparse_query_embedding.get("values", [])) > 0:
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

        # Format output with document summaries (prevent 1MB limit issues)
        MAX_PREVIEW_CHARS = 2000  # Show first 2000 chars per document
        MAX_TOTAL_SIZE = 900_000  # Keep total response under 900KB (well below 1MB limit)

        current_size = len(output)

        for i, (doc_id, doc_info) in enumerate(doc_results.items(), 1):
            full_text = doc_info['full_text']
            text_length = len(full_text)

            # Truncate if needed
            if text_length > MAX_PREVIEW_CHARS:
                preview_text = full_text[:MAX_PREVIEW_CHARS] + f"\n\n... [Truncated: {text_length - MAX_PREVIEW_CHARS:,} more characters in full document]"
            else:
                preview_text = full_text

            result_block = (
                f"**Result {i}** (Score: {doc_info['score']:.3f})\n"
                f"📄 **File:** {doc_info['file_name']}\n"
                f"📁 **Path:** {doc_info['file_path']}\n"
                f"📅 **Modified:** {doc_info['modified']}\n"
                f"📊 **Size:** {text_length:,} characters\n"
                f"🔑 **Document ID:** `{doc_id}`\n"
                f"📝 **Preview:**\n{preview_text}\n\n"
                f"---\n\n"
            )

            # Check if adding this result would exceed total size limit
            if current_size + len(result_block) > MAX_TOTAL_SIZE:
                output += f"\n⚠️ **Remaining results omitted** (response size limit reached)\n"
                break

            output += result_block
            current_size += len(result_block)

        return [TextContent(type="text", text=output)]

    elif name == "read_document":
        doc_id = arguments["doc_id"]

        # Retrieve full document text from Azure Blob Storage
        full_text = document_storage.retrieve_document(doc_id)

        if full_text is None:
            return [TextContent(
                type="text",
                text=f"❌ Document not found: {doc_id}\n\nThe document may have been deleted or the doc_id may be incorrect."
            )]

        # Return full document with metadata
        output = (
            f"📄 **Document ID:** {doc_id}\n"
            f"📊 **Size:** {len(full_text):,} characters\n\n"
            f"**Full Text:**\n{full_text}"
        )

        return [TextContent(type="text", text=output)]

    raise ValueError(f"Unknown tool: {name}")

async def run_sync_loop():
    """Run blocking Graph/index work off the MCP event loop."""
    interval = settings.SMARTDRIVE_SYNC_INTERVAL
    while True:
        await asyncio.to_thread(sync_all, index, embedding_provider, document_storage)
        if interval <= 0:
            return
        await asyncio.sleep(interval)


def run_http(host="127.0.0.1", port=8000):
    """Run the stateless Streamable HTTP MCP server."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route
    from starlette.types import Receive, Scope, Send
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    import uvicorn

    session_manager = StreamableHTTPSessionManager(
        app=app,
        event_store=None,
        json_response=False,
        stateless=True,
    )

    async def handle_streamable_http(scope: Scope, receive: Receive, send: Send):
        await session_manager.handle_request(scope, receive, send)

    async def healthz(request):
        return JSONResponse({"status": "ok"})

    @contextlib.asynccontextmanager
    async def lifespan(starlette_app):
        sync_task = asyncio.create_task(run_sync_loop())
        async with session_manager.run():
            try:
                yield
            finally:
                sync_task.cancel()
                await asyncio.gather(sync_task, return_exceptions=True)

    starlette_app = Starlette(
        routes=[
            Route("/mcp", endpoint=handle_streamable_http, methods=["GET", "POST", "DELETE"]),
            Route("/mcp/", endpoint=handle_streamable_http, methods=["GET", "POST", "DELETE"]),
            Route("/healthz", endpoint=healthz, methods=["GET"]),
        ],
        lifespan=lifespan,
    )
    logger.info("Starting Streamable HTTP server on http://%s:%d/mcp", host, port)
    uvicorn.run(starlette_app, host=host, port=port)


def parse_args():
    parser = argparse.ArgumentParser(description="SmartDrive Streamable HTTP server")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument("--port", type=int, default=8000, help="HTTP bind port")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_http(args.host, args.port)
