import json
import logging
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from ark_engine.store.models import StoreIndex, IndexEntry
from ark_engine.store.utils import get_store_root

logger = logging.getLogger("ark_store_index")

class IndexManager:
    def __init__(self):
        self.root = get_store_root()
        self.index_path = self.root / "index.json"
        self.index_data = self._load_index()

    def _load_index(self) -> StoreIndex:
        if not self.index_path.exists():
            return StoreIndex()
        
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return StoreIndex(**data)
        except Exception as e:
            logger.error(f"Corrupted index file: {e}. Creating new.")
            return StoreIndex()

    def save(self):
        self.index_data.updated_at = datetime.now()
        with open(self.index_path, "w", encoding="utf-8") as f:
            # model_dump_json для Pydantic v2
            f.write(self.index_data.model_dump_json(indent=2))

    def add_package(self, entry: IndexEntry):
        # Видаляємо стару версію, якщо існує
        self.remove_package(entry.id)
        self.index_data.packages.append(entry)
        self.save()

    def remove_package(self, package_id: str) -> bool:
        initial_count = len(self.index_data.packages)
        self.index_data.packages = [p for p in self.index_data.packages if p.id != package_id]
        if len(self.index_data.packages) < initial_count:
            self.save()
            return True
        return False

    def get_package(self, package_id: str) -> Optional[IndexEntry]:
        for p in self.index_data.packages:
            if p.id == package_id:
                return p
        return None

    def list_packages(self) -> List[IndexEntry]:
        return self.index_data.packages
