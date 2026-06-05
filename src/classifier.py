import os
import pickle
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import RidgeClassifier
from sklearn.pipeline import Pipeline

MODEL_PATH = os.path.join(os.path.dirname(__file__), "classifier.pkl")

GRATITUDE_WORDS = {"спасибо", "благодарю", "благодарность", "выразить признательность", "молодцы"}
QUESTION_WORDS = {"подскажите", "подскажите,", "где узнать", "со скольки", "какой график", "тестовое"}

class RequestClassifier:
    def __init__(self):
        self.model = self._load_model()

    def _load_model(self):
        if os.path.exists(MODEL_PATH):
            try:
                with open(MODEL_PATH, "rb") as f:
                    return pickle.load(f)
            except Exception as e:
                print(f"Ошибка загрузки модели: {e}")
        return None

    def train(self, texts, labels):
        pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(max_features=5000, ngram_range=(1, 2))),
            ("clf", RidgeClassifier(class_weight="balanced"))
        ])
        pipeline.fit(texts, labels)
        self.model = pipeline
        
        with open(MODEL_PATH, "wb") as f:
            pickle.dump(pipeline, f)

    def is_sarcastic_problem(self, text_lower: str) -> bool:
        """Детекция саркастических жалоб. Принимает уже готовый text.lower()."""
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
                
        return False

    def predict_single(self, text: str, text_lower: str = None) -> str:
        """Классификация одного текста. text_lower — опционально предвычисленный .lower()."""
        if not text:
            return "Не проблема"

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

    def predict(self, texts: list, texts_lower: list = None) -> list:
        """Батчевая классификация. texts_lower — предвычисленные .lower() для каждого текста."""
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
