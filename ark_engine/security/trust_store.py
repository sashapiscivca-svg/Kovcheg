import json
import logging
from pathlib import Path
from typing import Optional, List

# Імпортуємо моделі з створеного файлу models.py
from ark_engine.security.models import TrustedPublishers, Publisher

logger = logging.getLogger("ark_trust_store")

def get_security_root() -> Path:
    """Повертає шлях ~/.kovcheg/security."""
    security_path = Path.home() / ".kovcheg" / "security"
    security_path.mkdir(parents=True, exist_ok=True)
    return security_path

def get_keys_dir() -> Path:
    """Повертає шлях ~/.kovcheg/security/keys."""
    keys_dir = get_security_root() / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    return keys_dir

def get_trust_file_path() -> Path:
    """Повертає шлях до trusted_publishers.json."""
    return get_security_root() / "trusted_publishers.json"

class TrustStore:
    def __init__(self):
        self._path = get_trust_file_path()
        self._data: TrustedPublishers = self._load()

    def _load(self) -> TrustedPublishers:
        if not self._path.exists():
            return TrustedPublishers()
        try:
            return TrustedPublishers.model_validate_json(self._path.read_text())
        except Exception as e:
            logger.error(f"Corrupted trust store: {e}. Starting fresh.")
            return TrustedPublishers()

    def save(self):
        self._path.write_text(self._data.model_dump_json(indent=2))

    def add_publisher(self, publisher: Publisher):
        # Видаляємо старий запис з таким самим ID, якщо є
        self._data.publishers = [p for p in self._data.publishers if p.id != publisher.id]
        self._data.publishers.append(publisher)
        self.save()

    def remove_publisher(self, publisher_id: str) -> bool:
        initial_count = len(self._data.publishers)
        self._data.publishers = [p for p in self._data.publishers if p.id != publisher_id]
        if len(self._data.publishers) < initial_count:
            self.save()
            return True
        return False

    def get_publisher(self, publisher_id: str) -> Optional[Publisher]:
        return next((p for p in self._data.publishers if p.id == publisher_id), None)

    def list_publishers(self) -> List[Publisher]:
        return self._data.publishers
