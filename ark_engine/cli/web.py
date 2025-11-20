import typer
import uvicorn
import webbrowser
from rich.console import Console
from pathlib import Path
import os
import sys # <--- НОВИЙ ІМПОРТ
import logging # <--- Додано для логування, хоча не викликається, але корисно

# Встановлюємо шлях до бекенду, щоб uvicorn міг знайти app.py
# Цей рядок тепер коректно використовує sys.path:
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Імпортуємо налаштування для отримання хосту/порту
from web_ui.backend.settings import settings

console = Console()

def web_command():
    """
    Запускає локальний веб-інтерфейс (FastAPI + UI) і відкриває його в браузері.
    """
    host = settings.API_HOST
    port = settings.API_PORT
    url = f"http://{host}:{port}"
    
    console.print(f"[bold green]🚀 Starting Kovcheg Web UI...[/bold green]")
    console.print(f"[yellow]  URL:[/yellow] {url}")
    console.print(f"[yellow]  Modules Path:[/yellow] {Path(settings.ARK_MODULES_PATH).resolve()}")
    console.print("[dim]  (This server runs entirely offline)[/dim]")

    # Відкриваємо браузер
    webbrowser.open(url)

    # Запускаємо Uvicorn. Використовуємо web_ui.backend.app як точку входу
    uvicorn.run(
        "web_ui.backend.app:app", 
        host=host, 
        port=port, 
        reload=False, 
        log_level="info"
    )

if __name__ == "__main__":
    typer.run(web_command)
