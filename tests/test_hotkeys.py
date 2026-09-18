# Unit test for custom Google Lens hotkeys (Peek Original & Freeze Translation)
# Callers: unittest discover
# Affected API: PEEK_ORIGINAL_HOTKEY, FREEZE_TRANSLATION_HOTKEY in src.config
# User instruction: "peakkkkkkk original dan resueme translate itu ada hot key nya ga?? di uiux buatt custom?"
import unittest
from src.config import (
    SETTINGS_TOPMOST_HOTKEY,
    TEMPORARY_REGION_HOTKEY,
    PEEK_ORIGINAL_HOTKEY,
    FREEZE_TRANSLATION_HOTKEY,
)


class HotkeyConfigTests(unittest.TestCase):
    def test_default_hotkey_definitions(self):
        self.assertEqual(PEEK_ORIGINAL_HOTKEY, "<ctrl>+<shift>+p")
        self.assertEqual(FREEZE_TRANSLATION_HOTKEY, "<ctrl>+<shift>+f")
        self.assertIn("<ctrl>", PEEK_ORIGINAL_HOTKEY)
        self.assertIn("<ctrl>", FREEZE_TRANSLATION_HOTKEY)

    def test_all_hotkeys_are_distinct(self):
        hotkeys = [
            SETTINGS_TOPMOST_HOTKEY,
            TEMPORARY_REGION_HOTKEY,
            PEEK_ORIGINAL_HOTKEY,
            FREEZE_TRANSLATION_HOTKEY,
        ]
        # No two shortcuts collide by default
        self.assertEqual(len(hotkeys), len(set(hotkeys)))


if __name__ == "__main__":
    unittest.main()
