"""Plotly-based interactive plot panel for Test Viewer."""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import Qt


class PlotlyPlotPanel(QWidget):
    """Interactive plot panel using Plotly for rich interactivity."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Data storage
        self._dataframe = None
        self._device_colors = {}

        # Plot settings (synced from main panel)
        self._x_axis = "Time"
        self._x_axis_reversed = False
        self._y1_param = "Voltage"
        self._y2_param = "Current"
        self._y2_enabled = False
        self._normalize_enabled = False
        self._drop_first_n = 0
        self._drop_last_n = 1
        self._test_type = None  # Current test type for title

        self._create_ui()

    def _create_ui(self):
        """Create the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create WebEngine view for displaying Plotly HTML
        self.web_view = QWebEngineView()
        self.web_view.setMinimumSize(800, 600)
        layout.addWidget(self.web_view)

        # Show empty plot initially
        self._show_empty_plot()

    def _show_empty_plot(self):
        """Display an empty plot."""
        fig = go.Figure()
        fig.update_layout(
            template="plotly_white",
            title="No data loaded",
            xaxis_title="",
            yaxis_title="",
            height=600,
        )
        self.web_view.setHtml(fig.to_html(include_plotlyjs='cdn'))

    def update_plot_settings(self, x_axis, x_reversed, y1, y2, y2_enabled, normalize, drop_first, drop_last, test_type=None):
        """Update plot settings and redraw."""
        self._x_axis = x_axis
        self._x_axis_reversed = x_reversed
        self._y1_param = y1
        self._y2_param = y2
        self._y2_enabled = y2_enabled
        self._normalize_enabled = normalize
        self._drop_first_n = drop_first
        self._drop_last_n = drop_last
        if test_type:
            self._test_type = test_type
        self._update_plot()

    def load_grouped_dataset(self, df: pd.DataFrame, device_colors: dict) -> None:
        """Load a grouped dataset from a DataFrame with Device column."""
        # Convert QColor to hex string
        self._device_colors = {}
        for device_name, qcolor in device_colors.items():
            color_hex = f"#{qcolor.red():02x}{qcolor.green():02x}{qcolor.blue():02x}"
            self._device_colors[device_name] = color_hex

        self._dataframe = df
        self._update_plot()

    def clear_all_datasets(self):
        """Clear all datasets."""
        self._dataframe = None
        self._device_colors = {}
        self._show_empty_plot()

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
        """Update the plot with current data and settings."""
        if self._dataframe is None or self._dataframe.empty:
            self._show_empty_plot()
            return

        # Create subplot with secondary y-axis if Y2 is enabled
        if self._y2_enabled:
            fig = make_subplots(specs=[[{"secondary_y": True}]])
        else:
            fig = go.Figure()

        device_names = self._dataframe['Device'].unique()

        # Determine time scaling if X-axis is Time
        time_scale = 1.0
        x_axis_label = self._get_parameter_label(self._x_axis)
        if self._x_axis == "Time" and not self._dataframe.empty:
            max_time = self._dataframe['Time'].max()
            time_scale, x_axis_label = self._get_time_scale(max_time)

        # Plot Y1 for each device
        for device_name in device_names:
            device_df = self._dataframe[self._dataframe['Device'] == device_name].copy()

            # Apply drop first/last filtering
            total_points = len(device_df)
            if total_points > 1:
                drop_first = min(self._drop_first_n, total_points - 1)
                drop_last = min(self._drop_last_n, total_points - drop_first - 1)

                if drop_first > 0 or drop_last > 0:
                    end_idx = total_points - drop_last if drop_last > 0 else total_points
                    device_df = device_df.iloc[drop_first:end_idx]

            color = self._device_colors.get(device_name, '#1f77b4')

            # Get X data and apply time scaling if needed
            x_data = device_df[self._x_axis] * time_scale

            # Get Y1 data and normalize if enabled (per-curve)
            y1_data = device_df[self._y1_param].copy()
            if self._normalize_enabled:
                y1_max = y1_data.max()
                if y1_max > 0:
                    y1_data = (y1_data / y1_max) * 100

            # Plot Y1 with solid line
            y1_label = self._y1_param + " (%)" if self._normalize_enabled else self._get_parameter_label(self._y1_param)

            # Custom hover template showing only Y1 parameter
            y1_unit = "%" if self._normalize_enabled else self._get_parameter_label(self._y1_param).split('(')[-1].strip(')')
            x_axis_base = x_axis_label.split('(')[0].strip()

            # Extract x-axis unit for hover
            x_unit = ""
            if '(' in x_axis_label:
                x_unit = x_axis_label.split('(')[-1].strip(')')

            # Format x differently for Time (1 decimal) vs others (2 decimals)
            x_format = ".1f" if self._x_axis == "Time" else ".2f"
            hover_template = f"<b>{device_name}</b><br>{x_axis_base}: %{{x:{x_format}}} {x_unit}<br>{self._y1_param}: %{{y:.2f}} {y1_unit}<extra></extra>"

            if self._y2_enabled:
                fig.add_trace(
                    go.Scatter(
                        x=x_data,
                        y=y1_data,
                        name=device_name,
                        line=dict(color=color, width=2),
                        mode='lines',
                        legendgroup=device_name,
                        hovertemplate=hover_template,
                    ),
                    secondary_y=False
                )
            else:
                fig.add_trace(
                    go.Scatter(
                        x=x_data,
                        y=y1_data,
                        name=device_name,
                        line=dict(color=color, width=2),
                        mode='lines',
                        hovertemplate=hover_template,
                    )
                )

        # Plot Y2 if enabled
        if self._y2_enabled:
            for device_name in device_names:
                device_df = self._dataframe[self._dataframe['Device'] == device_name].copy()

                # Apply same filtering
                total_points = len(device_df)
                if total_points > 1:
                    drop_first = min(self._drop_first_n, total_points - 1)
                    drop_last = min(self._drop_last_n, total_points - drop_first - 1)

                    if drop_first > 0 or drop_last > 0:
                        end_idx = total_points - drop_last if drop_last > 0 else total_points
                        device_df = device_df.iloc[drop_first:end_idx]

                color = self._device_colors.get(device_name, '#1f77b4')

                # Get X data and apply time scaling if needed
                x_data = device_df[self._x_axis] * time_scale

                # Get Y2 data and normalize if enabled (per-curve)
                y2_data = device_df[self._y2_param].copy()
                if self._normalize_enabled:
                    y2_max = y2_data.max()
                    if y2_max > 0:
                        y2_data = (y2_data / y2_max) * 100

                # Plot Y2 with dashed line
                # Custom hover template showing only Y2 parameter
                y2_unit = "%" if self._normalize_enabled else self._get_parameter_label(self._y2_param).split('(')[-1].strip(')')
                x_axis_base = x_axis_label.split('(')[0].strip()

                # Extract x-axis unit for hover
                x_unit = ""
                if '(' in x_axis_label:
                    x_unit = x_axis_label.split('(')[-1].strip(')')

                # Format x differently for Time (1 decimal) vs others (2 decimals)
                x_format = ".1f" if self._x_axis == "Time" else ".2f"
                hover_template_y2 = f"<b>{device_name}</b><br>{x_axis_base}: %{{x:{x_format}}} {x_unit}<br>{self._y2_param}: %{{y:.2f}} {y2_unit}<extra></extra>"

                fig.add_trace(
                    go.Scatter(
                        x=x_data,
                        y=y2_data,
                        name=f"{device_name} ({self._y2_param})",
                        line=dict(color=color, width=2, dash='dash'),
                        mode='lines',
                        legendgroup=device_name,
                        showlegend=False,  # Don't duplicate in legend
                        hovertemplate=hover_template_y2,
                    ),
                    secondary_y=True
                )

        # Add reference lines if normalized
        if self._normalize_enabled:
            for level in [20, 50, 80]:
                fig.add_hline(
                    y=level,
                    line_dash="dot",
                    line_color="lightgray",
                    opacity=0.6,
                    annotation_text=f"{level}%",
                    annotation_position="right"
                )

        # Update layout
        y1_label = self._y1_param + " (%)" if self._normalize_enabled else self._get_parameter_label(self._y1_param)

        # Get test type title
        test_type_titles = {
            'battery_capacity': 'Battery Capacity',
            'battery_load': 'Battery Load',
            'battery_charger': 'Battery Charger',
            'cable_resistance': 'Cable Resistance',
            'charger': 'Wall Charger',
            'power_bank': 'Power Bank',
        }
        title = test_type_titles.get(self._test_type, 'Test Data') if self._test_type else 'Test Data'

        layout_config = {
            'template': 'plotly_white',
            'hovermode': 'x unified',
            'height': 600,
            'title': dict(text=title, font=dict(size=16), x=0.5, xanchor='center'),
            'legend': dict(
                orientation='v',
                yanchor='top',
                y=1.0,
                xanchor='left',
                x=1.02
            ),
            'xaxis': dict(title=x_axis_label),
        }

        if self._y2_enabled:
            y2_label = self._y2_param + " (%)" if self._normalize_enabled else self._get_parameter_label(self._y2_param)
            fig.update_xaxes(title_text=x_axis_label)
            fig.update_yaxes(title_text=y1_label, secondary_y=False)
            fig.update_yaxes(title_text=y2_label, secondary_y=True)

            # Set y-axis ranges if normalized
            if self._normalize_enabled:
                fig.update_yaxes(range=[-2, 105], secondary_y=False)
                fig.update_yaxes(range=[-2, 105], secondary_y=True)
        else:
            layout_config['yaxis'] = dict(title=y1_label)
            # Set y-axis range if normalized
            if self._normalize_enabled:
                layout_config['yaxis']['range'] = [-2, 105]

        fig.update_layout(**layout_config)

        # Reverse X-axis if enabled
        if self._x_axis_reversed:
            fig.update_xaxes(autorange='reversed')

        # Display the plot
        self.web_view.setHtml(fig.to_html(include_plotlyjs='cdn'))

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
