def find_column_index(df, key: str, default_idx: int) -> int:
    """Интеллектуальный поиск индекса колонки по ключевым словам в заголовках."""
    keywords = {
        "created_at": ["дата создания", "создано", "created_at", "created"],
        "closed_at": ["дата закрытия", "закрыто", "closed_at", "closed", "дата окончания", "окончания", "окончание"],
        "group": ["группа", "категория", "group", "theme_group"],
        "topic": ["тема", "подкатегория", "topic", "theme"],
        "municipality": ["муниципалитет", "район", "municipality", "district"],
        "settlement": ["населенный пункт", "населённый пункт", "город", "село", "settlement"],
        "text": ["текст инцидента", "текст обращения", "текст жалобы", "текст", "содержание", "обращение", "жалоба", "text", "comment"]
    }
    
    if hasattr(df, 'columns'):
        col_names = [str(col).strip().lower() for col in df.columns]
    else:
        col_names = [str(col).strip().lower() for col in df]
    
    # 1. Сначала ищем точное совпадение
    for kw in keywords.get(key, []):
        for idx, col_name in enumerate(col_names):
            if kw == col_name:
                return idx
                
    # 2. Затем ищем частичное совпадение с защитой от ложных срабатываний
    for kw in keywords.get(key, []):
        for idx, col_name in enumerate(col_names):
            if kw in col_name:
                if key == "text" and any(bad in col_name for bad in ["ответ", "пи"]):
                    continue
                return idx
                
    # 3. Поиск по буквам Excel (если колонки названы по буквам)
    letter_mapping = {
        "created_at": "T",
        "closed_at": "U",
        "group": "V",
        "topic": "W",
        "municipality": "Y",
        "settlement": "Z",
        "text": "AK"
    }
    target_letter = letter_mapping.get(key, "").lower()
    if target_letter:
        for idx, col_name in enumerate(col_names):
            if col_name == target_letter:
                return idx

    # 4. Fallback к дефолтному индексу
    limit = len(df.columns) if hasattr(df, 'columns') else len(df)
    if default_idx < limit:
        return default_idx
        
    return default_idx
