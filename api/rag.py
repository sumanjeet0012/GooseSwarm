"""
Distributed RAG API endpoints.

POST /api/v1/rag/ask
    Distributed RAG query — searches locally and across peers.
    Body:  {"question": "..."}
    Response: {
        "success": true,
        "answer": "...",
        "sources": ["file.py", ...],
        "peers_queried": ["Qm...", ...]
    }

POST /api/v1/rag/ingest
    Upload a file (multipart/form-data, field name "file") and ingest it into
    the local ChromaDB vector store.  Supported types: .txt .md .py .js .ts
    .json .yaml .yml .rst .csv .html .xml  (anything UTF-8 readable).
    Response: {
        "success": true,
        "filename": "...",
        "chunks_added": 42,
        "doc_count": 1234
    }

GET /api/v1/rag/status
    Returns whether this node is a RAG provider and basic metadata stats.

POST /api/v1/rag/publish
    Re-publish this node's RAG metadata to the DHT (admin/debug endpoint).

GET /api/v1/rag/peers
    Discover RAG-capable peers via DHT.
"""

import json
import logging

import tornado.web

from .base import BaseHandler

log = logging.getLogger("api.rag")


class DistributedAskHandler(tornado.web.RequestHandler):
    """
    POST /api/v1/rag/ask

    Runs the full distributed RAG query:
      local search → peer discovery → peer queries → merge → LLM answer.
    """

    def initialize(self, service, vectorstore, rag_client):
        self.service    = service
        self.vectorstore = vectorstore
        self.rag_client  = rag_client   # DistributedRAGClient (or None)

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")
        self.set_header("Content-Type", "application/json")

    async def options(self):
        self.set_status(204)
        self.finish()

    async def post(self):
        if self.rag_client is None:
            self.set_status(503)
            self.finish(json.dumps({
                "success": False,
                "error": "Distributed RAG is not available. Vector store not loaded.",
            }))
            return

        try:
            body     = json.loads(self.request.body)
            question = body.get("question", "").strip()
        except (json.JSONDecodeError, AttributeError):
            self.set_status(400)
            self.finish(json.dumps({
                "success": False,
                "error": "Request body must be JSON with a 'question' field.",
            }))
            return

        if not question:
            self.set_status(400)
            self.finish(json.dumps({
                "success": False,
                "error": "'question' cannot be empty.",
            }))
            return

        try:
            # Run the distributed RAG query on the trio thread via the queue+Event
            # pattern (same as find_capability_providers). Never call trio
            # coroutines directly from the Tornado/asyncio thread.
            import asyncio
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.service.run_rag_query(question, timeout=60),
            )
        except Exception as exc:
            log.error("Distributed RAG query failed: %s", exc)
            self.set_status(500)
            self.finish(json.dumps({
                "success": False,
                "error": f"Distributed RAG query failed: {exc}",
            }))
            return

        self.finish(json.dumps({
            "success":       True,
            "answer":        result.get("answer", ""),
            "sources":       result.get("sources", []),
            "peers_queried": result.get("peers_queried", []),
        }))


class RAGStatusHandler(BaseHandler):
    """
    GET /api/v1/rag/status

    Returns this node's RAG provider status and metadata stats.
    """

    def initialize(self, service, vectorstore, metadata_manager):
        self.service          = service
        self.vectorstore      = vectorstore
        self.metadata_manager = metadata_manager

    def get(self):
        is_provider = False
        doc_count   = 0
        keywords    = []

        if self.vectorstore is not None:
            try:
                col       = self.vectorstore._collection
                result    = col.get(include=["documents"])
                doc_count = len(result.get("documents") or [])
                is_provider = doc_count > 0
            except Exception:
                pass

        meta = getattr(self.metadata_manager, "_metadata", {}) if self.metadata_manager else {}
        keywords = meta.get("keywords", [])[:20]

        registry  = getattr(self.service, "capability_registry", None)
        announced = registry.get_announced() if registry else []
        from capabilities import CapabilityKey
        rag_announced = CapabilityKey.RAG_PROVIDER in announced

        self.send_success({
            "is_rag_provider":  is_provider,
            "rag_announced":    rag_announced,
            "doc_count":        doc_count,
            "top_keywords":     keywords,
            "vectorstore_ready": self.vectorstore is not None,
        })


class RAGPublishHandler(BaseHandler):
    """
    POST /api/v1/rag/publish

    Re-publish this node's RAG metadata to the DHT (admin/debug endpoint).
    """

    def initialize(self, service, vectorstore, metadata_manager):
        self.service          = service
        self.vectorstore      = vectorstore
        self.metadata_manager = metadata_manager

    async def post(self):
        if not self.require_ready():
            return

        if self.metadata_manager is None or self.vectorstore is None:
            self.send_error_response("RAG metadata manager or vector store not available.", status=503)
            return

        try:
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.service._rag_metadata_manager.publish(
                    self.service._rag_query_server._vectorstore
                ) if hasattr(self.service._rag_metadata_manager, 'publish') else None,
            )
        except Exception as exc:
            log.error("RAG metadata publish failed: %s", exc)
            self.send_error_response(f"Publish failed: {exc}", status=500)
            return

        meta = getattr(self.metadata_manager, "_metadata", {})
        self.send_success({
            "message":   "RAG metadata published to DHT.",
            "doc_count": meta.get("doc_count", 0),
            "keywords":  meta.get("keywords", [])[:20],
        })


class RAGPeersHandler(BaseHandler):
    """
    GET /api/v1/rag/peers

    Discover RAG-capable peers via DHT find_providers.
    """

    def initialize(self, service, vectorstore, rag_client):
        self.service     = service
        self.vectorstore = vectorstore
        self.rag_client  = rag_client

    async def get(self):
        if not self.require_ready():
            return

        registry = getattr(self.service, "capability_registry", None)
        if registry is None:
            self.send_error_response("Capability registry not available.", status=503)
            return

        try:
            import asyncio
            from capabilities import CapabilityKey
            loop = asyncio.get_event_loop()
            peer_infos = await loop.run_in_executor(
                None,
                lambda: self.service.find_capability_providers(CapabilityKey.RAG_PROVIDER, 20),
            )
            my_id = str(self.service.host.get_id()) if self.service.host else ""
            peers = [
                {"peer_id": str(p.peer_id), "addrs": [str(a) for a in (p.addrs or [])]}
                for p in peer_infos
                if str(p.peer_id) != my_id
            ]
        except Exception as exc:
            log.error("RAG peer discovery failed: %s", exc)
            self.send_error_response(f"Peer discovery failed: {exc}", status=500)
            return

        self.send_success({
            "rag_peers": peers,
            "count":     len(peers),
        })


# ── Ingest ────────────────────────────────────────────────────────────────────

_ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".json", ".yaml", ".yml", ".rst", ".csv", ".html", ".xml",
    ".toml", ".cfg", ".ini", ".sh", ".go", ".rs", ".c", ".cpp",
    ".h", ".java", ".rb", ".php", ".swift", ".kt",
    ".pdf",
}


def _extract_text(body: bytes, filename: str) -> str:
    """
    Extract plain text from *body*.

    For PDF files, uses ``pypdf`` (preferred) or ``pdfminer.six`` as a
    fallback.  For all other file types the bytes are decoded as UTF-8.
    """
    import os
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".pdf":
        # ── Try pypdf first ───────────────────────────────────────────
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(body))
            pages = []
            for page in reader.pages:
                page_text = page.extract_text() or ""
                pages.append(page_text)
            return "\n\n".join(pages)
        except ImportError:
            pass
        except Exception as exc:
            log.warning("pypdf failed for '%s': %s — trying pdfminer", filename, exc)

        # ── Fallback: pdfminer.six ────────────────────────────────────
        try:
            import io
            from pdfminer.high_level import extract_text as pdfminer_extract
            return pdfminer_extract(io.BytesIO(body))
        except ImportError:
            raise ImportError(
                "PDF parsing requires 'pypdf' or 'pdfminer.six'. "
                "Install one: pip install pypdf"
            )
        except Exception as exc:
            raise RuntimeError(f"Could not extract text from PDF: {exc}") from exc

    # ── Plain text / source code ──────────────────────────────────────
    return body.decode("utf-8", errors="replace")


class RAGIngestHandler(tornado.web.RequestHandler):
    """
    POST /api/v1/rag/ingest

    Accepts a multipart/form-data upload with a single field named ``file``.
    Chunks the file text and adds the chunks to the local ChromaDB vector store.
    """

    def initialize(self, vectorstore, metadata_manager):
        self.vectorstore      = vectorstore
        self.metadata_manager = metadata_manager

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")
        self.set_header("Content-Type", "application/json")

    async def options(self):
        self.set_status(204)
        self.finish()

    async def post(self):
        import os
        import json as _json
        import tempfile

        if self.vectorstore is None:
            self.set_status(503)
            self.finish(_json.dumps({
                "success": False,
                "error": "Vector store not initialised. Run build_vectorstore.py first.",
            }))
            return

        # ── Parse multipart upload ────────────────────────────────────
        files = self.request.files.get("file")
        if not files:
            self.set_status(400)
            self.finish(_json.dumps({"success": False, "error": "No file field in request."}))
            return

        file_info = files[0]
        filename  = file_info.get("filename", "upload.txt")
        body      = file_info["body"]

        ext = os.path.splitext(filename)[1].lower()
        if ext not in _ALLOWED_EXTENSIONS:
            self.set_status(400)
            self.finish(_json.dumps({
                "success": False,
                "error": (
                    f"Unsupported file type '{ext}'. "
                    f"Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
                ),
            }))
            return

        # ── Extract text (PDF-aware) ──────────────────────────────────
        try:
            text = _extract_text(body, filename)
        except (ImportError, RuntimeError) as exc:
            self.set_status(400)
            self.finish(_json.dumps({"success": False, "error": str(exc)}))
            return
        except Exception as exc:
            self.set_status(400)
            self.finish(_json.dumps({"success": False, "error": f"Cannot read file: {exc}"}))
            return

        if not text.strip():
            self.set_status(400)
            self.finish(_json.dumps({"success": False, "error": "Uploaded file is empty."}))
            return

        # ── Chunk + embed + store ─────────────────────────────────────
        try:
            from langchain_core.documents import Document
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=300,
                chunk_overlap=30,
                separators=["\nclass ", "\ndef ", "\n\n", "\n", " "],
            )
            doc    = Document(page_content=text, metadata={"source": filename})
            chunks = splitter.split_documents([doc])

            if not chunks:
                self.set_status(400)
                self.finish(_json.dumps({"success": False, "error": "File produced no chunks."}))
                return

            # Add to ChromaDB (runs in thread to avoid blocking the event loop)
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.vectorstore.add_documents, chunks)

            # Count total docs after ingestion
            try:
                total = self.vectorstore._collection.count()
            except Exception:
                total = -1

            log.info("📄 Ingested '%s': %d chunks (total docs: %d)", filename, len(chunks), total)

        except Exception as exc:
            log.error("RAG ingest failed for '%s': %s", filename, exc)
            self.set_status(500)
            self.finish(_json.dumps({"success": False, "error": f"Ingestion failed: {exc}"}))
            return

        self.finish(_json.dumps({
            "success":      True,
            "filename":     filename,
            "chunks_added": len(chunks),
            "doc_count":    total,
        }))


# ── List & Delete ingested files ──────────────────────────────────────────────

class RAGFilesHandler(tornado.web.RequestHandler):
    """
    GET  /api/v1/rag/files
        List every unique source (filename) currently in the vector store,
        together with its chunk count.
        Response: {"success": true, "files": [{"filename": "...", "chunks": 42}, ...]}

    DELETE /api/v1/rag/files
        Body: {"filename": "report.pdf"}
        Removes ALL chunks whose metadata source == filename from ChromaDB.
        Response: {"success": true, "filename": "...", "chunks_deleted": 42, "doc_count": 999}
    """

    def initialize(self, vectorstore):
        self.vectorstore = vectorstore

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, DELETE, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")
        self.set_header("Content-Type", "application/json")

    async def options(self):
        self.set_status(204)
        self.finish()

    def get(self):
        import json as _json
        if self.vectorstore is None:
            self.set_status(503)
            self.finish(_json.dumps({"success": False, "error": "Vector store not available."}))
            return
        try:
            # Fetch in pages of 500 to avoid SQLite "too many SQL variables"
            PAGE = 500
            counts: dict = {}
            offset = 0
            while True:
                result = self.vectorstore._collection.get(
                    include=["metadatas"],
                    limit=PAGE,
                    offset=offset,
                )
                batch = result.get("metadatas") or []
                if not batch:
                    break
                for meta in batch:
                    src = (meta or {}).get("source", "<unknown>")
                    counts[src] = counts.get(src, 0) + 1
                if len(batch) < PAGE:
                    break
                offset += PAGE
            files = [{"filename": src, "chunks": n} for src, n in sorted(counts.items())]
            self.finish(_json.dumps({"success": True, "files": files}))
        except Exception as exc:
            log.error("RAG files list failed: %s", exc)
            self.set_status(500)
            self.finish(_json.dumps({"success": False, "error": str(exc)}))

    async def delete(self):
        import json as _json
        import asyncio

        if self.vectorstore is None:
            self.set_status(503)
            self.finish(_json.dumps({"success": False, "error": "Vector store not available."}))
            return

        try:
            body     = _json.loads(self.request.body)
            filename = body.get("filename", "").strip()
        except Exception:
            filename = ""

        if not filename:
            self.set_status(400)
            self.finish(_json.dumps({"success": False, "error": "Missing 'filename' in request body."}))
            return

        try:
            # Find all IDs whose source metadata matches the filename
            result = self.vectorstore._collection.get(
                where={"source": filename},
                include=["metadatas"],
            )
            ids = result.get("ids") or []

            if not ids:
                self.set_status(404)
                self.finish(_json.dumps({
                    "success": False,
                    "error": f"No chunks found for '{filename}'.",
                }))
                return

            # Delete in batches of 100 to avoid SQLite "too many SQL variables"
            # (SQLite's default limit is 999 bound parameters).
            BATCH = 100
            loop = asyncio.get_event_loop()
            for i in range(0, len(ids), BATCH):
                batch = ids[i : i + BATCH]
                await loop.run_in_executor(
                    None,
                    lambda b=batch: self.vectorstore._collection.delete(ids=b),
                )

            # Count remaining docs (use count() API to avoid fetching all IDs)
            try:
                total = self.vectorstore._collection.count()
            except Exception:
                total = -1

            log.info("🗑️  Deleted '%s': %d chunks removed (total remaining: %d)", filename, len(ids), total)
            self.finish(_json.dumps({
                "success":        True,
                "filename":       filename,
                "chunks_deleted": len(ids),
                "doc_count":      total,
            }))

        except Exception as exc:
            log.error("RAG delete failed for '%s': %s", filename, exc)
            self.set_status(500)
            self.finish(_json.dumps({"success": False, "error": f"Delete failed: {exc}"}))
