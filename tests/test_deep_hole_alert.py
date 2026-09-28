import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from bots import deep_hole_alert as alert


class StopTracker(BaseException):
    pass


class DeepHoleAlertTests(unittest.TestCase):
    def test_waits_do_not_skip_spawn_or_expiry(self):
        self.assertEqual(alert._next_wait_seconds(1770), 30)
        self.assertEqual(alert._next_wait_seconds(1796, 4, True), 5)
        self.assertLessEqual(alert._next_wait_seconds(1791, 1799), 30)

    def test_event_key_uses_expiry(self):
        now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        expiry = now + timedelta(minutes=30)
        reports = [{"server": alert.DEEP_HOLE_TARGET_SERVER,
                    "area": alert.DEEP_HOLE_TARGET_AREA,
                    "expired": expiry.isoformat()}]
        status = alert._extract_target_status_from_reports(reports, timezone.utc, now)
        self.assertTrue(status["is_open"])
        self.assertEqual(status["event_key"], expiry.isoformat())

    def test_late_reports_consecutive_cycles_and_temporary_gaps(self):
        def opened(key, remaining):
            return dict(is_open=True, event_key=key, reset_seconds=1796,
                        target_remaining_seconds=remaining)

        statuses = iter([
            dict(is_open=False, reset_seconds=1796),
            opened("cycle-a", 1770),  # Report arrived after boundary.
            opened("cycle-a", 1740),  # No duplicate start.
            dict(is_open=False, reset_seconds=1700),
            opened("cycle-a", 1680),  # Same event reappears, no duplicate.
            opened("cycle-a", 599),   # Reminder once.
            opened("cycle-a", 4),
            opened("cycle-b", 1799), # No observed closed state.
            RuntimeError("temporary API failure"),
            opened("cycle-b", 1769),
        ])
        waits, messages = [], []

        def fetch(kst):
            item = next(statuses, None)
            if item is None:
                raise StopTracker()
            if isinstance(item, Exception):
                raise item
            return item

        class InlineThread:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                with self_case.assertRaises(StopTracker):
                    self.target()

        self_case = self
        with patch.object(alert, "_TRACKER_STARTED", False), \
             patch.object(alert, "DEEP_HOLE_TRACKER_ENABLED", True), \
             patch.object(alert.threading, "Thread", InlineThread), \
             patch.object(alert.time, "sleep", waits.append), \
             patch.object(alert, "fetch_deep_hole_status", fetch), \
             patch.object(alert, "get_deep_hole_room_ids", return_value=["room"]):
            alert.start_deep_hole_tracker(
                None, lambda bot, room, message: messages.append(message),
                None, None, timezone.utc)

        self.assertEqual(len(messages), 3)  # A start, A reminder, B start.
        self.assertIn("30분", messages[0])
        self.assertIn("10분", messages[1])
        self.assertIn("30분", messages[2])
        self.assertTrue(all(wait <= 30 for wait in waits))
        self.assertEqual(waits[7], 5)  # After the 4-seconds-left response.
        self.assertEqual(waits[9], 30)  # Retry after API failure.


if __name__ == "__main__":
    unittest.main()
