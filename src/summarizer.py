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
    # Медицина
    "врач", "скорая", "больниц", "поликлиник", "приём", "прием",
    "запись", "очередь", "медик", "фельдшер", "аптек", "лекарств",
    "скорую", "не принима", "не приехала",
    # Снег / уборка территории
    "снег", "уборк", "чист", "подмет", "двор", "гололед", "сугроб",
    "не расчист", "не посыпа", "тротуар",
    # Парковка / дороги
    "парков", "стоянк", "машин", "автомобил", "пробк",
    # Администрация / управление
    "контрол", "поруч", "обеспеч", "реагиру", "не реагир",
    # Связь / интернет / газ
    "газ", "газоснабж", "интернет", "связь", "сигнал",
    # Благоустройство
    "детск", "площадк", "фонар", "освещен", "лавочк", "скамейк",
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
    # Обращения к чиновникам — не несут сути проблемы
    "виталий", "уважаемый губернатор", "уважаемый мэр",
    "александр леонидович", "обратитесь к", "поручите мэру",
    "возмитесь пожалуйста", "хотите город", "соболезнование",
)

def _is_filler_sentence(sentence: str) -> bool:
    """Проверяет, является ли предложение чисто шумовым/эмоциональным."""
    s = sentence.lower().strip().lstrip("'\"").strip()
    # Слишком короткое (менее 3 слов) и не содержит проблемных слов
    if len(s.split()) < 3:
        has_problem = any(kw in s for kw in _PROBLEM_KEYWORDS)
        if not has_problem:
            return True
    # Чисто эмоциональное или административное
    if s.startswith(_FILLER_STARTS_TUPLE):
        return True
    return False


def _smart_truncate(text: str, max_chars: int = 300) -> str:
    """Умное обрезание по количеству символов.
    Ищет естественную границу (конец предложения, запятую, союз) перед лимитом.
    Предотвращает обрезание посередине слов, кавычек или скобок.
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    # Обрезаем строку с запасом на троеточие
    limit = max_chars - 3
    if limit <= 0:
        return "..."

    # Пробуем обрезать по последней точке/знаку препинания (. ! ?) в пределах лимита
    # Но знак препинания должен быть достаточно близко к концу лимита (в пределах 60 символов)
    best_cut = -1
    for p in ['. ', '! ', '? ']:
        pos = text[:limit].rfind(p)
        if pos > limit - 60:
            best_cut = max(best_cut, pos + 1)
            
    if best_cut != -1:
        return text[:best_cut].strip() + "..."

    # Пробуем обрезать по запятой или союзу/предлогу
    truncated = text[:limit]
    
    # Ищем последний пробел перед лимитом
    last_space = truncated.rfind(' ')
    if last_space != -1 and last_space > limit - 40:
        truncated = truncated[:last_space]
        
    # Убираем висячие союзы/предлоги в конце
    _BREAK_WORDS = {
        "и", "но", "а", "или", "что", "где", "когда", "потому", "так", "также", "чтобы", 
        "раз", "то", "как", "для", "на", "в", "с", "по", "у", "к", "о", "об", "обо", "из", "от", "до"
    }
    words = truncated.split()
    while words and words[-1].lower().rstrip(",.!:;?") in _BREAK_WORDS:
        words.pop()
    
    truncated = " ".join(words)
    
    # Очищаем от висячих знаков
    truncated = truncated.rstrip(' ,.-:;("«')

    # Закрываем или убираем несбалансированные скобки и кавычки на конце
    if truncated.count('(') > truncated.count(')'):
        last_paren = truncated.rfind('(')
        if last_paren != -1 and last_paren > len(truncated) - 60:
            truncated = truncated[:last_paren].rstrip(' ,.-:;')
            
    if truncated.count('«') > truncated.count('»'):
        last_quote = truncated.rfind('«')
        if last_quote != -1 and last_quote > len(truncated) - 60:
            truncated = truncated[:last_quote].rstrip(' ,.-:;')
            
    if not truncated:
        return text[:limit].rstrip(' ,.-:;("«') + "..."
        
    return truncated + "..."


# Диапазоны Unicode эмодзи для быстрой фильтрации
_EMOJI_PATTERN = None


def _remove_emoji(text: str) -> str:
    """Удаляет эмодзи и спецсимволы соцсетей из текста."""
    global _EMOJI_PATTERN
    import re
    if _EMOJI_PATTERN is None:
        _EMOJI_PATTERN = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # эмодзи лиц
            "\U0001F300-\U0001F5FF"  # символы/картинки
            "\U0001F680-\U0001F6FF"  # транспорт
            "\U0001F1E0-\U0001F1FF"  # флаги
            "\U00002702-\U000027B0"  # доп. символы
            "\U000024C2-\U0001F251"  # прочие
            "\U0001f926-\U0001f937"  # жесты
            "\U00010000-\U0010ffff"  # прочие блоки
            "\u2640-\u2642"          # символы пола
            "\u2600-\u2B55"          # разное
            "\u200d"                 # zero-width joiner
            "\u23cf\u23e9\u231a\ufe0f\u3030"
            "]+",
            re.UNICODE
        )
    return _EMOJI_PATTERN.sub('', text).strip()


def _clean_leading_junk(text: str) -> str:
    """Убирает мусор: эмодзи, апостроф, кавычки, VK-теги, HTML, спецсимволы соцсетей."""
    import re
    # Убираем HTML-теги (<br>, <br/>, <p> и т.д.)
    text = re.sub(r'<[^>]+>', ' ', text)
    # Убираем '[club12345|Название]' и '@упоминания' паттерны ВКонтакте
    text = re.sub(r'\[club\d+\|[^\]]+\],?\s*', '', text)
    text = re.sub(r'\[id\d+\|[^\]]+\],?\s*', '', text)  # [id123|Имя]
    text = re.sub(r'@[\w]+,?\s*', '', text)              # @username
    # Убираем эмодзи из всего текста
    text = _remove_emoji(text)
    # Убираем ведущие не-буквенные символы (включая апостроф в начале)
    text = text.lstrip("'\"«»!?,. ")
    # Схлопываем множественные пробелы
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_summary_local(text: str, max_chars: int = 300, text_lower: str = None) -> str:
    """Оптимизированная быстрая экстрактивная суммаризация.

    1. Быстрый поиск сути по ключевым шаблонам (дает лаконичную выжимку).
    2. Очистка приветствий и шумовых фраз.
    3. Выбор наиболее значимого предложения и его сокращение.

    text_lower — предвычисленный text.lower() (опционально).
    Если передан, повторный .lower() внутри функции не вызывается.
    """
    if not text:
        return ""

    # --- Fallback для очень коротких текстов (<50 символов) ---
    # Чистим и берём текст напрямую как саммари (без LLM/шаблонов)
    stripped_text = _clean_leading_junk(text.strip())
    if len(stripped_text) < 50:
        if not stripped_text:
            return ""
        result = stripped_text[0].upper() + stripped_text[1:] if len(stripped_text) > 1 else stripped_text.upper()
        return result

    t_lower = text_lower if text_lower is not None else text.lower()
    
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
            
    # Железнодорожный переезд / барьеры
    if "переезд" in t_lower:
        if any(w in t_lower for w in ["барьер", "шлагбаум", "не закрыва", "сломан", "не работа"]):
            return "Неисправные барьеры/шлагбаум на железнодорожном переезде"
        if any(w in t_lower for w in ["асфальт", "яма", "разбит", "плохой"]):
            return "Неудовлетворительное состояние дорог на переезде"
        return "Проблемы на железнодорожном переезде"

    # Барьеры / шлагбаумы вне переезда
    if "барьер" in t_lower or "шлагбаум" in t_lower:
        if any(w in t_lower for w in ["сломан", "не работа", "не закрыва", "не открыва"]):
            return "Неисправный барьер/шлагбаум"

    # Ямы / Дороги
    if "яма" in t_lower or "дорог" in t_lower or "выбоин" in t_lower or "асфальт" in t_lower or "колея" in t_lower:
        if any(w in t_lower for w in ["разбит", "ремонт", "плох", "ужасн", "яма", "выбоин"]):
            return "Неудовлетворительное состояние дорожного покрытия"
        if any(w in t_lower for w in ["не чист", "снег", "грязь", "лужа"]):
            return "Неудовлетворительная уборка дорог"

    # Мост / путепровод
    if "мост" in t_lower or "путепровод" in t_lower:
        if any(w in t_lower for w in ["дыр", "яма", "разбит", "аварий", "опасн"]):
            return "Аварийное состояние моста / путепровода"

    # Тротуар
    if "тротуар" in t_lower:
        if any(w in t_lower for w in ["разбит", "яма", "нет", "плох", "снег", "лед", "наледь"]):
            return "Неудовлетворительное состояние тротуара"

    # Метро / пробки / транспортная перегруженность
    if "метро" in t_lower:
        if any(w in t_lower for w in ["нет", "нужн", "необходим", "пробк", "строит"]):
            return "Отсутствие/необходимость метро, транспортные пробки"

    if "пробк" in t_lower:
        if any(w in t_lower for w in ["огромн", "стоим", "стоят", "час", "застрял"]):
            return "Транспортные пробки"

    # Транспорт
    if "автобус" in t_lower or "маршрут" in t_lower or "транспорт" in t_lower or "рейс" in t_lower:
        if any(w in t_lower for w in ["не ход", "отмен", "плохо", "интервал", "не прие"]):
            return "Сбои в расписании общественного транспорта"

    # ЖКХ / управляющая компания
    if "управляющ" in t_lower or " укп" in t_lower or "жкх" in t_lower or "ук " in t_lower:
        if any(w in t_lower for w in ["не реагир", "не приход", "не делает", "бездейств", "игнорир"]):
            return "Бездействие управляющей компании / ЖКХ"

    # Лифт
    if "лифт" in t_lower:
        if any(w in t_lower for w in ["сломан", "не работа", "не ход", "застрял"]):
            return "Неисправный лифт"

    # Подъезд / дом
    if "подъезд" in t_lower:
        if any(w in t_lower for w in ["грязь", "мусор", "запах", "сломан", "не убира"]):
            return "Антисанитария / запустение в подъезде"
        if any(w in t_lower for w in ["дверь", "домофон", "замок", "не закрыва"]):
            return "Неисправная дверь/домофон в подъезде"

    # Крыша / подвал
    if "крыш" in t_lower:
        if any(w in t_lower for w in ["течет", "течь", "протека", "проваливает"]):
            return "Протечка кровли"
    if "подвал" in t_lower:
        if any(w in t_lower for w in ["затопл", "вода", "течет", "запах", "крыс"]):
            return "Подтопление/антисанитария в подвале"
            
    # Мусор
    if "мусор" in t_lower or "свалк" in t_lower or "контейнер" in t_lower or "вывоз" in t_lower:
        if any(w in t_lower for w in ["не вывоз", "переполн", "грязь", "не убира", "лежит", "собак", "раскидали", "завалили"]):
            return "Нарушение графика вывоза мусора / антисанитария"
        # Общий случай: упоминание мусора без конкретики — тоже возвращаем шаблон
        return "Проблемы с вывозом мусора / несанкционированная свалка"
            
    # Канализация / Засор / Люк
    if "засор" in t_lower or "канализ" in t_lower or "вонь" in t_lower or "запах" in t_lower:
        return "Засор канализации / неприятный запах"
    if "люк" in t_lower and ("открыт" in t_lower or "нет крышки" in t_lower):
        return "Открытый люк на дороге/тротуаре"
        
    # Снег / Гололед / Лед
    if "снег" in t_lower or "лед" in t_lower or "наледь" in t_lower or "каток" in t_lower or "гололед" in t_lower:
        if any(w in t_lower for w in ["не убран", "почист", "заносы", "скользко", "уборк", "не чист", "не посыпа"]):
            return "Неудовлетворительная очистка от снега и льда"
        if any(w in t_lower for w in ["упал", "упала", "упали", "поскользн", "травм"]):
            return "Травма из-за гололёда / неубранного льда"

    # Медицина — поликлиника / врач
    if "поликлиник" in t_lower or "врач" in t_lower or "больниц" in t_lower:
        if any(w in t_lower for w in ["нехватк", "нет специалист", "нет врач", "уволил", "медработник"]):
            return "Нехватка медицинских специалистов"
        if any(w in t_lower for w in ["нет", "не принима", "очередь", "запись", "не работа", "закрыт"]):
            return "Проблемы с записью/приёмом у врача"

    # Скорая помощь
    if "скорая" in t_lower or "скорую" in t_lower:
        if any(w in t_lower for w in ["не прие", "долго", "ждём", "ждем", "не едет", "час"]):
            return "Долгое ожидание скорой помощи"

    # Аптека / лекарства
    if "аптек" in t_lower or "лекарств" in t_lower or "препарат" in t_lower:
        if any(w in t_lower for w in ["нет", "нехватк", "отсутств", "не выдают", "закончил"]):
            return "Нехватка лекарств / перебои в аптеке"

    # Парковка
    if "парков" in t_lower or "стоянк" in t_lower:
        if any(w in t_lower for w in ["нет", "мало", "недостаточ", "негде", "не хватает"]):
            return "Нехватка парковочных мест"
        if any(w in t_lower for w in ["брошен", "бросают", "на тротуар", "на газон", "мешают"]):
            return "Несанкционированная парковка на тротуарах/газонах"

    # Освещение
    if "фонар" in t_lower or "освещен" in t_lower or "свет" in t_lower and "улиц" in t_lower:
        if any(w in t_lower for w in ["нет", "не работа", "темно", "сломан", "не горит"]):
            return "Отсутствие уличного освещения"

    # Детская площадка / благоустройство
    if "детск" in t_lower and "площадк" in t_lower:
        if any(w in t_lower for w in ["сломан", "опасн", "разбит", "нет", "плох"]):
            return "Неисправное/опасное оборудование детской площадки"

    # Газоснабжение
    if "газ" in t_lower or "газоснабж" in t_lower:
        if any(w in t_lower for w in ["нет", "отключ", "авари", "утечк", "запах"]):
            return "Проблемы с газоснабжением"

    # Светофор / перекрёсток
    if "светофор" in t_lower or "перекрест" in t_lower or "перекрёст" in t_lower:
        if any(w in t_lower for w in ["не работа", "сломан", "не горит", "отключ", "верни"]):
            return "Неисправный/отключённый светофор на перекрёстке"
        if any(w in t_lower for w in ["пробк", "авари", "дтп", "опасн"]):
            return "Опасная ситуация на перекрёстке"

    # АЗС / бензин / топливо
    if "бензин" in t_lower or "заправк" in t_lower or "азс" in t_lower or "топлив" in t_lower:
        if any(w in t_lower for w in ["нет", "кончил", "дефицит", "не достать", "92", "95", "дизел"]):
            return "Дефицит топлива / проблемы на АЗС"

    # Школа / права детей / образование
    if "школ" in t_lower or "образован" in t_lower or "учебн" in t_lower:
        if any(w in t_lower for w in ["нет мест", "не зачислил", "отказал", "нарушил", "права дет"]):
            return "Нарушение прав при зачислении в школу"
        if any(w in t_lower for w in ["аварийная школа", "аварийное здание школы", "снос школы", "закрытие школы", "школу закрыли", "школа закрыта", "закрывают школу", "рухнул потолок в школе"]):
            return "Закрытие/снос школьного здания"

    # Бассейн / стройка / инфраструктура
    if "бассейн" in t_lower:
        if any(w in t_lower for w in ["снос бассейна", "заморозка строительства бассейна", "недостроенный бассейн", "бассейн не достроили", "бассейн закрыт"]):
            return "Снос/заморозка строительства бассейна"

    # Экология / загрязнение воздуха / промышленность
    if any(w in t_lower for w in ["воздух", "дышат", "дышать", "дым", "смог", "выброс", "загрязн", "экологи", "отходы"]):
        if any(w in t_lower for w in ["нельзя", "плох", "ужас", "вредн", "опасн", "завод", "промышл", "запах"]):
            return "Загрязнение воздуха / экологическая проблема"

    # Животные / бездомные / нападения
    if any(w in t_lower for w in ["собак", "кошк", "бездомн", "бродяч"]):
        if any(w in t_lower for w in ["напал", "кусает", "укусил", "стая", "опасн", "агресс"]):
            return "Нападение бездомных животных / угроза безопасности"

    # Дороги — более широкий охват
    if "дорог" in t_lower or "дорожн" in t_lower or "проезж" in t_lower:
        if any(w in t_lower for w in ["не чист", "снег", "грязь", "лужа"]):
            return "Неудовлетворительная уборка дорог"
        if any(w in t_lower for w in ["перекрыт", "закрыт", "нет проезд"]):
            return "Перекрытие дороги / нет проезда"

    # Двор / придомовая территория
    if "двор" in t_lower:
        if any(w in t_lower for w in ["мусор", "грязь", "не убира", "свалк"]):
            return "Антисанитария во дворе / неубранная территория"
        if any(w in t_lower for w in ["снег", "лед", "наледь", "не чист"]):
            return "Неубранный снег/лёд во дворе"

    # Если шаблоны не сработали, делаем стандартный TextRank
    cleaned = _strip_greeting(text)
    cleaned = _clean_leading_junk(cleaned)  # убираем эмодзи и VK-теги
    if len(cleaned) <= 120:
        result = _clean_filler(cleaned)
        return result if result else cleaned

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

    # Финальная очистка: убираем оставшийся мусор и шумовые фразы
    result = _clean_leading_junk(best)
    result = _clean_filler(result)
    if not result:
        result = _clean_leading_junk(best)

    # Умное обрезание: ищем естественную границу вместо жёсткого лимита
    result = _smart_truncate(result, max_chars=max_chars)

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
        "ОТВЕЧАЙ СТРОГО НА РУССКОМ ЯЗЫКЕ! Использование китайских иероглифов, латиницы или других нерусских символов категорически запрещено. "
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
                    "repetition_penalty": 1.05
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


def generate_district_summary_llm(
    district: str,
    summaries: list[str],
    ollama_url: str = "http://localhost:11434/api/generate",
    source_context: str = "",
) -> str:
    """Генерация связного аналитического отчета по району на основе списка жалоб."""
    if not summaries:
        return f"В районе {district} нет зарегистрированных критических проблем."
        
    problems_text = "\n- ".join(summaries[:3])
    
    system_prompt = (
        "Ты — главный аналитик Центра управления регионом (ЦУР) Омской области. "
        "Напиши одну короткую, связную и красивую аналитическую сводку (до 250 символов) "
        f"о ключевых системных проблемах в районе '{district}' на основе предоставленных жалоб. "
        "ОТВЕЧАЙ СТРОГО НА РУССКОМ ЯЗЫКЕ! Использование китайских иероглифов, латиницы или других нерусских символов категорически запрещено.\n"
        "Правила:\n"
        "1. Пиши емко и лаконично (1-2 предложения от третьего лица).\n"
        "2. Опиши исключительно реальные проблемы из списка (ЖКХ, дороги, транспорт и т.д.). Игнорируй слова благодарности или спам.\n"
        "3. Полностью исключи адреса, имена, даты и любые персональные данные.\n"
        "4. Начни сразу с сути (без 'Анализ показывает...' или 'В районе...'). Не используй списки, кавычки и вводные фразы."
    )
    
    user_prompt = (
        f"Район: {district}\n"
        f"Зафиксированные инциденты:\n"
        f"- {problems_text}\n\n"
        f"Напиши одну лаконичную и красивую фразу о проблемах района:"
    )
    
    try:
        chat_url = ollama_url.replace("/api/generate", "/api/chat")
        response = requests.post(
            chat_url,
            json={
                "model": "qwen2.5:1.5b",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "stream": False,
                "options": {
                    "temperature": 0.25,
                    "repetition_penalty": 1.05
                }
            },
            timeout=30
        )
        if response.status_code == 200:
            summary = response.json().get("message", {}).get("content", "").strip()
            # Убираем кавычки
            summary = summary.replace('"', '').replace("'", "")
            return summary
    except Exception:
        pass
    return "; ".join(summaries[:3])
