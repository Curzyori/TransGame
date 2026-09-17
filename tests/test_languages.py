import unittest

from src.config import LANGUAGES, OCR_LANG_MAPPING, get_language_code, get_translation_language_code


class LanguageConfigurationTests(unittest.TestCase):
    def test_indonesian_in_languages(self):
        self.assertIn("Indonesian", LANGUAGES)
        id_config = LANGUAGES["Indonesian"]
        self.assertEqual(id_config["code"], "id")
        self.assertEqual(id_config["google"]["source"], "id")
        self.assertEqual(id_config["google"]["target"], "id")
        self.assertEqual(id_config["deepl"]["source"], "id")
        self.assertEqual(id_config["deepl"]["target"], "id")

    def test_indonesian_in_ocr_lang_mapping(self):
        self.assertIn("id", OCR_LANG_MAPPING)
        mapping = OCR_LANG_MAPPING["id"]
        self.assertEqual(mapping["tess"], "ind")
        self.assertEqual(mapping["easy"], "id")
        self.assertEqual(mapping["rapid"], "latin")
        self.assertEqual(mapping["paddle"], "en")

    def test_get_language_code_indonesian(self):
        self.assertEqual(get_language_code("Indonesian", "en"), "id")

    def test_get_translation_language_code_indonesian(self):
        self.assertEqual(get_translation_language_code("id", "google", "source"), "id")
        self.assertEqual(get_translation_language_code("id", "google", "target"), "id")
        self.assertEqual(get_translation_language_code("id", "deepl", "source"), "id")
        self.assertEqual(get_translation_language_code("id", "deepl", "target"), "id")


if __name__ == "__main__":
    unittest.main()
