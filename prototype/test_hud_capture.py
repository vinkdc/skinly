import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from hud_capture import (
    CaptureError,
    capture_game_window,
    capture_valorant,
    find_game_window,
    find_valorant_pid,
    foreground_is_process,
    save_capture,
    window_is_for_process,
)


class FakeKernel32:
    def __init__(self, processes):
        self.processes = processes
        self.index = 0

    def CreateToolhelp32Snapshot(self, _flags, _process_id):
        return 55

    def Process32FirstW(self, _snapshot, entry_pointer):
        self.index = 0
        return self._write_entry(entry_pointer)

    def Process32NextW(self, _snapshot, entry_pointer):
        self.index += 1
        return self._write_entry(entry_pointer)

    def _write_entry(self, entry_pointer):
        if self.index >= len(self.processes):
            return False
        process_id, name = self.processes[self.index]
        entry = entry_pointer._obj
        entry.th32ProcessID = process_id
        entry.szExeFile = name
        return True

    def CloseHandle(self, _handle):
        return True


class FakeUser32:
    def __init__(self, windows, foreground=0):
        self.windows = windows
        self.foreground = foreground

    def EnumWindows(self, callback, _parameter):
        for window in self.windows:
            if callback(window["hwnd"], 0) is False:
                break
        return True

    def IsWindow(self, hwnd):
        return any(w["hwnd"] == hwnd and w.get("valid", True) for w in self.windows)

    def IsWindowVisible(self, hwnd):
        return self._window(hwnd).get("visible", True)

    def IsIconic(self, hwnd):
        return self._window(hwnd).get("minimized", False)

    def GetWindowThreadProcessId(self, hwnd, process_id_pointer):
        process_id_pointer._obj.value = self._window(hwnd)["process_id"]
        return 1

    def GetClientRect(self, hwnd, rect_pointer):
        left, top, right, bottom = self._window(hwnd)["rect"]
        rect = rect_pointer._obj
        rect.left, rect.top, rect.right, rect.bottom = left, top, right, bottom
        return True

    def GetForegroundWindow(self):
        return self.foreground

    def _window(self, hwnd):
        return next(window for window in self.windows if window["hwnd"] == hwnd)


class HudCaptureTests(unittest.TestCase):
    def test_finds_valorant_pid_by_executable_name(self):
        kernel32 = FakeKernel32(
            [
                (10, "RiotClientServices.exe"),
                (42, "valorant-win64-shipping.EXE"),
            ]
        )

        self.assertEqual(find_valorant_pid(kernel32), 42)

    def test_returns_none_when_game_process_is_not_running(self):
        kernel32 = FakeKernel32([(10, "RiotClientServices.exe")])

        self.assertIsNone(find_valorant_pid(kernel32))

    def test_selects_largest_visible_nonempty_window_for_game_pid(self):
        user32 = FakeUser32(
            [
                {"hwnd": 1, "process_id": 7, "rect": (0, 0, 1920, 1080)},
                {
                    "hwnd": 2,
                    "process_id": 42,
                    "rect": (0, 0, 800, 600),
                    "visible": False,
                },
                {"hwnd": 3, "process_id": 42, "rect": (0, 0, 0, 0)},
                {"hwnd": 4, "process_id": 42, "rect": (0, 0, 1280, 720)},
                {"hwnd": 5, "process_id": 42, "rect": (0, 0, 1920, 1080)},
            ]
        )

        self.assertEqual(find_game_window(user32, 42), (5, 1920, 1080))

    def test_window_association_and_foreground_are_pid_based(self):
        user32 = FakeUser32(
            [
                {"hwnd": 5, "process_id": 42, "rect": (0, 0, 1920, 1080)},
                {"hwnd": 6, "process_id": 77, "rect": (0, 0, 800, 600)},
            ],
            foreground=6,
        )

        self.assertTrue(window_is_for_process(user32, 5, 42))
        self.assertFalse(window_is_for_process(user32, 6, 42))
        self.assertFalse(foreground_is_process(user32, 42))
        user32.foreground = 5
        self.assertTrue(foreground_is_process(user32, 42))

    def test_invalid_or_hidden_window_is_not_kept_as_game_window(self):
        user32 = FakeUser32(
            [
                {"hwnd": 5, "process_id": 42, "rect": (0, 0, 1920, 1080)},
                {
                    "hwnd": 6,
                    "process_id": 42,
                    "rect": (0, 0, 1920, 1080),
                    "visible": False,
                },
            ]
        )

        self.assertFalse(window_is_for_process(user32, 99, 42))
        self.assertFalse(window_is_for_process(user32, 6, 42))

    def test_capture_targets_only_the_associated_hwnd(self):
        image = Image.new("RGB", (64, 48), "blue")
        with patch("hud_capture.ImageGrab.grab", return_value=image) as grab:
            captured = capture_game_window(1234)

        grab.assert_called_once_with(window=1234)
        self.assertEqual(captured.size, (64, 48))

    def test_capture_hotkey_uses_pid_window_capture_and_saves_png(self):
        user32 = FakeUser32(
            [{"hwnd": 1234, "process_id": 42, "rect": (0, 0, 64, 48)}]
        )
        kernel32 = FakeKernel32([(42, "VALORANT-Win64-Shipping.exe")])
        image = Image.new("RGB", (64, 48), "blue")
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "capture.png"
            with patch("hud_capture.ImageGrab.grab", return_value=image) as grab:
                with patch("hud_capture.save_capture", return_value=output_path):
                    saved_path = capture_valorant(user32, kernel32)

        grab.assert_called_once_with(window=1234)
        self.assertEqual(saved_path, output_path)

    def test_capture_hotkey_reports_game_not_running(self):
        with self.assertRaisesRegex(CaptureError, "VALORANT is not running"):
            capture_valorant(FakeUser32([]), FakeKernel32([]))

    def test_saves_timestamped_png_in_capture_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "test_images"
            image = Image.new("RGB", (16, 12), "red")

            saved_path = save_capture(image, output_dir)

            self.assertEqual(saved_path.parent, output_dir)
            self.assertTrue(saved_path.name.startswith("valorant_"))
            self.assertEqual(saved_path.suffix, ".png")
            with Image.open(saved_path) as saved_image:
                self.assertEqual(saved_image.size, (16, 12))
                self.assertEqual(saved_image.getpixel((0, 0)), (255, 0, 0))


if __name__ == "__main__":
    unittest.main()
