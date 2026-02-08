"""Historical data browser panel."""

from typing import Optional
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QHeaderView,
    QAbstractItemView,
    QMessageBox,
    QComboBox,
    QLabel,
)
from PySide6.QtCore import Qt, Signal, Slot

from ..data.database import Database
from ..data.models import TestSession


class HistoryPanel(QWidget):
    """Panel for browsing historical test data."""

    session_selected = Signal(TestSession)

    def __init__(self, database: Database):
        super().__init__()

        self.database = database
        self._sessions: list[TestSession] = []
        self._selected_session: Optional[TestSession] = None

        self._create_ui()
        self.refresh()

    def _create_ui(self) -> None:
        """Create the history panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Filter bar
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Battery:"))
        self.battery_filter = QComboBox()
        self.battery_filter.addItem("All Batteries")
        self.battery_filter.currentIndexChanged.connect(self.refresh)
        filter_layout.addWidget(self.battery_filter)

        filter_layout.addStretch()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        filter_layout.addWidget(self.refresh_btn)

        layout.addLayout(filter_layout)

        # Sessions table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Date",
            "Name",
            "Battery",
            "Type",
            "Duration",
            "Capacity",
            "Energy",
        ])

        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(self._on_double_click)

        layout.addWidget(self.table)

        # Action buttons
        action_layout = QHBoxLayout()

        self.view_btn = QPushButton("View")
        self.view_btn.setEnabled(False)
        self.view_btn.clicked.connect(self._on_view)
        action_layout.addWidget(self.view_btn)

        self.compare_btn = QPushButton("Compare")
        self.compare_btn.setEnabled(False)
        self.compare_btn.clicked.connect(self._on_compare)
        action_layout.addWidget(self.compare_btn)

        action_layout.addStretch()

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._on_delete)
        action_layout.addWidget(self.delete_btn)

        layout.addLayout(action_layout)

    @property
    def selected_session(self) -> Optional[TestSession]:
        """Get the currently selected session."""
        return self._selected_session

    @Slot()
    def refresh(self) -> None:
        """Refresh the session list."""
        # Get battery filter
        battery_name = None
        if self.battery_filter.currentIndex() > 0:
            battery_name = self.battery_filter.currentText()

        # Load sessions
        self._sessions = self.database.list_sessions(
            limit=100,
            battery_name=battery_name,
        )

        # Update battery filter options
        self._update_battery_filter()

        # Populate table
        self.table.setRowCount(len(self._sessions))

        for row, session in enumerate(self._sessions):
            # Date
            date_str = session.start_time.strftime("%Y-%m-%d %H:%M")
            self.table.setItem(row, 0, QTableWidgetItem(date_str))

            # Name
            self.table.setItem(row, 1, QTableWidgetItem(session.name))

            # Battery
            self.table.setItem(row, 2, QTableWidgetItem(session.battery_name))

            # Type
            self.table.setItem(row, 3, QTableWidgetItem(session.test_type))

            # Duration
            duration = session.duration_seconds
            h = duration // 3600
            m = (duration % 3600) // 60
            s = duration % 60
            duration_str = f"{h:02d}:{m:02d}:{s:02d}"
            self.table.setItem(row, 4, QTableWidgetItem(duration_str))

            # Load readings to get capacity/energy
            if not session.readings:
                session.readings = self.database.get_readings(session.id)

            # Capacity
            capacity_str = f"{session.final_capacity_mah:.0f} mAh"
            self.table.setItem(row, 5, QTableWidgetItem(capacity_str))

            # Energy
            energy_str = f"{session.final_energy_wh:.2f} Wh"
            self.table.setItem(row, 6, QTableWidgetItem(energy_str))

        self._selected_session = None
        self._update_buttons()

    def _update_battery_filter(self) -> None:
        """Update battery filter dropdown."""
        current = self.battery_filter.currentText()

        self.battery_filter.blockSignals(True)
        self.battery_filter.clear()
        self.battery_filter.addItem("All Batteries")

        for name in self.database.get_battery_names():
            self.battery_filter.addItem(name)

        # Restore selection if still exists
        index = self.battery_filter.findText(current)
        if index >= 0:
            self.battery_filter.setCurrentIndex(index)

        self.battery_filter.blockSignals(False)

    def _update_buttons(self) -> None:
        """Update button enabled states."""
        has_selection = self._selected_session is not None
        self.view_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
        self.compare_btn.setEnabled(has_selection)

    @Slot()
    def _on_selection_changed(self) -> None:
        """Handle table selection change."""
        rows = self.table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            if 0 <= row < len(self._sessions):
                self._selected_session = self._sessions[row]
            else:
                self._selected_session = None
        else:
            self._selected_session = None

        self._update_buttons()

    @Slot()
    def _on_double_click(self) -> None:
        """Handle double-click to view session."""
        self._on_view()

    @Slot()
    def _on_view(self) -> None:
        """View the selected session."""
        if self._selected_session:
            # Ensure readings are loaded
            if not self._selected_session.readings:
                self._selected_session.readings = self.database.get_readings(
                    self._selected_session.id
                )
            self.session_selected.emit(self._selected_session)

    @Slot()
    def _on_compare(self) -> None:
        """Compare selected session with another."""
        # For now, just view it - comparison can be added later
        self._on_view()

    @Slot()
    def _on_delete(self) -> None:
        """Delete the selected session."""
        if not self._selected_session:
            return

        reply = QMessageBox.question(
            self,
            "Delete Session",
            f"Are you sure you want to delete '{self._selected_session.name}'?\n"
            "This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.database.delete_session(self._selected_session.id)
            self.refresh()
