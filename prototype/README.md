# Local VALORANT loadout prototype

Install the Python dependencies with `python -m pip install -r prototype/requirements.txt`.

With Riot Client signed in, run from the repository root:

```powershell
python prototype\tracker.py
```

The local loadout tracker uses only the Python standard library. It reads the local Riot Client lockfile, retrieves the current account session and equipped loadout, then resolves weapon and skin names from Valorant-API.com. The lockfile credential is used only for read-only requests to `127.0.0.1`; the PVP loadout request is scoped to the PUUID returned by that local session. No data is saved. A network connection is needed for the loadout and metadata requests.

## Capture screenshots for HUD OCR

On Windows, run:

```powershell
python prototype\hud_capture.py
```

Leave this terminal running, focus VALORANT, then press **Ctrl+Shift+F8** to capture the game window to `prototype/test_images/`. Press Ctrl+C in the terminal to stop. The script locates the visible game window by the `VALORANT-Win64-Shipping.exe` process and captures that HWND only; it does not fall back to desktop or monitor capture. Pillow 11.2.1 or newer is required for window-only capture.

## Live skin tracking

Refresh the local skin catalog explicitly after setting `HENRIK_API_KEY`:

```powershell
python prototype\update_catalog.py
```

The refresh stores only Henrik `data.skins` IDs, names, and safely detected weapon suffixes in `prototype/data/skin_catalog.json`. Normal tracking reads this cache and does not contact Henrik.

The live tracker now receives captured frames from a background Overwolf app. Overwolf uses its supported game capture integration; this prototype does not create an in-game window. Overwolf must be installed and the account must be enabled for unpacked app development.

Load the app from the `prototype` folder:

1. In Overwolf, open **Settings → About → Development Options** (or **Packages → Development Options**).
2. Choose **Load unpacked extension** and select this repository's `prototype` folder.
3. Start VALORANT; the capture app starts for game ID 21640.

Run the tracker while VALORANT is open:

```powershell
python prototype\hud_live.py
```

Overwolf writes the newest grayscale Weapon Switcher ROI and sequence metadata under `%LOCALAPPDATA%\ValorantSkinTrackerBridge`; no full screenshots are retained. The app crops the normalized ROI from `prototype/hud_config.json` before publishing each frame. Alt-Tab pauses capture and OCR; returning resumes with a fresh difference baseline. The tracker waits if Overwolf is closed or its status becomes stale. Add `--debug` to show HUD-change and OCR details. Press Ctrl+C to stop and print the in-memory usage summary. Live thresholds are in `prototype/hud_config.json`.
