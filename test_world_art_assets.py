import unittest
from io import BytesIO

from PIL import Image

from world_art import ART_ASSET_MAP, _load_prebuilt_art


class BundledArtworkTests(unittest.TestCase):
    def test_all_mapped_assets_exist_and_are_valid_images(self):
        for kind, filename in ART_ASSET_MAP.items():
            with self.subTest(kind=kind, filename=filename):
                payload = _load_prebuilt_art(kind)
                self.assertIsNotNone(payload)
                with Image.open(BytesIO(payload)) as image:
                    self.assertIn(image.format, {"JPEG", "PNG", "WEBP"})
                    self.assertGreaterEqual(image.width, 1000)
                    self.assertGreaterEqual(image.height, 600)

    def test_unknown_kind_uses_world_asset(self):
        self.assertEqual(_load_prebuilt_art("not-a-real-kind"), _load_prebuilt_art("world"))


if __name__ == "__main__":
    unittest.main()
