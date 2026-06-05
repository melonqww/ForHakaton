import re
import requests
from src.config import CRITICALITY_KEYWORDS

SENTENCE_SPLIT_REGEX = re.compile(
    r'(?<=(?<!\bс)(?<!\bд)(?<!\bг)(?<!\bп)(?<!\bул)(?<!\bкв)(?<!\bобл)(?<!\bр-н)(?<!\bрп)(?<!\bим)[.!?])\s+',
    re.IGNORECASE
)

def split_into_sentences(text: str) -> list:
    """Разбиение текста на предложения с фильтрацией сокращений."""
    return [s.strip() for s in SENTENCE_SPLIT_REGEX.split(text) if s.strip()]

def extract_summary_local(text: str, max_chars: int = 300) -> str:
    """Экстрактивная суммаризация на основе эвристического TextRank."""
    if not text:
        return ""
        
    if len(text) <= 80:
        return text

    # Быстрый выход для простых односоставных текстов без знаков препинания
    if '.' not in text and '!' not in text and '?' not in text:
        return text if len(text) <= max_chars else text[:max_chars-3] + "..."

    sentences = split_into_sentences(text)
    if not sentences:
        return ""
    if len(sentences) == 1:
        s = sentences[0]
        return s if len(s) <= max_chars else s[:max_chars-3] + "..."

    # Эвристический выбор лучшего предложения
    best_score = -1.0
    best_sentence = sentences[0]
    
    for idx, sentence in enumerate(sentences):
        position_score = 1.5 if idx == 0 else 1.0
        words_count = sentence.count(' ') + 1
        length_score = 1.3 if 5 <= words_count <= 20 else 0.8
            
        score = position_score * length_score
        if score > best_score:
            best_score = score
            best_sentence = sentence

    if len(best_sentence) > max_chars:
        return best_sentence[:max_chars-3].strip() + "..."
        
    return best_sentence

def extract_summary_llm(text: str, ollama_url: str = "http://localhost:11434/api/generate") -> tuple[str, bool]:
    """Генеративная суммаризация через локальный API Ollama."""
    if not text:
        return "", True
        
    working_text = text
    if len(text) > 1000:
        working_text = extract_summary_local(text, max_chars=800)

    prompt = (
        "Сделай краткую выжимку (саммари) сути следующей жалобы гражданина на русском языке. "
        "Верни ТОЛЬКО саму суть в одно предложение, длиной не более 300 символов, без вводных фраз и кавычек.\n\n"
        f"Текст жалобы: {working_text}"
    )
    
    try:
        response = requests.post(
            ollama_url,
            json={
                "model": "qwen2.5:0.5b",
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3}
            },
            timeout=5
        )
        if response.status_code == 200:
            summary = response.json().get("response", "").strip()
            summary = summary.replace('"', '').replace("'", "")
            return summary[:300], True
    except Exception:
        pass
        
    return extract_summary_local(text), False

def get_criticality_rank(text: str) -> int:
    """Вычисление ранга критичности обращения (1-5) по ключевым словам и паттернам."""
    text_lower = text.lower()
    
    # Высокий уровень угрозы (ранг 5)
    if any(w in text_lower for w in ["взрыв", "обрушен", "пожар", "чп"]):
        return 5
    if "больниц" in text_lower and "нет воды" in text_lower:
        return 5
    if any(w in text_lower for w in ["замерза", "замерз", "обморож"]):
        if "остановк" in text_lower or "автобус" in text_lower:
            return 4
        return 5
        
    # Высокий приоритет (ранг 4)
    if any(w in text_lower for w in ["прорыв тепло", "прорвало тепло", "нет отопл", "нет воды"]):
        return 4
    if any(w in text_lower for w in ["ломают ноги", "ломать ноги", "ледниковый период", "затопил", "отключили свет"]):
        return 4
        
    # Транспортные сбои (ранг 3)
    if any(w in text_lower for w in ["автобус", "маршрутк", "рейс", "транспорт", "остановк"]):
        if any(w in text_lower for w in ["не прие", "не прише", "не ход", "отмен", "нет"]):
            return 3
        if "час" in text_lower and any(w in text_lower for w in ["стоя", "жда", "ожида"]):
            return 3

    # Средний приоритет (ранг 3)
    if any(w in text_lower for w in ["огромная яма", "открытый люк", "свалка", "сломалась", "каток", "бассейн во дворе"]):
        return 3
    if "дорог" in text_lower and any(w in text_lower for w in ["колесо"]):
        return 3
    if "дорог" in text_lower and any(w in text_lower for w in ["дыр", "ямы", "колея"]):
        return 2

    # Резервный поиск по словарю
    for rank in sorted(CRITICALITY_KEYWORDS.keys(), reverse=True):
        if any(keyword in text_lower for keyword in CRITICALITY_KEYWORDS[rank]):
            return rank
            
    return 2
