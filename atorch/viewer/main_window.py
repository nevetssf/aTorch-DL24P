"""Main window for Test Viewer application."""

import json
import logging
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QMenuBar, QMenu, QFileDialog, QMessageBox, QPushButton,
    QDialog, QLabel, QSpinBox, QFormLayout, QDialogButtonBox
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction

from .plot_panel_container import PlotPanelContainer
from .test_list_panel import TestListPanel
from .debug_console import DebugConsole
from .data_viewer_dialog import DataViewerDialog


class ViewerMainWindow(QMainWindow):
    """Main window for Test Viewer application."""

    # Test type mapping to tab names
    TEST_TYPES = {
        'battery_capacity': 'Battery Capacity',
        'battery_load': 'Battery Load',
        'battery_charger': 'Battery Charger',
        'cable_resistance': 'Cable Resistance',
        'charger': 'Wall Charger',
        'power_bank': 'Power Bank',
    }

    # Line styles for different measurements on same plot
    LINE_STYLES = [
        Qt.SolidLine,
        Qt.DashLine,
        Qt.DotLine,
        Qt.DashDotLine,
        Qt.DashDotDotLine,
    ]

    def __init__(self):
        super().__init__()

        self.setWindowTitle("DL24/P Test Viewer")
        self.setMinimumSize(1200, 800)

        # Default data directory
        self.data_directory = Path.home() / ".atorch" / "test_data"
        self.data_directory.mkdir(parents=True, exist_ok=True)

        # Settings file
        self._atorch_dir = Path.home() / ".atorch"
        self._atorch_dir.mkdir(parents=True, exist_ok=True)
        self._settings_file = self._atorch_dir / "test_viewer_settings.json"

        # Currently displayed datasets
        self._current_datasets = []

        # Plot settings (defaults, will be overridden by saved settings)
        self._drop_first_n = 0  # Drop first N data points
        self._drop_last_n = 1   # Drop last N data points (default 1)

        # Debug console
        self.debug_console = DebugConsole(self)

        # Data viewer dialog
        self.data_viewer = DataViewerDialog(self)

        # Currently loaded datasets for inspection
        self._current_plot_datasets = {}

        # Set up file logging (clears on each run)
        self._setup_logging()

        # Load saved settings (after logging is set up)
        self._load_plot_settings()

        # Log startup
        self._log("Test Viewer started", "INFO")
        self._log(f"Data directory: {self.data_directory}", "INFO")

        self._create_ui()
        self._create_menus()

    def _create_ui(self):
        """Create the main UI."""
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Plot panel (top) - container with both seaborn and plotly
        self.plot_panel = PlotPanelContainer()
        # Set initial test type to first tab (Battery Capacity)
        self.plot_panel.set_test_type('battery_capacity')
        # Apply loaded drop settings
        self.plot_panel.set_drop_points(self._drop_first_n, self._drop_last_n)
        layout.addWidget(self.plot_panel, stretch=2)

        # Export buttons below plot
        export_layout = QHBoxLayout()
        export_layout.addStretch()

        self.view_data_btn = QPushButton("View Plot Data...")
        self.view_data_btn.setToolTip("View raw data being plotted (for debugging)")
        self.view_data_btn.clicked.connect(self._view_plot_data)
        export_layout.addWidget(self.view_data_btn)

        self.export_plot_btn = QPushButton("Export Plot...")
        self.export_plot_btn.setToolTip("Save plot as image (PNG or PDF)")
        self.export_plot_btn.clicked.connect(self._export_plot)
        export_layout.addWidget(self.export_plot_btn)

        self.export_data_btn = QPushButton("Export Data...")
        self.export_data_btn.setToolTip("Save selected test data as CSV")
        self.export_data_btn.clicked.connect(self._export_data)
        export_layout.addWidget(self.export_data_btn)

        layout.addLayout(export_layout)

        # Tab widget (bottom) with test list panels
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Create a panel for each test type
        self.test_panels = {}
        for test_type, tab_name in self.TEST_TYPES.items():
            panel = TestListPanel(test_type, self.data_directory, log_callback=self._log)
            panel.selection_changed.connect(self._on_selection_changed)
            self.tabs.addTab(panel, tab_name)
            self.test_panels[test_type] = panel

        layout.addWidget(self.tabs, stretch=1)

        # Status bar
        self.statusBar().showMessage("Ready")

    def _create_menus(self):
        """Create menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        # Browse folder
        browse_action = QAction("&Browse Data Folder...", self)
        browse_action.triggered.connect(self._browse_data_folder)
        file_menu.addAction(browse_action)

        file_menu.addSeparator()

        # Export plot
        export_plot_action = QAction("Export &Plot...", self)
        export_plot_action.triggered.connect(self._export_plot)
        file_menu.addAction(export_plot_action)

        # Export data
        export_data_action = QAction("Export &Data...", self)
        export_data_action.triggered.connect(self._export_data)
        file_menu.addAction(export_data_action)

        file_menu.addSeparator()

        # Exit
        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        # Refresh all
        refresh_action = QAction("&Refresh All", self)
        refresh_action.triggered.connect(self._refresh_all)
        view_menu.addAction(refresh_action)

        view_menu.addSeparator()

        # Debug console
        debug_action = QAction("&Debug Console", self)
        debug_action.triggered.connect(self._show_debug_console)
        view_menu.addAction(debug_action)

        # Settings menu
        settings_menu = menubar.addMenu("&Settings")

        plot_settings_action = QAction("&Plot Settings...", self)
        plot_settings_action.triggered.connect(self._show_plot_settings)
        settings_menu.addAction(plot_settings_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    @Slot()
    def _browse_data_folder(self):
        """Browse to a different data folder."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Data Folder",
            str(self.data_directory),
            QFileDialog.ShowDirsOnly
        )

        if folder:
            self.data_directory = Path(folder)
            # Update all panels
            for panel in self.test_panels.values():
                panel.data_directory = self.data_directory
                panel._load_test_files()

            self.statusBar().showMessage(f"Data folder: {self.data_directory}")

    @Slot()
    def _refresh_all(self):
        """Refresh all test panels."""
        for panel in self.test_panels.values():
            panel._load_test_files()
        self.statusBar().showMessage("Refreshed all panels")

    @Slot(int)
    def _on_tab_changed(self, index: int):
        """Handle tab change - update plot with current tab's selections."""
        current_panel = self.tabs.widget(index)
        if isinstance(current_panel, TestListPanel):
            # Update plot panel's test type to restore its settings
            self.plot_panel.set_test_type(current_panel.test_type)

            selected = current_panel.get_selected_tests()
            self._log(f"Tab changed to {self.tabs.tabText(index)}, {len(selected)} tests selected", "INFO")
            self._update_plot_with_selections(selected)

    @Slot(list)
    def _on_selection_changed(self, selected_tests):
        """Handle selection change in any test panel."""
        self._log(f"Selection changed, {len(selected_tests)} tests selected", "DEBUG")

        # Get current tab's panel
        current_panel = self.tabs.currentWidget()
        if not isinstance(current_panel, TestListPanel):
            return

        selected = current_panel.get_selected_tests()
        self._update_plot_with_selections(selected)

    def _update_plot_with_selections(self, selected):
        """Update plot with given test selections."""

        # Clear all datasets
        self.plot_panel.clear_all_datasets()
        self._current_plot_datasets.clear()

        if not selected:
            self.statusBar().showMessage("No tests selected")
            return

        self._log(f"Loading {len(selected)} datasets into plot", "INFO")
        dataset_names = [f"{t.get('manufacturer', '')} {t.get('name', '')}" for t in selected]
        self._log(f"Selected datasets: {dataset_names}", "DEBUG")

        # Build a combined table with all data and a Device column
        import pandas as pd

        all_data = []
        device_colors = {}

        for i, test_data in enumerate(selected):
            data = test_data['data']
            color = test_data['color']
            name = test_data['name']
            manufacturer = test_data['manufacturer']

            # Get date from summary or first reading
            timestamp = None
            summary = data.get('summary', {})
            if summary:
                timestamp = summary.get('start_time')

            if not timestamp:
                # Fallback to first reading's timestamp
                readings = data.get('readings', [])
                if readings:
                    timestamp = readings[0].get('timestamp')

            # Format date for display
            date_str = ""
            if timestamp:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(timestamp)
                    date_str = dt.strftime("%m-%d %H:%M")
                except:
                    date_str = timestamp[:16] if len(timestamp) > 16 else timestamp

            # Create legend label with date
            if manufacturer:
                legend_label = f"{manufacturer} {name}"
            else:
                legend_label = name

            if date_str:
                legend_label = f"{legend_label} ({date_str})"

            self._log(f"Processing test {i+1}/{len(selected)}: {legend_label}", "DEBUG")

            # Get readings
            readings = data.get('readings', [])
            if not readings:
                self._log(f"Warning: No readings found for {legend_label}", "WARN")
                continue

            self._log(f"Found {len(readings)} readings for {legend_label}", "DEBUG")

            try:

                # Find final (maximum) capacity and energy values for calculating remaining
                final_capacity = max((r.get('capacity_mah', 0) for r in readings), default=0)
                final_energy = max((r.get('energy_wh', 0) for r in readings), default=0)

                # Extract data points and create table rows
                from datetime import datetime

                # Parse timestamps and calculate elapsed time
                raw_timestamps = []
                for reading in readings:
                    timestamp_str = reading.get('timestamp', '')
                    if timestamp_str:
                        try:
                            dt = datetime.fromisoformat(timestamp_str)
                            raw_timestamps.append(dt)
                        except:
                            raw_timestamps.append(None)
                    else:
                        raw_timestamps.append(None)

                # Calculate elapsed time from first timestamp
                if raw_timestamps and raw_timestamps[0]:
                    first_timestamp = raw_timestamps[0]

                    # Create rows for this device
                    for idx, reading in enumerate(readings):
                        ts = raw_timestamps[idx]
                        if ts:
                            elapsed = (ts - first_timestamp).total_seconds()
                        else:
                            elapsed = 0

                        # Get current capacity and energy
                        capacity = reading.get('capacity_mah', 0)
                        energy = reading.get('energy_wh', 0)

                        # Calculate remaining capacity and energy (final - current)
                        # This shows what's left in the battery based on actual discharge
                        capacity_remaining = final_capacity - capacity
                        energy_remaining = final_energy - energy

                        # Create a row with Device column
                        row = {
                            'Device': legend_label,
                            'Time': elapsed,
                            'Voltage': reading.get('voltage_v', reading.get('voltage', 0)),
                            'Current': reading.get('current_a', reading.get('current', 0)),
                            'Power': reading.get('power_w', reading.get('power', 0)),
                            'Capacity': capacity,
                            'Capacity Remaining': capacity_remaining,
                            'Energy': energy,
                            'Energy Remaining': energy_remaining,
                            'R Load': reading.get('load_r_ohm', reading.get('resistance_ohm', 0)),
                            'Temp MOSFET': reading.get('mosfet_temp_c', reading.get('temperature_c', 0)),
                        }
                        all_data.append(row)

                    # Store color for this device
                    device_colors[legend_label] = color

                    self._log(f"Added {len(readings)} rows for device: {legend_label}", "DEBUG")

            except Exception as e:
                self._log(f"ERROR loading dataset {i}: {e}", "ERROR")
                import traceback
                self._log(f"Traceback: {traceback.format_exc()}", "ERROR")

        # Create DataFrame from all data
        if not all_data:
            self._log("No data to plot", "WARN")
            return

        df = pd.DataFrame(all_data)
        self._log(f"Created combined table: {len(df)} rows, {len(df['Device'].unique())} devices", "INFO")
        self._log(f"Table columns: {list(df.columns)}", "DEBUG")
        self._log(f"Devices in table: {list(df['Device'].unique())}", "DEBUG")

        # Store the combined table for inspection
        self._current_plot_datasets['combined_table'] = {
            'dataframe': df,
            'device_colors': device_colors
        }

        # Pass the SINGLE combined table to the plot panel
        self.plot_panel.load_grouped_dataset(df, device_colors)

        self._log(f"Loaded combined table with {len(df['Device'].unique())} devices", "INFO")

        # Log plot configuration
        params = [f"Y1={self.plot_panel._y1_param}"]
        if self.plot_panel._y2_enabled:
            params.append(f"Y2={self.plot_panel._y2_param}")
        self._log(f"Plot parameters: {', '.join(params)} vs X={self.plot_panel._x_axis}", "INFO")

        self.statusBar().showMessage(f"{len(selected)} test(s) displayed")
        self._log(f"Finished loading {len(selected)} test(s)", "INFO")

    @Slot()
    def _export_plot(self):
        """Export plot as image."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Plot",
            str(self.data_directory / "plot.png"),
            "PNG Image (*.png);;PDF Document (*.pdf);;SVG Vector (*.svg)"
        )

        if file_path:
            try:
                # Use matplotlib's save functionality
                self.plot_panel.figure.savefig(
                    file_path,
                    dpi=300,
                    bbox_inches='tight',
                    facecolor='white'
                )

                QMessageBox.information(
                    self,
                    "Export Plot",
                    f"Plot exported successfully to:\n{file_path}"
                )
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export plot:\n{e}")

    @Slot()
    def _export_data(self):
        """Export selected data as CSV."""
        # Get current panel
        current_panel = self.tabs.currentWidget()
        if not isinstance(current_panel, TestListPanel):
            return

        selected = current_panel.get_selected_tests()
        if not selected:
            QMessageBox.information(self, "Export Data", "No tests selected")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Data",
            str(self.data_directory / "export.csv"),
            "CSV File (*.csv)"
        )

        if file_path:
            try:
                self._write_csv(file_path, selected)
                QMessageBox.information(
                    self,
                    "Export Data",
                    f"Exported {len(selected)} test(s) to:\n{file_path}"
                )
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export data:\n{e}")

    def _write_csv(self, file_path: str, selected_tests: list):
        """Write selected tests to CSV file."""
        import csv

        with open(file_path, 'w', newline='') as f:
            writer = csv.writer(f)

            # Write header
            header = [
                'Test Name', 'Manufacturer', 'Time (s)',
                'Voltage (V)', 'Current (A)', 'Power (W)',
                'Capacity (mAh)', 'Energy (Wh)', 'Resistance (Ω)', 'Temp (°C)'
            ]
            writer.writerow(header)

            # Write data for each test
            for test_data in selected_tests:
                data = test_data['data']
                name = test_data['name']
                manufacturer = test_data['manufacturer']

                readings = data.get('readings', [])
                for reading in readings:
                    row = [
                        name,
                        manufacturer,
                        reading.get('elapsed_time', 0),
                        reading.get('voltage_v', reading.get('voltage', 0)),
                        reading.get('current_a', reading.get('current', 0)),
                        reading.get('power_w', reading.get('power', 0)),
                        reading.get('capacity_mah', 0),
                        reading.get('energy_wh', 0),
                        reading.get('load_r_ohm', reading.get('resistance_ohm', 0)),
                        reading.get('mosfet_temp_c', reading.get('temperature_c', 0)),
                    ]
                    writer.writerow(row)

    def _load_plot_settings(self):
        """Load plot settings from config file."""
        try:
            if self._settings_file.exists():
                with open(self._settings_file, 'r') as f:
                    settings = json.load(f)
                    self._drop_first_n = settings.get('drop_first_n', 0)
                    self._drop_last_n = settings.get('drop_last_n', 1)
                    self._log(f"Loaded plot settings: drop first {self._drop_first_n}, last {self._drop_last_n}", "INFO")
        except Exception as e:
            self._log(f"Failed to load plot settings: {e}", "ERROR")
            # Use defaults on error
            self._drop_first_n = 0
            self._drop_last_n = 1

    def _save_plot_settings(self):
        """Save plot settings to config file."""
        try:
            settings = {
                'drop_first_n': self._drop_first_n,
                'drop_last_n': self._drop_last_n
            }
            with open(self._settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
            self._log(f"Saved plot settings: drop first {self._drop_first_n}, last {self._drop_last_n}", "INFO")
        except Exception as e:
            self._log(f"Failed to save plot settings: {e}", "ERROR")

    def _setup_logging(self):
        """Set up file logging (clears each run)."""
        log_file = Path(__file__).parent.parent.parent / "viewer_debug.log"

        # Clear log file if it exists
        if log_file.exists():
            log_file.unlink()

        # Configure logging
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, mode='w'),
            ]
        )

        self.logger = logging.getLogger(__name__)

    def _log(self, message: str, level: str = "INFO"):
        """Log a message to both file and debug console.

        Args:
            message: Message to log
            level: Log level (INFO, ERROR, DEBUG, WARN)
        """
        # Log to file
        if level == "ERROR":
            self.logger.error(message)
        elif level == "DEBUG":
            self.logger.debug(message)
        elif level == "WARN":
            self.logger.warning(message)
        else:
            self.logger.info(message)

        # Log to debug console
        self.debug_console.log(message, level)

    @Slot()
    def _show_debug_console(self):
        """Show the debug console window."""
        self.debug_console.show()
        self.debug_console.raise_()
        self.debug_console.activateWindow()

    @Slot()
    def _show_plot_settings(self):
        """Show plot settings dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Plot Settings")
        dialog.setMinimumWidth(400)

        layout = QFormLayout(dialog)

        # Drop first N points
        first_spin = QSpinBox()
        first_spin.setRange(0, 1000)
        first_spin.setValue(self._drop_first_n)
        first_spin.setToolTip("Number of initial data points to exclude from plot")
        layout.addRow("Drop first N points:", first_spin)

        # Drop last N points
        last_spin = QSpinBox()
        last_spin.setRange(0, 1000)
        last_spin.setValue(self._drop_last_n)
        last_spin.setToolTip("Number of final data points to exclude from plot")
        layout.addRow("Drop last N points:", last_spin)

        # Add explanation
        info_label = QLabel("These settings control which data points are displayed in plots.\n"
                           "Useful for removing startup transients (first) or final outliers (last).")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addRow("", info_label)

        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        # Show dialog and apply settings if accepted
        if dialog.exec() == QDialog.Accepted:
            self._drop_first_n = first_spin.value()
            self._drop_last_n = last_spin.value()
            self._log(f"Plot settings updated: drop first {self._drop_first_n}, last {self._drop_last_n} points", "INFO")

            # Save settings to config file
            self._save_plot_settings()

            # Update plot panel with new drop settings (triggers immediate redraw)
            self.plot_panel.set_drop_points(self._drop_first_n, self._drop_last_n)

            # Refresh plot with new settings if data is loaded
            current_panel = self.tabs.currentWidget()
            if isinstance(current_panel, TestListPanel):
                self._log("Refreshing plot with new settings...", "INFO")
                selected = current_panel.get_selected_tests()
                if selected:
                    self._update_plot_with_selections(selected)

    @Slot()
    def _view_plot_data(self):
        """Show the raw plot data viewer."""
        if not self._current_plot_datasets or 'combined_table' not in self._current_plot_datasets:
            QMessageBox.information(
                self,
                "No Data",
                "No datasets are currently loaded. Check some test boxes to load data."
            )
            return

        # Get the combined DataFrame with Device column
        df = self._current_plot_datasets['combined_table']['dataframe']

        self._log(f"Opening data viewer with {len(df)} rows, {len(df['Device'].unique())} devices", "INFO")

        # Pass the DataFrame directly - it has the Device column!
        self.data_viewer.set_dataframe(df)
        self.data_viewer.show()
        self.data_viewer.raise_()
        self.data_viewer.activateWindow()

    @Slot()
    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About DL24/P Test Viewer",
            "<h2>DL24/P Test Viewer</h2>"
            "<p><b>Version 1.0.0</b></p>"
            "<p>Companion application for viewing and comparing test data "
            "from the DL24/P Test Bench.</p>"
            "<p><b>Features:</b></p>"
            "<ul>"
            "<li>View and compare multiple test results</li>"
            "<li>Color-coded plots with custom colors</li>"
            "<li>Multi-axis plotting with different line styles</li>"
            "<li>Export plots and data</li>"
            "<li>Auto-refresh when new data is added</li>"
            "</ul>"
            "<p>© 2026 • Built with PySide6 and pyqtgraph</p>",
        )
