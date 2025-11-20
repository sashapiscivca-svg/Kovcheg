FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SENTENCE_TRANSFORMERS_HOME=/app/models_cache

WORKDIR /app

RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-ukr \
    libmagic1 \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/models_cache

EXPOSE 8000

CMD ["uvicorn", "ark_engine.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
