import streamlit as st
import pandas as pd
import os
import time
import traceback
import requests

from src.pipeline import run_pipeline
from src.utils import find_column_index
from src.classifier import RequestClassifier


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
            "Ты - локальный аналитический центр Ollama. Сначала изучи карту исходного Excel, "
            "чтобы потом точнее объяснять районы, темы, спам/благодарности и реальные проблемы. "
            "Сделай короткий рабочий контекст до 1800 символов: какие темы встречаются, какие признаки "
            "отличают реальные проблемы от информационных обращений, какие формулировки важны для анализа. "
            "Не выдумывай внешних фактов.\n\n"
            f"{source_profile}"
        )

        try:
            response = requests.post(
                ollama_url,
                json={
                    "model": "qwen2.5:0.5b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2, "num_ctx": 4096},
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
                    if st.button(toggle_char, key=f"tg_{path}", use_container_width=True):
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
                    if st.button(btn_label, key=f"nm_{path}", use_container_width=True):
                        is_expanded = path in st.session_state.expanded_paths
                        if is_expanded:
                            st.session_state.expanded_paths.remove(path)
                        else:
                            st.session_state.expanded_paths.add(path)
                        st.rerun()
                else:
                    is_selected = path == selected_path
                    btn_type = "primary" if is_selected else "secondary"
                    if st.button(btn_label, key=f"nm_{path}", type=btn_type, use_container_width=True):
                        st.session_state.selected_path = path
                        st.rerun()
                    
    st.markdown("---")
    col_ok, col_cn = st.columns(2)
    with col_ok:
        if st.button("ОК", type="primary", use_container_width=True, key="dlg_ok_btn"):
            st.session_state.custom_save_path = st.session_state.get("selected_path", st.session_state.custom_save_path)
            st.session_state.show_folder_picker = False
            st.rerun()
    with col_cn:
        if st.button("Отмена", use_container_width=True, key="dlg_cn_btn"):
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
        if st.button("Обзор", use_container_width=True):
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

selected_file = "Все файлы"
if st.session_state.processed_files:
    st.sidebar.markdown("---")
    st.sidebar.subheader("Что показать")
    file_options = ["Все файлы"] + list(st.session_state.processed_files.keys())
    selected_file = st.sidebar.selectbox(
        "Выберите отчет:",
        options=file_options,
        help="Можно смотреть один файл или общие итоги по всем файлам."
    )

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
        if st.button("Сделать отчет", type="primary"):
            st.session_state.processed_files = {}
            st.session_state.result_df = None
            st.session_state.processing_error = None
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
                ollama_context, ollama_warning = build_ollama_source_context(files_queue[0]["input_path"], ollama_url)
                if ollama_warning:
                    st.warning(ollama_warning)
                elif ollama_context:
                    st.caption("Ollama-центр изучил исходный файл и будет использовать этот контекст в отчете.")
            
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
                    
                    processed_file_names.append((name, {
                        "stats": stats,
                        "preview_df": file_df,
                        "output_path": output_path,
                    }))
                    
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
        stats, preview_df = get_active_stats_and_preview(selected_file)
    
        if stats is not None:
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
                                    "title": "Район"
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
            else:
                st.info("В файле не найдено обращений, которые требуют решения.")
        else:
            st.info("Пока нет данных для показа.")
    else:
        st.info("Сначала выберите файл и сделайте отчет.")



with tab_preview:

    if st.session_state.result_df is not None:
        stats, preview_df = get_active_stats_and_preview(selected_file)
    
        if preview_df is not None:
            processed_dir_path = os.path.join(save_dir, "Обработанные файлы")
            st.info(f"Готовые Excel-отчеты сохранены здесь: {processed_dir_path}")
        
            # Кнопки скачивания
            st.markdown("##### Скачать готовый Excel-отчет")
            if selected_file == "Все файлы":
                col_dl_left, col_dl_right = st.columns(2)
                for i, (filename, file_data) in enumerate(st.session_state.processed_files.items()):
                    out_path = file_data.get("output_path") or os.path.join(processed_dir_path, f"Обработанные_{filename}")
                    if os.path.exists(out_path):
                        try:
                            with open(out_path, "rb") as f:
                                file_bytes = f.read()
                            target_col = col_dl_left if i % 2 == 0 else col_dl_right
                            with target_col:
                                st.download_button(
                                    label=f"Скачать отчет: {filename}",
                                    data=file_bytes,
                                    file_name=os.path.basename(out_path),
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key=f"dl_{filename}"
                                )
                        except Exception as e:
                            st.error(f"Не удалось подготовить Excel для скачивания ({filename}): {friendly_error_message(e)}")
                    else:
                        st.warning(f"Не нашел готовый отчет для файла: {filename}")
            else:
                file_data = st.session_state.processed_files.get(selected_file, {})
                out_path = file_data.get("output_path") or os.path.join(processed_dir_path, f"Обработанные_{selected_file}")
                if os.path.exists(out_path):
                    try:
                        with open(out_path, "rb") as f:
                            file_bytes = f.read()
                        st.download_button(
                            label=f"Скачать отчет: {selected_file}",
                            data=file_bytes,
                            file_name=os.path.basename(out_path),
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_single_{selected_file}"
                        )
                    except Exception as e:
                        st.error(f"Не удалось подготовить Excel для скачивания ({selected_file}): {friendly_error_message(e)}")
                else:
                    st.warning(f"Не нашел готовый отчет для файла: {selected_file}")
        
            st.markdown("---")
            st.markdown("##### Первые строки готового отчета")
        
            df_clean = preview_df.dropna(how='all', axis=1)
            df_clean = df_clean.dropna(how='all', axis=0)
            df_clean = df_clean.fillna("")
        
            if "CLASS_LABEL" in df_clean.columns:
                df_clean = df_clean.drop(columns=["CLASS_LABEL"])
            
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

            if "Ранг критичности" in df_clean.columns:
                try:
                    styled_df = df_clean.head(100).style.map(color_ranks, subset=["Ранг критичности"])
                except AttributeError:
                    styled_df = df_clean.head(100).style.applymap(color_ranks, subset=["Ранг критичности"])
            else:
                styled_df = df_clean.head(100)

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
                        "Нормализованное Гео"
                    ),
                    "Краткое саммари": st.column_config.TextColumn(
                        "Кратко о проблеме"
                    )
                }
            )
        else:
            st.info("Таблица пока недоступна.")
    else:
        st.info("Сначала выберите файл и нажмите «Сделать отчет».")
