import requests
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

    def _translate_gtx(self, text: str) -> str:
        source = get_translation_language_code(self.source, "google", "source")
        target = get_translation_language_code(self.target, "google", "target")
        params = {
            "client": "gtx",
            "sl": source or "auto",
            "tl": target or "en",
            "dt": "t",
            "q": text,
        }
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params=params,
            headers=headers,
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list) and data[0]:
                return "".join(part[0] for part in data[0] if part and part[0])
        raise RuntimeError(f"GTX API status {resp.status_code}")

    def translate(self, text: str) -> str:
        try:
            return self.translator.translate(text)
        except Exception as e:
            try:
                return self._translate_gtx(text)
            except Exception as gtx_err:
                print(f"Google Translation Error (deep_translator: {e}, gtx: {gtx_err})")
                return f"Error: {e}"
