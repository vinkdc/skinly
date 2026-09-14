import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skin_catalog import (
    HENRIK_CONTENT_URL,
    extract_catalog,
    fetch_catalog,
    load_catalog,
    save_catalog,
    weapon_from_name,
)


class SkinCatalogTests(unittest.TestCase):
    def test_extracts_only_skin_fields_and_assigns_known_weapon(self):
        content = {
            "data": {
                "skins": [
                    {
                        "id": "skin-1",
                        "name": "Recon Phantom",
                        "assetName": "ignored",
                    },
                    {"id": "skin-2", "name": "Example Blade"},
                ],
                "chromas": [{"id": "chroma-1", "name": "Ignored"}],
                "skinLevels": [{"id": "level-1", "name": "Ignored"}],
            }
        }

        catalog = extract_catalog(content)

        self.assertEqual(
            catalog,
            [
                {"id": "skin-1", "name": "Recon Phantom", "weapon": "Phantom"},
                {"id": "skin-2", "name": "Example Blade", "weapon": None},
            ],
        )

    def test_weapon_suffix_is_required(self):
        self.assertEqual(weapon_from_name("Champions 2025 Vandal"), "Vandal")
        self.assertIsNone(weapon_from_name("Vandal Champions 2025"))
        self.assertIsNone(weapon_from_name("Example Knife"))

    def test_saved_catalog_loads_offline(self):
        catalog = [{"id": "skin-1", "name": "Recon Phantom", "weapon": "Phantom"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "skin_catalog.json"

            save_catalog(catalog, path)
            loaded = load_catalog(path)

        self.assertEqual(loaded, catalog)

    def test_fetch_uses_environment_key_and_content_endpoint(self):
        response = io.BytesIO(
            json.dumps(
                {"data": {"skins": [{"id": "skin-1", "name": "Recon Phantom"}]}}
            ).encode("utf-8")
        )
        with patch.dict("os.environ", {"HENRIK_API_KEY": "test-key"}, clear=True):
            with patch("skin_catalog.urllib.request.urlopen", return_value=response) as open_url:
                catalog = fetch_catalog()

        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, HENRIK_CONTENT_URL)
        self.assertEqual(request.get_header("Authorization"), "test-key")
        self.assertEqual(catalog[0]["name"], "Recon Phantom")


if __name__ == "__main__":
    unittest.main()
