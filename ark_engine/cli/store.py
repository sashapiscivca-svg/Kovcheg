import typer
from rich.console import Console
from rich.table import Table
from typing import Optional

from ark_engine.store.manager import ArkStoreManager

store_app = typer.Typer(help="Manage Ark packages (install, list, remove)")
console = Console()
manager = ArkStoreManager()

@store_app.command("install")
def install(path: str = typer.Argument(..., help="Path to local .ark file")):
    """Install a package into the local store."""
    try:
        console.print(f"[yellow]Installing from {path}...[/yellow]")
        entry = manager.install(path)
        console.print(f"[bold green]Successfully installed:[/bold green] {entry.title} (v{entry.version})")
        console.print(f"ID: {entry.id}")
    except Exception as e:
        console.print(f"[bold red]Installation failed:[/bold red] {e}")
        raise typer.Exit(1)

@store_app.command("list")
def list_packages():
    """List all installed packages."""
    packages = manager.list()
    
    if not packages:
        console.print("No packages installed.")
        return

    table = Table(title="Installed Ark Modules")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Version", style="magenta")
    table.add_column("Title", style="green")
    table.add_column("Installed At")

    for p in packages:
        table.add_row(
            p.id, 
            p.version, 
            p.title, 
            p.installed_at.strftime("%Y-%m-%d %H:%M")
        )

    console.print(table)

@store_app.command("info")
def info(package_id: str):
    """Show details about a specific package."""
    try:
        data = manager.get_info(package_id)
        console.print(f"[bold]Package Info: {package_id}[/bold]")
        console.print_json(data=data)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")

@store_app.command("remove")
def remove(package_id: str):
    """Uninstall a package."""
    try:
        manager.remove(package_id)
        console.print(f"[green]Package {package_id} removed.[/green]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")

@store_app.command("doctor")
def doctor():
    """Repair the package store index."""
    manager.doctor()
