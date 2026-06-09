import os
import pickle
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import RidgeClassifier
from sklearn.pipeline import Pipeline

MODEL_PATH = os.path.join(os.path.dirname(__file__), "classifier.pkl")

GRATITUDE_WORDS = {"спасибо", "благодарю", "благодарность", "выразить признательность", "молодцы"}
QUESTION_WORDS = {"подскажите", "подскажите,", "где узнать", "со скольки", "какой график", "тестовое"}


class ClassifierError(Exception):
    """Ошибка классификатора с понятным сообщением."""
    pass


class RequestClassifier:
    def __init__(self):
        self.model = self._load_model()

    def _load_model(self):
        if os.path.exists(MODEL_PATH):
            try:
                with open(MODEL_PATH, "rb") as f:
                    return pickle.load(f)
            except pickle.UnpicklingError:
                print("Предупреждение: файл модели повреждён. Будет использована эвристическая классификация.")
                return None
            except Exception as e:
                print(f"Предупреждение: не удалось загрузить модель: {e}. Будет использована эвристика.")
                return None
        return None

    def train(self, texts, labels):
        if not texts or not labels:
            raise ClassifierError("Нет данных для обучения классификатора. Передайте хотя бы один текст с меткой.")
        if len(texts) != len(labels):
            raise ClassifierError(
                f"Количество текстов ({len(texts)}) не совпадает с количеством меток ({len(labels)}). "
                f"Проверьте входные данные."
            )
        if len(set(labels)) < 2:
            unique_labels = set(labels)
            raise ClassifierError(
                f"Для обучения нужно минимум 2 разных класса, а найден только 1: {', '.join(unique_labels)}. "
                f"Убедитесь, что в колонке CLASS_LABEL есть и «Проблема», и «Не проблема»."
            )

        try:
            pipeline = Pipeline([
                ("tfidf", TfidfVectorizer(max_features=5000, ngram_range=(1, 2))),
                ("clf", RidgeClassifier(class_weight="balanced"))
            ])
            pipeline.fit(texts, labels)
            self.model = pipeline

            with open(MODEL_PATH, "wb") as f:
                pickle.dump(pipeline, f)
        except ValueError as e:
            raise ClassifierError(f"Ошибка при обучении модели: {e}. Проверьте формат входных данных.")
        except Exception as e:
            raise ClassifierError(f"Не удалось сохранить обученную модель: {e}. Проверьте права на запись.")

    def is_sarcastic_problem(self, text_lower: str) -> bool:
        """Детекция саркастических жалоб. Принимает уже готовый text.lower()."""
        if not text_lower:
            return False

        try:
            if "каток" in text_lower:
                bad_words = ["тротуар", "дорог", "улиц", "подъезд", "пешеход", "падают", "ломают", "травм", "наледь"]
                if any(w in text_lower for w in bad_words):
                    return True

            if "бассейн" in text_lower:
                bad_words = ["двор", "подъезд", "улиц", "дорог", "дом", "колено", "затопило", "хлещет", "вода стоит"]
                if any(w in text_lower for w in bad_words):
                    return True

            if "ледниковый период" in text_lower:
                bad_words = ["квартир", "дом", "комнат", "батаре", "холод", "замерза", "дубак", "ледяные"]
                if any(w in text_lower for w in bad_words):
                    return True

            if any(w in text_lower for w in ["падают", "ломают ноги", "прорвало", "замерзаем"]):
                return True
        except Exception:
            return False

        return False

    def predict_single(self, text: str, text_lower: str = None) -> str:
        """Классификация одного текста. text_lower — опционально предвычисленный .lower()."""
        if not text:
            return "Не проблема"

        try:
            if text_lower is None:
                text_lower = text.lower()

            if self.is_sarcastic_problem(text_lower):
                return "Проблема"

            if self.model:
                return self.model.predict([text])[0]

            if any(word in text_lower for word in GRATITUDE_WORDS):
                return "Не проблема"

            if any(word in text_lower for word in QUESTION_WORDS) or len(text) < 15:
                return "Не проблема"

            return "Проблема"
        except Exception as e:
            print(f"Предупреждение: ошибка при классификации текста: {e}. Текст помечен как «Не проблема».")
            return "Не проблема"

    def predict(self, texts: list, texts_lower: list = None) -> list:
        """Батчевая классификация. texts_lower — предвычисленные .lower() для каждого текста."""
        if not texts:
            return []

        try:
            if texts_lower is None:
                texts_lower = [t.lower() for t in texts]

            if self.model:
                raw_preds = self.model.predict(texts).tolist()
                results = []
                for text_lower, pred in zip(texts_lower, raw_preds):
                    if pred == "Не проблема" and self.is_sarcastic_problem(text_lower):
                        results.append("Проблема")
                    else:
                        results.append(pred)
                return results
            else:
                return [self.predict_single(t, tl) for t, tl in zip(texts, texts_lower)]
        except Exception as e:
            print(f"Предупреждение: ошибка при пакетной классификации: {e}. Используется показовый метод.")
            return [self.predict_single(t) for t in texts]