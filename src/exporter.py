from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import ColorScaleRule
import pandas as pd
import openpyxl

from src.config import CATEGORIES
from src.utils import find_column_index

def export_to_excel(df: pd.DataFrame, output_path: str):
    """Экспорт DataFrame в Excel с профессиональным оформлением и оптимизацией."""
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Данные'
    ws.views.sheetView[0].showGridLines = True
 
    cols_list = list(df.columns)
    text_col = find_column_index(df, "text", 36) + 1
    group_col = find_column_index(df, "group", 21) + 1
    
    anon_col = cols_list.index("Очищенный текст") + 1 if "Очищенный текст" in cols_list else None
    geo_col = cols_list.index("Нормализованное Гео") + 1 if "Нормализованное Гео" in cols_list else None
    rank_col = cols_list.index("Ранг критичности") + 1 if "Ранг критичности" in cols_list else None
    summary_col = cols_list.index("Краткое саммари") + 1 if "Краткое саммари" in cols_list else None
    type_col = cols_list.index("Тип инцидента") + 1 if "Тип инцидента" in cols_list else None
 
    header_fill = PatternFill(start_color="2B4C7E", end_color="2B4C7E", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )
 
    # Заголовки таблицы
    for col_idx, col_name in enumerate(cols_list, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
 
    # Быстрый экспорт данных
    values_list = df.values.tolist()
    for row_data in values_list:
        row_data_clean = []
        for val in row_data:
            if pd.isna(val):
                row_data_clean.append("")
            elif isinstance(val, pd.Timestamp):
                row_data_clean.append(val.strftime('%Y-%m-%d %H:%M:%S'))
            else:
                row_data_clean.append(val)
        ws.append(row_data_clean)

    # Выпадающий список категорий Минцифры
    group_letter = get_column_letter(group_col)
    dv = DataValidation(
        type="list", 
        formula1=f'"{",".join(CATEGORIES)}"', 
        allow_blank=True,
        showErrorMessage=True,
        errorTitle="Ошибка ввода",
        error="Пожалуйста, выберите категорию из списка утвержденных Минцифры."
    )
    ws.add_data_validation(dv)
    dv.add(f"{group_letter}2:{group_letter}{ws.max_row}")

    # Цветовое шкалирование важности (градиент на весь столбец)
    if rank_col:
        rank_col_letter = get_column_letter(rank_col)
        color_scale = ColorScaleRule(
            start_type='num', start_value=1, start_color='E2F0D9',
            mid_type='num', mid_value=3, mid_color='FFF2CC',
            end_type='num', end_value=5, end_color='FCE4D6'
        )
        ws.conditional_formatting.add(f"{rank_col_letter}2:{rank_col_letter}{ws.max_row}", color_scale)

    # Корректировка ширины столбцов по выборке первых 1000 строк
    for col_idx in range(1, ws.max_column + 1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        
        for row_idx in range(1, min(ws.max_row + 1, 1000)):
            val_str = str(ws.cell(row=row_idx, column=col_idx).value or '')
            if len(val_str) > max_len:
                max_len = len(val_str)
        
        if col_idx in [text_col, anon_col, summary_col]:
            ws.column_dimensions[col_letter].width = 40
        else:
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 10), 25)

    ws.row_dimensions[1].height = 28

    # Создание листа аналитической сводки
    ws_summary = wb.create_sheet("Сводка")
    group_col_name = df.columns[find_column_index(df, 'group', 21)]
    df_problems = df[df.get('Тип инцидента', pd.Series()) == 'Проблема'] if 'Тип инцидента' in df.columns else df
    
    if not df_problems.empty and 'Нормализованное Гео' in df.columns:
        title_font = Font(name='Calibri', size=14, bold=True, color='2B4C7E')
        section_font = Font(name='Calibri', size=12, bold=True)
        bold_font = Font(name='Calibri', size=11, bold=True)
        normal_font = Font(name='Calibri', size=11)
        
        row_num = 1
        
        ws_summary.cell(row=row_num, column=1, value='Сводный анализ обращений граждан').font = title_font
        row_num += 2
        
        total = len(df)
        problems = len(df_problems)
        ws_summary.cell(row=row_num, column=1, value='Всего обращений:').font = bold_font
        ws_summary.cell(row=row_num, column=2, value=total).font = normal_font
        row_num += 1
        ws_summary.cell(row=row_num, column=1, value='Реальных проблем:').font = bold_font
        ws_summary.cell(row=row_num, column=2, value=problems).font = normal_font
        row_num += 1
        ws_summary.cell(row=row_num, column=1, value='Спам/благодарности:').font = bold_font
        ws_summary.cell(row=row_num, column=2, value=total - problems).font = normal_font
        row_num += 2
        
        # Блок Топ-3
        ws_summary.cell(row=row_num, column=1, value='ТОП-3 проблемных муниципалитета').font = section_font
        row_num += 1
        
        headers_top3 = ['Район', 'Обращений', 'Основная категория', 'Ср. критичность', 'Критичных (4-5)', 'Ключевые проблемы']
        for col_i, h in enumerate(headers_top3, 1):
            cell = ws_summary.cell(row=row_num, column=col_i, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center', vertical='center')
        row_num += 1
        
        top3 = df_problems['Нормализованное Гео'].value_counts().head(3)
        for district, count in top3.items():
            d_df = df_problems[df_problems['Нормализованное Гео'] == district]
            cats = d_df[group_col_name].value_counts()
            top_cat = cats.index[0] if not cats.empty else ''
            avg_rank = d_df['Ранг критичности'].mean() if 'Ранг критичности' in d_df.columns else 0
            critical_count = len(d_df[d_df['Ранг критичности'] >= 4]) if 'Ранг критичности' in d_df.columns else 0
            
            key_problems = ''
            if 'Краткое саммари' in d_df.columns and 'Ранг критичности' in d_df.columns:
                critical = d_df[d_df['Ранг критичности'] >= 4]
                if not critical.empty:
                    summaries = critical['Краткое саммари'].head(3).tolist()
                    key_problems = '; '.join([s for s in summaries if s])
            
            ws_summary.cell(row=row_num, column=1, value=district).font = bold_font
            ws_summary.cell(row=row_num, column=2, value=count).font = normal_font
            ws_summary.cell(row=row_num, column=2).alignment = Alignment(horizontal='center')
            ws_summary.cell(row=row_num, column=3, value=top_cat).font = normal_font
            ws_summary.cell(row=row_num, column=4, value=round(avg_rank, 1)).font = normal_font
            ws_summary.cell(row=row_num, column=4).alignment = Alignment(horizontal='center')
            ws_summary.cell(row=row_num, column=5, value=critical_count).font = normal_font
            ws_summary.cell(row=row_num, column=5).alignment = Alignment(horizontal='center')
            ws_summary.cell(row=row_num, column=6, value=key_problems).font = normal_font
            ws_summary.cell(row=row_num, column=6).alignment = Alignment(wrap_text=True)
            row_num += 1
        
        row_num += 1
        
        # Блок Топ-10
        ws_summary.cell(row=row_num, column=1, value='ТОП-10 районов по количеству обращений').font = section_font
        row_num += 1
        
        headers_top10 = ['Район', 'Обращений', 'Основная категория', 'Ср. критичность']
        for col_i, h in enumerate(headers_top10, 1):
            cell = ws_summary.cell(row=row_num, column=col_i, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center', vertical='center')
        row_num += 1
        
        top10 = df_problems['Нормализованное Гео'].value_counts().head(10)
        for district, count in top10.items():
            d_df = df_problems[df_problems['Нормализованное Гео'] == district]
            cats = d_df[group_col_name].value_counts()
            top_cat = cats.index[0] if not cats.empty else ''
            avg_rank = d_df['Ранг критичности'].mean() if 'Ранг критичности' in d_df.columns else 0
            
            ws_summary.cell(row=row_num, column=1, value=district).font = normal_font
            ws_summary.cell(row=row_num, column=2, value=count).font = normal_font
            ws_summary.cell(row=row_num, column=2).alignment = Alignment(horizontal='center')
            ws_summary.cell(row=row_num, column=3, value=top_cat).font = normal_font
            ws_summary.cell(row=row_num, column=4, value=round(avg_rank, 1)).font = normal_font
            ws_summary.cell(row=row_num, column=4).alignment = Alignment(horizontal='center')
            row_num += 1
        
        ws_summary.column_dimensions['A'].width = 25
        ws_summary.column_dimensions['B'].width = 14
        ws_summary.column_dimensions['C'].width = 25
        ws_summary.column_dimensions['D'].width = 18
        ws_summary.column_dimensions['E'].width = 18
        ws_summary.column_dimensions['F'].width = 60

    wb.save(output_path)
    wb.close()
