import unittest
from PySide6.QtCore import QRect
from src.core.worker import OCRWorker


class LensWorkerTests(unittest.TestCase):
    def test_worker_single_region_setup(self):
        worker = OCRWorker()
        self.assertIsNotNone(worker.capture_rect)

        # Set Region
        r1 = QRect(200, 600, 700, 100)
        worker.set_rect(r1)
        self.assertEqual(worker.capture_rect, r1)

    def test_worker_signals_and_stabilization_state(self):
        worker = OCRWorker()
        self.assertTrue(hasattr(worker, "new_translation"))
        self.assertTrue(hasattr(worker, "new_translation_pills"))
        self.assertTrue(hasattr(worker, "performance_update"))
        self.assertTrue(hasattr(worker, "translation_status"))
        self.assertTrue(hasattr(worker, "running_status"))

        # Check stabilization thresholds
        self.assertEqual(worker.STABILITY_COOLDOWN, 2.0)
        self.assertEqual(worker.MAX_ACCUMULATION_TIME, 3.5)
        self.assertEqual(worker.displayed_text, "")
        self.assertEqual(worker.candidate_text, "")

    def test_worker_async_translate_emits_box(self):
        worker = OCRWorker()
        emitted_results = []
        worker.new_translation.connect(lambda txt, box: emitted_results.append((txt, box)))

        target_box = QRect(300, 500, 400, 100)
        worker._async_translate("Hello world", target_box)

        self.assertEqual(len(emitted_results), 1)
        trans_txt, box = emitted_results[0]
        self.assertIn("Halo", trans_txt)
        self.assertEqual(box, target_box)


if __name__ == "__main__":
    unittest.main()
