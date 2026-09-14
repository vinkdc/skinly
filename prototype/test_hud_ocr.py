import unittest

from PIL import Image

from hud_ocr import crop_roi, detect_weapon, match_skin_name, preprocess


def catalog_entry(name, weapon):
    return {"id": name, "name": name, "weapon": weapon}


class HudOcrTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "x_start": 0.5,
            "y_start": 0.25,
            "x_end": 1.0,
            "y_end": 0.75,
            "upscale_factor": 3,
        }

    def test_crop_uses_normalized_coordinates(self):
        image = Image.new("RGB", (200, 100))

        crop, box = crop_roi(image, self.config)

        self.assertEqual(box, (100, 25, 200, 75))
        self.assertEqual(crop.size, (100, 50))

    def test_preprocess_grayscales_and_upscales(self):
        image = Image.new("RGB", (10, 8), "white")

        processed = preprocess(image, self.config)

        self.assertEqual(processed.mode, "L")
        self.assertEqual(processed.size, (30, 24))

    def test_fuzzy_matches_common_ocr_confusions(self):
        catalog = [
            catalog_entry("Champions 2025 Vandal", "Vandal"),
            catalog_entry("Champions 2023 Vandal", "Vandal"),
            catalog_entry("Recon Phantom", "Phantom"),
        ]

        match, score = match_skin_name(
            "VANDAL NWQHAMPIONS 2025", catalog, 82, 4
        )

        self.assertEqual(match, "Champions 2025 Vandal")
        self.assertGreaterEqual(score, 82)

    def test_recon_phantom_matches_correctly(self):
        catalog = [
            catalog_entry("Recon Phantom", "Phantom"),
            catalog_entry("Recon Vandal", "Vandal"),
        ]

        match, score = match_skin_name("Rec0n Phantom", catalog, 82, 5)

        self.assertEqual(match, "Recon Phantom")
        self.assertGreaterEqual(score, 82)

    def test_detects_clear_weapon_name(self):
        self.assertEqual(detect_weapon("Rec0n Phantom"), "Phantom")
        self.assertIsNone(detect_weapon("Rec0n Phant0m"))

    def test_ambiguous_top_candidates_return_unknown(self):
        catalog = [
            catalog_entry("Recon Phantom", "Phantom"),
            catalog_entry("Recon Phantom", "Phantom"),
        ]

        match, score = match_skin_name("Recon Phantom", catalog, 82, 5)

        self.assertEqual(match, "UNKNOWN")
        self.assertEqual(score, 100)

    def test_unlisted_skin_does_not_match_base_weapon_confidently(self):
        catalog = [
            catalog_entry("Champions 2025 Vandal", "Vandal"),
            catalog_entry("Standard Vandal", "Vandal"),
        ]

        match, _ = match_skin_name("Reaver Vandal", catalog, 82, 5)

        self.assertEqual(match, "UNKNOWN")

    def test_low_similarity_returns_unknown(self):
        catalog = [catalog_entry("Champions Vandal", "Vandal")]
        match, score = match_skin_name("???", catalog, 82, 5)

        self.assertEqual(match, "UNKNOWN")
        self.assertEqual(score, 0)


if __name__ == "__main__":
    unittest.main()
