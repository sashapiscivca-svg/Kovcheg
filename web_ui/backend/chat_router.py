import shutil
import os
from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import json
from pathlib import Path

from web_ui.backend import db
from web_ui.backend.session_manager import get_session
from web_ui.backend.rag_router import get_or_load_rag

router = APIRouter()

class CreateChatReq(BaseModel):
    title: str

class ChatMessage(BaseModel):
    role: str
    content: str
    sources: Optional[List[dict]] = None
    created_at: str

class ChatHistory(BaseModel):
    id: str
    title: str
    messages: List[ChatMessage]

@router.get("/chats")
def list_chats():
    return db.get_chats()

@router.post("/chats")
def create_new_chat(req: CreateChatReq):
    chat_id = db.create_chat(req.title)
    return {"id": chat_id, "title": req.title}

@router.delete("/chats/{chat_id}")
def delete_chat(chat_id: str):
    db.delete_chat(chat_id)
    return {"status": "ok"}

@router.get("/chats/{chat_id}", response_model=ChatHistory)
def get_chat_details(chat_id: str):
    msgs = db.get_messages(chat_id)
    chats = db.get_chats()
    title = next((c['title'] for c in chats if c['id'] == chat_id), "Chat")
    return {"id": chat_id, "title": title, "messages": msgs}

@router.post("/chats/{chat_id}/upload")
async def upload_file_to_chat(chat_id: str, file: UploadFile = File(...)):
    temp_dir = Path("/app/data/temp_uploads")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = temp_dir / file.filename
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        session = get_session(chat_id)
        chunks_count = session.ingest_file(file_path)
        
        db.add_message(chat_id, "system", f"Завантажено файл: {file.filename} ({chunks_count} фрагментів).")
        
        return {"status": "ok", "filename": file.filename, "chunks": chunks_count}
    finally:
        if file_path.exists():
            os.remove(file_path)

@router.post("/chats/{chat_id}/ask_stream")
async def ask_chat_stream(chat_id: str, req: dict):
    query = req.get("query")
    module_id = req.get("module_id")
    
    if not query: raise HTTPException(400, "Query empty")

    session = get_session(chat_id)
    
    if module_id:
        try:
            base_rag = get_or_load_rag(module_id)
            session.set_base_module(base_rag)
        except Exception as e:
            print(f"Warning: Could not load base module: {e}")

    db.add_message(chat_id, "user", query)

    def iter_response():
        # Збільшено top_k з 3 до 6 для кращого контексту
        sources = session.search(query, top_k=6)
        
        sources_data = [{"chunk": t, "score": float(s)} for t, s in sources]
        
        yield json.dumps({"type": "sources", "data": sources_data}, ensure_ascii=False) + "\n"

        full_answer = ""
        for token in session.ask_stream(query):
            full_answer += token
            yield json.dumps({"type": "token", "content": token}, ensure_ascii=False) + "\n"
        
        db.add_message(chat_id, "system", full_answer, sources=sources_data)

    return StreamingResponse(iter_response(), media_type="application/x-ndjson")
