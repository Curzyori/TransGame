import unittest
from unittest import mock
from src.core.translation.hybrid_engine import HybridEngine


class HybridEngineTests(unittest.TestCase):
    def test_hybrid_primary_success(self):
        engine = HybridEngine(source="en", target="id")
        with mock.patch.object(engine.google, "translate", return_value="Halo dunia") as mock_google:
            res = engine.translate("Hello world")
            self.assertEqual(res, "Halo dunia")
            mock_google.assert_called_once()

    def test_hybrid_fallback_to_argos_on_google_error(self):
        engine = HybridEngine(source="en", target="id")
        with mock.patch.object(engine.google, "translate", side_effect=Exception("Network error")):
            with mock.patch.object(engine.argos, "translate", return_value="Halo dunia (offline)") as mock_argos:
                res = engine.translate("Hello world")
                self.assertEqual(res, "Halo dunia (offline)")
                mock_argos.assert_called_once()

    def test_hybrid_translate_batch(self):
        engine = HybridEngine(source="en", target="id")
        with mock.patch.object(engine.google, "translate_batch", return_value=["TOKO", "MAINKAN"]):
            res = engine.translate_batch(["STORE", "PLAY"])
            self.assertEqual(res, ["TOKO", "MAINKAN"])


if __name__ == "__main__":
    unittest.main()
