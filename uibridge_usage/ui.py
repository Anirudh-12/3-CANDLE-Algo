import sys
import atexit
from PyQt6.QtWidgets import (
    QApplication, QWidget, QGridLayout, QLabel,
    QLineEdit, QPushButton, QHBoxLayout, QCheckBox,
    QVBoxLayout, QFrame, QSizePolicy, QComboBox,
    QTableWidget, QTableWidgetItem
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from uibridge import UIBridge

# ---------------------------------------------------------
# Styles & Constants
# ---------------------------------------------------------
STYLESHEET = """
QWidget {
    background-color: #121418;
    color: #e0e0e0;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}
QFrame#Panel {
    background-color: #1a1c21;
    border: 1px solid #333;
    border-radius: 4px;
}
QLabel {
    font-weight: 600;
}
QLineEdit {
    background-color: #000000;
    color: #ffffff;
    border: 1px solid #444;
    border-radius: 2px;
    padding: 2px;
    font-weight: bold;
    font-size: 14px;
}
QPushButton {
    border-radius: 3px;
    font-weight: bold;
}
QCheckBox {
    spacing: 5px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #555;
    background: #222;
}
QCheckBox::indicator:checked {
    background-color: #1e8e3e;
    border-color: #1e8e3e;
}
QHeaderView::section {
    background-color: #252830;
    color: #bbb;
    padding: 4px;
    border: none;
    font-weight: bold;
}
QTableWidget {
    background-color: #16181d;
    gridline-color: #333;
    border: 1px solid #333;
}
QScrollBar:vertical {
    background: #1a1c21;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: #444;
    border-radius: 5px;
}
"""

COLOR_GREEN = "#1e8e3e"
COLOR_RED = "#d93025"
COLOR_BLUE = "#1976d2"
COLOR_ORANGE = "#f57c00"
COLOR_TEXT_MUTED = "#999999"

# ---------------------------------------------------------
# Custom Widgets
# ---------------------------------------------------------

class ValueAdjustWidget(QWidget):
    """
    [ VALUE ] [ + ] [ - ]
    Strictly horizontal, fixed width buttons.
    """
    def __init__(self, value, fixed_width=None):
        super().__init__()
        self.value = value
        
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.setLayout(layout)

        # VALUE
        self.line_edit = QLineEdit(str(self.value))
        self.line_edit.setReadOnly(True)
        self.line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if fixed_width:
            self.line_edit.setFixedWidth(fixed_width)
        else:
            self.line_edit.setMinimumWidth(60)
        
        # [+]
        self.btn_plus = QPushButton("+")
        self.btn_plus.setFixedSize(28, 28)
        self.btn_plus.setStyleSheet(f"background-color: {COLOR_GREEN}; color: white; border: none;")
        
        # [-]
        self.btn_minus = QPushButton("−")
        self.btn_minus.setFixedSize(28, 28)
        self.btn_minus.setStyleSheet(f"background-color: {COLOR_RED}; color: white; border: none;")

        layout.addWidget(self.line_edit)
        layout.addWidget(self.btn_plus)
        layout.addWidget(self.btn_minus)


class HeaderBar(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(15)
        self.setLayout(layout)

        # Symbol & Price
        self.lbl_sym = QLabel("NF 25727.5")
        self.lbl_sym.setStyleSheet("font-size: 16px; font-weight: bold; color: white;")
        
        self.lbl_chg = QLabel("-147.49")
        self.lbl_chg.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_RED};")

        # Virtual Toggle
        self.lbl_virt = QLabel("VIRTUAL")
        self.lbl_virt.setStyleSheet(f"color: {COLOR_ORANGE}; font-weight: bold;")
        self.tgl_virt = QCheckBox() # Simple checkbox for now, styled as toggle if possible
        
        # Date Selector
        self.combo_date = QComboBox()
        self.combo_date.addItems(["13-JAN-202X"])
        self.combo_date.setStyleSheet("background: #222; color: white; border: 1px solid #444; padding: 3px;")

        # RUN button
        self.btn_run = QPushButton("RUN")
        self.btn_run.setStyleSheet("background: #333; color: white; border: 1px solid #555; padding: 4px 10px;")

        # Status Indicators
        self.lbl_trade = QLabel(" TRADE ")
        self.lbl_trade.setStyleSheet(f"background: {COLOR_GREEN}; color: black; font-weight: bold; padding: 2px;")
        
        self.lbl_key = QLabel(" KEY ")
        self.lbl_key.setStyleSheet(f"background: {COLOR_RED}; color: black; font-weight: bold; padding: 2px;")

        # Add widgets
        layout.addWidget(self.lbl_sym)
        layout.addWidget(self.lbl_chg)
        layout.addStretch()
        layout.addWidget(self.lbl_virt)
        layout.addWidget(self.tgl_virt)
        layout.addWidget(self.combo_date)
        layout.addWidget(self.btn_run)
        layout.addWidget(self.lbl_trade)
        layout.addWidget(self.lbl_key)


class StatsPanel(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Panel")
        layout = QHBoxLayout()
        layout.setContentsMargins(15, 8, 15, 8)
        self.setLayout(layout)

        # CE/PE Data
        self.lbl_ce = QLabel("CE: 12.89 Cr")
        self.lbl_ce.setStyleSheet(f"color: {COLOR_RED}; font-size: 14px;")
        
        self.lbl_pe = QLabel("PE: 6.19 Cr")
        self.lbl_pe.setStyleSheet(f"color: {COLOR_GREEN}; font-size: 14px; margin-left: 10px;")

        # PNL
        self.lbl_pnl_title = QLabel("PNL:")
        self.lbl_pnl_title.setStyleSheet("color: #ccc; font-size: 14px; margin-left: 40px;")
        
        self.lbl_pnl_val = QLabel("3230.50")
        self.lbl_pnl_val.setStyleSheet(f"color: {COLOR_GREEN}; font-size: 18px; font-weight: bold;")

        layout.addWidget(self.lbl_ce)
        layout.addWidget(self.lbl_pe)
        layout.addStretch()
        layout.addWidget(self.lbl_pnl_title)
        layout.addWidget(self.lbl_pnl_val)


class StartStopRow(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.setLayout(layout)

        self.btn_start = QPushButton("START")
        self.btn_start.setFixedHeight(35)
        self.btn_start.setStyleSheet(f"background-color: {COLOR_GREEN}; color: black; font-size: 14px;")
        
        self.lbl_status = QLabel("STOPPED")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setFixedHeight(35)
        self.lbl_status.setStyleSheet("background-color: #252830; color: white; font-weight: bold; border-radius: 3px;")

        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setFixedHeight(35)
        self.btn_stop.setStyleSheet(f"background-color: {COLOR_RED}; color: black; font-size: 14px;")

        layout.addWidget(self.btn_start, 1)
        layout.addWidget(self.lbl_status, 2)
        layout.addWidget(self.btn_stop, 1)


class MainControlGrid(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Panel")
        self.grid = QGridLayout()
        self.grid.setSpacing(12)
        self.grid.setContentsMargins(15, 15, 15, 15)
        self.setLayout(self.grid)

        # Helper to add labels
        def lbl(text, row, col, color=None):
            l = QLabel(text)
            if color:
                l.setStyleSheet(f"color: {color};")
            else:
                l.setStyleSheet("color: #cccccc;")
            # Right align labels for better visual
            l.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.grid.addWidget(l, row, col)

        # --- Row 0: SECS | PREM | OI ---
        lbl("SECS", 0, 0)
        self.grid.addWidget(ValueAdjustWidget(10), 0, 1)
        
        lbl("PREM", 0, 2)
        self.grid.addWidget(ValueAdjustWidget(160), 0, 3)

        lbl("OI", 0, 4)
        # Toggle Switch (Visual approximation)
        tgl_oi = QCheckBox() # Custom styling in CSS makes this look cleaner
        tgl_oi.setChecked(True)
        tgl_oi.setStyleSheet(f"""
            QCheckBox::indicator:checked {{
                background-color: {COLOR_GREEN};
                border-radius: 8px;
                width: 32px;
            }}
        """)
        self.grid.addWidget(tgl_oi, 0, 5)

        # --- Row 1: INQTY | ADD | MAX ---
        lbl("INQTY", 1, 0)
        self.grid.addWidget(ValueAdjustWidget(130), 1, 1)

        lbl("ADD", 1, 2)
        self.grid.addWidget(ValueAdjustWidget(65), 1, 3)

        lbl("MAX", 1, 4)
        self.grid.addWidget(ValueAdjustWidget(130), 1, 5)

        # --- Row 2: FORCE | BOTH | BUY CE | BUY PE ---
        lbl("FORCE", 2, 0, COLOR_ORANGE)
        
        # ComboBox for BOTH/CE/PE
        force_combo = QComboBox()
        force_combo.addItems(["BOTH", "CE", "PE"])
        force_combo.setStyleSheet("background: #252830; padding: 5px;")
        self.grid.addWidget(force_combo, 2, 1)

        btn_buy_ce = QPushButton("BUY CE")
        btn_buy_ce.setFixedHeight(30)
        btn_buy_ce.setStyleSheet(f"background-color: {COLOR_GREEN}; color: black;")
        self.grid.addWidget(btn_buy_ce, 2, 2, 1, 2) # Span 2 cols

        btn_buy_pe = QPushButton("BUY PE")
        btn_buy_pe.setFixedHeight(30)
        btn_buy_pe.setStyleSheet(f"background-color: {COLOR_RED}; color: black;")
        self.grid.addWidget(btn_buy_pe, 2, 4, 1, 2) # Span 2 cols

        # --- Row 3: PTGT | FTGT ---
        lbl("PTGT", 3, 0, COLOR_GREEN)
        self.grid.addWidget(ValueAdjustWidget(4), 3, 1)

        lbl("FTGT", 3, 2, COLOR_GREEN)
        self.grid.addWidget(ValueAdjustWidget(8), 3, 3)

        # Empty slot or spacer? Image shows + - buttons here too on right?
        # Actually in image FTGT is followed by [ + ] [ - ]. 
        # But wait, there's another [ + ] [ - ] pair next to FTGT's controller?
        # In image: [FTGT] [ 8 ] [+][-] ...... [+][-]
        # It looks like FTGT has 8, but then there's an empty control set?
        # Let's stick to the spec: "FTGT [8][+][-]"
        # The image shows FTGT [8] [+] [-] then another [+][-] below MAX?
        # No, looking at Row 4 in image:
        # PTGT [ 4 ][+][-]   FTGT [ 8 ][+][-]   [+][-] (Empty?)
        # Let's just put placeholders if needed, but for now stick to core.
        
        # --- Row 4: SL | EXIT | PART ---
        lbl("SL", 4, 0, COLOR_RED)
        self.grid.addWidget(ValueAdjustWidget(0), 4, 1)

        lbl("EXIT", 4, 2)
        self.grid.addWidget(ValueAdjustWidget(65), 4, 3)

        btn_part = QPushButton("PART")
        btn_part.setStyleSheet("background-color: #3e2723; color: #8d6e63; border: 1px solid #4e342e;")
        self.grid.addWidget(btn_part, 4, 5)

        # --- Row 5: RE-GAP | Checkboxes ---
        lbl("RE-GAP", 5, 0)
        self.grid.addWidget(ValueAdjustWidget(2), 5, 1)

        # Checkboxes
        chk_tgt2 = QCheckBox("Continue after\nTarget-2")
        self.grid.addWidget(chk_tgt2, 5, 3)

        chk_sl = QCheckBox("Continue after\nSL")
        self.grid.addWidget(chk_sl, 5, 5)


class PositionsTable(QTableWidget):
    def __init__(self):
        super().__init__(0, 5)
        self.setHorizontalHeaderLabels(["Sym", "Qty", "Avg", "LTP", "P&L"])
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        # Example Data
        self.add_row("NIFTY13JAN26P26000", "0", "0.00", "330.30", "1849.25", COLOR_GREEN)
        self.add_row("NIFTY13JAN26P25900", "0", "0.00", "231.75", "1381.25", COLOR_GREEN)

    def add_row(self, sym, qty, avg, ltp, pnl, pnl_color):
        row = self.rowCount()
        self.insertRow(row)
        
        self.setItem(row, 0, QTableWidgetItem(sym))
        self.setItem(row, 1, QTableWidgetItem(qty))
        self.setItem(row, 2, QTableWidgetItem(avg))
        self.setItem(row, 3, QTableWidgetItem(ltp))
        
        pnl_item = QTableWidgetItem(pnl)
        pnl_item.setForeground(QColor(pnl_color))
        self.setItem(row, 4, pnl_item)


class TradingWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt6 Trading UI Clone")
        self.resize(650, 600)
        self.setStyleSheet(STYLESHEET)

        # Main Vertical Layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(1, 1, 1, 1)
        main_layout.setSpacing(5)
        self.setLayout(main_layout)

        # 1. Header
        main_layout.addWidget(HeaderBar())

        # 2. Stats Panel
        main_layout.addWidget(StatsPanel())

        # 3. Controls Grid (Inside a generic wrapper for margins)
        grid_wrapper = QWidget()
        grid_layout = QVBoxLayout()
        grid_layout.setContentsMargins(10, 0, 10, 0)
        grid_wrapper.setLayout(grid_layout)
        
        self.controls = MainControlGrid()
        grid_layout.addWidget(self.controls)
        
        # 4. Start/Stop Action Bar
        self.action_bar = StartStopRow()
        grid_layout.addWidget(self.action_bar)
        
        main_layout.addWidget(grid_wrapper)

        # 5. Positions Table
        # Header for table section
        table_header = QLabel("POSITIONS                                ORDERS")
        table_header.setStyleSheet("background: #252830; color: white; padding: 5px; font-weight: bold;")
        table_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(table_header)

        self.table = PositionsTable()
        main_layout.addWidget(self.table)


def ui_main(backend_to_ui, ui_to_backend):
    bridge = UIBridge(backend_to_ui, ui_to_backend)
    bridge.start_listener()

    def on_exit():
        bridge.shutdown()
    atexit.register(on_exit)

    # High DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    app = QApplication(sys.argv)
    window = TradingWindow()
    window.show()
    sys.exit(app.exec())


