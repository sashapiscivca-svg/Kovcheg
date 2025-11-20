from typing import List

class TextChunker:
    
    def __init__(self, max_chars: int = 1000, overlap: int = 100):
        self.max_chars = max_chars
        self.overlap = overlap

    def chunk(self, text: str) -> List[str]:
        if not text:
            return []

        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk = []
        current_length = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            if len(para) > self.max_chars:
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = []
                    current_length = 0
                
                for i in range(0, len(para), self.max_chars - self.overlap):
                    chunks.append(para[i : i + self.max_chars])
                continue

            if current_length + len(para) + 2 > self.max_chars:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = [para]
                current_length = len(para)
            else:
                current_chunk.append(para)
                current_length += len(para) + 2  # +2 for \n\n

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks
