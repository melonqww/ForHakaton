import re
import requests
from src.config import CRITICALITY_KEYWORDS

SENTENCE_SPLIT_REGEX = re.compile(
    r'(?<=(?<!\bs)(?<!\bд)(?<!\bг)(?<!\bп)(?<!\bул)(?<!\bкв)(?<!\bобл)(?<!\bр-н)(?<!\bрп)(?<!\bим)[.!?])\s+',
    re.IGNORECASE
)

# ──────────────────────────────────────────────────────────────
# Словари для интеллектуальной экстрактивной суммаризации
# ──────────────────────────────────────────────────────────────

# Приветствия и обращения, которые нужно вырезать из начала текста
_GREETING_PREFIXES = (
    "здравствуйте", "добрый день", "добрый вечер", "доброе утро",
    "привет", "приветствую", "уважаем", "доброго времени",
    "добрый", "уважаемая", "уважаемый",
)

# Шумовые фразы — не несут информации о проблеме
_FILLER_PHRASES = [
    "просим принять меры", "примите меры", "примите срочные меры",
    "сделайте что-нибудь", "надеемся на вашу", "надеемся на оперативн",
    "просим разобраться", "ждем решения", "помогите решить",
    "прошу разобраться", "просим обратить внимание",
    "вынуждены обратиться", "на наши обращения",
    "получаем только отписки", "сколько можно это терпеть",
    "когда это закончится", "доколе", "сколько можно",
    "лопнуло терпение", "крайне возмущены",
    "обратите внимание", "прошу вас", "просим вас",
    "звонили в диспетчерскую", "звонили уже несколько раз",
    "заявка принята и никто не едет",
    "пишем вам от лица", "надеемся на вашу оперативную",
    "обещали сделать все вовремя", "до сих пор тишина",
    "жители крайне возмущены таким отношением",
    "это продолжается уже не первый день",
]

# Ключевые слова проблем — повышают вес предложения
_PROBLEM_KEYWORDS = [
    "нет", "сломал", "яма", "дыр", "прорыв", "авари", "затопил",
    "отключ", "не работа", "замерз", "разруш", "обрушен", "пожар",
    "течет", "течь", "проры", "засор", "мусор", "грязь", "лужа",
    "холод", "дубак", "открытый люк", "не ход", "отмен", "переполн",
    "вонь", "запах", "ямы", "выбоин", "наледь", "каток", "падают",
    "ломают", "прорвало", "хлещет", "ледяны", "нет воды", "нет света",
    "нет отопл", "не приех", "не прише", "опасн", "угроз",
    "не убира", "свалк", "разбит", "трещин",
]

# ──────────────────────────────────────────────────────────────


def split_into_sentences(text: str) -> list:
    """Разбиение текста на предложения с фильтрацией сокращений."""
    return [s.strip() for s in SENTENCE_SPLIT_REGEX.split(text) if s.strip()]


def _strip_greeting(text: str) -> str:
    """Удаляет приветственные фразы из начала текста."""
    stripped = text.lstrip()
    lower = stripped.lower()
    
    for greeting in _GREETING_PREFIXES:
        if lower.startswith(greeting):
            # Отрезаем приветствие и идущие за ним знаки/пробелы
            tail = stripped[len(greeting):].lstrip(" .,!:;")
            if tail:
                # Поднимаем первую букву
                return tail[0].upper() + tail[1:] if len(tail) > 1 else tail.upper()
    return stripped


def _clean_filler(text: str) -> str:
    """Удаляет шумовые фразы из текста, оставляя только суть."""
    result = text
    lower = result.lower()
    for filler in _FILLER_PHRASES:
        idx = lower.find(filler)
        if idx != -1:
            # Удаляем от начала filler до конца предложения (до точки/запятой или конца)
            end = idx + len(filler)
            # Ищем конец фразы-филлера
            while end < len(result) and result[end] not in '.!?\n':
                end += 1
            if end < len(result):
                end += 1  # включаем знак препинания
            result = result[:idx].rstrip(', ') + ' ' + result[end:].lstrip()
            result = result.strip()
            lower = result.lower()
    
    return result.strip(' ,.')  if result.strip(' ,.') else text


_FILLER_STARTS_TUPLE = (
    "сделайте что-нибудь", "примите меры", "помогите",
    "когда это закончится", "сколько можно", "доколе",
    "на наши обращения", "на наши письменные",
    "пишем вам от лица", "надеемся на вашу",
    "вынуждены обратиться", "прошлый раз обещали",
    "звонили в диспетчерскую", "звонили уже",
    "это продолжается уже", "лопнуло терпение",
    "жители крайне возмущены", "просим обратить",
    "ситуация аварийная, просим", "прошу разобраться",
    "объявлений не было",
)

def _is_filler_sentence(sentence: str) -> bool:
    """Проверяет, является ли предложение чисто шумовым/эмоциональным."""
    s = sentence.lower().strip()
    # Слишком короткое (менее 3 слов) и не содержит проблемных слов
    if len(s.split()) < 3:
        has_problem = any(kw in s for kw in _PROBLEM_KEYWORDS)
        if not has_problem:
            return True
    # Чисто эмоциональное или административное
    if s.startswith(_FILLER_STARTS_TUPLE):
        return True
    return False


def extract_summary_local(text: str, max_chars: int = 300) -> str:
    """Оптимизированная быстрая экстрактивная суммаризация.
    
    1. Быстрый поиск сути по ключевым шаблонам (дает лаконичную выжимку).
    2. Очистка приветствий и шумовых фраз.
    3. Выбор наиболее значимого предложения и его сокращение.
    """
    if not text:
        return ""
        
    t_lower = text.lower()
    
    # --- Шаблоны ключевых проблем для мгновенной выжимки ---
    # Отопление
    if "отопл" in t_lower or "тепло" in t_lower or "замерз" in t_lower:
        if any(w in t_lower for w in ["нет", "отключ", "холод", "дубак"]):
            return "Отсутствие или слабое отопление"
        if any(w in t_lower for w in ["прорыв", "прорва", "течет", "авари"]):
            return "Авария/прорыв системы отопления"
            
    # Горячая вода
    if "горяч" in t_lower and ("вод" in t_lower or "гвс" in t_lower):
        if any(w in t_lower for w in ["нет", "отключ", "отсутств"]):
            return "Отсутствие горячей воды"
            
    # Холодная вода
    if "холодн" in t_lower and ("вод" in t_lower or "хвс" in t_lower):
        if any(w in t_lower for w in ["нет", "отключ", "отсутств"]):
            return "Отсутствие холодной воды"
            
    # Общая вода
    if "вод" in t_lower or "водосн" in t_lower:
        if any(w in t_lower for w in ["нет", "отключ", "отсутств"]):
            return "Отсутствие водоснабжения"
        if any(w in t_lower for w in ["прорыв", "прорва", "течет", "авари"]):
            return "Прорыв водопровода / утечка воды"
            
    # Свет / Электричество
    if "свет" in t_lower or "электр" in t_lower or "энерг" in t_lower:
        if any(w in t_lower for w in ["нет", "отключ", "отсутств"]):
            return "Отсутствие электроснабжения"
            
    # Ямы / Дороги
    if "яма" in t_lower or "дорог" in t_lower or "выбоин" in t_lower or "асфальт" in t_lower or "колея" in t_lower:
        if any(w in t_lower for w in ["разбит", "ремонт", "плох"]):
            return "Неудовлетворительное состояние дорожного покрытия"
            
    # Транспорт
    if "автобус" in t_lower or "маршрут" in t_lower or "транспорт" in t_lower or "рейс" in t_lower:
        if any(w in t_lower for w in ["не ход", "отмен", "плохо", "интервал"]):
            return "Сбои в расписании общественного транспорта"
            
    # Мусор
    if "мусор" in t_lower or "свалк" in t_lower or "контейнер" in t_lower or "вывоз" in t_lower:
        if any(w in t_lower for w in ["не вывоз", "переполн", "грязь"]):
            return "Нарушение графика вывоза мусора / свалка"
            
    # Канализация / Засор / Люк
    if "засор" in t_lower or "канализ" in t_lower or "вонь" in t_lower or "запах" in t_lower:
        return "Засор канализации / неприятный запах"
    if "люк" in t_lower and ("открыт" in t_lower or "нет крышки" in t_lower):
        return "Открытый люк на дороге/тротуаре"
        
    # Снег / Гололед / Лед
    if "снег" in t_lower or "лед" in t_lower or "наледь" in t_lower or "каток" in t_lower:
        if any(w in t_lower for w in ["не убран", "почист", "заносы", "скользко"]):
            return "Неудовлетворительная очистка от снега и льда"

    # Если шаблоны не сработали, делаем стандартный TextRank
    cleaned = _strip_greeting(text)
    if len(cleaned) <= 120:
        return _clean_filler(cleaned)
        
    sentences = split_into_sentences(cleaned)
    if not sentences:
        return _clean_filler(cleaned[:max_chars])
        
    content_sentences = [s for s in sentences if not _is_filler_sentence(s)]
    if not content_sentences:
        content_sentences = sentences
        
    # Скоринг предложений
    scored = []
    for idx, sentence in enumerate(content_sentences):
        words = sentence.lower().split()
        word_count = len(words)
        if word_count == 0:
            continue
            
        pos_score = 10.0 if idx == 0 else (5.0 if idx == 1 else (2.0 if idx == 2 else 1.0))
        len_score = 3.0 if 5 <= word_count <= 25 else (-5.0 if word_count < 4 else 1.0)
        
        s_lower = sentence.lower()
        kw_hits = sum(1 for kw in _PROBLEM_KEYWORDS if kw in s_lower)
        kw_score = 3.0 * min(kw_hits, 5)
        
        score = pos_score + len_score + kw_score
        scored.append((score, idx, sentence))
        
    if not scored:
        return _clean_filler(cleaned[:max_chars])
        
    scored.sort(key=lambda x: -x[0])
    best = scored[0][2]
    
    # Финальная очистка
    result = _clean_filler(best)
    if not result:
        result = best
        
    # Делаем настоящую короткую выжимку (обрезаем до 12 слов, если предложение длинное)
    words = result.split()
    if len(words) > 12:
        result = " ".join(words[:12]) + "..."
        
    return result


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
                "options": {
                    "temperature": 0.3,
                    "repetition_penalty": 1.2
                }
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


def get_criticality_rank(text_lower: str) -> int:
    """Вычисление ранга критичности обращения (1-5) по ключевым словам и паттернам.
    
    Принимает уже готовый text.lower() для избежания повторного вычисления.
    """
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

    return 2


def generate_district_summary_llm(district: str, summaries: list[str], ollama_url: str = "http://localhost:11434/api/generate") -> str:
    """Генерация связного аналитического отчета по району на основе списка жалоб."""
    if not summaries:
        return f"В районе {district} нет зарегистрированных критических проблем."
        
    problems_text = "\n- ".join(summaries)
    prompt = (
        f"Ты — аналитик центра управления регионом Омской области. Напиши один связный аналитический абзац (до 400 символов) "
        f"от третьего лица о ключевых проблемах в районе '{district}'. Объясни с точки зрения аналитика, какие основные системные проблемы "
        f"вызвали поток жалоб (например, почему район оказался в лидерах по обращениям), опираясь на следующий список инцидентов:\n"
        f"- {problems_text}\n\n"
        f"Правила:\n"
        f"1. Полностью исключи любые даты, время (например, 'в 10:00', 'вчера', '05.06') или персональные данные.\n"
        f"2. Пиши строго как профессиональный аналитик, структурирующий суть жалоб.\n"
        f"3. Обобщай суть проблем, не копируя текст инцидентов дословно.\n"
        f"4. Не используй списки, кавычки, приветствия и вводные фразы.\n"
        f"5. Пиши строго по фактам из предоставленного списка, не выдумывая внешних деталей."
    )
    try:
        response = requests.post(
            ollama_url,
            json={
                "model": "qwen2.5:0.5b",
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "repetition_penalty": 1.2
                }
            },
            timeout=20
        )
        if response.status_code == 200:
            summary = response.json().get("response", "").strip()
            # Убираем кавычки
            summary = summary.replace('"', '').replace("'", "")
            return summary
    except Exception:
        pass
    return ""
