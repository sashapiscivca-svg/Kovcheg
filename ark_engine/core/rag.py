import logging
import re
import numpy as np
import lancedb
from typing import List, Tuple, Generator, Optional, Set
from sentence_transformers import SentenceTransformer

from ark_engine.core.models import ArkModule
from ark_engine.core.llm import LLMEngine

logger = logging.getLogger("ark_rag")

class ArkRAG:
    def __init__(self, module: ArkModule):
        self.module = module
        self.docs = module.content.docs
        self.llm = LLMEngine()

        # --- LanceDB Setup ---
        # Зчитуємо URI індексу з модуля. Якщо це старий модуль, поле може бути None.
        self.vector_index_uri = getattr(module.content, "vector_index_uri", None)
        self.vector_table = self._connect_lancedb()

        # --- Fallback: Keyword Index ---
        # Ми залишаємо простий індекс слів у пам'яті як резервний варіант
        self.doc_tokens: List[Set[str]] = [
            set(re.findall(r'\w+', doc.lower())) for doc in self.docs
        ]

    def _connect_lancedb(self) -> Optional[lancedb.table.Table]:
        """
        Встановлює з'єднання з дисковою таблицею векторів.
        """
        if not self.vector_index_uri:
            logger.warning("Vector index URI missing. RAG will default to keyword search.")
            return None

        try:
            # Підключаємося до локальної папки як до бази даних
            db = lancedb.connect(self.vector_index_uri)
            # Відкриваємо таблицю 'vectors', створену в ArkBuilder
            return db.open_table("vectors")
        except Exception as e:
            logger.error(f"Failed to open LanceDB index at {self.vector_index_uri}: {e}")
            return None

    def _simple_keyword_score(self, query: str) -> np.ndarray:
        """
        Швидкий алгоритм (Jaccard-like) для підрахунку співпадіння слів.
        Використовується, коли векторний пошук недоступний.
        """
        query_tokens = set(re.findall(r'\w+', query.lower()))
        if not query_tokens:
            return np.zeros(len(self.docs))
            
        scores = []
        for doc_set in self.doc_tokens:
            if not doc_set:
                scores.append(0.0)
                continue
            # Кількість спільних слів
            common = len(query_tokens.intersection(doc_set))
            # Нормалізуємо по довжині запиту для отримання score 0..1
            scores.append(common / len(query_tokens))
            
        return np.array(scores)

    def search(self, query: str, top_k: int = 3) -> List[Tuple[str, float]]:
        """
        Виконує пошук:
        1. Спроба векторного пошуку через LanceDB (Disk-based).
        2. Fallback до ключових слів, якщо LanceDB недоступний.
        """
        if not self.docs:
            return []

        results: List[Tuple[str, float]] = []
        used_vector_search = False

        # --- 1. LanceDB Vector Search ---
        if self.vector_table:
            try:
                embedder = SentenceTransformer('all-MiniLM-L6-v2')
                query_vec = embedder.encode(query).tolist()

                # --- ВИПРАВЛЕННЯ ТУТ: metric="cosine" ---
                # Це змушує LanceDB рахувати косинусну відстань, що поверне звичні нам скори.
                df = self.vector_table.search(query_vec).metric("cosine").limit(top_k).to_pandas()

                for _, row in df.iterrows():
                    # При metric="cosine", _distance = 1 - cosine_similarity
                    # Тобто якщо similarity 0.8, то _distance 0.2
                    # Формула score = 1.0 - dist поверне 0.8 (80%), що нам і треба.
                    dist = float(row.get('_distance', 0.0))
                    score = max(0.0, 1.0 - dist) 
                    
                    text_content = row.get('text', "")
                    results.append((text_content, score))

                if results:
                    used_vector_search = True
                    results.sort(key=lambda x: x[1], reverse=True)

            except Exception as e:
                logger.error(f"LanceDB search error: {e}. Switching to fallback.")

        # --- 2. Fallback: Keyword Search ---
        if not used_vector_search:
            logger.info("Using Keyword Fallback Search")
            scores = self._simple_keyword_score(query)
            
            top_indices = np.argsort(scores)[-top_k:][::-1]
            
            for idx in top_indices:
                score = float(scores[idx])
                if score > 0.0:
                    results.append((self.docs[idx], score))

        return results

    def ask_stream(self, query: str) -> Generator[str, None, None]:
        """
        Генерує відповідь LLM на основі знайдених джерел.
        """
        results = self.search(query, top_k=3)
        
        if not results:
            yield "Інформація відсутня в базі знань (не знайдено релевантних документів)."
            return

        context_text = "\n\n".join([
            f"[Джерело {i+1}]: {txt[:1000]}..." 
            for i, (txt, _) in enumerate(results)
        ])
        
        yield from self.llm.generate_stream(query, context_text)
