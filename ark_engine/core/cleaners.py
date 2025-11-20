import re
import unicodedata

class TextCleaner:
    
    @staticmethod
    def normalize(text: str) -> str:
        if not text:
            return ""

        text = unicodedata.normalize('NFKC', text)

        text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch in "\n\t")

        text = re.sub(r'[ \t]+', ' ', text)

        text = re.sub(r'\n\s*\n', '\n\n', text)

        return text.strip()
