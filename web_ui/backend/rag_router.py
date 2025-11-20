import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from pathlib import Path

from ark_engine.core.loader import ArkLoader
from ark_engine.core.rag import ArkRAG
from web_ui.backend.settings import settings

router = APIRouter()

# Кеш для RAG-рушіїв: {module_id: ArkRAG_Instance}
RAG_ENGINES = {}

class SourceChunk(BaseModel):
    chunk: str
    score: float

class AskRequest(BaseModel):
    query: str = Field(..., description="The user's question.")
    module_id: Optional[str] = Field(None, description="ID of the specific module to query.")

class AskResponse(BaseModel):
    answer: str = Field(..., description="The final answer from the RAG system (LLM Stub).")
    sources: List[SourceChunk]

def find_module_path_by_id(target_id: str) -> Optional[Path]:
    """
    Сканує папку даних і шукає файл, чий header.id співпадає з target_id.
    """
    search_path = Path(settings.ARK_MODULES_PATH)
    if not search_path.exists():
        return None
        
    # Перебираємо всі .ark.json файли
    for file_path in search_path.glob("*.ark.json"):
        try:
            # Швидко читаємо тільки JSON, щоб перевірити ID
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Перевірка безпечна: якщо header немає, просто пропускаємо
                if data.get("header", {}).get("id") == target_id:
                    return file_path
        except Exception as e:
            print(f"Error scanning {file_path}: {e}")
            continue
            
    return None

def get_rag_engine(module_id: str) -> ArkRAG:
    # 1. Перевіряємо кеш
    if module_id in RAG_ENGINES:
        return RAG_ENGINES[module_id]

    # 2. Якщо немає в кеші, шукаємо файл на диску
    file_path = find_module_path_by_id(module_id)
    
    if not file_path:
        print(f"❌ Module ID {module_id} not found in {settings.ARK_MODULES_PATH}")
        raise HTTPException(status_code=404, detail=f"Module ID {module_id} not found on disk.")

    # 3. Завантажуємо та ініціалізуємо
    print(f"📂 Loading module from: {file_path}")
    try:
        module = ArkLoader.load(file_path)
        rag_engine = ArkRAG(module)
        
        # Зберігаємо в кеш
        RAG_ENGINES[module_id] = rag_engine
        return rag_engine
    except Exception as e:
        print(f"🔥 Failed to load module: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load module: {e}")

@router.post("/ask", response_model=AskResponse)
def ask_question(request: AskRequest):
    # Якщо ID не вказано, спробуємо знайти хоч щось (для тестів)
    target_module_id = request.module_id
    
    if not target_module_id:
        # Якщо кеш порожній, спробуємо завантажити перший ліпший файл
        search_path = Path(settings.ARK_MODULES_PATH)
        first_file = next(search_path.glob("*.ark.json"), None)
        if first_file:
            # Отримуємо його ID
            try:
                 with open(first_file, 'r') as f:
                    data = json.load(f)
                    target_module_id = data["header"]["id"]
            except:
                pass
        
        if not target_module_id:
             raise HTTPException(status_code=400, detail="No modules found. Please build an ark module first.")

    try:
        rag_engine = get_rag_engine(target_module_id)
        
        # Пошук
        search_results = rag_engine.search(request.query, top_k=3)
        
        # Генерація відповіді
        llm_response = rag_engine.ask(request.query)
        
        return AskResponse(
            answer=llm_response,
            sources=[SourceChunk(chunk=text, score=score) for text, score in search_results]
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"RAG Error: {e}")
        raise HTTPException(status_code=500, detail=f"Internal RAG processing error: {e}")
