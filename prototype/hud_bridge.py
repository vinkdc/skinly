import base64
import binascii
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


BRIDGE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ValorantSkinTrackerBridge"
STATUS_PATH = BRIDGE_DIR / "status.json"
FRAME_PATH = BRIDGE_DIR / "frame.txt"
FRAME_META_PATH = BRIDGE_DIR / "frame.json"
STATUS_MAX_AGE_SECONDS = 5


@dataclass
class BridgeStatus:
    running: bool
    focused: bool
    width: int
    height: int
    session_id: str | None


@dataclass
class BridgeFrame:
    sequence: int
    image: Image.Image


def read_status(now=None):
    try:
        with STATUS_PATH.open(encoding="utf-8") as file:
            value = json.load(file)
        age = (time.time() if now is None else now) - float(value["updated_at"])
        if age > STATUS_MAX_AGE_SECONDS or age < 0:
            return None
        return BridgeStatus(
            running=bool(value["running"]),
            focused=bool(value["focused"]),
            width=int(value["width"]),
            height=int(value["height"]),
            session_id=value.get("session_id"),
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def read_frame(after_sequence=None):
    try:
        with FRAME_META_PATH.open(encoding="utf-8") as file:
            metadata = json.load(file)
        sequence = int(metadata["sequence"])
        if sequence == after_sequence:
            return None
        encoded = FRAME_PATH.read_text(encoding="ascii")
        with FRAME_META_PATH.open(encoding="utf-8") as file:
            latest_metadata = json.load(file)
        if latest_metadata != metadata:
            return None
        raw = base64.b64decode(encoded, validate=True)
        width = int(metadata["width"])
        height = int(metadata["height"])
        if width <= 0 or height <= 0 or len(raw) != width * height:
            return None
        return BridgeFrame(
            sequence=sequence,
            image=Image.frombytes("L", (width, height), raw).convert("RGB"),
        )
    except (
        OSError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        binascii.Error,
    ):
        return None
