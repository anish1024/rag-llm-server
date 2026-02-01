from fastapi import FastAPI
from pydantic import BaseModel
import requests
import os

app = FastAPI(title="Pi5 RAG API")

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agent_api:app", host="0.0.0.0", port=8000, reload=False)
