import typer
from pathlib import Path
from typing import Optional
import sys
import os
import json

# Імпорти існуючих команд
from ark_engine.cli.validate import validate_command
from ark_engine.cli.info import info_command
from ark_engine.cli.search import search_command
from ark_engine.cli.ask import ask_command
from ark_engine.cli.web import web_command
from ark_engine.core.builder import ArkBuilder

# Імпорти нових підгруп (Week 6 & 7)
from ark_engine.cli.store import store_app
from ark_engine.cli.trust import trust_app

# Імпорти безпеки (Week 7)
from ark_engine.security.key_manager import KeyManager
from ark_engine.security.signer import Signer
from ark_engine.security.verifier import Verifier

app = typer.Typer(help="Kovcheg Ark Engine CLI")

# --- Реєстрація підгруп команд ---
app.add_typer(store_app, name="store", help="Package Store commands")
app.add_typer(trust_app, name="trust", help="Trust management and key operations")

# ==========================================
# WEEK 3: Core Commands
# ==========================================

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

# ==========================================
# WEEK 4: Build Command
# ==========================================

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

# ==========================================
# WEEK 5: Web UI Command
# ==========================================

@app.command(name="web")
def web():
    """
    Starts the offline Web UI.
    """
    web_command()

# ==========================================
# WEEK 7: Crypto Commands
# ==========================================

@app.command(name="keygen")
def keygen(name: str = typer.Argument(..., help="Publisher ID (e.g., ark_research_lab)")):
    """Генерує Ed25519 пару ключів та додає публічний ключ у довірений реєстр."""
    try:
        public_pem, private_path = KeyManager.generate_keypair(name)
        KeyManager.add_publisher_to_store(name, public_pem)
        typer.secho(f"✅ Keypair generated for {name}.", fg=typer.colors.GREEN)
        typer.echo(f"Private Key: {private_path}")
        typer.echo("Public key added to trusted_publishers.json.")
    except Exception as e:
        typer.secho(f"Key generation failed: {e}", fg=typer.colors.RED)

@app.command(name="sign")
def sign_file(path: Path = typer.Argument(..., help="Path to .ark file to sign"),
              publisher: str = typer.Option(..., "--publisher", "-p", help="Publisher ID to sign with")):
    """Підписує Ark модуль за допомогою приватного ключа видавця."""
    try:
        # Signer.sign_module оновлює файл на диску
        Signer.sign_module(path, publisher)
        typer.secho(f"✅ File signed successfully by {publisher}.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"Signing failed: {e}", fg=typer.colors.RED)

@app.command(name="verify")
def verify_file(path: Path = typer.Argument(..., help="Path to .ark file to verify")):
    """Перевіряє цифровий підпис файлу Ark."""
    # verify_module повертає кортеж (passed, publisher_id, is_trusted, reason)
    passed, publisher_id, is_trusted, reason = Verifier.verify_module(path)
    
    if passed:
        typer.secho(f"✅ VERIFICATION PASS: Signed by {publisher_id} (Trusted: {is_trusted}).", fg=typer.colors.GREEN)
    else:
        status = "TRUSTED KEY, BUT INVALID SIGNATURE" if is_trusted else "UNTRUSTED / NO KEY"
        typer.secho(f"❌ VERIFICATION FAIL ({status}).", fg=typer.colors.RED)
        typer.echo(f"Reason: {reason}")

if __name__ == "__main__":
    app()
