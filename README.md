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
