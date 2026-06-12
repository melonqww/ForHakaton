import streamlit as st
import pandas as pd
import os
import time
import traceback
import requests

from src.pipeline import run_pipeline
from src.utils import find_column_index
from src.classifier import RequestClassifier
from src.doc_generator import generate_executive_summary, generate_docx, generate_pdf
from src.config import AI_RESULTS_CACHE, OMSK_DISTRICTS_COORDS
import pydeck as pdk
import threading

def run_background_ai(stats, key_name, ollama_url):
    try:
        import traceback
        print(f"[AI Background] Starting generation for: {key_name}")
        doc_filename = key_name if key_name != "Все файлы" else "Все файлы.xlsx"
        
        ai_summary = generate_executive_summary(stats, ollama_url)
        print(f"[AI Background] Summary generated for {key_name} (len={len(ai_summary) if ai_summary else 0})")
        
        ai_doc_docx = generate_docx(stats, ai_summary, doc_filename, ollama_url)
        print(f"[AI Background] DOCX generated for {key_name} (len={len(ai_doc_docx) if ai_doc_docx else 0})")
        
        ai_doc_pdf = generate_pdf(stats, ai_summary, doc_filename, ollama_url)
        print(f"[AI Background] PDF generated for {key_name} (len={len(ai_doc_pdf) if ai_doc_pdf else 0})")
        
        AI_RESULTS_CACHE[key_name] = {
            "ai_summary": ai_summary,
            "ai_doc_docx": ai_doc_docx,
            "ai_doc_pdf": ai_doc_pdf,
            "status": "ready"
        }
        print(f"[AI Background] Finished successfully for: {key_name}")
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print(f"[AI Background] Exception during generation for {key_name}:\n{err_msg}")
        AI_RESULTS_CACHE[key_name] = {
            "status": "error",
            "error": f"{str(e)}\n{err_msg}"
        }


def remember_processing_error(message, file_name=None):
    st.session_state.processing_error = {
        "message": message,
        "file_name": file_name,
        "details": traceback.format_exc(),
    }


def show_processing_error(error_info):
    if not error_info:
        return

    file_name = error_info.get("file_name")
    if file_name:
        st.error(f"Ошибка при обработке файла \"{file_name}\": {error_info['message']}")
    else:
        st.error(f"Ошибка при обработке: {error_info['message']}")

    with st.expander("Показать подробности ошибки"):
        st.code(error_info.get("details") or "Подробности недоступны.", language="text")


def friendly_error_message(error):
    if isinstance(error, PermissionError):
        return (
            "Нет доступа к файлу или папке. Проверьте, что Excel-файл не открыт в другой программе "
            "и что выбранная папка доступна для записи."
        )
    if isinstance(error, MemoryError):
        return (
            "Не хватило оперативной памяти. Попробуйте файл меньшего размера или закройте лишние программы."
        )
    if isinstance(error, FileNotFoundError):
        return "Файл или папка не найдены. Проверьте путь и повторите попытку."

    text = str(error).strip()
    lowered = text.lower()
    if "permission denied" in lowered or "access is denied" in lowered or "отказано в доступе" in lowered:
        return (
            "Нет доступа к файлу или папке. Закройте открытые Excel-файлы с результатами "
            "и проверьте права на папку сохранения."
        )
    if "no space left" in lowered or "not enough space" in lowered:
        return "Недостаточно места на диске для сохранения результата."
    return text or error.__class__.__name__


def unique_output_path(directory, source_name):
    safe_name = os.path.basename(source_name)
    base_name = f"Обработанные_{safe_name}"
    path = os.path.join(directory, base_name)
    if not os.path.exists(path):
        return path

    stem, ext = os.path.splitext(base_name)
    if not ext:
        ext = ".xlsx"
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    for counter in range(1, 1000):
        candidate = os.path.join(directory, f"{stem}_{timestamp}_{counter}{ext}")
        if not os.path.exists(candidate):
            return candidate
    return os.path.join(directory, f"{stem}_{timestamp}{ext}")


def build_ollama_source_context(input_path, ollama_url):
    """Prepare a compact source-file context for Ollama before the main analysis."""
    try:
        try:
            header_df = pd.read_excel(input_path, nrows=0, engine="calamine")
        except Exception:
            header_df = pd.read_excel(input_path, nrows=0)

        headers = list(header_df.columns)
        if not headers:
            return "", "В исходном Excel не найдены колонки."

        text_idx = find_column_index(headers, "text", 36)
        if text_idx >= len(headers):
            return "", "В исходном Excel не найдена колонка с текстом обращения."

        text_col = headers[text_idx]
        sample_cols = [text_col]
        source_fields = [
            ("municipality", 24, "Районы"),
            ("group", 21, "Темы"),
            ("topic", 22, "Подтемы"),
        ]
        resolved_fields = []
        for key, default_idx, label in source_fields:
            idx = find_column_index(headers, key, default_idx)
            if idx < len(headers):
                col = headers[idx]
                resolved_fields.append((col, label))
                if col not in sample_cols:
                    sample_cols.append(col)

        for label_col in ("CLASS_LABEL", "Тип инцидента"):
            if label_col in headers and label_col not in sample_cols:
                sample_cols.append(label_col)

        try:
            sample_df = pd.read_excel(input_path, usecols=sample_cols, nrows=500, engine="calamine")
        except Exception:
            sample_df = pd.read_excel(input_path, usecols=sample_cols, nrows=500)

        lines = ["Краткая карта исходного Excel для анализа обращений."]
        lines.append(f"Прочитано для настройки: {len(sample_df)} строк.")

        for col, label in resolved_fields:
            if col in sample_df.columns:
                values = sample_df[col].dropna().astype(str).str.strip()
                values = values[values != ""]
                if not values.empty:
                    top_values = values.value_counts().head(8)
                    joined = "; ".join(f"{name}: {count}" for name, count in top_values.items())
                    lines.append(f"{label}: {joined}")

        for label_col in ("CLASS_LABEL", "Тип инцидента"):
            if label_col in sample_df.columns:
                values = sample_df[label_col].dropna().astype(str).str.strip()
                values = values[values != ""]
                if not values.empty:
                    joined = "; ".join(f"{name}: {count}" for name, count in values.value_counts().head(6).items())
                    lines.append(f"Разметка в исходнике: {joined}")
                break

        examples = []
        for raw_text in sample_df[text_col].dropna().astype(str):
            text = " ".join(raw_text.split())
            if len(text) < 20:
                continue
            examples.append(text[:220])
            if len(examples) >= 30:
                break

        if examples:
            lines.append("Примеры обращений:")
            lines.extend(f"- {text}" for text in examples)

        source_profile = "\n".join(lines)[:7000]
        prompt = (
            "Ты - локальный аналитический центр Ollama. ОТВЕЧАЙ СТРОГО НА РУССКОМ ЯЗЫКЕ! "
            "Использование китайских иероглифов, латиницы или других нерусских символов категорически запрещено. "
            "Сначала изучи карту исходного Excel, чтобы потом точнее объяснять районы, темы, "
            "спам/благодарности и реальные проблемы. Сделай короткий рабочий контекст до 1800 символов: "
            "какие темы встречаются, какие признаки отличают реальные проблемы от информационных обращений, "
            "какие формулировки важны для анализа. Не выдумывай внешних фактов.\n\n"
            f"{source_profile}"
        )

        try:
            response = requests.post(
                ollama_url,
                json={
                    "model": "qwen2.5:0.5b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2, "num_ctx": 4096, "repetition_penalty": 1.05},
                },
                timeout=12,
            )
            if response.status_code == 200:
                ollama_text = response.json().get("response", "").strip()
                if ollama_text:
                    return ollama_text[:2500], None
            return source_profile[:2500], "Ollama не вернула учебный контекст. Использую краткую карту исходного файла."
        except Exception as e:
            return source_profile[:2500], f"Ollama сейчас не ответила: {e}. Использую краткую карту исходного файла."
    except Exception as e:
        return "", f"Не удалось подготовить исходный файл для Ollama: {e}"


def get_subdirectories(path):
    """Возвращает список поддиректорий в указанном пути, исключая скрытые."""
    try:
        return ["."] + [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d)) and not d.startswith('.')]
    except Exception:
        return ["."]

def get_visible_nodes(current_path, depth, expanded_paths):
    nodes = []
    if current_path == "Этот компьютер":
        nodes.append(("Этот компьютер", "Этот компьютер", depth))
        if "Этот компьютер" in expanded_paths:
            drives = []
            if os.name == 'nt':
                import string
                from ctypes import windll
                bitmask = windll.kernel32.GetLogicalDrives()
                for letter in string.ascii_uppercase:
                    if bitmask & 1:
                        drives.append(f"{letter}:\\")
                    bitmask >>= 1
            else:
                drives = ["/"]
            for drv in drives:
                drive_letter = drv[:2]
                label = f"Локальный диск ({drive_letter})" if os.name == 'nt' else "Корневой каталог (/)"
                nodes.append((drv, label, depth + 1))
                if drv in expanded_paths:
                    nodes.extend(get_visible_nodes(drv, depth + 2, expanded_paths))
    else:
        subdirs = []
        try:
            for item in os.listdir(current_path):
                full_path = os.path.join(current_path, item)
                if os.path.isdir(full_path) and not item.startswith('$') and not item.startswith('.'):
                    subdirs.append(item)
            subdirs.sort(key=str.lower)
        except Exception:
            pass
        for sd in subdirs:
            full_sd = os.path.join(current_path, sd)
            nodes.append((full_sd, sd, depth))
            if full_sd in expanded_paths:
                nodes.extend(get_visible_nodes(full_sd, depth + 1, expanded_paths))
    return nodes

@st.dialog("Обзор папок")
def folder_picker_dialog():
    st.markdown("Выберите папку из списка и нажмите «ОК».")
    
    selected_path = st.session_state.get("selected_path", st.session_state.custom_save_path)
    st.text_input("Выбранная папка:", value=selected_path, disabled=True, label_visibility="collapsed")
    
    if "expanded_paths" not in st.session_state:
        st.session_state.expanded_paths = set()
        st.session_state.expanded_paths.add("Этот компьютер")
        p = os.path.abspath(st.session_state.custom_save_path)
        while p:
            st.session_state.expanded_paths.add(p)
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
            
    # Inject Custom Tree CSS to style Streamlit buttons as tree nodes
    st.markdown("""
    <style>
        /* Сброс отступов колонок внутри диалога */
        div[data-testid="stDialog"] div[data-testid="column"] {
            padding: 0 !important;
        }
        
        /* Стилизация всех кнопок-стрелочек в дереве папок */
        div[class*="st-key-tg_"] button {
            background: transparent !important;
            background-color: transparent !important;
            border: none !important;
            box-shadow: none !important;
            min-height: 22px !important;
            height: 22px !important;
            line-height: 18px !important;
            font-size: 0.7rem !important;
            border-radius: 3px !important;
            color: #64748B !important;
            display: flex !important;
            align-items: center !important;
            text-align: right !important;
            justify-content: flex-end !important;
            width: 100% !important;
            padding: 0 6px 0 0 !important;
            font-weight: normal !important;
        }
        
        div[class*="st-key-tg_"] button:hover {
            background: transparent !important;
            background-color: transparent !important;
            color: #1E3A8A !important;
            border: none !important;
            box-shadow: none !important;
        }
        
        div[class*="st-key-tg_"] button:focus,
        div[class*="st-key-tg_"] button:active,
        div[class*="st-key-tg_"] button:focus-visible {
            outline: none !important;
            box-shadow: none !important;
            background-color: transparent !important;
            border: none !important;
        }

        /* Стилизация всех кнопок названий папок в дереве папок */
        div[class*="st-key-nm_"] button {
            background-color: rgba(128, 128, 128, 0.06) !important;
            background: rgba(128, 128, 128, 0.06) !important;
            border: 1px solid rgba(128, 128, 128, 0.12) !important;
            box-shadow: none !important;
            min-height: 22px !important;
            height: 22px !important;
            line-height: 18px !important;
            font-size: 0.85rem !important;
            border-radius: 4px !important;
            color: inherit !important;
            display: flex !important;
            align-items: center !important;
            text-align: left !important;
            justify-content: flex-start !important;
            width: 100% !important;
            padding: 2px 8px !important;
            transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
        }
        
        div[class*="st-key-nm_"] button:hover {
            background-color: rgba(128, 128, 128, 0.14) !important;
            background: rgba(128, 128, 128, 0.14) !important;
            border-color: rgba(128, 128, 128, 0.22) !important;
        }
        
        div[class*="st-key-nm_"] button:focus,
        div[class*="st-key-nm_"] button:active,
        div[class*="st-key-nm_"] button:focus-visible {
            outline: none !important;
            box-shadow: none !important;
            border: 1px solid rgba(128, 128, 128, 0.2) !important;
        }
        
        /* Стиль выделенной папки */
        div[class*="st-key-nm_"] button[data-testid="baseButton-primary"] {
            background-color: rgba(30, 58, 138, 0.3) !important;
            background: rgba(30, 58, 138, 0.3) !important;
            color: white !important;
            font-weight: 600 !important;
            border: 1px solid rgba(30, 58, 138, 0.5) !important;
        }
    </style>
    """, unsafe_allow_html=True)
    
    with st.container(height=350):
        visible_nodes = get_visible_nodes("Этот компьютер", 0, st.session_state.expanded_paths)
        
        for path, name, depth in visible_nodes:
            if path == "Этот компьютер":
                has_subdirs = True
            else:
                has_subdirs = False
                try:
                    with os.scandir(path) as it:
                        for entry in it:
                            if entry.is_dir() and not entry.name.startswith('.') and not entry.name.startswith('$'):
                                has_subdirs = True
                                break
                except Exception:
                    pass
                
            # Вычисляем динамические пропорции для выравнивания дерева
            tg_ratio = 0.08 + 0.05 * depth
            nm_ratio = 1.0 - tg_ratio
            col_tg, col_nm = st.columns([tg_ratio, nm_ratio])
            
            with col_tg:
                if has_subdirs:
                    is_expanded = path in st.session_state.expanded_paths
                    toggle_char = "▼" if is_expanded else "▶"
                    if st.button(toggle_char, key=f"tg_{path}", width="stretch"):
                        if is_expanded:
                            st.session_state.expanded_paths.remove(path)
                        else:
                            st.session_state.expanded_paths.add(path)
                        st.rerun()
                else:
                    st.write("")
                    
            with col_nm:
                btn_label = name
                if path == "Этот компьютер":
                    if st.button(btn_label, key=f"nm_{path}", width="stretch"):
                        is_expanded = path in st.session_state.expanded_paths
                        if is_expanded:
                            st.session_state.expanded_paths.remove(path)
                        else:
                            st.session_state.expanded_paths.add(path)
                        st.rerun()
                else:
                    is_selected = path == selected_path
                    btn_type = "primary" if is_selected else "secondary"
                    if st.button(btn_label, key=f"nm_{path}", type=btn_type, width="stretch"):
                        st.session_state.selected_path = path
                        st.rerun()
                    
    st.markdown("---")
    col_ok, col_cn = st.columns(2)
    with col_ok:
        if st.button("ОК", type="primary", width="stretch", key="dlg_ok_btn"):
            st.session_state.custom_save_path = st.session_state.get("selected_path", st.session_state.custom_save_path)
            st.session_state.show_folder_picker = False
            st.rerun()
    with col_cn:
        if st.button("Отмена", width="stretch", key="dlg_cn_btn"):
            st.session_state.show_folder_picker = False
            st.rerun()



st.set_page_config(
    page_title="Помощник по обращениям граждан",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stApp {
        background:
            radial-gradient(circle at 18% 0%, rgba(43, 94, 161, 0.32), transparent 34%),
            radial-gradient(circle at 86% 18%, rgba(71, 144, 128, 0.22), transparent 30%),
            linear-gradient(180deg, #08172F 0%, #0D2B42 48%, #123A3B 100%);
    }

    header[data-testid="stHeader"] {
        display: none !important;
    }

    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    #MainMenu,
    footer {
        display: none !important;
    }

    [data-testid="stMainBlockContainer"] {
        max-width: min(96vw, 1680px) !important;
        width: 96vw !important;
        padding: 2.2rem 2.4rem 3.2rem 2.4rem !important;
    }

    .block-container {
        max-width: min(96vw, 1680px) !important;
        width: 96vw !important;
    }

    section.main > div {
        max-width: none !important;
    }

    [data-testid="stSidebar"] {
        background: rgba(7, 22, 43, 0.94);
        border-right: 1px solid rgba(178, 222, 211, 0.16);
    }

    html, body, [class*="css"] {
        font-family: Segoe UI, Arial, sans-serif;
        color: #EAF6F2;
    }

    .stApp,
    .stApp p,
    .stApp span,
    .stApp label,
    .stApp h1,
    .stApp h2,
    .stApp h3,
    .stApp h4,
    .stApp h5,
    .stApp h6,
    [data-testid="stMarkdownContainer"],
    [data-testid="stMarkdownContainer"] *,
    [data-testid="stWidgetLabel"],
    [data-testid="stWidgetLabel"] *,
    [data-testid="stSidebar"],
    [data-testid="stSidebar"] *,
    [data-testid="stTabs"] button,
    [data-testid="stTabs"] button * {
        color: #EAF6F2 !important;
    }

    [data-testid="stSidebar"] input,
    [data-testid="stTextInput"] input {
        color: #EAF6F2 !important;
        background: rgba(5, 16, 31, 0.62) !important;
        border: 1px solid rgba(178, 222, 211, 0.22) !important;
    }

    [data-testid="stFileUploaderDropzone"] {
        background: rgba(6, 20, 38, 0.66) !important;
        border: 1px dashed rgba(178, 222, 211, 0.34) !important;
        border-radius: 8px !important;
    }

    [data-testid="stFileUploaderDropzone"] * {
        color: #D8EFEA !important;
    }

    [data-testid="stFileUploaderDropzone"] button,
    button[kind="secondary"],
    button[kind="primary"] {
        border-radius: 8px !important;
    }

    [data-testid="stFileUploaderDropzone"] button {
        background: #1D6F73 !important;
        color: #FFFFFF !important;
        border: 1px solid #2B8C8C !important;
    }

    [data-testid="stFileUploaderDropzone"] button * {
        color: #FFFFFF !important;
    }

    [data-testid="stAlert"] *,
    [data-testid="stExpander"] *,
    [data-testid="stDataFrame"] * {
        color: inherit;
    }

    [data-testid="stAlert"] {
        background-color: rgba(9, 32, 56, 0.78) !important;
        border: 1px solid rgba(178, 222, 211, 0.18) !important;
        color: #EAF6F2 !important;
    }

    [data-testid="stTabs"] button {
        background: transparent !important;
        color: #B8D8D3 !important;
    }

    [data-testid="stTabs"] button[aria-selected="true"] {
        color: #8BE0D0 !important;
    }

    [data-testid="stExpander"] {
        background: rgba(9, 32, 56, 0.7) !important;
        border: 1px solid rgba(178, 222, 211, 0.18) !important;
        border-radius: 8px !important;
    }

    div[data-testid="stDataFrame"] {
        background: rgba(9, 32, 56, 0.72) !important;
        border-radius: 8px;
    }

    button[kind="primary"] {
        background: #1D6F73 !important;
        border: 1px solid #2B8C8C !important;
        color: #FFFFFF !important;
    }

    button[kind="primary"] * {
        color: #FFFFFF !important;
    }

    button[kind="secondary"] {
        background: rgba(13, 47, 74, 0.82) !important;
        border: 1px solid rgba(178, 222, 211, 0.24) !important;
        color: #EAF6F2 !important;
    }
    
    .main-title {
        font-size: clamp(2.2rem, 2.5vw, 3.2rem);
        font-weight: 800;
        color: #F3FBF8;
        letter-spacing: 0;
        margin-bottom: 0.35rem;
    }
    
    .subtitle {
        font-size: clamp(1.05rem, 1vw, 1.28rem);
        color: #B8D8D3;
        margin-bottom: 1.25rem;
        max-width: 1120px;
    }

    .quick-steps {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 1.15rem;
        margin: 1.35rem 0 1.55rem 0;
    }

    .quick-step {
        background: rgba(9, 32, 56, 0.68);
        border: 1px solid rgba(178, 222, 211, 0.16);
        border-radius: 8px;
        padding: 1.15rem 1.25rem;
        min-height: 112px;
        color: #D8EFEA;
        backdrop-filter: blur(10px);
    }

    .quick-step strong {
        display: block;
        color: #F3FBF8;
        font-size: 1.08rem;
        margin-bottom: 0.35rem;
    }

    .soft-note {
        background: rgba(9, 32, 56, 0.68);
        border: 1px solid rgba(178, 222, 211, 0.16);
        border-left: 4px solid #8BE0D0;
        border-radius: 8px;
        padding: 1.05rem 1.25rem;
        margin: 1rem 0 1.25rem 0;
        color: #D8EFEA;
    }
    
    .metric-container {
        background-color: rgba(9, 32, 56, 0.7);
        border: 1px solid rgba(178, 222, 211, 0.16);
        border-radius: 8px;
        padding: 1.25rem;
        min-height: 112px;
        text-align: center;
        backdrop-filter: blur(10px);
    }
    
    .metric-val {
        font-size: clamp(1.9rem, 2vw, 2.6rem);
        font-weight: 700;
        color: #F3FBF8;
    }
    
    .metric-lbl {
        font-size: 0.95rem;
        color: #A9CDC7;
        text-transform: none;
        letter-spacing: 0;
        margin-top: 0.25rem;
    }

    div[data-testid="stTabs"] button {
        font-size: 1.02rem !important;
        padding: 0.65rem 1.1rem !important;
    }

    div[data-testid="stDataFrame"] {
        font-size: 0.98rem !important;
    }

    .ai-summary-box {
        background: rgba(29, 111, 115, 0.12);
        border: 1px solid rgba(139, 224, 208, 0.3);
        border-left: 4px solid #8BE0D0;
        border-radius: 8px;
        padding: 1.15rem 1.35rem;
        margin: 1rem 0;
        color: #EAF6F2;
        font-size: 1.05rem;
        line-height: 1.6;
    }

    @media (max-width: 900px) {
        .quick-steps {
            grid-template-columns: 1fr;
        }
    }
</style>
""", unsafe_allow_html=True)

if "result_df" not in st.session_state:
    st.session_state.result_df = None
if "processed_files" not in st.session_state:
    st.session_state.processed_files = {}
if "elapsed_time" not in st.session_state:
    st.session_state.elapsed_time = 0.0
if "custom_save_path" not in st.session_state:
    st.session_state.custom_save_path = os.getcwd()
if "show_folder_picker" not in st.session_state:
    st.session_state.show_folder_picker = False
if "browse_dir" not in st.session_state:
    st.session_state.browse_dir = os.getcwd()
if "processing_error" not in st.session_state:
    st.session_state.processing_error = None
if "ai_results" not in st.session_state:
    st.session_state.ai_results = {}
if "selected_file" not in st.session_state:
    st.session_state.selected_file = "Все файлы"

if st.session_state.show_folder_picker:
    folder_picker_dialog()



st.markdown('<div class="main-title">Помощник по обращениям граждан</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Загрузите Excel-файл, а система найдет важные проблемы и подготовит готовый отчет</div>', unsafe_allow_html=True)
st.markdown("""
<div class="quick-steps">
    <div class="quick-step"><strong>1. Выберите файл</strong>Подойдет Excel в формате .xlsx.</div>
    <div class="quick-step"><strong>2. Нажмите кнопку</strong>Программа сама разберет обращения.</div>
    <div class="quick-step"><strong>3. Скачайте отчет</strong>Готовый Excel появится на вкладке «Отчет».</div>
</div>
""", unsafe_allow_html=True)

st.sidebar.header("Готовые отчеты")
st.sidebar.caption("Обычно здесь ничего менять не нужно.")



st.sidebar.markdown("**Куда сохранить**")
default_path_check = st.sidebar.checkbox(
    "Сохранить рядом с программой", 
    value=True,
    help="Самый простой вариант: готовые отчеты появятся в папке программы."
)

if default_path_check:
    save_dir = os.getcwd()
    st.sidebar.text_input("Папка для отчетов:", value=save_dir, disabled=True)
else:
    st.sidebar.markdown("Выберите папку для отчетов:")
    col_path, col_browse = st.sidebar.columns([2.5, 1.5])
    with col_path:
        save_dir_input = st.text_input(
            "Папка", 
            value=st.session_state.custom_save_path,
            label_visibility="collapsed",
            help="Можно вставить полный путь к папке, куда сохранить готовые отчеты."
        )
    with col_browse:
        if st.button("Обзор", width="stretch"):
            st.session_state.show_folder_picker = True
            st.session_state.browse_dir = os.path.abspath(st.session_state.custom_save_path)
            st.rerun()
                
    st.session_state.custom_save_path = save_dir_input
    save_dir = save_dir_input
    
    if not os.path.exists(save_dir) and save_dir.strip() != "":
        st.sidebar.warning("Такой папки пока нет. Программа попробует создать ее сама.")

destination_path = os.path.abspath(os.path.join(save_dir, "Обработанные файлы"))
st.sidebar.markdown(f"""
<div style="
    border: 1px solid rgba(128, 128, 128, 0.25);
    border-radius: 8px;
    padding: 0.85rem;
    margin-top: 1rem;
    margin-bottom: 1rem;
">
    <div style="font-size: 0.75rem; color: #888888; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.35rem;">
        Готовые отчеты будут здесь:
    </div>
    <div style="font-size: 0.85rem; font-weight: 500; color: inherit; word-break: break-all; line-height: 1.4;">
        {destination_path}
    </div>
</div>
""", unsafe_allow_html=True)

# Быстрый режим для больших файлов: Ollama используется как аналитический слой
# для контекста и итоговых объяснений, но НЕ вызывается на каждую строку.
# Иначе 400k строк будут обрабатываться часы/сутки, а не минуты.
use_llm = True
ollama_url = "http://localhost:11434/api/generate"

selected_file = st.session_state.get("selected_file", "Все файлы")

def get_active_stats_and_preview(selected_file):
    if not st.session_state.processed_files:
        return None, None
        
    if selected_file == "Все файлы":
        files_list = list(st.session_state.processed_files.values())
        combined_preview = pd.concat([f["preview_df"].head(100) for f in files_list], ignore_index=True).head(1000)
        
        combined_stats = {
            "total_count": sum(f["stats"]["total_count"] for f in files_list),
            "problems_count": sum(f["stats"]["problems_count"] for f in files_list),
            "category_counts": {},
            "rank_counts": {},
            "district_counts": {},
            "district_stats": {}
        }
        
        for f in files_list:
            s = f["stats"]
            for cat, val in s.get("category_counts", {}).items():
                combined_stats["category_counts"][cat] = combined_stats["category_counts"].get(cat, 0) + val
            for r, val in s.get("rank_counts", {}).items():
                combined_stats["rank_counts"][r] = combined_stats["rank_counts"].get(r, 0) + val
            for dist, val in s.get("district_counts", {}).items():
                combined_stats["district_counts"][dist] = combined_stats["district_counts"].get(dist, 0) + val
                
            d_stats = s.get("district_stats", {})
            for dist, d_data in d_stats.items():
                if dist not in combined_stats["district_stats"]:
                    combined_stats["district_stats"][dist] = {
                        "count": 0,
                        "rank_sum": 0.0,
                        "rank_count": 0,
                        "critical_count": 0,
                        "categories": {},
                        "summaries": []
                    }
                m_stats = combined_stats["district_stats"][dist]
                m_stats["count"] += d_data.get("count", 0)
                m_stats["rank_sum"] += d_data.get("rank_sum", 0.0)
                m_stats["rank_count"] += d_data.get("rank_count", 0)
                m_stats["critical_count"] += d_data.get("critical_count", 0)
                
                for cat, val in d_data.get("categories", {}).items():
                    m_stats["categories"][cat] = m_stats["categories"].get(cat, 0) + val
                    
                for summ in d_data.get("summaries", []):
                    if len(m_stats["summaries"]) < 3 and summ not in m_stats["summaries"]:
                        m_stats["summaries"].append(summ)
                        
        sorted_districts = sorted(combined_stats["district_stats"].items(), key=lambda x: x[1]["count"], reverse=True)
        
        top3_districts = []
        for district, d_data in sorted_districts[:3]:
            sorted_cats = sorted(d_data["categories"].items(), key=lambda x: x[1], reverse=True)
            top_cat = sorted_cats[0][0] if sorted_cats else "Другое"
            avg_rank = d_data["rank_sum"] / d_data["rank_count"] if d_data["rank_count"] > 0 else 0
            key_problems = "; ".join(d_data["summaries"])
            
            top3_districts.append({
                "district": district,
                "count": d_data["count"],
                "top_cat": top_cat,
                "avg_rank": avg_rank,
                "critical_count": d_data["critical_count"],
                "key_problems": key_problems
            })
            
        top10_districts = []
        for district, d_data in sorted_districts[:10]:
            sorted_cats = sorted(d_data["categories"].items(), key=lambda x: x[1], reverse=True)
            top_cat = sorted_cats[0][0] if sorted_cats else "Другое"
            avg_rank = d_data["rank_sum"] / d_data["rank_count"] if d_data["rank_count"] > 0 else 0
            key_problems = "; ".join(d_data["summaries"])
            
            top10_districts.append({
                "district": district,
                "count": d_data["count"],
                "top_cat": top_cat,
                "avg_rank": avg_rank,
                "critical_count": d_data["critical_count"],
                "key_problems": key_problems
            })
            
        combined_stats["top3_districts"] = top3_districts
        combined_stats["top10_districts"] = top10_districts
        
        return combined_stats, combined_preview
    else:
        f_data = st.session_state.processed_files.get(selected_file)
        if f_data:
            return f_data["stats"], f_data["preview_df"]
        return None, None


tab_upload, tab_analytics, tab_preview = st.tabs([
    "1. Файл",
    "2. Итоги",
    "3. Отчет"
])

with tab_upload:
    st.subheader("Выберите файл")
    st.write(
        "Загрузите таблицу Excel с обращениями. Программа сама найдет проблемы, районы и степень срочности."
    )
    
    st.markdown(
        '<div class="soft-note">Можно загружать файлы до 5 ГБ. Для очень больших таблиц может понадобиться много оперативной памяти, поэтому обработка может занять время.</div>',
        unsafe_allow_html=True
    )

    show_processing_error(st.session_state.processing_error)

    uploaded_files = st.file_uploader(
        "Нажмите, чтобы выбрать Excel-файл",
        type=["xlsx"],
        accept_multiple_files=True,
    ) or []
    
    local_xlsx_files = []
    try:
        local_xlsx_files = [f for f in os.listdir(os.getcwd()) if f.endswith('.xlsx') and not f.startswith('~$') and not f.startswith('temp_')]
        local_xlsx_files.sort()
    except Exception:
        pass
    
    selected_local_files = []
    local_files_to_process = []
    
    with st.expander("Дополнительно: выбрать файл из папки программы"):
        custom_file_path = st.text_input("Путь к файлу, если он уже лежит на компьютере:")
        if local_xlsx_files:
            selected_local_files = st.multiselect(
                "Файлы, найденные рядом с программой:",
                options=local_xlsx_files,
                default=[f for f in local_xlsx_files if "prod" in f or "real" in f] or ([local_xlsx_files[0]] if local_xlsx_files else [])
            )
        else:
            st.caption("Рядом с программой пока нет Excel-файлов.")

        if custom_file_path:
            cleaned_path = custom_file_path.strip().strip('"').strip("'")
            if os.path.exists(cleaned_path) and cleaned_path.endswith('.xlsx'):
                if cleaned_path not in selected_local_files:
                    selected_local_files.append(cleaned_path)
            elif cleaned_path:
                st.error("Не получилось найти файл. Проверьте, что это Excel-файл .xlsx.")
    
        if selected_local_files:
            st.success(f"Выбрано из папки программы: {len(selected_local_files)}")
            for f in selected_local_files:
                if os.path.isabs(f):
                    local_files_to_process.append({"name": os.path.basename(f), "path": f})
                else:
                    local_files_to_process.append({"name": f, "path": os.path.abspath(f)})
    
    has_files = len(uploaded_files) > 0 or len(local_files_to_process) > 0

    if has_files:
        # ── Блок "Готово к обработке" ─────────────────────────────────────────
        all_file_infos = []
        total_bytes = 0

        for uf in uploaded_files:
            size_bytes = uf.size if hasattr(uf, "size") else 0
            total_bytes += size_bytes
            all_file_infos.append({"name": uf.name, "bytes": size_bytes, "source": "upload"})

        for lf in local_files_to_process:
            try:
                size_bytes = os.path.getsize(lf["path"])
            except Exception:
                size_bytes = 0
            total_bytes += size_bytes
            all_file_infos.append({"name": lf["name"], "bytes": size_bytes, "source": "local"})

        # Оценка времени: ~1 MB ≈ 1 000 строк, скорость ≈ 6 000 строк/сек
        total_mb = total_bytes / 1_048_576
        est_rows = int(total_mb * 1000)
        est_sec_min = max(1, int(est_rows / 10_000)) + 45   # оптимистично + буфер
        est_sec_max = max(2, int(est_rows / 4_000)) + 45    # консервативно + буфер

        if est_sec_max >= 120:
            time_str = f"~{est_sec_min // 60}–{est_sec_max // 60} мин"
        elif est_sec_max >= 60:
            time_str = f"~{est_sec_min}–{est_sec_max} сек (около минуты)"
        else:
            time_str = f"~{est_sec_min}–{est_sec_max} сек"

        n = len(all_file_infos)
        files_word = "файл" if n == 1 else ("файла" if n in (2, 3, 4) else "файлов")

        # Рисуем карточку
        file_rows_html = ""
        for fi in all_file_infos:
            mb = fi["bytes"] / 1_048_576
            icon = "📤" if fi["source"] == "upload" else "📁"
            mb_str = f"{mb:.1f} МБ" if mb >= 0.1 else "< 0.1 МБ"
            file_rows_html += (
                f'<div style="display:flex; justify-content:space-between; '
                f'align-items:center; padding:6px 0; '
                f'border-bottom:1px solid rgba(128,128,128,0.12); font-size:0.92rem;">'
                f'<span>{icon} {fi["name"]}</span>'
                f'<span style="color:rgba(160,160,160,0.85); white-space:nowrap; margin-left:12px;">{mb_str}</span>'
                f'</div>'
            )

        st.markdown(f"""
<div style="
    border: 1px solid rgba(99, 179, 237, 0.35);
    border-radius: 10px;
    padding: 14px 18px 10px 18px;
    margin: 14px 0 10px 0;
    background: rgba(99, 179, 237, 0.05);
">
    <div style="font-size:0.85rem; font-weight:600; color:rgba(99,179,237,0.9);
                text-transform:uppercase; letter-spacing:0.04em; margin-bottom:10px;">
        ✅ Готово к обработке: {n} {files_word}
    </div>
    {file_rows_html}
    <div style="margin-top:10px; font-size:0.88rem; color:rgba(160,160,160,0.9);">
        💾 Итого: <b>{total_mb:.1f} МБ</b> &nbsp;·&nbsp;
        ⏱ Примерное время: <b>{time_str}</b>
        <span style="font-size:0.78rem; color:rgba(128,128,128,0.7);">
            &nbsp;(оценка по размеру, зависит от ПК)
        </span>
    </div>
</div>
""", unsafe_allow_html=True)

        if st.button("Сделать отчет", type="primary"):

            st.session_state.processed_files = {}
            st.session_state.result_df = None
            st.session_state.processing_error = None
            st.session_state.ai_results = {}
            processed_dir = os.path.join(save_dir, "Обработанные файлы")
            try:
                os.makedirs(processed_dir, exist_ok=True)
            except Exception as e:
                remember_processing_error(friendly_error_message(e))
                show_processing_error(st.session_state.processing_error)
                st.stop()
                
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            status_text.text("Подготовка распознавания обращений...")
            classifier = RequestClassifier()
            
            files_queue = []
            try:
                for uploaded_file in uploaded_files:
                    temp_input_path = os.path.join(processed_dir, f"temp_in_{uploaded_file.name}")
                    with open(temp_input_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    files_queue.append({
                        "name": uploaded_file.name,
                        "input_path": temp_input_path,
                        "output_path": unique_output_path(processed_dir, uploaded_file.name),
                        "is_temp": True
                    })
                for f_info in local_files_to_process:
                    files_queue.append({
                        "name": f_info["name"],
                        "input_path": f_info["path"],
                        "output_path": unique_output_path(processed_dir, f_info["name"]),
                        "is_temp": False
                    })
            except Exception as e:
                remember_processing_error(friendly_error_message(e))
                show_processing_error(st.session_state.processing_error)
                st.stop()

            ollama_context = ""
            if use_llm and files_queue:
                status_text.text("Ollama-центр изучает исходный файл...")
                ollama_context, _ollama_warn = build_ollama_source_context(files_queue[0]["input_path"], ollama_url)
                # Предупреждение об Ollama не показываем — таймаут нормален, fallback работает автоматически
            
            if files_queue:
                status_text.text("Настройка распознавания по первому файлу...")
                try:
                    first_file = files_queue[0]["input_path"]
                    try:
                        header_df = pd.read_excel(first_file, nrows=1, engine="calamine")
                    except Exception:
                        header_df = pd.read_excel(first_file, nrows=1)
                    col_text_idx = find_column_index(header_df, "text", 36)
                    col_text_name = header_df.columns[col_text_idx]
                    
                    target_col = None
                    if "CLASS_LABEL" in header_df.columns:
                        target_col = "CLASS_LABEL"
                    elif "Тип инцидента" in header_df.columns:
                        target_col = "Тип инцидента"
                        
                    if target_col:
                        try:
                            temp_df = pd.read_excel(first_file, usecols=[col_text_name, target_col], nrows=20000, engine="calamine")
                        except Exception:
                            temp_df = pd.read_excel(first_file, usecols=[col_text_name, target_col], nrows=20000)
                        texts = temp_df[col_text_name].fillna("").astype(str).tolist()
                        
                        if target_col == "Тип инцидента":
                            labels = ["Проблема" if x == "Решаемый" else "Не проблема" for x in temp_df[target_col]]
                        else:
                            labels = temp_df[target_col].fillna("Проблема").tolist()
                            
                        classifier.train(texts, labels)
                    else:
                        st.info("В исходном файле нет ручной разметки для обучения распознавания. Продолжаю по встроенным правилам.")
                except Exception as e:
                    st.warning(f"Не удалось дополнительно настроить распознавание: {e}. Программа продолжит работу по встроенным правилам.")
            
            progress_bar.progress(10)
            
            start_time = time.time()
            all_dfs = []
            processed_file_names = []
            current_file_name = None
            
            # Очищаем кэш и сессию для новых файлов заранее
            st.session_state.ai_results = {}
            AI_RESULTS_CACHE.clear()
            
            try:
                for idx, f_item in enumerate(files_queue):
                    name = f_item["name"]
                    current_file_name = name
                    input_path = f_item["input_path"]
                    output_path = f_item["output_path"]
                    
                    def streamlit_progress_callback(current, total):
                        percent = int((current / total) * 80) + 10
                        progress_bar.progress(percent)
                        status_text.text(
                            f"Файл {idx+1}/{len(files_queue)} ({name}): "
                            f"обработано {current} из {total} важных обращений ({percent}%)..."
                        )
                    
                    stats, file_df = run_pipeline(
                        input_path, 
                        output_path, 
                        use_llm=use_llm, 
                        ollama_url=ollama_url, 
                        progress_callback=streamlit_progress_callback,
                        classifier=classifier,
                        ollama_context=ollama_context
                    )
                    
                    file_data = {
                        "stats": stats,
                        "preview_df": file_df,
                        "output_path": output_path,
                    }
                    processed_file_names.append((name, file_data))
                    
                    # Запускаем фоновую генерацию ИИ-отчетов для этого конкретного файла сразу же!
                    AI_RESULTS_CACHE[name] = {"status": "generating"}
                    t = threading.Thread(
                        target=run_background_ai,
                        args=(stats, name, ollama_url)
                    )
                    t.daemon = True
                    t.start()
                    
                    if f_item["is_temp"] and os.path.exists(input_path):
                        os.remove(input_path)
                
                elapsed = time.time() - start_time
                progress_bar.progress(100)
                status_text.text("Готово. Все выбранные файлы обработаны.")
                
                processed_files = {}
                for name, data in processed_file_names:
                    processed_files[name] = data
                st.session_state.processed_files = processed_files
                
                preview_list = [f["preview_df"].head(100) for f in processed_files.values()]
                st.session_state.result_df = pd.concat(preview_list, ignore_index=True) if preview_list else None
                st.session_state.elapsed_time = elapsed
                
                status_text.text("Готово. Все выбранные файлы обработаны. ИИ-аналитика генерируется в фоновом режиме.")
                
                st.success(
                    f"Отчет готов за {elapsed:.2f} сек. "
                    f"Файлы сохранены здесь: {processed_dir}."
                )
                    
            except Exception as e:
                remember_processing_error(friendly_error_message(e), current_file_name if "current_file_name" in locals() else None)
                status_text.error("Обработка остановлена из-за ошибки. Подробности показаны ниже.")
                show_processing_error(st.session_state.processing_error)
                for f_item in files_queue:
                    try:
                        if f_item["is_temp"] and os.path.exists(f_item["input_path"]):
                            os.remove(f_item["input_path"])
                    except Exception:
                        pass
    else:
        st.info("Выберите Excel-файл, чтобы начать.")


with tab_analytics:

    if st.session_state.result_df is not None:
        if st.session_state.processed_files:
            file_options = list(st.session_state.processed_files.keys())
            if st.session_state.selected_file not in file_options:
                st.session_state.selected_file = file_options[0] if file_options else ""
                
            def on_file_change_analytics():
                st.session_state.selected_file = st.session_state.analytics_file_selector
                
            st.selectbox(
                "📂 Выберите файл для просмотра статистики и сводки:",
                options=file_options,
                index=file_options.index(st.session_state.selected_file) if st.session_state.selected_file in file_options else 0,
                key="analytics_file_selector",
                on_change=on_file_change_analytics
            )
            selected_file = st.session_state.selected_file

        stats, preview_df = get_active_stats_and_preview(selected_file)
    
        if stats is not None:
            # ИИ Сводка
            # Синхронизируем готовые результаты из глобального кэша в session_state
            ai_cache = AI_RESULTS_CACHE
            for k, v in ai_cache.items():
                if v.get("status") == "ready" and k not in st.session_state.ai_results:
                    st.session_state.ai_results[k] = {
                        "ai_summary": v.get("ai_summary"),
                        "ai_doc_docx": v.get("ai_doc_docx"),
                        "ai_doc_pdf": v.get("ai_doc_pdf")
                    }

            ai_data = st.session_state.ai_results.get(selected_file)
            ai_summary = ai_data.get("ai_summary", "") if ai_data else ""
            
            st.session_state.need_rerun_analytics = False
            
            if not ai_summary:
                cache_entry = ai_cache.get(selected_file, {})
                cache_status = cache_entry.get("status")
                if cache_status == "generating":
                    st.info("🤖 Аналитическая сводка от ИИ создается в фоновом режиме, пожалуйста, подождите...")
                    st.session_state.need_rerun_analytics = True
                elif cache_status == "error":
                    st.error("🤖 Не удалось создать аналитическую сводку от ИИ.")
                    with st.expander("Показать подробности ошибки"):
                        st.code(cache_entry.get("error", "Неизвестная ошибка"))
                elif cache_status == "ready":
                    st.session_state.ai_results[selected_file] = {
                        "ai_summary": cache_entry.get("ai_summary"),
                        "ai_doc_docx": cache_entry.get("ai_doc_docx"),
                        "ai_doc_pdf": cache_entry.get("ai_doc_pdf")
                    }
                    st.session_state.need_rerun_analytics = True
                else:
                    # Запускаем фоновую генерацию
                    ai_cache[selected_file] = {"status": "generating"}
                    t = threading.Thread(
                        target=run_background_ai,
                        args=(stats, selected_file, ollama_url)
                    )
                    t.daemon = True
                    t.start()
                    st.info("🤖 Аналитическая сводка от ИИ создается в фоновом режиме, пожалуйста, подождите...")
                    st.session_state.need_rerun_analytics = True
            else:
                st.markdown("##### 🤖 Аналитическая сводка от ИИ")
                formatted_summary = ai_summary.replace("\n\n", "<br><br>").replace("\n", "<br>")
                st.markdown(f'<div class="ai-summary-box">{formatted_summary}</div>', unsafe_allow_html=True)
                st.markdown("<br>", unsafe_allow_html=True)

            kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        
            with kpi1:
                st.markdown(
                    f'<div class="metric-container"><div class="metric-val">{stats["total_count"]}</div>'
                    f'<div class="metric-lbl">Всего обращений</div></div>', 
                    unsafe_allow_html=True
                )
            with kpi2:
                st.markdown(
                    f'<div class="metric-container"><div class="metric-val">{stats["problems_count"]}</div>'
                    f'<div class="metric-lbl">Найдено проблем</div></div>', 
                    unsafe_allow_html=True
                )
            with kpi3:
                spam_count = stats["total_count"] - stats["problems_count"]
                st.markdown(
                    f'<div class="metric-container"><div class="metric-val">{spam_count}</div>'
                    f'<div class="metric-lbl">Не требует решения</div></div>', 
                    unsafe_allow_html=True
                )
            with kpi4:
                st.markdown(
                    f'<div class="metric-container"><div class="metric-val">{st.session_state.elapsed_time:.1f}с</div>'
                    f'<div class="metric-lbl">Время обработки</div></div>', 
                    unsafe_allow_html=True
                )
            
            st.markdown("<br>", unsafe_allow_html=True)
        
            if stats["problems_count"] > 0:
                st.markdown("##### Где больше всего проблем")
            
                cols_top3 = st.columns(min(3, len(stats["top3_districts"])))
                labels = ["1-е место", "2-е место", "3-е место"]
                colors = ["transparent", "transparent", "transparent"]
                border_colors = ["rgba(128, 128, 128, 0.25)", "rgba(128, 128, 128, 0.25)", "rgba(128, 128, 128, 0.25)"]
                text_colors = ["inherit", "inherit", "inherit"]
            
                for idx, row in enumerate(stats["top3_districts"]):
                    if idx >= len(cols_top3):
                        break
                    with cols_top3[idx]:
                        district_name = row["district"].replace(" р-н", "").replace(" рн", "").replace(" район", "").replace(" немецкий национальный", "").replace(" г. Омск", "Омск").replace("г. Омск", "Омск")
                        st.markdown(f"""
                        <div style="
                            background-color: {colors[idx]};
                            border: 1px solid {border_colors[idx]};
                            border-radius: 8px;
                            padding: 0.85rem;
                            text-align: center;
                            margin-bottom: 1rem;
                        ">
                            <div style="font-size: 0.8rem; font-weight: bold; color: {text_colors[idx]}; text-transform: uppercase;">
                                {labels[idx]}
                            </div>
                            <div style="font-size: 1.25rem; font-weight: bold; color: inherit; margin-top: 0.2rem; margin-bottom: 0.2rem;">
                                {district_name}
                            </div>
                            <div style="font-size: 0.85rem; color: inherit; margin-bottom: 0.5rem;">
                                Обращений с проблемой: <b>{row['count']}</b>
                            </div>
                            <div style="font-size: 0.95rem; font-style: italic; color: inherit; border-top: 1px solid rgba(128,128,128,0.15); padding-top: 0.5rem; text-align: left; line-height: 1.4;">
                                <b>Коротко:</b><br>
                                {row['key_problems'] or 'Подробности будут в готовом Excel-отчете.'}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
            
                st.markdown("<br>", unsafe_allow_html=True)
            
                col_charts_1, col_charts_2 = st.columns([1.25, 1])
            
                with col_charts_1:
                    st.markdown("##### Районы по числу проблем")
                
                    chart_data = []
                    for item in stats["top10_districts"]:
                        district_name = item["district"].replace(" р-н", "").replace(" рн", "").replace(" район", "").replace(" немецкий национальный", "").replace(" г. Омск", "Омск").replace("г. Омск", "Омск")
                        chart_data.append({"Район": district_name, "Количество": item["count"]})
                    chart_df = pd.DataFrame(chart_data)
                
                    st.vega_lite_chart(
                        chart_df,
                        {
                            "mark": {"type": "bar", "color": "#1E3A8A"},
                            "encoding": {
                                "x": {
                                    "field": "Район", 
                                    "type": "nominal", 
                                    "axis": {"labelAngle": 0, "labelOverlap": "hide"},
                                    "title": "Район",
                                    "sort": "-y"
                                },
                                "y": {
                                    "field": "Количество", 
                                    "type": "quantitative",
                                    "title": "Количество"
                                }
                            },
                            "width": "container",
                            "height": 460
                        },
                        use_container_width=True
                    )
                
                with col_charts_2:
                    st.markdown("##### Какие темы встречаются чаще")
                
                    cat_data = []
                    for cat, count in stats.get("category_counts", {}).items():
                        cat_data.append({"Категория": cat, "Количество": count})
                
                    if cat_data:
                        cat_df = pd.DataFrame(cat_data).sort_values(by="Количество", ascending=False)
                    else:
                        cat_df = pd.DataFrame(columns=["Категория", "Количество"])
                    
                    st.dataframe(
                        cat_df, 
                        hide_index=True,
                        use_container_width=True
                    )
                
                st.markdown("##### Какие проблемы требуют внимания")
            
                rank_data = []
                rank_desc = {
                    1: "1 - Минимальный (Благодарности, мелкие плановые работы)",
                    2: "2 - Низкий (Типовые недочеты, мелкие ямы, мусор во дворе)",
                    3: "3 - Средний (Транспортные сбои, открытые люки, крупные ямы)",
                    4: "4 - Высокий (Прорыв отопления, замерзаем, отключение света)",
                    5: "5 - Критический (ЧП, пожары, взрывы, угроза жизни)"
                }
                for rank, count in stats.get("rank_counts", {}).items():
                    rank_data.append({
                        "Важность": int(rank),
                        "Описание": rank_desc.get(int(rank), f"{rank}"),
                        "Количество обращений": count
                    })
            
                if rank_data:
                    rank_df = pd.DataFrame(rank_data).sort_values(by="Важность")
                else:
                    rank_df = pd.DataFrame(columns=["Описание", "Количество обращений"])
                
                st.dataframe(
                    rank_df[["Описание", "Количество обращений"]],
                    hide_index=True,
                    use_container_width=True
                )
                
                # 🗺 Карта обращений по Омской области
                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown("##### 🗺 Карта обращений по Омской области")
                
                # Подготовка данных для Pydeck
                map_data = []
                for dist_name, d_data in stats.get("district_stats", {}).items():
                    if dist_name in OMSK_DISTRICTS_COORDS:
                        coords = OMSK_DISTRICTS_COORDS[dist_name]
                        # Игнорируем общие fallback'и на всю область на карте, если они не несут конкретной гео-привязки
                        if dist_name == "Омская область" and len(stats.get("district_stats", {})) > 1:
                            continue
                            
                        # Считаем средний ранг критичности
                        rank_sum = d_data.get("rank_sum", 0.0)
                        rank_count = d_data.get("rank_count", 0)
                        avg_rank = rank_sum / rank_count if rank_count > 0 else 1.0
                        
                        # Интерполяция цвета от зелёного [46, 204, 113] к оранжевому [230, 126, 34] и красному [231, 76, 60]
                        # Нормализуем avg_rank от 1.0 до 5.0 в диапазон 0.0 до 1.0
                        t = (avg_rank - 1.0) / 4.0
                        t = max(0.0, min(1.0, t))
                        
                        if t < 0.5:
                            # Зелёный -> Жёлтый [241, 196, 15]
                            ratio = t / 0.5
                            r = int(46 + (241 - 46) * ratio)
                            g = int(204 + (196 - 204) * ratio)
                            b = int(113 + (15 - 113) * ratio)
                        else:
                            # Жёлтый -> Красный [231, 76, 60]
                            ratio = (t - 0.5) / 0.5
                            r = int(241 + (231 - 241) * ratio)
                            g = int(196 + (76 - 196) * ratio)
                            b = int(15 + (60 - 15) * ratio)
                            
                        # Определим основную категорию
                        sorted_cats = sorted(d_data.get("categories", {}).items(), key=lambda x: x[1], reverse=True)
                        top_cat = sorted_cats[0][0] if sorted_cats else "Другое"
                        
                        map_data.append({
                            "district": dist_name,
                            "lat": coords[0],
                            "lon": coords[1],
                            "count": d_data["count"],
                            "avg_rank": round(avg_rank, 2),
                            "top_category": top_cat,
                            "color_r": r,
                            "color_g": g,
                            "color_b": b
                        })
                
                if map_data:
                    map_df = pd.DataFrame(map_data)
                    
                    # Создание 2D-слоя плоских кругов (ScatterplotLayer) для эффекта "закрашивания" районов
                    layer = pdk.Layer(
                        "ScatterplotLayer",
                        data=map_df,
                        get_position="[lon, lat]",
                        get_radius=20000, # Диаметр ~40 км для покрытия районов
                        get_fill_color="[color_r, color_g, color_b, 120]", # Полупрозрачная заливка
                        get_line_color="[color_r, color_g, color_b, 200]", # Более плотный ободок
                        line_width_min_pixels=1.5,
                        pickable=True,
                        id="districts-layer" # Устанавливаем ID для отслеживания кликов
                    )
                    
                    # Начальная точка обзора - плоский 2D-вид на центр Омской области
                    view_state = pdk.ViewState(
                        latitude=55.2,
                        longitude=73.5,
                        zoom=6,
                        pitch=0, # Плоский 2D вид сверху
                        bearing=0
                    )
                    
                    # Отрисовка с параметрами интерактивного выбора (on_select)
                    map_event = st.pydeck_chart(
                        pdk.Deck(
                            layers=[layer],
                            initial_view_state=view_state,
                            map_style="light", # Светлая тема фоновой карты (Carto Positron)
                            tooltip={
                                "html": """
                                    <div style='font-family: sans-serif; font-size: 0.9rem; padding: 8px; border-radius: 4px; background: #fff; color: #111; border: 1px solid #ccc; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>
                                        <b>{district}</b><br/>
                                        📍 Центр: {lat}, {lon}<br/>
                                        🔥 Всего обращений: <b>{count}</b><br/>
                                        ⚠️ Средняя критичность: <b>{avg_rank}</b>/5.0<br/>
                                        🏷️ Топ тема: {top_category}
                                    </div>
                                """,
                                "style": {"backgroundColor": "transparent", "color": "black", "zIndex": 1000}
                            }
                        ),
                        on_select="rerun",
                        selection_mode="single-object",
                        use_container_width=True
                    )
                    
                    # Легенда
                    st.markdown("""
                    <div style="display: flex; flex-wrap: wrap; gap: 15px; justify-content: center; align-items: center; padding: 10px; border-radius: 6px; background-color: rgba(128,128,128,0.05); font-size: 0.85rem; border: 1px solid rgba(128,128,128,0.1);">
                        <div><b>Легенда критичности районов:</b></div>
                        <div style="display: flex; align-items: center; gap: 5px;">
                            <span style="display: inline-block; width: 12px; height: 12px; background-color: rgb(46, 204, 113); border-radius: 2px;"></span>
                            <span>1.0 - 2.0 (Низкая)</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 5px;">
                            <span style="display: inline-block; width: 12px; height: 12px; background-color: rgb(241, 196, 15); border-radius: 2px;"></span>
                            <span>2.0 - 3.5 (Средняя)</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 5px;">
                            <span style="display: inline-block; width: 12px; height: 12px; background-color: rgb(231, 76, 60); border-radius: 2px;"></span>
                            <span>3.5 - 5.0 (Критическая)</span>
                        </div>
                        <div style="margin-left: 10px; color: rgba(120,120,120,0.9);">
                            * Нажмите на любую область на карте, чтобы открыть её детальную сводку ниже.
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # 🔍 Раздел детальной сводки по выбору района
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown("#### 🔍 Детальный анализ выбранного района")
                    
                    active_districts = sorted([d for d in stats.get("district_stats", {}).keys() if d in OMSK_DISTRICTS_COORDS])
                    if active_districts:
                        # Инициализация состояния выбранного района в сессии
                        if "selected_district_click" not in st.session_state:
                            st.session_state.selected_district_click = active_districts[0]
                            
                        # Отслеживание изменения клика на карте
                        if "last_map_selection" not in st.session_state:
                            st.session_state.last_map_selection = None
                            
                        current_map_selection = None
                        if map_event and "selection" in map_event:
                            selection = map_event["selection"]
                            objects = selection.get("objects", {}).get("districts-layer", [])
                            if objects:
                                current_map_selection = objects[0].get("district")
                                
                        if current_map_selection != st.session_state.last_map_selection:
                            st.session_state.last_map_selection = current_map_selection
                            if current_map_selection and current_map_selection in active_districts:
                                st.session_state.selected_district_click = current_map_selection
                                st.session_state.district_selector_dashboard = current_map_selection
                                
                        # Индекс для селектбокса
                        default_idx = 0
                        if st.session_state.selected_district_click in active_districts:
                            default_idx = active_districts.index(st.session_state.selected_district_click)
                            
                        def on_district_change_dashboard():
                            st.session_state.selected_district_click = st.session_state.district_selector_dashboard
                            
                        selected_dist = st.selectbox(
                            "Выбранный район (можно переключить здесь или нажать на карту выше):",
                            options=active_districts,
                            index=default_idx,
                            key="district_selector_dashboard",
                            on_change=on_district_change_dashboard
                        )
                        
                        d_data = stats["district_stats"][selected_dist]
                        avg_rank = d_data["rank_sum"] / d_data["rank_count"] if d_data["rank_count"] > 0 else 1.0
                        
                        # Отобразим карточку с информацией по району в красивом виде
                        col_stat1, col_stat2, col_stat3 = st.columns(3)
                        with col_stat1:
                            st.markdown(
                                f'<div class="metric-container"><div class="metric-val">{d_data["count"]}</div>'
                                f'<div class="metric-lbl">Всего инцидентов</div></div>', 
                                unsafe_allow_html=True
                            )
                        with col_stat2:
                            st.markdown(
                                f'<div class="metric-container"><div class="metric-val">{avg_rank:.2f}</div>'
                                f'<div class="metric-lbl">Средний ранг критичности</div></div>', 
                                unsafe_allow_html=True
                            )
                        with col_stat3:
                            st.markdown(
                                f'<div class="metric-container"><div class="metric-val">{d_data["critical_count"]}</div>'
                                f'<div class="metric-lbl">Критических жалоб (ранг 4-5)</div></div>', 
                                unsafe_allow_html=True
                            )
                        
                        st.markdown("<br>", unsafe_allow_html=True)
                        
                        # Две колонки: Топ тем и Примеры конкретных жалоб
                        col_left, col_right = st.columns([1, 1.25])
                        
                        with col_left:
                            st.markdown("##### 📊 Проблемные сферы района")
                            sorted_cats = sorted(d_data.get("categories", {}).items(), key=lambda x: x[1], reverse=True)
                            cat_data_dist = []
                            for cat, c_count in sorted_cats[:5]:
                                cat_data_dist.append({"Сфера": cat, "Жалоб": c_count})
                            if cat_data_dist:
                                st.dataframe(pd.DataFrame(cat_data_dist), hide_index=True, use_container_width=True)
                            else:
                                st.caption("Нет данных по темам.")
                                
                            st.write("")
                            st.write("")
                            st.markdown("##### 🤖 ИИ-аналитика района")
                            report_format = st.selectbox(
                                "Формат отчета:",
                                options=["PDF (.pdf)", "Word (.docx)"],
                                key=f"format_{selected_dist}"
                            )
                            
                            is_generating = st.session_state.get(f"is_generating_{selected_dist}", False)
                            
                            if st.button(
                                "Сформировать ИИ-отчет" if not is_generating else "Формирование отчета...",
                                key=f"btn_{selected_dist}",
                                use_container_width=True,
                                disabled=is_generating
                            ):
                                st.session_state[f"is_generating_{selected_dist}"] = True
                                st.rerun()
                                
                            if st.session_state.get(f"is_generating_{selected_dist}", False):
                                with st.spinner("Генерация ИИ-отчета для района (примерное время ожидания: 15-20 секунд)..."):
                                    top_cat = sorted_cats[0][0] if sorted_cats else "Другое"
                                    district_report_stats = {
                                        "total_count": d_data["count"],
                                        "problems_count": d_data["count"],
                                        "category_counts": d_data.get("categories", {}),
                                        "rank_counts": {
                                            "1": 0,
                                            "2": max(0, d_data["count"] - d_data["critical_count"]),
                                            "3": 0,
                                            "4": d_data["critical_count"],
                                            "5": 0
                                        },
                                        "top3_districts": [
                                            {
                                                "district": selected_dist,
                                                "count": d_data["count"],
                                                "top_cat": top_cat,
                                                "avg_rank": avg_rank,
                                                "critical_count": d_data["critical_count"],
                                                "key_problems": "; ".join(d_data.get("summaries", []))
                                            }
                                        ],
                                        "top10_districts": [
                                            {
                                                "district": selected_dist,
                                                "count": d_data["count"],
                                                "top_cat": top_cat,
                                                "avg_rank": avg_rank,
                                                "critical_count": d_data["critical_count"],
                                                "key_problems": "; ".join(d_data.get("summaries", []))
                                            }
                                        ],
                                        "district_counts": {selected_dist: d_data["count"]},
                                        "district_stats": {selected_dist: d_data}
                                    }
                                    
                                    try:
                                        ai_summary = generate_executive_summary(district_report_stats, ollama_url)
                                        doc_filename = f"Район: {selected_dist}"
                                        
                                        if "docx" in report_format.lower():
                                            doc_bytes = generate_docx(district_report_stats, ai_summary, doc_filename, ollama_url)
                                            mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                                            ext = "docx"
                                        else:
                                            doc_bytes = generate_pdf(district_report_stats, ai_summary, doc_filename, ollama_url)
                                            mime_type = "application/pdf"
                                            ext = "pdf"
                                            
                                        if doc_bytes:
                                            st.session_state[f"generated_report_{selected_dist}"] = {
                                                "bytes": doc_bytes,
                                                "ext": ext,
                                                "mime": mime_type
                                            }
                                            st.success("Отчет успешно сформирован!")
                                        else:
                                            st.error("Не удалось сформировать отчет.")
                                    except Exception as e:
                                        st.error(f"Ошибка при формировании отчета: {e}")
                                    finally:
                                        st.session_state[f"is_generating_{selected_dist}"] = False
                                        st.rerun()
                                        
                            # Если отчет сгенерирован для текущего района, показываем кнопку скачивания
                            report_state_key = f"generated_report_{selected_dist}"
                            if report_state_key in st.session_state:
                                rep = st.session_state[report_state_key]
                                st.download_button(
                                    label=f"📥 Скачать {rep['ext'].upper()}-отчет",
                                    data=rep["bytes"],
                                    file_name=f"Отчет_{selected_dist}.{rep['ext']}",
                                    mime=rep["mime"],
                                    use_container_width=True,
                                    key=f"dl_btn_{selected_dist}_{rep['ext']}"
                                )
                                
                        with col_right:
                            st.markdown("##### 💬 Что особенно не нравится жителям:")
                            if d_data.get("summaries"):
                                for idx, s in enumerate(d_data["summaries"]):
                                    # Вычисляем красивый бейдж на основе текста обращения
                                    s_lower = s.lower()
                                    is_urgent = any(kw in s_lower for kw in ["прорыв", "взрыв", "замерзаем", "авария", "нет воды", "нет тепла", "нет отопления", "пожар"])
                                    badge_color = "#E74C3C" if is_urgent else "#E67E22"
                                    badge_text = "🚨 Критический" if is_urgent else "⚠️ Срочный"
                                    
                                    st.markdown(
                                        f'<div style="padding: 12px; margin-bottom: 10px; border-left: 4px solid {badge_color}; '
                                        f'background-color: rgba(128,128,128,0.06); border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">'
                                        f'<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">'
                                        f'<span style="font-size: 0.75rem; font-weight: bold; color: {badge_color}; background-color: {badge_color}1a; padding: 2px 6px; border-radius: 3px;">{badge_text}</span>'
                                        f'<span style="font-size: 0.75rem; color: #888;">Инцидент №{idx+1}</span>'
                                        f'</div>'
                                        f'<div style="font-style: italic; color: inherit; font-size: 0.92rem; line-height: 1.45;">'
                                        f'«{s}»'
                                        f'</div>'
                                        f'</div>',
                                        unsafe_allow_html=True
                                    )
                            else:
                                st.info("Для этого района нет детализированных текстовых жалоб.")
                    else:
                        st.info("Нет детализированных данных по районам.")
            else:
                st.info("В файле не найдено обращений, которые требуют решения.")
    else:
        st.info("Сначала выберите файл и сделайте отчет.")

    # Неблокирующий авторефреш в самом конце вкладки Аналитика
    if st.session_state.get("need_rerun_analytics", False):
        st.session_state.need_rerun_analytics = False
        time.sleep(2)
        st.rerun()



with tab_preview:

    if st.session_state.result_df is not None:
        if st.session_state.processed_files:
            file_options = list(st.session_state.processed_files.keys())
            if st.session_state.selected_file not in file_options:
                st.session_state.selected_file = file_options[0] if file_options else ""
                
            def on_file_change_preview():
                st.session_state.selected_file = st.session_state.preview_file_selector
                
            st.selectbox(
                "📂 Выберите файл для просмотра и скачивания отчетов:",
                options=file_options,
                index=file_options.index(st.session_state.selected_file) if st.session_state.selected_file in file_options else 0,
                key="preview_file_selector",
                on_change=on_file_change_preview
            )
            selected_file = st.session_state.selected_file

        stats, preview_df = get_active_stats_and_preview(selected_file)
    
        if preview_df is not None:
            processed_dir_path = os.path.join(save_dir, "Обработанные файлы")
            st.info(f"Готовые Excel-отчеты сохранены здесь: {processed_dir_path}")
        
            # Кнопки скачивания
            st.markdown("##### Скачать готовый Excel-отчет")
            file_data = st.session_state.processed_files.get(selected_file, {})
            out_path = file_data.get("output_path") or os.path.join(processed_dir_path, f"Обработанные_{selected_file}")
            if os.path.exists(out_path):
                try:
                    with open(out_path, "rb") as f:
                        file_bytes = f.read()
                    col_dl, _ = st.columns([2.5, 7.5])
                    with col_dl:
                        st.download_button(
                            label="🟢 Скачать Excel-отчет",
                            data=file_bytes,
                            file_name=os.path.basename(out_path),
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_single_{selected_file}"
                        )
                except Exception as e:
                    st.error(f"Не удалось подготовить Excel для скачивания ({selected_file}): {friendly_error_message(e)}")
            else:
                st.warning(f"Не нашел готовый отчет для файла: {selected_file}")

            # Кнопки скачивания аналитического документа для руководства
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("##### 📄 Аналитический документ для руководства")
            
            # Синхронизируем готовые результаты из глобального кэша в session_state
            ai_cache = AI_RESULTS_CACHE
            for k, v in ai_cache.items():
                if v.get("status") == "ready" and k not in st.session_state.ai_results:
                    st.session_state.ai_results[k] = {
                        "ai_summary": v.get("ai_summary"),
                        "ai_doc_docx": v.get("ai_doc_docx"),
                        "ai_doc_pdf": v.get("ai_doc_pdf")
                    }

            ai_cache_entry = ai_cache.get(selected_file, {})
            cache_status = ai_cache_entry.get("status")
            
            ai_data = st.session_state.ai_results.get(selected_file)
            ai_docx = ai_data.get("ai_doc_docx") if ai_data else None
            ai_pdf = ai_data.get("ai_doc_pdf") if ai_data else None
            
            st.session_state.need_rerun_preview = False

            if ai_docx and ai_pdf:
                col_doc1, col_doc2, _ = st.columns([1.4, 1.1, 7.5], gap="small")
                with col_doc1:
                    st.download_button(
                        label="📄 Скачать DOCX (Word)",
                        data=ai_docx,
                        file_name=f"Аналитическая_справка_{selected_file.replace('.xlsx', '')}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"dl_docx_{selected_file}"
                    )
                with col_doc2:
                    st.download_button(
                        label="📕 Скачать PDF",
                        data=ai_pdf,
                        file_name=f"Аналитическая_справка_{selected_file.replace('.xlsx', '')}.pdf",
                        mime="application/pdf",
                        key=f"dl_pdf_{selected_file}"
                    )
            elif cache_status == "generating":
                st.info("ℹ️ Аналитические отчеты (Word/PDF) создаются в фоновом режиме. Вы можете свободно просматривать таблицу ниже и скачать Excel-отчет.")
                st.button("🔄 Обновить статус Word/PDF", key=f"refresh_preview_status_{selected_file}")
            elif cache_status == "error":
                st.error("Не удалось сгенерировать аналитические документы.")
                with st.expander("Показать подробности ошибки"):
                    st.code(ai_cache_entry.get("error", "Неизвестная ошибка"))
            elif cache_status == "ready":
                st.session_state.ai_results[selected_file] = {
                    "ai_summary": ai_cache_entry.get("ai_summary"),
                    "ai_doc_docx": ai_cache_entry.get("ai_doc_docx"),
                    "ai_doc_pdf": ai_cache_entry.get("ai_doc_pdf")
                }
                st.session_state.need_rerun_preview = True
            else:
                if stats is not None:
                    # Запускаем фоновую генерацию
                    ai_cache[selected_file] = {"status": "generating"}
                    t = threading.Thread(
                        target=run_background_ai,
                        args=(stats, selected_file, ollama_url)
                    )
                    t.daemon = True
                    t.start()
                    st.info("ℹ️ Аналитические отчеты (Word/PDF) создаются в фоновом режиме. Вы можете свободно просматривать таблицу ниже и скачать Excel-отчет.")
                    st.button("🔄 Обновить статус Word/PDF", key=f"refresh_preview_status_init_{selected_file}")
        
            st.markdown("---")
            col_tbl_title, col_tbl_toggle = st.columns([6, 4])
            with col_tbl_title:
                st.markdown("##### 📊 Просмотр готового отчета")
            with col_tbl_toggle:
                show_all_rows = st.checkbox(
                    "Показать всю таблицу (все строки)",
                    value=False,
                    key=f"show_all_preview_{selected_file}"
                )

            # Показываем только нужные смысловые колонки (без сырого и очищенного текста)
            DISPLAY_COLS = [
                "Нормализованное Гео",
                "Ранг критичности",
                "Краткое саммари",
                "Тип инцидента",
                "Группа тем",      # group
                "Тема",            # topic
                "Муниципалитет",   # municipality
                "Населенный пункт",
                "Дата создания",
                "Дата окончания",
            ]
            df_clean = preview_df.dropna(how='all', axis=0).fillna("")
            # Берём только те колонки из списка, которые реально есть в DataFrame
            show_cols = [c for c in DISPLAY_COLS if c in df_clean.columns]
            # Если ни одной не нашлось — покажем всё что есть кроме мусора
            if not show_cols:
                drop_cols = ["Очищенный текст", "CLASS_LABEL"]
                show_cols = [c for c in df_clean.columns if c not in drop_cols]
            df_clean = df_clean[show_cols]

            def color_ranks(val):
                try:
                    rank = int(val)
                    if rank == 1 or rank == 2:
                        return 'background-color: rgba(46, 204, 113, 0.25);'
                    elif rank == 3:
                        return 'background-color: rgba(241, 196, 15, 0.25);'
                    elif rank == 4:
                        return 'background-color: rgba(230, 126, 34, 0.28);'
                    elif rank == 5:
                        return 'background-color: rgba(231, 76, 60, 0.32);'
                except Exception:
                    pass
                return ''

            df_to_show = df_clean if show_all_rows else df_clean.head(100)

            if "Ранг критичности" in df_clean.columns:
                try:
                    styled_df = df_to_show.style.map(color_ranks, subset=["Ранг критичности"])
                except AttributeError:
                    styled_df = df_to_show.style.applymap(color_ranks, subset=["Ранг критичности"])
            else:
                styled_df = df_to_show

            st.dataframe(
                styled_df,
                use_container_width=True,
                hide_index=True,
                height=850,
                column_config={
                    "Ранг критичности": st.column_config.NumberColumn(
                        "Важность",
                        help="От 1 (не срочно) до 5 (очень срочно)",
                        format="%d"
                    ),
                    "Тип инцидента": st.column_config.TextColumn(
                        "Нужно ли решать",
                        help="Показывает, является ли обращение реальной проблемой."
                    ),
                    "Нормализованное Гео": st.column_config.TextColumn(
                        "Район"
                    ),
                    "Краткое саммари": st.column_config.TextColumn(
                        "Кратко о проблеме"
                    ),
                    "Группа тем": st.column_config.TextColumn("Тема"),
                    "Тема": st.column_config.TextColumn("Подтема"),
                }
            )
        else:
            st.info("Таблица пока недоступна.")
    else:
        st.info("Сначала выберите файл и нажмите «Сделать отчет».")

    # Неблокирующий авторефреш в самом конце вкладки Отчет (Превью)
    if st.session_state.get("need_rerun_preview", False):
        st.session_state.need_rerun_preview = False
        time.sleep(2)
        st.rerun()
