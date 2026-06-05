import re
import functools
from rapidfuzz import process, utils
from src.config import OMSK_DISTRICTS

# Компилируем один раз при загрузке модуля, а не при каждом вызове clean_text
_WHITESPACE_RE = re.compile(r'\s+')

def clean_text(text: str) -> str:
    """Удаление лишних пробельных символов и переносов."""
    if not isinstance(text, str):
        return ""
    return _WHITESPACE_RE.sub(' ', text).strip()

@functools.lru_cache(maxsize=512)
def normalize_municipality(name: str) -> str:
    """Сопоставление названия района со справочником Омской области.
    
    Результат кэшируется: ~35 уникальных районов → после прогрева
    все вызовы O(1) без повторного fuzzy matching.
    """
    if not name or not isinstance(name, str):
        return "Неизвестный р-н"
        
    cleaned_name = name.strip()
    match = process.extractOne(
        cleaned_name, 
        OMSK_DISTRICTS, 
        processor=utils.default_process,
        score_cutoff=75.0
    )
    return match[0] if match else cleaned_name
