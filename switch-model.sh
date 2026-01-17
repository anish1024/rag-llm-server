#!/bin/bash
MODEL=$1
echo "Switching to $MODEL..."
docker exec ollama-pi5 ollama pull "$MODEL"
sed -i "s/\"model\": \".*\"/\"model\": \"$MODEL\"/" agent_api.py
docker compose up -d --build rag-agents
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d "{\"messages\":[{\"role\":\"user\",\"content\":\"Test $MODEL\"}]}"
