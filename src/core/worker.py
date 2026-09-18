import time
import difflib
import threading
from threading import Lock
from PySide6.QtCore import QThread, Signal, QRect
from src.core.ocr.ocr_manager import OCRManager
from src.core.translation.translator_manager import TranslatorManager
from src.core.translation.text_cleaner import clean_ocr_text, is_translatable_text
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

        # Google Lens Phrase Translation Cache (phrase -> translation)
        self.translation_cache = {}

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

    def _lookup_cache(self, text: str):
        if not text:
            return None
        # 1. Exact match
        if text in self.translation_cache:
            return self.translation_cache[text]

        # 2. Case-insensitive / stripped match
        text_clean = text.strip()
        text_lower = text_clean.lower()
        for k, v in self.translation_cache.items():
            if k.lower().strip() == text_lower:
                self.translation_cache[text] = v
                return v

        # 3. Fuzzy match for OCR jitter on longer sentences (>= 8 chars)
        if len(text_clean) >= 8:
            for k, v in self.translation_cache.items():
                if len(k) >= 8 and abs(len(k) - len(text_clean)) <= 4:
                    if difflib.SequenceMatcher(None, text_clean, k).ratio() >= 0.88:
                        self.translation_cache[text] = v
                        return v

        return None

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
            self.translation_cache.clear()
            self.displayed_text = ""
            self.candidate_text = ""
            print(f"OCRWorker: Engine: {engine_name}")

    def set_translator(self, translator_name):
        with self.lock:
            self.translator_manager.set_translator(translator_name)
            self.translation_cache.clear()
            self.displayed_text = ""
            self.candidate_text = ""
            print(f"OCRWorker: Translator: {translator_name}")

    def set_api_key(self, engine: str, api_key: str):
        with self.lock:
            self.translator_manager.set_api_key(engine, api_key)
            self.translation_cache.clear()
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
            self.translation_cache.clear()
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

    def _async_translate_blocks(self, current_screen_blocks: list, uncached_blocks: list = None):
        if uncached_blocks is None:
            uncached_blocks = current_screen_blocks

        with self._translation_lock:
            self._is_translating = True
        self.translation_status.emit(True)
        try:
            valid_uncached = [(box, clean_ocr_text(text)) for box, text in uncached_blocks if text and clean_ocr_text(text)]
            if valid_uncached:
                raw_texts = [t for _, t in valid_uncached]
                translated_texts = self.translator_manager.translate_batch(raw_texts)
                source, target = self.translator_manager.get_languages()

                for (box, orig), translated in zip(valid_uncached, translated_texts):
                    if translated and not translated.startswith("Error:"):
                        self.translation_cache[orig] = translated
                        self.publisher.broadcast(
                            original=orig,
                            translated=translated,
                            source_lang=source,
                            target_lang=target,
                            engine=self.translator_manager.current_translator_name,
                        )

            # Build full list of pills for all visible blocks currently on screen
            all_pills = []
            for box, text in current_screen_blocks:
                cached = self._lookup_cache(text)
                if cached:
                    all_pills.append((box, cached))

            self.new_translation_pills.emit(all_pills)
            if all_pills:
                self.new_translation.emit(all_pills[0][1], all_pills[0][0])
        except Exception as e:
            print(f"Translation Error: {e}")
        finally:
            with self._translation_lock:
                self._is_translating = False
            self.translation_status.emit(False)

    def _async_translate(self, text: str, target_box: QRect):
        self._async_translate_blocks([(target_box, text)], [(target_box, text)])

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
                    cleaned_t = clean_ocr_text(b_text)
                    if not is_translatable_text(cleaned_t):
                        continue
                    if b_box:
                        abs_box = QRect(
                            rect.x() + b_box.x(),
                            rect.y() + b_box.y(),
                            b_box.width(),
                            b_box.height(),
                        )
                    else:
                        abs_box = QRect(rect)
                    abs_blocks.append((abs_box, cleaned_t))

                now = time.time()

                if not abs_blocks:
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

                    # Google Lens Phrase Translation Cache matching
                    current_cached_pills = []
                    uncached = []
                    for box, text in abs_blocks:
                        cached_translation = self._lookup_cache(text)
                        if cached_translation:
                            current_cached_pills.append((box, cached_translation))
                        else:
                            uncached.append((box, text))

                    # 1. Instantly render all cached pills on screen (0ms latency, zero flicker)
                    if current_cached_pills:
                        self.new_translation_pills.emit(current_cached_pills)
                        self.new_translation.emit(current_cached_pills[0][1], current_cached_pills[0][0])

                    # 2. Process uncached items if not currently translating
                    if uncached and not translating:
                        # Check if any uncached item is an expanding typewriter dialogue
                        has_growing_dialogue = False
                        for _, text in uncached:
                            words = text.split()
                            if len(words) > 3:
                                # Multi-word dialogue: typewriter debounce
                                if self.candidate_signature != text:
                                    self.candidate_signature = text
                                    self.candidate_first_seen = now
                                    self.candidate_last_changed = now
                                    has_growing_dialogue = True
                                else:
                                    time_stable = now - self.candidate_last_changed
                                    total_wait = now - self.candidate_first_seen
                                    if time_stable < self.STABILITY_COOLDOWN and total_wait < self.MAX_ACCUMULATION_TIME:
                                        has_growing_dialogue = True

                        if not has_growing_dialogue:
                            self.candidate_signature = ""
                            self.candidate_first_seen = 0.0
                            threading.Thread(
                                target=self._async_translate_blocks,
                                args=(list(abs_blocks), list(uncached)),
                                daemon=True,
                            ).start()

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