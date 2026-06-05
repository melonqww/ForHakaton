Генерация тестового датасета: python generate\_synthetic\_data.py
В корне появится файл cases\_synthetic.xlsx



После запуск скрипта:
python main.py --input cases\_synthetic.xlsx --output cases\_output.xlsx



Бенчмарки: 



1-Запустите генератор тестов: python generate\_synthetic\_data.py

2-После скрипт для теста: python benchmark.py --sizes от 1000 до 500\_000



