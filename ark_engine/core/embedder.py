from typing import List
from sentence_transformers import SentenceTransformer

class Embedder:
    """
    Обгортка для локальної моделі Sentence Transformers.
    """
    def __init__(self, model_name: str = 'all-MiniLM-L6-v2'):
        print(f"Loading embedding model: {model_name}...")
        self.model = SentenceTransformer(model_name)

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        
        embeddings = self.model.encode(texts, show_progress_bar=True)
        return embeddings.tolist()
