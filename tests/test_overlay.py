import unittest
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QRect
from src.ui.overlay_window import TransparentOverlay


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_window_transparent_for_input_flag(self):
        overlay = TransparentOverlay(enable_hotkey=False)
        flags = overlay.windowFlags()
        self.assertTrue(bool(flags & Qt.WindowTransparentForInput))
        self.assertTrue(overlay.testAttribute(Qt.WA_TransparentForMouseEvents))
        overlay.close()

    def test_set_pills_in_place(self):
        overlay = TransparentOverlay(enable_hotkey=False)
        box1 = QRect(300, 600, 400, 50)
        box2 = QRect(700, 350, 200, 40)

        overlay.set_pills([(box1, "Halo dunia"), (box2, "Pilihan interaksi")])
        self.assertEqual(len(overlay.pills), 2)
        self.assertFalse(overlay.isHidden())

        # Clear pills
        overlay.set_pills([])
        self.assertEqual(len(overlay.pills), 0)
        self.assertTrue(overlay.isHidden())
        overlay.close()


if __name__ == "__main__":
    unittest.main()
