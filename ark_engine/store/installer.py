import shutil
import json
import logging
from pathlib import Path
from datetime import datetime

# Core imports
from ark_engine.core.loader import ArkLoader
from ark_engine.core.models import ArkModule

# Store imports
from ark_engine.store.models import IndexEntry, PackageMeta
from ark_engine.store.utils import get_store_root, calculate_file_hash, get_file_size

# Security imports (Week 7)
from ark_engine.security.verifier import Verifier

logger = logging.getLogger("ark_installer")

class Installer:
    def __init__(self, index_manager):
        self.store_root = get_store_root()
        self.packages_dir = self.store_root / "packages"
        self.index = index_manager

    def install_local(self, source_path: Path, allow_untrusted: bool = False) -> IndexEntry:
        """Встановлює .ark файл з локального шляху з перевіркою підпису."""
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        # --- КРОК 1: ПЕРЕВІРКА ПІДПИСУ ---
        passed, publisher_id, is_trusted, reason = Verifier.verify_module(source_path)
        
        # Логіка блокування ненадійних модулів
        if not passed and not allow_untrusted:
            if is_trusted:
                # Ключ є, але підпис невірний (пошкодження файлу)
                raise PermissionError(f"Verification FAILED: Signature invalid. Reason: {reason}")
            else:
                # Ключа немає або модуль не підписаний
                raise PermissionError(f"Verification FAILED: Module is unsigned or publisher ({publisher_id}) is not trusted. Use --allow-untrusted to bypass.")
        
        if not passed and allow_untrusted:
            logger.warning(f"SECURITY WARNING: Installing untrusted module {source_path} (Reason: {reason})")

        # --- КРОК 2: ВАЛІДАЦІЯ ---
        logger.info(f"Validating {source_path}...")
        try:
            module: ArkModule = ArkLoader.load(source_path)
        except Exception as e:
            raise ValueError(f"Invalid .ark file: {e}")

        module_id = str(module.header.id)
        
        # --- КРОК 3: ПІДГОТОВКА ДИРЕКТОРІЇ ---
        target_dir = self.packages_dir / module_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "module.ark"
        meta_file = target_dir / "meta.json"

        # --- КРОК 4: КОПІЮВАННЯ ---
        logger.info(f"Installing to {target_dir}...")
        shutil.copy2(source_path, target_file)

        # --- КРОК 5: МЕТАДАНІ ---
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

        # --- КРОК 6: ОНОВЛЕННЯ ІНДЕКСУ ---
        entry = IndexEntry(
            id=module_id,
            version=module.header.version,
            title=module.header.title,
            installed_at=datetime.now(),
            path=str(target_file.absolute()),
            signature_ok=passed,
            # Використовуємо publisher_id, якщо він є, інакше "unsigned"
            publisher_id=publisher_id if publisher_id else "unsigned",
            trusted=is_trusted
        )
        
        self.index.add_package(entry)
        logger.info(f"Package {module_id} installed successfully.")
        
        return entry
