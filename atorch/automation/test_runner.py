"""Test execution engine for automated testing."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Callable, Optional
import threading
import time

from ..protocol.device import Device
from ..protocol.atorch_protocol import DeviceStatus
from ..data.models import TestSession, Reading
from ..data.database import Database
from .profiles import (
    TestProfile,
    DischargeProfile,
    CycleProfile,
    TimedProfile,
    SteppedProfile,
)


class TestState(Enum):
    """Test execution states."""
    IDLE = auto()
    STARTING = auto()
    RUNNING = auto()
    PAUSED = auto()
    STOPPING = auto()
    COMPLETED = auto()
    ERROR = auto()
    VOLTAGE_CUTOFF = auto()
    TIMEOUT = auto()


@dataclass
class TestProgress:
    """Current test progress information."""
    state: TestState
    elapsed_seconds: int = 0
    current_step: int = 0
    total_steps: int = 1
    current_cycle: int = 0
    total_cycles: int = 1
    message: str = ""


class TestRunner:
    """Executes automated tests on the DL24P."""

    def __init__(self, device: Device, database: Database):
        self.device = device
        self.database = database

        self._state = TestState.IDLE
        self._profile: Optional[TestProfile] = None
        self._session: Optional[TestSession] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially

        self._progress = TestProgress(state=TestState.IDLE)
        self._progress_callback: Optional[Callable[[TestProgress], None]] = None
        self._complete_callback: Optional[Callable[[TestSession], None]] = None

    @property
    def state(self) -> TestState:
        """Get current test state."""
        return self._state

    @property
    def progress(self) -> TestProgress:
        """Get current progress."""
        return self._progress

    @property
    def is_running(self) -> bool:
        """Check if a test is currently running."""
        return self._state in (TestState.STARTING, TestState.RUNNING, TestState.PAUSED)

    def set_progress_callback(self, callback: Callable[[TestProgress], None]) -> None:
        """Set callback for progress updates."""
        self._progress_callback = callback

    def set_complete_callback(self, callback: Callable[[TestSession], None]) -> None:
        """Set callback for test completion."""
        self._complete_callback = callback

    def start(
        self,
        profile: TestProfile,
        battery_name: str = "",
        notes: str = "",
    ) -> bool:
        """Start a test with the given profile.

        Args:
            profile: Test profile to execute
            battery_name: Name of the battery being tested
            notes: Optional notes about the test

        Returns:
            True if test started successfully
        """
        if self.is_running:
            return False

        if not self.device.is_connected:
            return False

        self._profile = profile
        self._stop_event.clear()
        self._pause_event.set()

        # Create session
        self._session = TestSession(
            name=profile.name,
            start_time=datetime.now(),
            battery_name=battery_name,
            notes=notes,
            test_type=profile.__class__.__name__.replace("Profile", "").lower(),
            settings=profile.to_dict(),
        )
        self.database.create_session(self._session)

        # Start test thread
        self._state = TestState.STARTING
        self._thread = threading.Thread(target=self._run_test, daemon=True)
        self._thread.start()

        return True

    def stop(self) -> None:
        """Stop the current test."""
        if not self.is_running:
            return

        self._state = TestState.STOPPING
        self._stop_event.set()
        self._pause_event.set()  # Unpause to allow thread to exit

        if self._thread:
            self._thread.join(timeout=5.0)

    def pause(self) -> None:
        """Pause the current test."""
        if self._state == TestState.RUNNING:
            self._state = TestState.PAUSED
            self._pause_event.clear()
            self.device.turn_off()
            self._update_progress(message="Test paused")

    def resume(self) -> None:
        """Resume a paused test."""
        if self._state == TestState.PAUSED:
            self._state = TestState.RUNNING
            self._pause_event.set()
            self._update_progress(message="Test resumed")

    def _run_test(self) -> None:
        """Main test execution loop."""
        try:
            self._state = TestState.RUNNING

            if isinstance(self._profile, DischargeProfile):
                self._run_discharge(self._profile)
            elif isinstance(self._profile, CycleProfile):
                self._run_cycle(self._profile)
            elif isinstance(self._profile, TimedProfile):
                self._run_timed(self._profile)
            elif isinstance(self._profile, SteppedProfile):
                self._run_stepped(self._profile)

        except Exception as e:
            self._state = TestState.ERROR
            self._update_progress(message=f"Error: {e}")
        finally:
            self._finish_test()

    def _run_discharge(self, profile: DischargeProfile) -> None:
        """Execute a discharge test."""
        self._update_progress(message=f"Starting discharge at {profile.current_a}A")

        # Reset counters and set current
        self.device.reset_counters()
        time.sleep(0.5)
        self.device.set_current(profile.current_a)
        time.sleep(0.5)
        self.device.set_voltage_cutoff(profile.voltage_cutoff)
        time.sleep(0.5)
        self.device.turn_on()

        start_time = time.time()

        while not self._stop_event.is_set():
            # Wait if paused
            self._pause_event.wait()

            if self._stop_event.is_set():
                break

            # Get current status
            status = self.device.last_status
            if status:
                # Log reading
                self._log_reading(status)

                # Check voltage cutoff
                if status.voltage <= profile.voltage_cutoff and status.load_on:
                    self._state = TestState.VOLTAGE_CUTOFF
                    self._update_progress(message=f"Voltage cutoff reached: {status.voltage:.2f}V")
                    break

                # Check load turned off (device-side cutoff)
                if not status.load_on and self._state == TestState.RUNNING:
                    # Device stopped on its own
                    self._state = TestState.VOLTAGE_CUTOFF
                    self._update_progress(message="Device stopped (cutoff reached)")
                    break

                elapsed = int(time.time() - start_time)
                self._update_progress(
                    elapsed_seconds=elapsed,
                    message=f"{status.voltage:.2f}V @ {status.current:.3f}A",
                )

                # Check max duration
                if profile.max_duration_s and elapsed >= profile.max_duration_s:
                    self._state = TestState.TIMEOUT
                    self._update_progress(message="Maximum duration reached")
                    break

            time.sleep(1.0)

    def _run_cycle(self, profile: CycleProfile) -> None:
        """Execute a cycle test."""
        for cycle in range(profile.num_cycles):
            if self._stop_event.is_set():
                break

            self._update_progress(
                current_cycle=cycle + 1,
                total_cycles=profile.num_cycles,
                message=f"Cycle {cycle + 1}/{profile.num_cycles}",
            )

            # Run discharge
            discharge = DischargeProfile(
                name=f"Cycle {cycle + 1}",
                current_a=profile.current_a,
                voltage_cutoff=profile.voltage_cutoff,
            )
            self._run_discharge(discharge)

            if self._stop_event.is_set():
                break

            # Rest between cycles
            if cycle < profile.num_cycles - 1:
                self._update_progress(message=f"Resting for {profile.rest_between_cycles_s}s")
                self.device.turn_off()
                for _ in range(profile.rest_between_cycles_s):
                    if self._stop_event.is_set():
                        break
                    time.sleep(1.0)

    def _run_timed(self, profile: TimedProfile) -> None:
        """Execute a timed test."""
        self._update_progress(message=f"Starting {profile.duration_s}s test at {profile.current_a}A")

        self.device.reset_counters()
        time.sleep(0.5)
        self.device.set_current(profile.current_a)
        time.sleep(0.5)
        if profile.voltage_cutoff:
            self.device.set_voltage_cutoff(profile.voltage_cutoff)
            time.sleep(0.5)
        self.device.set_timer(profile.duration_s)
        time.sleep(0.5)
        self.device.turn_on()

        start_time = time.time()

        while not self._stop_event.is_set():
            self._pause_event.wait()
            if self._stop_event.is_set():
                break

            status = self.device.last_status
            if status:
                self._log_reading(status)

                elapsed = int(time.time() - start_time)
                remaining = max(0, profile.duration_s - elapsed)
                self._update_progress(
                    elapsed_seconds=elapsed,
                    message=f"{remaining}s remaining | {status.voltage:.2f}V",
                )

                if elapsed >= profile.duration_s:
                    self._state = TestState.COMPLETED
                    break

                if not status.load_on:
                    # Timer completed or voltage cutoff
                    self._state = TestState.COMPLETED
                    break

            time.sleep(1.0)

    def _run_stepped(self, profile: SteppedProfile) -> None:
        """Execute a stepped current test."""
        self.device.reset_counters()
        time.sleep(0.5)

        if profile.voltage_cutoff:
            self.device.set_voltage_cutoff(profile.voltage_cutoff)
            time.sleep(0.5)

        for i, step in enumerate(profile.steps):
            if self._stop_event.is_set():
                break

            current = step["current_a"]
            duration = step["duration_s"]

            self._update_progress(
                current_step=i + 1,
                total_steps=len(profile.steps),
                message=f"Step {i + 1}: {current}A for {duration}s",
            )

            self.device.set_current(current)
            time.sleep(0.5)
            self.device.turn_on()

            # Run step
            step_start = time.time()
            while not self._stop_event.is_set():
                self._pause_event.wait()
                if self._stop_event.is_set():
                    break

                status = self.device.last_status
                if status:
                    self._log_reading(status)

                    if profile.voltage_cutoff and status.voltage <= profile.voltage_cutoff:
                        self._state = TestState.VOLTAGE_CUTOFF
                        return

                elapsed = time.time() - step_start
                if elapsed >= duration:
                    break

                time.sleep(1.0)

            # Rest between steps
            if i < len(profile.steps) - 1 and not self._stop_event.is_set():
                self.device.turn_off()
                time.sleep(profile.rest_between_steps_s)

        self._state = TestState.COMPLETED

    def _log_reading(self, status: DeviceStatus) -> None:
        """Log a reading to the database."""
        reading = Reading(
            timestamp=datetime.now(),
            voltage=status.voltage,
            current=status.current,
            power=status.power,
            energy_wh=status.energy_wh,
            capacity_mah=status.capacity_mah,
            temperature_c=status.temperature_c,
            ext_temperature_c=status.ext_temperature_c,
            runtime_seconds=status.runtime_seconds,
        )

        if self._session and self._session.id:
            self.database.add_reading(self._session.id, reading)
            self._session.readings.append(reading)

    def _update_progress(self, **kwargs) -> None:
        """Update and broadcast progress."""
        for key, value in kwargs.items():
            if hasattr(self._progress, key):
                setattr(self._progress, key, value)

        self._progress.state = self._state

        if self._progress_callback:
            try:
                self._progress_callback(self._progress)
            except Exception:
                pass

    def _finish_test(self) -> None:
        """Clean up after test completion."""
        # Stop logging first - update session and trigger callbacks
        if self._session:
            self._session.end_time = datetime.now()
            self.database.update_session(self._session)

            if self._complete_callback:
                try:
                    self._complete_callback(self._session)
                except Exception:
                    pass

        # Then turn off load
        try:
            self.device.turn_off()
        except Exception:
            pass

        if self._state not in (TestState.COMPLETED, TestState.VOLTAGE_CUTOFF, TestState.TIMEOUT, TestState.ERROR):
            self._state = TestState.COMPLETED

        self._update_progress(message="Test complete")
