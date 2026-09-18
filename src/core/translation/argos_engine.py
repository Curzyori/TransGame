import os
import tempfile
import threading
from typing import Optional

from src.core.translation.base_translator import BaseTranslator

try:
    import argostranslate.package
    import argostranslate.translate
    _ARGOS_AVAILABLE = True
except ImportError:
    argostranslate = None
    _ARGOS_AVAILABLE = False


class ArgosEngine(BaseTranslator):
    """Offline translation engine using Argos Translate (CTranslate2 / OpenNMT)."""

    PACKAGE_URLS = {
        ("en", "id"): "https://argos-net.com/v1/translate-en_id-1_9.argosmodel",
        ("id", "en"): "https://argos-net.com/v1/translate-id_en-1_9.argosmodel",
    }

    def __init__(self, source: str = "en", target: str = "id"):
        self.source = source if source != "auto" else "en"
        self.target = target if target != "auto" else "id"
        self._lock = threading.Lock()
        self._translation = None
        self._is_initialized = False

    @staticmethod
    def is_available() -> bool:
        """Returns True if the argostranslate library is installed."""
        return _ARGOS_AVAILABLE

    def set_languages(self, source: str, target: str):
        """Updates source and target languages."""
        with self._lock:
            # Argos requires specific language codes; fallback auto to en/id
            new_source = "en" if (not source or source == "auto") else source
            new_target = "id" if (not target or target == "auto") else target

            if new_source != self.source or new_target != self.target:
                self.source = new_source
                self.target = new_target
                self._translation = None
                self._is_initialized = False

    def is_model_installed(self, source: Optional[str] = None, target: Optional[str] = None) -> bool:
        """Checks whether the requested language model pair is installed."""
        if not _ARGOS_AVAILABLE:
            return False

        src = source or self.source
        tgt = target or self.target
        try:
            installed = argostranslate.translate.get_installed_languages()
            s_lang = next((l for l in installed if l.code == src), None)
            t_lang = next((l for l in installed if l.code == tgt), None)
            if s_lang and t_lang:
                return s_lang.get_translation(t_lang) is not None
            return False
        except Exception as e:
            print(f"ArgosEngine model check error: {e}")
            return False

    def _ensure_translation_object(self):
        """Initializes and caches the Argos translation object for (source, target)."""
        if self._is_initialized and self._translation is not None:
            return self._translation

        if not _ARGOS_AVAILABLE:
            return None

        try:
            installed = argostranslate.translate.get_installed_languages()
            s_lang = next((l for l in installed if l.code == self.source), None)
            t_lang = next((l for l in installed if l.code == self.target), None)

            if s_lang and t_lang:
                self._translation = s_lang.get_translation(t_lang)
                self._is_initialized = True
                return self._translation
            self._translation = None
            self._is_initialized = True
            return None
        except Exception as e:
            print(f"ArgosEngine init error: {e}")
            self._translation = None
            self._is_initialized = True
            return None

    def download_and_install_package(
        self,
        from_code: str = "en",
        to_code: str = "id",
        progress_callback=None
    ) -> bool:
        """
        Downloads and installs an offline translation package for from_code -> to_code.
        Safe to call from a worker thread.
        """
        if not _ARGOS_AVAILABLE:
            return False

        url = self.PACKAGE_URLS.get((from_code, to_code))
        if not url:
            print(f"ArgosEngine: No pre-configured package URL for {from_code}->{to_code}")
            return False

        import requests
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

        temp_path = None
        try:
            print(f"ArgosEngine: Downloading offline model for {from_code}->{to_code}...")
            response = requests.get(url, headers=headers, stream=True, timeout=60)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            with tempfile.NamedTemporaryFile(suffix=".argosmodel", delete=False) as tmp:
                temp_path = tmp.name
                for chunk in response.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        tmp.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            progress_callback(int((downloaded / total_size) * 100))

            print(f"ArgosEngine: Installing package {temp_path}...")
            argostranslate.package.install_from_path(temp_path)
            print(f"ArgosEngine: Model {from_code}->{to_code} installed successfully.")

            with self._lock:
                self._translation = None
                self._is_initialized = False

            return True
        except Exception as e:
            print(f"ArgosEngine: Failed to download/install package: {e}")
            return False
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def translate(self, text: str) -> str:
        """Translates text offline using Argos Translate."""
        if not text or not text.strip():
            return text

        if not _ARGOS_AVAILABLE:
            return "Error: argostranslate library is not installed."

        with self._lock:
            translation = self._ensure_translation_object()
            if translation is None:
                return (
                    f"Error: Offline model for {self.source}->{self.target} is not installed. "
                    f"Please install the model via Translation tab."
                )

            try:
                translated = translation.translate(text)
                return translated if translated else text
            except Exception as e:
                print(f"Argos Translation Error: {e}")
                return f"Error: {e}"

    def translate_batch(self, texts: list[str]) -> list[str]:
        """Translates a batch of texts offline."""
        if not texts:
            return []
        return [self.translate(t) for t in texts]
