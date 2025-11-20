from huggingface_hub import hf_hub_download
import os

# Спробуємо альтернативний, надійний репозиторій GGUF
# bartowski - один з найактивніших мейнтенерів квантованих моделей
REPO_ID = "bartowski/Qwen2.5-7B-Instruct-GGUF"
# Перевірена назва файлу
FILENAME = "Qwen2.5-7B-Instruct-Q4_K_M.gguf" 
CACHE_DIR = "./models_cache"

def download():
    print(f"Downloading {FILENAME} from {REPO_ID} to {CACHE_DIR}...")
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    try:
        path = hf_hub_download(
            repo_id=REPO_ID,
            filename=FILENAME,
            local_dir=CACHE_DIR,
            local_dir_use_symlinks=False
        )
        print(f"✅ Model downloaded to: {path}")
        
        # Перейменовуємо для зручності (lowercase), щоб код engine його знайшов
        target_path = os.path.join(CACHE_DIR, "qwen2.5-7b-instruct-q4_k_m.gguf")
        if path != target_path:
             os.rename(path, target_path)
             print(f"🔄 Renamed to standard name: {target_path}")

    except Exception as e:
        print(f"❌ Download failed: {e}")

if __name__ == "__main__":
    download()
