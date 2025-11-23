import os
import logging
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import List, Optional
from pathlib import Path

from ark_engine.core.loader import ArkLoader
from ark_engine.core.models import ArkModule
from web_ui.backend.settings import settings

# Налаштування логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("modules_router")

router = APIRouter()

# Розширена модель для UI карток
class ModuleMetadata(BaseModel):
    id: str
    title: str
    version: str
    description: str
    author: str
    category: str
    size: str
    verified: bool
    created_at: str

def get_human_readable_size(size_in_bytes):
    """Конвертує байти в MB/GB"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.1f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.1f} TB"

@router.get("/modules", response_model=List[ModuleMetadata])
def list_modules():
    """
    Сканує директорію та повертає розширені метадані для UI.
    """
    modules_list = []
    search_path = Path(settings.ARK_MODULES_PATH)
    
    if not search_path.exists():
        logger.warning(f"Modules directory not found: {search_path}")
        return []

    # Скануємо .ark.json файли
    ark_files = list(search_path.glob("*.ark.json"))
    
    for f_path in ark_files:
        try:
            # Завантажуємо тільки метадані (без важких векторів, якщо loader дозволяє)
            # Примітка: ArkLoader.load зараз вантажить все, для оптимізації в майбутньому
            # варто додати параметр lazy=True в ArkLoader.
            module = ArkLoader.load(f_path)
            
            # Визначаємо категорію (перший тег або дефолт)
            category = "📦 База знань"
            if module.metadata.tags:
                category = module.metadata.tags[0].title()
            
            # Перевірка підпису (спрощена для UI)
            is_verified = bool(module.header.signature)

            # Розмір файлу
            file_size = get_human_readable_size(f_path.stat().st_size)

            meta = ModuleMetadata(
                id=str(module.header.id),
                title=module.header.title,
                version=module.header.version,
                description=module.header.title, # Можна додати поле description в ArkHeader пізніше
                author=module.header.author,
                category=category,
                size=file_size,
                verified=is_verified,
                created_at=module.header.created_at.isoformat() if hasattr(module.header.created_at, 'isoformat') else str(module.header.created_at)
            )
            modules_list.append(meta)
            
        except Exception as e:
            logger.error(f"Failed to read module {f_path.name}: {e}")
            # Не крашимо весь список через один битий файл
            continue

    return modules_list
