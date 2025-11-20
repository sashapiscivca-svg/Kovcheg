import typer
from pathlib import Path
from typing import Optional
import sys
import os

from ark_engine.cli.validate import validate_command
from ark_engine.cli.info import info_command
from ark_engine.cli.search import search_command
from ark_engine.cli.ask import ask_command
from ark_engine.cli.web import web_command
from ark_engine.core.builder import ArkBuilder
from ark_engine.cli.store import store_app

app = typer.Typer(help="Kovcheg Ark Engine CLI")

app.add_typer(store_app, name="store", help="Package Store commands")

# --- WEEK 3 COMMANDS ---

@app.command(name="validate")
def validate(path: Path = typer.Argument(..., help="Path to .ark file")):
    validate_command(path)

@app.command(name="info")
def info(path: Path = typer.Argument(..., help="Path to .ark file")):
    info_command(path)

@app.command(name="search")
def search(
    query: str = typer.Argument(...),
    module: Path = typer.Option(..., "--module", "-m", help="Path to .ark file")
):
    search_command(query, module)

@app.command(name="ask")
def ask(
    question: str = typer.Argument(...),
    module: Path = typer.Option(..., "--module", "-m", help="Path to .ark file")
):
    ask_command(question, module)

# --- WEEK 4 COMMAND ---

@app.command(name="build")
def build(
    input_folder: Path = typer.Argument(..., help="Directory containing raw files"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output .ark.json file path"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="Title for the Ark module")
):
    """
    Convert raw documents into a .ark module.
    """
    try:
        builder = ArkBuilder(
            input_dir=str(input_folder), 
            output_file=str(output) if output else None, 
            title=title
        )
        builder.build()
    except Exception as e:
        typer.secho(f"Error during build: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

# --- WEEK 5 COMMAND ---

@app.command(name="web")
def web():
    """
    Starts the offline Web UI.
    """
    web_command()

if __name__ == "__main__":
    app()
