import os
import json
import logging
import shutil
from pathlib import Path
from typing import Optional, List

import pandas as pd
import lancedb
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
        
        # Компоненти пайплайну
        self.loader = MonsterLoader(ocr_enabled=True)
        self.cleaner = TextCleaner()
        self.chunker = TextChunker(max_chars=1000)
        self.embedder = None

    def build(self):
        """
        Основний метод збірки .ark модуля з використанням LanceDB для векторів.
        """
        if not self.input_dir.exists() or not self.input_dir.is_dir():
            raise FileNotFoundError(f"Input directory not found: {self.input_dir}")

        # 1. Сканування файлів
        files = [f for f in self.input_dir.glob("**/*") if f.is_file()]
        console.print(f"[bold green]Found {len(files)} files in {self.input_dir}[/bold green]")

        all_chunks: List[str] = []
        chunk_sources: List[str] = []

        # 2. Обробка тексту (ETL)
        for file_path in track(files, description="Processing documents..."):
            raw_text = self.loader.load(file_path)
            if not raw_text:
                continue
            
            clean_text = self.cleaner.normalize(raw_text)
            file_chunks = self.chunker.chunk(clean_text)
            
            if not file_chunks:
                continue

            all_chunks.extend(file_chunks)
            # Зберігаємо відносний шлях як джерело
            relative_source = str(file_path.relative_to(self.input_dir))
            chunk_sources.extend([relative_source] * len(file_chunks))

        console.print(f"[bold blue]Generated {len(all_chunks)} text chunks.[/bold blue]")

        if len(all_chunks) == 0:
            console.print("[red]No valid text extracted. Aborting build.[/red]")
            return

        # 3. Генерація Ембеддінгів
        self.embedder = Embedder() 
        console.print("[yellow]Generating embeddings (this may take a while)...[/yellow]")
        embeddings = self.embedder.embed(all_chunks)

        # 4. Підготовка ідентифікаторів та шляхів
        module_id = generate_uuid()
        
        # Визначаємо вихідний шлях
        if not self.output_file:
            self.output_file = Path(f"{self.title}.ark.json")
        
        # Шлях до LanceDB (папка поруч з .ark файлом)
        lancedb_dir = self.output_file.parent / f"{module_id}.lancedb"
        
        if lancedb_dir.exists():
            shutil.rmtree(lancedb_dir)
        lancedb_dir.mkdir(parents=True, exist_ok=True)

        # 5. Запис у LanceDB (Vector Index)
        console.print(f"[yellow]Creating LanceDB index at: {lancedb_dir}[/yellow]")
        
        try:
            df = pd.DataFrame({
                "vector": embeddings,
                "text": all_chunks,
                "source": chunk_sources,
                "id": range(len(all_chunks))
            })
            
            db = lancedb.connect(str(lancedb_dir))
            db.create_table("vectors", data=df)
            
            console.print("[green]Vectors successfully indexed in LanceDB.[/green]")
        except Exception as e:
            console.print(f"[bold red]Failed to create LanceDB index: {e}[/bold red]")
            raise e

        # 6. Формування Payload (Content)
        search_index = Indexer.build_index(chunk_sources)
        
        content = {
            "docs": all_chunks,
            "vector_index_uri": str(lancedb_dir.absolute()),
            "search_index": search_index,
            "references": chunk_sources,
            "media": []
        }

        checksum = calculate_checksum(content)

        ark_data = {
            "header": {
                "id": module_id,
                "title": self.title,
                "author": os.getenv("USER", "unknown"), # Це поле тепер є в моделі!
                "created_at": get_current_timestamp(),
                "version": "1.0",
                "checksum": checksum,
                "signature": None, # <--- ТУТ ЗМІНЕНО: None (null) замість ""
                "license": "unknown"
            },
            "metadata": {
                "language": "detected",
                "categories": ["auto-generated"],
                "tags": [],
                "locale": "en",
                "intended_use": "general",
                "risk_level": "low",
                "data_provenance": {
                    "author": os.getenv("USER", "local_user"),
                    "acquisition_method": "manual"
                }
            },
            "content": content,
            "signature_block": {},
            "update_manifest": {}
        }

        # 8. Запис фінального файлу .ark.json
        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(ark_data, f, ensure_ascii=False, indent=2)

        console.print(f"[bold green]✓ Build complete: {self.output_file}[/bold green]")
        console.print(f"  ID: {module_id}")
        console.print(f"  Vector DB: {lancedb_dir.name}")
        console.print(f"  Checksum: {checksum}")
