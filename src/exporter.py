import pandas as pd
import xlsxwriter


class StreamingExcelExporter:
    """Creates a compact final Excel report from aggregated processing stats."""

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
        self.wb = xlsxwriter.Workbook(output_path, {"strings_to_numbers": False})

        self.f_title = self.wb.add_format({
            "font_name": "Calibri", "font_size": 16, "bold": True,
            "font_color": "#0B2F3A",
        })
        self.f_section = self.wb.add_format({
            "font_name": "Calibri", "font_size": 12, "bold": True,
            "font_color": "#0B2F3A",
        })
        self.f_header = self.wb.add_format({
            "font_name": "Calibri", "font_size": 11, "bold": True,
            "bg_color": "#0E5F76", "font_color": "#FFFFFF",
            "align": "center", "valign": "vcenter", "text_wrap": True,
            "border": 1,
        })
        self.f_normal = self.wb.add_format({
            "font_name": "Calibri", "font_size": 11,
            "valign": "top",
        })
        self.f_wrap = self.wb.add_format({
            "font_name": "Calibri", "font_size": 11,
            "valign": "top", "text_wrap": True,
        })
        self.f_number = self.wb.add_format({
            "font_name": "Calibri", "font_size": 11,
            "align": "center", "valign": "top",
        })
        self.f_metric = self.wb.add_format({
            "font_name": "Calibri", "font_size": 13, "bold": True,
            "align": "center", "valign": "vcenter",
            "bg_color": "#E4F3F1", "font_color": "#0B2F3A",
            "border": 1,
        })
        self.f_metric_label = self.wb.add_format({
            "font_name": "Calibri", "font_size": 10,
            "align": "center", "valign": "vcenter",
            "bg_color": "#F3FBF8", "font_color": "#385A61",
            "border": 1, "text_wrap": True,
        })

    def write_row(self, row_data: list):
        # Processing still forms rows like the reference version, but the final
        # workbook is a compact management report, not a full row dump.
        return

    def close(self, stats: dict):
        self._write_overview(stats)
        self._write_all_districts(stats)
        self._write_top3(stats)
        self._write_top10(stats)
        self._write_categories(stats)
        self._write_attention(stats)
        self._write_ranks(stats)
        self.wb.close()

    def _district_count(self, stats: dict) -> int:
        district_stats = stats.get("district_stats", {})
        if district_stats:
            return len([name for name, data in district_stats.items() if data.get("count", 0) > 0])
        return len(stats.get("district_counts", {}))

    def _critical_total(self, stats: dict) -> int:
        total = 0
        for rank, count in stats.get("rank_counts", {}).items():
            try:
                if int(rank) >= 4:
                    total += int(count)
            except Exception:
                pass
        return total

    def _reason_text(self, item: dict) -> str:
        reason = str(item.get("key_problems") or "").strip()
        if reason:
            return reason
        top_cat = str(item.get("top_cat") or "").strip()
        if top_cat:
            return f"Район попал в топ из-за большого числа обращений по теме: {top_cat}."
        return "Район попал в топ из-за большого числа обращений с проблемами."

    def _write_metric(self, ws, row: int, col: int, label: str, value):
        ws.write(row, col, value, self.f_metric)
        ws.write(row + 1, col, label, self.f_metric_label)

    def _write_table(self, ws, start_row: int, headers: list[str], rows: list[list], *, autofilter: bool = True):
        for col, header in enumerate(headers):
            ws.write(start_row, col, header, self.f_header)
        for r_idx, row in enumerate(rows, start=start_row + 1):
            for c_idx, value in enumerate(row):
                fmt = self.f_wrap if isinstance(value, str) and len(value) > 35 else self.f_normal
                if isinstance(value, (int, float)):
                    fmt = self.f_number
                ws.write(r_idx, c_idx, value, fmt)
        if rows and autofilter:
            ws.autofilter(start_row, 0, start_row + len(rows), len(headers) - 1)

    def _write_overview(self, stats: dict):
        ws = self.wb.add_worksheet("Итоги")
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 20)
        ws.set_column(1, 1, 30)
        ws.set_column(2, 4, 18)
        ws.set_column(5, 5, 34)
        ws.set_column(6, 6, 72)

        total = int(stats.get("total_count", 0))
        problems = int(stats.get("problems_count", 0))
        no_action = max(total - problems, 0)
        districts = self._district_count(stats)
        critical = self._critical_total(stats)

        ws.write(0, 0, "Сводный отчет по обращениям", self.f_title)
        ws.write(2, 0, "Ключевые показатели", self.f_section)

        metrics = [
            ("Всего обращений", total),
            ("Найдено проблем", problems),
            ("Не требует решения", no_action),
            ("Всего районов", districts),
            ("Срочные проблемы 4-5", critical),
        ]
        for idx, (label, value) in enumerate(metrics):
            self._write_metric(ws, 4, idx, label, value)

        ws.write(8, 0, "Где больше всего проблем", self.f_section)
        top_rows = []
        for idx, item in enumerate(stats.get("top3_districts", []), start=1):
            top_rows.append([
                idx,
                item.get("district", ""),
                item.get("count", 0),
                round(float(item.get("avg_rank", 0) or 0), 1),
                item.get("critical_count", 0),
                item.get("top_cat", ""),
                self._reason_text(item),
            ])
        self._write_table(
            ws,
            10,
            ["Место", "Район", "Проблем", "Средняя важность", "Срочных 4-5", "Главная тема", "Кратко"],
            top_rows,
            autofilter=False,
        )

        start = 14 + max(len(top_rows), 1)
        ws.write(start, 0, "Какие темы встречаются чаще всего", self.f_section)
        theme_rows = []
        total_problems = max(problems, 1)
        for idx, (category, count) in enumerate(
            sorted(stats.get("category_counts", {}).items(), key=lambda x: x[1], reverse=True)[:8],
            start=1,
        ):
            theme_rows.append([idx, category, count, round(count / total_problems * 100, 1)])
        self._write_table(ws, start + 2, ["Место", "Тема", "Количество", "Доля, %"], theme_rows, autofilter=False)

        start = start + 5 + max(len(theme_rows), 1)
        ws.write(start, 0, "Какие проблемы требуют внимания", self.f_section)
        attention_rows = self._attention_rows(stats, limit=5)
        self._write_table(
            ws,
            start + 2,
            ["Район", "Срочных 4-5", "Всего проблем", "Главная тема", "Почему важно"],
            attention_rows,
            autofilter=False,
        )

    def _write_all_districts(self, stats: dict):
        ws = self.wb.add_worksheet("Все районы")
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 10)
        ws.set_column(1, 1, 30)
        ws.set_column(2, 4, 18)
        ws.set_column(5, 5, 28)
        ws.set_column(6, 6, 70)

        rows = []
        sorted_districts = sorted(
            stats.get("district_stats", {}).items(),
            key=lambda x: x[1].get("count", 0),
            reverse=True,
        )
        for idx, (district, d_stats) in enumerate(sorted_districts, start=1):
            sorted_cats = sorted(d_stats.get("categories", {}).items(), key=lambda x: x[1], reverse=True)
            top_cat = sorted_cats[0][0] if sorted_cats else "Другое"
            rank_count = d_stats.get("rank_count", 0)
            avg_rank = d_stats.get("rank_sum", 0) / rank_count if rank_count else 0
            key_problems = "; ".join(d_stats.get("summaries", []))
            rows.append([
                idx,
                district,
                d_stats.get("count", 0),
                round(float(avg_rank), 1),
                d_stats.get("critical_count", 0),
                top_cat,
                key_problems or f"Основной поток обращений связан с темой: {top_cat}.",
            ])

        ws.write(0, 0, "Все районы по реальным проблемам", self.f_title)
        self._write_table(
            ws,
            2,
            ["Место", "Район", "Реальные проблемы", "Средняя важность", "Срочных 4-5", "Главная тема", "Кратко о проблемах"],
            rows,
        )

    def _write_top3(self, stats: dict):
        ws = self.wb.add_worksheet("Топ-3 района")
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 10)
        ws.set_column(1, 1, 28)
        ws.set_column(2, 4, 18)
        ws.set_column(5, 5, 26)
        ws.set_column(6, 6, 70)

        rows = []
        for idx, item in enumerate(stats.get("top3_districts", []), start=1):
            rows.append([
                idx,
                item.get("district", ""),
                item.get("count", 0),
                round(float(item.get("avg_rank", 0) or 0), 1),
                item.get("critical_count", 0),
                item.get("top_cat", ""),
                self._reason_text(item),
            ])

        ws.write(0, 0, "Топ-3 районов", self.f_title)
        self._write_table(
            ws,
            2,
            ["Место", "Район", "Реальные проблемы", "Средняя важность", "Срочных 4-5", "Главная тема", "Почему район в топе"],
            rows,
        )

    def _write_top10(self, stats: dict):
        ws = self.wb.add_worksheet("Топ-10 районов")
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 10)
        ws.set_column(1, 1, 30)
        ws.set_column(2, 4, 18)
        ws.set_column(5, 5, 28)
        ws.set_column(6, 6, 70)

        rows = []
        for idx, item in enumerate(stats.get("top10_districts", []), start=1):
            rows.append([
                idx,
                item.get("district", ""),
                item.get("count", 0),
                round(float(item.get("avg_rank", 0) or 0), 1),
                item.get("critical_count", 0),
                item.get("top_cat", ""),
                self._reason_text(item),
            ])

        ws.write(0, 0, "Топ-10 районов по количеству проблем", self.f_title)
        self._write_table(
            ws,
            2,
            ["Место", "Район", "Реальные проблемы", "Средняя важность", "Срочных 4-5", "Главная тема", "Почему район в топе"],
            rows,
        )

    def _write_categories(self, stats: dict):
        ws = self.wb.add_worksheet("Темы проблем")
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 10)
        ws.set_column(1, 1, 42)
        ws.set_column(2, 3, 18)

        total = max(int(stats.get("problems_count", 0)), 1)
        rows = []
        for idx, (category, count) in enumerate(
            sorted(stats.get("category_counts", {}).items(), key=lambda x: x[1], reverse=True),
            start=1,
        ):
            rows.append([idx, category, count, round(count / total * 100, 1)])

        ws.write(0, 0, "Каких проблем больше всего", self.f_title)
        self._write_table(ws, 2, ["Место", "Проблема", "Количество", "Доля, %"], rows)

    def _attention_rows(self, stats: dict, limit: int = 20):
        rows = []
        district_stats = stats.get("district_stats", {})
        sorted_districts = sorted(
            district_stats.items(),
            key=lambda x: (x[1].get("critical_count", 0), x[1].get("count", 0)),
            reverse=True,
        )
        for district, d_stats in sorted_districts:
            critical_count = int(d_stats.get("critical_count", 0) or 0)
            if critical_count <= 0:
                continue
            sorted_cats = sorted(d_stats.get("categories", {}).items(), key=lambda x: x[1], reverse=True)
            top_cat = sorted_cats[0][0] if sorted_cats else "Другое"
            summaries = "; ".join(d_stats.get("summaries", []))
            if not summaries:
                summaries = f"В районе есть обращения с высокой критичностью по теме: {top_cat}."
            rows.append([district, critical_count, d_stats.get("count", 0), top_cat, summaries])
            if len(rows) >= limit:
                break

        if not rows:
            rows.append(["Нет данных", 0, 0, "Нет срочных тем", "Обращений с рангом 4-5 не найдено."])
        return rows

    def _write_attention(self, stats: dict):
        ws = self.wb.add_worksheet("Требуют внимания")
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 30)
        ws.set_column(1, 2, 18)
        ws.set_column(3, 3, 32)
        ws.set_column(4, 4, 78)

        ws.write(0, 0, "Какие проблемы требуют внимания", self.f_title)
        self._write_table(
            ws,
            2,
            ["Район", "Срочных 4-5", "Всего проблем", "Главная тема", "Почему важно"],
            self._attention_rows(stats),
        )

    def _write_ranks(self, stats: dict):
        ws = self.wb.add_worksheet("Важность")
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 18)
        ws.set_column(1, 1, 18)
        ws.set_column(2, 2, 56)

        descriptions = {
            1: "Минимальная",
            2: "Низкая",
            3: "Средняя",
            4: "Высокая",
            5: "Критическая",
        }
        explanations = {
            1: "Можно рассматривать в обычном порядке.",
            2: "Есть проблема, но без признаков срочности.",
            3: "Нужна проверка и плановое реагирование.",
            4: "Требует повышенного внимания.",
            5: "Самые срочные и чувствительные обращения.",
        }
        rows = []
        for rank in range(1, 6):
            count = int(stats.get("rank_counts", {}).get(rank, stats.get("rank_counts", {}).get(str(rank), 0)))
            rows.append([f"{rank} - {descriptions[rank]}", count, explanations[rank]])

        ws.write(0, 0, "Ранг критичности", self.f_title)
        self._write_table(ws, 2, ["Ранг", "Количество", "Пояснение"], rows)


def export_to_excel(df: pd.DataFrame, output_path: str):
    """Compatibility helper for older callers."""
    type_col = "Тип инцидента" if "Тип инцидента" in df.columns else None
    problems_df = df[df[type_col] == "Проблема"] if type_col else df
    stats = {
        "total_count": len(df),
        "problems_count": len(problems_df),
        "top3_districts": [],
        "top10_districts": [],
        "rank_counts": {},
        "district_stats": {},
        "district_counts": {},
        "category_counts": {},
    }
    exporter = StreamingExcelExporter(output_path, [], 0, 0, 0, 0, 0)
    exporter.close(stats)
