from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

class RiskLevel(str, Enum):
    low = "low"
    warning = "warning"
    restricted = "restricted"
    toxic = "toxic"

class ArkHeader(BaseModel):
    """Header: Immutable identification and cryptographic verification data."""
    id: UUID
    title: str
    author: str
    created_at: datetime
    version: str
    checksum: str
    signature: Optional[str] = None
    license: str

class ArkMetadata(BaseModel):
    """Metadata: Contextual layer for filtering and moderation."""
    language: str = Field(..., description="IETF BCP 47 language tag (e.g., 'uk-UA')")
    categories: List[str]
    tags: List[str]
    locale: str
    intended_use: str
    risk_level: RiskLevel = RiskLevel.low
    warning_label: Optional[str] = None

class ArkContent(BaseModel):
    """Content: The primary data payload."""
    
    docs: List[str] 
    
    embeddings: List[List[float]] 
    
    media: List[str] = Field(default_factory=list)
    
    search_index: List[Dict[str, Any]] = Field(default_factory=list) 
    
    references: Optional[List[str]] = None

class ArkSignatureBlock(BaseModel):
    """Signature Block: Data for cryptographic verification."""
    public_key_id: Optional[str] = None
    signature_algo: Optional[str] = None
    signature_bin: Optional[str] = None

class ArkUpdateManifest(BaseModel):
    """Update Manifest: Placeholder for differential updates."""
    patches: List[Any] = Field(default_factory=list)

class ArkModule(BaseModel):
    """The complete Kovcheg Archive Format (.ark) structure."""
    header: ArkHeader
    metadata: ArkMetadata
    content: ArkContent
    signature_block: ArkSignatureBlock = Field(default_factory=ArkSignatureBlock)
    update_manifest: ArkUpdateManifest = Field(default_factory=ArkUpdateManifest)
