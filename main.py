import argparse
import os
import pandas as pd
import time

from src.pipeline import run_pipeline
from src.utils import find_column_index
from src.classifier import RequestClassifier, MODEL_PATH

def main():
    parser = argparse.ArgumentParser(description="Консольный пайплайн анализа обращений граждан Омской области.")
    parser.add_argument("--input", default="cases_synthetic.xlsx", help="Путь к исходному файлу Excel")
    parser.add_argument("--output", default="cases_output.xlsx", help="Путь для сохранения результата")
    parser.add_argument("--use-llm", action="store_true", help="Использовать локальную LLM (Ollama)")
    parser.add_argument("--retrain", action="store_true", help="Принудительно переобучить классификатор спама")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"Ошибка: Входной файл '{args.input}' не найден.")
        return

    classifier = RequestClassifier()
    if not classifier.model or args.retrain:
        print("Классификатор не обучен. Запуск обучения на входном файле...")
        try:
            temp_df = pd.read_excel(args.input)
            if "CLASS_LABEL" in temp_df.columns:
                col_text = find_column_index(temp_df, "text", 36)
                texts = temp_df.iloc[:, col_text].fillna("").astype(str).tolist()
                labels = temp_df["CLASS_LABEL"].fillna("Проблема").tolist()
                classifier.train(texts, labels)
                print(f"Обучение завершено. Модель сохранена в {MODEL_PATH}")
            else:
                print("Предупреждение: Колонка CLASS_LABEL не найдена. Будет использован эвристический режим.")
        except Exception as e:
            print(f"Не удалось обучить классификатор: {e}. Используется эвристический режим.")

    print(f"Запуск пайплайна: '{args.input}' -> '{args.output}'")
    print(f"Режим суммаризации: {'Локальная LLM' if args.use_llm else 'Экстрактивный (TextRank)'}")
    
    try:
        start = time.time()
        run_pipeline(args.input, args.output, use_llm=args.use_llm, classifier=classifier)
        elapsed = time.time() - start
        print(f"Обработка завершена за {elapsed:.2f} сек! Результат сохранен в '{args.output}'")
        
        result_df = pd.read_excel(args.output)
        if "CLASS_LABEL" in result_df.columns:
            from sklearn.metrics import precision_score, recall_score, f1_score, accuracy_score
            y_true = result_df["CLASS_LABEL"].fillna("Проблема").tolist()
            y_pred = result_df["Тип инцидента"].tolist()
            
            print(f"\n--- Метрики классификации ---")
            print(f"Accuracy:  {accuracy_score(y_true, y_pred):.1%}")
            print(f"Precision: {precision_score(y_true, y_pred, pos_label='Проблема', zero_division=0):.1%}")
            print(f"Recall:    {recall_score(y_true, y_pred, pos_label='Проблема', zero_division=0):.1%}")
            print(f"F1-score:  {f1_score(y_true, y_pred, pos_label='Проблема', zero_division=0):.1%}")
    except Exception as e:
        print(f"Ошибка при обработке пайплайна: {e}")

if __name__ == "__main__":
    main()
