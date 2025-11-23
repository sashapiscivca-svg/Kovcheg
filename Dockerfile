# Використовуємо легкий Python образ
FROM python:3.11-slim

# Оптимізація Python та шляхи
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SENTENCE_TRANSFORMERS_HOME=/app/models_cache

WORKDIR /app

# 1. Встановлюємо системні бібліотеки для прискорення (OpenBLAS)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-ukr \
    libmagic1 \
    build-essential \
    cmake \
    g++ \
    gcc \
    libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# 2. Встановлюємо залежності з OpenBLAS прискоренням
RUN CMAKE_ARGS="-DLLAMA_BLAS=ON -DLLAMA_OPENBLAS=ON" pip install --upgrade pip && \
    CMAKE_ARGS="-DLLAMA_BLAS=ON -DLLAMA_OPENBLAS=ON" pip install --no-cache-dir -r requirements.txt

# --- МОДЕЛЬ ЗАВАНТАЖУЄТЬСЯ АВТОМАТИЧНО ---
# 3. Копіюємо скрипт завантаження
COPY download_model.py .

# 4. Запускаємо скрипт завантаження моделі (виконується тільки раз під час збірки!)
# Цей крок вимагає, щоб в requirements.txt був huggingface_hub.
RUN python download_model.py

# 5. Копіюємо решту коду проєкту
COPY . .

# 6. Створюємо необхідні папки
RUN mkdir -p /app/data /app/models_cache /app/sources

EXPOSE 8000

CMD ["uvicorn", "web_ui.backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
