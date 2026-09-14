import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import pytesseract
from PIL import Image, ImageDraw, ImageEnhance, ImageOps
from rapidfuzz import fuzz

from skin_catalog import CatalogError, KNOWN_WEAPONS, load_catalog


PROTOTYPE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PROTOTYPE_DIR / "hud_config.json"
DEBUG_DIR = PROTOTYPE_DIR / "debug"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


class PrototypeError(Exception):
    pass


def load_json(path):
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise PrototypeError(f"Could not read {path.name}.") from error


def load_config():
    config = load_json(CONFIG_PATH)
    try:
        coordinates = [
            float(config[key])
            for key in ("x_start", "y_start", "x_end", "y_end")
        ]
        minimum_score = float(config["minimum_match_score"])
        minimum_margin = float(config["minimum_match_margin"])
        scale = int(config["upscale_factor"])
        page_segmentation_mode = int(config.get("tesseract_psm", 6))
    except (KeyError, TypeError, ValueError) as error:
        raise PrototypeError("HUD config has missing or invalid values.") from error

    x_start, y_start, x_end, y_end = coordinates
    if not (0 <= x_start < x_end <= 1 and 0 <= y_start < y_end <= 1):
        raise PrototypeError("HUD ROI coordinates must be normalized from 0 to 1.")
    if not 0 <= minimum_score <= 100:
        raise PrototypeError("minimum_match_score must be between 0 and 100.")
    if not 0 <= minimum_margin <= 100:
        raise PrototypeError("minimum_match_margin must be between 0 and 100.")
    if scale not in (2, 3, 4):
        raise PrototypeError("upscale_factor must be 2, 3, or 4.")

    config["tesseract_psm"] = page_segmentation_mode
    return config


def configure_tesseract():
    executable = shutil.which("tesseract")
    if not executable:
        standard_path = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        if standard_path.is_file():
            executable = str(standard_path)
    if not executable:
        raise PrototypeError(
            "Tesseract was not found. Install it or add its folder to PATH."
        )
    pytesseract.pytesseract.tesseract_cmd = executable


def crop_roi(image, config):
    width, height = image.size
    left = round(width * config["x_start"])
    top = round(height * config["y_start"])
    right = round(width * config["x_end"])
    bottom = round(height * config["y_end"])
    return image.crop((left, top, right, bottom)), (left, top, right, bottom)


def preprocess(cropped_image, config):
    gray = ImageOps.grayscale(cropped_image)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(1.5)
    scale = config["upscale_factor"]
    return gray.resize(
        (gray.width * scale, gray.height * scale), Image.Resampling.LANCZOS
    )


def normalize_text(text):
    tokens = re.findall(r"[a-z0-9]+", text.casefold())
    return " ".join(token for token in tokens if len(token) > 1)


def detect_weapon(raw_text):
    tokens = set(normalize_text(raw_text).split())
    for weapon in KNOWN_WEAPONS:
        if weapon.casefold() in tokens:
            return weapon
    return None


def match_skin_name(raw_text, catalog, minimum_score, minimum_margin):
    query = normalize_text(raw_text)
    if not query:
        return "UNKNOWN", 0.0

    detected_weapon = detect_weapon(raw_text)
    candidates = catalog
    if detected_weapon is not None:
        candidates = [
            entry for entry in catalog if entry["weapon"] == detected_weapon
        ]
    scores = sorted(
        (
            (fuzz.token_sort_ratio(query, normalize_text(entry["name"])), entry["name"])
            for entry in candidates
        ),
        reverse=True,
    )
    if not scores:
        return "UNKNOWN", 0.0

    best_score, best_name = scores[0]
    second_best_score = scores[1][0] if len(scores) > 1 else 0.0
    if best_score < minimum_score or best_score - second_best_score < minimum_margin:
        return "UNKNOWN", best_score
    return best_name, best_score


def recognize_hud_crop(cropped, config, catalog):
    processed = preprocess(cropped, config)
    try:
        raw_text = pytesseract.image_to_string(
            processed, lang="eng", config=f"--psm {config['tesseract_psm']}"
        )
    except pytesseract.TesseractError as error:
        raise PrototypeError(
            "Tesseract OCR failed; check its English language data."
        ) from error

    raw_text = " ".join(raw_text.split())
    match, score = match_skin_name(
        raw_text,
        catalog,
        config["minimum_match_score"],
        config["minimum_match_margin"],
    )
    return raw_text, match, score, processed


def save_debug_images(image_path, original, roi_box, cropped, processed, folder_mode):
    output_dir = DEBUG_DIR
    if folder_mode:
        output_dir = DEBUG_DIR / image_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    marked_image = original.copy()
    draw = ImageDraw.Draw(marked_image)
    draw.rectangle(roi_box, outline=(255, 0, 0), width=max(2, round(min(original.size) / 400)))
    marked_image.save(output_dir / "screenshot_with_roi.png")
    cropped.save(output_dir / "hud_crop.png")
    processed.save(output_dir / "hud_preprocessed.png")


def read_image(image_path, config, catalog, debug=False, folder_mode=False):
    try:
        with Image.open(image_path) as image_file:
            original = image_file.convert("RGB")
    except OSError as error:
        raise PrototypeError(f"Could not open image: {image_path.name}.") from error

    cropped, roi_box = crop_roi(original, config)
    raw_text, match, score, processed = recognize_hud_crop(
        cropped, config, catalog
    )
    if debug:
        save_debug_images(
            image_path, original, roi_box, cropped, processed, folder_mode
        )
    return {"path": image_path, "raw_text": raw_text, "match": match, "score": score}


def input_images(path):
    if path.is_file():
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise PrototypeError(f"Unsupported image type: {path.suffix}.")
        return [path], False
    if path.is_dir():
        images = sorted(
            item
            for item in path.iterdir()
            if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS
        )
        if not images:
            raise PrototypeError(f"No supported image files found in {path}.")
        return images, True
    raise PrototypeError(f"Input does not exist: {path}.")


def shorten(value, width):
    if len(value) <= width:
        return value
    return value[: width - 3] + "..."


def print_single(result):
    print(f"Raw OCR: {result['raw_text']}")
    print(f"Matched: {result['match']}")
    print(f"Score: {round(result['score'])}")


def print_folder(results):
    print(f"{'file':<24} {'OCR':<32} {'match':<28} {'score':>5}")
    for result in results:
        print(
            f"{shorten(result['path'].name, 24):<24} "
            f"{shorten(result['raw_text'], 32):<32} "
            f"{shorten(result['match'], 28):<28} "
            f"{round(result['score']):>5}"
        )
    matched = sum(result["match"] != "UNKNOWN" for result in results)
    print(f"\nProcessed: {len(results)}")
    print(f"Matched: {matched}")
    print(f"Unknown: {len(results) - matched}")


def main():
    parser = argparse.ArgumentParser(description="Read VALORANT weapon names from screenshots.")
    parser.add_argument("input", type=Path, help="A screenshot file or folder of screenshots")
    parser.add_argument("--debug", action="store_true", help="Save ROI and preprocessing images")
    args = parser.parse_args()

    try:
        config = load_config()
        catalog = load_catalog()
        configure_tesseract()
        images, folder_mode = input_images(args.input)
        results = [
            read_image(image, config, catalog, args.debug, folder_mode)
            for image in images
        ]
    except (CatalogError, PrototypeError) as error:
        parser.error(str(error))

    if folder_mode:
        print_folder(results)
    else:
        print_single(results[0])
    if args.debug:
        print(f"Debug images: {DEBUG_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
