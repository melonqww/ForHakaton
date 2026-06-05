import os
import shutil
import subprocess
import threading
import urllib.request
import requests

# Глобальный статус фоновых задач
OLLAMA_STATUS = {
    "downloading_setup": False,
    "download_progress": 0.0,
    "download_error": None,
    "download_done": False,
    "pulling_model": False,
    "pull_progress": "",
    "pull_done": False,
    "pull_error": None
}

def get_base_url(generate_url: str) -> str:
    """Извлекает базовый URL Ollama из URL генерации."""
    if "/api/generate" in generate_url:
        return generate_url.split("/api/generate")[0]
    return "http://localhost:11434"

def is_ollama_running(generate_url: str) -> bool:
    """Проверяет, запущен ли API Ollama."""
    base_url = get_base_url(generate_url)
    try:
        response = requests.get(base_url, timeout=2)
        return response.status_code == 200
    except Exception:
        return False

def has_model(generate_url: str, model_name: str) -> bool:
    """Проверяет, загружена ли модель в Ollama."""
    base_url = get_base_url(generate_url)
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=2)
        if response.status_code == 200:
            models = response.json().get("models", [])
            for m in models:
                name = m.get("name", "")
                # Модель может быть указана с тегом или без (например qwen2.5:0.5b vs qwen2.5:0.5b-instruct)
                if model_name in name or name in model_name:
                    return True
    except Exception:
        pass
    return False

def _pull_model_thread(base_url: str, model_name: str):
    global OLLAMA_STATUS
    OLLAMA_STATUS["pulling_model"] = True
    OLLAMA_STATUS["pull_progress"] = "Запуск скачивания..."
    OLLAMA_STATUS["pull_done"] = False
    OLLAMA_STATUS["pull_error"] = None
    
    try:
        url = f"{base_url}/api/pull"
        # Запускаем стриминг прогресса скачивания
        response = requests.post(url, json={"name": model_name, "stream": True}, stream=True, timeout=600)
        if response.status_code == 200:
            for line in response.iter_lines():
                if line:
                    import json
                    data = json.loads(line.decode('utf-8'))
                    status = data.get("status", "")
                    completed = data.get("completed", 0)
                    total = data.get("total", 0)
                    
                    if total > 0:
                        pct = (completed / total) * 100
                        OLLAMA_STATUS["pull_progress"] = f"{status} ({pct:.1f}%)"
                    else:
                        OLLAMA_STATUS["pull_progress"] = status
            OLLAMA_STATUS["pull_done"] = True
        else:
            OLLAMA_STATUS["pull_error"] = f"Ошибка сервера Ollama: {response.status_code}"
    except Exception as e:
        OLLAMA_STATUS["pull_error"] = f"Не удалось скачать модель: {e}"
    finally:
        OLLAMA_STATUS["pulling_model"] = False

def pull_model_background(generate_url: str, model_name: str):
    """Запускает фоновое скачивание модели."""
    global OLLAMA_STATUS
    if OLLAMA_STATUS["pulling_model"]:
        return
    base_url = get_base_url(generate_url)
    thread = threading.Thread(target=_pull_model_thread, args=(base_url, model_name), daemon=True)
    thread.start()

def find_ollama_path() -> str:
    """Ищет исполняемый файл ollama.exe на компьютере."""
    # 1. Проверяем PATH
    which_path = shutil.which("ollama")
    if which_path:
        return which_path
        
    # 2. Проверяем стандартные пути установки Windows
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        standard_path = os.path.join(user_profile, "AppData", "Local", "Programs", "Ollama", "ollama.exe")
        if os.path.exists(standard_path):
            return standard_path
            
    # 3. Дополнительные системные папки
    program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    path_pf = os.path.join(program_files, "Ollama", "ollama.exe")
    if os.path.exists(path_pf):
        return path_pf
        
    return ""

def start_ollama_local() -> bool:
    """Ищет и запускает локальный процесс Ollama."""
    path = find_ollama_path()
    if path:
        try:
            # Запускаем в фоновом режиме
            subprocess.Popen([path, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass
    return False

def _download_setup_thread(dest_dir: str):
    global OLLAMA_STATUS
    OLLAMA_STATUS["downloading_setup"] = True
    OLLAMA_STATUS["download_progress"] = 0.0
    OLLAMA_STATUS["download_done"] = False
    OLLAMA_STATUS["download_error"] = None
    
    setup_url = "https://ollama.com/download/OllamaSetup.exe"
    dest_path = os.path.join(dest_dir, "OllamaSetup.exe")
    
    try:
        # Скачивание с отслеживанием прогресса
        req = urllib.request.Request(
            setup_url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req) as response:
            meta = response.info()
            file_size = int(meta.get("Content-Length", 0))
            
            chunk_size = 1024 * 1024  # 1 MB
            downloaded = 0
            
            with open(dest_path, "wb") as f:
                while True:
                    buffer = response.read(chunk_size)
                    if not buffer:
                        break
                    f.write(buffer)
                    downloaded += len(buffer)
                    if file_size > 0:
                        OLLAMA_STATUS["download_progress"] = downloaded / file_size
            OLLAMA_STATUS["download_done"] = True
    except Exception as e:
        OLLAMA_STATUS["download_error"] = f"Ошибка скачивания: {e}"
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except Exception:
                pass
    finally:
        OLLAMA_STATUS["downloading_setup"] = False

def download_ollama_setup_background(dest_dir: str):
    """Запускает фоновое скачивание установщика OllamaSetup.exe."""
    global OLLAMA_STATUS
    if OLLAMA_STATUS["downloading_setup"]:
        return
    os.makedirs(dest_dir, exist_ok=True)
    thread = threading.Thread(target=_download_setup_thread, args=(dest_dir,), daemon=True)
    thread.start()
