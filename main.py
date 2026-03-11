from dotenv import load_dotenv
load_dotenv()

import os, threading, uuid, time
import numpy as np
import faiss
import requests

from ollama import Client
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

# ================= CONFIG =================
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
CHAT_MODEL = "gpt-oss:120b"
EMBED_MODEL = "mxbai-embed-large"
EMBED_URL = os.getenv("OLLAMA_EMBED_BASE_URL", "http://ollama:11434")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///rag.db")
MAX_HISTORY = 5  # for session memory

# ================= OLLAMA CLIENT =================
ollama_client = Client(
    host="https://ollama.com",
    headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"}
)

# ================= DATABASE =================
Base = declarative_base()

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    text = Column(Text, nullable=False)
    source = Column(String, nullable=False)
    url = Column(String, default="")
    doc_type = Column(String, default="report")
    indexed = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

# ================= APP =================
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= SCHEMAS =================
class Ingest(BaseModel):
    text: str
    source: str
    url: str = ""
    doc_type: str = "report"

class Query(BaseModel):
    query: str
    session_id: str | None = None

# ================= GLOBALS =================
index = None
documents = []          # chunk text
document_meta = []      # source + url per chunk
index_lock = threading.Lock()
SESSION_MEMORY = {}     # store last MAX_HISTORY interactions per session

# ================= FAISS =================
def ensure_faiss(dim: int):
    global index
    if index is None:
        index = faiss.IndexFlatL2(dim)
        print("✅ FAISS initialized")

# ================= EMBEDDING =================
def ollama_embed(text: str) -> np.ndarray:
    r = requests.post(
        f"{EMBED_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": text},
        timeout=60
    )
    r.raise_for_status()
    return np.array(r.json()["embeddings"][0], dtype="float32")

# ================= CHAT =================
def ollama_chat(prompt: str) -> str:
    r = ollama_client.chat(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=False
    )
    return r["message"]["content"]

# ================= INDEX WORKER =================
def index_worker():
    print("🧵 Index worker started")
    db = SessionLocal()

    while True:
        docs = db.query(Document).filter(Document.indexed == 0).limit(1).all()
        if not docs:
            time.sleep(2)
            continue

        for doc in docs:
            chunks = [
                doc.text[i:i+400]
                for i in range(0, len(doc.text), 400)
                if len(doc.text[i:i+400].strip()) > 50
            ]

            for chunk in chunks:
                try:
                    emb = ollama_embed(chunk)
                    with index_lock:
                        ensure_faiss(len(emb))
                        index.add(np.array([emb]))
                        documents.append(chunk)
                        document_meta.append({
                            "source": doc.source,
                            "url": doc.url,
                            "type": doc.doc_type
                        })
                except Exception as e:
                    print("⚠️ Embed failed:", e)

            doc.indexed = 1
            db.commit()

# ================= STARTUP =================
@app.on_event("startup")
def startup():
    threading.Thread(target=index_worker, daemon=True).start()
    print("🚀 RAG API ready")

# ================= INGEST =================
@app.post("/ingest")
async def ingest(item: Ingest):
    db = SessionLocal()
    db.add(Document(**item.dict(), indexed=0))
    db.commit()
    db.close()
    return {"status": "queued"}

# ================= RAG =================
@app.post("/rag")
async def rag(q: Query):
    if index is None or index.ntotal == 0:
        if not q.session_id:
            q.session_id = str(uuid.uuid4())
        return {"answer": "Indexing in progress. Try again.", "sources": [], "session_id": q.session_id}

    # create session memory
    if not q.session_id:
        q.session_id = str(uuid.uuid4())
    SESSION_MEMORY.setdefault(q.session_id, [])

    # 1️⃣ Embed the query
    q_emb = ollama_embed(q.query)

    # 2️⃣ Search FAISS
    with index_lock:
        D, I = index.search(np.array([q_emb]), k=5)

    # 3️⃣ Gather retrieved chunks and their sources
    context_chunks = []
    retrieved_sources = []
    for i in I[0]:
        if i < len(documents):
            context_chunks.append(documents[i])
            retrieved_sources.append(document_meta[i])

    # 4️⃣ Deduplicate sources
    seen = set()
    unique_sources = []
    for s in retrieved_sources:
        key = (s["source"], s["url"])
        if key not in seen:
            unique_sources.append(s)
            seen.add(key)
    if not unique_sources and retrieved_sources:
        unique_sources = [retrieved_sources[0]]

    sources_text = "\n".join(f"[{i+1}] {s['source']} ({s['url']})" for i, s in enumerate(unique_sources))

    # 5️⃣ Build prompt using session memory
    previous_history = SESSION_MEMORY[q.session_id]
    history_text = "\n".join(f"Q: {h['q']}\nA: {h['a']}" for h in previous_history)
    context_text = "\n\n".join(context_chunks)
    prompt = f"""
You are a venture capital analyst.

MANDATORY:
- Use ONLY the sources listed below
- Append citation markers like [1], [2] for factual claims
- Do NOT invent new citations
- If information is not in sources, say you are unsure
- Answer in same language as the user query
- Ignore previous conversation history if it is not relevant
- Don't criticise dataset, say you are just don't know if needed, never mention dataset to user
Sources:
{sources_text}

Context from retrieved documents:
{context_text}

Previous conversation history:
{history_text}

User: {q.query.strip()}
Assistant:
"""

    # 6️⃣ Call LLM
    answer = ollama_chat(prompt)

    # update session memory
    SESSION_MEMORY[q.session_id].append({"q": q.query, "a": answer})
    SESSION_MEMORY[q.session_id] = SESSION_MEMORY[q.session_id][-MAX_HISTORY:]

    return {
        "answer": answer,
        "sources": unique_sources,
        "session_id": q.session_id,
        "retrieved_chunks": len(context_chunks)
    }

# ================= HEALTH =================
@app.get("/health")
async def health():
    return {"status": "ok", "chunks": index.ntotal if index else 0}
