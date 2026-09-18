# Unit test for Google Lens Phrase Translation Cache in OCRWorker
# Callers: unittest discover
# Affected API: OCRWorker._lookup_cache, OCRWorker.translation_cache
# User instruction: "pahami dlu kkode google lens translate itu, gw mau 100% seperti dia"
import unittest
from PySide6.QtCore import QRect
from src.core.worker import OCRWorker


class PhraseCacheTests(unittest.TestCase):
    def setUp(self):
        self.worker = OCRWorker()

    def test_exact_cache_hit(self):
        self.worker.translation_cache["STORE"] = "TOKO"
        res = self.worker._lookup_cache("STORE")
        self.assertEqual(res, "TOKO")

    def test_case_insensitive_cache_hit(self):
        self.worker.translation_cache["PLAY"] = "MAINKAN"
        res = self.worker._lookup_cache("play")
        self.assertEqual(res, "MAINKAN")

    def test_fuzzy_match_jitter_tolerance(self):
        # When OCR has minor character jitter (e.g. 'I' vs 'l' or punctuation)
        original = "Rover, about the sugar pearl..."
        self.worker.translation_cache[original] = "Rover, tentang mutiara gula..."

        jittered = "Rover, about the sugar pearI..."
        res = self.worker._lookup_cache(jittered)
        self.assertEqual(res, "Rover, tentang mutiara gula...")
        # Should now also be indexed directly in cache
        self.assertIn(jittered, self.worker.translation_cache)

    def test_cache_cleared_on_language_change(self):
        self.worker.translation_cache["STORE"] = "TOKO"
        self.worker.set_languages("en", "ja")
        self.assertEqual(len(self.worker.translation_cache), 0)


if __name__ == "__main__":
    unittest.main()
