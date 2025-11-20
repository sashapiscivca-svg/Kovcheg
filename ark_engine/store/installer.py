import shutil
import json
import logging
from pathlib import Path
from datetime import datetime

# Імпорти з попередніх тижнів
from ark_engine.core.loader import ArkLoader
from ark_engine.core.models import ArkModule

from ark_engine.store.models import IndexEntry, PackageMeta
from ark_engine.store.utils import get_store_root, calculate_file_hash, get_file_size

logger = logging.getLogger("ark_installer")

class Installer:
    def __init__(self, index_manager):
        self.store_root = get_store_root()
        self.packages_dir = self.store_root / "packages"
        self.index = index_manager

    def install_local(self, source_path: Path) -> IndexEntry:
        """Встановлює .ark файл з локального шляху."""
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        # 1. Валідація та читання метаданих через Core Loader
        logger.info(f"Validating {source_path}...")
        try:
            # ArkLoader перевіряє схему та чексуму (Week 3)
            module: ArkModule = ArkLoader.load(source_path)
        except Exception as e:
            raise ValueError(f"Invalid .ark file: {e}")

        module_id = str(module.header.id)
        
        # 2. Підготовка цільової директорії
        target_dir = self.packages_dir / module_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "module.ark"
        meta_file = target_dir / "meta.json"

        # 3. Копіювання файлу
        logger.info(f"Installing to {target_dir}...")
        shutil.copy2(source_path, target_file)

        # 4. Генерація та збереження розширених метаданих (meta.json)
        # Обчислюємо хеш всього файлу (для цілісності магазину)
        file_hash = calculate_file_hash(target_file)
        
        meta = PackageMeta(
            id=module_id,
            title=module.header.title,
            version=module.header.version,
            author=module.header.author,
            created_at=module.header.created_at,
            doc_count=len(module.content.docs),
            embedding_count=len(module.content.embeddings),
            total_size_bytes=get_file_size(target_file),
            checksum=file_hash
        )

        with open(meta_file, "w", encoding="utf-8") as f:
            f.write(meta.model_dump_json(indent=2))

        # 5. Оновлення індексу
        entry = IndexEntry(
            id=module_id,
            version=module.header.version,
            title=module.header.title,
            installed_at=datetime.now(),
            path=str(target_file.absolute()),
            signature_ok=True # Припускаємо OK, бо ArkLoader пройшов
        )
        
        self.index.add_package(entry)
        logger.info(f"Package {module_id} installed successfully.")
        
        return entry
