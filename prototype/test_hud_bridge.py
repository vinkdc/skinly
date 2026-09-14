import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hud_bridge import read_frame, read_status


class HudBridgeTests(unittest.TestCase):
    def test_reads_fresh_overwolf_status_and_rejects_stale_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status_path = Path(temp_dir) / "status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "running": True,
                        "focused": False,
                        "width": 1920,
                        "height": 1080,
                        "session_id": "game-session",
                        "updated_at": 100,
                    }
                ),
                encoding="utf-8",
            )
            with patch("hud_bridge.STATUS_PATH", status_path):
                status = read_status(now=104)
                stale_status = read_status(now=106)

        self.assertTrue(status.running)
        self.assertFalse(status.focused)
        self.assertEqual(status.session_id, "game-session")
        self.assertIsNone(stale_status)

    def test_reads_latest_grayscale_roi_frame_and_skips_seen_sequence(self):
        pixels = bytes([0, 64, 128, 255, 20, 40])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata_path = root / "frame.json"
            frame_path = root / "frame.txt"
            metadata_path.write_text(
                json.dumps(
                    {
                        "sequence": 7,
                        "width": 3,
                        "height": 2,
                        "timestamp": "2026-09-14T00:00:00.000Z",
                    }
                ),
                encoding="utf-8",
            )
            frame_path.write_text(base64.b64encode(pixels).decode("ascii"), encoding="ascii")
            with (
                patch("hud_bridge.FRAME_META_PATH", metadata_path),
                patch("hud_bridge.FRAME_PATH", frame_path),
            ):
                frame = read_frame()
                already_seen = read_frame(after_sequence=7)

        self.assertEqual(frame.sequence, 7)
        self.assertEqual(frame.image.size, (3, 2))
        self.assertEqual(frame.image.getpixel((1, 0)), (64, 64, 64))
        self.assertIsNone(already_seen)


if __name__ == "__main__":
    unittest.main()
