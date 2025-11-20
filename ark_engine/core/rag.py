import numpy as np
from typing import List, Tuple
from sentence_transformers import SentenceTransformer

from ark_engine.core.models import ArkModule

class ArkRAG:
    def __init__(self, module: ArkModule):
        self.module = module
        self.doc_embeddings = np.array(module.content.embeddings)
        self.docs = module.content.docs
        
        self.model = SentenceTransformer('all-MiniLM-L6-v2')

    def search(self, query: str, top_k: int = 3) -> List[Tuple[str, float]]:
        """
        Performs cosine similarity search.
        Returns list of (document_text, score).
        """
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
            results.append((self.docs[idx], float(scores[idx])))

        return results

    def ask(self, query: str) -> str:
        """
        Retrieves context and constructs a prompt for the LLM.
        """
        results = self.search(query, top_k=3)
        
        if not results:
            return "I could not find any relevant information in this Ark module."

        context_text = "\n\n".join([f"- {text}" for text, score in results])
        
        prompt = (
            f"SYSTEM: You are an offline assistant using the '{self.module.header.title}' knowledge base.\n"
            f"CONTEXT:\n{context_text}\n\n"
            f"USER QUERY: {query}\n\n"
            f"ANSWER:"
        )
        
        return f"[LLM STUB OUTPUT]\nBased on the context provided:\n{context_text}\n\n(Real generation pending integration)"
