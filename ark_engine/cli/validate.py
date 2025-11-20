import typer
from pathlib import Path
from ark_engine.core.loader import ArkLoader

app = typer.Typer()

def validate_command(path: Path):
    """Validate schema and checksum of an .ark file."""
    try:
        module = ArkLoader.load(path)
        typer.secho(f"✅ SUCCESS: '{module.header.title}' is valid.", fg=typer.colors.GREEN)
        typer.echo(f"ID: {module.header.id}")
        typer.echo(f"Version: {module.header.version}")
    except Exception as e:
        typer.secho(f"❌ INVALID: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
