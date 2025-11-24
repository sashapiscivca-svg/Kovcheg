# ark_engine/core/models.py

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ArkHeader(BaseModel):
    id: str = Field(..., description="Unique UUIDv4 for the archive.")
    version: str = Field("0.1.0", description="Schema version (SemVer).")
    title: str = Field(..., description="Human-readable title.")
    author: str = Field("Unknown", description="Author of the knowledge base.") # <--- ПОВЕРНУЛИ ПОЛЕ AUTHOR
    created_at: str = Field(..., description="ISO 8601 UTC timestamp.")
    checksum: str = Field(..., description="SHA-256 hash of the canonical JSON representation of 'content'.")
    license: str = Field("Unknown", description="SPDX license identifier.")
    # Дозволяємо і Dict, і str, і None для зворотної сумісності, якщо старі файли мають ""
    signature: Optional[Any] = Field(None, description="Cryptographic signature block.")

class ArkMetadata(BaseModel):
    language: str = Field("uk-UA", description="Primary language of content (IETF BCP 47 Tag).")
    risk_level: str = Field("safe", description="Content safety marker.")
    tags: List[str] = Field(default_factory=list, description="Keywords for quick search.")
    data_provenance: Dict[str, Any] = Field(default_factory=dict, description="Lineage information.")

class ArkContent(BaseModel):
    docs: List[str] = Field(..., description="List of normalized textual chunks.")
    vector_index_uri: Optional[str] = Field(None, description="URI path to the disk-based vector index.")
    search_index: List[Dict[str, Any]] = Field(default_factory=list, description="Optional pre-computed full-text or graph index data.")
    references: Optional[List[str]] = Field(None, description="Source links or identifiers for each chunk.")
    media: List[str] = Field(default_factory=list, description="Paths or URIs to associated media files.")

class ArkModule(BaseModel):
    header: ArkHeader
    metadata: ArkMetadata
    content: ArkContent
    signature_block: Dict[str, Any] = Field(default_factory=dict)
    update_manifest: Dict[str, Any] = Field(default_factory=dict)
