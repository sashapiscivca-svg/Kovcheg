import numpy as np
import re
from typing import List, Tuple, Generator
from sentence_transformers import SentenceTransformer
# rank_bm25 видалено

from ark_engine.core.models import ArkModule
from ark_engine.core.llm import LLMEngine

class ArkRAG:
    def __init__(self, module: ArkModule):
        self.module = module
        self.docs = module.content.docs
        self.doc_embeddings = np.array(module.content.embeddings)
        
        # Легка модель
        self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
        self.llm = LLMEngine()

        # Попередній розрахунок слів для швидкого пошуку
        # set() працює миттєво
        self.doc_tokens = [set(re.findall(r'\w+', doc.lower())) for doc in self.docs]

    def _simple_keyword_score(self, query: str) -> np.ndarray:
        """
        Надшвидкий алгоритм замість BM25.
        Рахує % співпадіння слів.
        """
        query_tokens = set(re.findall(r'\w+', query.lower()))
        if not query_tokens:
            return np.zeros(len(self.docs))
            
        scores = []
        for doc_set in self.doc_tokens:
            if not doc_set:
                scores.append(0.0)
                continue
            # Перетин множин: скільки слів запиту є в документі
            common = len(query_tokens.intersection(doc_set))
            scores.append(common)
            
        return np.array(scores)

    def search(self, query: str, top_k: int = 3) -> List[Tuple[str, float]]:
        if not self.docs: return []

        # 1. Векторний пошук (Сенс)
        query_vec = self.embedder.encode(query)
        vector_scores = np.dot(self.doc_embeddings, query_vec)
        
        # Нормалізація векторів (0..1)
        v_min, v_max = vector_scores.min(), vector_scores.max()
        if v_max != v_min:
            vector_scores = (vector_scores - v_min) / (v_max - v_min)

        # 2. Ключовий пошук (Точність) - ТЕПЕР ЛЕГКИЙ
        keyword_scores = self._simple_keyword_score(query)
        
        # Нормалізація ключових слів (0..1)
        k_min, k_max = keyword_scores.min(), keyword_scores.max()
        if k_max != k_min:
            keyword_scores = (keyword_scores - k_min) / (k_max - k_min)

        # 3. Злиття (Гібрид)
        # 60% Вектор (розум) + 40% Слова (точність)
        final_scores = (0.6 * vector_scores) + (0.4 * keyword_scores)

        # Сортування
        top_indices = np.argsort(final_scores)[-top_k:][::-1]

        results = []
        for idx in top_indices:
            if final_scores[idx] > 0.2:
                results.append((self.docs[idx], float(final_scores[idx])))
        
        return results

    def ask_stream(self, query: str) -> Generator[str, None, None]:
        # Використовуємо top_k=3, бо ми полегшили пошук
        results = self.search(query, top_k=3)
        
        if not results:
            yield "Інформація відсутня в базі знань."
            return

        # Обрізаємо текст до 1000 символів на шматок, щоб не перевантажити RAM
        context_text = "\n".join([
            f"[Джерело {i+1}]: {txt[:1000]}..." 
            for i, (txt, _) in enumerate(results)
        ])
        
        yield from self.llm.generate_stream(query, context_text)
