import pytest
import shutil
import json
from pathlib import Path
from datetime import datetime

from ark_engine.store.manager import ArkStoreManager
from ark_engine.store.models import IndexEntry
from ark_engine.core.models import ArkModule, ArkHeader, ArkMetadata, ArkContent

# Фікстура для створення тимчасового .ark файлу
@pytest.fixture
def sample_ark_file(tmp_path):
    file_path = tmp_path / "test_module.ark"
    
    # Створюємо мінімально валідний JSON для ArkLoader
    # Важливо: ArkLoader очікує структуру ArkModule
    data = {
        "header": {
            "id": "test-pkg-v1",
            "title": "Test Package",
            "author": "Tester",
            "created_at": datetime.now().isoformat(),
            "version": "1.0.0",
            "checksum": "fake_checksum",
            "license": "MIT"
        },
        "metadata": {
            "language": "uk",
            "categories": [],
            "tags": [],
            "locale": "uk_UA",
            "intended_use": "test",
            "risk_level": "low"
        },
        "content": {
            "docs": ["Test content"],
            "embeddings": [[0.1, 0.2]],
            "media": []
        }
    }
    
    with open(file_path, "w") as f:
        json.dump(data, f)
        
    return file_path

# Фікстура для ізоляції сховища
@pytest.fixture
def store_manager(tmp_path):
    # Перевизначаємо кореневий шлях для тестів через monkeypatch або 
    # просто створюємо екземпляр і підміняємо шлях (якщо клас дозволяє)
    # Тут ми використаємо monkeypatch для utils.get_store_root, якщо це можливо,
    # або просто змінимо атрибут root в екземплярі для простоти тесту.
    
    manager = ArkStoreManager()
    manager.root = tmp_path / "ark_store"
    manager.index.root = manager.root
    manager.index.index_path = manager.root / "index.json"
    manager.installer.packages_dir = manager.root / "packages"
    
    # Створюємо структуру
    manager.installer.packages_dir.mkdir(parents=True)
    
    return manager

def test_install_local_file(store_manager, sample_ark_file):
    entry = store_manager.install(str(sample_ark_file))
    
    assert entry.id == "test-pkg-v1"
    assert entry.title == "Test Package"
    assert (store_manager.root / "packages" / "test-pkg-v1" / "module.ark").exists()
    assert (store_manager.root / "packages" / "test-pkg-v1" / "meta.json").exists()

def test_list_packages(store_manager, sample_ark_file):
    store_manager.install(str(sample_ark_file))
    packages = store_manager.list()
    assert len(packages) == 1
    assert packages[0].id == "test-pkg-v1"

def test_remove_package(store_manager, sample_ark_file):
    store_manager.install(str(sample_ark_file))
    store_manager.remove("test-pkg-v1")
    
    assert len(store_manager.list()) == 0
    assert not (store_manager.root / "packages" / "test-pkg-v1").exists()

def test_doctor_removes_orphans(store_manager):
    # Створюємо фейковий запис в індексі
    fake_entry = IndexEntry(
        id="ghost", 
        version="1.0", 
        title="Ghost", 
        installed_at=datetime.now(), 
        path="/non/existent/path"
    )
    store_manager.index.add_package(fake_entry)
    
    assert len(store_manager.list()) == 1
    
    store_manager.doctor()
    
    assert len(store_manager.list()) == 0
