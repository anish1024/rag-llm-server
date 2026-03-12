# Pi5 RAG API Server

A Retrieval-Augmented Generation (RAG) stack for Raspberry Pi 5, using Ollama, Qdrant, Wiki.js, and FastAPI.

---

## Architecture

| Container | Image / Build | Port | Purpose |
|---|---|---|---|
| `ollama-pi5` | `ollama/ollama:latest` | `11434` | Local LLM inference |
| `qdrant-pi5` | `y0mg/qdrant-raspberry-pi:latest` | `6333` | Vector database |
| `rag-agents-pi5` | `Dockerfile.rag-agents` | `8000` | Main RAG API (`agent_api.py`) |
| `rag-tool-server` | `Dockerfile.rag-agents` | `9000` | Tool server (`tool_server.py`) — `/import` endpoint used by Telegram bot |
| `webui-pi5` | `ghcr.io/open-webui/open-webui:main` | `3000` | Open WebUI for Ollama |
| `telegram-gateway` | `Dockerfile.telegram-gateway` | `8080` | Telegram bot gateway |

---

## Configuration

Copy `.env.example` to `.env` and fill in values:

```env
WIKIJS_URL=http://your-wiki-host
WIKIJS_API_KEY=your-wikijs-api-key
```

Environment variables used by `rag-agents`:

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama base URL |
| `LLM_MODEL` | `qwen2.5:5b-instruct-q4_K_M` | LLM model name |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model name |
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant URL |
| `QDRANT_COLLECTION` | `rag_docs` | Qdrant collection name |
| `CHUNK_SIZE` | `800` | Text chunk size |
| `CHUNK_OVERLAP` | `200` | Chunk overlap |
| `WIKIJS_URL` | _(empty)_ | Wiki.js base URL |
| `WIKIJS_API_KEY` | _(empty)_ | Wiki.js API key |

---

## API Reference (`rag-agents` — port 8000)

### Health check
```bash
curl http://localhost:8000/health
```

### Test Ollama connectivity
```bash
curl http://localhost:8000/test
```

### Upload a PDF for ingestion
```bash
curl -X POST http://localhost:8000/upload \
  -F "file=@/path/to/document.pdf"
```

### Query the RAG pipeline
```bash
curl -X POST http://localhost:8000/rag \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the purpose of this system?"}'
```

### Ingest Wiki.js pages

Ingest all pages:
```bash
curl -X POST http://localhost:8000/ingest/wiki
```

Ingest pages under a path prefix:
```bash
curl -X POST http://localhost:8000/ingest/wiki \
  -H "Content-Type: application/json" \
  -d '{"path_prefix": "/iot"}'
```

Ingest specific page IDs:
```bash
curl -X POST http://localhost:8000/ingest/wiki \
  -H "Content-Type: application/json" \
  -d '{"page_ids": [1, 2, 3]}'
```

---

## Deployment — Fresh Linux or macOS Server

### Prerequisites

- Docker + Docker Compose v2
- `git`
- Sufficient RAM (8 GB+ recommended for LLMs on Pi 5)

### 1. Install Docker

**Linux (Debian/Ubuntu/Raspberry Pi OS):**
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

**macOS:**
```bash
brew install --cask docker
open /Applications/Docker.app
```

### 2. Clone the repository
```bash
git clone <your-repo-url> rag-server
cd rag-server
```

### 3. Configure environment
```bash
cp .env.example .env   # or create .env manually
# Edit .env and set WIKIJS_URL and WIKIJS_API_KEY
```

### 4. Pull Ollama models (first-time setup)

Start Ollama first, then pull the required models:
```bash
docker compose up -d ollama
docker exec -it ollama-pi5 ollama pull qwen2.5:3b-instruct-q4_K_M
docker exec -it ollama-pi5 ollama pull nomic-embed-text
```

### 5. Start all services
```bash
docker compose up -d
```

### 6. Verify everything is running
```bash
docker ps
curl http://localhost:8000/health
```

### 7. Ingest your Wiki.js knowledge base
```bash
curl -X POST http://localhost:8000/ingest/wiki
```

### 8. Test a RAG query
```bash
curl -X POST http://localhost:8000/rag \
  -H "Content-Type: application/json" \
  -d '{"question": "What is my system for?"}'
```

---

## Stopping / Restarting

```bash
docker compose down        # stop all
docker compose restart     # restart all
docker compose logs -f     # follow logs
docker compose logs -f rag-agents   # logs for specific service
```

---

## Full Deploy Script

Save as `deploy.sh` and run once on a new server:

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_URL="<your-repo-url>"
INSTALL_DIR="$HOME/rag-server"
LLM_MODEL="qwen2.5:3b-instruct-q4_K_M"
EMBED_MODEL="nomic-embed-text"

echo "==> Installing Docker..."
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
fi

echo "==> Cloning repository..."
git clone "$REPO_URL" "$INSTALL_DIR" || (cd "$INSTALL_DIR" && git pull)
cd "$INSTALL_DIR"

echo "==> Creating .env (edit this file with your Wiki.js credentials)..."
if [ ! -f .env ]; then
  cat > .env <<EOF
WIKIJS_URL=
WIKIJS_API_KEY=
EOF
  echo "    .env created — fill in WIKIJS_URL and WIKIJS_API_KEY before continuing."
  read -rp "    Press Enter once .env is configured..."
fi

echo "==> Starting Ollama..."
docker compose up -d ollama
sleep 5

echo "==> Pulling LLM models..."
docker exec ollama-pi5 ollama pull "$LLM_MODEL"
docker exec ollama-pi5 ollama pull "$EMBED_MODEL"

echo "==> Starting all services..."
docker compose up -d

echo "==> Waiting for rag-agents to be ready..."
until curl -sf http://localhost:8000/health >/dev/null; do
  sleep 3
done

echo "==> Ingesting Wiki.js pages..."
curl -X POST http://localhost:8000/ingest/wiki

echo ""
echo "✅ Deployment complete."
echo "   RAG API:   http://localhost:8000"
echo "   Open WebUI: http://localhost:3000"
echo "   Qdrant:    http://localhost:6333"
```

---

## Post Deployment Steps

### Connect RAG to Open WebUI (Native Tool)

Open WebUI's external tool server feature requires client-side URL resolution, which doesn't work with Docker service names. Instead, register the RAG pipeline as a **native Open WebUI Tool** — it runs server-side inside the Open WebUI container and can reach other containers by Docker service name.

**Steps:**

1. Open Open WebUI at `http://<pi-ip>:3000`
2. Go to **Workspace → Tools → +** (create new tool)
3. Paste the following Python script and save:

```python
"""
title: Pi5 RAG Query
description: Query the Pi5 RAG pipeline backed by Qdrant + Ollama
author: pi5
version: 1.0.0
"""

import requests
from pydantic import BaseModel

class Tools:
    class Valves(BaseModel):
        RAG_URL: str = "http://rag-agents:8000/rag"

    def __init__(self):
        self.valves = self.Valves()

    def query_rag(self, question: str) -> str:
        """
        Query the local RAG knowledge base with a question.
        Use this when the user asks about anything in the knowledge base,
        wiki pages, or uploaded documents.
        :param question: The question to answer using the RAG knowledge base.
        :return: Answer from the RAG pipeline.
        """
        try:
            r = requests.post(
                self.valves.RAG_URL,
                json={"question": question},
                timeout=120,
            )
            r.raise_for_status()
            return r.json().get("answer", "No answer returned.")
        except Exception as e:
            return f"[RAG error] {e}"
```

4. In a chat session, click the **Tools** icon in the message bar and enable **Pi5 RAG Query**
5. The LLM will automatically call the RAG tool when the question is relevant to the knowledge base

> **Note:** The `RAG_URL` defaults to `http://rag-agents:8000/rag` which resolves correctly within the Docker network. No changes needed unless you rename the service.
