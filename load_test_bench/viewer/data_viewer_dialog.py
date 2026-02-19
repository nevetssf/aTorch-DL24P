"""Dialog for viewing raw data being plotted."""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QComboBox, QHeaderView
)
from PySide6.QtCore import Qt


class DataViewerDialog(QDialog):
    """Dialog showing raw data being plotted."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plot Data Viewer")
        self.setMinimumSize(1000, 600)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._datasets = {}
        self._create_ui()

    def _create_ui(self):
        """Create the UI."""
        layout = QVBoxLayout(self)

        # Dataset selector
        self.selector_layout = QHBoxLayout()
        self.dataset_label = QLabel("Dataset:")
        self.selector_layout.addWidget(self.dataset_label)

        self.dataset_combo = QComboBox()
        self.dataset_combo.currentTextChanged.connect(self._on_dataset_changed)
        self.selector_layout.addWidget(self.dataset_combo, stretch=1)

        layout.addLayout(self.selector_layout)

        # Data table
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        # Close button
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def set_dataframe(self, df):
        """Set a pandas DataFrame to display.

        Args:
            df: pandas DataFrame with all columns including Device
        """
        import pandas as pd

        if df is None or df.empty:
            self.table.setRowCount(0)
            return

        # Hide the combo box and label since we're showing one combined table
        self.dataset_combo.setVisible(False)
        self.dataset_label.setVisible(False)

        # Build table from DataFrame
        self.table.blockSignals(True)

        # Set columns from DataFrame
        columns = list(df.columns)
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

        # Set row count
        num_rows = len(df)
        self.table.setRowCount(num_rows)

        # Populate table
        for row_idx in range(num_rows):
            for col_idx, col_name in enumerate(columns):
                value = df.iloc[row_idx, col_idx]

                # Format based on type
                if isinstance(value, (int, float)):
                    item_text = f"{value:.6f}" if isinstance(value, float) else str(value)
                else:
                    item_text = str(value)

                item = QTableWidgetItem(item_text)
                self.table.setItem(row_idx, col_idx, item)

        # Auto-resize columns
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)

        self.table.blockSignals(False)
        self.table.setSortingEnabled(True)

    def set_datasets(self, datasets: dict):
        """Set the datasets to display (legacy method for backwards compatibility).

        Args:
            datasets: Dictionary of {dataset_id: {'times': array, 'data': dict, 'label': str}}
        """
        self._datasets = datasets

        # Show combo box and label
        self.dataset_combo.setVisible(True)
        self.dataset_label.setVisible(True)

        # Update combo box
        self.dataset_combo.blockSignals(True)
        self.dataset_combo.clear()

        for dataset_id, dataset in datasets.items():
            label = dataset.get('label', dataset_id)
            self.dataset_combo.addItem(label, dataset_id)

        self.dataset_combo.blockSignals(False)

        # Show first dataset
        if self.dataset_combo.count() > 0:
            self._on_dataset_changed(self.dataset_combo.currentText())

    def _on_dataset_changed(self, label: str):
        """Handle dataset selection change."""
        dataset_id = self.dataset_combo.currentData()
        if not dataset_id or dataset_id not in self._datasets:
            self.table.setRowCount(0)
            return

        dataset = self._datasets[dataset_id]
        times = dataset['times']
        data_dict = dataset['data']

        # Build table
        self.table.blockSignals(True)

        # Create columns: Time + all parameters
        columns = ['Time (s)'] + sorted(data_dict.keys())
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

        # Set row count
        num_points = len(times)
        self.table.setRowCount(num_points)

        # Populate table
        for row in range(num_points):
            # Time column
            time_item = QTableWidgetItem(f"{times[row]:.3f}")
            self.table.setItem(row, 0, time_item)

            # Data columns
            for col_idx, param_name in enumerate(sorted(data_dict.keys()), start=1):
                values = data_dict[param_name]
                if row < len(values):
                    value = values[row]
                    value_item = QTableWidgetItem(f"{value:.6f}")
                    self.table.setItem(row, col_idx, value_item)

        # Auto-resize columns
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)

        self.table.blockSignals(False)
        self.table.setSortingEnabled(True)
