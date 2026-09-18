import glob
import os

from PySide6.QtCore import QRect
from src.core.ocr.base_ocr import BaseOCREngine
from src.config import OCR_LANG_MAPPING

_MODELS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "ocr_models",
    "rapidocr",
)


class RapidOCREngine(BaseOCREngine):
    DEFAULT_CPU_THREADS = 1
    THREAD_ENV_VARS = (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "ORT_NUM_THREADS",
    )

    def __init__(self, cpu_threads: int = DEFAULT_CPU_THREADS):
        self.ocr = None
        self.current_lang = "en"
        self._unavailable_reason = None
        self.cpu_threads = max(1, int(cpu_threads))

    @staticmethod
    def _get_model_path(lang_code: str) -> str:
        if not lang_code or lang_code == "en":
            return ""

        pattern = os.path.join(_MODELS_DIR, f"{lang_code}_PP-OCR*.onnx")
        matches = sorted(glob.glob(pattern))
        if matches:
            print(f"RapidOCREngine: Found recognition model for lang={lang_code}: {os.path.basename(matches[0])}")
            return matches[0]

        print(f"RapidOCREngine: No recognition model found for lang={lang_code}, using default")
        return ""

    def set_language(self, lang_code: str):
        mapping = OCR_LANG_MAPPING.get(lang_code, OCR_LANG_MAPPING["en"])
        new_lang = mapping.get("rapid", mapping.get("paddle", "en"))

        if new_lang != self.current_lang:
            self.current_lang = new_lang
            self.ocr = None  # Trigger re-initialization on next read
            self._unavailable_reason = None
            print(f"RapidOCREngine: Language scheduled for update: {self.current_lang}")

    def _apply_cpu_limit(self):
        thread_count = str(self.cpu_threads)
        for env_var in self.THREAD_ENV_VARS:
            os.environ.setdefault(env_var, thread_count)

    def _patch_rapidocr_ort_session(self):
        from onnxruntime import GraphOptimizationLevel, InferenceSession, SessionOptions
        from rapidocr_onnxruntime.utils import OrtInferSession, get_available_providers, get_device

        cpu_threads = self.cpu_threads

        def limited_init(session_self, config):
            sess_opt = SessionOptions()
            sess_opt.log_severity_level = 4
            sess_opt.enable_cpu_mem_arena = False
            sess_opt.graph_optimization_level = GraphOptimizationLevel.ORT_ENABLE_ALL
            sess_opt.intra_op_num_threads = cpu_threads
            sess_opt.inter_op_num_threads = 1

            cpu_ep = "CPUExecutionProvider"
            cpu_provider_options = {
                "arena_extend_strategy": "kSameAsRequested",
                "intra_op_num_threads": str(cpu_threads),
            }

            cuda_ep = "CUDAExecutionProvider"
            cuda_provider_options = {
                "device_id": 0,
                "arena_extend_strategy": "kNextPowerOfTwo",
                "cudnn_conv_algo_search": "EXHAUSTIVE",
                "do_copy_in_default_stream": True,
            }

            ep_list = []
            if (
                config["use_cuda"]
                and get_device() == "GPU"
                and cuda_ep in get_available_providers()
            ):
                ep_list = [(cuda_ep, cuda_provider_options)]
            ep_list.append((cpu_ep, cpu_provider_options))

            session_self._verify_model(config["model_path"])
            session_self.session = InferenceSession(
                config["model_path"],
                sess_options=sess_opt,
                providers=ep_list,
            )

        if getattr(OrtInferSession.__init__, "_usta_cpu_limited", False):
            print("RapidOCREngine: OrtInferSession already patched, skipping")
            return

        limited_init._usta_cpu_limited = True
        OrtInferSession.__init__ = limited_init
        print("RapidOCREngine: OrtInferSession monkey-patched for CPU thread limiting")

    def _initialize(self) -> bool:
        if self.ocr is not None:
            return True

        if self._unavailable_reason:
            return False

        try:
            self._apply_cpu_limit()

            from rapidocr_onnxruntime import RapidOCR

            self._patch_rapidocr_ort_session()

            print(
                "RapidOCREngine: Initializing reader "
                f"with lang={self.current_lang}, cpu_threads={self.cpu_threads}, "
                "use_text_det=True, use_angle_cls=False"
            )
            rec_model_path = self._get_model_path(self.current_lang)

            self.ocr = RapidOCR(
                use_text_det=True,
                use_angle_cls=False,
                det_model_path="",
                det_limit_side_len=960,
                rec_model_path=rec_model_path,
                rec_batch_num=1,
            )
            return True
        except ImportError:
            self._unavailable_reason = (
                "RapidOCR is not installed. "
                "Install it with: pip install rapidocr-onnxruntime onnxruntime"
            )
            print(f"RapidOCREngine: {self._unavailable_reason}")
            return False
        except Exception as e:
            self._unavailable_reason = f"RapidOCR initialization failed: {e}"
            print(f"RapidOCREngine: {self._unavailable_reason}")
            return False

    def _extract_lines(self, result):
        if not result:
            return []

        # rapidocr-onnxruntime commonly returns (ocr_result, elapsed_time).
        if isinstance(result, tuple):
            result = result[0]

        # Some RapidOCR versions return an object with a result-like attribute.
        if hasattr(result, "txts"):
            return [text for text in result.txts if text]
        if hasattr(result, "texts"):
            return [text for text in result.texts if text]
        if hasattr(result, "result"):
            result = result.result

        lines = []
        for item in result or []:
            text = ""
            confidence = 1.0

            if isinstance(item, dict):
                text = item.get("text") or item.get("rec_text") or ""
                confidence = item.get("score", item.get("confidence", 1.0))
            elif isinstance(item, (list, tuple)):
                if len(item) >= 3 and isinstance(item[1], str):
                    # [box, text, confidence]
                    text = item[1]
                    confidence = item[2]
                elif len(item) >= 2 and isinstance(item[1], (list, tuple)):
                    # Paddle-like fallback: [box, [text, confidence]]
                    text = item[1][0] if item[1] else ""
                    confidence = item[1][1] if len(item[1]) > 1 else 1.0
                elif item and isinstance(item[0], str):
                    text = item[0]
                    confidence = item[1] if len(item) > 1 else 1.0

            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = 1.0

            if text and confidence > 0.2:
                lines.append(text)

        return lines

    def extract_text_blocks(self, image_path: str):
        """
        Extracts translatable text blocks from the image.
        Lines that are vertically close (<28px) and horizontally overlapping/aligned are
        clustered into a single dialogue block (e.g. multi-line dialogue).
        Distant text lines (like action prompts or menu buttons) remain separate blocks.
        Returns: list of (QRect, text)
        """
        if not self._initialize():
            return []

        try:
            result = self.ocr(image_path)
            if not result:
                return []
            if isinstance(result, tuple):
                result = result[0]
            if hasattr(result, "result"):
                result = result.result

            from src.core.translation.text_cleaner import is_translatable_text, clean_ocr_text

            raw_items = []
            for item in result or []:
                text = ""
                box = None
                conf = 1.0

                if isinstance(item, (list, tuple)):
                    if len(item) >= 3 and isinstance(item[1], str):
                        box = item[0]
                        text = item[1].strip()
                        try:
                            conf = float(item[2])
                        except (TypeError, ValueError):
                            conf = 1.0
                    elif len(item) >= 2 and isinstance(item[1], (list, tuple)):
                        box = item[0]
                        text = item[1][0].strip() if item[1] else ""
                        conf = float(item[1][1]) if len(item[1]) > 1 else 1.0

                if text and conf > 0.2 and box and any(c.isalpha() for c in text):
                    try:
                        xs = [p[0] for p in box]
                        ys = [p[1] for p in box]
                        rect = QRect(
                            int(min(xs)),
                            int(min(ys)),
                            max(10, int(max(xs) - min(xs))),
                            max(10, int(max(ys) - min(ys))),
                        )
                        raw_items.append((rect, text))
                    except Exception:
                        pass

            if not raw_items:
                return []

            # Cluster lines into blocks like Google Lens:
            # Multi-line sentences merge together; standalone buttons/labels remain distinct
            clustered = []
            for rect, text in raw_items:
                merged = False
                words = text.split()
                is_short_label = len(words) <= 3 and not text.endswith((".", "?", "!", "...", "…"))

                if not is_short_label:
                    for i, (b_rect, b_texts) in enumerate(clustered):
                        b_last_text = b_texts[-1]
                        # If previous line ends with terminal punctuation, don't merge next sentence into it
                        if b_last_text.endswith((".", "?", "!")) and not b_last_text.endswith(("...", "…")):
                            continue

                        v_dist = rect.top() - b_rect.bottom()
                        h_diff = abs(rect.height() - b_rect.height()) / max(rect.height(), b_rect.height())
                        h_overlap = min(rect.right(), b_rect.right()) - max(rect.left(), b_rect.left())
                        min_w = min(rect.width(), b_rect.width())

                        # Merge if directly below (< 22px), similar height, and horizontally aligned
                        if 0 <= v_dist <= 22 and h_diff <= 0.35 and (h_overlap > 0.4 * min_w or abs(rect.left() - b_rect.left()) < 40):
                            new_rect = b_rect.united(rect)
                            b_texts.append(text)
                            clustered[i] = (new_rect, b_texts)
                            merged = True
                            break

                if not merged:
                    clustered.append((rect, [text]))

            from PIL import Image
            pil_img = None
            try:
                pil_img = Image.open(image_path).convert("RGB")
            except Exception:
                pass

            result_blocks = []
            for r, t in clustered:
                if t:
                    combined = " ".join(t)
                    if is_translatable_text(clean_ocr_text(combined)):
                        colors = self._sample_box_colors(pil_img, r) if pil_img else ("#1F1F1F", "#FFFFFF")
                        result_blocks.append((r, combined, colors))

            return result_blocks
        except Exception as e:
            print(f"RapidOCR extract_text_blocks Error: {e}")
            return []

    @staticmethod
    def _sample_box_colors(pil_image, rect: QRect) -> tuple[str, str]:
        if not pil_image:
            return ("#1F1F1F", "#FFFFFF")
        w, h = pil_image.size
        x1 = max(0, min(w - 1, rect.x()))
        y1 = max(0, min(h - 1, rect.y()))
        x2 = max(0, min(w - 1, rect.right()))
        y2 = max(0, min(h - 1, rect.bottom()))
        points = [
            (x1, y1), (x2, y1),
            (x1, y2), (x2, y2),
            (x1, (y1 + y2) // 2), (x2, (y1 + y2) // 2),
            ((x1 + x2) // 2, y1), ((x1 + x2) // 2, y2),
        ]
        colors = []
        for px, py in points:
            try:
                colors.append(pil_image.getpixel((px, py)))
            except Exception:
                pass

        if not colors:
            return ("#1F1F1F", "#FFFFFF")

        r_avg = int(sum(c[0] for c in colors) / len(colors))
        g_avg = int(sum(c[1] for c in colors) / len(colors))
        b_avg = int(sum(c[2] for c in colors) / len(colors))
        bg_hex = f"#{r_avg:02X}{g_avg:02X}{b_avg:02X}"

        luminance = 0.299 * r_avg + 0.587 * g_avg + 0.114 * b_avg
        fg_hex = "#111111" if luminance > 145 else "#FFFFFF"
        return (bg_hex, fg_hex)

    def read_dialogue_with_box(self, image_path: str):
        blocks = self.extract_text_blocks(image_path)
        if not blocks:
            return "", None
        full_text = " ".join(b[1] for b in blocks)
        first_box = (blocks[0][0].x(), blocks[0][0].y(), blocks[0][0].width(), blocks[0][0].height())
        return full_text.strip(), first_box

    def read_text(self, image_path: str) -> str:
        text, _ = self.read_dialogue_with_box(image_path)
        if text:
            return text

        if not self._initialize():
            return ""

        try:
            result = self.ocr(image_path)
            lines = self._extract_lines(result)
            clean = " ".join(lines)
            return " ".join(clean.split()).strip().strip("_").rstrip(":")
        except Exception as e:
            print(f"RapidOCR Error: {e}")
            return ""