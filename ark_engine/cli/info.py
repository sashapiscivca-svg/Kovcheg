import typer
from pathlib import Path
from ark_engine.core.loader import ArkLoader

def info_command(path: Path):
    """Show metadata about an .ark file."""
    try:
        module = ArkLoader.load(path)
        h = module.header
        m = module.metadata
        
        typer.secho(f"=== {h.title} ===", fg=typer.colors.BLUE, bold=True)
        typer.echo(f"Author: {h.author}")
        typer.echo(f"Created: {h.created_at}")
        typer.echo(f"License: {h.license}")
        typer.echo(f"Checksum: {h.checksum[:8]}...")
        typer.echo("\n[Metadata]")
        typer.echo(f"Language: {m.language}")
        typer.echo(f"Risk Level: {m.risk_level}")
        typer.echo(f"Tags: {', '.join(m.tags)}")
        typer.echo(f"\n[Content]")
        typer.echo(f"Documents: {len(module.content.docs)}")
        typer.echo(f"Embeddings: {len(module.content.embeddings)}")
        
    except Exception as e:
        typer.secho(f"Error reading module: {e}", fg=typer.colors.RED)
