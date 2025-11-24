# ark_engine/store/models.py (ОНОВЛЕНО)

from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class PackageMeta(BaseModel):
    """Розширена метаінформація про пакет, що зберігається локально."""
    id: str
    title: str
    version: str
    author: str
    description: Optional[str] = None
    created_at: datetime
    
    # Статистика вмісту
    doc_count: int = 0
    embedding_count: int = 0 # Залишаємо для сумісності, але заповнюємо інакше
    total_size_bytes: int = 0
    checksum: str 

class IndexEntry(BaseModel):
    """Запис в головному index.json."""
    id: str
    version: str
    title: str
    installed_at: datetime
    path: str
    
    # Статус цілісності
    signature_ok: bool = False
    is_corrupted: bool = False
    
    # Security поля
    publisher_id: str = "unknown"
    trusted: bool = False

class StoreIndex(BaseModel):
    """Структура файлу index.json."""
    version: str = "0.1"
    updated_at: datetime = Field(default_factory=datetime.now)
    packages: List[IndexEntry] = []
