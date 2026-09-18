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
    STABILITY_COOLDOWN = 2.0
    MAX_ACCUMULATION_TIME = 3.5

    new_translation_pills = Signal(object)  # List[Tuple[QRect, str]]
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
        self.active_signature = ""
        self.displayed_text = ""
        self.candidate_signature = ""
        self.candidate_text = ""
        self.candidate_blocks = []
        self.candidate_box = None
        self.candidate_first_seen = 0.0
        self.candidate_last_changed = 0.0
        self.empty_frames_count = 0

    def set_rect(self, qrect, dpi_scale=None):
        with self.lock:
            self.capture_rect = QRect(qrect)
            if dpi_scale is not None:
                self.dpi_scale = dpi_scale
            self.active_signature = ""
            self.displayed_text = ""
            self.candidate_signature = ""
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

    def _async_translate_blocks(self, blocks: list):
        with self._translation_lock:
            self._is_translating = True
        self.translation_status.emit(True)
        try:
            valid_blocks = [(box, clean_ocr_text(text)) for box, text in blocks if text and clean_ocr_text(text)]
            if not valid_blocks:
                self.new_translation_pills.emit([])
                return

            raw_texts = [t for _, t in valid_blocks]
            translated_texts = self.translator_manager.translate_batch(raw_texts)

            translated_pills = []
            source, target = self.translator_manager.get_languages()

            for (box, orig), translated in zip(valid_blocks, translated_texts):
                if translated and not translated.startswith("Error:"):
                    translated_pills.append((box, translated))
                    self.publisher.broadcast(
                        original=orig,
                        translated=translated,
                        source_lang=source,
                        target_lang=target,
                        engine=self.translator_manager.current_translator_name,
                    )

            self.new_translation_pills.emit(translated_pills)
            if translated_pills:
                self.new_translation.emit(translated_pills[0][1], translated_pills[0][0])
        except Exception as e:
            print(f"Translation Error: {e}")
        finally:
            with self._translation_lock:
                self._is_translating = False
            self.translation_status.emit(False)

    def _async_translate(self, text: str, target_box: QRect):
        self._async_translate_blocks([(target_box, text)])

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

                # Extract translatable text blocks with individual bounding boxes
                raw_blocks = self.ocr_manager.extract_text_blocks(IMG_PATH)

                abs_blocks = []
                for b_box, b_text in raw_blocks:
                    if b_box:
                        abs_box = QRect(
                            rect.x() + b_box.x(),
                            rect.y() + b_box.y(),
                            b_box.width(),
                            b_box.height(),
                        )
                    else:
                        abs_box = QRect(rect)
                    abs_blocks.append((abs_box, b_text))

                detected_signature = " | ".join(t for _, t in abs_blocks)
                now = time.time()

                if not detected_signature or len(detected_signature) < 3:
                    # Dialogue empty / absent
                    self.empty_frames_count += 1
                    if self.empty_frames_count >= 4:
                        if self.active_signature != "":
                            self.active_signature = ""
                            self.displayed_text = ""
                            self.candidate_signature = ""
                            self.candidate_text = ""
                            self.new_translation_pills.emit([])
                            self.new_translation.emit("", None)
                else:
                    self.empty_frames_count = 0

                    # Check if it matches currently displayed text (jitter tolerance)
                    is_same_as_active = False
                    if self.active_signature:
                        if detected_signature == self.active_signature:
                            is_same_as_active = True
                        elif len(detected_signature) > 8 and len(self.active_signature) > 8:
                            if difflib.SequenceMatcher(None, detected_signature, self.active_signature).ratio() >= 0.88:
                                is_same_as_active = True

                    if is_same_as_active:
                        # Current dialogue is still actively on screen! Hold it.
                        self.candidate_signature = ""
                        self.candidate_text = ""
                        self.candidate_first_seen = 0.0
                    else:
                        # New or typewriter dialogue streaming in!
                        if not self.candidate_signature:
                            self.candidate_first_seen = now
                            self.candidate_signature = detected_signature
                            self.candidate_blocks = abs_blocks
                            self.candidate_last_changed = now
                        elif detected_signature != self.candidate_signature:
                            self.candidate_signature = detected_signature
                            self.candidate_blocks = abs_blocks
                            self.candidate_last_changed = now

                        time_stable = now - self.candidate_last_changed
                        total_wait = now - self.candidate_first_seen

                        # Stabilized condition: text stopped growing/changing for STABILITY_COOLDOWN or reached MAX_ACCUMULATION
                        if (time_stable >= self.STABILITY_COOLDOWN or total_wait >= self.MAX_ACCUMULATION_TIME) and not translating:
                            self.active_signature = self.candidate_signature
                            self.displayed_text = self.candidate_signature
                            blocks_to_translate = list(self.candidate_blocks)
                            self.candidate_signature = ""
                            self.candidate_text = ""
                            self.candidate_first_seen = 0.0

                            threading.Thread(
                                target=self._async_translate_blocks,
                                args=(blocks_to_translate,),
                                daemon=True,
                            ).start()
                            print(f"[{current_engine}] Stabilized dialogue: {self.active_signature}")

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