import unittest
from src.core.translation.text_cleaner import clean_ocr_text


class TextCleanerTests(unittest.TestCase):
    def test_clean_punctuation_spacing(self):
        raw = "someday.I wanted to stay"
        expected = "someday. I wanted to stay"
        self.assertEqual(clean_ocr_text(raw), expected)

    def test_clean_wuwa_dialogue(self):
        raw = "Yuancai Hey,check it out! It's the first ResonanceNexus in Huanglong, part of our institute's collection. Isn't it gorgeous?"
        cleaned = clean_ocr_text(raw)
        self.assertIn("Hey, check", cleaned)
        self.assertIn("Resonance Nexus", cleaned)
        self.assertIn("collection. Isn't", cleaned)

    def test_clean_pronoun_i(self):
        raw = "whenIrealizedIhadto workhere"
        cleaned = clean_ocr_text(raw)
        self.assertIn("when I realized I had", cleaned)

    def test_empty_or_whitespace(self):
        self.assertEqual(clean_ocr_text(""), "")
        self.assertEqual(clean_ocr_text("   "), "")


if __name__ == "__main__":
    unittest.main()
