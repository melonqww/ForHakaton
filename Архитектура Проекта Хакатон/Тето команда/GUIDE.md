# Руководство по работе с библиотеками оптимизации (Python Cookbook)

Привет! В этом гайде собраны простые и наглядные примеры работы с библиотеками, которые используются в нашем пайплайне для быстрой обработки данных. Он поможет быстро разобраться, как устроено чтение тяжелых таблиц, нечеткий поиск и стриминговая генерация отчетов

---

## 1. Чтение больших Excel-файлов (Pandas + Calamine)

Если читать тяжелые Excel-файлы обычным способом, Python загрузит всю таблицу в оперативную память целиком вместе со всеми ненужными колонками. Это долго и часто приводит к зависанию системы

Чтобы этого избежать, мы считываем только нужные колонки с помощью движка `calamine` (он работает на Rust под капотом и читает данные в разы быстрее):

```python
import pandas as pd

# Установка: pip install python-calamine

INPUT_FILE = "ИМ_29_05_2026_prod(1).xlsx"

# Задаем индексы только тех колонок, которые нам реально нужны для работы:
# (дата создания, дата закрытия, группа тем, тема, район, поселок, текст инцидента)
columns_to_load = [19, 20, 21, 22, 24, 25, 36]

# Читаем только выбранные колонки через calamine
df = pd.read_excel(
    INPUT_FILE, 
    usecols=columns_to_load, 
    engine="calamine"
)

print(f"Успешно загружено строк: {len(df)}")
```

---

## 2. Нечеткое сопоставление строк (RapidFuzz + lru_cache)

В реестрах названия районов часто написаны с опечатками (например, "Исикуль" вместо "Исилькуль"). Чтобы привести их к единому справочнику, мы используем нечеткий поиск Левенштейна. А чтобы не вычислять схожесть слов повторно на каждой строке, мы кэшируем результаты

```python
import functools
from rapidfuzz import process, utils

# Справочник районов Омской области
OMSK_DISTRICTS = ["Азовский немецкий национальный р-н", "Тарский р-н", "Черлакский р-н", "г. Омск"]

# Декоратор lru_cache сохраняет результаты прошлых вызовов.
# Если мы опять передадим ту же опечатку, ответ мгновенно вернется из памяти
@functools.lru_cache(maxsize=512)
def normalize_district(raw_name: str) -> str:
    if not raw_name:
        return "Неизвестный р-н"
    
    # Ищем наиболее похожее название из справочника
    match = process.extractOne(
        raw_name, 
        OMSK_DISTRICTS, 
        processor=utils.default_process, # Приводит к нижнему регистру и чистит знаки препинания
        score_cutoff=75.0  # Минимальный порог совпадения в процентах
    )
    
    return match[0] if match else raw_name

# Тест:
print(normalize_district("Исикул"))  # Найдет совпадение в справочнике
print(normalize_district("Исикул"))  # Вернет из кэша мгновенно
```

---

## 3. Стриминговая запись в Excel (openpyxl write-only)

При генерации отчетов на сотни тысяч строк обычные инструменты сначала собирают всю таблицу в памяти и только потом сохраняют. Это вызывает перегрузку ОЗУ и падение скрипта

Режим `write-only` записывает строки в файл последовательно (потоком), сбрасывая их на диск чанками через буфер. Оперативная память при этом не забивается

```python
import openpyxl
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import PatternFill, Font

output_path = "output_optimized.xlsx"

# Создаем книгу в потоковом режиме записи
wb = openpyxl.Workbook(write_only=True)
ws = wb.create_sheet("Данные")

# Стили оформления шапки
header_fill = PatternFill(start_color="2B4C7E", end_color="2B4C7E", fill_type="solid")
header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

# Добавляем шапку
headers = ["Дата", "Район", "Текст обращения", "Статус"]
header_row = []
for h in headers:
    cell = WriteOnlyCell(ws, value=h)
    cell.fill = header_fill
    cell.font = header_font
    header_row.append(cell)

ws.append(header_row)

# Добавление данных (построчно сбрасываем на диск)
for i in range(100000):
    row = ["2026-06-06", "Омский р-н", f"Жалоба №{i}", "Проблема"]
    ws.append(row) # Записывается напрямую на диск, ОЗУ стабильна

wb.save(output_path)
wb.close()
```

---

## 4. Веб-интерфейс (Streamlit)

`Streamlit` позволяет сделать веб-интерфейс для скрипта за несколько минут без верстки и работы с фронтендом. Скрипт просто выполняется сверху вниз каждый раз, когда пользователь нажимает кнопку или меняет параметры

```python
import streamlit as st
import pandas as pd

# Запуск в терминале: streamlit run script.py

st.title("Анализ обращений")
st.write("Загрузите файл для обработки:")

# Кнопка загрузки файла в браузере
uploaded_file = st.file_uploader("Выберите Excel файл", type=["xlsx"])

if uploaded_file is not None:
    # Читаем первые 10 строк
    df = pd.read_excel(uploaded_file, nrows=10)
    
    # Отображаем интерактивную таблицу
    st.dataframe(df)
    
    # Кнопка для запуска обработки
    if st.button("Начать обработку"):
        st.success("Обработка запущена!")
```
