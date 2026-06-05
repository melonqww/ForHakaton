def find_column_index(df, key: str, default_idx: int) -> int:
    """Интеллектуальный поиск индекса колонки по ключевым словам в заголовках."""
    keywords = {
        "created_at": ["дата создания", "создано", "created_at", "created"],
        "closed_at": ["дата закрытия", "закрыто", "closed_at", "closed"],
        "group": ["группа", "категория", "group", "theme_group"],
        "topic": ["тема", "подкатегория", "topic", "theme"],
        "municipality": ["муниципалитет", "район", "municipality", "district"],
        "settlement": ["населенный пункт", "населённый пункт", "город", "село", "settlement"],
        "text": ["текст", "содержание", "обращение", "жалоба", "text", "comment"]
    }
    
    # 1. Поиск по названиям колонок (регистронезависимый поиск подстроки)
    col_names = [str(col).strip().lower() for col in df.columns]
    
    for kw in keywords.get(key, []):
        for idx, col_name in enumerate(col_names):
            if kw in col_name:
                return idx
                
    # 2. Поиск по буквам Excel (если колонки названы по буквам)
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

    # 3. Fallback к дефолтному индексу
    if default_idx < len(df.columns):
        return default_idx
        
    return default_idx
