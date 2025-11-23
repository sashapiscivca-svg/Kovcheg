from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from pathlib import Path
from typing import Tuple, Optional
import logging

# ОНОВЛЕНИЙ ІМПОРТ: Publisher беремо з models, решту з trust_store
from ark_engine.security.models import Publisher 
from ark_engine.security.trust_store import TrustStore, get_keys_dir

logger = logging.getLogger("ark_key_manager")

class KeyManager:
    # ... (решта коду без змін)
    @staticmethod
    def generate_keypair(publisher_id: str) -> Tuple[str, Path]:
        # ... (код без змін)
        private_key = ed25519.Ed25519PrivateKey.generate()
        # ...
        # (і так далі, весь код всередині методів залишається тим самим)
        # Тільки переконайтеся, що imports зверху правильні.
        # Нижче повний код методу generate_keypair для впевненості:
        
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        keys_dir = get_keys_dir() / publisher_id
        keys_dir.mkdir(exist_ok=True)

        # 1. Приватний ключ
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        private_key_path = keys_dir / "private_key.pem"
        private_key_path.write_bytes(private_pem)

        # 2. Публічний ключ
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        public_key_path = keys_dir / "public_key.pem"
        public_key_path.write_bytes(public_pem)
        
        return public_pem.decode('utf-8'), public_key_path

    @staticmethod
    def add_publisher_to_store(publisher_id: str, public_key_pem: str):
        """Додає новий публічний ключ до довіреного реєстру."""
        store = TrustStore()
        
        publisher_data = Publisher(
            id=publisher_id,
            display_name=publisher_id,
            public_key_path=f"keys/{publisher_id}/public_key.pem",
            public_key_pem=public_key_pem,
            trusted=True
        )
        
        store.add_publisher(publisher_data)

    # ... (решта методів get_private_key, get_public_key_pem, load_public_key_object залишаються без змін)
    @staticmethod
    def get_private_key(publisher_id: str) -> Optional[ed25519.Ed25519PrivateKey]:
        keys_dir = get_keys_dir() / publisher_id
        private_key_path = keys_dir / "private_key.pem"
        if not private_key_path.exists(): return None
        return serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)

    @staticmethod
    def get_public_key_pem(publisher_id: str) -> Optional[str]:
        store = TrustStore()
        publisher = store.get_publisher(publisher_id)
        if publisher and publisher.public_key_pem: return publisher.public_key_pem
        keys_dir = get_keys_dir() / publisher_id
        public_key_path = keys_dir / "public_key.pem"
        if public_key_path.exists(): return public_key_path.read_text().strip()
        return None

    @staticmethod
    def load_public_key_object(publisher_id: str) -> Optional[ed25519.Ed25519PublicKey]:
        public_pem = KeyManager.get_public_key_pem(publisher_id)
        if not public_pem: return None
        try:
            return serialization.load_pem_public_key(public_pem.encode())
        except Exception as e:
            logger.error(f"Error loading public key: {e}")
            return None
