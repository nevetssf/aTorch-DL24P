"""Test automation panel."""

from pathlib import Path
from typing import Optional
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QLineEdit,
    QTextEdit,
    QProgressBar,
    QFileDialog,
    QMessageBox,
    QFormLayout,
)
from PySide6.QtCore import Qt, Slot, Signal

from ..automation.test_runner import TestRunner, TestProgress, TestState
from ..automation.profiles import (
    TestProfile,
    DischargeProfile,
    TimedProfile,
)
from ..data.database import Database


class AutomationPanel(QWidget):
    """Panel for test automation control."""

    # Signal emitted when test should start: (current_a, voltage_cutoff, duration_s or 0)
    start_test_requested = Signal(float, float, int)
    # Signal emitted when pause is clicked (stops logging and load, keeps data)
    pause_test_requested = Signal()
    # Signal emitted when resume is clicked (continues logging and load)
    resume_test_requested = Signal()

    def __init__(self, test_runner: TestRunner, database: Database):
        super().__init__()

        self.test_runner = test_runner
        self.database = database
        self._current_profile: Optional[TestProfile] = None

        self._create_ui()

    def _create_ui(self) -> None:
        """Create the automation panel UI."""
        layout = QHBoxLayout(self)

        # Left: Test configuration
        config_group = QGroupBox("Test Configuration")
        config_layout = QVBoxLayout(config_group)

        # Test type selection
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Test Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Discharge", "Timed"])
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_layout.addWidget(self.type_combo)
        config_layout.addLayout(type_layout)

        # Parameters form
        self.params_form = QFormLayout()

        # Current
        self.current_spin = QDoubleSpinBox()
        self.current_spin.setRange(0.0, 24.0)
        self.current_spin.setDecimals(3)
        self.current_spin.setSingleStep(0.1)
        self.current_spin.setValue(0.5)
        self.params_form.addRow("Current (A):", self.current_spin)

        # Voltage cutoff
        self.cutoff_spin = QDoubleSpinBox()
        self.cutoff_spin.setRange(0.0, 200.0)
        self.cutoff_spin.setDecimals(2)
        self.cutoff_spin.setSingleStep(0.1)
        self.cutoff_spin.setValue(3.0)
        self.params_form.addRow("V Cutoff:", self.cutoff_spin)

        # Duration (for timed tests)
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 86400)
        self.duration_spin.setValue(3600)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setEnabled(False)
        self.params_form.addRow("Duration:", self.duration_spin)

        config_layout.addLayout(self.params_form)

        # Profile buttons
        profile_layout = QHBoxLayout()

        self.save_profile_btn = QPushButton("Save Profile")
        self.save_profile_btn.clicked.connect(self._save_profile)
        profile_layout.addWidget(self.save_profile_btn)

        self.load_profile_btn = QPushButton("Load Profile")
        self.load_profile_btn.clicked.connect(self._load_profile)
        profile_layout.addWidget(self.load_profile_btn)

        config_layout.addLayout(profile_layout)

        layout.addWidget(config_group)

        # Middle: Battery info
        info_group = QGroupBox("Battery Info")
        info_layout = QFormLayout(info_group)

        self.battery_name_edit = QLineEdit()
        self.battery_name_edit.setPlaceholderText("e.g., Samsung 30Q")
        info_layout.addRow("Battery Name:", self.battery_name_edit)

        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)
        self.notes_edit.setPlaceholderText("Test notes...")
        info_layout.addRow("Notes:", self.notes_edit)

        layout.addWidget(info_group)

        # Right: Test control
        control_group = QGroupBox("Test Control")
        control_layout = QVBoxLayout(control_group)

        # Start/Stop button
        self.start_btn = QPushButton("Start Test")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.clicked.connect(self._on_start_clicked)
        control_layout.addWidget(self.start_btn)

        # Pause/Resume button
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        control_layout.addWidget(self.pause_btn)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setValue(0)
        control_layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignCenter)
        control_layout.addWidget(self.status_label)

        # Elapsed time
        self.elapsed_label = QLabel("00:00:00")
        self.elapsed_label.setAlignment(Qt.AlignCenter)
        font = self.elapsed_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self.elapsed_label.setFont(font)
        control_layout.addWidget(self.elapsed_label)

        control_layout.addStretch()
        layout.addWidget(control_group)

    def _create_profile(self) -> TestProfile:
        """Create a profile from current settings."""
        test_type = self.type_combo.currentIndex()
        current = self.current_spin.value()
        cutoff = self.cutoff_spin.value()

        if test_type == 0:  # Discharge
            return DischargeProfile(
                name=f"Discharge {current}A to {cutoff}V",
                current_a=current,
                voltage_cutoff=cutoff,
            )
        else:  # Timed
            duration = self.duration_spin.value()
            return TimedProfile(
                name=f"Timed {current}A for {duration}s",
                current_a=current,
                duration_s=duration,
                voltage_cutoff=cutoff if cutoff > 0 else None,
            )

    @Slot(int)
    def _on_type_changed(self, index: int) -> None:
        """Handle test type selection change."""
        # Enable duration only for timed tests
        self.duration_spin.setEnabled(index == 1)  # Timed

    @Slot()
    def _on_start_clicked(self) -> None:
        """Handle start/stop button click."""
        if self.start_btn.text() == "Stop Test":
            # Stop test - this will be handled by main window turning off logging
            self._update_ui_stopped()
            # Emit with zeros to signal stop
            self.start_test_requested.emit(0, 0, 0)
        else:
            # Check if device is connected
            if not self.test_runner or not self.test_runner.device or not self.test_runner.device.is_connected:
                QMessageBox.warning(
                    self,
                    "Not Connected",
                    "Please connect to the device first.",
                )
                return

            # Start test - emit signal with parameters
            current = self.current_spin.value()
            cutoff = self.cutoff_spin.value()
            duration = self.duration_spin.value() if self.type_combo.currentIndex() == 1 else 0

            self.start_test_requested.emit(current, cutoff, duration)
            self._update_ui_running()

    @Slot()
    def _on_pause_clicked(self) -> None:
        """Handle pause/resume button click - toggles between pause and resume."""
        if self.pause_btn.text() == "Pause":
            # Pause the test
            self.pause_btn.setText("Resume")
            self.pause_test_requested.emit()
        else:
            # Resume the test
            self.pause_btn.setText("Pause")
            self.resume_test_requested.emit()

    @Slot()
    def _save_profile(self) -> None:
        """Save current settings as a profile."""
        profile = self._create_profile()

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Profile",
            f"{profile.name}.json",
            "JSON (*.json)",
        )

        if path:
            profile.save(Path(path))

    @Slot()
    def _load_profile(self) -> None:
        """Load a profile from file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Profile",
            "",
            "JSON (*.json)",
        )

        if path:
            try:
                profile = TestProfile.load(Path(path))
                self._apply_profile(profile)
            except Exception as e:
                QMessageBox.warning(self, "Load Error", str(e))

    def _apply_profile(self, profile: TestProfile) -> None:
        """Apply a loaded profile to the UI."""
        if isinstance(profile, DischargeProfile):
            self.type_combo.setCurrentIndex(0)
            self.current_spin.setValue(profile.current_a)
            self.cutoff_spin.setValue(profile.voltage_cutoff)
        elif isinstance(profile, TimedProfile):
            self.type_combo.setCurrentIndex(1)
            self.current_spin.setValue(profile.current_a)
            self.duration_spin.setValue(profile.duration_s)
            if profile.voltage_cutoff:
                self.cutoff_spin.setValue(profile.voltage_cutoff)

        self._current_profile = profile

    def update_progress(self, progress: TestProgress) -> None:
        """Update UI with test progress."""
        # Update status label
        self.status_label.setText(progress.message or progress.state.name)

        # Update elapsed time
        h = progress.elapsed_seconds // 3600
        m = (progress.elapsed_seconds % 3600) // 60
        s = progress.elapsed_seconds % 60
        self.elapsed_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

        # Update progress bar for cycle/stepped tests
        if progress.total_cycles > 1:
            percent = int(100 * progress.current_cycle / progress.total_cycles)
            self.progress_bar.setValue(percent)
            self.progress_bar.setFormat(
                f"Cycle {progress.current_cycle}/{progress.total_cycles}"
            )
        elif progress.total_steps > 1:
            percent = int(100 * progress.current_step / progress.total_steps)
            self.progress_bar.setValue(percent)
            self.progress_bar.setFormat(
                f"Step {progress.current_step}/{progress.total_steps}"
            )
        else:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("")

        # Check for completion
        if progress.state in (
            TestState.COMPLETED,
            TestState.VOLTAGE_CUTOFF,
            TestState.TIMEOUT,
            TestState.ERROR,
        ):
            self._update_ui_stopped()

    def _update_ui_running(self) -> None:
        """Update UI for running state."""
        self.start_btn.setText("Stop Test")
        self.pause_btn.setEnabled(True)
        self.type_combo.setEnabled(False)
        self.current_spin.setEnabled(False)
        self.cutoff_spin.setEnabled(False)
        self.duration_spin.setEnabled(False)

    def _update_ui_stopped(self) -> None:
        """Update UI for stopped state."""
        self.start_btn.setText("Start Test")
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("Pause")  # Reset pause button text
        self.type_combo.setEnabled(True)
        self.current_spin.setEnabled(True)
        self.cutoff_spin.setEnabled(True)
        self._on_type_changed(self.type_combo.currentIndex())
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("")
