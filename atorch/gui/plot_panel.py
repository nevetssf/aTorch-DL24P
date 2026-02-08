"""Real-time plotting panel using pyqtgraph with multiple Y-axes."""

from collections import deque
from typing import Optional
import time as time_module
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QCheckBox
)
from PySide6.QtCore import Qt
import pyqtgraph as pg

from ..protocol.atorch_protocol import DeviceStatus
from ..data.models import TestSession


def _get_unit_scale(data_max: float, base_unit: str) -> tuple:
    """Determine appropriate unit scaling for nice integer display.

    Args:
        data_max: Maximum data value in base units
        base_unit: The base unit (e.g., "V", "A", "W")

    Returns:
        Tuple of (scale_factor, display_unit) where data * scale_factor gives display values
    """
    # Unit scaling options: (threshold, scale, unit_prefix)
    # If max value is below threshold, use the scale
    unit_scales = {
        "V": [(1, 1000, "mV"), (1000, 1, "V")],
        "A": [(1, 1000, "mA"), (1000, 1, "A")],
        "W": [(1, 1000, "mW"), (1000, 1, "W")],
        "Wh": [(1, 1000, "mWh"), (1000, 1, "Wh")],
        "mAh": [(1000, 1, "mAh"), (1000000, 0.001, "Ah")],
        "°C": [(100, 1, "°C")],  # No scaling for temperature
    }

    scales = unit_scales.get(base_unit, [(float('inf'), 1, base_unit)])

    for threshold, scale, unit in scales:
        if data_max < threshold:
            return scale, unit

    # Default: no scaling
    return 1, base_unit


def _nice_axis_bounds_int(data_max: float) -> int:
    """Compute nice integer max axis bound (min is always 0).

    Args:
        data_max: Maximum data value (already scaled)

    Returns:
        Nice integer max value
    """
    import math

    if data_max <= 0:
        return 1

    # Add 10% margin
    data_max *= 1.1

    # For small ranges, just use ceil
    if data_max <= 5:
        return max(1, math.ceil(data_max))

    # Round up to nice integer (multiples of 1, 2, 5, 10, 20, 50, etc.)
    magnitude = 10 ** math.floor(math.log10(data_max))
    normalized = data_max / magnitude

    if normalized <= 1:
        nice = 1
    elif normalized <= 2:
        nice = 2
    elif normalized <= 5:
        nice = 5
    else:
        nice = 10

    return int(nice * magnitude)


class PlotPanel(QWidget):
    """Panel for real-time data visualization with independent Y-axes per series."""

    # Plot colors and config: (name, color, unit)
    SERIES_CONFIG = [
        ("Voltage", "#FFD700", "V"),      # Gold
        ("Current", "#00BFFF", "A"),      # Deep sky blue
        ("Power", "#FF6B6B", "W"),        # Coral red
        ("MOSFET Temp", "#98FB98", "°C"), # Pale green
        ("Ext Temp", "#90EE90", "°C"),    # Light green
        ("Capacity", "#DDA0DD", "mAh"),   # Plum
        ("Energy", "#FFA07A", "Wh"),      # Light salmon
    ]

    def __init__(self, max_points: int = 3600):
        super().__init__()

        self.max_points = max_points

        # Data storage
        self._time_data: deque = deque(maxlen=max_points)
        self._data = {name: deque(maxlen=max_points) for name, _, _ in self.SERIES_CONFIG}

        # Start time for relative time calculation
        self._start_time: Optional[float] = None

        # UI elements
        self._checkboxes = {}
        self._curves = {}
        self._viewboxes = {}
        self._axes = {}
        self._visible = {}
        self._unit_scales = {}  # Current scale factor per series
        self._display_units = {}  # Current display unit per series

        self._create_ui()

    def _create_ui(self) -> None:
        """Create the plot panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Top controls row
        controls = QHBoxLayout()

        # Data series checkboxes
        controls.addWidget(QLabel("Show:"))

        for name, color, _ in self.SERIES_CONFIG:
            cb = QCheckBox(name)
            cb.setStyleSheet(f"QCheckBox {{ color: {color}; font-weight: bold; }}")
            cb.setChecked(name == "Voltage")  # Default to Voltage only
            cb.toggled.connect(lambda checked, n=name: self._on_series_toggled(n, checked))
            controls.addWidget(cb)
            self._checkboxes[name] = cb
            self._visible[name] = (name == "Voltage")

        controls.addStretch()
        layout.addLayout(controls)

        # Configure pyqtgraph
        pg.setConfigOptions(antialias=True)

        # Create plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#1a1a1a")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel("bottom", "Time (seconds)")

        layout.addWidget(self.plot_widget)

        # Get main plot item and viewbox
        self.plot_item = self.plot_widget.getPlotItem()
        self.main_vb = self.plot_item.vb

        # Set up the first series to use the main left axis
        self._setup_series()

        # Handle view resizing to sync all viewboxes
        self.main_vb.sigResized.connect(self._on_resize)

        # Initial sync of viewbox geometries (deferred to ensure layout is ready)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._on_resize)

    def _setup_series(self) -> None:
        """Set up each data series with its own ViewBox and Y-axis."""
        # Hide the default right axis - we'll manage our own
        self.plot_item.hideAxis('right')

        # Track right-side axis positions (start at column 3 to avoid conflicts)
        right_axis_col = 3

        for i, (name, color, unit) in enumerate(self.SERIES_CONFIG):
            visible = self._visible.get(name, False)

            if i == 0:
                # First series uses the main plot's left axis and viewbox
                left_axis = self.plot_item.getAxis('left')
                left_axis.setLabel(name, units=unit, color=color)
                left_axis.setPen(pg.mkPen(color, width=1))
                left_axis.setTextPen(pg.mkPen(color))

                # Create curve in main viewbox
                curve = self.plot_item.plot(pen=pg.mkPen(color, width=2))
                self._curves[name] = curve
                self._viewboxes[name] = self.main_vb
                self._axes[name] = left_axis

                # Set visibility
                curve.setVisible(visible)
                left_axis.setVisible(visible)

            else:
                # Additional series get their own ViewBox and axis on the right
                vb = pg.ViewBox()
                self._viewboxes[name] = vb

                # Add viewbox to scene and link X axis
                self.plot_item.scene().addItem(vb)
                vb.setXLink(self.main_vb)

                # Create axis on right side
                axis = pg.AxisItem('right')
                axis.setLabel(name, units=unit, color=color)
                axis.setPen(pg.mkPen(color, width=1))
                axis.setTextPen(pg.mkPen(color))
                axis.linkToView(vb)
                self._axes[name] = axis

                # Add axis to the plot layout at next available column
                self.plot_item.layout.addItem(axis, 2, right_axis_col)
                right_axis_col += 1

                # Create curve in this viewbox
                curve = pg.PlotDataItem(pen=pg.mkPen(color, width=2))
                vb.addItem(curve)
                self._curves[name] = curve

                # Set initial visibility
                curve.setVisible(visible)
                axis.setVisible(visible)

    def _on_resize(self) -> None:
        """Handle main viewbox resize - sync all viewboxes."""
        for name, vb in self._viewboxes.items():
            if vb != self.main_vb:
                vb.setGeometry(self.main_vb.sceneBoundingRect())

    def _on_series_toggled(self, name: str, checked: bool) -> None:
        """Handle checkbox toggle for a data series."""
        self._visible[name] = checked

        if name in self._curves:
            self._curves[name].setVisible(checked)
        if name in self._axes:
            self._axes[name].setVisible(checked)

        self._update_plots()

    def add_data_point(self, status: DeviceStatus) -> None:
        """Add a new data point from device status."""
        # Initialize start time on first data point
        if self._start_time is None:
            self._start_time = time_module.time()

        # Calculate relative time from start
        t = time_module.time() - self._start_time

        self._time_data.append(t)
        self._data["Voltage"].append(status.voltage)
        self._data["Current"].append(status.current)
        self._data["Power"].append(status.power)
        self._data["MOSFET Temp"].append(status.temperature_c)
        self._data["Ext Temp"].append(status.ext_temperature_c)
        self._data["Capacity"].append(status.capacity_mah)
        self._data["Energy"].append(status.energy_wh)

        self._update_plots()

    def load_session(self, session: TestSession) -> None:
        """Load a historical session for display."""
        self.clear_data()

        for reading in session.readings:
            self._time_data.append(reading.runtime_seconds)
            self._data["Voltage"].append(reading.voltage)
            self._data["Current"].append(reading.current)
            self._data["Power"].append(reading.power)
            self._data["MOSFET Temp"].append(reading.temperature_c)
            self._data["Ext Temp"].append(getattr(reading, 'ext_temperature_c', 0))
            self._data["Capacity"].append(reading.capacity_mah)
            self._data["Energy"].append(reading.energy_wh)

        self._update_plots()
    def clear_data(self) -> None:
        """Clear all plot data."""
        self._time_data.clear()
        for name in self._data:
            self._data[name].clear()
        self._start_time = None
        self._update_plots()

    def _update_time_axis_label(self) -> None:
        """Update the X-axis label with appropriate time units."""
        if not self._time_data:
            self.plot_item.setLabel("bottom", "Time (seconds)")
            return

        max_time = max(self._time_data) if self._time_data else 0

        if max_time < 120:
            self.plot_item.setLabel("bottom", "Time (seconds)")
        elif max_time < 7200:
            self.plot_item.setLabel("bottom", "Time (minutes)")
        else:
            self.plot_item.setLabel("bottom", "Time (hours)")

    def _update_plots(self) -> None:
        """Update all plot curves with current data."""
        if not self._time_data:
            for name in self._curves:
                self._curves[name].setData([], [])
            self._update_time_axis_label()
            return

        time_raw = np.array(self._time_data)

        # Show all data (full test)
        mask = np.ones(len(time_raw), dtype=bool)
        time_masked = time_raw

        # Convert time to appropriate display units
        max_time_val = time_masked[-1] if len(time_masked) > 0 else 0
        if max_time_val < 120:
            time_display = time_masked  # seconds
        elif max_time_val < 7200:
            time_display = time_masked / 60.0  # minutes
        else:
            time_display = time_masked / 3600.0  # hours

        # Update each series
        for name, _, base_unit in self.SERIES_CONFIG:
            data = np.array(self._data[name])[mask]

            if not self._visible.get(name, False) or len(data) == 0:
                self._curves[name].setData([], [])
                continue

            # Determine unit scaling for nice integer display
            if len(data) > 0:
                y_max = np.max(data)
                scale, display_unit = _get_unit_scale(y_max, base_unit)

                # Scale the data
                scaled_data = data * scale

                self._curves[name].setData(time_display, scaled_data)

                # Update axis label if unit changed
                if self._display_units.get(name) != display_unit:
                    self._display_units[name] = display_unit
                    self._axes[name].setLabel(display_unit)

                # Auto-range Y using nice integers (min always 0)
                scaled_max = np.max(scaled_data)
                nice_max = _nice_axis_bounds_int(scaled_max)

                vb = self._viewboxes[name]
                vb.setYRange(0, nice_max, padding=0)
            else:
                self._curves[name].setData(time_display, data)

        self._update_time_axis_label()
