import os
import json
import logging
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import track

from ark_engine.core.text_loader import MonsterLoader
from ark_engine.core.cleaners import TextCleaner
from ark_engine.core.chunker import TextChunker
from ark_engine.core.embedder import Embedder
from ark_engine.core.indexer import Indexer
from ark_engine.core.utils import generate_uuid, get_current_timestamp, calculate_checksum

console = Console()
logger = logging.getLogger("ark_builder")

class ArkBuilder:
    def __init__(self, input_dir: str, output_file: Optional[str] = None, title: Optional[str] = None):
        self.input_dir = Path(input_dir)
        self.output_file = Path(output_file) if output_file else None
        self.title = title or self.input_dir.name
        self.loader = MonsterLoader(ocr_enabled=True)
        self.cleaner = TextCleaner()
        self.chunker = TextChunker(max_chars=1000)
        self.embedder = None

    def build(self):
        if not self.input_dir.exists() or not self.input_dir.is_dir():
            raise FileNotFoundError(f"Input directory not found: {self.input_dir}")

        files = [f for f in self.input_dir.glob("**/*") if f.is_file()]
        console.print(f"[bold green]Found {len(files)} files in {self.input_dir}[/bold green]")

        all_chunks = []
        chunk_sources = []

        for file_path in track(files, description="Processing files..."):
            raw_text = self.loader.load(file_path)
            if not raw_text:
                continue
            
            clean_text = self.cleaner.normalize(raw_text)
            file_chunks = self.chunker.chunk(clean_text)
            
            all_chunks.extend(file_chunks)
            
            chunk_sources.extend([str(file_path.relative_to(self.input_dir))] * len(file_chunks))

        console.print(f"[bold blue]Generated {len(all_chunks)} text chunks.[/bold blue]")

        if len(all_chunks) == 0:
            console.print("[red]No valid text extracted. Aborting.[/red]")
            return

        self.embedder = Embedder() 
        embeddings = self.embedder.embed(all_chunks)

        search_index = Indexer.build_index(chunk_sources)

        content = {
            "docs": all_chunks,
            "embeddings": embeddings,
            "search_index": search_index,
            "references": chunk_sources
        }

        checksum = calculate_checksum(content)

        ark_data = {
            "header": {
                "id": generate_uuid(),
                "title": self.title,
                "author": os.getenv("USER", "unknown"),
                "created_at": get_current_timestamp(),
                "version": "1.0",
                "checksum": checksum,
                "signature": "",
                "license": "unknown"
            },
            "metadata": {
                "language": "detected", # Placeholder for auto-detect
                "categories": ["auto-generated"],
                "tags": [],
                "locale": "en",
                "intended_use": "general",
                "risk_level": "low"
            },
            "content": content,
            "signature_block": {},
            "update_manifest": {}
        }

        # 8. Output
        if not self.output_file:
            self.output_file = Path(f"{self.title}.ark.json")

        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(ark_data, f, ensure_ascii=False, indent=2)

        console.print(f"[bold green]✓ Build complete: {self.output_file}[/bold green]")
        console.print(f"  ID: {ark_data['header']['id']}")
        console.print(f"  Checksum: {checksum}")
