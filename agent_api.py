import requests
import os
import io
import uuid
from typing import List
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


def chunk_documents(docs: List[Document]) -> List[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    return splitter.split_documents(docs)


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

#--------- Entry Point ------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agent_api:app", host="0.0.0.0", port=8000, reload=False)
