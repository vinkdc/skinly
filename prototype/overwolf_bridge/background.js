(() => {
  "use strict";

  const VALORANT_CLASS_ID = 21640;
  const BRIDGE_ROOT = `${overwolf.io.paths.localAppData}/ValorantSkinTrackerBridge`;
  const STATUS_PATH = `${BRIDGE_ROOT}/status.json`;
  const FRAME_PATH = `${BRIDGE_ROOT}/frame.txt`;
  const FRAME_META_PATH = `${BRIDGE_ROOT}/frame.json`;

  let config;
  let currentGame = null;
  let screenshotBuffer = null;
  let captureGeneration = 0;
  let sequence = 0;

  function writeText(path, value) {
    return new Promise((resolve, reject) => {
      overwolf.io.writeFileContents(
        path,
        value,
        overwolf.io.enums.eEncoding.UTF8,
        false,
        (result) => result.success ? resolve() : reject(new Error(result.error || "File write failed")),
      );
    });
  }

  function isValorant(info) {
    const classId = Number(info?.classId ?? Math.floor(Number(info?.id) / 10));
    return info?.isRunning === true && classId === VALORANT_CLASS_ID;
  }

  function statusValue() {
    const game = currentGame;
    return {
      running: Boolean(game),
      focused: Boolean(game?.focused),
      width: game?.width || 0,
      height: game?.height || 0,
      session_id: game?.sessionId || null,
      updated_at: Date.now() / 1000,
    };
  }

  function publishStatus() {
    writeText(STATUS_PATH, JSON.stringify(statusValue())).catch((error) => {
      console.error("Could not publish tracker bridge status:", error.message);
    });
  }

  function stopCapture() {
    captureGeneration += 1;
    if (screenshotBuffer) {
      screenshotBuffer.close();
      screenshotBuffer = null;
    }
  }

  function frameToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const chunkSize = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
    }
    return btoa(binary);
  }

  async function publishFrame(frame) {
    const nextSequence = sequence + 1;
    await writeText(FRAME_PATH, frameToBase64(frame.buffer));
    await writeText(FRAME_META_PATH, JSON.stringify({
      sequence: nextSequence,
      width: frame.width,
      height: frame.height,
      timestamp: new Date().toISOString(),
    }));
    sequence = nextSequence;
  }

  function grab(generation) {
    if (generation !== captureGeneration || !screenshotBuffer || !currentGame?.focused) {
      return;
    }
    screenshotBuffer.capture(async (frame) => {
      if (generation !== captureGeneration) return;
      if (!frame.success) {
        console.warn("Overwolf could not capture a VALORANT frame:", frame.error || frame.status);
        stopCapture();
        window.setTimeout(startCapture, 1000);
        return;
      }
      try {
        await publishFrame(frame);
      } catch (error) {
        console.error("Could not publish tracker bridge frame:", error.message);
      }
      if (generation === captureGeneration) {
        window.setTimeout(() => grab(generation), config.check_interval_ms);
      }
    });
  }

  function startCapture() {
    if (!currentGame?.focused || screenshotBuffer) return;
    const { width, height } = currentGame;
    const x = Math.round(width * config.x_start);
    const y = Math.round(height * config.y_start);
    const right = Math.round(width * config.x_end);
    const bottom = Math.round(height * config.y_end);
    if (right <= x || bottom <= y) return;

    const generation = ++captureGeneration;
    overwolf.media.createScreenshotBuffer({
      format: "gray8",
      crop: { x, y, width: right - x, height: bottom - y },
      roundAwayFromZero: true,
    }, (result) => {
      if (generation !== captureGeneration || !currentGame?.focused) {
        if (result.success) result.screenshotBuffer.close();
        return;
      }
      if (!result.success) {
        console.warn("Overwolf capture is not ready:", result.error || result.status);
        window.setTimeout(startCapture, 1000);
        return;
      }
      screenshotBuffer = result.screenshotBuffer;
      grab(generation);
    });
  }

  function updateGame(info) {
    const nextGame = isValorant(info) ? {
      focused: info.gameIsInFocus === true,
      width: Number(info.width) || 0,
      height: Number(info.height) || 0,
      sessionId: info.sessionId || String(info.processId || ""),
    } : null;

    const changed = JSON.stringify(currentGame) !== JSON.stringify(nextGame);
    if (!changed) return;
    const previousSession = currentGame?.sessionId;
    const previousDimensions = `${currentGame?.width}x${currentGame?.height}`;
    currentGame = nextGame;

    if (
      !currentGame?.focused ||
      currentGame.sessionId !== previousSession ||
      `${currentGame.width}x${currentGame.height}` !== previousDimensions
    ) {
      stopCapture();
    }
    publishStatus();
    startCapture();
  }

  function handleGameInfoUpdated(event) {
    updateGame(event?.gameInfo || null);
  }

  async function initialize() {
    const response = await fetch("../hud_config.json");
    if (!response.ok) throw new Error("Could not load prototype/hud_config.json");
    config = await response.json();
    overwolf.games.onGameInfoUpdated.addListener(handleGameInfoUpdated);
    overwolf.games.getRunningGameInfo2((result) => {
      updateGame(result.success ? result.gameInfo : null);
    });
    window.setInterval(publishStatus, 1000);
  }

  initialize().catch((error) => {
    console.error("VALORANT tracker bridge failed to start:", error.message);
  });
})();
