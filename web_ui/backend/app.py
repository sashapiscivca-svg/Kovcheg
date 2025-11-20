import os
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path

from web_ui.backend.modules_router import router as modules_router
from web_ui.backend.rag_router import router as rag_router
from web_ui.backend.settings import settings

# --- Application Setup ---

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kovcheg_ui")

app = FastAPI(
    title="Kovcheg Web UI Backend",
    description="Offline RAG API for .ark modules.",
    version="0.1.0",
    docs_url=None, 
    redoc_url=None
)

# --- Router Registration ---
app.include_router(modules_router, prefix="/api/v1")
app.include_router(rag_router, prefix="/api/v1")

# --- Static Files Configuration ---

# Визначаємо АБСОЛЮТНИЙ шлях до папки frontend всередині контейнера.
# Це /app/web_ui/frontend
APP_ROOT_CONTAINER = Path("/app")
FRONTEND_DIR_ABS = APP_ROOT_CONTAINER / "web_ui" / "frontend"

# --- Root Endpoint (HTML Serving) ---

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """
    Подає головний HTML-файл для UI.
    """
    index_path = FRONTEND_DIR_ABS / "index.html"
    
    # 1. Перевірка існування файлу
    if not index_path.exists():
        logger.error(f"❌ index.html NOT found at: {index_path}")
        return f"""
        <html>
            <body style="font-family: sans-serif; padding: 2rem;">
                <h1 style="color: red;">404 Error: Frontend Not Found</h1>
                <p>Path checked: <b>{index_path}</b></p>
                <p>Action: Rebuild Docker to ensure files were copied to this location.</p>
            </body>
        </html>
        """, 404
        
    # 2. Якщо файл існує, подаємо його
    return index_path.read_text()

# --- Static Files Mounting ---
# Монтуємо статику тільки якщо папка існує, щоб уникнути помилок Uvicorn
if FRONTEND_DIR_ABS.exists():
    logger.info(f"✅ Frontend directory found. Mounting static files from: {FRONTEND_DIR_ABS}")
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR_ABS), name="static")
else:
    logger.warning(f"❌ Cannot mount /static. Directory does not exist: {FRONTEND_DIR_ABS}")

# Примітка: Логіка перевірки index.html та монтажу статичних файлів
# тепер використовує одну й ту саму змінну `FRONTEND_DIR_ABS`, що усуває конфлікти.
