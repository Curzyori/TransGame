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
        self.is_frozen = False
        self.publisher = TranslationPublisher()

        # Google Lens Phrase Translation Cache (phrase -> translation)
        self.translation_cache = {}
        self.phrase_stability = {}

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

    def set_frozen(self, frozen: bool):
        self.is_frozen = bool(frozen)

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
            valid_uncached = []
            for item in uncached_blocks:
                box = item[0]
                text = item[1]
                colors = item[2] if len(item) > 2 else None
                clean_t = clean_ocr_text(text)
                if clean_t:
                    valid_uncached.append((box, clean_t, colors))

            if valid_uncached:
                raw_texts = [item[1] for item in valid_uncached]
                trans_engine = self.translator_manager.current_translator_name
                print(f"[Lens] Translating {len(valid_uncached)} phrase(s) via {trans_engine}: {raw_texts}")
                translated_texts = self.translator_manager.translate_batch(raw_texts)
                source, target = self.translator_manager.get_languages()

                for item, trans in zip(valid_uncached, translated_texts):
                    orig = item[1]
                    if trans and not trans.startswith("Error:"):
                        self.translation_cache[orig] = trans
                        print(f"  ✓ '{orig}' ➔ '{trans}'")
                        self.publisher.broadcast(
                            original=orig,
                            translated=trans,
                            source_lang=source,
                            target_lang=target,
                            engine=trans_engine,
                        )

            # Build full list of pills for all visible blocks currently on screen
            all_pills = []
            for item in current_screen_blocks:
                box = item[0]
                text = item[1]
                colors = item[2] if len(item) > 2 else None
                cached = self._lookup_cache(text)
                if cached:
                    all_pills.append((box, cached, colors))

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
                if self.is_frozen:
                    time.sleep(self.LOOP_SLEEP_SECONDS)
                    continue

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
                for item in raw_blocks:
                    b_box = item[0]
                    b_text = item[1]
                    b_colors = item[2] if len(item) > 2 else None
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
                    abs_blocks.append((abs_box, cleaned_t, b_colors))

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
                    for box, text, colors in abs_blocks:
                        cached_translation = self._lookup_cache(text)
                        if cached_translation:
                            current_cached_pills.append((box, cached_translation, colors))
                        else:
                            uncached.append((box, text, colors))

                    # 1. Instantly render all cached pills on screen (0ms latency, zero flicker)
                    if current_cached_pills:
                        self.new_translation_pills.emit(current_cached_pills)
                        self.new_translation.emit(current_cached_pills[0][1], current_cached_pills[0][0])

                    # 2. Process uncached items if not currently translating
                    if uncached and not translating:
                        current_uncached_texts = {text for _, text, _ in uncached}
                        self.phrase_stability = {
                            k: v for k, v in self.phrase_stability.items() if k in current_uncached_texts
                        }

                        items_to_translate = []
                        for item in uncached:
                            box, text, colors = item
                            words = text.split()
                            # Short labels/buttons (<=3 words) are translated immediately
                            if len(words) <= 3:
                                items_to_translate.append(item)
                            else:
                                # Multi-word dialogue: wait 0.5s stability (avoids typewriter flicker)
                                if text not in self.phrase_stability:
                                    self.phrase_stability[text] = now
                                else:
                                    if (now - self.phrase_stability[text]) >= 0.5:
                                        items_to_translate.append(item)

                        if items_to_translate:
                            for item in items_to_translate:
                                self.phrase_stability.pop(item[1], None)
                            threading.Thread(
                                target=self._async_translate_blocks,
                                args=(list(abs_blocks), list(items_to_translate)),
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