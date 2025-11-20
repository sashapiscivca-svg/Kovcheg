import glob
import os
import logging
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from pathlib import Path

# Імпорт з нашої ark_engine
from ark_engine.core.loader import ArkLoader
from web_ui.backend.settings import settings

# Налаштування логера
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("modules_router")

router = APIRouter()

class ModuleSummary(BaseModel):
    id: str
    title: str
    version: str

@router.get("/modules", response_model=List[ModuleSummary])
def list_modules():
    """Сканує директорію та повертає список доступних .ark модулів."""
    modules_list = []
    
    search_path = Path(settings.ARK_MODULES_PATH)
    
    # 1. ДІАГНОСТИКА: Перевіряємо папку
    if not search_path.exists():
        logger.error(f"❌ DIRECTORY NOT FOUND: {search_path}")
        return []
    
    logger.info(f"📂 Scanning directory: {search_path}")
    
    # 2. ДІАГНОСТИКА: Що фізично є в папці?
    try:
        all_files = os.listdir(search_path)
        logger.info(f"👀 Files in directory: {all_files}")
    except Exception as e:
        logger.error(f"❌ Failed to list directory: {e}")
        return []

    # 3. Пошук файлів
    ark_files = list(search_path.glob("*.ark.json"))
    logger.info(f"🔎 Found .ark.json files matching pattern: {ark_files}")
    
    for f_path in ark_files:
        logger.info(f"👉 Attempting to load: {f_path.name}")
        try:
            # Спроба завантаження
            module = ArkLoader.load(f_path)
            
            summary = ModuleSummary(
                id=str(module.header.id),
                title=module.header.title,
                version=module.header.version
            )
            modules_list.append(summary)
            logger.info(f"✅ SUCCESS: Loaded {module.header.title}")
            
        except Exception as e:
            # 4. ДІАГНОСТИКА: Чому саме файл впав?
            # Виводимо повний трейс помилки
            logger.error(f"❌ FAILED to load {f_path.name}. Reason: {str(e)}")
            import traceback
            traceback.print_exc()

    logger.info(f"🏁 Returning {len(modules_list)} modules.")
    return modules_list
