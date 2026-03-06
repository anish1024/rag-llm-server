import requests
import os
import io
import uuid
from typing import List, Optional
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader


app = FastAPI(title="Pi5 RAG API")

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:5b-instruct-q4_K_M")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "rag_docs") # test_rag_docs

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

WIKIJS_URL = os.getenv("WIKIJS_URL", "")          # e.g. http://wiki.local
WIKIJS_API_KEY = os.getenv("WIKIJS_API_KEY", "")

###################################################################
# ...Helper Functions....					  #
###################################################################

def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL)


def get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(
        model=EMBEDDING_MODEL,
        base_url=OLLAMA_URL,
    )


def get_llm() -> ChatOllama:
    return ChatOllama(
        model=LLM_MODEL,
        base_url=OLLAMA_URL,
    )


def ensure_collection(client: QdrantClient, dim: int) -> None:
    """Drop and recreate collection for now (simple test semantics)."""
    try:
        client.delete_collection(QDRANT_COLLECTION)
    except Exception:
        pass

    client.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config=qm.VectorParams(
            size=dim,
            distance=qm.Distance.COSINE,
        ),
    )


def get_or_create_collection(client: QdrantClient, dim: int) -> None:
    """Create collection only if it does not already exist."""
    existing = {c.name for c in client.get_collections().collections}
    if QDRANT_COLLECTION not in existing:
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=qm.VectorParams(
                size=dim,
                distance=qm.Distance.COSINE,
            ),
        )


def chunk_documents(docs: List[Document]) -> List[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    return splitter.split_documents(docs)


###################################################################
# ...Wiki.js helpers...                                           #
###################################################################

def _wikijs_graphql(query: str, variables: dict = None) -> dict:
    """Execute a GraphQL query against Wiki.js."""
    if not WIKIJS_URL:
        raise HTTPException(status_code=500, detail="WIKIJS_URL is not configured")
    if not WIKIJS_API_KEY:
        raise HTTPException(status_code=500, detail="WIKIJS_API_KEY is not configured")

    headers = {
        "Authorization": f"Bearer {WIKIJS_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    try:
        r = requests.post(
            f"{WIKIJS_URL}/graphql",
            json=payload,
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Wiki.js request failed: {e}")

    data = r.json()
    if "errors" in data:
        raise HTTPException(status_code=502, detail=f"Wiki.js GraphQL error: {data['errors']}")
    return data["data"]


_LIST_PAGES_QUERY = """
query {
  pages {
    list {
      id
      path
      title
    }
  }
}
"""

_GET_PAGE_QUERY = """
query ($id: Int!) {
  pages {
    single(id: $id) {
      id
      path
      title
      content
      updatedAt
    }
  }
}
"""


def fetch_wiki_page_list() -> List[dict]:
    data = _wikijs_graphql(_LIST_PAGES_QUERY)
    return data["pages"]["list"]


def fetch_wiki_page_content(page_id: int) -> dict:
    data = _wikijs_graphql(_GET_PAGE_QUERY, {"id": page_id})
    return data["pages"]["single"]


###################################################################
# ...API call block BEGINs...					  #
###################################################################

class ChatRequest(BaseModel):
    messages: list

@app.get("/health")
def health():
    return {"status": "healthy", "ollama": OLLAMA_URL}

@app.get("/test")
def test_ollama():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/version", timeout=3)
        return {"ollama_version": r.json()}
    except Exception as e:
        return {"error": str(e)}

@app.post("/chat")
def chat(req: ChatRequest):
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json={
            "model": "qwen2.5:3b-instruct-q4_K_M",
            "messages": req.messages,
            "stream": False,
	    "options": {"num_predict": 256}
        }, timeout=120)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


class UploadResponse(BaseModel):
    filename: str
    chunks: int

#----------- Upload --------------------------------------------------------------

UPLOAD_DIR = Path("/app/uploads")

@app.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Save to disk
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    pdf_file = UPLOAD_DIR / file.filename
    with pdf_file.open("wb") as f:
        f.write(await file.read())

    # Load PDF into Documents (in-memory)
    loader = PyPDFLoader(pdf_file)  # langchain-community loader supports file-like
    docs = loader.load()

    # Chunk
    chunks = chunk_documents(docs)
    if not chunks:
        raise HTTPException(status_code=400, detail="No text chunks extracted")

    # Embeddings + Qdrant
    embeddings = get_embeddings()
    vectors = embeddings.embed_documents([c.page_content for c in chunks])

    client = get_qdrant_client()
    dim = len(vectors[0])
    ensure_collection(client, dim)

    points = [
       qm.PointStruct(
            #id=f"{file.filename}-{i}",
	    id=str(uuid.uuid4()),
            vector=vectors[i],
            payload={
           	 "text": chunks[i].page_content,
           	 "source": file.filename,
           	 "doc_type": 'pdf',
        	},
    	)
    	for i in range(len(chunks))
    ]
    print("Upserting points:", type(points), "len:",  len(points))

    
    ## Build batch for upsert
    #ids = [f"{file.filename}-{i}" for i in range(len(chunks))]
    #vectors_batch = vectors  # list[list[float]]
    #payloads = [
    #	{
    #        "text": chunks[i].page_content,
    #        "source": file.filename,
    #        "page": chunks[i].metadata.get("page"),
    #	}
    #	for i in range(len(chunks))
    #]

    #batch = qm.Batch(
    #	ids=ids,
    #	vectors=vectors_batch,
    #	payloads=payloads,
    #)
    #print("Upserting batch:", type(batch), "len:",  len(ids))

    client.upsert(
        collection_name=QDRANT_COLLECTION,
        wait=True,
        points=points,
    )

    return UploadResponse(filename=file.filename, chunks=len(points))

@app.post("/upload_test", response_model=UploadResponse)
async def upload_pdf_test(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Save to disk
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    pdf_file = UPLOAD_DIR / file.filename
    with pdf_file.open("wb") as f:
        f.write(await file.read())

    # Load PDF into Documents (in-memory)
    loader = PyPDFLoader(pdf_file)  # langchain-community loader supports file-like
    docs = loader.load()

    # Chunk
    chunks = chunk_documents(docs)
    if not chunks:
        raise HTTPException(status_code=400, detail="No text chunks extracted")

    # Embeddings + Qdrant
    embeddings = get_embeddings()
    vectors = embeddings.embed_documents([c.page_content for c in chunks])
    print(f"✅ Embedded {len(vectors)} documents")
    
    client = get_qdrant_client()
    dim = len(vectors[0])
    ensure_collection(client, dim)

    points = [
       qm.PointStruct(
            id=str(uuid.uuid4()),
            vector=vectors[i],
            payload={
           	 "text": chunks[i].page_content,
           	 "source": file.filename,
           	 "doc_type": 'ebook',
        	},
    	)
    	for i in range(len(chunks))
    ]
    print("Upserting points:", type(points), "len:",  len(points))

    client.upsert(
        collection_name=QDRANT_COLLECTION,
        wait=True,
        points=points,
    )

    return UploadResponse(filename=file.filename, chunks=len(points))

#----------- RAG -------------------------------------------------------------
class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    answer: str


@app.post("/rag", response_model=QueryResponse)
async def rag_query(req: QueryRequest):
    client = get_qdrant_client()
    embeddings = get_embeddings()

    # Embed query
    q_vec = embeddings.embed_query(req.question)

    # Search top-k
    results = client.search(
        collection_name=QDRANT_COLLECTION,
        query_vector=q_vec,
        limit=5,
    )

    if not results:
        raise HTTPException(status_code=404, detail="No matches found in Qdrant")

    # Build context
    ctx_chunks = []
    for r in results:
        payload = r.payload or {}
        ctx_chunks.append(payload.get("text", ""))

    context = "\n\n".join(ctx_chunks)

    # LLM answer
    llm = get_llm()
    prompt = (
        "You are a helpful assistant running on a Raspberry Pi 5.\n"
        "Answer the question using ONLY the context below.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {req.question}\n\n"
        "Answer:"
    )
    resp = await llm.ainvoke(prompt)
    answer_text = resp.content if hasattr(resp, "content") else str(resp)

    return QueryResponse(answer=answer_text)

#----------- Wiki.js ingest --------------------------------------------------

class WikiIngestRequest(BaseModel):
    path_prefix: Optional[str] = None   # e.g. "/iot" to limit scope
    page_ids: Optional[List[int]] = None  # explicit list of page IDs


class WikiIngestResponse(BaseModel):
    pages: int
    chunks: int


@app.post("/ingest/wiki", response_model=WikiIngestResponse)
async def ingest_wiki(req: WikiIngestRequest = None):
    if req is None:
        req = WikiIngestRequest()

    # Resolve which pages to ingest
    if req.page_ids:
        page_list = [{"id": pid} for pid in req.page_ids]
    else:
        page_list = fetch_wiki_page_list()
        if req.path_prefix:
            prefix = req.path_prefix.lstrip("/")
            page_list = [p for p in page_list if p["path"].lstrip("/").startswith(prefix)]

    if not page_list:
        raise HTTPException(status_code=404, detail="No Wiki.js pages matched the filter")

    embeddings = get_embeddings()
    client = get_qdrant_client()

    total_chunks = 0
    ingested_pages = 0
    collection_ready = False

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )

    for page_meta in page_list:
        try:
            page = fetch_wiki_page_content(int(page_meta["id"]))
        except HTTPException:
            continue  # skip pages we can't fetch

        content = (page.get("content") or "").strip()
        if not content:
            continue

        chunks = splitter.split_text(content)
        if not chunks:
            continue

        vectors = embeddings.embed_documents(chunks)

        if not collection_ready:
            get_or_create_collection(client, len(vectors[0]))
            collection_ready = True

        points = [
            qm.PointStruct(
                id=str(uuid.uuid4()),
                vector=vectors[i],
                payload={
                    "text": chunks[i],
                    "source": page.get("path", ""),
                    "title": page.get("title", ""),
                    "doc_type": "wiki",
                    "updated_at": page.get("updatedAt", ""),
                },
            )
            for i in range(len(chunks))
        ]

        client.upsert(
            collection_name=QDRANT_COLLECTION,
            wait=True,
            points=points,
        )

        total_chunks += len(points)
        ingested_pages += 1

    if ingested_pages == 0:
        raise HTTPException(status_code=422, detail="Pages found but no content could be extracted")

    return WikiIngestResponse(pages=ingested_pages, chunks=total_chunks)


#--------- Entry Point ------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agent_api:app", host="0.0.0.0", port=8000, reload=False)
