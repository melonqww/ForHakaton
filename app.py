import streamlit as st
import pandas as pd
import os
import time

from src.pipeline import run_pipeline, find_column_index
from src.classifier import RequestClassifier

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
    page_title="Интеллектуальный анализ обращений граждан",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .main-title {
        font-size: 2.25rem;
        font-weight: 700;
        color: #1E3A8A;
        margin-bottom: 0.2rem;
    }
    
    .subtitle {
        font-size: 1rem;
        color: #475569;
        margin-bottom: 1.5rem;
        border-bottom: 2px solid #E2E8F0;
        padding-bottom: 1rem;
    }
    
        .metric-container {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 1.25rem;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    }
    
    .metric-val {
        font-size: 1.75rem;
        font-weight: 700;
        color: #1E3A8A;
    }
    
    .metric-lbl {
        font-size: 0.85rem;
        color: #64748B;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-top: 0.25rem;
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

if st.session_state.show_folder_picker:
    folder_picker_dialog()



st.markdown('<div class="main-title">Управление качеством обратной связи</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Интеллектуальная система классификации, фильтрации и приоритизации обращений Минцифры Омской области</div>', unsafe_allow_html=True)

st.sidebar.header("Параметры анализа")

st.sidebar.markdown("Настройки обработки текстовых инцидентов:")

st.sidebar.markdown("**Папка для сохранения**")
default_path_check = st.sidebar.checkbox(
    "Оставить по умолчанию (папка запуска)", 
    value=True,
    help="Если отмечено, файлы будут сохранены в рабочую директорию проекта."
)

if default_path_check:
    save_dir = os.getcwd()
    st.sidebar.text_input("Путь сохранения:", value=save_dir, disabled=True)
else:
    st.sidebar.markdown("Путь сохранения:")
    col_path, col_browse = st.sidebar.columns([2.5, 1.5])
    with col_path:
        save_dir_input = st.text_input(
            "Путь", 
            value=st.session_state.custom_save_path,
            label_visibility="collapsed",
            help="Укажите или вставьте абсолютный путь к папке."
        )
    with col_browse:
        if st.button("Обзор", use_container_width=True):
            st.session_state.show_folder_picker = True
            st.session_state.browse_dir = os.path.abspath(st.session_state.custom_save_path)
            st.rerun()
                
    st.session_state.custom_save_path = save_dir_input
    save_dir = save_dir_input
    
    if not os.path.exists(save_dir) and save_dir.strip() != "":
        st.sidebar.warning("Указанная директория не найдена. Папка будет создана автоматически.")

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
        Итоговый путь сохранения файлов:
    </div>
    <div style="font-size: 0.85rem; font-weight: 500; color: inherit; word-break: break-all; line-height: 1.4;">
        {destination_path}
    </div>
</div>
""", unsafe_allow_html=True)

use_llm = st.sidebar.checkbox(
    "Суммаризация через локальную LLM (Ollama)",
    value=False,
    help="Использовать Qwen2.5 для генерации саммари. Если выключено — используется сверхбыстрый TextRank."
)

ollama_url = st.sidebar.text_input(
    "Ollama API URL",
    value="http://localhost:11434/api/generate",
    disabled=not use_llm
)

max_workers = st.sidebar.slider(
    "Количество потоков LLM",
    min_value=1,
    max_value=32,
    value=8,
    disabled=not use_llm,
    help="Параллельные запросы к локальной LLM для увеличения скорости обработки"
)

st.sidebar.info(
    "Бинарный классификатор спама обучается автоматически на входящих размеченных данных "
    "и отсекает благодарности/информационные запросы от реальных проблем."
)

selected_file = "Все файлы вместе"
if st.session_state.processed_files:
    st.sidebar.markdown("---")
    st.sidebar.subheader("Выбор данных")
    file_options = ["Все файлы вместе"] + list(st.session_state.processed_files.keys())
    selected_file = st.sidebar.selectbox(
        "Файл для отображения:",
        options=file_options,
        help="Выберите конкретный файл для просмотра его данных или оставьте объединение всех файлов."
    )

tab_upload, tab_analytics, tab_preview = st.tabs([
    "Загрузка и обработка", 
    "Аналитика инцидентов", 
    "Просмотр результатов"
])

with tab_upload:
    st.subheader("Загрузка реестра обращений")
    st.write(
        "Загрузите один или несколько исходных файлов в формате Excel (.xlsx). Система проведет классификацию типа инцидента, "
        "нормализацию географических названий, маскирование конфиденциальных данных и расчитает ранг критичности."
    )
    
    input_source = st.radio("Источник данных:", ["Загрузить через браузер", "Выбрать локальный файл из проекта/диска"], horizontal=True)
    
    uploaded_files = []
    local_files_to_process = []
    
    if input_source == "Загрузить через браузер":
        uploaded_files = st.file_uploader(
            "Выберите файлы Excel", 
            type=["xlsx"],
            accept_multiple_files=True,
            help="Таблицы должны содержать колонки с датой создания, текстом обращения и районом."
        )
        if uploaded_files:
            st.success(f"Файлы успешно загружены в очередь (всего: {len(uploaded_files)}).")
    else:
        # Поиск xlsx в текущей папке
        local_xlsx_files = []
        try:
            local_xlsx_files = [f for f in os.listdir(os.getcwd()) if f.endswith('.xlsx') and not f.startswith('~$') and not f.startswith('temp_')]
            local_xlsx_files.sort()
        except Exception:
            pass
            
        st.markdown("**Доступные локальные файлы Excel в папке проекта:**")
        if local_xlsx_files:
            selected_local_files = st.multiselect(
                "Выберите файлы для обработки:",
                options=local_xlsx_files,
                default=[f for f in local_xlsx_files if "prod" in f or "real" in f] or ([local_xlsx_files[0]] if local_xlsx_files else [])
            )
        else:
            selected_local_files = []
            st.info("В текущей папке проекта не найдено файлов .xlsx.")
            
        custom_file_path = st.text_input("Или введите абсолютный путь к файлу на диске:")
        if custom_file_path:
            cleaned_path = custom_file_path.strip().strip('"').strip("'")
            if os.path.exists(cleaned_path) and cleaned_path.endswith('.xlsx'):
                if cleaned_path not in selected_local_files:
                    selected_local_files.append(cleaned_path)
            else:
                st.error("Файл по указанному пути не найден или имеет неверный формат.")
                
        if selected_local_files:
            st.success(f"Выбрано локальных файлов для обработки: {len(selected_local_files)}")
            for f in selected_local_files:
                if os.path.isabs(f):
                    local_files_to_process.append({"name": os.path.basename(f), "path": f})
                else:
                    local_files_to_process.append({"name": f, "path": os.path.abspath(f)})
                    
    has_files = (input_source == "Загрузить через браузер" and uploaded_files) or (input_source == "Выбрать локальный файл из проекта/диска" and local_files_to_process)
    
    if has_files:
        if st.button("Начать обработку данных", type="primary"):
            st.session_state.processed_files = {}
            st.session_state.result_df = None
            processed_dir = os.path.join(save_dir, "Обработанные файлы")
            try:
                os.makedirs(processed_dir, exist_ok=True)
            except Exception as e:
                st.error(f"Не удалось создать директорию для сохранения: {e}")
                st.stop()
                
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            status_text.text("Подготовка классификатора обращений...")
            classifier = RequestClassifier()
            
            # Собираем список файлов для обработки
            files_queue = []
            if input_source == "Загрузить через браузер":
                for idx, uploaded_file in enumerate(uploaded_files):
                    temp_input_path = os.path.join(processed_dir, f"temp_in_{uploaded_file.name}")
                    with open(temp_input_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    files_queue.append({
                        "name": uploaded_file.name,
                        "input_path": temp_input_path,
                        "output_path": os.path.join(processed_dir, f"Обработанные_{uploaded_file.name}"),
                        "is_temp": True
                    })
            else:
                for f_info in local_files_to_process:
                    files_queue.append({
                        "name": f_info["name"],
                        "input_path": f_info["path"],
                        "output_path": os.path.join(processed_dir, f"Обработанные_{f_info['name']}"),
                        "is_temp": False
                    })
            
            if not classifier.model and files_queue:
                status_text.text("Обучение модели классификатора на первом наборе данных...")
                try:
                    temp_df = pd.read_excel(files_queue[0]["input_path"])
                    if "CLASS_LABEL" in temp_df.columns:
                        col_text = find_column_index(temp_df, "text", 36)
                        texts = temp_df.iloc[:, col_text].fillna("").astype(str).tolist()
                        labels = temp_df["CLASS_LABEL"].fillna("Проблема").tolist()
                        classifier.train(texts, labels)
                except Exception as e:
                    st.warning(f"Не удалось автоматически дообучить классификатор: {e}. Используется эвристика.")
            
            progress_bar.progress(10)
            
            start_time = time.time()
            all_dfs = []
            processed_file_names = []
            
            try:
                for idx, f_item in enumerate(files_queue):
                    name = f_item["name"]
                    input_path = f_item["input_path"]
                    output_path = f_item["output_path"]
                    
                    def streamlit_progress_callback(current, total):
                        percent = int((current / total) * 80) + 10
                        progress_bar.progress(percent)
                        status_text.text(
                            f"Файл {idx+1}/{len(files_queue)} ({name}): "
                            f"обработано {current} из {total} уникальных проблемных обращений ({percent}%)..."
                        )
                    
                    run_pipeline(
                        input_path, 
                        output_path, 
                        use_llm=use_llm, 
                        ollama_url=ollama_url, 
                        max_workers=max_workers,
                        progress_callback=streamlit_progress_callback,
                        classifier=classifier
                    )
                    
                    # Читаем результат обработанного файла для аналитики
                    file_df = pd.read_excel(output_path)
                    all_dfs.append(file_df)
                    processed_file_names.append((name, file_df))
                    
                    # Удаляем временный входной файл
                    if f_item["is_temp"] and os.path.exists(input_path):
                        os.remove(input_path)
                
                elapsed = time.time() - start_time
                progress_bar.progress(100)
                status_text.text("Обработка всех файлов успешно завершена!")
                
                processed_files = {}
                for name, df in processed_file_names:
                    processed_files[name] = df
                st.session_state.processed_files = processed_files
                
                combined_df = pd.concat(all_dfs, ignore_index=True)
                st.session_state.result_df = combined_df
                st.session_state.elapsed_time = elapsed
                
                st.success(
                    f"Все файлы успешно обработаны за {elapsed:.2f} сек. "
                    f"Результаты сохранены в папку: {processed_dir}. "
                    f"Перейдите во вкладку 'Аналитика инцидентов' или 'Просмотр результатов'."
                )
                    
            except Exception as e:
                st.error(f"Ошибка в процессе обработки: {e}")
                # Чистим временные файлы в случае ошибки
                for f_item in files_queue:
                    if f_item["is_temp"] and os.path.exists(f_item["input_path"]):
                        os.remove(f_item["input_path"])
    else:
        st.info("Пожалуйста, загрузите файлы или выберите локальный файл из списка.")

with tab_analytics:
    st.subheader("Аналитическая сводка по инцидентам")
    
    if st.session_state.result_df is not None:
        if selected_file == "Все файлы вместе":
            df_res = st.session_state.result_df
        else:
            df_res = st.session_state.processed_files.get(selected_file, st.session_state.result_df)
        df_problems = df_res[df_res["Тип инцидента"] == "Проблема"]
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        
        with kpi1:
            st.markdown(
                f'<div class="metric-container"><div class="metric-val">{len(df_res)}</div>'
                f'<div class="metric-lbl">Всего обращений</div></div>', 
                unsafe_allow_html=True
            )
        with kpi2:
            st.markdown(
                f'<div class="metric-container"><div class="metric-val">{len(df_problems)}</div>'
                f'<div class="metric-lbl">Реальные проблемы</div></div>', 
                unsafe_allow_html=True
            )
        with kpi3:
            spam_count = len(df_res) - len(df_problems)
            st.markdown(
                f'<div class="metric-container"><div class="metric-val">{spam_count}</div>'
                f'<div class="metric-lbl">Отсеяно (Спам/Благодарности)</div></div>', 
                unsafe_allow_html=True
            )
        with kpi4:
            st.markdown(
                f'<div class="metric-container"><div class="metric-val">{st.session_state.elapsed_time:.1f}с</div>'
                f'<div class="metric-lbl">Время обработки</div></div>', 
                unsafe_allow_html=True
            )
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        if not df_problems.empty:
            st.markdown("##### Лидеры по количеству инцидентов (Топ-3)")
            top_3_districts = df_problems["Нормализованное Гео"].value_counts().head(3).reset_index()
            top_3_districts.columns = ["Район", "Количество"]
            
            cols_top3 = st.columns(min(3, len(top_3_districts)))
            labels = ["1-е место", "2-е место", "3-е место"]
            colors = ["transparent", "transparent", "transparent"]
            border_colors = ["rgba(128, 128, 128, 0.25)", "rgba(128, 128, 128, 0.25)", "rgba(128, 128, 128, 0.25)"]
            text_colors = ["inherit", "inherit", "inherit"]
            
            for idx, row in top_3_districts.iterrows():
                with cols_top3[idx]:
                    district_name = row["Район"].replace(" р-н", "").replace(" рн", "").replace(" район", "").replace(" немецкий национальный", "").replace(" г. Омск", "Омск").replace("г. Омск", "Омск")
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
                        <div style="font-size: 0.85rem; color: inherit;">
                            Количество инцидентов: <b>{row['Количество']}</b>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            col_charts_1, col_charts_2 = st.columns(2)
            
            with col_charts_1:
                st.markdown("##### Топ-10 районов Омской области по числу проблем")
                district_counts = df_problems["Нормализованное Гео"].value_counts().head(10).reset_index()
                district_counts.columns = ["Район", "Количество"]
                
                chart_df = district_counts.copy()
                chart_df["Район"] = chart_df["Район"].apply(
                    lambda x: x.replace(" р-н", "")
                               .replace(" рн", "")
                               .replace(" район", "")
                               .replace(" немецкий национальный", "")
                               .replace(" г. Омск", "Омск")
                               .replace("г. Омск", "Омск")
                )
                
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
                        "height": 380
                    },
                    use_container_width=True
                )
                
            with col_charts_2:
                st.markdown("##### Распределение инцидентов по категориям")
                group_col_idx = find_column_index(df_res, "group", 21)
                group_col_name = df_res.columns[group_col_idx]
                category_counts = df_problems[group_col_name].value_counts().reset_index()
                category_counts.columns = ["Категория", "Количество"]
                
                st.dataframe(
                    category_counts, 
                    hide_index=True,
                    use_container_width=True
                )
                
            st.markdown("##### Распределение проблем по рангам критичности")
            rank_counts = df_problems["Ранг критичности"].value_counts().sort_index().reset_index()
            rank_counts.columns = ["Ранг критичности", "Количество обращений"]
            rank_desc = {
                1: "1 - Минимальный (Благодарности, мелкие плановые работы)",
                2: "2 - Низкий (Типовые недочеты, мелкие ямы, мусор во дворе)",
                3: "3 - Средний (Транспортные сбои, открытые люки, крупные ямы)",
                4: "4 - Высокий (Прорыв отопления, замерзаем, отключение света)",
                5: "5 - Критический (ЧП, пожары, взрывы, угроза жизни)"
            }
            rank_counts["Описание ранга"] = rank_counts["Ранг критичности"].map(rank_desc)
            st.dataframe(
                rank_counts[["Описание ранга", "Количество обращений"]],
                hide_index=True,
                use_container_width=True
            )
        else:
            st.info("Реальных проблем в реестре не найдено. Все записи отсеяны как нерелевантные.")
    else:
        st.info("Для отображения аналитики необходимо загрузить и обработать файлы во вкладке 'Загрузка и обработка'.")

with tab_preview:
    st.subheader("Просмотр обработанных данных")
    
    if st.session_state.result_df is not None:
        if selected_file == "Все файлы вместе":
            df_res = st.session_state.result_df
        else:
            df_res = st.session_state.processed_files.get(selected_file, st.session_state.result_df)
        processed_dir_path = os.path.join(save_dir, "Обработанные файлы")
        st.info(f"Все обработанные отчеты сохранены на диск в директорию: {processed_dir_path}")
        
        st.markdown("##### Таблица результатов (превью первых 100 строк)")
        
        df_clean = df_res.dropna(how='all', axis=1)
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
            height=700, # Увеличенная высота до конца экрана
            column_config={
                "Ранг критичности": st.column_config.NumberColumn(
                    "Ранг критичности",
                    help="От 1 (минимальный) до 5 (критический)",
                    format="%d"
                ),
                "Тип инцидента": st.column_config.TextColumn(
                    "Тип инцидента",
                    help="Результат классификации: Проблема или Не проблема"
                ),
                "Нормализованное Гео": st.column_config.TextColumn(
                    "Нормализованное Гео"
                ),
                "Краткое саммари": st.column_config.TextColumn(
                    "Суть инцидента (Саммари)"
                )
            }
        )
    else:
        st.info("Пожалуйста, сначала загрузите и обработайте файлы во вкладке 'Загрузка и обработка'.")
