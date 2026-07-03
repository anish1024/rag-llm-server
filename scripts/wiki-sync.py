#!/usr/bin/env python3
"""
wiki-sync.py - Sync wiki pages to Qdrant with heading-based chunking

This script:
1. Fetches wiki pages from the RAG API (rag-agents-pi5)
2. Chunks content by markdown headings (preserving structure)
3. Creates embeddings using Ollama (nomic-embed-text)
4. Upserts chunks to Qdrant with rich metadata

Network Configuration (wiki-bridge):
- Wiki API: http://172.20.0.3:8000/ingest/wiki
- Ollama: http://172.20.0.4:11434/api/embed
- Qdrant: http://172.20.0.5:6333
"""

import os
import sys
import re
import json
import time
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple

import requests
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm


# ==================== Configuration ====================

# Network IPs (wiki-bridge)
WIKI_API_URL = os.getenv("WIKI_API_URL", "http://172.20.0.3:8000/ingest/wiki")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://172.20.0.4:11434/api/embed")
QDRANT_URL = os.getenv("QDRANT_URL", "http://172.20.0.5:6333")

# API Key for Wiki.js
WIKI_API_KEY = os.getenv("WIKI_API_KEY", "")

# Chunking parameters
CHUNK_MAX_WORDS = 500  # Max words per chunk before splitting at heading
MIN_HEADING_LEVEL = 1  # Only split on h1, h2, h3 (not h4+)
MAX_HEADING_LEVEL = 3

# Qdrant settings
QDRANT_COLLECTION = "rag_docs"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
VECTOR_SIZE = 768  # nomic-embed-text output dimension

# Retry settings
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


# ==================== Helper Functions ====================

def get_qdrant_client():
    """Initialize Qdrant client."""
    return QdrantClient(url=QDRANT_URL)


def get_ollama_embeddings():
    """Initialize Ollama embeddings client."""
    return OllamaEmbeddings(
        model=EMBEDDING_MODEL,
        base_url=OLLAMA_URL,
    )


def ensure_collection(client: QdrantClient) -> None:
    """Ensure Qdrant collection exists with proper schema."""
    existing = {c.name for c in client.get_collections().collections}
    
    if QDRANT_COLLECTION not in existing:
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=qm.VectorParams(
                size=VECTOR_SIZE,
                distance=qm.Distance.COSINE,
            ),
        )


def fetch_wiki_pages(api_key: str) -> List[Dict]:
    """Fetch all wiki pages from the API."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    query = """
    {
        pages {
            tree {
                id
                path
                title
            }
        }
    }
    """
    
    payload = {"query": query}
    
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(
                WIKI_API_URL,
                json=payload,
                headers=headers,
                timeout=30,
            )
            r.raise_for_status()
            
            data = r.json()
            if "errors" in data:
                raise Exception(f"Wiki.js GraphQL error: {data['errors']}")
            
            pages = data["data"]["pages"]["tree"]
            return pages
            
        except requests.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                print(f"Wiki API request failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                raise


def fetch_page_content(api_key: str, page_id: int) -> Optional[str]:
    """Fetch content of a specific wiki page."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    query = f"""
    {{
        pages {{
            single(id: {page_id}) {{
                content
            }}
        }}
    }}
    """
    
    payload = {"query": query}
    
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(
                WIKI_API_URL,
                json=payload,
                headers=headers,
                timeout=30,
            )
            r.raise_for_status()
            
            data = r.json()
            if "errors" in data:
                raise Exception(f"Wiki.js GraphQL error: {data['errors']}")
            
            page = data["data"]["pages"]["single"]
            return page.get("content", "")
            
        except requests.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                print(f"Failed to fetch page {page_id} (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                return None


# ==================== Chunking Logic ====================

def parse_markdown_headings(content: str) -> List[Dict]:
    """
    Parse markdown content and split into chunks by headings.
    
    Each chunk contains:
    - heading_level: 1-3 (h1, h2, h3)
    - heading_text: The text of the heading
    - content: Content from this heading until next heading or max words
    
    Returns list of chunk dictionaries with full metadata.
    """
    
    # Regex to match markdown headings (h1, h2, h3)
    heading_pattern = re.compile(r'^(#{1,3})\s+(.+?)(?:\n|$)')
    
    # Split content into lines for processing
    lines = content.split('\n')
    
    chunks = []
    current_chunk = {
        "heading_level": None,
        "heading_text": "",
        "content_lines": [],
    }
    
    word_count = 0
    
    for line in lines:
        # Skip empty lines and code blocks
        stripped = line.strip()
        if not stripped or line.startswith('```'):
            current_chunk["content_lines"].append(line)
            continue
        
        # Check if this line is a heading
        match = heading_pattern.match(line)
        if match:
            # Save previous chunk if it has content
            if current_chunk["heading_level"] is not None and len(current_chunk["content_lines"]) > 0:
                chunks.append(_finalize_chunk(current_chunk, word_count))
            
            # Start new chunk with this heading
            current_chunk = {
                "heading_level": int(match.group(1).count('#')),
                "heading_text": match.group(2).strip(),
                "content_lines": [],
            }
            word_count = 0
        else:
            current_chunk["content_lines"].append(line)
            
            # Count words in content (rough estimate)
            word_count += len(stripped.split())
            
            # Check if we've reached max words and there's no pending heading
            if word_count >= CHUNK_MAX_WORDS:
                # Check if next line is a heading
                if lines.index(line) + 1 < len(lines):
                    next_line = lines[lines.index(line) + 1]
                    if heading_pattern.match(next_line):
                        # Save current chunk and start new one
                        chunks.append(_finalize_chunk(current_chunk, word_count))
                        current_chunk = {
                            "heading_level": None,
                            "heading_text": "",
                            "content_lines": [],
                        }
                        word_count = 0
    
    # Don't forget the last chunk
    if current_chunk["heading_level"] is not None and len(current_chunk["content_lines"]) > 0:
        chunks.append(_finalize_chunk(current_chunk, word_count))
    
    return chunks


def _finalize_chunk(chunk: Dict, word_count: int) -> Dict:
    """Finalize a chunk with all metadata."""
    
    content = '\n'.join(chunk["content_lines"])
    
    return {
        "page_id": chunk.get("page_id"),
        "path": chunk.get("path"),
        "title": chunk.get("title"),
        "chunk_index": len(chunk["content_lines"]),
        "parent_path": chunk.get("parent_path"),
        "heading_level": chunk["heading_level"],
        "heading_text": chunk["heading_text"],
        "content": content,
        "word_count": word_count,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_url": chunk.get("source_url"),
    }


def extract_tags(content: str) -> List[str]:
    """Extract tags/topics from content using keyword matching."""
    
    # Common technical topics to look for
    tag_keywords = [
        "LLM", "API", "Docker", "Python", "JavaScript", "Node.js",
        "Linux", "Raspberry Pi", "IoT", "MQTT", "REST", "GraphQL",
        "vector database", "embedding", "RAG", "chunking",
        "authentication", "authorization", "security",
    ]
    
    content_lower = content.lower()
    tags = []
    
    for keyword in tag_keywords:
        if keyword.lower() in content_lower:
            tags.append(keyword)
    
    return list(set(tags))[:5]  # Limit to top 5 tags


# ==================== Qdrant Operations ====================

def upsert_chunk_to_qdrant(
    client: QdrantClient,
    chunk: Dict,
    embeddings_client,
) -> bool:
    """Upsert a single chunk to Qdrant."""
    
    try:
        # Generate embedding for content
        response = embeddings_client.embed_query(chunk["content"])
        vector = response.embedding
        
        # Prepare point data
        point = qm.PointStruct(
            id=chunk["page_id"] * 1000 + chunk["chunk_index"],  # Unique point ID
            vector=vector,
            payload={
                "page_id": chunk["page_id"],
                "path": chunk["path"],
                "title": chunk["title"],
                "chunk_index": chunk["chunk_index"],
                "parent_path": chunk.get("parent_path"),
                "heading_level": chunk["heading_level"],
                "heading_text": chunk["heading_text"],
                "content": chunk["content"][:1000],  # Truncate for payload
                "word_count": chunk["word_count"],
                "created_at": chunk.get("created_at"),
                "source_url": chunk.get("source_url"),
                "tags": json.dumps(chunk.get("tags", [])),
            },
        )
        
        client.upsert(collection_name=QDRANT_COLLECTION, points=[point])
        return True
        
    except Exception as e:
        print(f"Failed to upsert chunk {chunk.get('page_id')}-{chunk.get('chunk_index')}: {e}")
        return False


def upsert_chunks_to_qdrant(
    client: QdrantClient,
    chunks: List[Dict],
    embeddings_client,
) -> int:
    """Upsert multiple chunks to Qdrant."""
    
    success_count = 0
    
    for chunk in chunks:
        if upsert_chunk_to_qdrant(client, chunk, embeddings_client):
            success_count += 1
    
    return success_count


# ==================== Main Sync Function ====================

def sync_wiki_to_qdrant(api_key: str) -> Dict:
    """Main function to sync wiki pages to Qdrant."""
    
    print(f"Starting wiki-sync at {datetime.now(timezone.utc).isoformat()}")
    
    # Initialize clients
    qdrant_client = get_qdrant_client()
    embeddings_client = get_ollama_embeddings()
    
    # Ensure collection exists
    ensure_collection(qdrant_client)
    
    # Fetch all wiki pages
    print("Fetching wiki pages...")
    pages = fetch_wiki_pages(api_key)
    print(f"Found {len(pages)} pages")
    
    # Process each page
    total_chunks = 0
    successful_upserts = 0
    
    for page in pages:
        print(f"Processing page '{page['title']}' (id={page['id']}, path={page['path']})...")
        
        # Fetch page content
        content = fetch_page_content(api_key, page['id'])
        
        if not content:
            print(f"  ⚠️  Could not fetch content for page {page['id']}")
            continue
        
        # Parse and chunk by headings
        chunks = parse_markdown_headings({
            "page_id": page['id'],
            "path": page['path'],
            "title": page['title'],
            "content": content,
        })
        
        total_chunks += len(chunks)
        
        # Extract tags from each chunk
        for chunk in chunks:
            chunk["tags"] = extract_tags(chunk["content"])
        
        # Upsert chunks to Qdrant
        upserted = upsert_chunks_to_qdrant(qdrant_client, chunks, embeddings_client)
        successful_upserts += upserted
        
        print(f"  ✓ Upserted {upserted}/{len(chunks)} chunks")
    
    print(f"\nSync complete: {successful_upserts}/{total_chunks} chunks upserted")
    
    return {
        "pages_processed": len(pages),
        "chunks_created": total_chunks,
        "chunks_upserted": successful_upserts,
    }


# ==================== Entry Point ====================

if __name__ == "__main__":
    api_key = os.getenv("WIKI_API_KEY", "")
    
    if not api_key:
        print("Error: WIKI_API_KEY environment variable is required")
        sys.exit(1)
    
    try:
        result = sync_wiki_to_qdrant(api_key)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
