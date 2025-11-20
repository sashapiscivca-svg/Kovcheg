# Використовуємо легкий Python образ
FROM python:3.11-slim

# Встановлюємо змінні середовища
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SENTENCE_TRANSFORMERS_HOME=/app/models_cache

# Встановлюємо робочу директорію
WORKDIR /app

# Встановлюємо системні залежності
# build-essential, g++, cmake: Необхідні для компіляції llama-cpp-python
# tesseract-ocr: для розпізнавання тексту
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-ukr \
    libmagic1 \
    build-essential \
    cmake \
    g++ \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо файл залежностей
COPY requirements.txt .

# Оновлюємо pip і встановлюємо залежності
# CMAKE_ARGS="-DLLAMA_BLAS=ON -DLLAMA_OPENBLAS=ON" можна додати для оптимізації, 
# але для простого CPU старту достатньо звичайного install
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копіюємо код проєкту
COPY . .

# Створюємо необхідні папки
RUN mkdir -p /app/data /app/models_cache /app/sources

# Відкриваємо порт для API
EXPOSE 8000

# Запускаємо сервер
CMD ["uvicorn", "web_ui.backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
