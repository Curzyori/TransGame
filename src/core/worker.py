import time
import difflib
import threading
from threading import Lock
from PySide6.QtCore import QThread, Signal, QRect
from src.core.ocr.ocr_manager import OCRManager
from src.core.translation.translator_manager import TranslatorManager
from src.core.translation.text_cleaner import clean_ocr_text
from src.core.exceptions import PortalCanceledError
from src.core.screenshot import ScreenshotFactory, ImageProcessor
from src.core.socket_publisher import TranslationPublisher
from src.config import IMG_PATH, IMG_PATH_2, DPI_SCALE_DEFAULT

class OCRWorker(QThread):
    LOOP_SLEEP_SECONDS = 0.5

    new_translation = Signal(str)
    new_translation_1 = Signal(str)
    new_translation_2 = Signal(str)
    performance_update = Signal(float) # Loop duration in seconds
    translation_status = Signal(bool)  # True: translating (API call active), False: idle
    running_status = Signal(bool)      # True: system started, False: system stopped

    def __init__(self):
        super().__init__()
        self.capture_rect = QRect(560, 750, 800, 140)
        self.capture_rect_2 = None
        self.dpi_scale = DPI_SCALE_DEFAULT
        self.lock = Lock()
        self.running = False
        self.ocr_manager = OCRManager()
        self.translator_manager = TranslatorManager()
        self.screenshot_engine = ScreenshotFactory.get_engine()
        self.last_text_1 = ""
        self.last_text_2 = ""
        self._translation_lock = Lock()
        self._is_translating = False
        self.publisher = TranslationPublisher()

    def set_rect(self, qrect, dpi_scale=None):
        with self.lock:
            self.capture_rect = QRect(qrect)
            if dpi_scale is not None:
                self.dpi_scale = dpi_scale
            self.last_text_1 = ""
            print(f"OCRWorker: Region 1: {qrect.x()},{qrect.y()} {qrect.width()}x{qrect.height()} DPI: {self.dpi_scale}")

    def set_rect_2(self, qrect):
        with self.lock:
            if qrect and qrect.width() > 10 and qrect.height() > 10:
                self.capture_rect_2 = QRect(qrect)
                print(f"OCRWorker: Region 2: {qrect.x()},{qrect.y()} {qrect.width()}x{qrect.height()}")
            else:
                self.capture_rect_2 = None
                print("OCRWorker: Region 2 cleared")
            self.last_text_2 = ""

    def set_engine(self, engine_name):
        with self.lock:
            self.ocr_manager.set_engine(engine_name)
            self.last_text_1 = ""
            self.last_text_2 = ""
            print(f"OCRWorker: Engine: {engine_name}")

    def set_translator(self, translator_name):
        with self.lock:
            self.translator_manager.set_translator(translator_name)
            self.last_text_1 = ""
            self.last_text_2 = ""
            print(f"OCRWorker: Translator: {translator_name}")

    def set_api_key(self, engine: str, api_key: str):
        with self.lock:
            self.translator_manager.set_api_key(engine, api_key)
            self.last_text_1 = ""
            self.last_text_2 = ""
            print(f"OCRWorker: API key set for: {engine}")

    def set_screenshot_engine(self, engine_name):
        with self.lock:
            if hasattr(self.screenshot_engine, "close"):
                self.screenshot_engine.close()
            self.screenshot_engine = ScreenshotFactory.get_engine(engine_name)
            self.last_text_1 = ""
            self.last_text_2 = ""
            print(f"OCRWorker: Screenshot engine: {engine_name}")

    def set_languages(self, source, target):
        with self.lock:
            self.translator_manager.set_languages(source, target)
            self.ocr_manager.set_language(source)
            self.last_text_1 = ""
            self.last_text_2 = ""
            print(f"OCRWorker: Languages: {source} -> {target}")

    def stop(self):
        self.running = False
        if self.isRunning():
            self.wait()
        if hasattr(self.screenshot_engine, "close"):
            self.screenshot_engine.close()
        self.publisher.stop()
        self.running_status.emit(False)

    def _async_translate(self, region_id: int, text: str):
        with self._translation_lock:
            self._is_translating = True
        self.translation_status.emit(True)
        try:
            cleaned = clean_ocr_text(text)
            translated = self.translator_manager.translate(cleaned)
            if region_id == 1:
                self.new_translation.emit(translated)
                self.new_translation_1.emit(translated)
            elif region_id == 2:
                self.new_translation_2.emit(translated)

            source, target = self.translator_manager.get_languages()
            self.publisher.broadcast(
                original=cleaned,
                translated=translated,
                source_lang=source,
                target_lang=target,
                engine=self.translator_manager.current_translator_name,
            )
        except Exception as e:
            print(f"Translation Error (Region {region_id}): {e}")
        finally:
            with self._translation_lock:
                self._is_translating = False
            self.translation_status.emit(False)

    def _process_region(self, region_id: int, rect: QRect, img_path: str, last_text: str, current_engine: str) -> tuple[str, bool]:
        """Captures, performs OCR, and returns (new_clean_text, should_translate)."""
        if not self.screenshot_engine.capture(rect, img_path, self.dpi_scale):
            return last_text, False

        if current_engine == "Tesseract":
            ImageProcessor.preprocess_for_tesseract(img_path, img_path)

        clean = self.ocr_manager.read_text(img_path).strip()
        if len(clean) <= 2:
            return "", False

        # Jitter detection using SequenceMatcher
        if last_text:
            if clean == last_text:
                return last_text, False
            if len(clean) > 8 and len(last_text) > 8:
                if difflib.SequenceMatcher(None, clean, last_text).ratio() >= 0.88:
                    return last_text, False

        return clean, True

    def run(self):
        self.publisher.start()
        self.running = True
        self.running_status.emit(True)
        print(f"OCRWorker: LOOP STARTED (Dual-Region Ready).")
        while self.running:
            try:
                start_total = time.perf_counter()
                with self.lock:
                    rect_1 = QRect(self.capture_rect)
                    rect_2 = QRect(self.capture_rect_2) if self.capture_rect_2 is not None else None
                    current_engine = self.ocr_manager.current_engine_name

                with self._translation_lock:
                    translating = self._is_translating

                # 1. Process Region 1 (Primary / Dialogue)
                if rect_1.width() >= 10 and rect_1.height() >= 10:
                    clean_1, should_trans_1 = self._process_region(
                        1, rect_1, IMG_PATH, self.last_text_1, current_engine
                    )
                    if should_trans_1 and not translating:
                        self.last_text_1 = clean_1
                        threading.Thread(target=self._async_translate, args=(1, clean_1), daemon=True).start()
                        print(f"[{current_engine} R1] Text: {clean_1}")
                    elif clean_1 == "" and self.last_text_1 != "":
                        self.last_text_1 = ""
                        self.new_translation_1.emit("")

                # 2. Process Region 2 (Secondary / Choices & Interaction)
                if rect_2 is not None and rect_2.width() >= 10 and rect_2.height() >= 10:
                    clean_2, should_trans_2 = self._process_region(
                        2, rect_2, IMG_PATH_2, self.last_text_2, current_engine
                    )
                    if should_trans_2 and not translating:
                        self.last_text_2 = clean_2
                        threading.Thread(target=self._async_translate, args=(2, clean_2), daemon=True).start()
                        print(f"[{current_engine} R2] Text: {clean_2}")
                    elif clean_2 == "" and self.last_text_2 != "":
                        self.last_text_2 = ""
                        self.new_translation_2.emit("")

                # Emit loop duration
                self.performance_update.emit(time.perf_counter() - start_total)

            except PortalCanceledError:
                print("OCRWorker: Portal selection canceled, stopping.")
                self.running = False
                if hasattr(self.screenshot_engine, "close"):
                    self.screenshot_engine.close()
                self.publisher.stop()
                self.running_status.emit(False)
            except Exception as e:
                print(f"Loop Error: {e}")
            time.sleep(self.LOOP_SLEEP_SECONDS)