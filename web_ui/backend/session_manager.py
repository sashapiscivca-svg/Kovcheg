import shutil
import os
import logging
from pathlib import Path
from typing import List, Dict

# Імпорти ядра
from ark_engine.core.text_loader import MonsterLoader
from ark_engine.core.chunker import TextChunker
from ark_engine.core.embedder import Embedder
from ark_engine.core.rag import ArkRAG
from ark_engine.core.models import ArkModule, ArkContent

logger = logging.getLogger("session_manager")

class SessionRAG:
    """
    Об'єднує основний модуль .ark та тимчасові файли користувача.
    """
    def __init__(self, base_rag: ArkRAG = None):
        self.base_rag = base_rag
        self.dynamic_rag = None # RAG для завантажених файлів
        self.temp_docs = []
        self.temp_embeddings = []

    def set_base_module(self, rag: ArkRAG):
        self.base_rag = rag

    def ingest_file(self, file_path: Path):
        """Обробка файлу користувача на льоту."""
        logger.info(f"Ingesting user file: {file_path}")
        
        # 1. Load text
        loader = MonsterLoader()
        text = loader.load(file_path)
        if not text: return 0

        # 2. Chunk
        chunker = TextChunker(max_chars=1000)
        chunks = chunker.chunk(text)
        
        # 3. Embed
        embedder = Embedder('all-MiniLM-L6-v2') # Та сама модель
        embeddings = embedder.embed(chunks)

        # 4. Add to dynamic storage
        self.temp_docs.extend(chunks)
        self.temp_embeddings.extend(embeddings)

        # 5. Re-build dynamic RAG instance
        # Ми створюємо фейковий модуль, щоб використати існуючий клас ArkRAG
        fake_content = ArkContent(
            docs=self.temp_docs,
            embeddings=self.temp_embeddings
        )
        # Створюємо мінімальний об'єкт-заглушку
        class MockModule:
            def __init__(self, content): self.content = content
        
        self.dynamic_rag = ArkRAG(MockModule(fake_content))
        return len(chunks)

    def search(self, query: str, top_k: int = 3):
        results = []
        
        # Пошук в основному модулі
        if self.base_rag:
            results.extend(self.base_rag.search(query, top_k=top_k))
            
        # Пошук у файлах користувача
        if self.dynamic_rag:
            results.extend(self.dynamic_rag.search(query, top_k=top_k))
            
        # Сортуємо все разом за релевантністю і беремо топ-K
        # results це список туплів (text, score)
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def ask_stream(self, query: str):
        # Використовуємо LLM з базового RAG (або створюємо новий, якщо бази немає)
        llm_engine = self.base_rag.llm if self.base_rag else None
        
        # Якщо бази немає, але є файли - треба ініціалізувати LLM
        if not llm_engine and self.dynamic_rag:
            llm_engine = self.dynamic_rag.llm
            
        if not llm_engine:
            yield "Система не готова. Завантажте модуль або файл."
            return

        # 1. Гібридний пошук
        results = self.search(query, top_k=6)
        
        if not results:
            yield "На жаль, я не знайшов достатньо релевантної інформації у ваших документах."
            return

        # 2. Контекст
        context = "\n".join([f"[Джерело {i+1}]: {txt}" for i, (txt, _) in enumerate(results)])
        
        # 3. Генерація
        yield from llm_engine.generate_stream(query, context)

# Глобальне сховище сесій {chat_id: SessionRAG}
# В реальному проді це має бути Redis або кеш з TTL
ACTIVE_SESSIONS: Dict[str, SessionRAG] = {}

def get_session(chat_id: str) -> SessionRAG:
    if chat_id not in ACTIVE_SESSIONS:
        ACTIVE_SESSIONS[chat_id] = SessionRAG()
    return ACTIVE_SESSIONS[chat_id]
