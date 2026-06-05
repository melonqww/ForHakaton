import pandas as pd
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.config import EXCEL_COLUMNS
from src.utils import find_column_index
from src.preprocessing import clean_text, normalize_municipality
from src.classifier import RequestClassifier
from src.summarizer import extract_summary_local, extract_summary_llm, get_criticality_rank
from src.exporter import export_to_excel

def run_pipeline(input_path: str, output_path: str, use_llm: bool = False, 
                 ollama_url: str = "http://localhost:11434/api/generate", 
                 max_workers: int = 8, progress_callback=None, classifier=None):
    """Сквозной конвейер обработки и анализа реестра обращений."""
    
    df = pd.read_excel(input_path)
    
    col_text = find_column_index(df, "text", EXCEL_COLUMNS["text"])
    col_mun = find_column_index(df, "municipality", EXCEL_COLUMNS["municipality"])
    col_settlement = find_column_index(df, "settlement", EXCEL_COLUMNS["settlement"])
    
    raw_texts = df.iloc[:, col_text].fillna("").astype(str).tolist()
    cleaned_texts = [clean_text(t) for t in raw_texts]
    
    # Кэширование гео-нормализации для ускорения работы
    raw_muns = df.iloc[:, col_mun].fillna("").astype(str).tolist()
    unique_muns = set(raw_muns)
    geo_map = {mun: normalize_municipality(mun) for mun in unique_muns}
    normalized_geos = [geo_map[mun] for mun in raw_muns]
    
    settlements = df.iloc[:, col_settlement].fillna("").astype(str).tolist()
    
    if classifier is None:
        classifier = RequestClassifier()
    incidents_types = classifier.predict(cleaned_texts)
    
    # Суммаризируем только уникальные тексты реальных проблем
    unique_problem_texts = list(dict.fromkeys([
        text for text, inc_type in zip(cleaned_texts, incidents_types)
        if inc_type == "Проблема"
    ]))
    
    summaries_map = {}
    total_to_process = len(unique_problem_texts)
    
    if total_to_process > 0:
        if use_llm:
            lock = threading.Lock()
            ollama_active = True
            consecutive_failures = 0
            max_failures = 5
            
            def llm_worker(text):
                nonlocal ollama_active, consecutive_failures
                with lock:
                    if not ollama_active:
                        return text, extract_summary_local(text), False
                
                summary, success = extract_summary_llm(text, ollama_url=ollama_url)
                return text, summary, success
            
            processed_count = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(llm_worker, text): text for text in unique_problem_texts}
                
                for future in as_completed(futures):
                    text = futures[future]
                    try:
                        _, summary, success = future.result()
                        with lock:
                            if success:
                                consecutive_failures = 0
                            else:
                                consecutive_failures += 1
                                if consecutive_failures >= max_failures:
                                    ollama_active = False
                        summaries_map[text] = summary
                    except Exception:
                        summaries_map[text] = extract_summary_local(text)
                        with lock:
                            consecutive_failures += 1
                            if consecutive_failures >= max_failures:
                                ollama_active = False
                    
                    processed_count += 1
                    if progress_callback:
                        progress_callback(processed_count, total_to_process)
        else:
            processed_count = 0
            for text in unique_problem_texts:
                summaries_map[text] = extract_summary_local(text)
                processed_count += 1
                if progress_callback:
                    progress_callback(processed_count, total_to_process)
    ranks_map = {text: get_criticality_rank(text) for text in unique_problem_texts}

    ranks = []
    summaries = []
    
    for text, inc_type in zip(cleaned_texts, incidents_types):
        if inc_type == "Проблема":
            rank = ranks_map.get(text, 2)
            summary = summaries_map.get(text)
            if not summary:
                summary = extract_summary_local(text)
        else:
            rank = 1
            summary = "Не требует решения (спам/благодарность)"
            
        ranks.append(rank)
        summaries.append(summary)
        
    df["Очищенный текст"] = cleaned_texts
    df["Нормализованное Гео"] = normalized_geos
    df["Населённый пункт"] = settlements
    df["Ранг критичности"] = ranks
    df["Краткое саммари"] = summaries
    df["Тип инцидента"] = incidents_types
    
    export_to_excel(df, output_path)
