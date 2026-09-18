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
from src.config import IMG_PATH, DPI_SCALE_DEFAULT

class OCRWorker(QThread):
    LOOP_SLEEP_SECONDS = 0.35
    STABILITY_COOLDOWN = 1.5
    MAX_ACCUMULATION_TIME = 3.2

    new_translation = Signal(str, object)  # (translated_text, target_rect_or_None)
    performance_update = Signal(float)     # Loop duration in seconds
    translation_status = Signal(bool)      # True: translating, False: idle
    running_status = Signal(bool)          # True: system started, False: system stopped

    def __init__(self):
        super().__init__()
        self.capture_rect = QRect(560, 750, 800, 140)
        self.dpi_scale = DPI_SCALE_DEFAULT
        self.lock = Lock()
        self.running = False
        self.ocr_manager = OCRManager()
        self.translator_manager = TranslatorManager()
        self.screenshot_engine = ScreenshotFactory.get_engine()
        self._translation_lock = Lock()
        self._is_translating = False
        self.publisher = TranslationPublisher()

        # Subtitle stabilization state
        self.displayed_text = ""
        self.candidate_text = ""
        self.candidate_box = None
        self.candidate_first_seen = 0.0
        self.candidate_last_changed = 0.0
        self.empty_frames_count = 0

    def set_rect(self, qrect, dpi_scale=None):
        with self.lock:
            self.capture_rect = QRect(qrect)
            if dpi_scale is not None:
                self.dpi_scale = dpi_scale
            self.displayed_text = ""
            self.candidate_text = ""
            print(f"OCRWorker: Region: {qrect.x()},{qrect.y()} {qrect.width()}x{qrect.height()} DPI: {self.dpi_scale}")

    def set_engine(self, engine_name):
        with self.lock:
            self.ocr_manager.set_engine(engine_name)
            self.displayed_text = ""
            self.candidate_text = ""
            print(f"OCRWorker: Engine: {engine_name}")

    def set_translator(self, translator_name):
        with self.lock:
            self.translator_manager.set_translator(translator_name)
            self.displayed_text = ""
            self.candidate_text = ""
            print(f"OCRWorker: Translator: {translator_name}")

    def set_api_key(self, engine: str, api_key: str):
        with self.lock:
            self.translator_manager.set_api_key(engine, api_key)
            self.displayed_text = ""
            self.candidate_text = ""
            print(f"OCRWorker: API key set for: {engine}")

    def set_screenshot_engine(self, engine_name):
        with self.lock:
            if hasattr(self.screenshot_engine, "close"):
                self.screenshot_engine.close()
            self.screenshot_engine = ScreenshotFactory.get_engine(engine_name)
            self.displayed_text = ""
            self.candidate_text = ""
            print(f"OCRWorker: Screenshot engine: {engine_name}")

    def set_languages(self, source, target):
        with self.lock:
            self.translator_manager.set_languages(source, target)
            self.ocr_manager.set_language(source)
            self.displayed_text = ""
            self.candidate_text = ""
            print(f"OCRWorker: Languages: {source} -> {target}")

    def stop(self):
        self.running = False
        if self.isRunning():
            self.wait()
        if hasattr(self.screenshot_engine, "close"):
            self.screenshot_engine.close()
        self.publisher.stop()
        self.running_status.emit(False)

    def _async_translate(self, text: str, target_box: QRect):
        with self._translation_lock:
            self._is_translating = True
        self.translation_status.emit(True)
        try:
            cleaned = clean_ocr_text(text)
            translated = self.translator_manager.translate(cleaned)
            self.new_translation.emit(translated, target_box)

            source, target = self.translator_manager.get_languages()
            self.publisher.broadcast(
                original=cleaned,
                translated=translated,
                source_lang=source,
                target_lang=target,
                engine=self.translator_manager.current_translator_name,
            )
        except Exception as e:
            print(f"Translation Error: {e}")
        finally:
            with self._translation_lock:
                self._is_translating = False
            self.translation_status.emit(False)

    def run(self):
        self.publisher.start()
        self.running = True
        self.running_status.emit(True)
        print(f"OCRWorker: LOOP STARTED (In-Place Lens Mode).")

        while self.running:
            try:
                start_total = time.perf_counter()
                with self.lock:
                    rect = QRect(self.capture_rect)
                    current_engine = self.ocr_manager.current_engine_name

                with self._translation_lock:
                    translating = self._is_translating

                if rect.width() < 10 or rect.height() < 10:
                    time.sleep(self.LOOP_SLEEP_SECONDS)
                    continue

                if not self.screenshot_engine.capture(rect, IMG_PATH, self.dpi_scale):
                    time.sleep(self.LOOP_SLEEP_SECONDS)
                    continue

                if current_engine == "Tesseract":
                    ImageProcessor.preprocess_for_tesseract(IMG_PATH, IMG_PATH)

                # Extract dialogue and union bounding box
                clean, rel_box = self.ocr_manager.read_dialogue_with_box(IMG_PATH)

                # Convert relative box to absolute screen coordinates
                if rel_box:
                    abs_box = QRect(
                        rect.x() + rel_box[0],
                        rect.y() + rel_box[1],
                        rel_box[2],
                        rel_box[3],
                    )
                else:
                    abs_box = QRect(rect)

                now = time.time()

                if not clean or len(clean) < 3:
                    # Dialogue empty / absent
                    self.empty_frames_count += 1
                    if self.empty_frames_count >= 3:
                        if self.displayed_text != "":
                            self.displayed_text = ""
                            self.candidate_text = ""
                            self.new_translation.emit("", None)
                else:
                    self.empty_frames_count = 0

                    # Check if it matches currently displayed text (jitter tolerance)
                    is_same_as_displayed = False
                    if self.displayed_text:
                        if clean == self.displayed_text:
                            is_same_as_displayed = True
                        elif len(clean) > 8 and len(self.displayed_text) > 8:
                            if difflib.SequenceMatcher(None, clean, self.displayed_text).ratio() >= 0.88:
                                is_same_as_displayed = True

                    if is_same_as_displayed:
                        # Dialogue is still actively displayed on screen.
                        # Reset candidate and hold current translation.
                        self.candidate_text = ""
                        self.candidate_first_seen = 0.0
                    else:
                        # New dialogue is streaming in!
                        if not self.candidate_text:
                            self.candidate_first_seen = now
                            self.candidate_text = clean
                            self.candidate_box = abs_box
                            self.candidate_last_changed = now
                        elif clean != self.candidate_text:
                            self.candidate_text = clean
                            self.candidate_box = abs_box
                            self.candidate_last_changed = now

                        time_stable = now - self.candidate_last_changed
                        total_wait = now - self.candidate_first_seen

                        # Stabilized condition: text stopped changing for STABILITY_COOLDOWN or reached MAX_ACCUMULATION
                        if (time_stable >= self.STABILITY_COOLDOWN or total_wait >= self.MAX_ACCUMULATION_TIME) and not translating:
                            self.displayed_text = self.candidate_text
                            target_box = self.candidate_box or abs_box
                            text_to_translate = self.candidate_text
                            self.candidate_text = ""
                            self.candidate_first_seen = 0.0

                            threading.Thread(
                                target=self._async_translate,
                                args=(text_to_translate, target_box),
                                daemon=True,
                            ).start()
                            print(f"[{current_engine}] Stabilized dialogue: {text_to_translate}")

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