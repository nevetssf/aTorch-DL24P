"""Seaborn-based plot panel for Test Viewer - publication-quality plots."""

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QWidget, QVBoxLayout
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
import seaborn as sns


class SeabornPlotPanel(QWidget):
    """Plot panel using matplotlib + seaborn for beautiful plots.

    This is a rendering-only panel that accepts plot settings externally
    via update_plot_settings(). It does not contain any UI controls.
    """

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
    ]

    # Available x-axis options (includes Time plus all plottable parameters)
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
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        # Set seaborn style
        sns.set_style("whitegrid")
        sns.set_context("notebook", font_scale=1.1)

        # Data storage
        self._dataframe = None
        self._device_colors = {}
        self._x_axis = "Time"  # Default x-axis
        self._x_axis_reversed = False  # Reverse X-axis direction
        self._y1_param = "Voltage"  # Default Y1 parameter
        self._y2_param = "Current"  # Default Y2 parameter
        self._y2_enabled = False  # Y2 disabled by default
        self._normalize_enabled = False  # Normalize to percentage by default
        self._drop_first_n = 0  # Drop first N points when plotting
        self._drop_last_n = 1   # Drop last N points when plotting

        self._create_ui()

    def _create_ui(self):
        """Create the UI - canvas only, no controls."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create matplotlib figure
        self.figure = Figure(figsize=(12, 6), facecolor='white')
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas)

        # Create initial empty plot
        self._update_plot()

    def update_plot_settings(self, x_axis: str, x_reversed: bool, y1: str, y2: str,
                             y2_enabled: bool, normalize: bool, drop_first: int, drop_last: int):
        """Update plot settings and redraw.

        Args:
            x_axis: X-axis parameter (e.g., "Time", "Current")
            x_reversed: Whether to reverse X-axis direction
            y1: Y1 (left axis) parameter (e.g., "Voltage")
            y2: Y2 (right axis) parameter (e.g., "Current")
            y2_enabled: Whether to show Y2 axis
            normalize: Whether to normalize Y-axes to 0-100%
            drop_first: Number of first points to drop
            drop_last: Number of last points to drop
        """
        self._x_axis = x_axis
        self._x_axis_reversed = x_reversed
        self._y1_param = y1
        self._y2_param = y2
        self._y2_enabled = y2_enabled
        self._normalize_enabled = normalize
        self._drop_first_n = drop_first
        self._drop_last_n = drop_last
        self._update_plot()

    def load_grouped_dataset(self, df: pd.DataFrame, device_colors: dict) -> None:
        """Load a grouped dataset from a DataFrame with Device column.

        Args:
            df: pandas DataFrame with columns: Device, Time, Voltage, Current, etc.
            device_colors: Dictionary mapping device names to QColor objects
        """
        # Convert QColor to matplotlib color format
        self._device_colors = {}
        for device_name, qcolor in device_colors.items():
            # Convert QColor to hex string
            color_hex = f"#{qcolor.red():02x}{qcolor.green():02x}{qcolor.blue():02x}"
            self._device_colors[device_name] = color_hex

        self._dataframe = df
        self._update_plot()

    def clear_all_datasets(self):
        """Clear all datasets."""
        self._dataframe = None
        self._device_colors = {}
        self._update_plot()

    def set_drop_points(self, drop_first: int, drop_last: int):
        """Set how many first/last points to drop from plot."""
        self._drop_first_n = drop_first
        self._drop_last_n = drop_last
        self._update_plot()  # Immediately redraw

    def _get_time_scale(self, max_time_seconds: float) -> tuple:
        """Determine appropriate time unit and scale factor.

        Returns:
            tuple: (scale_factor, unit_label)
        """
        if max_time_seconds < 120:  # Less than 2 minutes
            return 1.0, "Time (s)"
        elif max_time_seconds < 7200:  # Less than 2 hours
            return 1/60, "Time (min)"
        else:  # 2 hours or more
            return 1/3600, "Time (h)"

    def _update_plot(self):
        """Update the plot with current data and settings - single plot with dual y-axes."""
        self.figure.clear()

        if self._dataframe is None or self._dataframe.empty:
            self.canvas.draw()
            return

        # Create single plot
        ax1 = self.figure.add_subplot(111)

        device_names = self._dataframe['Device'].unique()

        # Determine time scaling if X-axis is Time
        time_scale = 1.0
        x_axis_label = self._get_parameter_label(self._x_axis)
        if self._x_axis == "Time" and not self._dataframe.empty:
            max_time = self._dataframe['Time'].max()
            time_scale, x_axis_label = self._get_time_scale(max_time)

        # Plot Y1 parameter on left axis (solid line)
        for device_name in device_names:
            device_df = self._dataframe[self._dataframe['Device'] == device_name].copy()

            # Apply drop first/last filtering
            total_points = len(device_df)
            if total_points > 1:  # Only filter if we have more than 1 point
                drop_first = min(self._drop_first_n, total_points - 1)
                drop_last = min(self._drop_last_n, total_points - drop_first - 1)

                if drop_first > 0 or drop_last > 0:
                    # Use iloc to drop first and last rows
                    end_idx = total_points - drop_last if drop_last > 0 else total_points
                    device_df = device_df.iloc[drop_first:end_idx]

            color = self._device_colors.get(device_name, '#1f77b4')

            # Get X data and apply time scaling if needed
            x_data = device_df[self._x_axis] * time_scale

            # Get Y1 data and normalize if enabled (per-curve normalization)
            y1_data = device_df[self._y1_param]
            if self._normalize_enabled:
                y1_max = y1_data.max()
                if y1_max > 0:
                    y1_data = (y1_data / y1_max) * 100

            # Plot Y1 with solid line
            ax1.plot(x_data, y1_data,
                    label=device_name, color=color, linewidth=2, alpha=0.8,
                    linestyle='-')

        # Style left axis (Y1)
        ax1.set_xlabel(x_axis_label, fontsize=11, fontweight='bold')
        y1_label = self._get_parameter_label(self._y1_param)
        if self._normalize_enabled:
            y1_label = f"{self._y1_param} (%)"
        ax1.set_ylabel(y1_label, fontsize=11, fontweight='bold', color='black')
        ax1.tick_params(axis='y', labelcolor='black')
        ax1.grid(True, alpha=0.3)
        ax1.spines['top'].set_visible(False)

        # Use nice round numbers for y-axis
        ax1.yaxis.set_major_locator(MaxNLocator(nbins='auto', steps=[1, 2, 5, 10]))

        # Add horizontal reference lines when normalized
        if self._normalize_enabled:
            for level in [20, 50, 80]:
                ax1.axhline(y=level, color='lightgray', linestyle=':', linewidth=1, alpha=0.6)
            # Set Y-axis range to 0-100% when normalized (with padding to avoid clipping)
            ax1.set_ylim(-2, 105)

        # Add legend for devices (outside plot on right, vertical layout)
        ax1.legend(loc='center left', bbox_to_anchor=(1.02, 0.5),
                  frameon=True, fancybox=True, shadow=True)

        # Reverse X-axis if enabled
        if self._x_axis_reversed:
            ax1.invert_xaxis()

        # Plot Y2 parameter on right axis if enabled (dashed line)
        if self._y2_enabled:
            ax2 = ax1.twinx()  # Create second y-axis sharing x-axis

            for device_name in device_names:
                device_df = self._dataframe[self._dataframe['Device'] == device_name].copy()

                # Apply drop first/last filtering (same as Y1)
                total_points = len(device_df)
                if total_points > 1:  # Only filter if we have more than 1 point
                    drop_first = min(self._drop_first_n, total_points - 1)
                    drop_last = min(self._drop_last_n, total_points - drop_first - 1)

                    if drop_first > 0 or drop_last > 0:
                        # Use iloc to drop first and last rows
                        end_idx = total_points - drop_last if drop_last > 0 else total_points
                        device_df = device_df.iloc[drop_first:end_idx]

                color = self._device_colors.get(device_name, '#1f77b4')

                # Get X data and apply time scaling if needed
                x_data = device_df[self._x_axis] * time_scale

                # Get Y2 data and normalize if enabled (per-curve normalization)
                y2_data = device_df[self._y2_param]
                if self._normalize_enabled:
                    y2_max = y2_data.max()
                    if y2_max > 0:
                        y2_data = (y2_data / y2_max) * 100

                # Plot Y2 with dashed line
                ax2.plot(x_data, y2_data,
                        color=color, linewidth=2, alpha=0.8,
                        linestyle='--')

            # Style right axis (Y2)
            y2_label = self._get_parameter_label(self._y2_param)
            if self._normalize_enabled:
                y2_label = f"{self._y2_param} (%)"
            ax2.set_ylabel(y2_label, fontsize=11, fontweight='bold', color='black')
            ax2.tick_params(axis='y', labelcolor='black')
            ax2.spines['top'].set_visible(False)
            ax2.yaxis.set_major_locator(MaxNLocator(nbins='auto', steps=[1, 2, 5, 10]))
            # Set Y-axis range to 0-100% when normalized (with padding to avoid clipping)
            if self._normalize_enabled:
                ax2.set_ylim(-2, 105)
        else:
            # Hide right spine if Y2 is not enabled
            ax1.spines['right'].set_visible(False)

        # Adjust layout
        self.figure.tight_layout()
        self.canvas.draw()

    def _get_parameter_label(self, param: str) -> str:
        """Get formatted parameter label with units."""
        labels = {
            "Time": "Time (s)",
            "Voltage": "Voltage (V)",
            "Current": "Current (A)",
            "Power": "Power (W)",
            "Capacity": "Capacity (mAh)",
            "Capacity Remaining": "Capacity Remaining (mAh)",
            "Energy": "Energy (Wh)",
            "Energy Remaining": "Energy Remaining (Wh)",
            "R Load": "Load Resistance (Ω)",
            "Temp MOSFET": "MOSFET Temp (°C)",
        }
        return labels.get(param, param)
