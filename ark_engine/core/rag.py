import numpy as np
from typing import List, Tuple
from sentence_transformers import SentenceTransformer

from ark_engine.core.models import ArkModule
# НОВИЙ ІМПОРТ
from ark_engine.core.llm import LLMEngine 

class ArkRAG:
    def __init__(self, module: ArkModule):
        self.module = module
        # Конвертуємо ембеддінги у numpy array
        self.doc_embeddings = np.array(module.content.embeddings)
        self.docs = module.content.docs
        
        # Модель для пошуку (маленька, швидка)
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Ініціалізуємо LLM (вона завантажиться тільки при першому запиті)
        self.llm = LLMEngine()

    def search(self, query: str, top_k: int = 3) -> List[Tuple[str, float]]:
        """Пошук релевантних шматків тексту (без змін)."""
        if len(self.doc_embeddings) == 0:
            return []

        query_embedding = self.model.encode(query)
        
        norm_docs = np.linalg.norm(self.doc_embeddings, axis=1)
        norm_query = np.linalg.norm(query_embedding)
        
        norm_docs[norm_docs == 0] = 1e-10
        if norm_query == 0:
            norm_query = 1e-10

        dot_products = np.dot(self.doc_embeddings, query_embedding)
        scores = dot_products / (norm_docs * norm_query)

        top_indices = np.argsort(scores)[-top_k:][::-1]

        results = []
        for idx in top_indices:
            # Фільтруємо дуже слабкі збіги
            if scores[idx] > 0.25:
                results.append((self.docs[idx], float(scores[idx])))

        return results

    def ask(self, query: str) -> str:
        """
        Retrieves context and generates a REAL answer using Offline LLM.
        """
        # 1. Шукаємо контекст
        results = self.search(query, top_k=5) # Беремо більше контексту (5 шматків)
        
        if not results:
            return "У цьому модулі немає інформації, що відповідає вашому запиту."

        # 2. Склеюємо контекст
        context_text = "\n---\n".join([text for text, score in results])
        
        # 3. Генерація через LLM
        try:
            response = self.llm.generate_response(query, context_text)
            return response
        except Exception as e:
            return f"Помилка генерації LLM: {str(e)}"
