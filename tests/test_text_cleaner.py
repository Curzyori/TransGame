import unittest
from src.core.translation.text_cleaner import clean_ocr_text, is_translatable_text


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

    def test_is_translatable_valid_dialogue(self):
        self.assertTrue(is_translatable_text("Rover, about the sugar pearl..."))
        self.assertTrue(is_translatable_text("Talk about the founding of Jinzhou."))
        self.assertTrue(is_translatable_text("I've promised the missing man's grandfather to bring him back."))
        self.assertTrue(is_translatable_text("Would you let me through?"))

    def test_is_translatable_filters_out_numbers_and_symbols(self):
        # Pure numbers
        self.assertFalse(is_translatable_text("100"))
        self.assertFalse(is_translatable_text("0"))
        self.assertFalse(is_translatable_text("12345"))
        # Pure symbols
        self.assertFalse(is_translatable_text("/"))
        self.assertFalse(is_translatable_text("->"))
        self.assertFalse(is_translatable_text("..."))
        self.assertFalse(is_translatable_text("---"))
        # Single keys / shortcuts
        self.assertFalse(is_translatable_text("F"))
        self.assertFalse(is_translatable_text("E"))
        self.assertFalse(is_translatable_text("<E>"))
        self.assertFalse(is_translatable_text("[F]"))
        # Game telemetry / UI metrics
        self.assertFalse(is_translatable_text("186ms"))
        self.assertFalse(is_translatable_text("29m"))
        self.assertFalse(is_translatable_text("60fps"))
        self.assertFalse(is_translatable_text("L20"))
        # User ID / Timestamps
        self.assertFalse(is_translatable_text("UserID:718261532"))
        self.assertFalse(is_translatable_text("08.12026-09-1806:59:44+7"))


if __name__ == "__main__":
    unittest.main()
