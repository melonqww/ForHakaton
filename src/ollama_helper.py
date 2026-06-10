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


class OllamaError(Exception):
    """Ошибка Ollama с понятным сообщением."""
    pass


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
    except requests.exceptions.ConnectionError:
        return False
    except requests.exceptions.Timeout:
        return False
    except Exception:
        return False


def has_model(generate_url: str, model_name: str) -> bool:
    """Проверяет, загружена ли модель в Ollama."""
    if not model_name:
        return False
    base_url = get_base_url(generate_url)
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=2)
        if response.status_code == 200:
            models = response.json().get("models", [])
            for m in models:
                name = m.get("name", "")
                if model_name in name or name in model_name:
                    return True
        return False
    except requests.exceptions.ConnectionError:
        return False
    except requests.exceptions.Timeout:
        return False
    except Exception:
        return False


def _pull_model_thread(base_url: str, model_name: str):
    global OLLAMA_STATUS
    OLLAMA_STATUS["pulling_model"] = True
    OLLAMA_STATUS["pull_progress"] = "Запуск скачивания..."
    OLLAMA_STATUS["pull_done"] = False
    OLLAMA_STATUS["pull_error"] = None

    try:
        url = f"{base_url}/api/pull"
        response = requests.post(url, json={"name": model_name, "stream": True}, stream=True, timeout=600)
        if response.status_code == 200:
            for line in response.iter_lines():
                if line:
                    try:
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
                    except json.JSONDecodeError:
                        continue
                    except Exception:
                        continue
            OLLAMA_STATUS["pull_done"] = True
        else:
            OLLAMA_STATUS["pull_error"] = (
                f"Ошибка сервера Ollama: код {response.status_code}. "
                f"Проверьте, что Ollama запущена командой «ollama serve»."
            )
    except requests.exceptions.ConnectionError:
        OLLAMA_STATUS["pull_error"] = "Не удалось подключиться к Ollama. Убедитесь, что Ollama запущена."
    except requests.exceptions.Timeout:
        OLLAMA_STATUS["pull_error"] = "Ollama не ответила за 10 минут. Возможно, модель слишком велика для вашего интернета."
    except Exception as e:
        OLLAMA_STATUS["pull_error"] = f"Не удалось скачать модель: {e}"
    finally:
        if not OLLAMA_STATUS["pull_done"] and not OLLAMA_STATUS["pull_error"]:
            OLLAMA_STATUS["pull_error"] = "Скачивание модели прервано по неизвестной причине."
        OLLAMA_STATUS["pulling_model"] = False


def pull_model_background(generate_url: str, model_name: str):
    """Запускает фоновое скачивание модели."""
    global OLLAMA_STATUS
    if OLLAMA_STATUS["pulling_model"]:
        return
    if not model_name:
        OLLAMA_STATUS["pull_error"] = "Не указано имя модели для скачивания."
        return
    base_url = get_base_url(generate_url)
    thread = threading.Thread(target=_pull_model_thread, args=(base_url, model_name), daemon=True)
    thread.start()


def find_ollama_path() -> str:
    """Ищет исполняемый файл ollama.exe на компьютере."""
    try:
        which_path = shutil.which("ollama")
        if which_path:
            return which_path

        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            standard_path = os.path.join(user_profile, "AppData", "Local", "Programs", "Ollama", "ollama.exe")
            if os.path.exists(standard_path):
                return standard_path

        program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        path_pf = os.path.join(program_files, "Ollama", "ollama.exe")
        if os.path.exists(path_pf):
            return path_pf
    except Exception:
        pass

    return ""


def start_ollama_local() -> bool:
    """Ищет и запускает локальный процесс Ollama."""
    path = find_ollama_path()
    if path:
        try:
            subprocess.Popen([path, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except FileNotFoundError:
            print("Предупреждение: ollama.exe не найден по указанному пути.")
        except PermissionError:
            print("Предупреждение: нет прав на запуск Ollama. Запустите от имени администратора.")
        except Exception as e:
            print(f"Предупреждение: не удалось запустить Ollama: {e}")
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
    except urllib.error.URLError as e:
        OLLAMA_STATUS["download_error"] = f"Не удалось скачать установщик Ollama: нет соединения с интернетом ({e.reason})."
    except PermissionError:
        OLLAMA_STATUS["download_error"] = "Нет прав на запись в папку для скачивания установщика."
    except Exception as e:
        OLLAMA_STATUS["download_error"] = f"Ошибка скачивания установщика Ollama: {e}"
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
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except Exception as e:
        OLLAMA_STATUS["download_error"] = f"Не удалось создать папку для скачивания: {e}"
        return
    thread = threading.Thread(target=_download_setup_thread, args=(dest_dir,), daemon=True)
    thread.start()