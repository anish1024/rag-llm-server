from fastapi import FastAPI
from pydantic import BaseModel
import requests
import os

RAG_URL = os.getenv("RAG_URL", "http://rag-agents:8000/chat")

app = FastAPI(
    title="Pi5 RAG Tool Server",
    description="OpenAPI Tool Server exposing the /rag endpoint for Open WebUI.",
    version="1.0.0"
)

class RagToolRequest(BaseModel):
    question: str
    doc_type: str | None = None

class RagToolResponse(BaseModel):
    answer: str

@app.post("/rag_tool_old", response_model=RagToolResponse)
def rag_tool_old(body: RagToolRequest):
    try:
        r = requests.post(RAG_URL, json=body.dict(), timeout=60)
        r.raise_for_status()
        data = r.json()
        return RagToolResponse(answer=data.get("answer", ""))
    except Exception as e:
        return RagToolResponse(answer=f"[Pi5 RAG error] {e}")

@app.post("/rag_tool", response_model=RagToolResponse)
def rag_tool(body: RagToolRequest):
    print(f"[rag_tool] >>> incoming request body : {body}", flush=True)
    print(f"[rag_tool] question={body.question!r} doc_type={body.doc_type!r}", flush=True)

    text = body.question.strip()
    doc_type = body.doc_type
    if doc_type is None:
        lower = text.lower()
        if lower.startswith("wiki:"):
            doc_type = "wiki"
            text = text[5:].strip()
        elif lower.startswith("ebook:"):
            doc_type = "ebook"
            text = text[6:].strip()

    payload = {"question": text, "doc_type": doc_type}

    try:
        r = requests.post(RAG_URL, json=payload, timeout=1200)
        r.raise_for_status()
        data = r.json()
        print(f"[rag_tool] <<< response generated :{len(data)}",flush=True)
        return RagToolResponse(answer=data.get("answer", ""))
    except Exception as e:
        print(f"[rag_tool][error] {e}", flush=True)
        return RagToolResponse(answer=f"[Pi5 RAG error] {e}")

@app.post("/import")
def import_file():
    data = request.get_json()
    path = data["path"]
    file_type = data["type"]
    user_id = data["user_id"]

    # TODO: call your existing indexing function
    # index_document(path, file_type=file_type, owner=user_id)

    return {"ok": True}



# Entry point
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("tool_server:app", host="0.0.0.0", port=9000, reload=False)
