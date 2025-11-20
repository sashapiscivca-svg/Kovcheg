import json
import base64
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

from ark_engine.security.key_manager import KeyManager
from ark_engine.security.models import SignatureBlock
from ark_engine.core.loader import ArkLoader  # Потрібен для read_raw_data та оновлення
from ark_engine.core.utils import calculate_checksum # Потрібен для хешування

logger = logging.getLogger("ark_signer")

class Signer:
    @staticmethod
    def sign_module(module_path: Path, publisher_id: str) -> Path:
        """
        Підписує .ark файл, використовуючи Ed25519. Перезаписує оригінальний файл.
        """
        raw_data: Dict[str, Any] = ArkLoader.read_raw_data(module_path)
        private_key = KeyManager.get_private_key(publisher_id)
        
        if not private_key:
            raise PermissionError(f"Private key for {publisher_id} not found in keys directory.")

        # 1. Канонічний хеш вмісту (Content)
        content_dict = raw_data.get('content', {})
        content_checksum = calculate_checksum(content_dict)
        
        # 2. Дані для підпису: хеш контенту (string -> bytes)
        data_to_sign = content_checksum.encode('utf-8')
        
        # 3. Підпис Ed25519
        signature_bytes = private_key.sign(data_to_sign)
        signature_base64 = base64.b64encode(signature_bytes).decode('utf-8')

        # 4. Створення блоку підпису
        signature_block = SignatureBlock(
            public_key_id=publisher_id,
            checksum_sha256=content_checksum,
            signature_b64=signature_base64,
            signed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        )

        # 5. Оновлення ArkModule та перезапис файлу
        module_data = raw_data
        module_data['signature_block'] = signature_block.model_dump()
        module_data['header']['checksum'] = content_checksum # Оновлюємо заголовок
        
        with open(module_path, 'w', encoding='utf-8') as f:
            json.dump(module_data, f, indent=2)

        return module_path
