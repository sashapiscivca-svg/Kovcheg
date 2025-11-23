from huggingface_hub import hf_hub_download
import os

# Оптимальна модель для i3/8-16GB RAM
# Qwen 2.5 3B Instruct (Q4_K_M квантування)
REPO_ID = "bartowski/Qwen2.5-3B-Instruct-GGUF"
FILENAME = "Qwen2.5-3B-Instruct-Q4_K_M.gguf"
CACHE_DIR = "./models_cache"

def download():
    print(f"🚀 Downloading LIGHTWEIGHT model: {FILENAME}...")
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    try:
        path = hf_hub_download(
            repo_id=REPO_ID,
            filename=FILENAME,
            local_dir=CACHE_DIR,
            local_dir_use_symlinks=False
        )
        print(f"✅ Model downloaded to: {path}")
        
        # Перейменовуємо для зручності
        target_path = os.path.join(CACHE_DIR, "qwen2.5-3b-instruct.gguf")
        if path != target_path:
             os.rename(path, target_path)
             print(f"🔄 Renamed to: {target_path}")

    except Exception as e:
        print(f"❌ Download failed: {e}")

if __name__ == "__main__":
    download()
