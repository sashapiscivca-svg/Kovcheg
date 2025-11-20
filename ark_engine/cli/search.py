import typer
from pathlib import Path
from ark_engine.core.loader import ArkLoader
from ark_engine.core.rag import ArkRAG

def search_command(query: str, module_path: Path):
    """Semantic search inside an .ark module."""
    try:
        module = ArkLoader.load(module_path)
        rag = ArkRAG(module)
        
        results = rag.search(query)
        
        typer.secho(f"Search results for: '{query}'", fg=typer.colors.YELLOW)
        for i, (doc, score) in enumerate(results, 1):
            typer.echo(f"\n{i}. [Score: {score:.4f}]")
            typer.echo(f"   {doc[:200]}...")
            
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED)
