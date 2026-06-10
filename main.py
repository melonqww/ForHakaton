import argparse
import os
import sys
import time
import pandas as pd

from src.pipeline import run_pipeline
from src.utils import find_column_index
from src.classifier import RequestClassifier, MODEL_PATH


# ── ANSI цвета ─────────────────────────────────────────────────────────────
# Включаем ANSI на Windows (cmd / PowerShell)
if os.name == "nt":
    os.system("")

_USE_COLOR = sys.stdout.isatty()


class _C:
    """ANSI-коды. Сбрасываются в пустые строки при --no-color."""
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    RED    = "\033[91m"
    BLUE   = "\033[94m"
    GREY   = "\033[90m"
    WHITE  = "\033[97m"


def _disable_color():
    for attr in ("RESET", "BOLD", "GREEN", "YELLOW", "CYAN", "RED", "BLUE", "GREY", "WHITE"):
        setattr(_C, attr, "")


# ── Вспомогательные функции вывода ─────────────────────────────────────────

def _sep(char="═", n=62):
    return f"{_C.BLUE}{_C.BOLD}{char * n}{_C.RESET}"


def _print_header():
    print(_sep())
    print(f"{_C.BLUE}{_C.BOLD}  Анализ обращений граждан — Минцифры Омской области{_C.RESET}")
    print(_sep())
    print()


def _section(title):
    print(f"\n{_C.CYAN}{_C.BOLD}▸ {title}{_C.RESET}")


def _ok(msg):    print(f"  {_C.GREEN}✓{_C.RESET}  {msg}")
def _warn(msg):  print(f"  {_C.YELLOW}⚠{_C.RESET}  {msg}")
def _err(msg):   print(f"  {_C.RED}✗{_C.RESET}  {msg}")
def _info(msg):  print(f"  {_C.GREY}{msg}{_C.RESET}")


# ── Прогресс-бар ────────────────────────────────────────────────────────────

_pb_start = 0.0
_BAR_W = 38


def _progress(current: int, total: int):
    if total == 0:
        return
    pct = current / total
    filled = int(_BAR_W * pct)
    bar = f"{_C.CYAN}{'█' * filled}{'░' * (_BAR_W - filled)}{_C.RESET}"
    elapsed = time.time() - _pb_start
    rps = current / elapsed if elapsed > 0.1 else 0
    if rps > 0 and current < total:
        eta = f"ETA {(total - current) / rps:.0f}с"
    else:
        eta = "готово   " if current >= total else "..."
    sys.stdout.write(
        f"\r  {bar} {pct:5.1%}  "
        f"{_C.GREY}{current:>7,}/{total:,}  {eta}{_C.RESET}  "
    )
    sys.stdout.flush()
    if current >= total:
        print()


# ── Таблица результатов ─────────────────────────────────────────────────────

def _print_stats(stats: dict, elapsed: float):
    total    = stats.get("total_count", 0)
    problems = stats.get("problems_count", 0)
    spam     = total - problems

    _section("Итоги обработки")
    w = 30
    print(f"  {'Всего обращений:':<{w}} {_C.BOLD}{total:>8,}{_C.RESET}")
    if total:
        print(
            f"  {'Реальные проблемы:':<{w}} "
            f"{_C.GREEN}{_C.BOLD}{problems:>8,}{_C.RESET}"
            f"  {_C.GREY}({problems / total:.1%}){_C.RESET}"
        )
        print(
            f"  {'Спам / благодарности:':<{w}} "
            f"{_C.YELLOW}{spam:>8,}{_C.RESET}"
            f"  {_C.GREY}({spam / total:.1%}){_C.RESET}"
        )
    print(f"  {'Время обработки:':<{w}} {_C.BOLD}{elapsed:>7.1f} с{_C.RESET}")
    if elapsed > 0 and total:
        rps = total / elapsed
        print(f"  {'Скорость:':<{w}} {_C.GREY}{rps:>6,.0f} строк/сек{_C.RESET}")

    # Топ-3 района
    top3 = stats.get("top3_districts", [])
    if top3:
        _section("ТОП-3 проблемных района")
        medals = ["🥇", "🥈", "🥉"] if _USE_COLOR else ["1.", "2.", "3."]
        for i, d in enumerate(top3):
            crit = d.get("critical_count", 0)
            avg  = d.get("avg_rank", 0)
            crit_clr = _C.RED if crit > 0 else _C.GREY
            print(
                f"  {medals[i]} {_C.BOLD}{d['district']:<28}{_C.RESET}"
                f"  {d['count']:>5,} обращ."
                f"  критич.: {crit_clr}{crit:>3}{_C.RESET}"
                f"  ср.ранг: {avg:.1f}"
            )

    # Категории
    cats = stats.get("category_counts", {})
    if cats and problems:
        _section("Распределение по категориям")
        max_cnt = max(cats.values())
        for cat, cnt in sorted(cats.items(), key=lambda x: -x[1])[:8]:
            bl = int(22 * cnt / max_cnt)
            bar = f"{_C.CYAN}{'▓' * bl}{'░' * (22 - bl)}{_C.RESET}"
            pct = cnt / problems * 100
            print(f"  {cat:<26} {bar} {cnt:>6,}  ({pct:.1f}%)")


def _print_metrics(output_path: str):
    """Метрики качества, если в файле есть ground-truth колонка CLASS_LABEL."""
    try:
        try:
            hdr = pd.read_excel(output_path, nrows=1, engine="calamine")
        except Exception:
            hdr = pd.read_excel(output_path, nrows=1)

        if "CLASS_LABEL" not in hdr.columns or "Тип инцидента" not in hdr.columns:
            return

        try:
            df = pd.read_excel(output_path, usecols=["CLASS_LABEL", "Тип инцидента"], engine="calamine")
        except Exception:
            df = pd.read_excel(output_path, usecols=["CLASS_LABEL", "Тип инцидента"])

        from sklearn.metrics import (
            accuracy_score, precision_score, recall_score, f1_score
        )
        y_true = df["CLASS_LABEL"].fillna("Проблема").tolist()
        y_pred = df["Тип инцидента"].tolist()

        _section("Метрики качества классификации")

        def _clr(v):
            if v >= 0.90: return _C.GREEN
            if v >= 0.75: return _C.YELLOW
            return _C.RED

        for name, val in [
            ("Accuracy",  accuracy_score(y_true, y_pred)),
            ("Precision", precision_score(y_true, y_pred, pos_label="Проблема", zero_division=0)),
            ("Recall",    recall_score(y_true, y_pred,    pos_label="Проблема", zero_division=0)),
            ("F1-score",  f1_score(y_true, y_pred,        pos_label="Проблема", zero_division=0)),
        ]:
            print(f"  {name + ':':<14} {_clr(val)}{_C.BOLD}{val:.1%}{_C.RESET}")
    except Exception:
        pass


# ── Главная функция ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Консольный пайплайн анализа обращений граждан Омской области.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python main.py --input data.xlsx
  python main.py --input data.xlsx --output results/out.xlsx --workers 4
  python main.py --input data.xlsx --use-llm
  python main.py --input data.xlsx --retrain --no-color > report.txt
        """,
    )
    parser.add_argument(
        "--input",    default="cases_synthetic.xlsx",
        metavar="FILE",
        help="Путь к исходному файлу Excel (.xlsx) [по умолчанию: cases_synthetic.xlsx]",
    )
    parser.add_argument(
        "--output",   default="cases_output.xlsx",
        metavar="FILE",
        help="Путь для сохранения результата (.xlsx) [по умолчанию: cases_output.xlsx]",
    )
    parser.add_argument(
        "--workers",  type=int, default=0,
        metavar="N",
        help="Количество потоков обработки (0 = авто по CPU) [по умолчанию: 0]",
    )
    parser.add_argument(
        "--use-llm",  action="store_true",
        help="Использовать локальную LLM Ollama для саммари районов",
    )
    parser.add_argument(
        "--retrain",  action="store_true",
        help="Принудительно переобучить классификатор на входных данных",
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Отключить цветной вывод (полезно для логов и CI/CD)",
    )

    args = parser.parse_args()

    if args.no_color or not _USE_COLOR:
        _disable_color()

    _print_header()

    # ── Проверка файла ──────────────────────────────────────────────────────
    if not os.path.exists(args.input):
        _err(f"Входной файл не найден: '{args.input}'")
        sys.exit(1)

    size_mb = os.path.getsize(args.input) / 1_048_576
    _ok(f"Входной файл:  {args.input}  ({size_mb:.1f} MB)")
    _info(f"Выходной файл: {args.output}")

    mode_str = "LLM (Ollama/Qwen)" if args.use_llm else "Экстрактивный TextRank (быстро, без сети)"
    _info(f"Суммаризация:  {mode_str}")

    n_workers = args.workers if args.workers > 0 else min(4, max(1, os.cpu_count() or 2))
    _info(f"Потоков:       {n_workers}")

    # ── Создание выходной папки ─────────────────────────────────────────────
    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)
        _ok(f"Создана папка: {out_dir}")

    # ── Классификатор ───────────────────────────────────────────────────────
    _section("Классификатор")
    classifier = RequestClassifier()

    if not classifier.model or args.retrain:
        _warn("Модель не обучена — запускаем обучение на входных данных...")
        try:
            try:
                hdr_df = pd.read_excel(args.input, nrows=1, engine="calamine")
            except Exception:
                hdr_df = pd.read_excel(args.input, nrows=1)

            target_col = None
            if "CLASS_LABEL" in hdr_df.columns:
                target_col = "CLASS_LABEL"
            elif "Тип инцидента" in hdr_df.columns:
                target_col = "Тип инцидента"

            if target_col:
                col_text_idx  = find_column_index(hdr_df, "text", 36)
                col_text_name = hdr_df.columns[col_text_idx]
                try:
                    tmp = pd.read_excel(
                        args.input,
                        usecols=[col_text_name, target_col],
                        nrows=50_000,
                        engine="calamine",
                    )
                except Exception:
                    tmp = pd.read_excel(
                        args.input,
                        usecols=[col_text_name, target_col],
                        nrows=50_000,
                    )
                texts  = tmp[col_text_name].fillna("").astype(str).tolist()
                if target_col == "Тип инцидента":
                    labels = ["Проблема" if x == "Решаемый" else "Не проблема"
                              for x in tmp[target_col]]
                else:
                    labels = tmp[target_col].fillna("Проблема").tolist()
                classifier.train(texts, labels)
                _ok(f"Обучено {len(texts):,} примеров → {MODEL_PATH}")
            else:
                _warn("CLASS_LABEL / Тип инцидента не найден — используется эвристика.")
        except Exception as exc:
            _warn(f"Ошибка обучения: {exc} — используется эвристика.")
    else:
        _ok("Модель загружена из кеша.")

    # ── Запуск пайплайна ────────────────────────────────────────────────────
    _section("Обработка данных")

    global _pb_start
    _pb_start = time.time()

    try:
        t0 = time.time()
        stats, _ = run_pipeline(
            args.input,
            args.output,
            use_llm=args.use_llm,
            max_workers=n_workers,
            progress_callback=_progress,
            classifier=classifier,
        )
        elapsed = time.time() - t0
    except Exception as exc:
        print()
        _err(f"Ошибка пайплайна: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    out_size_mb = os.path.getsize(args.output) / 1_048_576
    _ok(f"Файл сохранён: {args.output}  ({out_size_mb:.1f} MB)")

    # ── Статистика и метрики ────────────────────────────────────────────────
    _print_stats(stats, elapsed)
    _print_metrics(args.output)

    # ── Финальная строка ────────────────────────────────────────────────────
    print(f"\n{_sep('═')}")
    print(
        f"{_C.GREEN}{_C.BOLD}"
        f"  Готово! {stats.get('total_count', 0):,} строк за {elapsed:.1f} с."
        f"{_C.RESET}"
    )
    print(_sep("═"))
    print()


if __name__ == "__main__":
    main()
