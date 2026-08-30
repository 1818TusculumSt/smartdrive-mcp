# AGENTS.md — SmartDrive MCP

## What this is
Single local Streamable HTTP MCP server giving Claude hybrid semantic search over a personal
OneDrive. Vectors + metadata in Pinecone (namespace `smartdrive`), full document text
in Azure Blob Storage. A background delta-sync task keeps the index fresh; no remote
server, no second MCP server, no webhooks.

## Architecture
- `smartdrive_server.py` — Streamable HTTP MCP server. Tools: `search_onedrive`,
  `read_document`. Read-only against the cloud index. Spawns background sync loop
  on startup.
- `delta_sync.py` — Graph delta sync (`/me/drive/root/delta`, client-side
  `/Documents` filter). Incremental via deltaLink; on 410/404 (stale token) falls
  back to full enumeration. State in `~/.smartdrive_delta_store.json` (atomic writes).
- `indexing_core.py` — shared extract→embed→upsert pipeline. The ONLY place that
  talks to Pinecone/Azure for writes. Used by both delta sync and the crawler.
- `onedrive_crawler.py` — interactive manual CLI. Imports indexing helpers from
  `indexing_core.py`; never imported by the server.
- `embeddings.py` — `EmbeddingProvider` (dense + BM25 sparse).
- `document_storage.py` — Azure Blob doc store. `doc_id` = `doc_<sha256(path)[:16]>`.
- `config.py` — pydantic settings from env vars (host env / Docker `.env`).

## CRITICAL rules (violations break the server)
1. **Never `print()` or `input()` in server/shared code.** Use `logging` to stderr.
   Streamable HTTP no longer uses stdout for JSON-RPC, but stdout/stderr discipline
   keeps logs clean and shared modules safe to reuse.
2. **Shared modules must be side-effect-free at import.** No client instantiation,
   no `load_dotenv()`, no I/O at module level. Dependencies (index, embedding provider,
   document storage) are passed in as parameters.
3. **Never block the event loop.** Sync work (Graph calls, embedding, uploads) runs
   via `asyncio.to_thread()`. `get_embedding_sync()` needs a worker thread's own loop.
4. **Server auth is silent-only:** `get_access_token(silent_only=True)`. If it returns
   None, log and bail — never trigger device-code flow inside the server.
5. **Background sync errors: log, never raise.** The server must answer queries
   immediately regardless of sync state.
6. **ID scheme is path-derived** (`doc_id` = SHA256(path), `vector_id` = MD5(path)).
   Graph deletes arrive id-only → resolve via the persistent `item_map` in the delta
   store. Moves/renames = delete old IDs + re-index under new path.

## Sync semantics (personal OneDrive)
- No `?token=<timestamp>` bootstrap — first sync and every recovery is a full
  enumeration (delta query without a token IS the full crawl; same loop, no
  separate code path).
- Respect `~/.smartdrive_folder_skip_cache.json` (process / list-only / skip).
- Cadence: boot + every 15 min (`SMARTDRIVE_SYNC_INTERVAL` seconds; `0` = boot only).
- Token refresh mid-sync follows the `token_ref` list pattern from the crawler.

## Commands
- MCP server: `python smartdrive_server.py` (Streamable HTTP on `127.0.0.1:8000`; `--host`/`--port` to override)
- Health check: `curl http://127.0.0.1:8000/healthz`
- Manual crawl (interactive): `python onedrive_crawler.py`
- Manual delta sync: `python delta_sync.py sync`

## Testing
No test framework. Verify changes manually:
first run → full crawl; add file → restart → only that file syncs; delete file →
gone from Pinecone + Blob; rename → old IDs removed/new added; corrupt deltaLink →
410 → auto full resync; server answers search while sync runs.

## Environment
Launched as `python smartdrive_server.py` (Streamable HTTP on `127.0.0.1:8000`). Env vars
supply all secrets (Pinecone, Azure, Microsoft client id). Token cache at
`~/.smartdrive_token_cache.json`. Python 3.12+; deps in `requirements.txt`.
