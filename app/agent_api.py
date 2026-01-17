from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import os, json, tempfile
from langchain_ollama import OllamaLLM, OllamaEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langgraph.graph import StateGraph, MessagesState, END
import operator

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])

# Paths (production)
CHROMA_PATH = "/chromadb"
AGENT_MEMORY = "/agent_data/memory.json"
EBOOKS_PATH = "/ebooks"

llm = OllamaLLM(model="qwen2.5:7b-instruct", temperature=0.1)
embeddings = OllamaEmbeddings(model="nomic-embed-text")

class ChatRequest(BaseModel):
    message: str

class AgentState(MessagesState):
    agent_memory: dict = {}

# 4 Agents
AGENT_PROMPTS = {
    "devops": "DevOps expert. CUPS/Samba/Linux from docs/wiki. YAML output.",
    "code": "Python/.NET/Playwright reviewer. Extract/fix code from ebooks.",
    "ebook_research": "Technical researcher. Books + wiki synthesis.",
    "finance": "Indian finance consultant. NPS/PPF conservative advice."
}

def route_agent(state):
    query
