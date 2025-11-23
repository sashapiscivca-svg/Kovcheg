import os
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pathlib import Path

from web_ui.backend.modules_router import router as modules_router
from web_ui.backend.rag_router import router as rag_router
from web_ui.backend.settings import settings
from web_ui.backend.chat_router import router as chat_router

# --- Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kovcheg_app")

app = FastAPI(
    title="Kovcheg UI Backend",
    version="0.1.0",
    docs_url="/docs" # Swagger документація буде доступна
)

# --- CORS (Критично для веб-розробки) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Дозволити всі джерела (для локальної роботи безпечно)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ---
app.include_router(modules_router, prefix="/api/v1")
app.include_router(rag_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")

# --- Static Files Logic ---
# Визначаємо шлях до frontend папки (всередині контейнера це /app/web_ui/frontend)
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

if not FRONTEND_DIR.exists():
    # Fallback для Docker шляхів, якщо запускаємо не з кореня
    FRONTEND_DIR = Path("/app/web_ui/frontend")

# Монтуємо статику (CSS, JS, Images)
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
    logger.info(f"✅ Static files mounted from {FRONTEND_DIR}")
else:
    logger.error(f"❌ Frontend directory not found at {FRONTEND_DIR}")

# --- Root Endpoint ---
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Віддає головну сторінку SPA (Single Page Application)"""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return """
    <html>
        <body>
            <h1>Kovcheg Backend Running</h1>
            <p>UI not found. Check Docker mapping.</p>
        </body>
    </html>
    """
