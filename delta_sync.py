"""Background Microsoft Graph delta synchronization for OneDrive."""

import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import requests

from config import settings
from indexing_core import extract_file, generate_vector_id, process_files

logger = logging.getLogger(__name__)

DELTA_STORE_FILE = Path.home() / ".smartdrive_delta_store.json"
FOLDER_SKIP_CACHE_FILE = Path.home() / ".smartdrive_folder_skip_cache.json"
NAMESPACE = "smartdrive"
DELTA_URL = "https://graph.microsoft.com/v1.0/me/drive/root/delta"


class DeltaInvalidated(Exception):
    """The Graph delta checkpoint can no longer be used."""


class DeltaStore:
    def __init__(self, path=DELTA_STORE_FILE):
        self.path = Path(path)
        self.delta_link = None
        self.item_map = {}

    def _is_broken_mount(self):
        return self.path.is_dir()

    def load(self):
        if self._is_broken_mount():
            logger.warning("Delta store path %s is a directory (Docker file mount created a dir) — treating as empty and using ephemeral state", self.path)
            return self
        if not self.path.exists():
            return self
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            self.delta_link = data.get("delta_link")
            self.item_map = data.get("item_map", {})
        except (OSError, ValueError) as error:
            logger.warning("Could not load delta store; starting a full sync: %s", error)
            self.delta_link = None
            self.item_map = {}
        return self

    def save(self):
        if self._is_broken_mount():
            logger.warning("Delta store path %s is a directory — skipping persist (fix host: rm -rf %s && touch %s)", self.path, self.path, self.path)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "delta_link": self.delta_link,
            "item_map": self.item_map,
            "last_sync": datetime.now(timezone.utc).isoformat(),
        }
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def clear(self):
        self.delta_link = None
        self.item_map = {}
        if self._is_broken_mount():
            return
        if self.path.exists():
            try:
                self.path.unlink()
            except (IsADirectoryError, OSError):
                pass


def get_delta_link(path=DELTA_STORE_FILE):
    return DeltaStore(path).load().delta_link


def save_delta_link(link, path=DELTA_STORE_FILE):
    store = DeltaStore(path).load()
    store.delta_link = link
    store.save()


def _load_skip_cache():
    try:
        with FOLDER_SKIP_CACHE_FILE.open("r", encoding="utf-8") as file:
            value = json.load(file)
            return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _normalise_path(parent_path, name):
    """Convert Graph's /drive/root:/Documents form to crawler paths."""
    parent_path = unquote(parent_path or "")
    marker = ":/"
    if marker in parent_path:
        parent_path = parent_path.split(marker, 1)[1]
    parent_path = "/" + parent_path.strip("/")
    return f"{parent_path}/{name}" if name else parent_path


def _folder_mode(file_path, skip_cache):
    parent = file_path.rsplit("/", 1)[0]
    while parent.startswith("/Documents"):
        if parent in skip_cache:
            return skip_cache[parent]
        if parent == "/Documents":
            break
        parent = parent.rsplit("/", 1)[0]
    return "process"


def _is_documents_path(path):
    return path == "/Documents" or path.startswith("/Documents/")


def _is_deleted(item):
    return "@removed" in item or "deleted" in item


def _delete_entry(entry, index, document_storage):
    vector_id = entry.get("vector_id")
    doc_id = entry.get("doc_id")
    if vector_id:
        try:
            index.delete(ids=[vector_id], namespace=NAMESPACE)
        except Exception:
            logger.exception("Failed to delete Pinecone vector %s", vector_id)
    if doc_id:
        document_storage.delete_document(doc_id)


def _refresh_token(token_ref):
    from onedrive_crawler import get_access_token

    token = get_access_token(silent_only=True)
    if token:
        token_ref[0] = token
        return True
    logger.error("Microsoft token refresh failed; sync will stop")
    return False


def _get_page(url, token_ref):
    for attempt in range(2):
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token_ref[0]}"},
            timeout=60,
        )
        if response.status_code in (401, 400) and attempt == 0:
            if _refresh_token(token_ref):
                continue
        if response.status_code in (404, 410):
            raise DeltaInvalidated(response.text)
        if response.status_code != 200:
            raise RuntimeError(
                f"Graph delta request failed ({response.status_code}): {response.text}"
            )
        return response.json()
    raise RuntimeError("Graph authentication failed after token refresh")


def _process_file(item, path, store, token, index, embedding_provider, document_storage,
                  mode):
    modified = item.get("lastModifiedDateTime", "")
    size = item.get("size", 0)
    old_entry = store.item_map.get(item["id"])
    new_vector_id = generate_vector_id(path)
    new_doc_id = document_storage.generate_doc_id(path)

    if old_entry and old_entry.get("path") != path:
        logger.info("OneDrive move/rename: %s -> %s", old_entry.get("path"), path)
        _delete_entry(old_entry, index, document_storage)
        old_entry = None
    elif (old_entry and old_entry.get("modified") == modified
          and old_entry.get("size", 0) == size):
        return
    elif old_entry:
        # The shared uploader intentionally avoids overwriting existing blobs;
        # remove the previous version before indexing changed content.
        _delete_entry(old_entry, index, document_storage)
        old_entry = None

    if mode == "skip":
        store.item_map.pop(item["id"], None)
        if old_entry:
            _delete_entry(old_entry, index, document_storage)
        return

    if mode == "list-only":
        text = (
            f"File: {item.get('name', '')}\n"
            f"Location: {path}\n"
            f"Size: {size} bytes\n"
            "Type: metadata-only folder setting"
        )
    else:
        if not item.get("@microsoft.graph.downloadUrl"):
            # Delta metadata normally includes downloadUrl. If it does not,
            # resolve the content redirect before calling the shared extractor.
            response = requests.get(
                f"https://graph.microsoft.com/v1.0/me/drive/items/{item['id']}/content",
                headers={"Authorization": f"Bearer {token}"},
                allow_redirects=False,
                timeout=60,
            )
            if response.is_redirect and response.headers.get("Location"):
                item["@microsoft.graph.downloadUrl"] = response.headers["Location"]
        text = extract_file(token, item)
        if text is None:
            logger.warning("Could not extract %s; retaining prior index entry", path)
            return

    file_data = {
        "name": item.get("name", path.rsplit("/", 1)[-1]),
        "path": path,
        "text": text,
        "size": size,
        "modified": modified,
    }
    process_files([file_data], index, embedding_provider, document_storage)
    store.item_map[item["id"]] = {
        "path": path,
        "vector_id": new_vector_id,
        "doc_id": new_doc_id,
        "modified": modified,
        "size": size,
    }


def _run_delta(start_url, store, token_ref, index, embedding_provider, document_storage):
    skip_cache = _load_skip_cache()
    url = start_url
    processed = 0
    deleted = 0
    while url:
        page = _get_page(url, token_ref)
        for item in page.get("value", []):
            item_id = item.get("id")
            if not item_id:
                continue
            if _is_deleted(item):
                old_entry = store.item_map.pop(item_id, None)
                if old_entry:
                    _delete_entry(old_entry, index, document_storage)
                    deleted += 1
                continue
            if "file" not in item:
                continue
            path = _normalise_path(item.get("parentReference", {}).get("path"), item.get("name"))
            if not _is_documents_path(path):
                # A move out of /Documents is represented as a normal file item,
                # so remove the previously indexed path even without @removed.
                old_entry = store.item_map.pop(item_id, None)
                if old_entry:
                    _delete_entry(old_entry, index, document_storage)
                continue
            mode = _folder_mode(path, skip_cache)
            _process_file(item, path, store, token_ref[0], index, embedding_provider,
                          document_storage, mode)
            processed += 1
        url = page.get("@odata.nextLink")
        if not url:
            delta_link = page.get("@odata.deltaLink")
            if not delta_link:
                raise RuntimeError("Graph delta response did not include @odata.deltaLink")
            store.delta_link = delta_link
    store.save()
    logger.info("Delta sync complete: processed=%d deleted=%d", processed, deleted)
    return store.delta_link


def full_sync(index, embedding_provider, document_storage, store=None):
    """Rebuild the tracked index using a tokenless delta enumeration."""
    store = store or DeltaStore().load()
    for entry in list(store.item_map.values()):
        _delete_entry(entry, index, document_storage)
    store.clear()
    token = _get_token()
    if not token:
        return None
    return _run_delta(DELTA_URL, store, [token], index, embedding_provider, document_storage)


def incremental_sync(delta_link, index, embedding_provider, document_storage, store=None):
    store = store or DeltaStore().load()
    token = _get_token()
    if not token:
        return None
    return _run_delta(delta_link, store, [token], index, embedding_provider, document_storage)


def _get_token():
    from onedrive_crawler import get_access_token

    token = get_access_token(silent_only=True)
    if not token:
        logger.warning("No cached Microsoft token available; skipping background sync")
    return token


def sync_all(index, embedding_provider, document_storage):
    """Run one sync pass; failures are logged and never escape to the server."""
    store = DeltaStore().load()
    try:
        if store.delta_link:
            try:
                return incremental_sync(store.delta_link, index, embedding_provider,
                                        document_storage, store)
            except DeltaInvalidated:
                logger.warning("Delta link is stale; starting a full resync")
        return full_sync(index, embedding_provider, document_storage, store)
    except Exception:
        logger.exception("Background OneDrive sync failed")
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2 or sys.argv[1] == "sync":
        from pinecone import Pinecone
        from embeddings import EmbeddingProvider
        from document_storage import DocumentStorage

        pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        sync_all(
            pc.Index(name=settings.PINECONE_INDEX_NAME, host=settings.PINECONE_HOST),
            EmbeddingProvider(init_bm25=True),
            DocumentStorage(),
        )
