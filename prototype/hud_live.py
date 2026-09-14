import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime

from PIL import ImageChops, ImageOps, ImageStat

from hud_bridge import read_frame, read_status
from hud_ocr import (
    PrototypeError,
    configure_tesseract,
    load_config,
    normalize_text,
    recognize_hud_crop,
)
from skin_catalog import CatalogError, load_catalog


UNKNOWN = "UNKNOWN"


@dataclass
class SkinUsageSession:
    skin_name: str
    started_at: datetime
    ended_at: datetime | None = None

    @property
    def duration_seconds(self):
        end = self.ended_at or datetime.now()
        return max(0.0, (end - self.started_at).total_seconds())


class SkinState:
    def __init__(self, config):
        self.current_skin = None
        self.current_skin_started_at = None
        self.last_confirmed_at = None
        self.sessions = []
        self.pending_skin = None
        self.pending_count = 0
        self.pending_started_at = None
        self.confirmation_count = config["confirmation_count"]
        self.confirmation_window_seconds = config["confirmation_window_ms"] / 1000
        self.high_confidence_threshold = config["high_confidence_threshold"]

    def observe(self, skin_name, score, observed_at):
        if skin_name == UNKNOWN:
            return None

        specific_skin = len(normalize_text(skin_name).split()) > 1
        if specific_skin and score >= self.high_confidence_threshold:
            return self._confirm(skin_name, observed_at)

        pending_expired = (
            self.pending_started_at is not None
            and (observed_at - self.pending_started_at).total_seconds()
            > self.confirmation_window_seconds
        )
        if skin_name != self.pending_skin or pending_expired:
            self.pending_skin = skin_name
            self.pending_count = 1
            self.pending_started_at = observed_at
            return None

        self.pending_count += 1
        if self.pending_count < self.confirmation_count:
            return None
        return self._confirm(skin_name, observed_at)

    def _confirm(self, skin_name, observed_at):
        self.pending_skin = None
        self.pending_count = 0
        self.pending_started_at = None
        self.last_confirmed_at = observed_at
        if skin_name == self.current_skin:
            return None

        previous_skin = self.current_skin
        if self.sessions and self.sessions[-1].ended_at is None:
            self.sessions[-1].ended_at = observed_at
        self.current_skin = skin_name
        self.current_skin_started_at = observed_at
        self.sessions.append(SkinUsageSession(skin_name, observed_at))
        return previous_skin, skin_name, observed_at

    def close(self, ended_at):
        if self.sessions and self.sessions[-1].ended_at is None:
            self.sessions[-1].ended_at = ended_at

    def reset_for_game_restart(self, ended_at):
        self.close(ended_at)
        self.current_skin = None
        self.current_skin_started_at = None
        self.last_confirmed_at = None
        self.pending_skin = None
        self.pending_count = 0
        self.pending_started_at = None


def validate_live_config(config):
    try:
        for key in (
            "check_interval_ms",
            "stabilization_ms",
            "confirmation_delay_ms",
            "confirmation_window_ms",
        ):
            if int(config[key]) <= 0:
                raise ValueError
        if float(config["change_threshold"]) <= 0:
            raise ValueError
        if int(config["confirmation_count"]) < 2:
            raise ValueError
        if not 0 <= float(config["high_confidence_threshold"]) <= 100:
            raise ValueError
        if int(config["difference_width"]) <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError) as error:
        raise PrototypeError("HUD live-tracking config has missing or invalid values.") from error


def difference_sample(image, width):
    height = max(1, round(image.height * width / image.width))
    return ImageOps.grayscale(image).resize((width, height))


def mean_absolute_difference(first, second):
    difference = ImageChops.difference(first, second)
    return ImageStat.Stat(difference).mean[0]


def format_duration(seconds):
    total_seconds = max(0, round(seconds))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    return f"{minutes}m {seconds:02d}s"


def print_summary(state, checks, started_at, ocr_times):
    totals = {}
    for session in state.sessions:
        totals[session.skin_name] = totals.get(session.skin_name, 0) + session.duration_seconds

    print("\n=== Skin Usage ===")
    for skin_name, duration in totals.items():
        print(f"\n{skin_name}\n{format_duration(duration)}")
    print(f"\nTotal confirmed usage:\n{format_duration(sum(totals.values()))}")

    elapsed = max(time.perf_counter() - started_at, 0.001)
    average_ocr_ms = 1000 * sum(ocr_times) / len(ocr_times) if ocr_times else 0
    print(f"\nCapture/check frequency: {checks / elapsed:.1f} Hz")
    print(f"OCR calls: {len(ocr_times)}")
    print(f"Average OCR time: {average_ocr_ms:.0f} ms")


def perform_ocr(crop, config, catalog, debug, ocr_times):
    started = time.perf_counter()
    raw_text, match, score, _ = recognize_hud_crop(crop, config, catalog)
    ocr_times.append(time.perf_counter() - started)
    if debug:
        print(f"OCR raw: {raw_text}")
        print(f"Match: {match}")
        print(f"Score: {round(score)}")
    return match, score


def report_transition(event, debug):
    previous_skin, skin_name, observed_at = event
    print(f"[{observed_at:%H:%M:%S}] {skin_name}")
    if debug and previous_skin is not None:
        print("SKIN_CHANGED")
        print(f"from: {previous_skin}")
        print(f"to: {skin_name}")
        print(f"timestamp: {observed_at.isoformat(timespec='seconds')}")


def run(debug=False):
    config = load_config()
    validate_live_config(config)
    catalog = load_catalog()
    configure_tesseract()
    state = SkinState(config)
    checks = 0
    ocr_times = []
    started_at = time.perf_counter()

    print("Waiting for VALORANT...")
    game_running = False
    session_id = None
    baseline = None
    last_sequence = None
    try:
        while True:
            time.sleep(config["check_interval_ms"] / 1000)

            status = read_status()
            is_running = status is not None and status.running
            if not is_running:
                if game_running:
                    state.reset_for_game_restart(datetime.now())
                    print("VALORANT exited")
                    print("Waiting for VALORANT...")
                game_running = False
                session_id = None
                baseline = None
                last_sequence = None
                continue

            if not game_running or status.session_id != session_id:
                if game_running:
                    state.reset_for_game_restart(datetime.now())
                game_running = True
                session_id = status.session_id
                baseline = None
                last_sequence = None
                print("VALORANT detected")
                print(f"Game window found: {status.width}x{status.height}")
                print("Tracking started")

            if not status.focused:
                baseline = None
                continue

            frame = read_frame(last_sequence)
            if frame is None:
                continue
            last_sequence = frame.sequence
            crop = frame.image
            checks += 1
            sample = difference_sample(crop, config["difference_width"])
            if baseline is None:
                baseline = sample
                continue

            if sample.size != baseline.size:
                baseline = sample
                continue
            if mean_absolute_difference(baseline, sample) < config["change_threshold"]:
                baseline = sample
                continue

            if debug:
                print("HUD change detected")
            time.sleep(config["stabilization_ms"] / 1000)
            status = read_status()
            if status is None or not status.running or not status.focused:
                baseline = None
                continue
            frame = read_frame(last_sequence)
            if frame is not None:
                last_sequence = frame.sequence
                crop = frame.image
            baseline = difference_sample(crop, config["difference_width"])
            match, score = perform_ocr(crop, config, catalog, debug, ocr_times)
            event = state.observe(match, score, datetime.now())

            for _ in range(config["confirmation_count"] - 1):
                if event is not None or match == UNKNOWN:
                    break
                time.sleep(config["confirmation_delay_ms"] / 1000)
                status = read_status()
                if status is None or not status.running or not status.focused:
                    baseline = None
                    break
                frame = read_frame(last_sequence)
                if frame is None:
                    break
                last_sequence = frame.sequence
                crop = frame.image
                baseline = difference_sample(crop, config["difference_width"])
                match, score = perform_ocr(crop, config, catalog, debug, ocr_times)
                event = state.observe(match, score, datetime.now())
            if event is not None:
                report_transition(event, debug)
    except KeyboardInterrupt:
        pass
    finally:
        state.close(datetime.now())
        print_summary(state, checks, started_at, ocr_times)


def main():
    parser = argparse.ArgumentParser(description="Track equipped VALORANT skins in memory.")
    parser.add_argument("--debug", action="store_true", help="Show HUD and OCR events")
    args = parser.parse_args()
    try:
        run(args.debug)
    except (CatalogError, PrototypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
