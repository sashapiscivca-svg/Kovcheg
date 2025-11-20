import typer
from pathlib import Path
from ark_engine.core.loader import ArkLoader
from ark_engine.core.rag import ArkRAG

def ask_command(question: str, module_path: Path):
    """Ask a question to the .ark module (RAG + LLM Stub)."""
    try:
        module = ArkLoader.load(module_path)
        rag = ArkRAG(module)
        
        response = rag.ask(question)
        
        typer.secho("\n=== Ark Engine Response ===", fg=typer.colors.CYAN)
        typer.echo(response)
        
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED)
