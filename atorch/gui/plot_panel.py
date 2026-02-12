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
        ("Voltage", "#FFC107", "V"),            # Amber - warm yellow
        ("Current", "#29B6F6", "A"),            # Light blue - cool
        ("Power", "#EF5350", "W"),              # Red - attention
        ("R Load", "#66BB6A", "Ω"),             # Green - resistance
        ("R Battery", "#5C6BC0", "Ω"),          # Indigo - internal resistance
        ("Temp MOSFET", "#26A69A", "°C"),       # Teal - blue-green
        ("Temp External", "#9CCC65", "°C"),     # Light green - yellow-green
        ("Capacity", "#AB47BC", "mAh"),         # Purple - distinct
        ("Energy", "#FF7043", "Wh"),            # Deep orange - warm
    ]

    # Axis slot names
    AXIS_SLOTS = ["Y", "Y1", "Y2", "Y3"]

    def __init__(self, max_points: int = 3600):
        super().__init__()

        self.max_points = max_points

        # Data storage (single-dataset mode for Test Bench streaming)
        self._time_data: deque = deque(maxlen=max_points)
        self._data = {name: deque(maxlen=max_points) for name, _, _ in self.SERIES_CONFIG}

        # Start time for relative time calculation
        self._start_time: Optional[float] = None

        # Multi-dataset storage (for Test Viewer)
        # Format: {dataset_id: {'times': array, 'data': {param: array}, 'color': QColor, 'label': str}}
        self._datasets = {}
        self._dataset_curves = {}  # {dataset_id: {slot: PlotDataItem}}
        self._legend = None  # pg.LegendItem, created when needed

        # Axis-centric UI elements (4 fixed axis slots)
        self._axis_dropdowns = {}       # slot → QComboBox
        self._axis_checkboxes = {}      # slot → QCheckBox
        self._axis_selections = {}      # slot → parameter name or None
        self._axis_enabled = {}         # slot → bool
        self._axis_viewboxes = {}       # slot → ViewBox
        self._axis_axes = {}            # slot → AxisItem
        self._axis_curves = {}          # slot → PlotDataItem
        self._display_units = {}        # slot → current display unit
        self._show_points = False       # Whether to show point markers

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

        # Parameter dropdown options: all 9 parameters
        param_options = [name for name, _, _ in self.SERIES_CONFIG]

        # Create 4 axis controls (Y, Y1, Y2, Y3)
        for slot in self.AXIS_SLOTS:
            # Checkbox to enable axis
            cb = QCheckBox(f"{slot}:")
            cb.setChecked(slot == "Y")  # Only Y enabled by default
            cb.setToolTip(f"Enable {slot} axis for plotting additional parameters")
            cb.toggled.connect(lambda checked, s=slot: self._on_axis_enabled_changed(s, checked))
            controls.addWidget(cb)
            self._axis_checkboxes[slot] = cb

            # Dropdown to select parameter
            dropdown = QComboBox()
            dropdown.addItems(param_options)
            if slot == "Y":
                dropdown.setCurrentText("Voltage")
            elif slot == "Y1":
                dropdown.setCurrentText("Current")
            else:
                dropdown.setCurrentText("Voltage")  # Default to Voltage for disabled axes
            dropdown.setToolTip(f"Select parameter to plot on {slot} axis")
            dropdown.currentTextChanged.connect(lambda text, s=slot: self._on_axis_selection_changed(s, text))
            dropdown.setEnabled(cb.isChecked())
            controls.addWidget(dropdown)
            self._axis_dropdowns[slot] = dropdown

            # Initialize state
            self._axis_enabled[slot] = cb.isChecked()
            self._axis_selections[slot] = dropdown.currentText() if cb.isChecked() else None

        controls.addStretch()

        # X-axis selector
        controls.addWidget(QLabel("X"))
        self.x_axis_combo = QComboBox()
        # Use full names in X-axis dropdown
        x_axis_options = ["Time"] + [name for name, _, _ in self.SERIES_CONFIG]
        self.x_axis_combo.addItems(x_axis_options)
        self.x_axis_combo.setCurrentText("Time")
        self.x_axis_combo.setToolTip("Select X-axis parameter (Time for time-series, or other for characteristic curves)")
        self.x_axis_combo.currentTextChanged.connect(self._on_x_axis_changed)
        controls.addWidget(self.x_axis_combo)

        # Time window selector (only active when X-Axis is Time)
        controls.addWidget(QLabel("Time Span"))
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
        self.time_window_combo.setToolTip("Time window to display (Full shows all data)")
        self.time_window_combo.currentTextChanged.connect(self._on_time_window_changed)
        controls.addWidget(self.time_window_combo)

        # Points checkbox
        self.show_points_checkbox = QCheckBox("Points")
        self.show_points_checkbox.setChecked(False)
        self.show_points_checkbox.setToolTip("Show point markers on plot")
        self.show_points_checkbox.toggled.connect(self._on_show_points_toggled)
        controls.addWidget(self.show_points_checkbox)

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
        """Set up the 4 fixed axis slots."""
        # Hide the default right axis - we'll manage our own
        self.plot_item.hideAxis('right')

        # Y axis (left)
        left_axis = self.plot_item.getAxis('left')
        curve = self.plot_item.plot(pen=None)  # Initially no pen (will be set by appearance update)

        # Enable performance optimizations for large datasets
        curve.setDownsampling(auto=True, method='peak')
        curve.setClipToView(True)

        self._axis_viewboxes["Y"] = self.main_vb
        self._axis_axes["Y"] = left_axis
        self._axis_curves["Y"] = curve

        # Y1, Y2, Y3 axes (right)
        right_col = 3  # Start at column 3
        for slot in ["Y1", "Y2", "Y3"]:
            # Create ViewBox
            vb = pg.ViewBox()
            vb.setXLink(self.main_vb)
            self.plot_item.scene().addItem(vb)

            # Create right axis
            axis = pg.AxisItem('right')
            axis.linkToView(vb)
            self.plot_item.layout.addItem(axis, 2, right_col)
            right_col += 1

            # Create curve
            curve = pg.PlotDataItem(pen=None)

            # Enable performance optimizations for large datasets
            curve.setDownsampling(auto=True, method='peak')
            curve.setClipToView(True)

            vb.addItem(curve)

            self._axis_viewboxes[slot] = vb
            self._axis_axes[slot] = axis
            self._axis_curves[slot] = curve

        # Update appearance for all axes based on initial enabled state
        self._update_all_axes_appearance()

        # Set visibility based on enabled state
        for slot in self.AXIS_SLOTS:
            enabled = self._axis_enabled.get(slot, False)
            self._axis_curves[slot].setVisible(enabled)
            self._axis_axes[slot].setVisible(enabled)

    def _on_resize(self) -> None:
        """Handle main viewbox resize - sync all viewboxes."""
        for slot, vb in self._axis_viewboxes.items():
            if vb != self.main_vb:
                vb.setGeometry(self.main_vb.sceneBoundingRect())

    def _on_axis_selection_changed(self, slot: str, param_name: str) -> None:
        """Handle dropdown selection change."""
        # Update selection only if axis is enabled
        if self._axis_enabled.get(slot, False):
            self._axis_selections[slot] = param_name
            self._update_axis_appearance(slot)
            self._update_plots()
        else:
            # If disabled, just update the dropdown but don't apply
            pass

    def _on_axis_enabled_changed(self, slot: str, enabled: bool) -> None:
        """Handle checkbox enable/disable."""
        self._axis_enabled[slot] = enabled
        self._axis_dropdowns[slot].setEnabled(enabled)

        # Update selection based on enabled state
        if enabled:
            # When enabling, use the current dropdown value
            self._axis_selections[slot] = self._axis_dropdowns[slot].currentText()
        else:
            # When disabling, clear selection
            self._axis_selections[slot] = None

        # Update appearance and visibility
        self._update_axis_appearance(slot)

        # Show/hide curve and axis
        self._axis_curves[slot].setVisible(enabled)
        self._axis_axes[slot].setVisible(enabled)

        self._update_plots()

    def _update_axis_appearance(self, slot: str) -> None:
        """Update axis label and color based on selected parameter."""
        param_name = self._axis_selections[slot]
        axis = self._axis_axes[slot]

        if param_name is None:
            axis.setLabel("", color="#999999")
            return

        # Find parameter config
        for name, color, unit in self.SERIES_CONFIG:
            if name == param_name:
                axis.setLabel(name, units=unit, color=color)
                axis.setPen(pg.mkPen(color, width=1))
                axis.setTextPen(pg.mkPen(color))
                # Update curve pen color
                self._axis_curves[slot].setPen(pg.mkPen(color, width=2))
                break

    def _update_all_axes_appearance(self) -> None:
        """Update appearance for all 4 axes."""
        for slot in self.AXIS_SLOTS:
            self._update_axis_appearance(slot)

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

    def _on_show_points_toggled(self, checked: bool) -> None:
        """Handle show points checkbox toggle."""
        self.set_show_points(checked)

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
        self._data["R Load"].append(status.resistance_ohm)
        self._data["R Battery"].append(status.calculated_battery_resistance_ohm)
        self._data["Temp MOSFET"].append(status.mosfet_temp_c)
        self._data["Temp External"].append(status.ext_temp_c)
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
            self._data["R Load"].append(reading.load_r_ohm or 0)
            self._data["R Battery"].append(reading.battery_r_ohm or 0)
            self._data["Temp MOSFET"].append(reading.mosfet_temp_c)
            self._data["Temp External"].append(reading.ext_temp_c)
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
            self._data["R Load"].append(reading.load_r_ohm or 0)
            self._data["R Battery"].append(reading.battery_r_ohm or 0)
            self._data["Temp MOSFET"].append(reading.mosfet_temp_c)
            self._data["Temp External"].append(reading.ext_temp_c)
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

    # Multi-dataset support methods (for Test Viewer)

    def load_grouped_dataset(self, df, device_colors: dict) -> None:
        """Load a grouped dataset from a DataFrame with Device column.

        Args:
            df: pandas DataFrame with columns: Device, Time, Voltage, Current, etc.
            device_colors: Dictionary mapping device names to QColor objects
        """
        import pandas as pd
        from PySide6.QtGui import QColor

        print(f"[PlotPanel] load_grouped_dataset called with {len(df)} rows, {len(df['Device'].unique())} devices")

        # Clear existing datasets first
        self.clear_all_datasets()

        # Group by Device and create separate datasets
        for device_name in df['Device'].unique():
            device_df = df[df['Device'] == device_name]

            # Get color for this device
            color = device_colors.get(device_name, QColor(255, 0, 0))

            # Extract data arrays
            times = device_df['Time'].values
            data_dict = {
                'Voltage': device_df['Voltage'].values,
                'Current': device_df['Current'].values,
                'Power': device_df['Power'].values,
                'Capacity': device_df['Capacity'].values,
                'Energy': device_df['Energy'].values,
                'R Load': device_df['R Load'].values,
                'Temp MOSFET': device_df['Temp MOSFET'].values,
            }

            # Create dataset ID from device name
            dataset_id = f"device_{device_name.replace(' ', '_')}"

            print(f"[PlotPanel] Loading device from table: {device_name} ({len(times)} points)")

            # Use the existing load_dataset method
            self.load_dataset(
                dataset_id=dataset_id,
                times=times.tolist(),
                data_dict={k: v.tolist() for k, v in data_dict.items()},
                color=color,
                label=device_name
            )

        print(f"[PlotPanel] Loaded {len(df['Device'].unique())} devices from grouped dataset")

    def load_dataset(self, dataset_id: str, times: list, data_dict: dict, color: str, label: str) -> None:
        """Load a complete dataset for viewing (Test Viewer mode).

        Args:
            dataset_id: Unique identifier for this dataset
            times: List of time values (elapsed seconds)
            data_dict: Dictionary mapping parameter names to value lists
                      Keys should match SERIES_CONFIG names (e.g., 'Voltage', 'Current')
            color: Hex color string (e.g., '#FF0000') or QColor
            label: Display label for legend (e.g., 'Panasonic NCR18650B')
        """
        from PySide6.QtGui import QColor

        print(f"[PlotPanel] load_dataset called: ID={dataset_id}, label={label}, {len(times)} points")

        # Convert color to QColor if needed
        if isinstance(color, str):
            color = QColor(color)
        elif not isinstance(color, QColor):
            color = QColor(255, 0, 0)  # Default to red

        print(f"[PlotPanel] Color: {color.name()}")

        # Store dataset
        self._datasets[dataset_id] = {
            'times': np.array(times),
            'data': {param: np.array(values) for param, values in data_dict.items()},
            'color': color,
            'label': label
        }

        print(f"[PlotPanel] Dataset stored, total datasets: {len(self._datasets)}")

        # Create curves for this dataset (one per axis slot)
        if dataset_id not in self._dataset_curves:
            self._dataset_curves[dataset_id] = {}

        # Update plots to show new dataset
        print(f"[PlotPanel] Calling _update_plots()")
        self._update_plots()
        print(f"[PlotPanel] _update_plots() completed")

    def remove_dataset(self, dataset_id: str) -> None:
        """Remove a dataset from display.

        Args:
            dataset_id: ID of dataset to remove
        """
        if dataset_id in self._datasets:
            del self._datasets[dataset_id]

        # Remove and clean up curves
        if dataset_id in self._dataset_curves:
            for slot, curve in self._dataset_curves[dataset_id].items():
                vb = self._axis_viewboxes[slot]
                vb.removeItem(curve)
            del self._dataset_curves[dataset_id]

        self._update_plots()

    def clear_all_datasets(self) -> None:
        """Clear all multi-dataset mode data."""
        print(f"[PlotPanel] clear_all_datasets called, clearing {len(self._datasets)} datasets")

        # Remove all curves from all viewboxes
        for dataset_id in list(self._dataset_curves.keys()):
            for slot, curve in self._dataset_curves[dataset_id].items():
                vb = self._axis_viewboxes[slot]
                if curve in vb.addedItems:
                    vb.removeItem(curve)

        self._datasets.clear()
        self._dataset_curves.clear()

        # Remove and recreate legend to ensure clean state
        if self._legend is not None:
            self.plot_item.removeItem(self._legend)
            self._legend = None

        # Clear single-dataset curves too
        for slot in self.AXIS_SLOTS:
            self._axis_curves[slot].setData([], [])

        # Force a plot update
        self._update_plots()

        print(f"[PlotPanel] clear_all_datasets complete")

    def is_multi_dataset_mode(self) -> bool:
        """Check if we're in multi-dataset mode (Test Viewer).

        Returns:
            True if datasets are loaded, False for single-dataset mode (Test Bench)
        """
        return len(self._datasets) > 0

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
        for slot in self.AXIS_SLOTS:
            curve = self._axis_curves.get(slot)
            if curve and self._axis_selections.get(slot):
                # Get color for selected parameter
                param_name = self._axis_selections[slot]
                color = None
                for name, c, _ in self.SERIES_CONFIG:
                    if name == param_name:
                        color = c
                        break

                if show and color:
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
        # Check if we're in multi-dataset mode (Test Viewer)
        if self.is_multi_dataset_mode():
            self._update_multi_dataset_plots()
            return

        # Single-dataset mode (Test Bench) - existing behavior
        if not self._time_data:
            for slot in self._axis_curves:
                self._axis_curves[slot].setData([], [])
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
            for slot in self._axis_curves:
                self._axis_curves[slot].setData([], [])
            return

        # Update each axis slot
        for slot in self.AXIS_SLOTS:
            if not self._axis_enabled.get(slot, False):
                self._axis_curves[slot].setData([], [])
                continue

            param_name = self._axis_selections.get(slot)
            if param_name is None or param_name not in self._data:
                self._axis_curves[slot].setData([], [])
                continue

            # Get parameter config
            _, color, base_unit = next((cfg for cfg in self.SERIES_CONFIG if cfg[0] == param_name), (None, None, None))
            if base_unit is None:
                continue

            # Get data
            data = np.array(self._data[param_name])

            if len(data) == 0:
                self._axis_curves[slot].setData([], [])
                continue

            # Determine unit scaling for nice integer display
            y_max = np.max(data)
            scale, display_unit = _get_unit_scale(y_max, base_unit)

            # Scale the data
            scaled_data = data * scale

            self._axis_curves[slot].setData(x_display, scaled_data)

            # Update axis label if unit changed
            if self._display_units.get(slot) != display_unit:
                self._display_units[slot] = display_unit
                self._axis_axes[slot].setLabel(param_name, units=display_unit, color=color)

            # Auto-range Y using nice integers (min always 0)
            scaled_max = np.max(scaled_data)
            nice_max = _nice_axis_bounds_int(scaled_max)

            vb = self._axis_viewboxes[slot]
            vb.setYRange(0, nice_max, padding=0)

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

    def _update_multi_dataset_plots(self) -> None:
        """Update plots in multi-dataset mode (Test Viewer).

        Each dataset gets its own color, and different parameters use different line styles.
        """
        from PySide6.QtCore import Qt

        print(f"[PlotPanel] _update_multi_dataset_plots called with {len(self._datasets)} datasets")

        # Line styles for different parameters (when multiple Y-axes are enabled)
        LINE_STYLES = [Qt.SolidLine, Qt.DashLine, Qt.DotLine, Qt.DashDotLine, Qt.DashDotDotLine]

        # Hide single-dataset curves
        for slot in self.AXIS_SLOTS:
            self._axis_curves[slot].setData([], [])

        # Always recreate legend to ensure clean state
        if self._legend is not None:
            self.plot_item.removeItem(self._legend)
            self._legend = None

        if not self._datasets:
            print(f"[PlotPanel] No datasets to plot")
            return

        # Create fresh legend - position it better to avoid overlaps
        print(f"[PlotPanel] Creating fresh legend for {len(self._datasets)} datasets")
        self._legend = pg.LegendItem(offset=(10, 10))
        self._legend.setParentItem(self.plot_item.vb)
        # Make legend semi-transparent to see through it
        self._legend.setBrush(pg.mkBrush(0, 0, 0, 150))

        # Find global time range across all datasets
        all_times = []
        for dataset in self._datasets.values():
            if len(dataset['times']) > 0:
                all_times.extend(dataset['times'])

        if not all_times:
            return

        min_time = min(all_times)
        max_time = max(all_times)

        # Convert time to display units
        if max_time < 120:
            time_scale = 1.0
            time_unit = "seconds"
        elif max_time < 7200:
            time_scale = 1.0 / 60.0
            time_unit = "minutes"
        else:
            time_scale = 1.0 / 3600.0
            time_unit = "hours"

        # Update time axis label
        self.plot_widget.setLabel("bottom", f"Time ({time_unit})")

        # Build a mapping of slot -> parameter name for enabled axes
        enabled_params = {}  # slot -> param_name
        for slot in self.AXIS_SLOTS:
            if self._axis_enabled.get(slot, False):
                param = self._axis_selections.get(slot)
                if param:
                    enabled_params[slot] = param

        print(f"[PlotPanel] Enabled axes: {enabled_params}")

        if not enabled_params:
            print(f"[PlotPanel] No axes enabled - returning")
            return

        # Assign line style index based on slot order
        slot_line_styles = {}
        for i, slot in enumerate(self.AXIS_SLOTS):
            slot_line_styles[slot] = LINE_STYLES[i % len(LINE_STYLES)]

        # Track Y-axis ranges for each slot
        slot_y_ranges = {slot: [float('inf'), float('-inf')] for slot in enabled_params}

        # Plot each dataset with varying line widths for distinction
        dataset_index = 0
        for dataset_id, dataset in self._datasets.items():
            times = dataset['times']
            data_dict = dataset['data']
            color = dataset['color']
            label = dataset['label']

            print(f"[PlotPanel] Plotting dataset: {label} ({len(times)} points, color={color.name()})")

            if len(times) == 0:
                print(f"[PlotPanel] Skipping dataset {label} - no time data")
                continue

            # Convert times to display units
            times_display = times * time_scale

            # Ensure we have curves for this dataset
            if dataset_id not in self._dataset_curves:
                self._dataset_curves[dataset_id] = {}

            curves_created = 0

            # Plot on each enabled axis
            for slot, param_name in enabled_params.items():
                if param_name not in data_dict:
                    continue

                values = data_dict[param_name]
                if len(values) == 0 or len(values) != len(times):
                    continue

                # Get or create curve for this dataset/slot combination
                if slot not in self._dataset_curves[dataset_id]:
                    curve = pg.PlotDataItem()
                    curve.setDownsampling(auto=True, method='peak')
                    curve.setClipToView(True)
                    vb = self._axis_viewboxes[slot]
                    vb.addItem(curve)
                    self._dataset_curves[dataset_id][slot] = curve
                else:
                    curve = self._dataset_curves[dataset_id][slot]

                # Get parameter config for unit scaling
                _, _, base_unit = next((cfg for cfg in self.SERIES_CONFIG if cfg[0] == param_name), (None, None, None))
                if base_unit is None:
                    continue

                # Scale values for display
                y_max = np.max(values) if len(values) > 0 else 0
                scale, display_unit = _get_unit_scale(y_max, base_unit)
                values_display = values * scale

                # Update axis label if unit changed
                if self._display_units.get(slot) != display_unit:
                    self._display_units[slot] = display_unit
                    # Get color for this parameter from SERIES_CONFIG
                    param_color = next((cfg[1] for cfg in self.SERIES_CONFIG if cfg[0] == param_name), "#999999")
                    self._axis_axes[slot].setLabel(param_name, units=display_unit, color=param_color)

                # Set curve appearance: dataset color + line style based on slot + varying width
                line_style = slot_line_styles[slot]
                # Alternate line widths: 2, 3, 2, 3, ... for visual distinction
                line_width = 2 + (dataset_index % 2)
                pen = pg.mkPen(color=color.name(), width=line_width, style=line_style)
                curve.setPen(pen)

                # Show points if enabled
                if self._show_points:
                    curve.setSymbol('o')
                    curve.setSymbolSize(5)
                    curve.setSymbolBrush(color)
                else:
                    curve.setSymbol(None)

                # Set data
                curve.setData(times_display, values_display)
                curves_created += 1

                # Track Y range for this slot
                if len(values_display) > 0:
                    y_min_val = np.min(values_display)
                    y_max_val = np.max(values_display)
                    slot_y_ranges[slot][0] = min(slot_y_ranges[slot][0], y_min_val)
                    slot_y_ranges[slot][1] = max(slot_y_ranges[slot][1], y_max_val)
                    print(f"[PlotPanel] {label} on {slot}: Y range {y_min_val:.2f} to {y_max_val:.2f}")

            print(f"[PlotPanel] Dataset {label}: created {curves_created} curves on enabled axes")

            # Add to legend (one entry per dataset, using first enabled slot's curve)
            first_slot = list(enabled_params.keys())[0]
            if first_slot in self._dataset_curves[dataset_id]:
                curve = self._dataset_curves[dataset_id][first_slot]
                self._legend.addItem(curve, label)
                print(f"[PlotPanel] Added legend entry: {label} (using {first_slot} axis)")

            dataset_index += 1

        # Set Y ranges for each slot (auto-scale with nice bounds)
        for slot, (y_min, y_max) in slot_y_ranges.items():
            if y_min != float('inf') and y_max != float('-inf'):
                nice_min, nice_max = _nice_range_bounds(y_min, y_max)
                vb = self._axis_viewboxes[slot]
                vb.setYRange(nice_min, nice_max, padding=0)

        # Set X range (show all data)
        x_min_display = min_time * time_scale
        x_max_display = max_time * time_scale
        self.main_vb.setXRange(x_min_display, x_max_display, padding=0.02)

        print(f"[PlotPanel] Multi-dataset plot complete: {len(self._datasets)} datasets, X range: {x_min_display:.1f} to {x_max_display:.1f} {time_unit}")
