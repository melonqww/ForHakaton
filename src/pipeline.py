import openpyxl
import pandas as pd
import os
import gc
import re
from concurrent.futures import ThreadPoolExecutor

from src.utils import find_column_index
from src.preprocessing import clean_text, normalize_municipality
from src.exporter import StreamingExcelExporter
from src.summarizer import extract_summary_local, extract_summary_llm, get_criticality_rank, generate_district_summary_llm

SETTLEMENT_PREFIXES = re.compile(
    r"\b(?:г\.|город|с\.|село|д\.|деревня|р\.п\.|рп|пгт|поселок|посёлок|х\.|хутор|ст\.|станция)\s*([А-Я][а-я]+(?:-[А-Я][а-я]+)?)",
    re.UNICODE
)

def extract_settlement_from_text(text: str) -> str:
    """Извлекает название населенного пункта из текста обращения."""
    if not text:
        return ""
    match = SETTLEMENT_PREFIXES.search(text)
    if match:
        return match.group(0).strip()
    return ""

DISTRICT_CENTERS = {
    "азовск": "Азово",
    "большереч": "Большеречье",
    "большеук": "Большие Уки",
    "горьковск": "Горьковское",
    "знаменск": "Знаменское",
    "исилькуль": "Исилькуль",
    "калачинск": "Калачинск",
    "колосовк": "Колосовка",
    "кормилов": "Кормиловка",
    "крутин": "Крутинка",
    "любин": "Любинский",
    "марьянов": "Марьяновка",
    "муромцев": "Муромцево",
    "называев": "Называевск",
    "нижнеомск": "Нижняя Омка",
    "нововаршав": "Нововаршавка",
    "одесск": "Одесское",
    "оконешников": "Оконешниково",
    "омск": "Омск",
    "павлоград": "Павлоградка",
    "полтав": "Полтавка",
    "русско-полян": "Русская Поляна",
    "русская поляна": "Русская Поляна",
    "саргат": "Саргатское",
    "седельников": "Седельниково",
    "таврическ": "Таврическое",
    "тарск": "Тара",
    "тевриз": "Тевриз",
    "тюкалин": "Тюкалинск",
    "усть-ишим": "Усть-Ишим",
    "черлак": "Черлак",
    "шербакуль": "Шербакуль"
}

def infer_settlement_from_municipality(mun: str) -> str:
    """Определяет административный центр района, если населенный пункт пропущен."""
    if not mun:
        return ""
    m_lower = mun.lower()
    for key, center in DISTRICT_CENTERS.items():
        if key in m_lower:
            return center
    return ""

# ──────────────────────────────────────────────────────────────
# Обработка чанка
# Фиксированные индексы: 0: created_at, 1: closed_at, 2: group,
# 3: topic, 4: municipality, 5: settlement, 6: text
# ──────────────────────────────────────────────────────────────


def _process_chunk_inline(chunk_data, classifier):
    """Обработка чанка в основном процессе (без форка). Для однопоточного режима."""
    (chunk_rows, use_llm, ollama_url, has_incident_type_column) = chunk_data
    clf = classifier
    
    raw_texts = [str(row[6] or "").strip() for row in chunk_rows]
    muns = [str(row[4] or "").strip() for row in chunk_rows]
    
    # Интеллектуальное автозаполнение населенного пункта из текста или по названию Муниципалитета
    settlements = []
    for i, row in enumerate(chunk_rows):
        settlement = str(row[5] or "").strip()
        mun = str(row[4] or "").strip()
        
        # 1. Сначала пытаемся извлечь из текста инцидента
        if not settlement or settlement.lower() in ["nan", "none", "null", ""]:
            extracted = extract_settlement_from_text(raw_texts[i])
            if extracted:
                settlement = extracted
                
        # 2. Если все еще пусто — подставляем по названию района (например, Омск г.о. -> Омск, Тарский район -> Тара)
        if not settlement or settlement.lower() in ["nan", "none", "null", ""]:
            fallback = infer_settlement_from_municipality(mun)
            if fallback:
                settlement = fallback
                
        # 3. На всякий случай очищаем строковые "nan" и приводим в божеский вид
        if settlement.lower() in ["nan", "none", "null"]:
            settlement = ""
            
        settlements.append(settlement)
        
    group_vals = [str(row[2] or "Другое").strip() for row in chunk_rows]
    
    cleaned_texts = [clean_text(t) for t in raw_texts]
    texts_lower = [t.lower() for t in cleaned_texts]
    normalized_geos = [normalize_municipality(mun) for mun in muns]
    
    incidents_types = clf.predict(cleaned_texts, texts_lower)
    
    processed_rows = []
    chunk_stats = {
        "problems_count": 0,
        "category_counts": {},
        "rank_counts": {},
        "district_stats": {}
    }
    
    for i, (text, text_lower, inc_type) in enumerate(zip(cleaned_texts, texts_lower, incidents_types)):
        group_val = group_vals[i]
        geo = normalized_geos[i]
        
        if inc_type == "Проблема":
            chunk_stats["problems_count"] += 1
            rank = get_criticality_rank(text_lower)
            summary = extract_summary_local(text)

            chunk_stats["category_counts"][group_val] = chunk_stats["category_counts"].get(group_val, 0) + 1
            chunk_stats["rank_counts"][rank] = chunk_stats["rank_counts"].get(rank, 0) + 1

            if geo not in chunk_stats["district_stats"]:
                chunk_stats["district_stats"][geo] = {
                    "count": 0, "rank_sum": 0.0, "rank_count": 0,
                    "critical_count": 0, "categories": {}, "summaries": []
                }
            d_stats = chunk_stats["district_stats"][geo]
            d_stats["count"] += 1
            d_stats["rank_sum"] += rank
            d_stats["rank_count"] += 1
            if rank >= 4:
                d_stats["critical_count"] += 1
                if len(d_stats["summaries"]) < 3 and summary not in d_stats["summaries"]:
                    d_stats["summaries"].append(summary)
            d_stats["categories"][group_val] = d_stats["categories"].get(group_val, 0) + 1
        else:
            rank = 1
            summary = "Не требует решения (спам/благодарность)"
            
        row_data = list(chunk_rows[i])
        row_data[5] = settlements[i] # Записываем автозаполненный населенный пункт
        row_data.extend([""] * 5)
        
        row_data[7] = text          # Очищенный текст
        row_data[8] = geo           # Нормализованное Гео
        row_data[9] = rank          # Ранг критичности
        row_data[10] = summary      # Краткое саммари
        
        if has_incident_type_column:
            row_data[11] = "Решаемый" if inc_type == "Проблема" else "Информационный"
        else:
            row_data[11] = inc_type
            
        processed_rows.append(row_data)
    
    return processed_rows, chunk_stats


def _merge_chunk_stats(target: dict, source: dict):
    """Слияние статистики из чанка в общую агрегацию."""
    target["problems_count"] = target.get("problems_count", 0) + source["problems_count"]
    
    for cat, val in source["category_counts"].items():
        target["category_counts"][cat] = target["category_counts"].get(cat, 0) + val
        
    for r, val in source["rank_counts"].items():
        target["rank_counts"][r] = target["rank_counts"].get(r, 0) + val
        
    for geo, d_data in source["district_stats"].items():
        if geo not in target["district_stats"]:
            target["district_stats"][geo] = {
                "count": 0, "rank_sum": 0.0, "rank_count": 0,
                "critical_count": 0, "categories": {}, "summaries": []
            }
        m = target["district_stats"][geo]
        m["count"] += d_data["count"]
        m["rank_sum"] += d_data["rank_sum"]
        m["rank_count"] += d_data["rank_count"]
        m["critical_count"] += d_data["critical_count"]
        
        for cat, val in d_data["categories"].items():
            m["categories"][cat] = m["categories"].get(cat, 0) + val
            
        for summ in d_data["summaries"]:
            if len(m["summaries"]) < 3 and summ not in m["summaries"]:
                m["summaries"].append(summ)


def run_pipeline(input_path: str, output_path: str, use_llm: bool = False, 
                 ollama_url: str = "http://localhost:11434/api/generate", 
                 max_workers: int = 8, progress_callback=None, classifier=None):
    """Оптимизированный конвейер обработки реестра обращений.

    Особенности оптимизации:
    - Считывает только 7 ключевых колонок из исходного файла (пропуск лишних 43 колонок).
    - Записывает только 12 колонок в результирующий файл.
    - Внутри чанков работает сверхбыстрый локальный суммаризатор (TextRank).
    - Локальная LLM (Ollama) применяется только в конце для 10 Топ-районов.
    """
    # 1. Считываем только шапку через pandas
    try:
        header_df = pd.read_excel(input_path, nrows=0, engine="calamine")
    except Exception:
        header_df = pd.read_excel(input_path, nrows=0)
    headers = list(header_df.columns)
    
    # Поиск индексов исходных колонок
    col_created_at = find_column_index(header_df, "created_at", 19)
    col_closed_at = find_column_index(header_df, "closed_at", 20)
    col_group = find_column_index(header_df, "group", 21)
    col_topic = find_column_index(header_df, "topic", 22)
    col_mun = find_column_index(header_df, "municipality", 24)
    col_settlement = find_column_index(header_df, "settlement", 25)
    col_text = find_column_index(header_df, "text", 36)
    
    has_incident_type_column = False
    for idx, col_name in enumerate(headers):
        if str(col_name).strip().lower() == "тип инцидента":
            has_incident_type_column = True
            break
            
    # Заголовки для 12-колоночного выходного файла
    out_headers = [
        headers[col_created_at] if col_created_at < len(headers) else "Дата создания",
        headers[col_closed_at] if col_closed_at < len(headers) else "Дата окончания",
        headers[col_group] if col_group < len(headers) else "Группа тем",
        headers[col_topic] if col_topic < len(headers) else "Тема",
        headers[col_mun] if col_mun < len(headers) else "Муниципалитет",
        headers[col_settlement] if col_settlement < len(headers) else "Населенный пункт",
        headers[col_text] if col_text < len(headers) else "Текст инцидента",
        "Очищенный текст",
        "Нормализованное Гео",
        "Ранг критичности",
        "Краткое саммари",
        "Тип инцидента"
    ]
        
    # Стриминг-экспортер (новые индексы колонок в 12-колоночном файле)
    exporter = StreamingExcelExporter(
        output_path, 
        out_headers, 
        text_col=6, 
        group_col=2, 
        rank_col=9, 
        summary_col=10, 
        type_col=11
    )
    
    agg_stats = {
        "problems_count": 0,
        "category_counts": {},
        "rank_counts": {},
        "district_stats": {}
    }
    total_count = 0
    preview_rows = []
    
    chunk_size = 5000
    
    if classifier is None:
        from src.classifier import RequestClassifier
        classifier = RequestClassifier()
        
    # Читаем только 7 нужных колонок через Pandas
    indices = [col_created_at, col_closed_at, col_group, col_topic, col_mun, col_settlement, col_text]
    unique_indices = list(set(indices))

    try:
        # calamine — Rust-движок, читает xlsx в 5-10x быстрее openpyxl
        df_raw = pd.read_excel(input_path, usecols=unique_indices, engine="calamine")
    except Exception:
        # Фолбек на стандартный openpyxl если calamine не установлен
        df_raw = pd.read_excel(input_path, usecols=unique_indices)
    total_rows = len(df_raw)

    # Сопоставляем в нужном фиксированном порядке
    df_7 = pd.DataFrame()
    for idx, col_idx in enumerate(indices):
        if col_idx < len(headers):
            col_name = headers[col_idx]
            if col_name in df_raw.columns:
                df_7[idx] = df_raw[col_name]
            else:
                df_7[idx] = ""
        else:
            df_7[idx] = ""

    del df_raw
    gc.collect()


    def _write_results(processed_rows, chunk_stats):
        nonlocal total_count
        for row in processed_rows:
            exporter.write_row(row)
            if len(preview_rows) < 1000:
                preview_rows.append(row)
        total_count += len(processed_rows)
        _merge_chunk_stats(agg_stats, chunk_stats)
        if progress_callback:
            progress_callback(min(total_count, total_rows), total_rows)

    # Запускаем конвейер по чанкам
    for start_idx in range(0, total_rows, chunk_size):
        chunk_df = df_7.iloc[start_idx : start_idx + chunk_size]
        chunk_rows = list(chunk_df.itertuples(index=False, name=None))

        chunk_data = (chunk_rows, False, ollama_url, has_incident_type_column)
        processed_rows, chunk_stats = _process_chunk_inline(chunk_data, classifier)
        _write_results(processed_rows, chunk_stats)

        del processed_rows, chunk_stats, chunk_rows
        gc.collect()

    
    # Постобработка статистики районов
    district_stats = agg_stats["district_stats"]
    sorted_districts = sorted(district_stats.items(), key=lambda x: x[1]["count"], reverse=True)
    
    top3_districts = []
    for district, d_stats in sorted_districts[:3]:
        sorted_cats = sorted(d_stats["categories"].items(), key=lambda x: x[1], reverse=True)
        top_cat = sorted_cats[0][0] if sorted_cats else "Другое"
        avg_rank = d_stats["rank_sum"] / d_stats["rank_count"] if d_stats["rank_count"] > 0 else 0
        
        # Интеллектуальная LLM-сводка для Топ-3
        key_problems = "; ".join(d_stats["summaries"])
        if use_llm:
            llm_summary = generate_district_summary_llm(district, d_stats["summaries"], ollama_url=ollama_url)
            if llm_summary:
                key_problems = llm_summary
                
        top3_districts.append({
            "district": district,
            "count": d_stats["count"],
            "top_cat": top_cat,
            "avg_rank": avg_rank,
            "critical_count": d_stats["critical_count"],
            "key_problems": key_problems
        })
        
    top10_districts = []
    for district, d_stats in sorted_districts[:10]:
        sorted_cats = sorted(d_stats["categories"].items(), key=lambda x: x[1], reverse=True)
        top_cat = sorted_cats[0][0] if sorted_cats else "Другое"
        avg_rank = d_stats["rank_sum"] / d_stats["rank_count"] if d_stats["rank_count"] > 0 else 0
        
        top10_districts.append({
            "district": district,
            "count": d_stats["count"],
            "top_cat": top_cat,
            "avg_rank": avg_rank
        })
        
    stats = {
        "total_count": total_count,
        "problems_count": agg_stats["problems_count"],
        "top3_districts": top3_districts,
        "top10_districts": top10_districts,
        "category_counts": agg_stats["category_counts"],
        "rank_counts": agg_stats["rank_counts"],
        "district_counts": {k: v["count"] for k, v in district_stats.items()},
        "district_stats": district_stats
    }
    
    exporter.close(stats)
    
    preview_df = pd.DataFrame(preview_rows, columns=out_headers)
    return stats, preview_df
