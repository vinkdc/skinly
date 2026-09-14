import json
import os
import urllib.error
import urllib.request
from pathlib import Path


PROTOTYPE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = PROTOTYPE_DIR / "data" / "skin_catalog.json"
HENRIK_CONTENT_URL = "https://api.henrikdev.xyz/valorant/v1/content?locale=en-US"
KNOWN_WEAPONS = (
    "Vandal",
    "Phantom",
    "Operator",
    "Guardian",
    "Bulldog",
    "Marshal",
    "Sheriff",
    "Ghost",
    "Classic",
    "Frenzy",
    "Shorty",
    "Spectre",
    "Stinger",
    "Judge",
    "Bucky",
    "Odin",
    "Ares",
    "Outlaw",
    "Bandit",
)


class CatalogError(Exception):
    pass


def weapon_from_name(name):
    normalized_name = name.strip().casefold()
    for weapon in KNOWN_WEAPONS:
        normalized_weapon = weapon.casefold()
        if normalized_name == normalized_weapon or normalized_name.endswith(
            f" {normalized_weapon}"
        ):
            return weapon
    return None


def extract_catalog(content):
    try:
        skins = content["data"]["skins"]
    except (KeyError, TypeError) as error:
        raise CatalogError("Henrik response does not contain data.skins.") from error
    if not isinstance(skins, list):
        raise CatalogError("Henrik data.skins is not a list.")

    catalog = []
    for skin in skins:
        if not isinstance(skin, dict):
            raise CatalogError("Henrik data.skins contains an invalid entry.")
        skin_id = skin.get("id")
        name = skin.get("name")
        if not isinstance(skin_id, str) or not isinstance(name, str) or not name.strip():
            raise CatalogError("Henrik data.skins contains a skin without an id or name.")
        catalog.append(
            {"id": skin_id, "name": name.strip(), "weapon": weapon_from_name(name)}
        )
    return catalog


def save_catalog(catalog, path=CATALOG_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    try:
        temporary_path.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise CatalogError(f"Could not save skin catalog to {path}.") from error


def load_catalog(path=CATALOG_PATH):
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CatalogError(
            "Skin catalog is missing. Run: python prototype/update_catalog.py"
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogError(f"Could not read skin catalog from {path}.") from error

    if not isinstance(catalog, list) or not catalog:
        raise CatalogError("Skin catalog must contain a non-empty list.")
    for entry in catalog:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("id"), str)
            or not isinstance(entry.get("name"), str)
            or entry.get("weapon") not in (*KNOWN_WEAPONS, None)
        ):
            raise CatalogError("Skin catalog contains an invalid entry.")
    return catalog


def fetch_catalog():
    api_key = os.environ.get("HENRIK_API_KEY")
    if not api_key:
        raise CatalogError("Set HENRIK_API_KEY before refreshing the catalog.")

    request = urllib.request.Request(
        HENRIK_CONTENT_URL,
        headers={"Authorization": api_key, "User-Agent": "valorant-skin-tracker-prototype"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise CatalogError("Could not fetch the Henrik content catalog.") from error
    return extract_catalog(content)
