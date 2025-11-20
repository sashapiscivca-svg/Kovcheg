from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class Publisher(BaseModel):
    """Модель даних для довіреного видавця."""
    id: str
    display_name: str
    public_key_path: str
    trusted: bool = True
    public_key_pem: Optional[str] = Field(None, description="PEM representation of the public key")
    added_at: datetime = Field(default_factory=datetime.now)

class TrustedPublishers(BaseModel):
    """Структура файлу trusted_publishers.json."""
    version: str = "0.1"
    publishers: List[Publisher] = Field(default_factory=list)

class SignatureBlock(BaseModel):
    """Блок підпису, що інтегрується в .ark файл."""
    public_key_id: str = Field(..., description="ID видавця")
    signature_algo: str = "Ed25519"
    checksum_sha256: str = Field(..., description="SHA-256 хеш контенту")
    signature_b64: str = Field(..., description="Підпис Ed25519, кодований Base64")
    signed_at: str = Field(..., description="ISO 8601 timestamp підпису")
