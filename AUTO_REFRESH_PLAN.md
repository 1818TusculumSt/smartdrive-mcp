# SmartDrive Auto-Refresh Plan

**Status:** Approved
**Goal:** Single local MCP server, semantic search preserved, auto-refreshing index without manual crawler runs. No remote server, no second MCP server.

---

## The one gotcha that defines the design

Graph delta query (`/me/drive/root/delta`) **is** supported on personal OneDrive accounts. But two things constrain the design:

1. **No timestamp bootstrap on personal accounts.** The `?token=<timestamp>` form is only supported on OneDrive for Business/SharePoint. So the *first* sync — and any recovery — must be a **full crawl** to establish a baseline.

2. **Delta tokens can go stale** (HTTP `410 resyncRequired` / `404`). There is no documented expiration, but tokens can be invalidated by service-side cache eviction or drive maintenance. When that happens the code must **fall back to a full sync**.

**Net design:** *incremental wherever possible, full-resync when the checkpoint is invalid.* Both paths funnel into the same embed/upsert pipeline.

---

## Architecture

```
smartdrive_server.py  (single MCP server, spawned by Claude)
        │
        ├─ on startup → start background sync task (asyncio)
        │        ├─ load deltaLink from local store
        │        ├─ valid?  → incremental delta sync
        │        └─ invalid/missing → full crawl → rebuild
        │        └─ save new deltaLink
        │
        ├─ search_onedrive (query)  → Pinecone hybrid → Azure Blob full text
        │
        └─ read_document (query)    → Azure Blob by doc_id
```

**Key point:** the server stays **read-only against the cloud index for search**, exactly as agreed. The sync task only *writes* to Pinecone + Azure. Both live in the same process. Nothing remote.

---

## Key simplification

A "full sync" is just a delta query **without a token** — the first `/me/drive/root/delta` call enumerates everything and ends with a `@odata.deltaLink`. So `full_sync` and `incremental_sync` are the *same loop* with different starting URLs. The crawler's recursive folder walk does not need to be refactored into the sync path — only its extract→embed→upsert pipeline is extracted into a shared module. One code path, no drift; the interactive crawler CLI stays untouched.

## Codebase realities that shaped the design

1. **`onedrive_crawler.py` cannot be imported by the server.** It `print()`s at import time (stdout is the MCP JSON-RPC channel), calls `load_dotenv()` at module level, instantiates its own Pinecone/EmbeddingProvider/DocumentStorage singletons, and contains `input()` calls. Shared logic must live in a side-effect-free module with injected dependencies and stderr logging.
2. **`input()` trap:** `list_documents_folder(interactive=False, preflight=False)` still prompts for a new-folder check when a skip cache exists. The background sync must never route through `list_documents_folder`.
3. **Deletes arrive id-only.** Delta deletions provide `id` + `@removed` — no path. Since `doc_id` = SHA256(path) and `vector_id` = MD5(path), the delta store maintains a persistent `item_id → {path, doc_id, vector_id, modified, size}` map. This also resolves rename/move (same `item_id`, new path → delete old IDs, re-index under new path).
4. **The sync stack is synchronous.** It must run via `asyncio.to_thread()`; `create_task(sync_all())` directly would block the event loop. The low-level `mcp.server.Server` API has no lifespan support, so the task is spawned in `main()` inside the stdio context.

---

## Locked decisions

| Decision | Choice |
|---|---|
| Delta scope | Root delta (`/me/drive/root/delta`) + client-side `/Documents` path filter |
| Folder filter | Respect `~/.smartdrive_folder_skip_cache.json` (process / list-only / skip) |
| Sync cadence | Boot + every 15 min (`SMARTDRIVE_SYNC_INTERVAL` seconds; `0` = boot only) |
| Deployment | `python smartdrive_server.py` directly (local); no Docker changes |
| Auth in server | Silent-only (`get_access_token(silent_only=True)`); never device-code flow |

---

## Milestone plan

### Phase 1 — Shared indexing core (`indexing_core.py`)

New file, side-effect-free. Extracted from `onedrive_crawler.py`:

- `extract_text_from_file()`, `extract_text_from_zip_item()`, OCR helpers (moved, env read at call time)
- `generate_vector_id()`, `chunk_text()`
- `process_files(files_data, index, embedding_provider, document_storage)` — the extract→embed→upsert loop from `upload_to_pinecone()` internals, `print` → `logging`

`onedrive_crawler.py` imports these back so the CLI keeps working. One implementation, no drift.

### Phase 2 — Delta sync module (`delta_sync.py`)

- `DeltaStore` — `~/.smartdrive_delta_store.json` holding `{delta_link, item_map: {graph_id → {path, vector_id, doc_id, modified, size}}, last_sync}`; atomic tmp+rename writes
- `sync_all(index, embedding_provider, document_storage)`:
  - Silent token via `get_access_token(silent_only=True)`; if `None` → log, return
  - GET saved deltaLink (or bare `/me/drive/root/delta` first run) → page through `@odata.nextLink`, with 401 retry via token refresh (`token_ref` pattern)
  - Per item: `@removed`/`deleted` → map lookup → delete Pinecone vector + Azure blob; file → normalize path from `parentReference.path`, drop non-`/Documents`, apply skip-cache, skip unchanged (modified+size compare), else download (fallback `/items/{id}/content` if no `@microsoft.graph.downloadUrl`) → `process_files()`
  - Move detection: map path ≠ current path → delete old IDs, re-index new
  - On `410`/`404`: clear store, re-run from scratch; log everything, raise nothing
- CLI: `python delta_sync.py sync` for manual runs/testing

### Phase 3 — Wire into the MCP server

In `smartdrive_server.py` `main()`, inside the stdio context:

```python
sync_task = asyncio.create_task(run_sync_loop(index, embedding_provider, document_storage))
# ... app.run(...) ...
sync_task.cancel()
```

`run_sync_loop` does `await asyncio.to_thread(sync_all, ...)` at boot, then sleeps the configured interval. The server's existing `index`/`embedding_provider`/`document_storage` instances are passed in. Search tools are unchanged.

---

## What NOT to do (avoid over-engineering)

- **No webhooks/subscriptions.** They need a public callback URL and an always-on listener — that's a remote server, which we don't want. Polling delta on boot + a light periodic timer is enough.
- **No separate index daemon.** That's the two-server setup we killed. Sync lives *inside* the one server.
- **No timestamp bootstrap.** It won't work on personal accounts.
- **No refactoring of the recursive crawler walk into the sync path.** Delta enumeration replaces it.

---

## The honest tradeoff to sign off on

"Auto refresh without thinking" means **the index syncs when the server is alive** — which is whenever you're at Claude. If you add files and don't open Claude for a month, the index is a month stale until the next boot sync picks it up. That's the correct price for "one server, no remote."

---

## Test sequence

1. First run (no store) → full enumeration, deltaLink saved, indexed docs match manual crawler output
2. Add a file → restart → exactly 1 file processed
3. Delete a file → restart → vector gone from Pinecone, blob gone from Azure
4. Rename a file → old IDs deleted, new IDs created
5. Corrupt deltaLink manually → 410 → automatic full resync
6. Server answers `search_onedrive` immediately while sync runs (non-blocking check)
