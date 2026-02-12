"""Seaborn-based plot panel for Test Viewer - publication-quality plots."""

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QLabel, QComboBox
from PySide6.QtCore import Qt
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
import seaborn as sns


class SeabornPlotPanel(QWidget):
    """Plot panel using matplotlib + seaborn for beautiful plots."""

    # Available parameters to plot
    PARAMETERS = [
        "Voltage",
        "Current",
        "Power",
        "Capacity",
        "Energy",
        "R Load",
        "Temp MOSFET",
    ]

    # Available x-axis options
    X_AXIS_OPTIONS = [
        "Time",
        "Current",
        "Power",
        "R Load",
        "Capacity",
        "Energy",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        # Set seaborn style
        sns.set_style("whitegrid")
        sns.set_context("notebook", font_scale=1.1)

        # Data storage
        self._dataframe = None
        self._device_colors = {}
        self._enabled_params = set()
        self._x_axis = "Time"  # Default x-axis
        self._current_test_type = None

        # State storage per test type
        self._test_type_states = {
            'battery_capacity': {'x_axis': 'Time', 'y_params': {'Voltage'}},
            'battery_load': {'x_axis': 'Current', 'y_params': {'Voltage'}},
            'battery_charger': {'x_axis': 'Time', 'y_params': {'Voltage', 'Current'}},
            'cable_resistance': {'x_axis': 'Current', 'y_params': {'Voltage'}},
            'charger': {'x_axis': 'Current', 'y_params': {'Voltage'}},
            'power_bank': {'x_axis': 'Time', 'y_params': {'Voltage', 'Current'}},
        }

        self._create_ui()

    def _create_ui(self):
        """Create the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Controls layout
        controls_layout = QHBoxLayout()

        # X-axis selection
        controls_layout.addWidget(QLabel("X-axis:"))
        self.x_axis_combo = QComboBox()
        self.x_axis_combo.addItems(self.X_AXIS_OPTIONS)
        self.x_axis_combo.setCurrentText("Time")
        self.x_axis_combo.currentTextChanged.connect(self._on_x_axis_changed)
        controls_layout.addWidget(self.x_axis_combo)

        controls_layout.addSpacing(20)

        # Parameter selection checkboxes
        controls_layout.addWidget(QLabel("Y-axis:"))

        self._param_checkboxes = {}
        for i, param in enumerate(self.PARAMETERS):
            cb = QCheckBox(param)

            # Enable Voltage by default (before connecting signal)
            if param == "Voltage":
                cb.setChecked(True)
                self._enabled_params.add(param)

            # Connect signal AFTER setting initial state
            cb.stateChanged.connect(lambda state, p=param: self._on_param_toggled(p, state))

            controls_layout.addWidget(cb)
            self._param_checkboxes[param] = cb

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        # Create matplotlib figure
        self.figure = Figure(figsize=(12, 6), facecolor='white')
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas)

        # Create initial empty plot
        self._update_plot()

    def _on_param_toggled(self, param: str, state: int):
        """Handle parameter checkbox toggle."""
        if state == Qt.CheckState.Checked.value:
            self._enabled_params.add(param)
        else:
            self._enabled_params.discard(param)
        self._save_current_state()
        self._update_plot()

    def _on_x_axis_changed(self, x_axis: str):
        """Handle x-axis selection change."""
        self._x_axis = x_axis
        self._save_current_state()
        self._update_plot()

    def set_test_type(self, test_type: str):
        """Set the current test type and restore its settings."""
        self._current_test_type = test_type
        self._restore_state_for_test_type(test_type)

    def _save_current_state(self):
        """Save current plot settings for the current test type."""
        if self._current_test_type:
            self._test_type_states[self._current_test_type] = {
                'x_axis': self._x_axis,
                'y_params': self._enabled_params.copy()
            }

    def _restore_state_for_test_type(self, test_type: str):
        """Restore plot settings for a specific test type."""
        if test_type not in self._test_type_states:
            # Use default state if not found
            self._test_type_states[test_type] = {'x_axis': 'Time', 'y_params': {'Voltage'}}

        state = self._test_type_states[test_type]

        # Restore x-axis
        self._x_axis = state['x_axis']
        self.x_axis_combo.blockSignals(True)
        self.x_axis_combo.setCurrentText(self._x_axis)
        self.x_axis_combo.blockSignals(False)

        # Restore y-axis parameters
        self._enabled_params = state['y_params'].copy()
        for param, checkbox in self._param_checkboxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(param in self._enabled_params)
            checkbox.blockSignals(False)

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

    def _update_plot(self):
        """Update the plot with current data and settings."""
        self.figure.clear()

        if self._dataframe is None or self._dataframe.empty:
            self.canvas.draw()
            return

        if not self._enabled_params:
            # No parameters selected, show message
            ax = self.figure.add_subplot(111)
            ax.text(0.5, 0.5, 'Select parameters to plot',
                   ha='center', va='center', fontsize=14, color='gray')
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis('off')
            self.canvas.draw()
            return

        # Create subplots based on number of enabled parameters
        n_params = len(self._enabled_params)

        # Create axes
        axes = []
        for i, param in enumerate(sorted(self._enabled_params)):
            if i == 0:
                ax = self.figure.add_subplot(n_params, 1, i + 1)
            else:
                # Share x-axis with first plot
                ax = self.figure.add_subplot(n_params, 1, i + 1, sharex=axes[0])
            axes.append(ax)

        # Plot each device
        device_names = self._dataframe['Device'].unique()

        for ax, param in zip(axes, sorted(self._enabled_params)):
            for device_name in device_names:
                device_df = self._dataframe[self._dataframe['Device'] == device_name]
                color = self._device_colors.get(device_name, '#1f77b4')

                # Plot with seaborn style using selected x-axis
                ax.plot(device_df[self._x_axis], device_df[param],
                       label=device_name, color=color, linewidth=2, alpha=0.8)

            # Styling
            ax.set_ylabel(self._get_parameter_label(param), fontsize=11, fontweight='bold')
            ax.grid(True, alpha=0.3)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)

            # Use nice round numbers for y-axis (multiples of 1, 2, 5)
            ax.yaxis.set_major_locator(MaxNLocator(nbins='auto', steps=[1, 2, 5, 10]))

            # Only show legend on first subplot
            if ax == axes[0]:
                ax.legend(loc='best', frameon=True, fancybox=True,
                         shadow=True, ncol=min(3, len(device_names)))

            # Only show x-label on bottom subplot
            if ax == axes[-1]:
                ax.set_xlabel(self._get_parameter_label(self._x_axis), fontsize=11, fontweight='bold')
            else:
                ax.tick_params(labelbottom=False)

        # Adjust layout
        self.figure.tight_layout()
        self.canvas.draw()

    def _get_parameter_label(self, param: str) -> str:
        """Get formatted parameter label with units."""
        labels = {
            "Voltage": "Voltage (V)",
            "Current": "Current (A)",
            "Power": "Power (W)",
            "Capacity": "Capacity (mAh)",
            "Energy": "Energy (Wh)",
            "R Load": "Load Resistance (Ω)",
            "Temp MOSFET": "MOSFET Temp (°C)",
        }
        return labels.get(param, param)
