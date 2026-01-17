from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
async def health():
    return {
        "status": "healthy", 
        "agents": ["devops", "code", "ebook_research", "finance"],
        "timestamp": "$(date)"
    }

@app.get("/status")
async def status():
    import subprocess
    ollama_status = subprocess.run(["curl", "-s", "-f", "http://ollama:11434/api/version"], capture_output=True)
    return {
        "ollama_healthy": ollama_status.returncode == 0,
        "models_ready": True
    }
