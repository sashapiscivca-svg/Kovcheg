import logging
import os
from pathlib import Path
from llama_cpp import Llama

logger = logging.getLogger("ark_llm")

# --- СИСТЕМНИЙ ПРОМПТ (V5: FLEXIBLE ANALYST) ---
SYSTEM_PROMPT_TEXT = """ТИ — ІНТЕЛЕКТУАЛЬНИЙ АНАЛІТИК СИСТЕМИ "КОВЧЕГ".
ТВОЯ ЦІЛЬ: Допомогти користувачеві розібратися в наданих документах.

ПРАВИЛА РОБОТИ:
1. АНАЛІЗУЙ КОНТЕКСТ: Використовуй надані фрагменти тексту (Chunks) як основу для відповіді.
2. СИНТЕЗУЙ: Якщо пряма відповідь розкидана по декількох фрагментах, об'єднай їх у цілісну думку.
3. РОБИ ВИСНОВКИ: Якщо точної відповіді немає, але є дотична інформація (наприклад, згадується назва документа, але не його зміст) — опиши те, що є, і припусти, про що йдеться, вказавши, що це припущення.
4. НЕ ВІДМОВЛЯЙСЯ: Замість "Інформація відсутня", напиши: "На основі доступних фрагментів я знайшов наступне..." і виклади все, що хоч трохи стосується теми.
5. МОВА: Відповідай мовою запиту (українською).
"""

class LLMEngine:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LLMEngine, cls).__new__(cls)
            cls._instance._model = None
        return cls._instance

    def load_model(self):
        if self._model is not None: return

        default_path = Path("/app/models_cache/qwen2.5-3b-instruct.gguf")
        if default_path.exists():
            model_path = default_path
        else:
            found = list(Path("/app/models_cache").glob("*.gguf"))
            if found: model_path = found[0]
            else: raise FileNotFoundError("Model not found!")

        logger.info(f"🚀 Loading LLM: {model_path}")
        
        total_threads = os.cpu_count() or 4
        safe_threads = max(1, total_threads - 1)

        self._model = Llama(
            model_path=str(model_path),
            n_ctx=4096,           
            n_threads=safe_threads, 
            n_batch=512,
            use_mmap=True,        
            use_mlock=False,      
            verbose=False
        )

    def generate_stream(self, query: str, context: str):
        self.load_model()
        
        limit = 10000 
        if len(context) > limit:
            context = context[:limit] + "... [контекст обрізано]"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_TEXT},
            {"role": "user", "content": f"ДОКУМЕНТИ:\n{context}\n\nЗАПИТАННЯ КОРИСТУВАЧА:\n{query}"}
        ]

        stream = self._model.create_chat_completion(
            messages=messages,
            max_tokens=1024,
            temperature=0.3, 
            stream=True
        )

        for chunk in stream:
            delta = chunk["choices"][0]["delta"]
            if "content" in delta:
                yield delta["content"]
