import json
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List
from pathlib import Path

from ark_engine.core.loader import ArkLoader
from ark_engine.core.rag import ArkRAG
from web_ui.backend.settings import settings

logger = logging.getLogger("rag_router")
router = APIRouter()

RAG_CACHE = {}

class AskRequest(BaseModel):
    query: str
    module_id: str

def get_or_load_rag(module_id: str) -> ArkRAG:
    if module_id in RAG_CACHE:
        return RAG_CACHE[module_id]

    search_path = Path(settings.ARK_MODULES_PATH)
    target_file = None
    
    # Оптимізований пошук файлу
    for f_path in search_path.glob("*.ark.json"):
        if module_id in f_path.name: # Хак для швидкості, краще хешмапу
            target_file = f_path
            break
            
    # Якщо не знайшли швидко, шукаємо повільно (всередині JSON)
    if not target_file:
        for f_path in search_path.glob("*.ark.json"):
            try:
                with open(f_path, 'r', encoding='utf-8') as f:
                    # Читаємо тільки початок файлу для ID
                    head = f.read(1024) 
                    if module_id in head: 
                        target_file = f_path
                        break
            except: continue

    if not target_file:
        raise HTTPException(status_code=404, detail="Module not found")

    logger.info(f"Loading {target_file}...")
    module = ArkLoader.load(target_file)
    rag = ArkRAG(module)
    RAG_CACHE[module_id] = rag
    return rag

@router.post("/ask_stream")
async def ask_question_stream(req: AskRequest):
    """Новий ендпоінт для потокової передачі"""
    rag_engine = get_or_load_rag(req.module_id)

    # Генератор, який спочатку віддає метадані (джерела), а потім текст
    def iter_response():
        # 1. Спочатку шукаємо джерела
        sources = rag_engine.search(req.query, top_k=3)
        
        # Відправляємо джерела як перший чанк (JSON рядок)
        sources_data = json.dumps({
            "type": "sources",
            "data": [{"chunk": t, "score": s} for t, s in sources]
        }, ensure_ascii=False)
        yield sources_data + "\n"

        # 2. Потім стрімимо токени
        for token in rag_engine.ask_stream(req.query):
            # Екрануємо спецсимволи для JSON, якщо треба, або шлемо raw
            # Тут використовуємо простий формат: prefix "data: "
            msg = json.dumps({"type": "token", "content": token}, ensure_ascii=False)
            yield msg + "\n"

    return StreamingResponse(iter_response(), media_type="application/x-ndjson")
