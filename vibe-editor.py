#!/usr/bin/env python3
import sys
import os
import csv
from PyQt5.QtWidgets import (QApplication, QMainWindow, QTableView,
                             QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QHeaderView,
                             QMessageBox, QStyledItemDelegate, QComboBox, QLineEdit,
                             QLabel, QShortcut, QAbstractItemView, QScrollBar)
from PyQt5.QtCore import QAbstractTableModel, Qt, QTimer, qInstallMessageHandler
from PyQt5.QtGui import QColor, QKeySequence

# =====================================================================
# SUPPRESS HARMLESS QT WARNINGS
# =====================================================================
def qt_message_handler(mode, context, message):
    if "edit: editing failed" in message:
        return
    sys.stderr.write(message + '\n')

# =====================================================================
# CUSTOM EDITORS & CONTROLS
# =====================================================================
class CustomLineEdit(QLineEdit):
    """
    Custom QLineEdit for standard text cells to override Up/Down arrow behavior.
    """
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Up:
            self.setCursorPosition(0)
        elif event.key() == Qt.Key_Down:
            self.setCursorPosition(len(self.text()))
        else:
            super().keyPressEvent(event)

class SearchLineEdit(QLineEdit):
    """
    Custom QLineEdit for the search bar to handle Enter / Shift+Enter for navigation.
    """
    def __init__(self, search_callback, parent=None):
        super().__init__(parent)
        self.search_callback = search_callback

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            # Pass direction: -1 for up (Shift), 1 for down
            direction = -1 if event.modifiers() == Qt.ShiftModifier else 1
            self.search_callback(direction=direction, start_from_current=True)
        else:
            super().keyPressEvent(event)

class EdgeScrollBar(QScrollBar):
    """
    An invisible scrollbar placed at the absolute edge of the window.
    Supports instant click-to-scroll and click-and-drag.
    """
    def __init__(self, parent=None):
        super().__init__(Qt.Vertical, parent)
        self.setCursor(Qt.ArrowCursor)
        # Keep it completely invisible to not alter the visible UI layout
        self.setStyleSheet("""
            QScrollBar:vertical {
                background: transparent;
                margin: 0px;
            }
            QScrollBar::handle:vertical { background: transparent; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._jump_to_cursor(event.pos().y())
            
    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._jump_to_cursor(event.pos().y())
            
    def _jump_to_cursor(self, y_pos):
        height = self.height()
        if height <= 0: return
        # Instantly map the physical pixel clicked to the scrolling range
        ratio = max(0.0, min(1.0, y_pos / height))
        val = int(self.minimum() + ratio * (self.maximum() - self.minimum()))
        self.setValue(val)

# =====================================================================
# DELEGATES
# =====================================================================
class CustomItemDelegate(QStyledItemDelegate):
    """
    Custom delegate to render QComboBoxes and custom LineEdits during editing.
    Design Choice: We intentionally DO NOT force the popup to open automatically.
    This allows the user to hover the cell and use the mouse wheel to rapidly
    cycle through options. Clicking the cell will open the standard dropdown.
    """
    def __init__(self, cb_cols, parent=None):
        super().__init__(parent)
        self.cb_cols = cb_cols

    def createEditor(self, parent, option, index):
        col = index.column()
        if col in self.cb_cols:
            editor = QComboBox(parent)
            
            # CRITICAL THEME FIX: By default, Qt uses the OS's native rendering
            # engine (like GTK on Linux) for combobox dropdowns, which completely
            # ignores our QSS colors. Forcing a blank QStyledItemDelegate onto
            # the combobox makes it obey our custom green/black CSS.
            editor.setItemDelegate(QStyledItemDelegate())
            
            editor.addItems(self.cb_cols[col])
            return editor
        else:
            # Use our custom line edit for standard text cells
            editor = CustomLineEdit(parent)
            return editor

    def setEditorData(self, editor, index):
        col = index.column()
        if col in self.cb_cols:
            value = index.model().data(index, Qt.EditRole)
            cb_index = editor.findText(value)
            if cb_index >= 0:
                editor.setCurrentIndex(cb_index)
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        col = index.column()
        if col in self.cb_cols:
            value = editor.currentText()
            model.setData(index, value, Qt.EditRole)
        else:
            super().setModelData(editor, model, index)

# =====================================================================
# CUSTOM TABLE VIEW (FOR KEYBOARD INTERACTION)
# =====================================================================
class TSVTableView(QTableView):
    """
    Custom QTableView to handle specific keyboard interactions,
    specifically making 'Enter' behave like a mouse click, and
    handling Ctrl+V pasting directly into unedited cells.
    """
    def keyPressEvent(self, event):
        # Intercept Ctrl+V to paste and enter edit mode
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_V:
            index = self.currentIndex()
            if index.isValid():
                col = index.column()
                model = self.model()
                # Ensure we only paste into editable, non-checkbox columns
                if col not in model.chk_cols and col not in model.ro_cols:
                    clipboard_text = QApplication.clipboard().text()
                    # Strip tabs and newlines so the paste doesn't break the structure
                    clean_text = clipboard_text.replace('\t', ' ').replace('\n', ' ').replace('\r', '')
                    
                    model.setData(index, clean_text, Qt.EditRole)
                    self.edit(index)
                    return # Prevent default processing
        
        # Intercept Enter/Return to mimic a mouse click
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            index = self.currentIndex()
            if index.isValid():
                # Trigger the same logic as a mouse click
                self.window().on_cell_clicked(index)
                return  # Prevent the default behavior (moving to the next row)
                
        super().keyPressEvent(event)

# =====================================================================
# DATA MODEL
# =====================================================================
class TSVModel(QAbstractTableModel):
    """
    A lightweight data model required to efficiently handle 3,000+ lines.
    Instead of drawing thousands of widgets, this keeps the data in memory
    as a simple list of lists and only renders what is visible on screen.
    Now supports both TSV and CSV datasets.
    """
    def __init__(self, data, raw_headers):
        super().__init__()
        self._data = data
        self._raw_headers = raw_headers
        self._display_headers = []
        
        # Track column indices based on custom header markers
        self.chk_cols = []
        self.ro_cols = []
        self.cb_cols = {}

        # Parse and strip out formatting markers so they don't show in the UI
        for i, header in enumerate(raw_headers):
            if header.endswith(':chk'):
                self.chk_cols.append(i)
                self._display_headers.append(header[:-4])
            elif header.endswith(':ro'):
                self.ro_cols.append(i)
                self._display_headers.append(header[:-3])
            elif ':cb=' in header:
                base_name, opts_str = header.split(':cb=', 1)
                self.cb_cols[i] = opts_str.split(',')
                self._display_headers.append(base_name)
            else:
                self._display_headers.append(header)

    def rowCount(self, parent=None):
        return len(self._data)

    def columnCount(self, parent=None):
        return len(self._raw_headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._display_headers[section]
        if role == Qt.DisplayRole and orientation == Qt.Vertical:
            return str(section + 1)
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
            
        row, col = index.row(), index.column()

        # Safely handle jagged rows (missing trailing cells)
        val = self._data[row][col] if col < len(self._data[row]) else ""

        if role == Qt.DisplayRole or role == Qt.EditRole:
            if col in self.chk_cols:
                return None  # Hide literal "TRUE/FALSE" text under checkboxes
            return val
            
        elif role == Qt.ForegroundRole:
            # Highlight negative money values bright red
            if val.strip().startswith('-'):
                return QColor('#FF3333')
            # Return None so the global QSS handles the default green text and black selection
            return None
            
        elif role == Qt.CheckStateRole:
            if col in self.chk_cols:
                return Qt.Checked if val.strip().upper() == 'TRUE' else Qt.Unchecked
                
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False
            
        row, col = index.row(), index.column()
        
        # Pad row out if saving data to a previously empty trailing cell
        while len(self._data[row]) <= col:
            self._data[row].append("")

        if role == Qt.EditRole:
            # Enforce read-only constraint at the data level
            if col not in self.chk_cols and col not in self.ro_cols:
                self._data[row][col] = value
                self.dataChanged.emit(index, index)
                return True
                
        elif role == Qt.CheckStateRole:
            if col in self.chk_cols:
                self._data[row][col] = "TRUE" if value == Qt.Checked else "FALSE"
                self.dataChanged.emit(index, index)
                return True
                
        return False

    def flags(self, index):
        col = index.column()
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        
        # We explicitly omit Qt.ItemIsUserCheckable here because we manually
        # intercept single-clicks in TSVEditor.on_cell_clicked to prevent double-toggling.
        if col not in self.chk_cols and col not in self.ro_cols:
            flags |= Qt.ItemIsEditable
            
        return flags

# =====================================================================
# MAIN WINDOW & UI
# =====================================================================
class TSVEditor(QMainWindow):
    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath
        self.delimiter = ',' # Default, updated in load_data
        self.setWindowTitle(f"Editing: {os.path.basename(filepath)}")
        
        self.initUI()
        self.load_data()
        self.apply_column_sizing()

    def initUI(self):
        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)
        
        # Use our custom TableView class instead of the standard QTableView
        self.table = TSVTableView()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(False)
        
        # Allow smooth pixel-based scrolling horizontally, but keep item-based vertically
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerItem)
        
        # Intercept clicks for ultra-responsive editing
        self.table.clicked.connect(self.on_cell_clicked)
        
        # --- Bottom Control Bar ---
        bottom_layout = QHBoxLayout()
        
        # Status area for messages and calculation sums
        self.status_label = QLineEdit("")
        self.status_label.setReadOnly(True)
        self.status_label.setMinimumWidth(150)
        self.status_label.setPlaceholderText("Status")
        
        self.search_box = SearchLineEdit(self.perform_search)
        self.search_box.setPlaceholderText("Search")
        # Instantly search from start/current on text change
        self.search_box.textChanged.connect(lambda text: self.perform_search(direction=1, start_from_current=False))
        
        self.save_btn = QPushButton("SAVE")
        self.save_btn.clicked.connect(self.save_file)
        
        self.close_btn = QPushButton("CLOSE")
        self.close_btn.clicked.connect(self.close)
        
        bottom_layout.addWidget(self.status_label)
        bottom_layout.addWidget(self.search_box)
        bottom_layout.addWidget(self.save_btn)
        bottom_layout.addWidget(self.close_btn)
        
        layout.addWidget(self.table)
        layout.addLayout(bottom_layout)
        self.setCentralWidget(main_widget)
        
        # --- Invisible Edge Scrollbar ---
        self.edge_scrollbar = EdgeScrollBar(main_widget)
        real_sb = self.table.verticalScrollBar()
        real_sb.rangeChanged.connect(self.edge_scrollbar.setRange)
        real_sb.valueChanged.connect(self.edge_scrollbar.setValue)
        self.edge_scrollbar.valueChanged.connect(real_sb.setValue)
        
        # Keyboard Shortcuts
        self.shortcut_save = QShortcut(QKeySequence("Ctrl+S"), self)
        self.shortcut_save.activated.connect(self.save_file)

        self.shortcut_find = QShortcut(QKeySequence("Ctrl+F"), self)
        self.shortcut_find.activated.connect(self.focus_search)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Position the invisible scrollbar at the absolute right edge of the window,
        # spanning the vertical height of the table so it perfectly catches edge-thrown mouse clicks.
        if hasattr(self, 'edge_scrollbar') and self.centralWidget():
            cw = self.centralWidget()
            table_rect = self.table.geometry()
            sb_width = 25  # Wide enough to cover layout margins and guarantee an edge catch
            self.edge_scrollbar.setGeometry(
                cw.width() - sb_width,
                table_rect.y(),
                sb_width,
                table_rect.height()
            )

    def focus_search(self):
        self.search_box.setFocus()
        self.search_box.selectAll()

    def on_cell_clicked(self, index):
        """
        Forces immediate interaction on a single click (or Enter key)
        instead of requiring double-clicks.
        """
        col = index.column()
        if col in self.model.chk_cols:
            # Allows clicking/Enter anywhere in the cell box to toggle the checkbox
            current_state = self.model.data(index, Qt.CheckStateRole)
            new_state = Qt.Unchecked if current_state == Qt.Checked else Qt.Checked
            self.model.setData(index, new_state, Qt.CheckStateRole)
        elif col not in self.model.ro_cols:
            # Instantly drop into edit mode (or open the combobox)
            self.table.edit(index)

    def perform_search(self, direction=1, start_from_current=False):
        """
        Searches the table for the target text. Wraps around the edges.
        direction: 1 for forward/down, -1 for backward/up.
        start_from_current: If True, advances from current cell. If False, checks current, then starts.
        """
        text = self.search_box.text().lower()
        if not text:
            return

        row_count = self.model.rowCount()
        col_count = self.model.columnCount()
        if row_count == 0 or col_count == 0:
            return

        total_cells = row_count * col_count
        
        has_selection = self.table.selectionModel().hasSelection()
        current_index = self.table.currentIndex()

        # When typing (start_from_current=False), check if current selection already matches.
        if not start_from_current and has_selection and current_index.isValid():
            val = self.model.data(current_index, Qt.DisplayRole)
            if val is not None and text in str(val).lower():
                return  # Stay on current match

        # Determine starting coordinates
        if has_selection and current_index.isValid():
            start_row = current_index.row()
            start_col = current_index.column()
            
            if start_from_current:
                # Advance from current cell to avoid re-matching the same cell when hitting Enter
                start_col += direction
                if start_col >= col_count:
                    start_col = 0
                    start_row += 1
                elif start_col < 0:
                    start_col = col_count - 1
                    start_row -= 1
        else:
            # No selection active, grab the topmost visible row, but always start at column 0
            start_row = self.table.rowAt(0)
            if start_row == -1: 
                start_row = 0
            
            start_col = 0

        start_idx = start_row * col_count + start_col
        wrapped_initially = False
        
        # Normalize bounds in case we pushed past the end/beginning of the document
        if start_idx >= total_cells:
            start_idx = 0
            wrapped_initially = True
        elif start_idx < 0:
            start_idx = total_cells - 1
            wrapped_initially = True

        for i in range(total_cells):
            raw_idx = start_idx + (i * direction)
            curr_idx = raw_idx % total_cells
            r = curr_idx // col_count
            c = curr_idx % col_count
            
            index = self.model.index(r, c)
            val = self.model.data(index, Qt.DisplayRole)
            
            if val is not None and text in str(val).lower():
                self.table.setCurrentIndex(index)
                self.table.scrollTo(index)
                
                # Check if the search looped past the end or beginning
                if raw_idx >= total_cells or raw_idx < 0 or wrapped_initially:
                    self.show_status_message("Search wrapped", 2000)
                else:
                    # Clear wrap/no results messages if we found a straightforward result
                    if self.status_label.text() in ["Search wrapped", "No results found"]:
                        self.clear_status_message()
                return
                
        # If we complete the entire loop without returning, nothing matched
        self.show_status_message("No results found", 2000)

    def load_data(self):
        try:
            # Detect extension to set delimiter properly
            ext = os.path.splitext(self.filepath)[1].lower()
            self.delimiter = '\t' if ext == '.tsv' else ','

            # Use the built-in csv module to respect quotes protecting internal delimiters
            with open(self.filepath, 'r', encoding='utf-8', newline='') as f:
                reader = csv.reader(f, delimiter=self.delimiter)
                lines = list(reader)
                
            if not lines:
                raise ValueError("File is empty.")
                
            raw_headers = lines[0]
            data = lines[1:]
            
            self.model = TSVModel(data, raw_headers)
            self.table.setModel(self.model)
            
            self.delegate = CustomItemDelegate(self.model.cb_cols, self.table)
            self.table.setItemDelegate(self.delegate)
            
            # Connect selection model changes to calculate multi-cell sums
            self.table.selectionModel().selectionChanged.connect(self.update_sum_status)
            
            # Initial sync for the invisible edge scrollbar
            real_sb = self.table.verticalScrollBar()
            self.edge_scrollbar.setRange(real_sb.minimum(), real_sb.maximum())
            self.edge_scrollbar.setValue(real_sb.value())
            
        except Exception as e:
            QMessageBox.critical(self, "Error Loading File", str(e))
            sys.exit(1)

    def apply_column_sizing(self):
        # Calculates and sets the exact width needed for every column's content
        self.table.resizeColumnsToContents()

    def save_file(self):
        raw_headers = self.model._raw_headers
        data = self.model._data
        
        try:
            # Use the built-in csv module to properly construct quotes on saving
            with open(self.filepath, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f, delimiter=self.delimiter)
                
                # Write header row
                writer.writerow(raw_headers)
                
                for row in data:
                    padded_row = []
                    for col in range(len(raw_headers)):
                        val = row[col] if col < len(row) else ""
                        if col in self.model.chk_cols and str(val).strip() == "":
                            val = "FALSE"
                        padded_row.append(val)
                        
                    writer.writerow(padded_row)
                    
            self.show_status_message("Saved", 2000)
            print(f"Successfully saved to {self.filepath}")
            
        except Exception as e:
            QMessageBox.critical(self, "Error Saving File", str(e))

    def show_status_message(self, msg, timeout=2000):
        self.status_label.setPlaceholderText("") # Clear the initial tip forever
        self.status_label.setText(msg)
        # Clear the message after `timeout` milliseconds
        QTimer.singleShot(timeout, self.clear_status_message)

    def clear_status_message(self):
        # Only clear if it hasn't been overwritten by a new sum calculation
        if self.status_label.text() in ["Saved", "Search wrapped", "No results found"]:
            self.status_label.setText("")
            self.update_sum_status() # Re-check if we need to display a selection sum instead

    def update_sum_status(self):
        if not hasattr(self, 'table') or not self.table.selectionModel():
            return
            
        indexes = self.table.selectionModel().selectedIndexes()
        total = 0.0
        has_numbers = False
        
        # Only calculate/show sum if more than 1 cell is selected
        if len(indexes) > 1:
            for idx in indexes:
                val = self.model.data(idx, Qt.DisplayRole)
                if val:
                    # Clean currency symbols and formatting for float conversion
                    clean_str = str(val).replace('$', '').replace(',', '').strip()
                    try:
                        total += float(clean_str)
                        has_numbers = True
                    except ValueError:
                        pass
                        
        if has_numbers and len(indexes) > 1:
            self.status_label.setPlaceholderText("") # Clear the initial tip forever
            self.status_label.setText(f"Sum: {total:,.2f}")
        else:
            # Clear label if it's not currently displaying a temporary status message
            if self.status_label.text() not in ["Saved", "Search wrapped", "No results found"]:
                self.status_label.setText("")

# =====================================================================
# GLOBAL THEMING
# =====================================================================
def apply_futuristic_theme(app):
    """
    Applies a strict #000000 background and #00FF41 neon green text theme.
    Uses 12pt sans-serif text as the base font.
    Includes a subtle dark green prelight/hover effect for cells.
    """
    style_sheet = """
        QWidget {
            background-color: #000000;
            color: #00FF41;
            font-family: "Consolas", "Courier New", monospace;
            font-size: 12pt;
        }
        QLineEdit {
            background-color: #000000;
            color: #00FF41;
            border: 1px solid #00FF41;
            padding: 5px;
            selection-background-color: #00FF41;
            selection-color: #000000;
        }
        QTableView {
            background-color: #000000;
            gridline-color: #333333;
            border: 1px solid #00FF41;
            selection-background-color: #00FF41;
            selection-color: #000000;
        }
        QTableView::item:selected {
            background-color: #00FF41;
            color: #000000;
        }
        QTableView::item:hover:!selected {
            background-color: #002208; /* Subtle dark green prelight */
        }
        
        QMenu {
            background-color: #000000;
            color: #00FF41;
            border: 1px solid #00FF41;
        }
        QMenu::item {
            padding: 5px 25px 5px 25px;
            background-color: transparent;
        }
        QMenu::item:selected {
            background-color: #00FF41;
            color: #000000;
        }
        QMenu::separator {
            height: 1px;
            background: #00FF41;
            margin-left: 5px;
            margin-right: 5px;
        }

        QComboBox {
            background-color: #000000;
            color: #00FF41;
            border: 1px solid #00FF41;
            selection-background-color: #00FF41;
            selection-color: #000000;
        }
        QComboBox QAbstractItemView {
            background-color: #000000;
            color: #00FF41;
            border: 1px solid #00FF41;
            selection-background-color: #00FF41;
            selection-color: #000000;
            outline: none;
        }
        QComboBox QAbstractItemView::item:selected,
        QComboBox QAbstractItemView::item:hover {
            background-color: #00FF41;
            color: #000000;
        }
        
        QHeaderView::section {
            background-color: #0a0a0a;
            color: #00FF41;
            border: 1px solid #333333;
            padding: 4px;
            font-weight: bold;
        }
        QTableCornerButton::section {
            background-color: #0a0a0a;
            border: 1px solid #333333;
        }
        
        QPushButton {
            background-color: #000000;
            color: #00FF41;
            border: 2px solid #00FF41;
            padding: 10px;
            font-weight: bold;
            letter-spacing: 2px;
        }
        QPushButton:hover {
            background-color: #00FF41;
            color: #000000;
        }
        QPushButton:pressed {
            background-color: #008822;
        }
    """
    app.setStyleSheet(style_sheet)

# =====================================================================
# ENTRY POINT
# =====================================================================
if __name__ == '__main__':
    # Globally suppress the harmless edit warnings
    qInstallMessageHandler(qt_message_handler)

    if len(sys.argv) < 2:
        print("Usage: ./tsv_editor.py <path_to_tsv_or_csv_file>")
        sys.exit(1)
        
    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' does not exist.")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    apply_futuristic_theme(app)
    
    editor = TSVEditor(filepath)
    editor.showMaximized()
    sys.exit(app.exec_())
