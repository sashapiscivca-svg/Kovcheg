import hashlib
import os
from pathlib import Path

def get_store_root() -> Path:
    """Повертає шлях до кореневої папки сховища (~/.kovcheg/ark_store)."""
    home = Path.home()
    store_path = home / ".kovcheg" / "ark_store"
    store_path.mkdir(parents=True, exist_ok=True)
    
    (store_path / "packages").mkdir(exist_ok=True)
    return store_path

def calculate_file_hash(file_path: Path) -> str:
    """Обчислює SHA256 хеш файлу."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Читаємо блоками по 4K для ефективності пам'яті
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def get_file_size(file_path: Path) -> int:
    return os.path.getsize(file_path)
