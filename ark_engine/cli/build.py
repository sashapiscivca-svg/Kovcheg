import typer
from pathlib import Path
from typing import Optional
from ark_engine.core.builder import ArkBuilder

app = typer.Typer()

@app.command()
def main(
    input_folder: Path = typer.Argument(..., help="Directory containing raw files"),
    output: Optional[Path] = typer.Option(None, help="Output .ark.json file path"),
    title: Optional[str] = typer.Option(None, help="Title for the Ark module")
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

if __name__ == "__main__":
    app()
