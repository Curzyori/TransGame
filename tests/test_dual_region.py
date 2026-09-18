import unittest
from PySide6.QtCore import QRect
from src.core.worker import OCRWorker


class DualRegionTests(unittest.TestCase):
    def test_worker_dual_region_setup(self):
        worker = OCRWorker()
        # Region 1 default
        self.assertIsNotNone(worker.capture_rect)
        self.assertIsNone(worker.capture_rect_2)

        # Set Region 1
        r1 = QRect(200, 600, 700, 100)
        worker.set_rect(r1)
        self.assertEqual(worker.capture_rect, r1)

        # Set Region 2 (e.g. WuWa Interactive Prompt [F])
        r2 = QRect(850, 350, 300, 150)
        worker.set_rect_2(r2)
        self.assertEqual(worker.capture_rect_2, r2)

        # Clear Region 2
        worker.set_rect_2(None)
        self.assertIsNone(worker.capture_rect_2)

    def test_worker_signals_exist(self):
        worker = OCRWorker()
        self.assertTrue(hasattr(worker, "new_translation_1"))
        self.assertTrue(hasattr(worker, "new_translation_2"))
        self.assertTrue(hasattr(worker, "new_translation"))


if __name__ == "__main__":
    unittest.main()
