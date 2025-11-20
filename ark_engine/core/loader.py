import json
import yaml
import hashlib
import logging
from pathlib import Path
from typing import Union, Dict

from ark_engine.core.models import ArkModule

logger = logging.getLogger(__name__)

class ArkLoader:
    @staticmethod
    def _calculate_checksum(content_dict: Dict) -> str:
        """
        Calculates SHA256 of the content block.
        Uses sorted keys to ensure JSON canonicalization for hashing.
        """
        dumped = json.dumps(content_dict, sort_keys=True).encode("utf-8")
        return hashlib.sha256(dumped).hexdigest()

    @classmethod
    def load(cls, file_path: Union[str, Path]) -> ArkModule:
        """
        Loads a .ark file, validates schema via Pydantic, 
        and verifies the SHA256 checksum of the content.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Ark module not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            if path.suffix in ['.yaml', '.yml']:
                data = yaml.safe_load(f)
            else:
                data = json.load(f)

        try:
            module = ArkModule(**data)
        except Exception as e:
            raise ValueError(f"Schema Validation Failed: {e}")

        calculated_hash = cls._calculate_checksum(data.get("content", {}))
        
        if module.header.checksum != calculated_hash:
            logger.warning(
                f"Checksum mismatch! Header: {module.header.checksum}, "
                f"Calculated: {calculated_hash}"
            )
           
        return module
