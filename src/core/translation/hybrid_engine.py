import logging
from src.core.translation.base_translator import BaseTranslator
from src.core.translation.google_engine import GoogleEngine
from src.core.translation.argos_engine import ArgosEngine
from src.core.translation.text_cleaner import clean_ocr_text

logger = logging.getLogger(__name__)


class HybridEngine(BaseTranslator):
    """
    Hybrid Translation Engine (Google Lens style):
    - Pre-processes and normalizes OCR text spacing.
    - Primary: High-accuracy Google NMT (via robust GTX API).
    - Automatic Fallback: 100% Offline Argos Translate if offline or rate-limited.
    """

    def __init__(self, source: str = "en", target: str = "id"):
        self.source = source
        self.target = target
        self.google = GoogleEngine(source=source, target=target)
        self.argos = ArgosEngine(source=source, target=target)

    def set_languages(self, source: str, target: str):
        self.source = source
        self.target = target
        self.google.set_languages(source, target)
        self.argos.set_languages(source, target)

    def translate(self, text: str) -> str:
        if not text or not text.strip():
            return text

        # 1. Normalize OCR text to avoid translation artifacts
        normalized = clean_ocr_text(text)

        # 2. Try Google NMT first (Lens-grade natural translation)
        try:
            result = self.google.translate(normalized)
            if result and not result.startswith("Error:"):
                return result
        except Exception as e:
            logger.warning("HybridEngine: Google translation failed: %s, falling back to Argos", e)

        # 3. Seamless offline fallback to Argos
        try:
            argos_result = self.argos.translate(normalized)
            if argos_result and not argos_result.startswith("Error:"):
                return argos_result
        except Exception as e:
            logger.warning("HybridEngine: Argos fallback failed: %s", e)

        # If both fail, return best-effort
        return self.google.translate(normalized)

    def translate_batch(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        cleaned_list = [clean_ocr_text(t) for t in texts]
        try:
            results = self.google.translate_batch(cleaned_list)
            if results and len(results) == len(texts) and not any(r.startswith("Error:") for r in results):
                return results
        except Exception as e:
            logger.warning("HybridEngine batch translation failed: %s, falling back to item translation", e)

        return [self.translate(t) for t in texts]
