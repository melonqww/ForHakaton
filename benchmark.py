import time
import os
import argparse
import pandas as pd
import numpy as np
from src.pipeline import run_pipeline

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="10000,50000,100000,200000,500000", help="Размеры через запятую")
    parser.add_argument("--input", default="cases_synthetic.xlsx", help="Входной Excel файл")
    args = parser.parse_args()

    input_file = args.input
    sizes = [int(x.strip()) for x in args.sizes.split(",")]

    if not os.path.exists(input_file):
        print(f"Нет файла {input_file}. Сначала запусти generate_synthetic_data.py")
        return
        
    df = pd.read_excel(input_file)
    print(f"Загрузили {input_file}, всего строк: {len(df)}")
    
    print("\n--- Запуск тестов ---")
    for sz in sizes:
        temp_in = f"temp_bench_in_{sz}.xlsx"
        temp_out = f"temp_bench_out_{sz}.xlsx"
        
        if len(df) < sz:
            repeats = int(np.ceil(sz / len(df)))
            bench_df = pd.concat([df] * repeats, ignore_index=True).head(sz)
        else:
            bench_df = df.head(sz).copy()
            
        bench_df.to_excel(temp_in, index=False)
        
        t0 = time.time()
        run_pipeline(temp_in, temp_out, use_llm=False)
        dt = time.time() - t0
        
        print(f"Размер: {sz} | Время: {dt:.2f} сек | Скорость: {sz/dt:.1f} стр/сек")
        
        for f in (temp_in, temp_out):
            if os.path.exists(f):
                os.remove(f)

if __name__ == "__main__":
    main()
