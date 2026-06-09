import re
import functools
from rapidfuzz import process, utils
from src.config import OMSK_DISTRICTS

_WHITESPACE_RE = re.compile(r'\s+')


class PreprocessingError(Exception):
    """Ошибка предобработки данных."""
    pass


def clean_text(text: str) -> str:
    """Удаление лишних пробельных символов и переносов."""
    if not isinstance(text, str):
        return ""
    try:
        return _WHITESPACE_RE.sub(' ', text).strip()
    except Exception as e:
        return ""


@functools.lru_cache(maxsize=512)
def normalize_municipality(name: str) -> str:
    """Сопоставление названия района со справочником Омской области.

    Результат кэшируется: ~35 уникальных районов → после прогрева
    все вызовы O(1) без повторного fuzzy matching.
    """
    if not name or not isinstance(name, str):
        return "Неизвестный р-н"

    try:
        cleaned_name = name.strip()
        match = process.extractOne(
            cleaned_name,
            OMSK_DISTRICTS,
            processor=utils.default_process,
            score_cutoff=75.0
        )
        return match[0] if match else cleaned_name
    except ValueError as e:
        raise PreprocessingError(f"Ошибка при сопоставлении названия района «{name}»: {e}")
    except Exception as e:
        # В случае ошибки fuzzy-матчинга возвращаем исходное название
        return cleaned_name