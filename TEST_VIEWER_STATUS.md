# Test Viewer Implementation Status

## Implemented ✅

### Core Structure
- ✅ Main window with plot panel on top and tabs on bottom
- ✅ Five tabs for different test types (Battery Capacity, Battery Load, Battery Charger, Wall Charger, Power Bank)
- ✅ Test list panels showing JSON files for each test type

### Test List Panel Features
- ✅ Table showing test files with key information:
  - Checkbox for selection
  - Color picker button (custom color per test)
  - Date/time
  - Device name
  - Manufacturer
  - Test conditions (mode, value, cutoff)
  - Results (capacity, energy)
  - Delete button
- ✅ Auto-refresh every 5 seconds to detect new files
- ✅ Browse button to change data folder
- ✅ Refresh button to manually reload files
- ✅ File count display
- ✅ Delete functionality with confirmation dialog

### Menu System
- ✅ File menu with:
  - Browse Data Folder
  - Export Plot
  - Export Data (CSV)
  - Exit
- ✅ View menu with:
  - Refresh All
- ✅ Help menu with:
  - About

### GUI Export Buttons
- ✅ Export Plot button below plot panel
- ✅ Export Data button below plot panel

### Data Export
- ✅ CSV export of selected tests with all readings
- ✅ Exports: Test Name, Manufacturer, Time, Voltage, Current, Power, Capacity, Energy, Resistance, Temperature

## Recently Implemented ✅

### Plot Integration
- ✅ Extended PlotPanel with multi-dataset support (backwards compatible with Test Bench)
- ✅ New methods: `load_dataset()`, `remove_dataset()`, `clear_all_datasets()`, `is_multi_dataset_mode()`
- ✅ Multi-dataset storage: `_datasets` dictionary tracks multiple complete datasets
- ✅ Custom colors per dataset (from color picker in test list)
- ✅ Different line styles for different Y-axis parameters (solid, dash, dot, dash-dot, dash-dot-dot)
- ✅ Legend showing dataset names (manufacturer + device name)
- ✅ Automatic unit scaling and axis labeling
- ✅ Single-dataset mode unchanged (Test Bench streaming still works)

### Plot Export
- ✅ Plot export to PNG/PDF using pyqtgraph's ImageExporter
- ✅ Available from both menu (File → Export Plot) and GUI button

### Nice to Have
- Search/filter in test file lists
- Sort by different columns
- Batch selection (select all, select none, invert selection)
- Preset color schemes
- Save viewer layout/preferences
- Zoom/pan controls on plot
- Data statistics panel showing min/max/average values
- Comparison metrics between selected tests

## File Structure
```
atorch/
  viewer/
    __init__.py              ✅ Module init
    main_window.py           ✅ Main viewer window
    test_list_panel.py       ✅ Test file list panel with table
  viewer_main.py             ✅ Entry point
run_viewer.py                ✅ Simple launcher script
```

## Running Test Viewer

```bash
# From project root
python run_viewer.py

# Or
python -m atorch.viewer_main
```

## Next Steps

1. Test with real data files from ~/.atorch/test_data/
2. Verify backwards compatibility - Test Bench should work unchanged
3. Refine UI based on user feedback
4. Add missing features from "Nice to Have" list as needed
