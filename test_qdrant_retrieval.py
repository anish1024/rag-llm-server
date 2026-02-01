#!/usr/bin/env python3

import os
import uuid
from typing import List

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from langchain_ollama import OllamaEmbeddings

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "test_rag_docs")
EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

EMBED_DIM = 768  # adjust if your model differs


def get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(
        model=EMBED_MODEL,
        base_url=OLLAMA_URL,
    )

def ensure_collection(client: QdrantClient) -> None:
    # Try to delete if it exists; ignore "not found" errors
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=qm.VectorParams(
            size=EMBED_DIM,
            distance=qm.Distance.COSINE,
        ),
    )
    print("✅ Collection recreated:", COLLECTION_NAME)


def main() -> None:
    client = QdrantClient(url=QDRANT_URL)
    emb = get_embeddings()

    ensure_collection(client)

    texts = [
        "Raspberry Pi 5 features PCIe Gen 3, active cooling recommended for sustained loads.",
        "Docker Compose orchestrates multi-container RAG: Ollama, Qdrant, FastAPI agents.",
        "Wiki.js exports Markdown files; chunk and embed for semantic search in RAG.",
        "Qwen2.5:7b quantized fits Pi 5 8GB; use NVMe SSD for vector DB persistence.",
    ]
    metadatas = [
        {"source": "hardware.md", "doc_type": "ebook"},
        {"source": "docker-setup.md", "doc_type": "wiki"},
        {"source": "wiki-ingestion.md", "doc_type": "wiki"},
        {"source": "llm-deployment.md", "doc_type": "ebook"},
    ]

    vectors: List[List[float]] = emb.embed_documents(texts)
    print(f"✅ Embedded {len(vectors)} documents")

    points = [
        qm.PointStruct(
            id=str(uuid.uuid4()),
            vector=vectors[i],
            payload={"text": texts[i], **metadatas[i]},
        )
        for i in range(len(texts))
    ]

    client.upsert(
        collection_name=COLLECTION_NAME,
        wait=True,
        points=points,
    )
    print(f"✅ Upserted {len(points)} points into {COLLECTION_NAME}")

    query = "Best setup for Pi 5 RAG with Qdrant?"
    q_vec = emb.embed_query(query)

    res = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=q_vec,
        limit=3,
    )

    print("\n📄 Search results:")
    for r in res:
        payload = r.payload or {}
        print(f"- score={r.score:.4f}, text={payload.get('text', '')[:80]}..., source={payload.get('source')}")

    filt_res = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=q_vec,
        limit=3,
        query_filter=qm.Filter(
            must=[qm.FieldCondition(key="doc_type", match=qm.MatchValue(value="wiki"))]
        ),
    )

    print("\n🔍 Filtered results (doc_type=wiki):")
    for r in filt_res:
        payload = r.payload or {}
        print(f"- score={r.score:.4f}, text={payload.get('text', '')[:80]}..., source={payload.get('source')}")


if __name__ == "__main__":
    main()
