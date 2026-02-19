"""Scheduled and timed test execution."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional
import threading
import time


@dataclass
class ScheduledTest:
    """A scheduled test to run at a specific time."""
    id: str
    start_time: datetime
    profile_path: str
    battery_name: str = ""
    notes: str = ""
    repeat_interval_hours: Optional[float] = None


class Scheduler:
    """Manages scheduled test execution."""

    def __init__(self):
        self._scheduled: dict[str, ScheduledTest] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._start_callback: Optional[Callable[[ScheduledTest], None]] = None

    @property
    def scheduled_tests(self) -> list[ScheduledTest]:
        """Get list of scheduled tests."""
        with self._lock:
            return list(self._scheduled.values())

    def set_start_callback(self, callback: Callable[[ScheduledTest], None]) -> None:
        """Set callback when a scheduled test should start."""
        self._start_callback = callback

    def schedule(self, test: ScheduledTest) -> None:
        """Schedule a test.

        Args:
            test: ScheduledTest to schedule
        """
        with self._lock:
            self._scheduled[test.id] = test

    def cancel(self, test_id: str) -> bool:
        """Cancel a scheduled test.

        Args:
            test_id: ID of test to cancel

        Returns:
            True if found and cancelled
        """
        with self._lock:
            if test_id in self._scheduled:
                del self._scheduled[test_id]
                return True
            return False

    def schedule_delay(
        self,
        profile_path: str,
        delay_seconds: int,
        battery_name: str = "",
        notes: str = "",
    ) -> str:
        """Schedule a test to run after a delay.

        Args:
            profile_path: Path to test profile
            delay_seconds: Delay in seconds
            battery_name: Battery name
            notes: Test notes

        Returns:
            ID of scheduled test
        """
        test_id = f"delay_{int(time.time())}"
        start_time = datetime.now() + timedelta(seconds=delay_seconds)

        test = ScheduledTest(
            id=test_id,
            start_time=start_time,
            profile_path=profile_path,
            battery_name=battery_name,
            notes=notes,
        )

        self.schedule(test)
        return test_id

    def schedule_at(
        self,
        profile_path: str,
        start_time: datetime,
        battery_name: str = "",
        notes: str = "",
        repeat_hours: Optional[float] = None,
    ) -> str:
        """Schedule a test for a specific time.

        Args:
            profile_path: Path to test profile
            start_time: When to start
            battery_name: Battery name
            notes: Test notes
            repeat_hours: Optional repeat interval

        Returns:
            ID of scheduled test
        """
        test_id = f"at_{int(time.time())}"

        test = ScheduledTest(
            id=test_id,
            start_time=start_time,
            profile_path=profile_path,
            battery_name=battery_name,
            notes=notes,
            repeat_interval_hours=repeat_hours,
        )

        self.schedule(test)
        return test_id

    def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run_loop(self) -> None:
        """Scheduler loop."""
        while self._running:
            now = datetime.now()
            to_run = []

            with self._lock:
                for test_id, test in list(self._scheduled.items()):
                    if test.start_time <= now:
                        to_run.append(test)

                        # Handle repeat
                        if test.repeat_interval_hours:
                            test.start_time = now + timedelta(hours=test.repeat_interval_hours)
                        else:
                            del self._scheduled[test_id]

            # Trigger callbacks
            for test in to_run:
                if self._start_callback:
                    try:
                        self._start_callback(test)
                    except Exception:
                        pass

            time.sleep(1.0)
