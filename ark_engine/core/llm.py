import logging
import os
from pathlib import Path
from llama_cpp import Llama

logger = logging.getLogger("ark_llm")

# --- СИСТЕМНИЙ ПРОМПТ (V4: UNIVERSAL ANALYST) ---
# Цей промпт працює з будь-якими даними: від інструкцій до художніх текстів.
SYSTEM_PROMPT_TEXT = """ТИ — УНІВЕРСАЛЬНИЙ АНАЛІТИЧНИЙ АСИСТЕНТ.
ТВОЯ ЦІЛЬ: Надати вичерпну відповідь, спираючись виключно на блок "КОНТЕКСТ".

ПРАВИЛА РОБОТИ:
1. ПРІОРИТЕТ КОНТЕКСТУ: Ігноруй свої попередні знання. Використовуй тільки те, що написано нижче.
2. РОЗУМІННЯ СУТІ: Якщо користувач питає загальними словами (наприклад, "яка формула", "як оцінюють", "правила"), а в тексті це називається специфічно (наприклад, "Індекс X", "Метрика Y", "Протокол безпеки") — ти ПОВИНЕН ідентифікувати це і навести як відповідь.
3. ТОЧНІСТЬ: Цифри, формули, імена та назви передавай без змін.
4. ВІДСУТНІСТЬ ФАНТАЗІЙ: Не вигадуй приклади розрахунків, якщо їх немає в тексті.
5. ЧЕСНІСТЬ: Якщо інформації немає в контексті, напиши: "У доступних документах інформація відсутня".
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
        
        # Конфігурація під i3-1115G4
        total_threads = os.cpu_count() or 4
        safe_threads = max(1, total_threads - 1)

        self._model = Llama(
            model_path=str(model_path),
            n_ctx=4096,           
            n_threads=safe_threads, 
            n_batch=512,          # Баланс швидкості та стабільності
            use_mmap=True,        
            use_mlock=False,      
            verbose=False
        )

    def generate_stream(self, query: str, context: str):
        self.load_model()
        
        # Обрізка контексту для швидкості (безпечний ліміт)
        limit = 3000
        if len(context) > limit:
            context = context[:limit] + "..."

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_TEXT},
            {"role": "user", "content": f"КОНТЕКСТ:\n{context}\n\nЗАПИТАННЯ:\n{query}"}
        ]

        stream = self._model.create_chat_completion(
            messages=messages,
            max_tokens=1024,
            # Температура 0.2 ідеальна для універсальних задач:
            # Вона дозволяє зрозуміти, що "оцінка" = "мурашковий індекс",
            # але не дозволяє вигадувати неіснуючі факти.
            temperature=0.2, 
            stream=True
        )

        for chunk in stream:
            delta = chunk["choices"][0]["delta"]
            if "content" in delta:
                yield delta["content"]
