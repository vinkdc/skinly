import unittest
from datetime import datetime, timedelta

from PIL import Image

from hud_live import (
    SkinState,
    difference_sample,
    format_duration,
    mean_absolute_difference,
)


class HudLiveTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "confirmation_count": 2,
            "confirmation_window_ms": 1500,
            "high_confidence_threshold": 92,
        }
        self.started = datetime(2026, 9, 14, 13, 42, 0)

    def test_difference_detects_changed_roi(self):
        dark = difference_sample(Image.new("RGB", (200, 100), "black"), 64)
        light = difference_sample(Image.new("RGB", (200, 100), "white"), 64)

        self.assertEqual(mean_absolute_difference(dark, dark), 0)
        self.assertEqual(mean_absolute_difference(dark, light), 255)

    def test_high_confidence_specific_skin_confirms_once(self):
        state = SkinState(self.config)

        event = state.observe("Champions 2025 Vandal", 96, self.started)

        self.assertEqual(event[1], "Champions 2025 Vandal")
        self.assertEqual(state.current_skin, "Champions 2025 Vandal")

    def test_generic_knife_requires_two_readings(self):
        state = SkinState(self.config)
        state.observe("Champions 2025 Vandal", 96, self.started)

        first = state.observe("Knife", 100, self.started + timedelta(seconds=1))
        second = state.observe("Knife", 100, self.started + timedelta(seconds=1.25))

        self.assertIsNone(first)
        self.assertEqual(second[0:2], ("Champions 2025 Vandal", "Knife"))

    def test_unknown_does_not_close_current_session(self):
        state = SkinState(self.config)
        state.observe("Champions 2025 Vandal", 96, self.started)

        event = state.observe("UNKNOWN", 0, self.started + timedelta(seconds=5))

        self.assertIsNone(event)
        self.assertEqual(state.current_skin, "Champions 2025 Vandal")
        self.assertIsNone(state.sessions[-1].ended_at)

    def test_game_restart_closes_session_and_allows_same_skin_to_start_again(self):
        state = SkinState(self.config)
        state.observe("Champions 2025 Vandal", 96, self.started)
        restarted_at = self.started + timedelta(minutes=2)

        state.reset_for_game_restart(restarted_at)
        event = state.observe("Champions 2025 Vandal", 96, restarted_at)

        self.assertEqual(state.sessions[0].ended_at, restarted_at)
        self.assertEqual(event[1], "Champions 2025 Vandal")
        self.assertEqual(len(state.sessions), 2)

    def test_short_knife_interruption_does_not_switch_skin(self):
        state = SkinState(self.config)
        state.observe("Champions 2025 Vandal", 96, self.started)
        state.observe("Knife", 100, self.started + timedelta(seconds=1))

        event = state.observe(
            "Champions 2025 Vandal", 96, self.started + timedelta(seconds=1.1)
        )

        self.assertIsNone(event)
        self.assertEqual(state.current_skin, "Champions 2025 Vandal")
        self.assertEqual(len(state.sessions), 1)
        self.assertEqual(
            state.last_confirmed_at, self.started + timedelta(seconds=1.1)
        )

    def test_switch_closes_previous_session(self):
        state = SkinState(self.config)
        state.observe("Champions 2025 Vandal", 96, self.started)
        switched_at = self.started + timedelta(seconds=10)

        event = state.observe("Reaver Phantom", 96, switched_at)

        self.assertEqual(event[0:2], ("Champions 2025 Vandal", "Reaver Phantom"))
        self.assertEqual(state.sessions[0].ended_at, switched_at)
        self.assertEqual(state.sessions[0].duration_seconds, 10)

    def test_duration_format(self):
        self.assertEqual(format_duration(762), "12m 42s")


if __name__ == "__main__":
    unittest.main()
