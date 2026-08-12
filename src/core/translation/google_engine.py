from deep_translator import GoogleTranslator
from src.config import get_translation_language_code
from src.core.translation.base_translator import BaseTranslator


class GoogleEngine(BaseTranslator):
    def __init__(self, source='en', target='tr'):
        self.source = source
        self.target = target
        self.translator = GoogleTranslator(
            source=get_translation_language_code(self.source, "google", "source"),
            target=get_translation_language_code(self.target, "google", "target")
        )

    def set_languages(self, source: str, target: str):
        self.source = source
        self.target = target
        self.translator.source = get_translation_language_code(source, "google", "source")
        self.translator.target = get_translation_language_code(target, "google", "target")

    def translate(self, text: str) -> str:
        try:
            return self.translator.translate(text)
        except Exception as e:
            print(f"Google Translation Error: {e}")
            return f"Error: {e}"
