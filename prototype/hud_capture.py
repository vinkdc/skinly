import ctypes
import sys
import time
from datetime import datetime
from pathlib import Path
from ctypes import wintypes

from PIL import ImageGrab


PROTOTYPE_DIR = Path(__file__).resolve().parent
TEST_IMAGES_DIR = PROTOTYPE_DIR / "test_images"
HOTKEY_ID = 1
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_F8 = 0x77
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
PM_REMOVE = 0x0001
TH32CS_SNAPPROCESS = 0x00000002
VALORANT_PROCESS_NAME = "VALORANT-Win64-Shipping.exe"


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class CaptureError(Exception):
    pass


def load_user32():
    if sys.platform != "win32":
        raise CaptureError("VALORANT window capture runs on Windows only.")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.RECT),
    ]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.RegisterHotKey.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    return user32


def load_kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def find_valorant_pid(kernel32):
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if snapshot in (None, invalid_handle):
        raise CaptureError("Could not enumerate running processes.")

    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while has_entry:
            if entry.szExeFile.casefold() == VALORANT_PROCESS_NAME.casefold():
                return entry.th32ProcessID
            has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return None


def _window_process_id(user32, hwnd):
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    return process_id.value


def window_is_for_process(user32, hwnd, process_id):
    if (
        not hwnd
        or not user32.IsWindow(hwnd)
        or not user32.IsWindowVisible(hwnd)
        or _window_process_id(user32, hwnd) != process_id
    ):
        return False
    client_rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(client_rect)):
        return False
    return client_rect.right > client_rect.left and client_rect.bottom > client_rect.top


def find_game_window(user32, process_id):
    candidates = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    def inspect_window(hwnd, _parameter):
        if (
            not user32.IsWindowVisible(hwnd)
            or user32.IsIconic(hwnd)
            or _window_process_id(user32, hwnd) != process_id
        ):
            return True

        client_rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(client_rect)):
            return True
        width = client_rect.right - client_rect.left
        height = client_rect.bottom - client_rect.top
        if width > 0 and height > 0:
            candidates.append((width * height, int(hwnd), width, height))
        return True

    callback = callback_type(inspect_window)
    if not user32.EnumWindows(callback, 0):
        raise CaptureError("Could not enumerate top-level game windows.")
    if not candidates:
        return None
    _, hwnd, width, height = max(candidates)
    return hwnd, width, height


def foreground_is_process(user32, process_id):
    hwnd = user32.GetForegroundWindow()
    return bool(hwnd) and _window_process_id(user32, hwnd) == process_id


def capture_game_window(hwnd):
    try:
        image = ImageGrab.grab(window=int(hwnd)).convert("RGB")
    except TypeError as error:
        raise CaptureError(
            "Window capture requires Pillow 11.2.1 or newer."
        ) from error
    except OSError as error:
        raise CaptureError("Windows could not capture the VALORANT window.") from error
    if image.width == 0 or image.height == 0:
        raise CaptureError("VALORANT window capture returned an empty image.")
    return image


def save_capture(image, output_dir=TEST_IMAGES_DIR):
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_path = output_dir / f"valorant_{timestamp}.png"
    image.save(output_path, format="PNG")
    return output_path


def capture_valorant(user32, kernel32):
    process_id = find_valorant_pid(kernel32)
    if process_id is None:
        raise CaptureError("VALORANT is not running.")
    window = find_game_window(user32, process_id)
    if window is None:
        raise CaptureError("Could not find a visible VALORANT game window.")
    hwnd, _, _ = window
    try:
        return save_capture(capture_game_window(hwnd))
    except OSError as error:
        raise CaptureError("Could not save the screenshot in prototype/test_images.") from error


def run():
    user32 = load_user32()
    kernel32 = load_kernel32()
    hotkey_modifiers = MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT
    if not user32.RegisterHotKey(None, HOTKEY_ID, hotkey_modifiers, VK_F8):
        raise CaptureError(
            "Could not register Ctrl+Shift+F8; another application may already use it."
        )

    print("Ready: focus VALORANT, then press Ctrl+Shift+F8 to save a screenshot.")
    print("Press Ctrl+C here to stop.")
    message = wintypes.MSG()
    try:
        while True:
            if user32.PeekMessageW(
                ctypes.byref(message), None, 0, 0, PM_REMOVE
            ):
                if message.message == WM_QUIT:
                    break
                if message.message == WM_HOTKEY and message.wParam == HOTKEY_ID:
                    try:
                        saved_path = capture_valorant(user32, kernel32)
                        print(f"Saved: {saved_path}")
                    except CaptureError as error:
                        print(f"Capture failed: {error}")
            else:
                time.sleep(0.1)
    finally:
        user32.UnregisterHotKey(None, HOTKEY_ID)


def main():
    try:
        run()
    except KeyboardInterrupt:
        print("\nStopped.")
    except CaptureError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
