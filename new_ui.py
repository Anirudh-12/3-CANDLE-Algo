import sys
import atexit
import json
import math
import threading
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QWidget, QGridLayout, QLabel,
    QLineEdit, QPushButton, QHBoxLayout, QCheckBox,
    QVBoxLayout, QFrame, QSizePolicy, QComboBox,
    QTableWidget, QTableWidgetItem, QMessageBox, QHeaderView,
    QStackedWidget, QScrollArea, QAbstractItemView
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QSize, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QIntValidator, QDoubleValidator, QCursor
from bi_rpc import RpcHandler
import logging
logging.disable(logging.CRITICAL)

import sys
sys.stderr = open("nul", "w")
sys.stdout = open("nul", "w")

import ctypes
try:
    ctypes.windll.winmm.timeBeginPeriod(1)
except Exception:
    pass

import os
os.environ.setdefault("PYTHONUNBUFFERED", "1")

# Reduce Windows background throttling hints
try:
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000002)
except Exception:
    pass

# ---------------------------------------------------------
# Styles & Constants
# ---------------------------------------------------------
STYLESHEET = """
QWidget {
    background-color: #0b0f14;
    color: #e0e0e0;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 11px;
}
QFrame#Panel, QFrame#StrategyBox, QFrame#DataSection, QFrame#CredentialsPanel {
    background-color: #151a21;
    border: 1px solid #2a2f38;
    border-radius: 4px;
}
QLabel {
    font-weight: 600;
}
QLineEdit {
    background-color: #000000;
    color: #ffffff;
    border: 1px solid #333;
    border-radius: 2px;
    padding: 2px;
    font-weight: bold;
    font-size: 12px;
    selection-background-color: #4b5563;
}
QPushButton {
    border: none;
    outline: none;
    border-radius: 3px;
    font-weight: bold;
}
QPushButton:disabled {
    opacity: 0.4;
    background-color: #374151; /* Fallback */
}
QCheckBox {
    spacing: 5px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #555;
    background: #222;
    border-radius: 2px;
}
QCheckBox::indicator:checked {
    background-color: #22c55e;
    border-color: #22c55e;
}
QComboBox {
    background: #1f2937;
    color: #fff;
    border: 1px solid #374151;
    border-radius: 4px;
    padding: 2px 4px;
    font-size: 10px;
    min-height: 18px;
}
QComboBox QAbstractItemView {
    background-color: #1f2937;
    color: white;
    selection-background-color: #374151;
}

/* Header */
QFrame#TopBar {
    background-color: #111827;
    border-bottom: 1px solid #2a2f38;
}

/* Scrollbars */
QScrollBar:vertical {
    background: #1a1c21;
    width: 6px;
    margin: 0px 0px 0px 0px;
}
QScrollBar::handle:vertical {
    background: #333;
    min-height: 20px;
    border-radius: 3px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* Table */
QTableWidget {
    background-color: #151a21;
    border: none;
    gridline-color: #2a2f38;
    font-size: 10px;
}
QHeaderView::section {
    background-color: #111827;
    color: #9ca3af;
    padding: 4px;
    border: none;
    border-bottom: 1px solid #374151;
    font-weight: normal;
}
QTableWidget::item {
    padding: 2px;
    border-bottom: 1px solid #2a2f38;
}
QTableWidget::item:selected {
    background-color: #2a2f38;
}
"""

COLOR_GREEN = "#22c55e"  # Tailwind green-500
COLOR_RED = "#ef4444"    # Tailwind red-500
COLOR_BLUE = "#3b82f6"   # Tailwind blue-500
COLOR_ORANGE = "#f59e0b" # Tailwind amber-500
COLOR_YELLOW = "#facc15" # Tailwind yellow-400
COLOR_CYAN = "#06b6d4"   # Tailwind cyan-500
COLOR_PURPLE = "#a855f7" # Tailwind purple-500
COLOR_DARK_BG = "#0b0f14"
COLOR_PANEL_BG = "#151a21"
COLOR_TEXT_MUTED = "#9ca3af"

# ---------------------------------------------------------
# Helper Widgets
# ---------------------------------------------------------

def format_indian_number(n):
    """Format number with L (Lakhs) or Cr (Crores) suffix if large enough"""
    try:
        val = float(n)
        abs_val = abs(val)
        
        if abs_val >= 10000000: # 1 Crore
            return f"{val/10000000:.2f} Cr"
        elif abs_val >= 100000: # 1 Lakh
            return f"{val/100000:.2f} L"
        else:
            # Fallback to standard comma separator
            return f"{val:,.0f}"
    except:
        return str(n)


class StepperButton(QPushButton):
    def __init__(self, text, color, parent=None):
        super().__init__(text, parent)
        # HARD-LOCKED SIZE - Never expand, never shrink
        self.setFixedSize(22, 24)
        self.setMinimumSize(22, 24)
        self.setMaximumSize(22, 24)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 2px;
            }}
            QPushButton:hover {{
                background-color: {color}dd;
            }}
            QPushButton:pressed {{
                background-color: {color}aa;
            }}
        """)

class GridValueInput(QLineEdit):
    def __init__(self, text="", parent=None, width=None):
        super().__init__(str(text), parent)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        # TRIPLE-LOCKED WIDTH - Fixed, Min, Max all same
        w = width if width else 55
        self.setFixedWidth(w)
        self.setMinimumWidth(w)
        self.setMaximumWidth(w)
        self.setFixedHeight(24)
        self.setMinimumHeight(24)
        self.setMaximumHeight(24)
        
        # HARD SIZE POLICY - Never expand
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("padding-left: 4px; padding-right: 4px;")
        
        self.setValidator(QIntValidator()) # Default to int

class TabButton(QPushButton):
    def __init__(self, text, color=None, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setFixedHeight(24)
        self.cursor_color = color
        self.base_style = """
            QPushButton {
                background-color: transparent;
                color: #9ca3af;
                padding: 2px 8px;
                font-size: 10px;
                border: none;
                border-radius: 2px;
                font-weight: bold;
            }
            QPushButton:checked {
                color: #ffffff;
                background-color: %s;
            }
            QPushButton:hover {
                color: #e0e0e0;
            }
        """ % (color if color else "#4b5563")
        self.setStyleSheet(self.base_style)

class DataTabButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setFixedHeight(26)
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #9ca3af;
                font-size: 10px;
                font-weight: bold;
                border: none;
            }
            QPushButton:checked {
                background-color: #374151;
                color: #fff;
            }
            QPushButton:hover {
                 color: #fff;
            }
        """)

class Header(QFrame):
    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.setObjectName("TopBar")
        self.setFixedHeight(32)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(10)
        
        # Left: Market Data
        self.lbl_sym_name = QLabel("NF")
        self.lbl_sym_name.setStyleSheet("color: white; font-size: 10px; background-color: transparent;")
        
        self.lbl_ltp = QLabel("0.00")
        self.lbl_ltp.setStyleSheet("color: white; font-size: 14px; background-color: transparent;")
        self.lbl_ltp.setMinimumWidth(60)
        
        self.lbl_change = QLabel("0.00")
        self.lbl_change.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px; background-color: transparent;")
        self.lbl_change.setMinimumWidth(40)
        # Virtual Toggle
        self.lbl_virt = QLabel("VIRTUAL")
        self.lbl_virt.setStyleSheet(f"color: {COLOR_YELLOW}; font-size: 9px;font-weight: bold; background-color: transparent;margin-left: 4px;")
        
        self.chk_virt = QCheckBox()
        self.chk_virt.setFixedSize(32, 16)
        # Custom style for small toggle
        self.chk_virt.setStyleSheet("""
            QCheckBox::indicator { width: 32px; height: 16px; border-radius: 8px;border: none; }
            QCheckBox::indicator:checked { background: #facc15; }
        """)
        self.chk_virt.toggled.connect(self.on_virtual_toggled)

        # Right: Controls
        self.combo_expiry = QComboBox()
        self.combo_expiry.setFixedWidth(85)
        self.combo_expiry.currentTextChanged.connect(self.on_expiry_changed)
        
        self.btn_run = QPushButton("RUN")
        self.btn_run.setFixedSize(40, 22)
        self.btn_run.setStyleSheet(f"background-color: #374151; color: white; font-size: 10px;")
        self.btn_run.clicked.connect(self.on_run_clicked)
        self.btn_run.setEnabled(True) # Enabled by default now

        # Tabs
        self.btn_tab_trade = TabButton("TRADE", COLOR_GREEN)
        self.btn_tab_key = TabButton("KEY", COLOR_RED)
        self.btn_tab_trade.setChecked(True) # Default
        
        # Tab Group
        self.tab_group = QFrame()
        self.tab_group.setStyleSheet("background: #1f2937; border-radius: 4px; padding: 1px;")
        tab_layout = QHBoxLayout(self.tab_group)
        tab_layout.setContentsMargins(0,0,0,0)
        tab_layout.setSpacing(2)
        tab_layout.addWidget(self.btn_tab_trade)
        tab_layout.addWidget(self.btn_tab_key)

        layout.addWidget(self.lbl_sym_name)
        layout.addWidget(self.lbl_ltp)
        layout.addWidget(self.lbl_change)
        
        # Separator line logic handled by spacing/borders usually, mimicking CSS
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("border-left: 1px solid #2a2f38;")
        line.setFixedHeight(16)
        layout.addWidget(line)
        
        layout.addWidget(self.lbl_virt)
        layout.addWidget(self.chk_virt)
        
        layout.addStretch()
        
        layout.addWidget(self.combo_expiry)
        layout.addWidget(self.btn_run)
        layout.addWidget(self.tab_group)

    def on_virtual_toggled(self, checked):
        # In CSS this calls toggleVirtualMode(checked) which calls eel
        if self.bridge:
            self.bridge.notify("toggle_virtual", checked)

    def on_expiry_changed(self, text):
        if self.bridge and text:
            self.bridge.call("set_expiry", text)

    def on_run_clicked(self):
        txt = self.btn_run.text()
        if txt == "RUN":
             # Run in thread to avoid freezing UI during connection/startup
             threading.Thread(target=lambda: self.bridge.call("start_trading"), daemon=True).start()
        else:
             threading.Thread(target=lambda: self.bridge.call("stop_trading"), daemon=True).start()

    def set_run_state(self, running):
        if running:
            self.btn_run.setText("STOP")
            self.btn_run.setStyleSheet(f"background-color: {COLOR_RED}; color: white; font-size: 10px;")
        else:
            self.btn_run.setText("RUN")
            self.btn_run.setStyleSheet(f"background-color: #374151; color: white; font-size: 10px;")

    def update_market(self, data):
        if "nifty_ltp" in data:
            self.lbl_ltp.setText(str(data["nifty_ltp"]))
        if "nifty_change" in data:
            val = float(data["nifty_change"])
            self.lbl_change.setText(f"{val:.2f}")
            self.lbl_change.setStyleSheet(f"font-size: 12px; color: {COLOR_GREEN if val >= 0 else COLOR_RED}; background-color: transparent;")


class StrategyPanel(QFrame):
    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.lot_size = 65
        self.setObjectName("StrategyBox")

        main = QVBoxLayout(self)
        main.setContentsMargins(6, 6, 6, 6)
        main.setSpacing(4)

        # ── Header: OI + PNL ──────────────────────────────────────
        hdr = QFrame()
        hdr.setStyleSheet("border-bottom: 1px solid #2a2f38;")
        hdr.setFixedHeight(28)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(0, 0, 0, 4)

        self.oi_lbl_ce_t = QLabel("CE:")
        self.oi_lbl_ce_t.setStyleSheet("color:white;font-size:11px;")
        self.oi_lbl_ce_v = QLabel("")
        self.oi_lbl_ce_v.setStyleSheet(f"color:{COLOR_RED};font-size:12px;font-weight:bold;min-width:40px;")
        self.oi_lbl_pe_t = QLabel("PE:")
        self.oi_lbl_pe_t.setStyleSheet("color:white;font-size:11px;margin-left:8px;")
        self.oi_lbl_pe_v = QLabel("")
        self.oi_lbl_pe_v.setStyleSheet(f"color:{COLOR_GREEN};font-size:12px;font-weight:bold;min-width:40px;")
        self.toggle_oi = QCheckBox("OI")
        self.toggle_oi.setChecked(True)
        self.toggle_oi.setStyleSheet("""
            QCheckBox{color:white;font-size:10px;font-weight:600;spacing:4px;}
            QCheckBox::indicator{width:28px;height:14px;border-radius:7px;background:#374151;border:none;}
            QCheckBox::indicator:checked{background:#22c55e;}
        """)
        self.lbl_pnl_t = QLabel("PNL:")
        self.lbl_pnl_t.setStyleSheet("color:white;font-weight:bold;font-size:12px;")
        self.lbl_pnl_v = QLabel("0.00")
        self.lbl_pnl_v.setMinimumWidth(100)
        self.lbl_pnl_v.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_pnl_v.setStyleSheet("color:#06b6d4;font-weight:bold;font-size:18px;")

        hl.addWidget(self.oi_lbl_ce_t); hl.addWidget(self.oi_lbl_ce_v)
        hl.addWidget(self.oi_lbl_pe_t); hl.addWidget(self.oi_lbl_pe_v)
        hl.addStretch(); hl.addWidget(self.toggle_oi); hl.addStretch()
        hl.addWidget(self.lbl_pnl_t); hl.addWidget(self.lbl_pnl_v)
        main.addWidget(hdr)

        # ── Section A: Pre-Market & Parameters Grid Layout ────────
        grid_params = QGridLayout()
        grid_params.setSpacing(4)
        grid_params.setHorizontalSpacing(8) # Add a nice horizontal spacing between elements
        grid_params.setVerticalSpacing(6)   # Add a nice vertical spacing between rows

        # Helper function for parameters (defined early so we can use it in Pre-Market section)
        def mk_param(label, attr, val, step=1, is_float=False, width=55, color="white"):
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{color};font-size:10px;font-weight:600;")
            inp = GridValueInput(val, width=width)
            inp.setValidator(QDoubleValidator())
            btn_p = StepperButton("+", COLOR_GREEN)
            btn_m = StepperButton("-", COLOR_RED)
            btn_p.clicked.connect(lambda _, i=inp: self.step_param(i, step, is_float))
            btn_m.clicked.connect(lambda _, i=inp: self.step_param(i, -step, is_float))
            setattr(self, attr, inp)
            return lbl, inp, btn_p, btn_m

        # Row 0: Pre-Market Status & Limits
        lbl_pm = QLabel("PRE-MKT")
        lbl_pm.setStyleSheet("color:#9ca3af;font-size:10px;font-weight:600;")
        self.lbl_premarket = QLabel("NOT CHECKED")
        self.lbl_premarket.setStyleSheet("color:#9ca3af;font-size:10px;font-weight:bold;background:#1f2937;padding:2px 6px;border-radius:3px;")
        
        lbl_pml, self.inp_pm_limit, b_pml_p, b_pml_m = mk_param("PMLMT", "inp_pm_limit", 100, step=10, width=55)

        lbl_mv = QLabel("MOVE")
        lbl_mv.setStyleSheet("color:#9ca3af;font-size:10px;")
        self.lbl_pm_move = QLabel("0")
        self.lbl_pm_move.setStyleSheet("color:white;font-size:10px;font-weight:bold;")
        lbl_rng = QLabel("RANGE")
        lbl_rng.setStyleSheet("color:#9ca3af;font-size:10px;")
        self.lbl_pm_range = QLabel("0")
        self.lbl_pm_range.setStyleSheet("color:white;font-size:10px;font-weight:bold;")

        # Col 0-3: PRE-MKT info
        grid_params.addWidget(lbl_pm, 0, 0)
        grid_params.addWidget(self.lbl_premarket, 0, 1, 1, 3)

        # Col 4-7: PMLMT
        grid_params.addWidget(lbl_pml, 0, 4)
        grid_params.addWidget(self.inp_pm_limit, 0, 5)
        grid_params.addWidget(b_pml_p, 0, 6)
        grid_params.addWidget(b_pml_m, 0, 7)
        self.inp_pm_limit.editingFinished.connect(self._push_config)

        # Spans Col 8-11: right-aligned MOVE/RANGE
        pm_right_layout = QHBoxLayout()
        pm_right_layout.setContentsMargins(0, 0, 0, 0)
        pm_right_layout.setSpacing(4)
        pm_right_layout.addStretch()
        pm_right_layout.addWidget(lbl_mv)
        pm_right_layout.addWidget(self.lbl_pm_move)
        pm_right_layout.addSpacing(8)
        pm_right_layout.addWidget(lbl_rng)
        pm_right_layout.addWidget(self.lbl_pm_range)
        grid_params.addLayout(pm_right_layout, 0, 8, 1, 4)

        # Row 1: TMIN, TMAX, BUF
        lbl_tmin, self.inp_trig_min,   b_tmin_p, b_tmin_m   = mk_param("TMIN", "inp_trig_min", 25, step=1, width=55)
        lbl_tmax, self.inp_trig_max,   b_tmax_p, b_tmax_m   = mk_param("TMAX", "inp_trig_max", 45, step=1, width=55)
        lbl_buf,  self.inp_break_buf,  b_buf_p,  b_buf_m    = mk_param("BUF",  "inp_break_buf", 2, step=1, width=55)

        for lbl, inp, bp, bm, col in [(lbl_tmin, self.inp_trig_min, b_tmin_p, b_tmin_m, 0),
                                      (lbl_tmax, self.inp_trig_max, b_tmax_p, b_tmax_m, 4),
                                      (lbl_buf,  self.inp_break_buf, b_buf_p, b_buf_m, 8)]:
            grid_params.addWidget(lbl, 1, col)
            grid_params.addWidget(inp, 1, col+1)
            grid_params.addWidget(bp, 1, col+2)
            grid_params.addWidget(bm, 1, col+3)
            inp.editingFinished.connect(self._push_config)

        # Row 2: T1%, T2%, T3x
        lbl_t1p,  self.inp_t1_pct,     b_t1p_p,  b_t1p_m     = mk_param("T1%",  "inp_t1_pct",   0.5, step=0.1, is_float=True, color=COLOR_GREEN, width=55)
        lbl_t2p,  self.inp_t2_pct,     b_t2p_p,  b_t2p_m     = mk_param("T2%",  "inp_t2_pct",   1.0, step=0.1, is_float=True, color=COLOR_GREEN, width=55)
        lbl_t3,   self.inp_t3_mult,    b_t3_p,   b_t3_m      = mk_param("T3x",  "inp_t3_mult",   2, step=1, color=COLOR_CYAN, width=55)

        for lbl, inp, bp, bm, col in [(lbl_t1p, self.inp_t1_pct, b_t1p_p, b_t1p_m, 0),
                                      (lbl_t2p, self.inp_t2_pct, b_t2p_p, b_t2p_m, 4),
                                      (lbl_t3,   self.inp_t3_mult, b_t3_p, b_t3_m, 8)]:
            grid_params.addWidget(lbl, 2, col)
            grid_params.addWidget(inp, 2, col+1)
            grid_params.addWidget(bp, 2, col+2)
            grid_params.addWidget(bm, 2, col+3)
            inp.editingFinished.connect(self._push_config)

        # Row 3: Quantities (InQTY / T1QTY / T2QTY)
        def mk_qty(label, attr, val, color="white"):
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{color};font-size:10px;font-weight:600;")
            inp = GridValueInput(val, width=55)
            btn_p = StepperButton("+", COLOR_GREEN)
            btn_m = StepperButton("-", COLOR_RED)
            btn_p.clicked.connect(lambda _, i=inp: self.step_qty(i, 1))
            btn_m.clicked.connect(lambda _, i=inp: self.step_qty(i, -1))
            setattr(self, attr, inp)
            return lbl, inp, btn_p, btn_m

        lbl_iq, self.inp_initial_qty, bip, bim = mk_qty("InQTY", "inp_initial_qty", 130)
        lbl_t1, self.inp_t1_qty,      b1p, b1m = mk_qty("T1QTY","inp_t1_qty",       65, COLOR_GREEN)
        lbl_t2, self.inp_t2_qty,      b2p, b2m = mk_qty("T2QTY","inp_t2_qty",        0, COLOR_ORANGE)

        for lbl, inp, bp, bm, col in [(lbl_iq, self.inp_initial_qty, bip, bim, 0),
                                      (lbl_t1, self.inp_t1_qty, b1p, b1m, 4),
                                      (lbl_t2, self.inp_t2_qty, b2p, b2m, 8)]:
            grid_params.addWidget(lbl, 3, col)
            grid_params.addWidget(inp, 3, col+1)
            grid_params.addWidget(bp, 3, col+2)
            grid_params.addWidget(bm, 3, col+3)
            inp.editingFinished.connect(self._push_config)

        # Row 4: Start and Stop Times
        def mk_time_input(label, attr, val, color="white"):
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{color};font-size:10px;font-weight:600;")
            inp = GridValueInput(val, width=55)
            btn_p = StepperButton("+", COLOR_GREEN)
            btn_m = StepperButton("-", COLOR_RED)
            btn_p.clicked.connect(lambda _, i=inp: self.step_time(i, 5))
            btn_m.clicked.connect(lambda _, i=inp: self.step_time(i, -5))
            setattr(self, attr, inp)
            return lbl, inp, btn_p, btn_m

        lbl_start, self.inp_start_time, bstart_p, bstart_m = mk_time_input("START", "inp_start_time", "09:35", COLOR_YELLOW)
        lbl_stop, self.inp_stop_time, bstop_p, bstop_m = mk_time_input("STOP", "inp_stop_time", "10:45", COLOR_RED)
        lbl_trail, self.inp_trail_pts, btrail_p, btrail_m = mk_param("TRAIL", "inp_trail_pts", 12.0, step=1.0, is_float=True, width=55, color=COLOR_CYAN)

        for lbl, inp, bp, bm, col in [(lbl_start, self.inp_start_time, bstart_p, bstart_m, 0),
                                      (lbl_stop, self.inp_stop_time, bstop_p, bstop_m, 4),
                                      (lbl_trail, self.inp_trail_pts, btrail_p, btrail_m, 8)]:
            grid_params.addWidget(lbl, 4, col)
            grid_params.addWidget(inp, 4, col+1)
            grid_params.addWidget(bp, 4, col+2)
            grid_params.addWidget(bm, 4, col+3)
            inp.editingFinished.connect(self._push_config)

        # Set Column stretches to make sure it aligns on the left and has correct spacing
        grid_params.setColumnStretch(12, 1) # Column 12 takes up all extra stretch space

        # Add the entire parameter grid to main layout
        main.addLayout(grid_params)

        # ── Section E: Trade Status ──────────────────────────────
        status_frame = QFrame()
        status_frame.setStyleSheet("background:#111827;border-radius:4px;padding:2px;")
        sf_layout = QGridLayout(status_frame)
        sf_layout.setContentsMargins(6, 4, 6, 4)
        sf_layout.setHorizontalSpacing(12)
        sf_layout.setVerticalSpacing(2)

        def stat_lbl(text, color="#9ca3af"):
            l = QLabel(text)
            l.setStyleSheet(f"color:{color};font-size:10px;background:transparent;")
            return l

        def stat_val(color="white"):
            l = QLabel("—")
            l.setStyleSheet(f"color:{color};font-size:11px;font-weight:bold;background:transparent;")
            return l

        # Row 0: SETUP / CANDLE / OPT SZ
        sf_layout.addWidget(stat_lbl("SETUP"), 0, 0)
        self.lbl_setup = stat_val(COLOR_YELLOW)
        sf_layout.addWidget(self.lbl_setup, 0, 1)

        sf_layout.addWidget(stat_lbl("CANDLE"), 0, 2)
        self.lbl_trig_candle = stat_val()
        sf_layout.addWidget(self.lbl_trig_candle, 0, 3)

        sf_layout.addWidget(stat_lbl("OPT SZ"), 0, 4)
        self.lbl_opt_size = stat_val(COLOR_CYAN)
        sf_layout.addWidget(self.lbl_opt_size, 0, 5)

        # Row 1: CE CANDLE / PE CANDLE / ENTRY
        self.lbl_ce_candle_hdr = stat_lbl("CE CANDLE", COLOR_GREEN)
        sf_layout.addWidget(self.lbl_ce_candle_hdr, 1, 0)
        self.lbl_ce_candle = stat_val(COLOR_GREEN)
        sf_layout.addWidget(self.lbl_ce_candle, 1, 1)

        self.lbl_pe_candle_hdr = stat_lbl("PE CANDLE", COLOR_RED)
        sf_layout.addWidget(self.lbl_pe_candle_hdr, 1, 2)
        self.lbl_pe_candle = stat_val(COLOR_RED)
        sf_layout.addWidget(self.lbl_pe_candle, 1, 3)

        sf_layout.addWidget(stat_lbl("ENTRY"), 1, 4)
        self.lbl_entry = stat_val(COLOR_BLUE)
        sf_layout.addWidget(self.lbl_entry, 1, 5)

        # Row 2: T1 / T2 / SL
        sf_layout.addWidget(stat_lbl("T1"), 2, 0)
        self.lbl_t1 = stat_val(COLOR_GREEN)
        sf_layout.addWidget(self.lbl_t1, 2, 1)

        sf_layout.addWidget(stat_lbl("T2"), 2, 2)
        self.lbl_t2 = stat_val(COLOR_GREEN)
        sf_layout.addWidget(self.lbl_t2, 2, 3)

        sf_layout.addWidget(stat_lbl("SL"), 2, 4)
        self.lbl_sl = stat_val(COLOR_RED)
        sf_layout.addWidget(self.lbl_sl, 2, 5)

        main.addWidget(status_frame)

        # ── Section B: Strikes (Moved just above the start stop line) ─────────────────
        stk_row = QHBoxLayout()
        stk_row.setSpacing(4)

        lbl_ce = QLabel("CE STK")
        lbl_ce.setStyleSheet("color:white;font-size:10px;font-weight:bold;")
        self.inp_strike_ce = GridValueInput(0, width=55)
        self.inp_strike_ce.editingFinished.connect(self.update_ui_strikes)
        self.inp_strike_ce.editingFinished.connect(self._push_config)
        btn_cep = StepperButton("+", COLOR_GREEN); btn_cep.clicked.connect(lambda _: self.adjust_strike(self.inp_strike_ce, 50))
        btn_cem = StepperButton("-", COLOR_RED);  btn_cem.clicked.connect(lambda _: self.adjust_strike(self.inp_strike_ce, -50))
        self.lbl_ce_price = QLabel("0.00")
        self.lbl_ce_price.setStyleSheet(f"color:{COLOR_GREEN};font-weight:bold;font-size:12px;min-width:40px;")

        lbl_pe = QLabel("PE STK")
        lbl_pe.setStyleSheet("color:white;font-size:10px;font-weight:bold;")
        self.inp_strike_pe = GridValueInput(0, width=55)
        self.inp_strike_pe.editingFinished.connect(self.update_ui_strikes)
        self.inp_strike_pe.editingFinished.connect(self._push_config)
        btn_pep = StepperButton("+", COLOR_GREEN); btn_pep.clicked.connect(lambda _: self.adjust_strike(self.inp_strike_pe, 50))
        btn_pem = StepperButton("-", COLOR_RED);  btn_pem.clicked.connect(lambda _: self.adjust_strike(self.inp_strike_pe, -50))
        self.lbl_pe_price = QLabel("0.00")
        self.lbl_pe_price.setStyleSheet(f"color:{COLOR_RED};font-weight:bold;font-size:12px;min-width:40px;")

        for w in [lbl_ce, self.inp_strike_ce, btn_cep, btn_cem, self.lbl_ce_price,
                  lbl_pe, self.inp_strike_pe, btn_pep, btn_pem, self.lbl_pe_price]:
            stk_row.addWidget(w)
        main.addLayout(stk_row)

        # ── Section F: Controls ──────────────────────────────────
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(4)

        self.combo_dir_filter = QComboBox()
        self.combo_dir_filter.addItems(["BOTH", "LONG", "SHORT"])
        self.combo_dir_filter.setFixedWidth(62)
        self.combo_dir_filter.setToolTip("Direction filter: restrict trades to one side")
        self.combo_dir_filter.setStyleSheet("""
            QComboBox { background:#1f2937; color:#facc15; border:1px solid #374151;
                        border-radius:3px; padding:2px 4px; font-weight:bold; font-size:10px; }
            QComboBox QAbstractItemView { background:#1f2937; color:white;
                                          selection-background-color:#374151; }
        """)
        self._strategy_running = False
        self.combo_dir_filter.currentTextChanged.connect(self._push_config)

        self.btn_start = QPushButton("START")
        self.btn_start.setFixedHeight(28)
        self.btn_start.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_start.setStyleSheet(f"background-color:{COLOR_GREEN};color:black;font-weight:bold;font-size:11px;")
        self.btn_start.clicked.connect(self.on_start_clicked)

        self.lbl_status = QLabel("STOPPED")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setFixedHeight(28)
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.lbl_status.setStyleSheet("background:#1f2937;color:white;font-weight:bold;font-size:11px;border-radius:3px;")

        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setFixedHeight(28)
        self.btn_stop.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_stop.setStyleSheet("background-color:#e81515;color:white;font-weight:bold;font-size:13px;")
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        self.btn_stop.setEnabled(False)

        ctrl_row.addWidget(self.combo_dir_filter)
        ctrl_row.addWidget(self.btn_start)
        ctrl_row.addWidget(self.lbl_status)
        ctrl_row.addWidget(self.btn_stop)
        main.addLayout(ctrl_row)

        self.load_defaults()

    # ── Helpers ──────────────────────────────────────────────────

    def save_defaults(self):
        import json
        try:
            iq_lots = max(0, int(self.inp_initial_qty.text() or 0) // self.lot_size)
            t1q_lots = max(0, int(self.inp_t1_qty.text() or 0) // self.lot_size)
            t2q_lots = max(0, int(self.inp_t2_qty.text() or 0) // self.lot_size)
        except Exception:
            iq_lots, t1q_lots, t2q_lots = 2, 1, 0

        defaults = {
            "pm_limit": self.inp_pm_limit.text(),
            "trig_min": self.inp_trig_min.text(),
            "trig_max": self.inp_trig_max.text(),
            "break_buf": self.inp_break_buf.text(),
            "t1_pct": self.inp_t1_pct.text(),
            "t2_pct": self.inp_t2_pct.text(),
            "t3_mult": self.inp_t3_mult.text(),
            "initial_qty_lots": iq_lots,
            "t1_qty_lots": t1q_lots,
            "t2_qty_lots": t2q_lots,
            "start_time": self.inp_start_time.text(),
            "stop_time": self.inp_stop_time.text(),
            "trail_pts": self.inp_trail_pts.text(),
        }
        try:
            with open("ui_defaults.json", "w") as f:
                json.dump(defaults, f)
            QMessageBox.information(self, "Success", "Defaults saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save defaults: {e}")

    def load_defaults(self):
        import json, os
        if os.path.exists("ui_defaults.json"):
            try:
                with open("ui_defaults.json", "r") as f:
                    defaults = json.load(f)
                self.inp_pm_limit.setText(str(defaults.get("pm_limit", "100")))
                self.inp_trig_min.setText(str(defaults.get("trig_min", "25")))
                self.inp_trig_max.setText(str(defaults.get("trig_max", "45")))
                self.inp_break_buf.setText(str(defaults.get("break_buf", "2")))
                self.inp_t1_pct.setText(str(defaults.get("t1_pct", "0.5")))
                self.inp_t2_pct.setText(str(defaults.get("t2_pct", "1.0")))
                self.inp_t3_mult.setText(str(defaults.get("t3_mult", "2")))
                
                iq_lots = defaults.get("initial_qty_lots", 2)
                t1q_lots = defaults.get("t1_qty_lots", 1)
                t2q_lots = defaults.get("t2_qty_lots", 0)
                
                self.inp_initial_qty.setText(str(int(iq_lots) * self.lot_size))
                self.inp_t1_qty.setText(str(int(t1q_lots) * self.lot_size))
                self.inp_t2_qty.setText(str(int(t2q_lots) * self.lot_size))
                
                self.inp_start_time.setText(str(defaults.get("start_time", "09:35")))
                self.inp_stop_time.setText(str(defaults.get("stop_time", "10:45")))
                self.inp_trail_pts.setText(str(defaults.get("trail_pts", "12.0")))
            except Exception as e:
                print("Failed to load ui_defaults.json", e)

    def step_qty(self, inp, direction):
        try:
            val = int(inp.text() or 0) + direction * self.lot_size
            if val < 0: val = 0
            inp.setText(str(val))
            self._push_config()
        except Exception:
            pass

    def adjust_strike(self, inp, delta):
        try:
            val = int(inp.text() or 0) + delta
            if val < 0: val = 0
            inp.setText(str(val))
            self.update_ui_strikes()
            self._push_config()
        except Exception:
            pass

    def step_param(self, inp, amount, is_float=False):
        try:
            val = float(inp.text() or "0")
            val += amount
            if is_float:
                inp.setText(f"{val:.1f}")
            else:
                inp.setText(str(int(val)))
            self._push_config()
        except Exception:
            pass

    def step_time(self, inp, delta_minutes):
        try:
            t_str = inp.text().strip()
            parts = t_str.split(":")
            if len(parts) == 2:
                h, m = int(parts[0]), int(parts[1])
                total_min = h * 60 + m + delta_minutes
                total_min = total_min % 1440
                new_h = total_min // 60
                new_m = total_min % 60
                inp.setText(f"{new_h:02d}:{new_m:02d}")
                self._push_config()
        except Exception:
            pass

    def _push_config(self):
        """Send current UI values to backend in real-time (only when running)."""
        if not self._strategy_running:
            return
        try:
            iq   = int(self.inp_initial_qty.text() or 0)
            t1q  = int(self.inp_t1_qty.text() or 0)
            t2q  = int(self.inp_t2_qty.text() or 0)
            sce  = int(self.inp_strike_ce.text() or 0)
            spe  = int(self.inp_strike_pe.text() or 0)
            tmin = int(self.inp_trig_min.text() or 25)
            tmax = int(self.inp_trig_max.text() or 45)
            buf  = float(self.inp_break_buf.text() or 2)
            t1p  = float(self.inp_t1_pct.text() or 0.5)
            t2p  = float(self.inp_t2_pct.text() or 1.0)
            t3m  = int(self.inp_t3_mult.text() or 2)
            pml  = int(self.inp_pm_limit.text() or 100)
            df   = self.combo_dir_filter.currentText()
            start_time = self.inp_start_time.text().strip() or "09:35"
            stop_time = self.inp_stop_time.text().strip() or "10:45"
            trail_pts = float(self.inp_trail_pts.text() or 12.0)
            self.bridge.notify("update_nifty_config",
                               iq, t1q, t2q, sce, spe,
                               df, tmin, tmax, buf, t1p, t2p, t3m, pml,
                               start_time, stop_time, trail_pts)
        except Exception:
            pass

    def update_ui_strikes(self):
        ce = self.inp_strike_ce.text() or "0"
        pe = self.inp_strike_pe.text() or "0"
        self.bridge.notify("update_ui_strikes", ce, pe)

    def set_lot_size(self, size):
        if size > 0 and size != self.lot_size:
            try:
                iq = int(self.inp_initial_qty.text() or 0) // self.lot_size
                t1q = int(self.inp_t1_qty.text() or 0) // self.lot_size
                t2q = int(self.inp_t2_qty.text() or 0) // self.lot_size
                self.lot_size = size
                self.inp_initial_qty.setText(str(iq * self.lot_size))
                self.inp_t1_qty.setText(str(t1q * self.lot_size))
                self.inp_t2_qty.setText(str(t2q * self.lot_size))
                self._push_config()
            except Exception:
                self.lot_size = size

    def on_oi_toggled(self, checked):
        self.bridge.notify("oi_toggle", checked)

    def on_start_clicked(self):
        try:
            iq   = int(self.inp_initial_qty.text() or 0)
            t1q  = int(self.inp_t1_qty.text() or 0)
            t2q  = int(self.inp_t2_qty.text() or 0)
            sce  = int(self.inp_strike_ce.text() or 0)
            spe  = int(self.inp_strike_pe.text() or 0)
            tmin = int(self.inp_trig_min.text() or 25)
            tmax = int(self.inp_trig_max.text() or 45)
            buf  = float(self.inp_break_buf.text() or 2)
            t1p  = float(self.inp_t1_pct.text() or 0.5)
            t2p  = float(self.inp_t2_pct.text() or 1.0)
            t3m  = int(self.inp_t3_mult.text() or 2)
            pml  = int(self.inp_pm_limit.text() or 100)
            direction_filter = self.combo_dir_filter.currentText()
            start_time = self.inp_start_time.text().strip() or "09:35"
            stop_time = self.inp_stop_time.text().strip() or "10:45"
            trail_pts = float(self.inp_trail_pts.text() or 12.0)
            self.bridge.notify("start_nifty_strategy",
                               iq, t1q, t2q, sce, spe,
                               direction_filter, tmin, tmax, buf, t1p, t2p, t3m, pml,
                               start_time, stop_time, trail_pts)
            self.lbl_status.setText("RUNNING")
            self.lbl_status.setStyleSheet(f"background-color:{COLOR_GREEN};color:black;font-weight:bold;font-size:11px;border-radius:3px;")
            self._strategy_running = True
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
        except Exception:
            pass

    def on_stop_clicked(self):
        self.bridge.notify("stop_nifty_strategy")
        self.lbl_status.setText("STOPPED")
        self.lbl_status.setStyleSheet("background:#1f2937;color:white;font-weight:bold;font-size:11px;border-radius:3px;")
        self._strategy_running = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)


    def update_settings(self):
        pass  # no-op — settings sent at start time

    def update_nifty_status(self, data):
        state = data.get("state", "IDLE")
        is_running = state != "IDLE"

        tc = data.get("trigger_candle", {})
        
        # Status label
        if state == "IN_TRADE":
            self.lbl_status.setText("IN TRADE")
            self.lbl_status.setStyleSheet(f"background-color:{COLOR_GREEN};color:black;font-weight:bold;font-size:11px;border-radius:3px;")
        elif state == "TRAILING":
            self.lbl_status.setText("TRAILING")
            self.lbl_status.setStyleSheet(f"background-color:{COLOR_CYAN};color:black;font-weight:bold;font-size:11px;border-radius:3px;")
        elif state == "SCANNING" and tc:
            self.lbl_status.setText("TRIGGERED")
            self.lbl_status.setStyleSheet(f"background-color:{COLOR_ORANGE};color:black;font-weight:bold;font-size:11px;border-radius:3px;")
        elif state == "SCANNING":
            self.lbl_status.setText("SCANNING")
            self.lbl_status.setStyleSheet(f"background-color:{COLOR_BLUE};color:white;font-weight:bold;font-size:11px;border-radius:3px;")
        elif state == "WAITING_TIME":
            self.lbl_status.setText("WAITING TIME")
            self.lbl_status.setStyleSheet("background-color:#cca43b;color:black;font-weight:bold;font-size:11px;border-radius:3px;")
        elif state == "PREMARKET_FAIL":
            self.lbl_status.setText("PM FAIL")
            self.lbl_status.setStyleSheet(f"background-color:{COLOR_RED};color:white;font-weight:bold;font-size:11px;border-radius:3px;")
        else:
            self.lbl_status.setText("STOPPED")
            self.lbl_status.setStyleSheet("background:#1f2937;color:white;font-weight:bold;font-size:11px;border-radius:3px;")

        self._strategy_running = is_running
        self.btn_start.setEnabled(not is_running)
        self.btn_stop.setEnabled(is_running)

        # Pre-market
        pm_ok = data.get("premarket_ok", False)
        self.lbl_premarket.setText("OK ✓" if pm_ok else "PENDING")
        self.lbl_premarket.setStyleSheet(
            f"color:{COLOR_GREEN if pm_ok else COLOR_YELLOW};font-size:10px;font-weight:bold;background:#1f2937;padding:2px 6px;border-radius:3px;")
        self.lbl_pm_move.setText(str(data.get("premarket_move", 0)))
        self.lbl_pm_range.setText(str(data.get("day_range", 0)))

        self.lbl_opt_size.setText(f"{data.get('opt_candle_size', 0):.1f}")

        setup_signal = data.get("setup_signal") or ""
        safety_state = data.get("safety_state")
        is_suppressed = (safety_state is not None) and (not setup_signal)

        if not is_suppressed:
            # Trigger candle (nifty breakout candle)
            tc = data.get("trigger_candle", {})
            if tc:
                time_str = tc.get("open_time", "")
                self.lbl_trig_candle.setText(f"{time_str} H:{tc.get('high',0):.0f} L:{tc.get('low',0):.0f}")
            else:
                self.lbl_trig_candle.setText("—")

            self.lbl_setup.setText(setup_signal or "—")

            # CE / PE candle display
            ce_c = data.get("ce_candle", {})
            pe_c = data.get("pe_candle", {})

            def fmt_opt_candle(c):
                if not c:
                    return "—"
                t = c.get("open_time", "")
                h = c.get("high", 0)
                l = c.get("low", 0)
                return f"{t} H:{h:.0f} L:{l:.0f}" if t else f"H:{h:.0f} L:{l:.0f}"

            self.lbl_ce_candle.setText(fmt_opt_candle(ce_c))
            self.lbl_pe_candle.setText(fmt_opt_candle(pe_c))

        # Trade levels
        entry = data.get("entry_price_opt", 0)
        self.lbl_entry.setText(f"{entry:.2f}" if entry else "—")
        sl = data.get("current_sl", 0)
        self.lbl_sl.setText(f"{sl:.2f}" if sl else "—")
        t1 = data.get("t1_target", 0)
        t1h = data.get("t1_hit", False)
        self.lbl_t1.setText(f"✓{t1:.2f}" if t1h else (f"{t1:.2f}" if t1 else "—"))
        self.lbl_t1.setStyleSheet(f"color:{COLOR_YELLOW if t1h else COLOR_GREEN};font-size:11px;font-weight:bold;background:transparent;")
        t2 = data.get("t2_target", 0)
        t2h = data.get("t2_hit", False)
        self.lbl_t2.setText(f"✓{t2:.2f}" if t2h else (f"{t2:.2f}" if t2 else "—"))

    # keep legacy compat
    def update_data(self, data):
        pass


class CredentialsPanel(QFrame):
    sig_result = pyqtSignal(dict) 
    sig_creds_loaded = pyqtSignal(dict)

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.setObjectName("CredentialsPanel")
        
        self.sig_result.connect(self.on_connect_result)
        self.sig_creds_loaded.connect(self.on_creds_loaded)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        
        title = QLabel("API Credentials")
        title.setStyleSheet("color: white; font-size: 14px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)
        
        # Form
        form_layout = QGridLayout()
        form_layout.setSpacing(10)
        
        def add_field(row, label, key, is_pwd=False):
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #9ca3af; font-size: 11px;")
            inp = QLineEdit()
            if is_pwd:
                inp.setEchoMode(QLineEdit.EchoMode.Password)
            setattr(self, f"inp_{key}", inp)
            form_layout.addWidget(lbl, row, 0)
            form_layout.addWidget(inp, row, 1)
            
        add_field(0, "User ID", "user_id")
        add_field(1, "Password", "password", True)
        add_field(2, "2FA / TOTP", "factor2", True)
        add_field(3, "API Key", "api_key", True)
        add_field(4, "API Secret", "api_secret", True)
        
        layout.addLayout(form_layout)
        
        layout.addStretch()
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_save_defaults = QPushButton("SAVE DEFAULTS")
        self.btn_save_defaults.setFixedHeight(32)
        self.btn_save_defaults.setStyleSheet(f"background-color: {COLOR_CYAN}; color: black; font-weight: bold;")
        
        self.btn_connect = QPushButton("SAVE & CONNECT")
        self.btn_connect.setFixedHeight(32)
        self.btn_connect.setStyleSheet(f"background-color: {COLOR_GREEN}; color: black; font-weight: bold;")
        self.btn_connect.clicked.connect(self.on_connect_clicked)
        
        btn_layout.addWidget(self.btn_save_defaults)
        btn_layout.addWidget(self.btn_connect)
        layout.addLayout(btn_layout)

    def on_connect_clicked(self):
        creds = {
            "user_id": self.inp_user_id.text(),
            "password": self.inp_password.text(),
            "factor2": self.inp_factor2.text(),
            "api_key": self.inp_api_key.text(),
            "api_secret": self.inp_api_secret.text()
        }
        # Disable button to prevent double click
        self.btn_connect.setEnabled(False)
        self.btn_connect.setText("CONNECTING...")
        
        # Run in thread
        threading.Thread(target=self._do_connect, args=(creds,), daemon=True).start()

    def _do_connect(self, creds):
        try:
             res = self.bridge.call("connect_to_api", creds)
             self.sig_result.emit(res)
        except Exception as e:
             self.sig_result.emit({"success": False, "message": str(e)})

    def on_connect_result(self, res):
         try:
             if res.get("success"):
                 QMessageBox.information(self, "Success", "Connected Successfully")
             else:
                 QMessageBox.critical(self, "Error", res.get("message", "Unknown Error"))
         except Exception as e:
             QMessageBox.critical(self, "Error", str(e))
         finally:
             self.btn_connect.setEnabled(True)
             self.btn_connect.setText("SAVE & CONNECT")

    def load_creds_bg(self):
        try:
            creds = self.bridge.call("get_saved_credentials")
            if creds:
                self.sig_creds_loaded.emit(creds)
        except Exception:
            pass

    def on_creds_loaded(self, creds):
        self.inp_user_id.setText(creds.get("user_id", ""))
        self.inp_password.setText(creds.get("password", ""))
        self.inp_factor2.setText(creds.get("factor2", ""))
        self.inp_api_key.setText(creds.get("api_key", ""))
        self.inp_api_secret.setText(creds.get("api_secret", ""))

class DataPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataSection")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Tabs Header
        self.tabs_frame = QFrame()
        self.tabs_frame.setStyleSheet("background: #1f2937; border-bottom: 1px solid #2a2f38;")
        self.tabs_frame.setFixedHeight(30)
        tabs_layout = QHBoxLayout(self.tabs_frame)
        tabs_layout.setContentsMargins(0, 0, 0, 0)
        tabs_layout.setSpacing(0)
        
        self.btn_pos = DataTabButton("POSITIONS")
        self.btn_ord = DataTabButton("ORDERS")
        self.btn_pos.setChecked(True)
        
        self.btn_pos.clicked.connect(lambda: self.switch_tab(0))
        self.btn_ord.clicked.connect(lambda: self.switch_tab(1))
        
        tabs_layout.addWidget(self.btn_pos)
        tabs_layout.addWidget(self.btn_ord)
        
        layout.addWidget(self.tabs_frame)
        
        # Content
        self.stack = QStackedWidget()
        
        # Table 1: Positions
        self.table_pos = QTableWidget(0, 5)
        self.table_pos.setHorizontalHeaderLabels(["Sym", "Qty", "Avg", "LTP", "P&L"])
        self.table_pos.verticalHeader().setVisible(False)
        self.table_pos.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.stack.addWidget(self.table_pos)
        
        # Table 2: Orders
        self.table_ord = QTableWidget(0, 6)
        self.table_ord.setHorizontalHeaderLabels(["Time", "Sym", "Type", "Qty", "Prc", "Sts"])
        self.table_ord.verticalHeader().setVisible(False)
        self.table_ord.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.stack.addWidget(self.table_ord)
        
        layout.addWidget(self.stack)

    def switch_tab(self, index):
        self.stack.setCurrentIndex(index)
        if index == 0:
            self.btn_pos.setChecked(True)
            self.btn_ord.setChecked(False)
        else:
            self.btn_pos.setChecked(False)
            self.btn_ord.setChecked(True)
            
    def update_positions(self, positions_data):
        self.table_pos.setRowCount(0)
        # positions_data is dict: symbol -> details
        if not positions_data: return
        
        # Sort positions by absolute quantity descending
        sorted_pos = sorted(positions_data.values(), key=lambda x: abs(int(x.get('qty', 0))), reverse=True)
        
        self.table_pos.setRowCount(len(sorted_pos))
        for row, pos in enumerate(sorted_pos):
            self.table_pos.setItem(row, 0, QTableWidgetItem(str(pos.get('symbol'))))
            self.table_pos.setItem(row, 1, QTableWidgetItem(str(pos.get('qty'))))
            self.table_pos.setItem(row, 2, QTableWidgetItem(f"{float(pos.get('avg_price', 0)):.2f}"))
            self.table_pos.setItem(row, 3, QTableWidgetItem(f"{float(pos.get('ltp', 0)):.2f}"))
            
            pnl = float(pos.get('pnl', 0))
            item_pnl = QTableWidgetItem(f"{pnl:.2f}")
            item_pnl.setForeground(QColor(COLOR_GREEN if pnl >= 0 else COLOR_RED))
            self.table_pos.setItem(row, 4, item_pnl)

    def update_orders(self, order_data):
        if not order_data:
            return
            
        # Helper to add one order
        def add_single_order(ord_d):
            row = 0
            self.table_ord.insertRow(0)
            self.table_ord.setItem(row, 0, QTableWidgetItem(datetime.now().strftime("%H:%M:%S"))) 
            self.table_ord.setItem(row, 1, QTableWidgetItem(str(ord_d.get('symbol'))))
            self.table_ord.setItem(row, 2, QTableWidgetItem(str(ord_d.get('type'))))
            self.table_ord.setItem(row, 3, QTableWidgetItem(str(ord_d.get('qty'))))
            self.table_ord.setItem(row, 4, QTableWidgetItem(str(ord_d.get('price'))))
            self.table_ord.setItem(row, 5, QTableWidgetItem(str(ord_d.get('status'))))

        if isinstance(order_data, list):
            # Sort by time? Assuming order preserved or reverse order needed.
            # Appending all.
            for o in order_data:
                add_single_order(o)
        else:
            add_single_order(order_data)


class MainWindow(QWidget):
    sig_conn = pyqtSignal(bool)
    sig_pos = pyqtSignal(dict)
    sig_mkt = pyqtSignal(dict)
    sig_nifty = pyqtSignal(dict)
    sig_exp = pyqtSignal(list)
    sig_ord = pyqtSignal(dict)
    sig_lot_size = pyqtSignal(int)
    sig_notify = pyqtSignal(dict)

    def __init__(self, bridge):
        super().__init__()
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.bridge = bridge
        self.setWindowTitle("ARK Trading Overlay")
        self.resize(500, 600)
        self.setMinimumSize(400, 500)
        self.setStyleSheet(STYLESHEET)
        
        # Connect Signals
        self.sig_conn.connect(self.on_conn)
        self.sig_pos.connect(self.on_pos)
        self.sig_mkt.connect(self.on_mkt)
        self.sig_nifty.connect(self.on_nifty)
        self.sig_exp.connect(self.on_exp)
        self.sig_ord.connect(self.on_ord)
        self.sig_lot_size.connect(self.on_lot_size)
        self.sig_notify.connect(self.on_notify_message)
        
        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        self.header = Header(bridge)
        layout.addWidget(self.header)
        
        # Container for main content
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(5, 5, 5, 5)
        content_layout.setSpacing(5)
        
        # Trading Panel (Left/Main) - It is the ONLY visible panel for trading in this view
        # The CSS hides Credentials panel or shows it. Swapping.
        self.stack = QStackedWidget()
        
        # 1. Trading Page
        trading_page = QWidget()
        tp_layout = QVBoxLayout(trading_page)
        tp_layout.setContentsMargins(0, 0, 0, 0)
        tp_layout.setSpacing(5)
        
        self.strategy_panel = StrategyPanel(bridge)
        self.data_panel = DataPanel()
        
        tp_layout.addWidget(self.strategy_panel)
        tp_layout.addWidget(self.data_panel, 1) # Expand data panel
        
        self.stack.addWidget(trading_page)
        
        # 2. Credentials Page
        self.creds_panel = CredentialsPanel(bridge)
        self.stack.addWidget(self.creds_panel)
        
        content_layout.addWidget(self.stack)
        layout.addWidget(content_widget)

        # Connect the Save Defaults button
        self.creds_panel.btn_save_defaults.clicked.connect(self.strategy_panel.save_defaults)

        # Connect Header Tabs
        self.header.btn_tab_trade.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        self.header.btn_tab_key.clicked.connect(lambda: self.stack.setCurrentIndex(1)) # Or 2? 
        self.header.btn_tab_trade.toggled.connect(self.tab_toggled)
        self.header.btn_tab_key.toggled.connect(self.tab_toggled)
        
        # Initial trigger
        self.header.btn_tab_trade.click()

        # Auto Init
        QTimer.singleShot(500, self.auto_init)



    def auto_init(self):
        # Everything relative to backend must be threaded to avoid blocking UI on startup
        threading.Thread(target=self._full_auto_init_bg, daemon=True).start()

    def _full_auto_init_bg(self):
        # 0. Fetch Lot Size
        try:
             res = self.bridge.call("get_lot_size", "NIFTY")
             if res and res.get("success"):
                 self.sig_lot_size.emit(res.get("lot_size", 25))
        except:
             pass

        # 1. Load creds to UI
        self.creds_panel.load_creds_bg()
        # 2. Connection is now handled by RUN button

        # 3. Fetch ATM for strikes
        try:
             atm = self.bridge.call("get_atm_strike")
             if atm:
                 self.strategy_panel.inp_strike_ce.setText(str(atm))
                 self.strategy_panel.inp_strike_pe.setText(str(atm))
                 self.strategy_panel.update_ui_strikes()
        except Exception:
             pass

    def tab_toggled(self):
        sender = self.sender()
        if sender.isChecked():
            if sender == self.header.btn_tab_trade:
                self.header.btn_tab_key.setChecked(False)
            else:
                self.header.btn_tab_trade.setChecked(False)

    def on_conn(self, success):
        self.header.btn_run.setEnabled(True)
        if success and self.strategy_panel:
            # Fetch ATM strike now that we are successfully connected
            def post_login_tasks():
                try:
                    atm = self.bridge.call("get_atm_strike")
                    if atm and int(atm) > 0:
                        self.strategy_panel.inp_strike_ce.setText(str(atm))
                        self.strategy_panel.inp_strike_pe.setText(str(atm))
                        self.strategy_panel.update_ui_strikes()
                except Exception:
                    pass
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1000, post_login_tasks)

    def on_pos(self, data):
        self.data_panel.update_positions(data)
        # Calculate total PNL
        total = sum(float(p.get('pnl', 0)) for p in data.values())
        self.strategy_panel.lbl_pnl_v.setText(f"{total:.2f}")
        self.strategy_panel.lbl_pnl_v.setStyleSheet(f"color: {COLOR_GREEN if total>=0 else COLOR_RED}; font-weight: bold; font-size: 18px;")

    def on_mkt(self, data):
        self.header.update_market(data)
        
        # Auto-initialize strikes if they are zero
        if "nifty_ltp" in data:
            try:
                ltp = float(data["nifty_ltp"])
                if ltp > 0:
                    ce_text = self.strategy_panel.inp_strike_ce.text()
                    pe_text = self.strategy_panel.inp_strike_pe.text()
                    
                    # If either is 0 or empty, initialize both to ATM
                    if not ce_text or ce_text == "0" or not pe_text or pe_text == "0":
                        # Use 50 as default step for NIFTY
                        atm = int(round(ltp / 50) * 50)
                        self.strategy_panel.inp_strike_ce.setText(str(atm))
                        self.strategy_panel.inp_strike_pe.setText(str(atm))
                        self.strategy_panel.update_ui_strikes()
            except Exception:
                pass

        if "ce_change_oi" in data:
            self.strategy_panel.oi_lbl_ce_v.setText(format_indian_number(data["ce_change_oi"]))
        if "pe_change_oi" in data:
            self.strategy_panel.oi_lbl_pe_v.setText(format_indian_number(data["pe_change_oi"]))
        
        # Update UI selected strike prices
        if "ce_strike_price" in data:
            self.strategy_panel.lbl_ce_price.setText(f"{float(data['ce_strike_price']):.2f}")
        if "pe_strike_price" in data:
            self.strategy_panel.lbl_pe_price.setText(f"{float(data['pe_strike_price']):.2f}")

    def on_nifty(self, data):
        self.strategy_panel.update_nifty_status(data)

    def on_exp(self, dates):
        self.header.combo_expiry.blockSignals(True)
        self.header.combo_expiry.clear()
        self.header.combo_expiry.addItems(dates)
        self.header.combo_expiry.blockSignals(False)
        # Automatically select the first expiry and trigger the backend update
        if dates:
            self.header.combo_expiry.setCurrentIndex(0)
            self.header.on_expiry_changed(dates[0])

    def on_ord(self, data):
        self.data_panel.update_orders(data)

    def on_notify_message(self, data):
        title = data.get("title", "Nifty Strategy")
        message = data.get("message", "")
        if message:
            QMessageBox.information(self, title, message)

    def on_lot_size(self, size):
        if self.strategy_panel:
            self.strategy_panel.set_lot_size(size)



def ui_main(rpc_address):
    bridge = RpcHandler(rpc_address, "client", name="UI")
    
    app = QApplication(sys.argv)
    window = MainWindow(bridge)

    @bridge.expose
    def updateConnectionStatus(success):
        window.sig_conn.emit(success)

    @bridge.expose
    def updatePositions(data):
        window.sig_pos.emit(data)

    @bridge.expose
    def updateMarketData(data):
        window.sig_mkt.emit(data)

    @bridge.expose
    def updateNiftyState(data):
        window.sig_nifty.emit(data)

    @bridge.expose
    def updateExpiryDates(dates):
        window.sig_exp.emit(dates)

    @bridge.expose
    def handleOrderUpdate(data):
        window.sig_ord.emit(data)
        
    @bridge.expose
    def showNotification(data):
        window.sig_notify.emit(data)
        
    @bridge.expose
    def initializePositionsAndOrders():
        # Trigger initialization on backend
        bridge.call("initializePositionsAndOrders")

    bridge.start()
    
    def on_exit():
        bridge.shutdown()
    atexit.register(on_exit)

    window.show()
    sys.exit(app.exec())
