from typing import List, Dict

class Indexer:
    
    @staticmethod
    def build_index(doc_sources: List[str]) -> List[Dict[str, str]]:
        index = []
        for i, source in enumerate(doc_sources):
            index.append({
                "id": i,
                "source": str(source)
            })
        return index
