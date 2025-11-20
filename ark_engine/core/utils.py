import hashlib
import json
import uuid
from datetime import datetime, timezone

def generate_uuid() -> str:
    return str(uuid.uuid4())

def get_current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def calculate_checksum(data: dict) -> str:
    """
    Обчислює SHA256 хеш від канонічного JSON представлення даних content.
    """
    dumped = json.dumps(data, sort_keys=True).encode("utf-8")
    return hashlib.sha256(dumped).hexdigest()
