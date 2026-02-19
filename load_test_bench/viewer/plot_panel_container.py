"""Container for plot panels with unified controls and mode selector."""

import pandas as pd
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QStackedWidget
from PySide6.QtCore import Qt

from .plot_controls_panel import PlotControlsPanel
from .seaborn_plot_panel import SeabornPlotPanel
from .plotly_plot_panel import PlotlyPlotPanel


class PlotPanelContainer(QWidget):
    """Container widget with unified controls for both Seaborn and Plotly rendering."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Current render mode
        self._render_mode = "Interactive"  # "Bitmap" or "Interactive"

        # Current test type
        self._current_test_type = None
        self._drop_first_n = 0
        self._drop_last_n = 1

        # State storage per test type
        self._test_type_states = {
            'battery_capacity': {'x_axis': 'Voltage', 'x_reversed': True, 'y1': 'Energy Remaining', 'y2': 'Current', 'y2_enabled': False, 'normalize': False, 'show_lines': True, 'show_points': False},
            'battery_load': {'x_axis': 'Current', 'x_reversed': False, 'y1': 'Voltage', 'y2': 'Power', 'y2_enabled': False, 'normalize': False, 'show_lines': True, 'show_points': False},
            'battery_charger': {'x_axis': 'Voltage', 'x_reversed': False, 'y1': 'Current', 'y2': 'Power', 'y2_enabled': False, 'normalize': False, 'show_lines': True, 'show_points': True},
            'charger': {'x_axis': 'Current', 'x_reversed': False, 'y1': 'Voltage', 'y2': 'Power', 'y2_enabled': False, 'normalize': False, 'show_lines': True, 'show_points': False},
            'power_bank': {'x_axis': 'Time', 'x_reversed': False, 'y1': 'Voltage', 'y2': 'Current', 'y2_enabled': True, 'normalize': False, 'show_lines': True, 'show_points': False},
        }

        self._create_ui()

    def _create_ui(self):
        """Create the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Top row: Controls and mode selector
        top_layout = QHBoxLayout()

        # Plot controls
        self.controls = PlotControlsPanel()
        self.controls.x_axis_changed.connect(self._on_setting_changed)
        self.controls.x_reverse_changed.connect(self._on_setting_changed)
        self.controls.y1_changed.connect(self._on_setting_changed)
        self.controls.y2_changed.connect(self._on_setting_changed)
        self.controls.y2_enabled_changed.connect(self._on_setting_changed)
        self.controls.normalize_changed.connect(self._on_setting_changed)
        self.controls.show_lines_changed.connect(self._on_setting_changed)
        self.controls.show_points_changed.connect(self._on_setting_changed)
        top_layout.addWidget(self.controls, stretch=1)

        top_layout.addSpacing(20)

        # Mode selector
        top_layout.addWidget(QLabel("Render:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Bitmap", "Interactive"])
        self.mode_combo.setCurrentText(self._render_mode)
        self.mode_combo.setToolTip("Bitmap: High-quality static plots (Seaborn)\nInteractive: Zoomable, hoverable plots (Plotly)")
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        top_layout.addWidget(self.mode_combo)

        layout.addLayout(top_layout)

        # Create stacked widget with both panels (no controls, just plot canvas)
        self.stack = QStackedWidget()

        # Create both plot panels (they will only render, not have controls)
        self.seaborn_panel = SeabornPlotPanel()
        self.plotly_panel = PlotlyPlotPanel()

        # Add to stack (index 0 = Bitmap, index 1 = Interactive)
        self.stack.addWidget(self.seaborn_panel)
        self.stack.addWidget(self.plotly_panel)

        # Show interactive by default
        self.stack.setCurrentIndex(1)

        layout.addWidget(self.stack)

    def _on_mode_changed(self, mode: str):
        """Handle render mode change."""
        self._render_mode = mode
        if mode == "Bitmap":
            self.stack.setCurrentIndex(0)
        else:  # Interactive
            self.stack.setCurrentIndex(1)
            # Update Plotly panel with current settings
            self._update_plotly_panel()

    def _on_setting_changed(self):
        """Handle any setting change from controls."""
        # Save current state
        self._save_current_state()

        # Update both panels
        self._update_seaborn_panel()
        self._update_plotly_panel()

    def _save_current_state(self):
        """Save current control settings for the current test type."""
        if self._current_test_type:
            settings = self.controls.get_settings()
            self._test_type_states[self._current_test_type] = settings

    def _update_seaborn_panel(self):
        """Update Seaborn panel with current settings."""
        settings = self.controls.get_settings()
        settings['drop_first'] = self._drop_first_n
        settings['drop_last'] = self._drop_last_n
        self.seaborn_panel.update_plot_settings(**settings)

    def _update_plotly_panel(self):
        """Update Plotly panel with current settings."""
        settings = self.controls.get_settings()
        settings['drop_first'] = self._drop_first_n
        settings['drop_last'] = self._drop_last_n
        settings['test_type'] = self._current_test_type
        self.plotly_panel.update_plot_settings(**settings)

    def set_test_type(self, test_type: str):
        """Set the current test type and restore its settings."""
        self._current_test_type = test_type

        # Get state for this test type (or use defaults)
        if test_type not in self._test_type_states:
            self._test_type_states[test_type] = {
                'x_axis': 'Time',
                'x_reversed': False,
                'y1': 'Voltage',
                'y2': 'Current',
                'y2_enabled': False,
                'normalize': False,
                'show_lines': True,
                'show_points': False,
            }

        state = self._test_type_states[test_type]

        # Update controls (signals are blocked during set_settings)
        self.controls.set_settings(state)

        # Manually trigger plot updates since signals were blocked
        self._update_seaborn_panel()
        self._update_plotly_panel()

    def load_grouped_dataset(self, df: pd.DataFrame, device_colors: dict) -> None:
        """Load dataset into both panels."""
        self.seaborn_panel.load_grouped_dataset(df, device_colors)
        self.plotly_panel.load_grouped_dataset(df, device_colors)

    def clear_all_datasets(self):
        """Clear datasets from both panels."""
        self.seaborn_panel.clear_all_datasets()
        self.plotly_panel.clear_all_datasets()

    def set_drop_points(self, drop_first: int, drop_last: int):
        """Set drop points for both panels."""
        self._drop_first_n = drop_first
        self._drop_last_n = drop_last

        # Update both panels
        self._update_seaborn_panel()
        if self._render_mode == "Interactive":
            self._update_plotly_panel()

    # Expose properties for backwards compatibility
    @property
    def _x_axis(self):
        return self.controls._x_axis

    @property
    def _y1_param(self):
        return self.controls._y1_param

    @property
    def _y2_param(self):
        return self.controls._y2_param

    @property
    def _y2_enabled(self):
        return self.controls._y2_enabled
