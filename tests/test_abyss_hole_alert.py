import unittest
from datetime import timezone
from unittest.mock import patch

from bots import abyss_hole_alert as alert


class StopTracker(BaseException):
    pass


class AbyssHourAlertTests(unittest.TestCase):
    def test_wake_at_hour_then_ten_minutes_then_spawn(self):
        status = {"is_open": False, "seconds_to_start": 4000}
        self.assertEqual(alert._next_wait_seconds(status), 401)
        status["seconds_to_start"] = 700
        self.assertEqual(alert._next_wait_seconds(status, hour_alert_sent=True), 101)
        status["seconds_to_start"] = 599
        self.assertEqual(alert._next_wait_seconds(status, True, False, True), 600)

    def run_tracker(self, events):
        statuses = iter(events)
        messages = []

        def fetch(kst):
            item = next(statuses, None)
            if item is None:
                raise StopTracker()
            key, seconds = item
            return {"event": {"start": key}, "is_open": seconds == 0,
                    "seconds_to_start": seconds, "target_remaining_seconds": 900}

        class InlineThread:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                try:
                    self.target()
                except StopTracker:
                    pass

        with patch.object(alert, "_TRACKER_STARTED", False), \
             patch.object(alert, "ABYSS_HOLE_TRACKER_ENABLED", True), \
             patch.object(alert.threading, "Thread", InlineThread), \
             patch.object(alert.time, "sleep"), \
             patch.object(alert, "fetch_abyss_hole_status", fetch), \
             patch.object(alert, "get_abyss_hole_room_ids", return_value=["room"]), \
             patch.object(alert, "_format_abyss_hole_alert_message", side_effect=lambda s, t: t):
            alert.start_abyss_hole_tracker(
                None, lambda bot, room, msg: messages.append(msg), None, None, timezone.utc)
        return messages

    def test_each_notice_once_and_new_cycle_resets(self):
        self.assertEqual(self.run_tracker([
            ("a", 4000), ("a", 3599), ("a", 1800),
            ("a", 599), ("a", 100), ("a", 0), ("a", 0),
            ("b", 3599),
        ]), ["hour", "pre", "spawn", "hour"])

    def test_late_start_does_not_send_stale_hour_notice(self):
        self.assertEqual(self.run_tracker([("a", 300), ("a", 0)]), ["pre", "spawn"])


if __name__ == "__main__":
    unittest.main()
