import unittest
from unittest import mock

from src.core.translation.argos_engine import ArgosEngine
from src.core.translation.translator_manager import TranslatorManager


class ArgosEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = ArgosEngine(source="en", target="id")

    def test_argos_is_available(self):
        self.assertTrue(ArgosEngine.is_available())

    def test_en_id_model_is_installed(self):
        self.assertTrue(self.engine.is_model_installed("en", "id"))

    def test_id_en_model_is_installed(self):
        self.assertTrue(self.engine.is_model_installed("id", "en"))

    def test_offline_translation_en_to_id(self):
        result = self.engine.translate("Hello world")
        self.assertTrue(len(result) > 0)
        self.assertNotIn("Error:", result)
        # Expected Indonesian translation contains "Halo"
        self.assertIn("Halo", result)

    def test_offline_translation_empty_string(self):
        self.assertEqual(self.engine.translate(""), "")
        self.assertEqual(self.engine.translate("   "), "   ")

    def test_uninstalled_model_returns_friendly_error(self):
        self.engine.set_languages("en", "zz")  # nonexistent language code
        result = self.engine.translate("Hello")
        self.assertTrue(result.startswith("Error:"))
        self.assertIn("not installed", result)

    def test_translator_manager_integration(self):
        manager = TranslatorManager()
        self.assertIn("Argos (Offline)", manager.translators)
        manager.set_translator("Argos (Offline)")
        self.assertEqual(manager.current_translator_name, "Argos (Offline)")
        manager.set_languages("en", "id")
        result = manager.translate("Hello world")
        self.assertIn("Halo", result)


if __name__ == "__main__":
    unittest.main()
