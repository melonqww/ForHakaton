"""
StreamingExcelExporter — быстрая потоковая запись xlsx.

Использует xlsxwriter вместо openpyxl:
  • constant_memory=True  — строки пишутся на диск по одной (не хранятся в RAM)
  • В 5-10x быстрее openpyxl для файлов > 50k строк
  • Меньше RAM: нет накопления всех строк в памяти
"""
import pandas as pd
import xlsxwriter

from src.config import CATEGORIES
from src.utils import find_column_index


class StreamingExcelExporter:
    def __init__(
        self,
        output_path: str,
        headers: list,
        text_col: int,
        group_col: int,
        rank_col: int,
        summary_col: int,
        type_col: int,
    ):
        self.output_path = output_path
        self.headers     = headers

        # Храним как 0-based индексы (xlsxwriter — 0-based)
        self.text_col    = text_col
        self.group_col   = group_col
        self.rank_col    = rank_col
        self.summary_col = summary_col
        self.type_col    = type_col

        # ── Workbook с потоковой записью ────────────────────────────────────
        # constant_memory=True: каждая строка записывается на диск сразу —
        # память не растёт вместе с файлом.
        self.wb = xlsxwriter.Workbook(output_path, {
            "constant_memory":    True,
            "strings_to_numbers": False,   # не конвертируем строки в числа
        })

        # Форматы нужно создавать ДО начала записи строк
        self._fmt_header = self.wb.add_format({
            "font_name": "Calibri", "font_size": 11, "bold": True,
            "bg_color":  "#2B4C7E", "font_color": "#FFFFFF",
            "align":     "center",  "valign": "vcenter", "text_wrap": True,
        })
        self._fmt_normal = self.wb.add_format({
            "font_name": "Calibri", "font_size": 11,
        })
        self._fmt_center = self.wb.add_format({
            "font_name": "Calibri", "font_size": 11, "align": "center",
        })
        self._fmt_wrap = self.wb.add_format({
            "font_name": "Calibri", "font_size": 11, "text_wrap": True,
        })
        self._fmt_rank_ok   = self.wb.add_format({
            "font_name": "Calibri", "font_size": 11,
            "align": "center", "bg_color": "#E2F0D9",  # зелёный (1-2)
        })
        self._fmt_rank_warn = self.wb.add_format({
            "font_name": "Calibri", "font_size": 11,
            "align": "center", "bg_color": "#FFF2CC",  # жёлтый (3)
        })
        self._fmt_rank_crit = self.wb.add_format({
            "font_name": "Calibri", "font_size": 11,
            "align": "center", "bg_color": "#FCE4D6",  # красный (4-5)
        })

        # ── Листы: сначала «Данные» (активный), потом «Сводка» ─────────────
        self.ws         = self.wb.add_worksheet("Данные")
        self.ws_summary = self.wb.add_worksheet("Сводка")

        # Закрепляем шапку
        self.ws.freeze_panes(1, 0)

        # Шапка
        for col_idx, col_name in enumerate(headers):
            self.ws.write(0, col_idx, col_name, self._fmt_header)

        self.row_count  = 1                              # следующая строка (0-based)
        self.col_widths = [len(str(h)) for h in headers]  # ширина по заголовкам

    # ── Запись строки данных ─────────────────────────────────────────────────
    def write_row(self, row_data: list):
        for col_idx, val in enumerate(row_data):
            # None / NaN → пустая строка
            if val is None or (isinstance(val, float) and val != val):
                self.ws.write(self.row_count, col_idx, "", self._fmt_normal)
                continue

            # Даты в первых двух колонках → строка
            if col_idx < 2 and hasattr(val, "strftime"):
                self.ws.write(
                    self.row_count, col_idx,
                    val.strftime("%Y-%m-%d %H:%M:%S"),
                    self._fmt_normal,
                )
                continue

            # Ранг критичности → цветная ячейка
            if col_idx == self.rank_col:
                rank = int(val) if isinstance(val, (int, float)) else 1
                fmt = (
                    self._fmt_rank_crit if rank >= 4
                    else self._fmt_rank_warn if rank == 3
                    else self._fmt_rank_ok
                )
                self.ws.write_number(self.row_count, col_idx, rank, fmt)
                continue

            # Текстовые/саммари колонки → с переносом
            if col_idx in (self.text_col, self.summary_col):
                self.ws.write(self.row_count, col_idx, val, self._fmt_wrap)
                continue

            self.ws.write(self.row_count, col_idx, val, self._fmt_normal)

        # Ширина колонок — считаем по первым 1000 строкам
        if self.row_count <= 1000:
            for col_idx, val in enumerate(row_data):
                if col_idx < len(self.col_widths):
                    vl = len(str(val or ""))
                    if vl > self.col_widths[col_idx]:
                        self.col_widths[col_idx] = vl

        self.row_count += 1

    # ── Финализация файла ────────────────────────────────────────────────────
    def close(self, stats: dict):
        # Ширина колонок для листа «Данные»
        for col_idx, width in enumerate(self.col_widths):
            if col_idx in (self.text_col, self.summary_col) or (
                col_idx < len(self.headers)
                and self.headers[col_idx] == "Очищенный текст"
            ):
                self.ws.set_column(col_idx, col_idx, 40)
            else:
                self.ws.set_column(col_idx, col_idx, min(max(width + 3, 10), 25))

        # Автофильтр на весь диапазон данных
        if self.row_count > 1:
            self.ws.autofilter(0, 0, self.row_count - 1, len(self.headers) - 1)

        # Лист аналитической сводки
        self._write_summary(stats)

        # close() — здесь xlsxwriter финализирует ZIP (значительно быстрее openpyxl)
        self.wb.close()

    # ── Лист «Сводка» ────────────────────────────────────────────────────────
    def _write_summary(self, stats: dict):
        ws = self.ws_summary
        wb = self.wb

        f_title   = wb.add_format({"font_name": "Calibri", "font_size": 14, "bold": True, "font_color": "#2B4C7E"})
        f_section = wb.add_format({"font_name": "Calibri", "font_size": 12, "bold": True})
        f_bold    = wb.add_format({"font_name": "Calibri", "font_size": 11, "bold": True})
        f_normal  = wb.add_format({"font_name": "Calibri", "font_size": 11})
        f_hdr     = wb.add_format({
            "font_name": "Calibri", "font_size": 11, "bold": True,
            "bg_color": "#2B4C7E", "font_color": "#FFFFFF",
            "align": "center", "valign": "vcenter",
        })
        f_center  = wb.add_format({"font_name": "Calibri", "font_size": 11, "align": "center"})
        f_wrap    = wb.add_format({"font_name": "Calibri", "font_size": 11, "text_wrap": True})
        f_green   = wb.add_format({"font_name": "Calibri", "font_size": 11, "font_color": "#375623", "bg_color": "#E2F0D9"})
        f_red     = wb.add_format({"font_name": "Calibri", "font_size": 11, "font_color": "#843C0C", "bg_color": "#FCE4D6", "bold": True})

        r = 0
        ws.write(r, 0, "Сводный анализ обращений граждан", f_title); r += 1
        ws.write(r, 0, ""); r += 1

        total    = stats.get("total_count", 0)
        problems = stats.get("problems_count", 0)
        spam     = total - problems

        ws.write(r, 0, "Всего обращений:",    f_bold); ws.write(r, 1, total,    f_normal); r += 1
        ws.write(r, 0, "Реальных проблем:",   f_bold); ws.write(r, 1, problems, f_green);  r += 1
        ws.write(r, 0, "Спам/благодарности:", f_bold); ws.write(r, 1, spam,     f_normal); r += 1
        ws.write(r, 0, ""); r += 1

        # ТОП-3
        ws.write(r, 0, "ТОП-3 проблемных муниципалитета", f_section); r += 1
        for col_idx, h in enumerate(
            ["Район", "Обращений", "Основная категория", "Ср. критичность", "Критичных (4-5)", "Ключевые проблемы"]
        ):
            ws.write(r, col_idx, h, f_hdr)
        r += 1

        for item in stats.get("top3_districts", []):
            crit     = item.get("critical_count", 0)
            avg_rank = round(item.get("avg_rank", 0), 1)
            ws.write(r, 0, item["district"],      f_bold)
            ws.write(r, 1, item["count"],          f_center)
            ws.write(r, 2, item["top_cat"],        f_normal)
            ws.write(r, 3, avg_rank,               f_center)
            ws.write(r, 4, crit, f_red if crit > 0 else f_center)
            ws.write(r, 5, item.get("key_problems", ""), f_wrap)
            r += 1

        ws.write(r, 0, ""); r += 1

        # ТОП-10
        ws.write(r, 0, "ТОП-10 районов по количеству обращений", f_section); r += 1
        for col_idx, h in enumerate(
            ["Район", "Обращений", "Основная категория", "Ср. критичность"]
        ):
            ws.write(r, col_idx, h, f_hdr)
        r += 1

        for item in stats.get("top10_districts", []):
            ws.write(r, 0, item["district"],           f_normal)
            ws.write(r, 1, item["count"],              f_center)
            ws.write(r, 2, item["top_cat"],            f_normal)
            ws.write(r, 3, round(item.get("avg_rank", 0), 1), f_center)
            r += 1

        ws.set_column(0, 0, 25)
        ws.set_column(1, 1, 14)
        ws.set_column(2, 2, 25)
        ws.set_column(3, 3, 18)
        ws.set_column(4, 4, 18)
        ws.set_column(5, 5, 60)


# ── Обёртка для DataFrame-ориентированного использования ────────────────────
def export_to_excel(df: pd.DataFrame, output_path: str):
    """Совместимость с DataFrame-ориентированными тестами и утилитами."""
    headers   = list(df.columns)
    cols_list = headers

    text_col    = find_column_index(df, "text", 36)
    group_col   = find_column_index(df, "group", 21)
    rank_col    = cols_list.index("Ранг критичности")    if "Ранг критичности"    in cols_list else None
    summary_col = cols_list.index("Краткое саммари")     if "Краткое саммари"     in cols_list else None
    type_col    = cols_list.index("Тип инцидента")       if "Тип инцидента"       in cols_list else None

    df_problems = df[df["Тип инцидента"] == "Проблема"] if "Тип инцидента" in df.columns else df

    stats: dict = {
        "total_count":    len(df),
        "problems_count": len(df_problems),
        "top3_districts":  [],
        "top10_districts": [],
    }

    if not df_problems.empty and "Нормализованное Гео" in df.columns:
        group_col_name = df.columns[find_column_index(df, "group", 21)]

        for n, top_n in [(3, "top3_districts"), (10, "top10_districts")]:
            top = df_problems["Нормализованное Гео"].value_counts().head(n)
            result = []
            for district, count in top.items():
                d_df    = df_problems[df_problems["Нормализованное Гео"] == district]
                cats    = d_df[group_col_name].value_counts()
                top_cat = cats.index[0] if not cats.empty else ""
                avg_r   = d_df["Ранг критичности"].mean() if "Ранг критичности" in d_df.columns else 0
                crit    = (
                    len(d_df[d_df["Ранг критичности"] >= 4])
                    if "Ранг критичности" in d_df.columns else 0
                )
                key_probs = ""
                if "Краткое саммари" in d_df.columns and "Ранг критичности" in d_df.columns:
                    sums = d_df[d_df["Ранг критичности"] >= 4]["Краткое саммари"].head(3).tolist()
                    key_probs = "; ".join(s for s in sums if s)

                entry = {"district": district, "count": count, "top_cat": top_cat,
                         "avg_rank": avg_r, "critical_count": crit, "key_problems": key_probs}
                result.append(entry)
            stats[top_n] = result

    exporter = StreamingExcelExporter(
        output_path, headers, text_col, group_col, rank_col, summary_col, type_col
    )
    for row in df.values.tolist():
        exporter.write_row(row)
    exporter.close(stats)
