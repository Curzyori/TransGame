import unittest
from unittest import mock
from src.core.translation.google_engine import GoogleEngine


class GoogleEngineFallbackTests(unittest.TestCase):
    def test_translate_fallback_to_gtx_on_deep_translator_error(self):
        engine = GoogleEngine(source="en", target="id")

        # Simulate deep_translator raising an error (e.g. TooManyRequests)
        with mock.patch.object(engine.translator, "translate", side_effect=Exception("Rate limit")):
            with mock.patch.object(engine, "_translate_gtx", return_value="Halo dunia") as mock_gtx:
                result = engine.translate("Hello world")
                self.assertEqual(result, "Halo dunia")
                mock_gtx.assert_called_once_with("Hello world")

    def test_translate_normal_path(self):
        engine = GoogleEngine(source="en", target="id")
        with mock.patch.object(engine.translator, "translate", return_value="Halo"):
            result = engine.translate("Hello")
            self.assertEqual(result, "Halo")


if __name__ == "__main__":
    unittest.main()
