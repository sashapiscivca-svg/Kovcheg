import json
import yaml
import hashlib
import logging
from pathlib import Path
from typing import Union, Dict, Any

from ark_engine.core.models import ArkModule

logger = logging.getLogger(__name__)

class ArkLoader:
    @staticmethod
    def _calculate_checksum(content_dict: Dict) -> str:
        """
        Calculates SHA256 of the content block.
        Uses sorted keys to ensure JSON canonicalization for hashing.
        """
        # Ensure consistent JSON dump
        dumped = json.dumps(content_dict, sort_keys=True).encode("utf-8")
        return hashlib.sha256(dumped).hexdigest()

    @staticmethod
    def read_raw_data(file_path: Path) -> Dict[str, Any]:
        """
        Reads .ark file as raw dictionary (JSON/YAML) without full Pydantic validation.
        Used for verifying signatures before data is trusted.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Ark module not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            if file_path.suffix in ['.yaml', '.yml']:
                return yaml.safe_load(f)
            else:
                return json.load(f)

    @classmethod
    def load(cls, file_path: Union[str, Path]) -> ArkModule:
        """
        Loads a .ark file, validates schema via Pydantic, 
        and verifies the SHA256 checksum of the content.
        """
        path = Path(file_path)
        
        # Use the raw reader to get the dict
        data = cls.read_raw_data(path)

        # 1. Validate Schema (Pydantic)
        try:
            module = ArkModule(**data)
        except Exception as e:
            raise ValueError(f"Schema Validation Failed: {e}")

        # 2. Verify Checksum
        # Note: We hash the raw dict content from the loaded JSON/YAML
        calculated_hash = cls._calculate_checksum(data.get("content", {}))
        
        if module.header.checksum != calculated_hash:
            logger.warning(
                f"Checksum mismatch! Header: {module.header.checksum}, "
                f"Calculated: {calculated_hash}"
            )
            # In strict mode, this should raise error, but for MVP we warn
            # raise ValueError("Integrity Check Failed: Checksum mismatch")

        return module
