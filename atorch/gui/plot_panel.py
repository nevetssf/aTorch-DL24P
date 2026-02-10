"""Real-time plotting panel using pyqtgraph with multiple Y-axes."""

from collections import deque
from typing import Optional
import time as time_module
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QCheckBox, QScrollBar
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
        "Ω": [(1, 1000, "mΩ"), (1000, 1, "Ω")],  # Resistance scaling
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


def _nice_range_bounds(data_min: float, data_max: float) -> tuple:
    """Compute nice range bounds that encompass all data.

    Args:
        data_min: Minimum data value
        data_max: Maximum data value

    Returns:
        Tuple of (nice_min, nice_max) that encompass the data range
    """
    import math

    if data_min >= data_max:
        return (0, 1)

    # Add 5% margin on each side
    range_span = data_max - data_min
    margin = range_span * 0.05
    data_min_margin = data_min - margin
    data_max_margin = data_max + margin

    # Determine magnitude for rounding
    magnitude = 10 ** math.floor(math.log10(range_span))

    # Round min down, max up to nearest nice value
    # For magnitude, use multiples of 1, 2, 5
    if range_span / magnitude < 2:
        step = magnitude / 10  # Use finer steps for small ranges
    elif range_span / magnitude < 5:
        step = magnitude / 5
    else:
        step = magnitude

    nice_min = math.floor(data_min_margin / step) * step
    nice_max = math.ceil(data_max_margin / step) * step

    # Never go below 0
    nice_min = max(0, nice_min)

    # Ensure we have at least some range
    if nice_max - nice_min < step:
        nice_max = nice_min + step

    return (nice_min, nice_max)


class PlotPanel(QWidget):
    """Panel for real-time data visualization with independent Y-axes per series."""

    # Plot colors and config: (name, color, unit)
    # Colors chosen for visibility on both dark (#1a1a1a) and light grey backgrounds
    # Medium luminance, high saturation, distinct hues spread across color wheel
    SERIES_CONFIG = [
        ("Voltage", "#FFC107", "V"),      # Amber - warm yellow
        ("Current", "#29B6F6", "A"),      # Light blue - cool
        ("Power", "#EF5350", "W"),        # Red - attention
        ("Load R", "#66BB6A", "Ω"),       # Green - resistance
        ("Battery R", "#5C6BC0", "Ω"),    # Indigo - internal resistance
        ("MOSFET Temp", "#26A69A", "°C"), # Teal - blue-green
        ("Ext Temp", "#9CCC65", "°C"),    # Light green - yellow-green
        ("Capacity", "#AB47BC", "mAh"),   # Purple - distinct
        ("Energy", "#FF7043", "Wh"),      # Deep orange - warm
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
        self._show_points = False  # Whether to show point markers

        # Time window settings
        self._time_window_seconds = None  # None = Full, otherwise window size in seconds
        self._time_scroll_position = 1.0  # 0.0 = start, 1.0 = end (most recent)
        self._data_exceeded_window = False  # Track if data has exceeded window (for auto-scroll switch)

        # X-axis settings
        self._x_axis_param = "Time"  # Default to Time, can be any parameter name

        # Plot update throttling to reduce rendering overhead
        self._plot_update_counter = 0
        self._plot_update_interval = 2  # Update plot every N data points (reduces 23-50ms operations)

        self._create_ui()

    def _create_ui(self) -> None:
        """Create the plot panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Top controls row
        controls = QHBoxLayout()

        # Data series checkboxes
        for name, color, _ in self.SERIES_CONFIG:
            cb = QCheckBox(name)
            cb.setStyleSheet(f"QCheckBox {{ color: {color}; font-weight: bold; }}")
            cb.setChecked(name == "Voltage")  # Default to Voltage only
            cb.toggled.connect(lambda checked, n=name: self._on_series_toggled(n, checked))
            controls.addWidget(cb)
            self._checkboxes[name] = cb
            self._visible[name] = (name == "Voltage")

        controls.addStretch()

        # X-axis selector
        controls.addWidget(QLabel("X-Axis:"))
        self.x_axis_combo = QComboBox()
        self.x_axis_combo.addItems(["Time", "Voltage", "Current", "Power", "Load R", "Battery R", "Capacity", "Energy"])
        self.x_axis_combo.setCurrentText("Time")
        self.x_axis_combo.currentTextChanged.connect(self._on_x_axis_changed)
        controls.addWidget(self.x_axis_combo)

        # Time window selector (only active when X-Axis is Time)
        controls.addWidget(QLabel("Time Span:"))
        self.time_window_combo = QComboBox()
        self.time_window_combo.addItems([
            "Full",
            "30s",
            "1m",
            "5m",
            "10m",
            "30m",
            "1h",
            "2h",
            "5h",
            "10h",
            "24h",
        ])
        self.time_window_combo.setCurrentText("Full")
        self.time_window_combo.currentTextChanged.connect(self._on_time_window_changed)
        controls.addWidget(self.time_window_combo)

        layout.addLayout(controls)

        # Configure pyqtgraph
        pg.setConfigOptions(antialias=True)

        # Create plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#1a1a1a")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel("bottom", "Time (seconds)")

        layout.addWidget(self.plot_widget)

        # Time scroll bar (handle width represents visible window ratio)
        self.time_scroll_slider = QScrollBar(Qt.Horizontal)
        self.time_scroll_slider.setMinimum(0)
        self.time_scroll_slider.setMaximum(1000)  # Use 1000 steps for smooth scrolling
        self.time_scroll_slider.setPageStep(100)  # Initial page step (will be updated)
        self.time_scroll_slider.setValue(1000)  # Default to end (most recent)
        self.time_scroll_slider.setEnabled(False)  # Disabled until time window is selected
        self.time_scroll_slider.valueChanged.connect(self._on_time_scroll_changed)
        layout.addWidget(self.time_scroll_slider)

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

    def _on_x_axis_changed(self, param_name: str) -> None:
        """Handle X-axis parameter selection change."""
        self._x_axis_param = param_name

        # Enable/disable time controls based on selection
        is_time = (param_name == "Time")
        self.time_window_combo.setEnabled(is_time)

        if not is_time:
            # Disable time scrolling when using parameter as x-axis
            self.time_scroll_slider.setEnabled(False)

        # Update axis label (will be refined in _update_plots with scaled units)
        if is_time:
            self._update_time_axis_label()
        else:
            # Get unit for selected parameter
            param_unit = ""
            for name, _, unit in self.SERIES_CONFIG:
                if name == param_name:
                    param_unit = unit
                    break
            # This is a placeholder - actual scaled unit will be set in _update_plots
            self.plot_widget.setLabel("bottom", f"{param_name} ({param_unit})")

        # Redraw plot with new x-axis
        self._update_plots()

    def _on_time_window_changed(self, window_text: str) -> None:
        """Handle time window selection change."""
        # Get current view range to preserve left edge
        current_x_min = None
        if len(self._time_data) > 0:
            view_range = self.main_vb.viewRange()
            current_x_min = view_range[0][0]  # Current left edge of view

        # Parse window text to seconds
        if window_text == "Full":
            self._time_window_seconds = None
            self.time_scroll_slider.setEnabled(False)
            self._time_scroll_position = 1.0
        else:
            # Parse time window (e.g., "30s" -> 30, "1m" -> 60, "2h" -> 7200)
            if window_text.endswith("s"):
                seconds = int(window_text[:-1])
                self._time_window_seconds = seconds
            elif window_text.endswith("m"):
                minutes = int(window_text[:-1])
                self._time_window_seconds = minutes * 60
            elif window_text.endswith("h"):
                hours = int(window_text[:-1])
                self._time_window_seconds = hours * 3600
            else:
                self._time_window_seconds = None

            # Calculate scroll position to preserve left edge if we have data
            if current_x_min is not None and len(self._time_data) > 0:
                time_array = np.array(self._time_data)
                # Convert current_x_min back to raw time (undo display scaling)
                max_time = time_array[-1]
                if max_time < 120:
                    raw_x_min = current_x_min  # seconds
                elif max_time < 7200:
                    raw_x_min = current_x_min * 60.0  # minutes -> seconds
                else:
                    raw_x_min = current_x_min * 3600.0  # hours -> seconds

                # Calculate what scroll position gives us this x_min
                total_duration = time_array[-1] - time_array[0]
                if total_duration > self._time_window_seconds:
                    # Clamp raw_x_min to valid range
                    raw_x_min = max(time_array[0], min(raw_x_min, time_array[-1] - self._time_window_seconds))
                    window_start_offset = raw_x_min - time_array[0]
                    self._time_scroll_position = window_start_offset / (total_duration - self._time_window_seconds)
                    self._time_scroll_position = max(0.0, min(1.0, self._time_scroll_position))
                else:
                    self._time_scroll_position = 0.0

                self.time_scroll_slider.blockSignals(True)
                self.time_scroll_slider.setValue(int(self._time_scroll_position * 1000))
                self.time_scroll_slider.blockSignals(False)
            else:
                # No data yet or first time - default to end (most recent)
                self._time_scroll_position = 1.0
                self.time_scroll_slider.setValue(1000)

            # Enable slider if window is selected
            self.time_scroll_slider.setEnabled(self._time_window_seconds is not None)

        self._update_plots()

    def _on_time_scroll_changed(self, value: int) -> None:
        """Handle time scroll slider change."""
        # Convert slider value (0-1000) to position (0.0-1.0)
        self._time_scroll_position = value / 1000.0
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
        self._data["Load R"].append(status.resistance_ohm)
        self._data["Battery R"].append(status.calculated_battery_resistance_ohm)
        self._data["MOSFET Temp"].append(status.temperature_c)
        self._data["Ext Temp"].append(status.ext_temperature_c)
        self._data["Capacity"].append(status.capacity_mah)
        self._data["Energy"].append(status.energy_wh)

        # If scroll position is at the end (1.0), keep it there for auto-scroll
        # Otherwise, maintain current position (don't auto-scroll)
        if self._time_scroll_position >= 0.99:  # Close to 1.0 to account for rounding
            self._time_scroll_position = 1.0
            self.time_scroll_slider.blockSignals(True)
            self.time_scroll_slider.setValue(1000)
            self.time_scroll_slider.blockSignals(False)

        # Throttle plot updates to reduce rendering overhead (23-50ms per update)
        # Only update every N data points (default: every 2 points = 0.5 Hz instead of 1 Hz)
        self._plot_update_counter += 1
        if self._plot_update_counter >= self._plot_update_interval:
            self._plot_update_counter = 0
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

    def load_readings(self, readings: list) -> None:
        """Load a list of Reading objects for display.

        Args:
            readings: List of Reading objects from a loaded session
        """
        self.clear_data()

        for reading in readings:
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

        # Reset scroll position to left (start at time 0)
        self._time_scroll_position = 0.0
        self.time_scroll_slider.blockSignals(True)
        self.time_scroll_slider.setValue(0)
        self.time_scroll_slider.blockSignals(False)

        # Reset the exceeded window flag
        self._data_exceeded_window = False

        self._update_plots()

    def get_elapsed_time(self) -> float:
        """Get elapsed time from first to last data point in seconds."""
        if not self._time_data or len(self._time_data) < 1:
            return 0.0
        # Time data is relative to start, so last value is the elapsed time
        return self._time_data[-1]

    def get_points_count(self) -> int:
        """Get the number of data points."""
        return len(self._time_data)

    def set_show_points(self, show: bool) -> None:
        """Toggle visibility of point markers on curves."""
        self._show_points = show
        for name, color, _ in self.SERIES_CONFIG:
            curve = self._curves.get(name)
            if curve:
                if show:
                    curve.setSymbol('o')
                    curve.setSymbolSize(5)
                    curve.setSymbolBrush(color)
                else:
                    curve.setSymbol(None)

    def _update_time_axis_label(self) -> None:
        """Update the X-axis label with appropriate time units."""
        # Only update if using Time as x-axis
        if self._x_axis_param != "Time":
            return

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

        # Determine X-axis data
        if self._x_axis_param == "Time":
            # Use time as x-axis (default behavior)
            time_raw = np.array(self._time_data)
            time_masked = time_raw

            # Convert time to appropriate display units
            max_time_val = time_masked[-1] if len(time_masked) > 0 else 0
            if max_time_val < 120:
                x_display = time_masked  # seconds
            elif max_time_val < 7200:
                x_display = time_masked / 60.0  # minutes
            else:
                x_display = time_masked / 3600.0  # hours
        else:
            # Use a parameter as x-axis
            if self._x_axis_param in self._data:
                x_raw = np.array(self._data[self._x_axis_param])
                if len(x_raw) == 0:
                    x_display = np.array([])
                else:
                    # Get unit scale for x-axis parameter
                    x_unit = ""
                    for name, _, unit in self.SERIES_CONFIG:
                        if name == self._x_axis_param:
                            x_unit = unit
                            break

                    x_max = np.max(x_raw) if len(x_raw) > 0 else 0
                    x_scale, x_display_unit = _get_unit_scale(x_max, x_unit)
                    x_display = x_raw * x_scale

                    # Update x-axis label with scaled unit
                    self.plot_widget.setLabel("bottom", f"{self._x_axis_param} ({x_display_unit})")
            else:
                x_display = np.array([])

        if len(x_display) == 0:
            for name in self._curves:
                self._curves[name].setData([], [])
            return

        # Update each series
        for name, _, base_unit in self.SERIES_CONFIG:
            data = np.array(self._data[name])

            if not self._visible.get(name, False) or len(data) == 0:
                self._curves[name].setData([], [])
                continue

            # Determine unit scaling for nice integer display
            if len(data) > 0:
                y_max = np.max(data)
                scale, display_unit = _get_unit_scale(y_max, base_unit)

                # Scale the data
                scaled_data = data * scale

                self._curves[name].setData(x_display, scaled_data)

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
                self._curves[name].setData(x_display, data)

        # Set X-axis range
        if self._x_axis_param != "Time":
            # For parameter-based x-axis, auto-scale to show all data with nice bounds
            if len(x_display) > 0:
                x_min_raw = np.min(x_display)
                x_max_raw = np.max(x_display)
                x_min, x_max = _nice_range_bounds(x_min_raw, x_max_raw)
                self.main_vb.setXRange(x_min, x_max, padding=0)
        elif len(x_display) > 0:
            # Time-based x-axis with window controls
            total_duration = x_display[-1] - x_display[0]
            max_time_val = np.array(self._time_data)[-1] if len(self._time_data) > 0 else 0

            if self._time_window_seconds is not None:
                # Convert window to display units
                if max_time_val < 120:
                    window_display = self._time_window_seconds
                elif max_time_val < 7200:
                    window_display = self._time_window_seconds / 60.0
                else:
                    window_display = self._time_window_seconds / 3600.0

                if total_duration > window_display:
                    # Enable slider if data exceeds window
                    if not self.time_scroll_slider.isEnabled():
                        self.time_scroll_slider.setEnabled(True)

                    # Detect transition: data just exceeded window size
                    # Switch to auto-scroll mode (position 1.0) if we haven't scrolled manually yet
                    if not self._data_exceeded_window and self._time_scroll_position <= 0.01:
                        self._data_exceeded_window = True
                        self._time_scroll_position = 1.0
                        self.time_scroll_slider.blockSignals(True)
                        self.time_scroll_slider.setValue(1000)
                        self.time_scroll_slider.blockSignals(False)

                    # Set scrollbar page step to represent visible window ratio
                    # Page step = (window / total) * range
                    ratio = window_display / total_duration
                    page_step = max(1, int(ratio * 1000))  # At least 1
                    self.time_scroll_slider.blockSignals(True)
                    self.time_scroll_slider.setPageStep(page_step)
                    self.time_scroll_slider.blockSignals(False)

                    # Calculate window position based on scroll position
                    # scroll_position: 0.0 = start, 1.0 = end (most recent)
                    window_start_offset = (total_duration - window_display) * self._time_scroll_position
                    x_min = x_display[0] + window_start_offset
                    x_max = x_min + window_display

                    # Set X range for all viewboxes
                    self.main_vb.setXRange(x_min, x_max, padding=0)
                else:
                    # Data is smaller than window - still show full window
                    # Disable slider since we can't scroll
                    if self.time_scroll_slider.isEnabled():
                        self.time_scroll_slider.setEnabled(False)

                    # Mark that we haven't exceeded window yet
                    self._data_exceeded_window = False

                    # Set scrollbar page step to 100% (full width handle)
                    self.time_scroll_slider.blockSignals(True)
                    self.time_scroll_slider.setPageStep(1000)
                    self.time_scroll_slider.blockSignals(False)

                    # Position window based on scroll position
                    # At position 1.0 (right), data appears on right side with empty space on left
                    # At position 0.0 (left), data appears on left side with empty space on right
                    if self._time_scroll_position >= 0.99:
                        # Right-aligned: show [data_end - window, data_end]
                        x_max = x_display[-1]
                        x_min = x_max - window_display
                    else:
                        # Left-aligned or middle: show [data_start, data_start + window]
                        x_min = x_display[0]
                        x_max = x_min + window_display

                    self.main_vb.setXRange(x_min, x_max, padding=0)
            else:
                # Full mode - show all data and disable slider
                if self.time_scroll_slider.isEnabled():
                    self.time_scroll_slider.setEnabled(False)
                self.main_vb.setXRange(x_display[0], x_display[-1], padding=0.02)

        self._update_time_axis_label()
