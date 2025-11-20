import typer
from rich.console import Console
from rich.table import Table
from pathlib import Path
from typing import Optional

from ark_engine.security.trust_store import TrustStore, Publisher
from ark_engine.security.key_manager import KeyManager

trust_app = typer.Typer(help="Manage trusted publishers and keys.")
console = Console()
store = TrustStore()

@trust_app.command("add")
def add_publisher(
    public_key_file: Path = typer.Argument(..., help="Path to public_key.pem file"),
    id: str = typer.Option(..., "--id", help="Unique ID for the publisher"),
    name: str = typer.Option(..., "--name", help="Display name for the publisher")
):
    """Додає публічний ключ до реєстру довіри."""
    if not public_key_file.exists():
        console.print(f"[red]Error:[/red] Public key file not found at {public_key_file}")
        raise typer.Exit(1)
        
    public_key_pem = public_key_file.read_text().strip()
    
    publisher = Publisher(
        id=id,
        display_name=name,
        public_key_path=public_key_file.as_posix(),
        public_key_pem=public_key_pem,
        trusted=True
    )
    store.add_publisher(publisher)
    console.print(f"[green]Publisher '{name}' added successfully and marked as trusted.[/green]")

@trust_app.command("remove")
def remove_publisher(id: str = typer.Argument(..., help="Publisher ID to remove.")):
    """Видаляє видавця з реєстру довіри."""
    if store.remove_publisher(id):
        console.print(f"[green]Publisher {id} removed.[/green]")
    else:
        console.print(f"[yellow]Publisher {id} not found.[/yellow]")

@trust_app.command("list")
def list_publishers():
    """Показує список довірених видавців."""
    publishers = store.list_publishers()
    if not publishers:
        console.print("No publishers in the trust store.")
        return
        
    table = Table(title="Trusted Ark Publishers")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="magenta")
    table.add_column("Trusted", style="green")
    table.add_column("Key Path")

    for p in publishers:
        table.add_row(
            p.id, 
            p.display_name, 
            "✅ Yes" if p.trusted else "❌ No", 
            p.public_key_path
        )
    console.print(table)
