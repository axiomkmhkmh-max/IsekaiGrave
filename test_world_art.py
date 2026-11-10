import unittest
from io import BytesIO

from PIL import Image

from world_art import render_world_art


class WorldArtTests(unittest.TestCase):
    def test_each_major_section_renders_valid_png(self):
        for kind in ("world", "boss", "npc", "region", "chronicle", "news", "character", "market", "guild", "quest"):
            with self.subTest(kind=kind):
                payload = render_world_art(kind, "جهان ایسکا", "یک جهان مشترک", ["سطح: ۱۰"])
                self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))
                image = Image.open(BytesIO(payload))
                self.assertEqual(image.size, (1200, 720))
                self.assertEqual(image.format, "PNG")

    def test_unknown_theme_falls_back_safely(self):
        payload = render_world_art("unknown", "عنوان")
        self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
