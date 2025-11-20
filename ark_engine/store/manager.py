import shutil
import logging
from pathlib import Path
from typing import List, Optional

from ark_engine.store.index import IndexManager
from ark_engine.store.installer import Installer
from ark_engine.store.models import IndexEntry, PackageMeta
from ark_engine.store.utils import get_store_root

logger = logging.getLogger("ark_store_manager")

class ArkStoreManager:
    def __init__(self):
        self.index = IndexManager()
        self.installer = Installer(self.index)
        self.root = get_store_root()

    def install(self, source: str):
        """Вхідна точка для встановлення (шлях або URL)."""
        path = Path(source)
        if path.exists():
             # Локальний файл
             return self.installer.install_local(path)
        elif source.startswith("http"):
            # TODO: Week 7 - Network Fetcher
            raise NotImplementedError("Remote installation not implemented yet. Use local file.")
        else:
            raise FileNotFoundError(f"File not found: {source}")

    def list(self) -> List[IndexEntry]:
        return self.index.list_packages()

    def get_info(self, package_id: str) -> dict:
        """Повертає повну інформацію з meta.json."""
        entry = self.index.get_package(package_id)
        if not entry:
            raise KeyError(f"Package {package_id} not found")
        
        # Шукаємо meta.json поруч із файлом
        ark_path = Path(entry.path)
        meta_path = ark_path.parent / "meta.json"
        
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            # Fallback до даних з індексу
            return entry.model_dump()

    def remove(self, package_id: str):
        entry = self.index.get_package(package_id)
        if not entry:
            raise KeyError(f"Package {package_id} not installed")

        # Видаляємо папку пакету
        package_dir = Path(entry.path).parent
        if package_dir.exists() and package_dir.parent == (self.root / "packages"):
            shutil.rmtree(package_dir)
            logger.info(f"Removed directory: {package_dir}")

        # Видаляємо з індексу
        self.index.remove_package(package_id)

    def doctor(self):
        """Відновлює цілісність магазину."""
        print("Running Ark Store Doctor...")
        fixed_count = 0
        
        # 1. Перевірка записів в індексі
        valid_packages = []
        for pkg in self.index.index_data.packages:
            if Path(pkg.path).exists():
                valid_packages.append(pkg)
            else:
                print(f"❌ Orphaned index entry removed: {pkg.id}")
                fixed_count += 1
        
        self.index.index_data.packages = valid_packages
        self.index.save()

        # 2. Сканування папок на наявність "нічиїх" пакетів
        # (Можна реалізувати зворотній імпорт - add to index if exists on disk)
        # Для MVP просто чистимо індекс.
        
        print(f"Doctor finished. Fixed {fixed_count} issues.")
