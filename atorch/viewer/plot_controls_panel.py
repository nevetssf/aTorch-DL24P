"""Unified plot controls panel for both Seaborn and Plotly rendering."""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox, QCheckBox
from PySide6.QtCore import Qt, Signal


class PlotControlsPanel(QWidget):
    """Control panel for plot settings."""

    # Signals emitted when settings change
    x_axis_changed = Signal(str)  # x_axis value
    x_reverse_changed = Signal(bool)  # reversed state
    y1_changed = Signal(str)  # y1 parameter
    y2_changed = Signal(str)  # y2 parameter
    y2_enabled_changed = Signal(bool)  # y2 enabled state
    normalize_changed = Signal(bool)  # normalize enabled state
    show_lines_changed = Signal(bool)  # show lines state
    show_points_changed = Signal(bool)  # show points state

    # Available parameters to plot
    PARAMETERS = [
        "Voltage",
        "Current",
        "Power",
        "Capacity",
        "Capacity Remaining",
        "Energy",
        "Energy Remaining",
        "R Load",
        "Temp MOSFET",
        "Set Current",
        "Set Voltage",
        "Set Power",
        "Set Resistance",
    ]

    # Available x-axis options
    X_AXIS_OPTIONS = [
        "Time",
        "Voltage",
        "Current",
        "Power",
        "Capacity",
        "Capacity Remaining",
        "Energy",
        "Energy Remaining",
        "R Load",
        "Temp MOSFET",
        "Set Current",
        "Set Voltage",
        "Set Power",
        "Set Resistance",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        # Current settings
        self._x_axis = "Time"
        self._x_reversed = False
        self._y1_param = "Voltage"
        self._y2_param = "Current"
        self._y2_enabled = False
        self._normalize_enabled = False
        self._show_lines = True
        self._show_points = False

        self._create_ui()

    def _create_ui(self):
        """Create the controls UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # X-axis selection
        layout.addWidget(QLabel("X-axis:"))
        self.x_axis_combo = QComboBox()
        self.x_axis_combo.addItems(self.X_AXIS_OPTIONS)
        self.x_axis_combo.setCurrentText(self._x_axis)
        self.x_axis_combo.currentTextChanged.connect(self._on_x_axis_changed)
        layout.addWidget(self.x_axis_combo)

        # X-axis reverse checkbox
        self.x_reverse_checkbox = QCheckBox("←")
        self.x_reverse_checkbox.setChecked(self._x_reversed)
        self.x_reverse_checkbox.setToolTip("Reverse X-axis direction (high to low)")
        self.x_reverse_checkbox.stateChanged.connect(self._on_x_reverse_changed)
        layout.addWidget(self.x_reverse_checkbox)

        layout.addSpacing(20)

        # Y1 axis selection (left axis, solid line)
        layout.addWidget(QLabel("Y1 (left):"))
        self.y1_combo = QComboBox()
        self.y1_combo.addItems(self.PARAMETERS)
        self.y1_combo.setCurrentText(self._y1_param)
        self.y1_combo.currentTextChanged.connect(self._on_y1_changed)
        layout.addWidget(self.y1_combo)

        layout.addSpacing(20)

        # Y2 axis selection (right axis, dashed line)
        self.y2_checkbox = QCheckBox("Y2 (right):")
        self.y2_checkbox.setChecked(self._y2_enabled)
        self.y2_checkbox.stateChanged.connect(self._on_y2_enabled_changed)
        layout.addWidget(self.y2_checkbox)

        self.y2_combo = QComboBox()
        self.y2_combo.addItems(self.PARAMETERS)
        self.y2_combo.setCurrentText(self._y2_param)
        self.y2_combo.setEnabled(self._y2_enabled)
        self.y2_combo.currentTextChanged.connect(self._on_y2_changed)
        layout.addWidget(self.y2_combo)

        layout.addSpacing(20)

        # Normalize to percentage checkbox
        self.normalize_checkbox = QCheckBox("%")
        self.normalize_checkbox.setChecked(self._normalize_enabled)
        self.normalize_checkbox.setToolTip("Normalize Y-axes to 0-100% scale")
        self.normalize_checkbox.stateChanged.connect(self._on_normalize_changed)
        layout.addWidget(self.normalize_checkbox)

        layout.addSpacing(20)

        # Lines visibility checkbox
        self.lines_checkbox = QCheckBox("Lines")
        self.lines_checkbox.setChecked(self._show_lines)
        self.lines_checkbox.setToolTip("Show lines connecting data points")
        self.lines_checkbox.stateChanged.connect(self._on_show_lines_changed)
        layout.addWidget(self.lines_checkbox)

        # Points visibility checkbox
        self.points_checkbox = QCheckBox("Points")
        self.points_checkbox.setChecked(self._show_points)
        self.points_checkbox.setToolTip("Show individual data points")
        self.points_checkbox.stateChanged.connect(self._on_show_points_changed)
        layout.addWidget(self.points_checkbox)

        layout.addStretch()

    def _on_x_axis_changed(self, x_axis: str):
        """Handle x-axis selection change."""
        self._x_axis = x_axis
        self.x_axis_changed.emit(x_axis)

    def _on_x_reverse_changed(self, state: int):
        """Handle X-axis reverse checkbox."""
        self._x_reversed = (state == Qt.CheckState.Checked.value)
        self.x_reverse_changed.emit(self._x_reversed)

    def _on_y1_changed(self, param: str):
        """Handle Y1 parameter selection change."""
        self._y1_param = param
        self.y1_changed.emit(param)

    def _on_y2_changed(self, param: str):
        """Handle Y2 parameter selection change."""
        self._y2_param = param
        self.y2_changed.emit(param)

    def _on_y2_enabled_changed(self, state: int):
        """Handle Y2 enable/disable checkbox."""
        self._y2_enabled = (state == Qt.CheckState.Checked.value)
        self.y2_combo.setEnabled(self._y2_enabled)
        self.y2_enabled_changed.emit(self._y2_enabled)

    def _on_normalize_changed(self, state: int):
        """Handle normalize to percentage checkbox."""
        self._normalize_enabled = (state == Qt.CheckState.Checked.value)
        self.normalize_changed.emit(self._normalize_enabled)

    def _on_show_lines_changed(self, state: int):
        """Handle show lines checkbox."""
        self._show_lines = (state == Qt.CheckState.Checked.value)
        self.show_lines_changed.emit(self._show_lines)

    def _on_show_points_changed(self, state: int):
        """Handle show points checkbox."""
        self._show_points = (state == Qt.CheckState.Checked.value)
        self.show_points_changed.emit(self._show_points)

    def get_settings(self):
        """Get current settings as a dict."""
        return {
            'x_axis': self._x_axis,
            'x_reversed': self._x_reversed,
            'y1': self._y1_param,
            'y2': self._y2_param,
            'y2_enabled': self._y2_enabled,
            'normalize': self._normalize_enabled,
            'show_lines': self._show_lines,
            'show_points': self._show_points,
        }

    def set_settings(self, settings: dict):
        """Set settings from a dict (used for test type restoration)."""
        # Block signals while updating
        self.x_axis_combo.blockSignals(True)
        self.x_reverse_checkbox.blockSignals(True)
        self.y1_combo.blockSignals(True)
        self.y2_combo.blockSignals(True)
        self.y2_checkbox.blockSignals(True)
        self.normalize_checkbox.blockSignals(True)
        self.lines_checkbox.blockSignals(True)
        self.points_checkbox.blockSignals(True)

        self._x_axis = settings.get('x_axis', 'Time')
        self._x_reversed = settings.get('x_reversed', False)
        self._y1_param = settings.get('y1', 'Voltage')
        self._y2_param = settings.get('y2', 'Current')
        self._y2_enabled = settings.get('y2_enabled', False)
        self._normalize_enabled = settings.get('normalize', False)
        self._show_lines = settings.get('show_lines', True)
        self._show_points = settings.get('show_points', False)

        self.x_axis_combo.setCurrentText(self._x_axis)
        self.x_reverse_checkbox.setChecked(self._x_reversed)
        self.y1_combo.setCurrentText(self._y1_param)
        self.y2_combo.setCurrentText(self._y2_param)
        self.y2_combo.setEnabled(self._y2_enabled)
        self.y2_checkbox.setChecked(self._y2_enabled)
        self.normalize_checkbox.setChecked(self._normalize_enabled)
        self.lines_checkbox.setChecked(self._show_lines)
        self.points_checkbox.setChecked(self._show_points)

        # Unblock signals
        self.x_axis_combo.blockSignals(False)
        self.x_reverse_checkbox.blockSignals(False)
        self.y1_combo.blockSignals(False)
        self.y2_combo.blockSignals(False)
        self.y2_checkbox.blockSignals(False)
        self.normalize_checkbox.blockSignals(False)
        self.lines_checkbox.blockSignals(False)
        self.points_checkbox.blockSignals(False)
