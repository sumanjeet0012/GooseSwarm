"""
Distributed RAG — peer-to-peer knowledge retrieval.

This module implements the full distributed RAG query flow described in
``Distributed RAG.md``:

  1. Search locally (ChromaDB)
  2. Discover RAG-capable peers via DHT (capability: rag-provider/v1.0)
  3. Filter peers by embedding-summary similarity
  4. Query best peers over libp2p streams  (/rag/query/1.0.0)
  5. Merge + rerank chunks
  6. Pass to LLM for final answer

It also provides:
  - ``RAGMetadataManager`` – registers this node's document metadata in the DHT
    (VALUE STORE: ``peer_metadata:<peer_id>``) and re-announces the
    ``rag-provider/v1.0`` capability.
  - ``RAGQueryServer`` – handles incoming /rag/query/1.0.0 streams from peers.
  - ``DistributedRAGClient`` – orchestrates the full query flow.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("distributed_rag")

# ── Protocol constants ─────────────────────────────────────────────────────
RAG_QUERY_PROTOCOL = "/rag/query/1.0.0"
RAG_MAX_PAYLOAD    = 4 * 1024 * 1024   # 4 MB
TOP_K_LOCAL        = 4
TOP_K_REMOTE       = 3
MAX_PEERS_TO_QUERY = 3
MIN_LOCAL_SCORE    = 0.75  # cosine similarity threshold to skip remote search

# ── Metadata helpers ───────────────────────────────────────────────────────

def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Simple cosine similarity between two equal-length vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot  = sum(x * y for x, y in zip(a, b))
    na   = sum(x * x for x in a) ** 0.5
    nb   = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _embed_text(text: str) -> Optional[List[float]]:
    """
    Embed *text* using the same HuggingFace model used by the vector store.
    Returns None if the model is not available.
    """
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        emb = HuggingFaceEmbeddings(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            model_kwargs={"trust_remote_code": True},
        )
        return emb.embed_query(text)
    except Exception as exc:
        log.warning("Embedding unavailable: %s", exc)
        return None


# ── RAGMetadataManager ─────────────────────────────────────────────────────

class RAGMetadataManager:
    """
    Maintains this node's RAG metadata and publishes it to the DHT.

    VALUE STORE key:  ``peer_metadata:<peer_id>``
    PROVIDER STORE:   capability ``rag-provider/v1.0``

    The metadata JSON looks like::

        {
            "peer_id": "Qm...",
            "keywords": ["libp2p", "gossipsub", ...],
            "embedding_summary": [0.12, -0.34, ...],   # mean of all doc embeddings
            "doc_count": 42,
            "updated_at": 1716000000.0
        }
    """

    def __init__(self, service):
        """
        Parameters
        ----------
        service : HeadlessService
            The running headless service (provides host, dht, capability_registry,
            vectorstore).
        """
        self._service = service
        self._metadata: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_metadata(self, vectorstore) -> Dict[str, Any]:
        """
        Scan the local vector store and build the metadata dict.
        Stores the result in ``self._metadata`` and returns it.
        """
        if vectorstore is None:
            return {}

        try:
            col = vectorstore._collection
            result = col.get(include=["documents", "metadatas"])
            docs    = result.get("documents") or []
            metas   = result.get("metadatas") or []

            # Collect keywords from source filenames + first words of chunks
            keywords: set = set()
            for meta in metas:
                src = (meta or {}).get("source", "")
                if src:
                    # e.g. "libp2p/kad_dht/routing.py" → ["libp2p", "kad_dht", "routing"]
                    parts = src.replace("/", " ").replace("_", " ").replace(".", " ").split()
                    keywords.update(p.lower() for p in parts if len(p) > 3)

            for doc in docs[:200]:          # cap to first 200 chunks
                words = doc.split()[:10]
                keywords.update(w.lower().strip(".,;:") for w in words if len(w) > 4)

            # Build embedding summary (mean of up to 50 chunk embeddings)
            embedding_summary: List[float] = []
            try:
                sample_texts = docs[:50]
                if sample_texts:
                    from langchain_huggingface import HuggingFaceEmbeddings
                    emb_model = HuggingFaceEmbeddings(
                        model_name="nomic-ai/nomic-embed-text-v1.5",
                        model_kwargs={"trust_remote_code": True},
                    )
                    vecs = emb_model.embed_documents(sample_texts)
                    if vecs:
                        dim = len(vecs[0])
                        mean_vec = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
                        embedding_summary = mean_vec
            except Exception as exc:
                log.warning("Could not build embedding summary: %s", exc)

            peer_id = str(self._service.host.get_id()) if self._service.host else "unknown"
            self._metadata = {
                "peer_id":           peer_id,
                "keywords":          sorted(keywords)[:100],
                "embedding_summary": embedding_summary,
                "doc_count":         len(docs),
                "updated_at":        time.time(),
            }
            log.info(
                "📚 RAG metadata built: %d docs, %d keywords",
                len(docs), len(self._metadata["keywords"])
            )
            return self._metadata

        except Exception as exc:
            log.error("Failed to build RAG metadata: %s", exc)
            return {}

    async def publish(self, vectorstore) -> None:
        """
        Build metadata, store it in the DHT value store, and announce the
        ``rag-provider/v1.0`` capability.
        """
        meta = self.build_metadata(vectorstore)
        if not meta:
            log.warning("No RAG metadata to publish — skipping DHT registration.")
            return

        dht = getattr(self._service, "dht", None)
        if dht is None:
            log.warning("DHT not available — cannot publish RAG metadata.")
            return

        peer_id = meta["peer_id"]
        dht_key = f"peer_metadata:{peer_id}"
        value   = json.dumps(meta).encode("utf-8")

        try:
            await dht.put(dht_key, value)
            log.info("✅ RAG metadata stored in DHT under key '%s'", dht_key)
        except Exception as exc:
            log.warning("DHT put failed for RAG metadata: %s", exc)

        # Announce rag-provider capability
        registry = getattr(self._service, "capability_registry", None)
        if registry:
            try:
                from capabilities import CapabilityKey
                await registry.announce(CapabilityKey.RAG_PROVIDER)
                log.info("✅ Announced capability: %s", CapabilityKey.RAG_PROVIDER)
            except Exception as exc:
                log.warning("Failed to announce RAG capability: %s", exc)

    async def get_peer_metadata(self, peer_id_str: str) -> Optional[Dict[str, Any]]:
        """Fetch another peer's metadata from the DHT value store."""
        dht = getattr(self._service, "dht", None)
        if dht is None:
            return None
        try:
            dht_key = f"peer_metadata:{peer_id_str}"
            raw = await dht.get(dht_key)
            if raw:
                return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            log.debug("Could not fetch metadata for %s: %s", peer_id_str, exc)
        return None


# ── RAGQueryServer ─────────────────────────────────────────────────────────

class RAGQueryServer:
    """
    Handles incoming ``/rag/query/1.0.0`` streams from remote peers.

    A remote peer sends a length-prefixed JSON request::

        {"query": "how does DHT routing work?", "top_k": 3}

    We respond with a length-prefixed JSON::

        {
            "peer_id": "Qm...",
            "chunks": [
                {"text": "...", "source": "file.py", "score": 0.91},
                ...
            ]
        }
    """

    def __init__(self, service, vectorstore):
        self._service    = service
        self._vectorstore = vectorstore

    async def handle_stream(self, stream) -> None:
        """Trio stream handler registered on the host."""
        try:
            # Read 4-byte length prefix
            raw_len = await stream.read(4)
            if len(raw_len) < 4:
                return
            msg_len = int.from_bytes(raw_len, "big")
            if msg_len > RAG_MAX_PAYLOAD:
                log.warning(
                    "[SERVER] ⚠️  Incoming RAG query too large (%d bytes > %d limit) — dropping.",
                    msg_len, RAG_MAX_PAYLOAD,
                )
                return

            raw = await stream.read(msg_len)
            request = json.loads(raw.decode("utf-8"))
            query   = request.get("query", "").strip()
            top_k   = int(request.get("top_k", TOP_K_REMOTE))

            log.info("─" * 50)
            log.info(
                "[SERVER] 📨 Incoming RAG query (%d bytes) | query=%r | top_k=%d",
                msg_len, query, top_k,
            )

            if not query:
                log.info("[SERVER] ⚠️  Empty query — returning empty response.")
                await self._send_response(stream, {"peer_id": self._my_peer_id(), "chunks": []})
                return

            chunks = []
            if self._vectorstore is not None:
                log.info("[SERVER] 🔍 Searching local vector store for query=%r…", query)
                try:
                    results = self._vectorstore.similarity_search_with_score(query, k=top_k)
                    for doc, score in results:
                        chunks.append({
                            "text":   doc.page_content,
                            "source": doc.metadata.get("source", "unknown"),
                            "score":  float(score),
                        })
                    if chunks:
                        log.info(
                            "[SERVER] ✅ Local search found %d chunk(s) to share:",
                            len(chunks),
                        )
                        for i, c in enumerate(chunks, 1):
                            log.info(
                                "[SERVER]   chunk %d | score=%.4f | source=%-40s | preview=%r",
                                i, c["score"], c["source"], c["text"][:80],
                            )
                    else:
                        log.info("[SERVER] ❌ No relevant chunks found for query=%r.", query)
                except Exception as exc:
                    log.error("[SERVER] ❌ Vector search failed during remote query: %s", exc)
            else:
                log.info("[SERVER] ⚠️  No local vector store — returning empty response.")

            response = {
                "peer_id": self._my_peer_id(),
                "chunks":  chunks,
            }
            payload_size = len(json.dumps(response).encode("utf-8"))
            log.info(
                "[SERVER] 📤 Sending response: %d chunk(s) (%d bytes) back to requester.",
                len(chunks), payload_size,
            )
            log.info("─" * 50)
            await self._send_response(stream, response)

        except Exception as exc:
            log.error("[SERVER] ❌ Error handling RAG query stream: %s", exc)
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    def _my_peer_id(self) -> str:
        host = getattr(self._service, "host", None)
        return str(host.get_id()) if host else "unknown"

    @staticmethod
    async def _send_response(stream, data: dict) -> None:
        payload = json.dumps(data).encode("utf-8")
        await stream.write(len(payload).to_bytes(4, "big") + payload)


# ── DistributedRAGClient ───────────────────────────────────────────────────

class DistributedRAGClient:
    """
    Orchestrates the full distributed RAG query flow.

    Usage (from a Tornado coroutine bridged via trio_asyncio)::

        client = DistributedRAGClient(service, vectorstore)
        result = await client.query("how does Kademlia routing work?")
        # result = {"answer": "...", "sources": [...], "peers_queried": [...]}
    """

    def __init__(self, service, vectorstore):
        self._service     = service
        self._vectorstore = vectorstore

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def query(self, question: str) -> Dict[str, Any]:
        """
        Full distributed RAG query:
          1. Local search
          2. If insufficient → discover + query peers
          3. Merge + rerank
          4. LLM answer
        """
        from libp2p.peer.id import ID
        from libp2p.custom_types import TProtocol

        all_chunks: List[Dict[str, Any]] = []
        peers_queried: List[str] = []

        log.info("═" * 60)
        log.info("🧠 DISTRIBUTED RAG QUERY STARTED")
        log.info("   Question : %r", question)
        log.info("═" * 60)

        # ── Step 1: Local search ─────────────────────────────────────
        log.info("[STEP 1] 🔍 Searching LOCAL vector store (ChromaDB)…")
        local_chunks, best_local_score = self._local_search(question)
        all_chunks.extend(local_chunks)

        if local_chunks:
            log.info(
                "[STEP 1] ✅ Local search returned %d chunk(s) — best similarity score: %.4f",
                len(local_chunks), best_local_score,
            )
            for i, c in enumerate(local_chunks, 1):
                log.info(
                    "[STEP 1]   chunk %d | score=%.4f | source=%s | preview=%r",
                    i, c["score"], c["source"], c["text"][:80],
                )
        else:
            log.info("[STEP 1] ❌ No chunks found in local vector store.")

        if best_local_score >= MIN_LOCAL_SCORE and local_chunks:
            log.info(
                "[STEP 1] 🏁 Local result is sufficient (score %.4f >= threshold %.4f) — "
                "skipping peer discovery.",
                best_local_score, MIN_LOCAL_SCORE,
            )

        # ── Step 2: Discover peers if local result is weak ───────────
        if best_local_score < MIN_LOCAL_SCORE or not local_chunks:
            log.info(
                "[STEP 2] ⚠️  Local result insufficient "
                "(score=%.4f < threshold=%.4f, chunks=%d) — initiating peer discovery.",
                best_local_score, MIN_LOCAL_SCORE, len(local_chunks),
            )
            log.info("[STEP 2] 🌐 Querying Kademlia DHT for peers with capability '%s'…",
                     "rag-provider/v1.0")

            peer_ids = await self._discover_rag_peers()

            if peer_ids:
                log.info("[STEP 2] ✅ DHT returned %d RAG-capable peer(s):", len(peer_ids))
                for pid in peer_ids:
                    log.info("[STEP 2]   • %s", pid)
            else:
                log.info("[STEP 2] ❌ DHT found NO peers advertising 'rag-provider/v1.0'.")

            # ── Step 3: Filter peers by metadata similarity ──────────
            if peer_ids:
                log.info("[STEP 3] 🎯 Filtering %d peer(s) by embedding-summary similarity…",
                         len(peer_ids))
                filtered = await self._filter_peers(peer_ids, question)
                log.info("[STEP 3] ✅ Peer ranking after cosine similarity filter:")
                for rank, pid in enumerate(filtered, 1):
                    log.info("[STEP 3]   #%d %s", rank, pid)
            else:
                filtered = []

            # ── Step 4: Query best peers ─────────────────────────────
            to_query = filtered[:MAX_PEERS_TO_QUERY]
            if to_query:
                log.info(
                    "[STEP 4] 📡 Sending RAG query to %d peer(s) via libp2p stream "
                    "(protocol: %s)…",
                    len(to_query), RAG_QUERY_PROTOCOL,
                )
            else:
                log.info("[STEP 4] ⚠️  No peers to query — skipping remote retrieval.")

            for peer_id_str in to_query:
                log.info("[STEP 4] ➡️  Sending request to peer %s…", peer_id_str)
                try:
                    remote_chunks = await self._query_peer(peer_id_str, question)
                    all_chunks.extend(remote_chunks)
                    peers_queried.append(peer_id_str)
                    if remote_chunks:
                        log.info(
                            "[STEP 4] 📥 Received %d chunk(s) from peer %s:",
                            len(remote_chunks), peer_id_str,
                        )
                        for i, c in enumerate(remote_chunks, 1):
                            log.info(
                                "[STEP 4]   chunk %d | score=%.4f | source=%s | preview=%r",
                                i, c.get("score", 0.0), c.get("source", "?"),
                                c.get("text", "")[:80],
                            )
                    else:
                        log.info(
                            "[STEP 4] 📭 Peer %s returned 0 chunks.", peer_id_str
                        )
                except Exception as exc:
                    log.warning(
                        "[STEP 4] ❌ Failed to query peer %s: %s", peer_id_str, exc
                    )

        # ── Step 5: Merge + rerank ───────────────────────────────────
        log.info(
            "[STEP 5] 🔀 Merging & reranking %d total chunk(s) "
            "(%d local + %d remote)…",
            len(all_chunks),
            len([c for c in all_chunks if c.get("origin") == "local"]),
            len([c for c in all_chunks if c.get("origin", "").startswith("peer:")]),
        )
        merged = self._rerank(all_chunks, question)
        log.info("[STEP 5] ✅ After dedup+rerank: %d chunk(s) selected for LLM context.",
                 len(merged))
        for i, c in enumerate(merged, 1):
            log.info(
                "[STEP 5]   #%d | score=%.4f | origin=%-18s | source=%s",
                i, c.get("score", 0.0), c.get("origin", "?"), c.get("source", "?"),
            )

        # ── Step 6: LLM answer ───────────────────────────────────────
        if not merged:
            log.info(
                "[STEP 6] ❌ No relevant chunks found anywhere — "
                "returning empty answer."
            )
            return {
                "answer": "No relevant context found in the local or remote knowledge bases.",
                "sources": [],
                "peers_queried": peers_queried,
            }

        sources = sorted({c["source"] for c in merged})
        log.info(
            "[STEP 6] 🤖 Sending %d chunk(s) from %d source(s) to LLM (Groq llama-3.3-70b)…",
            len(merged), len(sources),
        )
        log.info("[STEP 6]   Sources: %s", ", ".join(sources))
        log.info(
            "[STEP 6]   Context size: ~%d chars",
            sum(len(c.get("text", "")) for c in merged),
        )

        answer = await self._llm_answer(question, merged)

        log.info("[STEP 6] ✅ LLM answer received (%d chars).", len(answer))
        log.info("═" * 60)
        log.info("🧠 DISTRIBUTED RAG QUERY COMPLETE")
        log.info("   Peers queried : %s", peers_queried or "(none — local only)")
        log.info("   Sources used  : %s", sources)
        log.info("═" * 60)

        return {
            "answer": answer,
            "sources": sources,
            "peers_queried": peers_queried,
        }

    # ------------------------------------------------------------------
    # Step 1 – Local search
    # ------------------------------------------------------------------

    def _local_search(self, question: str):
        """Returns (chunks_list, best_score)."""
        if self._vectorstore is None:
            log.info("[STEP 1] ⚠️  Vector store not loaded — local search skipped.")
            return [], 0.0
        try:
            results = self._vectorstore.similarity_search_with_score(question, k=TOP_K_LOCAL)
            chunks = []
            best_score = 0.0
            for doc, score in results:
                # ChromaDB returns L2 distance (lower = better).
                # Convert to a 0-1 similarity: similarity ≈ 1 / (1 + distance)
                similarity = 1.0 / (1.0 + float(score))
                best_score = max(best_score, similarity)
                chunks.append({
                    "text":   doc.page_content,
                    "source": doc.metadata.get("source", "unknown"),
                    "score":  similarity,
                    "origin": "local",
                })
            if not chunks:
                log.info("[STEP 1] ❌ ChromaDB similarity search returned 0 results.")
            return chunks, best_score
        except Exception as exc:
            log.error("[STEP 1] ❌ Local vector search failed: %s", exc)
            return [], 0.0

    # ------------------------------------------------------------------
    # Step 2 – Discover RAG-capable peers
    # ------------------------------------------------------------------

    async def _discover_rag_peers(self) -> List[str]:
        """Use DHT find_providers to discover peers with rag-provider/v1.0."""
        registry = getattr(self._service, "capability_registry", None)
        if registry is None:
            log.warning("[STEP 2] ⚠️  Capability registry not available — cannot query DHT.")
            return []
        try:
            from capabilities import CapabilityKey
            log.info(
                "[STEP 2] 🌐 Calling DHT find_providers('%s') …",
                CapabilityKey.RAG_PROVIDER,
            )
            peer_infos = await registry.find_providers(CapabilityKey.RAG_PROVIDER, count=20)
            my_id = str(self._service.host.get_id()) if self._service.host else ""
            peers = [str(p.peer_id) for p in peer_infos if str(p.peer_id) != my_id]
            log.info(
                "[STEP 2] 🌐 DHT find_providers returned %d result(s) "
                "(excluding self: %s…)",
                len(peers), my_id[:12] if my_id else "unknown",
            )
            return peers
        except Exception as exc:
            log.warning("[STEP 2] ❌ DHT find_providers for RAG failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Step 3 – Filter peers by metadata similarity
    # ------------------------------------------------------------------

    async def _filter_peers(self, peer_ids: List[str], question: str) -> List[str]:
        """
        Fetch each peer's metadata from the DHT and rank by cosine similarity
        of the query embedding vs the peer's embedding_summary.
        Returns peer_ids sorted by relevance (best first).
        """
        if not peer_ids:
            return []

        log.info("[STEP 3] 🔑 Embedding query to compare against peer summaries…")
        query_vec = _embed_text(question)
        if query_vec:
            log.info("[STEP 3] ✅ Query embedded (%d dims).", len(query_vec))
        else:
            log.info("[STEP 3] ⚠️  Query embedding unavailable — will use fallback scores.")

        scored: List[tuple] = []
        dht = getattr(self._service, "dht", None)

        for peer_id_str in peer_ids:
            score = 0.0
            if dht is not None:
                try:
                    dht_key = f"peer_metadata:{peer_id_str}"
                    log.info(
                        "[STEP 3] 🔍 Fetching DHT metadata for peer %s (key='%s')…",
                        peer_id_str[:12], dht_key,
                    )
                    raw = await dht.get(dht_key)
                    if raw:
                        meta = json.loads(raw.decode("utf-8"))
                        summary = meta.get("embedding_summary", [])
                        doc_count = meta.get("doc_count", "?")
                        keywords  = meta.get("keywords", [])[:8]
                        if query_vec and summary:
                            score = _cosine_similarity(query_vec, summary)
                            log.info(
                                "[STEP 3]   peer %s | docs=%s | keywords=%s | "
                                "cosine_similarity=%.4f",
                                peer_id_str[:12], doc_count, keywords, score,
                            )
                        else:
                            score = 0.1
                            log.info(
                                "[STEP 3]   peer %s | docs=%s | no embedding summary — "
                                "assigning default score=%.2f",
                                peer_id_str[:12], doc_count, score,
                            )
                    else:
                        score = 0.05
                        log.info(
                            "[STEP 3]   peer %s | no metadata in DHT — "
                            "assigning low score=%.2f",
                            peer_id_str[:12], score,
                        )
                except Exception as exc:
                    log.debug("[STEP 3] Metadata fetch failed for %s: %s", peer_id_str[:12], exc)
                    score = 0.05

            scored.append((score, peer_id_str))

        scored.sort(key=lambda t: t[0], reverse=True)
        log.info("[STEP 3] 📊 Peer scores (sorted): %s",
                 [(pid[:12], round(s, 4)) for s, pid in scored])
        return [pid for _, pid in scored]

    # ------------------------------------------------------------------
    # Step 4 – Query a single peer
    # ------------------------------------------------------------------

    async def _query_peer(self, peer_id_str: str, question: str) -> List[Dict[str, Any]]:
        """
        Open a /rag/query/1.0.0 stream to *peer_id_str* and return its chunks.
        """
        from libp2p.peer.id import ID
        from libp2p.custom_types import TProtocol

        host = getattr(self._service, "host", None)
        if host is None:
            return []

        target   = ID.from_base58(peer_id_str)
        protocol = TProtocol(RAG_QUERY_PROTOCOL)

        request = json.dumps({
            "query": question,
            "top_k": TOP_K_REMOTE,
        }).encode("utf-8")

        log.info(
            "[STEP 4] 📡 Opening libp2p stream to peer %s (protocol: %s)…",
            peer_id_str, RAG_QUERY_PROTOCOL,
        )
        log.info(
            "[STEP 4] ➡️  Sending request payload: query=%r top_k=%d (%d bytes)",
            question, TOP_K_REMOTE, len(request),
        )

        stream = await host.new_stream(target, [protocol])
        try:
            # Send length-prefixed request
            await stream.write(len(request).to_bytes(4, "big") + request)
            log.info("[STEP 4] ✅ Request sent to peer %s — waiting for response…", peer_id_str)

            # Read length-prefixed response
            raw_len = await stream.read(4)
            if len(raw_len) < 4:
                log.warning("[STEP 4] ⚠️  Peer %s sent incomplete length prefix.", peer_id_str)
                return []
            resp_len = int.from_bytes(raw_len, "big")
            log.info(
                "[STEP 4] 📥 Response from peer %s: %d bytes incoming…",
                peer_id_str, resp_len,
            )
            if resp_len > RAG_MAX_PAYLOAD:
                log.warning(
                    "[STEP 4] ⚠️  Response from peer %s too large (%d bytes > %d limit) — dropping.",
                    peer_id_str, resp_len, RAG_MAX_PAYLOAD,
                )
                return []
            raw = await stream.read(resp_len)
            response = json.loads(raw.decode("utf-8"))

            chunks = response.get("chunks", [])
            # Tag each chunk with its origin peer
            for c in chunks:
                c["origin"] = f"peer:{peer_id_str[:12]}"

            log.info(
                "[STEP 4] ✅ Received %d chunk(s) from peer %s:",
                len(chunks), peer_id_str,
            )
            for i, c in enumerate(chunks, 1):
                log.info(
                    "[STEP 4]   chunk %d | score=%.4f | source=%-40s | preview=%r",
                    i, c.get("score", 0.0), c.get("source", "?"), c.get("text", "")[:80],
                )
            return chunks
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Step 5 – Merge + rerank
    # ------------------------------------------------------------------

    @staticmethod
    def _rerank(chunks: List[Dict[str, Any]], question: str) -> List[Dict[str, Any]]:
        """
        Deduplicate by text prefix and sort by score descending.
        Returns the top (TOP_K_LOCAL + TOP_K_REMOTE * MAX_PEERS_TO_QUERY) chunks.
        """
        seen: set = set()
        unique: List[Dict[str, Any]] = []
        for c in chunks:
            key = c.get("text", "")[:120]
            if key not in seen:
                seen.add(key)
                unique.append(c)

        unique.sort(key=lambda c: c.get("score", 0.0), reverse=True)
        limit = TOP_K_LOCAL + TOP_K_REMOTE * MAX_PEERS_TO_QUERY
        return unique[:limit]

    # ------------------------------------------------------------------
    # Step 6 – LLM answer
    # ------------------------------------------------------------------

    @staticmethod
    async def _llm_answer(question: str, chunks: List[Dict[str, Any]]) -> str:
        """Call the Groq LLM with the merged context."""
        from groq import AsyncGroq

        GROQ_MODEL = "llama-3.3-70b-versatile"

        context_parts = []
        for c in chunks:
            context_parts.append(
                f"[Source: {c.get('source', 'unknown')} | Origin: {c.get('origin', '?')}]\n"
                f"{c.get('text', '')}"
            )
        context = "\n\n---\n\n".join(context_parts)

        prompt = (
            "You are an expert assistant for the py-libp2p library and libp2p protocols.\n"
            "Answer the question using ONLY the context below.\n"
            "The context may come from multiple nodes in a distributed knowledge network.\n"
            "If the answer is not in the context, say \"I don't have enough context to answer that.\"\n"
            "Always mention which file or spec the answer comes from.\n\n"
            f"{context}\n\n"
            "---\n"
            f"Question: {question}\n"
            "Answer:"
        )

        log.info(
            "[STEP 6] 🤖 Calling Groq API (model=%s) | prompt_chars=%d | context_chunks=%d",
            GROQ_MODEL, len(prompt), len(chunks),
        )
        log.info("[STEP 6]   Chunk breakdown:")
        for i, c in enumerate(chunks, 1):
            log.info(
                "[STEP 6]   #%d origin=%-20s source=%s",
                i, c.get("origin", "?"), c.get("source", "?"),
            )

        client = AsyncGroq()
        completion = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = completion.choices[0].message.content.strip()
        log.info(
            "[STEP 6] ✅ LLM responded: %d chars | first 120: %r",
            len(answer), answer[:120],
        )
        return answer
