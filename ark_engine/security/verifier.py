import base64
import logging
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

from cryptography.exceptions import InvalidSignature
from ark_engine.security.models import SignatureBlock
from ark_engine.security.key_manager import KeyManager
from ark_engine.core.loader import ArkLoader 
from ark_engine.core.utils import calculate_checksum

logger = logging.getLogger("ark_verifier")

class Verifier:
    @staticmethod
    def verify_module(module_path: Path) -> Tuple[bool, Optional[str], bool, Optional[str]]:
        """
        Перевіряє підпис .ark файлу.
        Повертає: (passed: bool, publisher_id: str, is_trusted: bool, error_reason: str)
        """
        try:
            module_data: Dict[str, Any] = ArkLoader.read_raw_data(module_path)
        except Exception as e:
            return False, None, False, f"File read error: {e}"

        sig_block_data = module_data.get('signature_block')
        if not sig_block_data:
            return False, None, False, "Signature block missing"

        try:
            sig_block = SignatureBlock.model_validate(sig_block_data)
        except Exception:
            return False, None, False, "Invalid signature block format"

        publisher_id = sig_block.public_key_id
        
        # 1. Отримання публічного ключа та перевірка довіри
        public_key = KeyManager.load_public_key_object(publisher_id)
        is_trusted = public_key is not None
        
        if not public_key:
            return False, publisher_id, False, "Publisher key not found in trust store."

        # 2. Обчислення хешу контенту ЛОКАЛЬНО
        content_dict = module_data.get('content', {})
        calculated_checksum = calculate_checksum(content_dict)

        # 3. Перевірка цілісності: чи збігаються хеші
        if calculated_checksum != sig_block.checksum_sha256:
            return False, publisher_id, is_trusted, "Checksum mismatch (File content altered)."

        # 4. Перевірка підпису Ed25519
        try:
            signature_bytes = base64.b64decode(sig_block.signature_b64)
            data_to_verify = sig_block.checksum_sha256.encode('utf-8')
            
            public_key.verify(signature_bytes, data_to_verify)
            
            return True, publisher_id, is_trusted, "Signature VALID"
            
        except InvalidSignature:
            return False, publisher_id, is_trusted, "Cryptographic signature INVALID."
        except Exception as e:
            return False, publisher_id, is_trusted, f"Verification error: {e}"
