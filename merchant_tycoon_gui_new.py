"""
merchant_tycoon_gui_new.py  —  PySide6 GUI for Merchant Tycoon
═══════════════════════════════════════════════════════════════

Architecture:
    GameApp (QMainWindow)
      ├── CustomTitleBar      — frameless draggable title bar with window controls
      ├── StatusBar           — persistent HUD strip; refreshed after every action
      ├── QStackedWidget      — content area; Screen instances swap in/out
      │     └── Screen        — base class; override build() / refresh() / on_show()
      └── MessageBar          — bottom toast strip (ok / warn / err)

Navigation:
    app.show(name)            — push screen onto nav stack and display it
    app.go_back()             — pop stack; return to previous screen
    app.goto(name)            — flat jump (collapses stack to [main, name])
    app.refresh()             — re-render status bar + current screen

Animation system:
    ScreenTransition          — QPropertyAnimation-based cross-fade / slide manager
    AnimationEasing           — curated easing curves used consistently across UI
    FadeWidget / SlideWidget  — lightweight effect compositors (no QPainter sub-class)

Talking to the game model:
    Every Screen holds  self.app.game  (the Game instance).
    Handlers call pure Game methods then call  self.app.refresh().

Thread-safety:
    All network work runs on QThreadPool via Worker / WorkerSignals.
    GUI callbacks must be dispatched via  QMetaObject.invokeMethod  or
    Qt signals — never touching widgets directly from a worker thread.

Scaling:
    UIScale singleton controls DPI-aware font and spacing values.
    The theme QSS is regenerated on scale change.
"""

from __future__ import annotations

import sys
import os
import time
import random
import weakref
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Type, Any

# ── PySide6 ───────────────────────────────────────────────────────────────────
from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QSize, QRect,
    QRunnable, QThreadPool, QObject, Signal, Slot, QAbstractAnimation,
    QParallelAnimationGroup, QSequentialAnimationGroup, Property,
    QByteArray, QEvent, QMimeData, QThread, QMetaObject, Q_ARG,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPixmap,
    QPalette, QIcon, QCursor, QLinearGradient, QRadialGradient,
    QKeySequence, QShortcut, QGuiApplication, QScreen, QAction,
    QCloseEvent, QMouseEvent, QResizeEvent, QPen, QBrush,
    QFontDatabase,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget, QScrollArea,
    QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QScrollBar, QDialog, QDialogButtonBox,
    QLineEdit, QTextEdit, QComboBox, QSpinBox, QCheckBox, QSlider,
    QProgressBar, QToolButton, QButtonGroup, QSpacerItem,
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
    QMenu, QMenuBar, QStatusBar, QToolBar, QDockWidget,
    QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem,
    QMessageBox, QFileDialog, QInputDialog, QColorDialog,
    QTabWidget, QGroupBox, QRadioButton,
)
from PySide6.QtSvgWidgets import QSvgWidget

# ── Game model import ─────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from merchant_tycoon import (
    Game, Area, Season, LicenseType, SkillType, ItemCategory, PropertyType,
    ALL_ITEMS, AREA_INFO, BUSINESS_CATALOGUE, LICENSE_INFO, ACHIEVEMENTS,
    TITLE_DEFINITIONS, TITLES_BY_ID,
    PROPERTY_CATALOGUE, LAND_PLOT_SIZES, PROPERTY_UPGRADES, AREA_PROPERTY_MULT,
    _PROP_NAMES, condition_label, DEFAULT_HOTKEYS,
    Item, LoanRecord, CDRecord, make_business, Contract,
    CitizenLoan, FundClient, StockHolding, Property, LandPlot,
    ManagerType, HiredManager, MANAGER_DEFS, MANAGER_XP_THRESHOLDS,
    MANAGER_EFFICIENCY, _MANAGER_DEFAULT_CONFIGS,
    Ship, Captain, Voyage, SHIP_TYPES, SHIP_UPGRADES, VOYAGE_PORTS,
    _SHIP_NAME_PREFIXES, _SHIP_NAME_SUFFIXES,
)

# ══════════════════════════════════════════════════════════════════════════════
# COLOUR PALETTE  —  Warm fantasy / medieval merchant
# ══════════════════════════════════════════════════════════════════════════════

class Palette:
    """
    Central colour registry.  All colours expressed as hex strings and as
    QColor objects (lazily constructed).  Access via  Palette.bg  etc.
    """
    # ── Backgrounds ──────────────────────────────────────────────────────────
    bg            = "#1c1409"   # midnight oak — deep warm dark
    bg_panel      = "#2a1d0d"   # rich oiled leather
    bg_row_alt    = "#211609"   # table row alternation — subtle warmth
    bg_hover      = "#5c4218"   # firelight hover — vivid amber tint
    bg_button     = "#3d2a12"   # mahogany button
    bg_button_act = "#7a4e1c"   # ember-glow active — noticeably brighter
    bg_input      = "#160e05"   # near-black input field
    bg_card       = "#261a0c"   # card panel — slightly lifted
    bg_overlay    = "#080502"   # modal scrim

    # ── Dialog backgrounds — dramatically darker for visual separation ────
    bg_dialog     = "#0c0805"
    bg_dialog_hdr = "#1a1208"
    bg_shadow     = "#020100"

    # ── Text ─────────────────────────────────────────────────────────────────
    fg            = "#faedd4"   # bright warm parchment
    fg_dim        = "#c4a878"   # aged ink — more visible than before
    fg_header     = "#ffffff"   # pure white for maximum prominence
    fg_disabled   = "#7a6042"   # disabled — slightly lighter

    # ── Accents — fully saturated, vivid ─────────────────────────────────────
    gold          = "#ffd030"   # brilliant coin gold
    amber         = "#ff9e20"   # full-saturation flame amber
    green         = "#66dd22"   # vivid lime-forest green
    red           = "#f03838"   # strong blood red
    cream         = "#f7eddc"   # soft cream white
    grey          = "#b8a888"   # warm mid-grey
    blue          = "#44a8e8"   # clean sky blue
    purple        = "#c078ee"   # vibrant arcane purple

    # ── Borders — polished and visible ───────────────────────────────────────
    border        = "#7a5428"   # copper-brown — clearly visible
    border_light  = "#dca030"   # gleaming brass — high contrast
    border_focus  = "#ffd030"   # bright gold focus ring

    # ── Season tints — punchy and distinct ───────────────────────────────────
    spring        = "#70dc38"   # fresh vivid green
    summer        = "#ffc820"   # blazing sun gold
    autumn        = "#f06a28"   # rich harvest orange
    winter        = "#78b8f0"   # clear ice blue

    # ── Semantic shortcuts ────────────────────────────────────────────────────
    ok     = green
    warn   = amber
    error  = red
    info   = gold

    # ── Gradient stops (for QLinearGradient) ─────────────────────────────────
    grad_header_top = "#3e2c14"   # warm bronze-dark
    grad_header_bot = "#190d05"   # near-black tinted
    grad_button_top = "#503618"   # mahogany mid
    grad_button_bot = "#2c1c08"   # dark amber-black
    grad_panel_top  = "#2e2010"   # leather panel top
    grad_panel_bot  = "#1c1208"   # leather panel bottom

    @staticmethod
    def qcolor(hex_str: str) -> QColor:
        """Convert a hex string to QColor, caching the result."""
        if hex_str not in _QCOLOR_CACHE:
            _QCOLOR_CACHE[hex_str] = QColor(hex_str)
        return _QCOLOR_CACHE[hex_str]

    @staticmethod
    def rgba(hex_str: str, alpha: int) -> QColor:
        """Return QColor from hex with explicit alpha (0-255)."""
        c = QColor(hex_str)
        c.setAlpha(alpha)
        return c

_QCOLOR_CACHE: Dict[str, QColor] = {}

# Convenience alias used heavily below
P = Palette

# ── Season colour lookup ──────────────────────────────────────────────────────
SEASON_COLOURS: Dict[Season, str] = {
    Season.SPRING: P.spring,
    Season.SUMMER: P.summer,
    Season.AUTUMN: P.autumn,
    Season.WINTER: P.winter,
}

# ── Reputation tier lookup  (threshold, label, colour) ───────────────────────
REP_TIERS: List[Tuple[int, str, str]] = [
    (20,  "Outlaw",    P.red),
    (40,  "Suspect",   P.amber),
    (60,  "Neutral",   P.cream),
    (80,  "Trusted",   P.green),
    (101, "Legendary", P.gold),
]

def rep_label(rep: int) -> Tuple[str, str]:
    for threshold, label, colour in REP_TIERS:
        if rep < threshold:
            return label, colour
    return "Legendary", P.gold

# ══════════════════════════════════════════════════════════════════════════════
# UI SCALE  —  DPI / accessibility scaling singleton
# ══════════════════════════════════════════════════════════════════════════════

class UIScale:
    """
    Singleton that owns the current UI scale factor (1.0 = 100%).
    Call  UIScale.set(factor)  to globally scale all fonts and spacing.
    Connect to  UIScale.changed  signal to react to scale changes.
    """

    _instance: Optional["UIScale"] = None
    _factor:   float               = 1.0

    class _Signals(QObject):
        changed = Signal(float)

    # Eagerly create the signals object at class definition time so that
    # set() / connect() work even before UIScale() is ever instantiated.
    _signals: "_Signals"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    @classmethod
    def _ensure_signals(cls) -> None:
        if not hasattr(cls, "_signals") or cls._signals is None:
            cls._signals = cls._Signals()

    def __new__(cls) -> "UIScale":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._ensure_signals()
        return cls._instance

    @classmethod
    def factor(cls) -> float:
        return cls._factor

    @classmethod
    def set(cls, factor: float) -> None:
        cls._ensure_signals()
        factor = max(0.7, min(2.5, round(factor, 2)))
        if factor == cls._factor:
            return
        cls._factor = factor
        Fonts._rebuild(factor)
        cls._signals.changed.emit(factor)

    @classmethod
    def px(cls, base: int) -> int:
        """Scale a base pixel dimension."""
        return max(1, round(base * cls._factor))

    @classmethod
    def connect(cls, slot: Callable[[float], None]) -> None:
        cls._ensure_signals()
        cls._signals.changed.connect(slot)


# Eagerly initialise signals at module load
UIScale._ensure_signals()

# ══════════════════════════════════════════════════════════════════════════════
# FONTS  —  Palatino Linotype (fantasy) + Consolas (data) with DPI scaling
# ══════════════════════════════════════════════════════════════════════════════

class Fonts:
    """
    Centralised font registry.  All fonts are QFont objects.
    Call  Fonts._rebuild(scale)  when UIScale changes.

    Using class-level attributes so any module can do:
        from merchant_tycoon_gui_new import Fonts
        label.setFont(Fonts.body)
    """

    _FANTASY = "Palatino Linotype"
    _MONO    = "Consolas"
    _FALLBACK_FANTASY = "Georgia"
    _FALLBACK_MONO    = "Courier New"

    # These are populated by _rebuild() which is called once at module load
    title:       QFont
    title_large: QFont
    heading:     QFont
    body:        QFont
    body_small:  QFont
    body_bold:   QFont
    mono:        QFont
    mono_small:  QFont
    mono_large:  QFont
    small:       QFont
    tiny:        QFont
    icon:        QFont   # for symbol / emoji labels

    @classmethod
    def _rebuild(cls, scale: float = 1.0) -> None:
        def _f(family: str, size: int, bold: bool = False,
               italic: bool = False) -> QFont:
            f = QFont(family, max(6, round(size * scale)))
            if bold:   f.setBold(True)
            if italic: f.setItalic(True)
            f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
            return f

        # Prefer Palatino Linotype; fall back to Georgia if unavailable
        fant = cls._FANTASY
        mono = cls._MONO

        cls.title_large = _f(fant, 20, bold=True)
        cls.title       = _f(fant, 16, bold=True)
        cls.heading     = _f(fant, 13, bold=True)
        cls.body        = _f(fant, 11)
        cls.body_small  = _f(fant, 10)
        cls.body_bold   = _f(fant, 11, bold=True)
        cls.small       = _f(fant,  9)
        cls.tiny        = _f(fant,  8)
        cls.mono        = _f(mono, 10)
        cls.mono_small  = _f(mono,  9)
        cls.mono_large  = _f(mono, 12)
        # Icon labels: use the default system font at a slightly larger size
        # so emoji render correctly on all platforms.
        cls.icon        = _f("Segoe UI Emoji" if sys.platform == "win32"
                             else fant, 12)

    @classmethod
    def metrics(cls, font: QFont) -> QFontMetrics:
        return QFontMetrics(font)

# Initialise fonts at module load
Fonts._rebuild(1.0)

# ══════════════════════════════════════════════════════════════════════════════
# QSS (Qt Style Sheet)  —  full application theme
# ══════════════════════════════════════════════════════════════════════════════

def _build_qss(scale: float = 1.0) -> str:
    """
    Generate the complete QSS string for the application theme.
    Regenerated on UIScale change.  Uses Palette constants for all colours.
    """
    px = lambda n: f"{max(1, round(n * scale))}px"

    return f"""
/* ── Global reset ──────────────────────────────────────────────────────── */
* {{
    color: {P.fg};
    font-family: "Palatino Linotype", "Georgia", serif;
    selection-background-color: {P.bg_hover};
    selection-color: {P.fg};
    outline: none;
}}

QWidget {{
    background-color: {P.bg};
}}

/* ── Main window ──────────────────────────────────────────────────────────*/
QMainWindow {{
    background-color: {P.bg};
    border: 1px solid {P.border};
}}

/* ── Panels (QPanelFrame) ─────────────────────────────────────────────────*/
QFrame#panel, QFrame.panel {{
    background-color: {P.bg_panel};
    border: 1px solid {P.border};
    border-radius: {px(4)};
}}

QFrame#card, QFrame.card {{
    background-color: {P.bg_card};
    border: 1px solid {P.border};
    border-radius: {px(6)};
}}

/* ── Labels ───────────────────────────────────────────────────────────────*/
QLabel {{
    background-color: transparent;
    color: {P.fg};
}}

QLabel[role="title"] {{
    color: {P.fg_header};
    font-size: {px(16)};
    font-weight: bold;
}}

QLabel[role="heading"] {{
    color: {P.gold};
    font-size: {px(13)};
    font-weight: bold;
}}

QLabel[role="section"] {{
    color: {P.gold};
    font-weight: bold;
    padding: {px(2)} 0px;
}}

QLabel[role="dim"] {{
    color: {P.fg_dim};
}}

QLabel[role="ok"]   {{ color: {P.green}; }}
QLabel[role="warn"] {{ color: {P.amber}; }}
QLabel[role="error"]{{ color: {P.red};   }}
QLabel[role="gold"] {{ color: {P.gold};  }}

/* ── Buttons ──────────────────────────────────────────────────────────────*/
QPushButton {{
    background-color: {P.bg_button};
    color: {P.fg};
    border: 1px solid {P.border};
    border-radius: {px(4)};
    padding: {px(6)} {px(14)};
    font-weight: bold;
}}

QPushButton:hover {{
    background-color: {P.bg_hover};
    border-color: {P.border_light};
    color: {P.gold};
}}

QPushButton:pressed {{
    background-color: {P.bg_button_act};
    border-color: {P.border_focus};
    color: {P.fg_header};
}}

QPushButton:disabled {{
    background-color: {P.bg};
    color: {P.fg_disabled};
    border-color: {P.border};
}}

QPushButton[role="primary"] {{
    background-color: {P.bg_button_act};
    border-color: {P.border_light};
    color: {P.gold};
    font-weight: bold;
}}

QPushButton[role="primary"]:hover {{
    background-color: #7a5020;
    border-color: {P.border_focus};
    color: {P.fg_header};
}}

QPushButton[role="danger"] {{
    border-color: {P.red};
    color: {P.red};
}}

QPushButton[role="danger"]:hover {{
    background-color: #4a1010;
    border-color: #ff5050;
    color: #ff8080;
}}

QPushButton[role="nav"] {{
    background-color: transparent;
    border: none;
    color: {P.fg_dim};
    padding: {px(4)} {px(10)};
    text-align: left;
    font-weight: normal;
}}

QPushButton[role="nav"]:hover {{
    color: {P.gold};
    background-color: {P.bg_panel};
}}

QPushButton[role="nav"][active="true"] {{
    color: {P.gold};
    font-weight: bold;
    border-left: 2px solid {P.border_light};
}}

/* ── Line edit / input ───────────────────────────────────────────────────*/
QLineEdit {{
    background-color: {P.bg_input};
    color: {P.fg};
    border: 1px solid {P.border};
    border-radius: {px(3)};
    padding: {px(4)} {px(8)};
    selection-background-color: {P.bg_hover};
}}

QLineEdit:focus {{
    border-color: {P.border_focus};
}}

QLineEdit:disabled {{
    color: {P.fg_disabled};
    background-color: {P.bg};
}}

QTextEdit, QPlainTextEdit {{
    background-color: {P.bg_input};
    color: {P.fg};
    border: 1px solid {P.border};
    border-radius: {px(3)};
    selection-background-color: {P.bg_hover};
}}

QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {P.border_focus};
}}

/* ── ComboBox ─────────────────────────────────────────────────────────────*/
QComboBox {{
    background-color: {P.bg_input};
    color: {P.fg};
    border: 1px solid {P.border};
    border-radius: {px(3)};
    padding: {px(4)} {px(8)};
    min-width: {px(80)};
}}

QComboBox:focus {{
    border-color: {P.border_focus};
}}

QComboBox::drop-down {{
    border: none;
    width: {px(20)};
}}

QComboBox::down-arrow {{
    image: none;
    border-left: {px(4)} solid transparent;
    border-right: {px(4)} solid transparent;
    border-top: {px(6)} solid {P.fg_dim};
    margin-right: {px(6)};
}}

QComboBox QAbstractItemView {{
    background-color: {P.bg_panel};
    color: {P.fg};
    border: 1px solid {P.border_light};
    selection-background-color: {P.bg_hover};
    selection-color: {P.gold};
    outline: none;
}}

/* ── Scroll bars ──────────────────────────────────────────────────────────*/
QScrollBar:vertical {{
    background-color: {P.bg};
    width: {px(10)};
    border: none;
    margin: 0px;
}}

QScrollBar::handle:vertical {{
    background-color: {P.border};
    min-height: {px(24)};
    border-radius: {px(4)};
    margin: {px(2)};
}}

QScrollBar::handle:vertical:hover {{
    background-color: {P.border_light};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background-color: {P.bg};
    height: {px(10)};
    border: none;
    margin: 0px;
}}

QScrollBar::handle:horizontal {{
    background-color: {P.border};
    min-width: {px(24)};
    border-radius: {px(4)};
    margin: {px(2)};
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {P.border_light};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ── Tables ───────────────────────────────────────────────────────────────*/
QTableWidget, QTreeWidget, QListWidget {{
    background-color: {P.bg};
    color: {P.fg};
    border: 1px solid {P.border};
    gridline-color: {P.border};
    alternate-background-color: {P.bg_row_alt};
    selection-background-color: {P.bg_hover};
    selection-color: {P.gold};
    outline: none;
}}

QHeaderView {{
    background-color: {P.bg_panel};
}}

QHeaderView::section {{
    background-color: {P.bg_panel};
    color: {P.gold};
    border: none;
    border-bottom: 1px solid {P.border_light};
    padding: {px(4)} {px(8)};
    font-weight: bold;
}}

QHeaderView::section:hover {{
    background-color: {P.bg_hover};
}}

QTableWidget::item:hover {{
    background-color: {P.bg_hover};
}}

/* ── Tabs ────────────────────────────────────────────────────────────────*/
QTabWidget::pane {{
    border: 1px solid {P.border};
    border-radius: {px(4)};
    background-color: {P.bg_panel};
}}

QTabBar::tab {{
    background-color: {P.bg_button};
    color: {P.fg_dim};
    border: 1px solid {P.border};
    border-bottom: none;
    padding: {px(6)} {px(16)};
    border-radius: {px(3)} {px(3)} 0 0;
    margin-right: {px(2)};
}}

QTabBar::tab:selected {{
    background-color: {P.bg_panel};
    color: {P.gold};
    border-color: {P.border_light};
    font-weight: bold;
}}

QTabBar::tab:hover:!selected {{
    background-color: {P.bg_hover};
    color: {P.fg};
}}

/* ── Progress bar ────────────────────────────────────────────────────────*/
QProgressBar {{
    background-color: {P.bg_input};
    border: 1px solid {P.border};
    border-radius: {px(3)};
    text-align: center;
    color: {P.fg};
    height: {px(16)};
}}

QProgressBar::chunk {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {P.border_light}, stop:1 {P.gold}
    );
    border-radius: {px(2)};
}}

/* ── Slider ──────────────────────────────────────────────────────────────*/
QSlider::groove:horizontal {{
    background-color: {P.bg_input};
    border: 1px solid {P.border};
    height: {px(4)};
    border-radius: {px(2)};
}}

QSlider::handle:horizontal {{
    background-color: {P.border_light};
    border: 1px solid {P.border_focus};
    width: {px(14)};
    height: {px(14)};
    border-radius: {px(7)};
    margin: {px(-5)} 0;
}}

QSlider::handle:horizontal:hover {{
    background-color: {P.gold};
}}

/* ── CheckBox / RadioButton ──────────────────────────────────────────────*/
QCheckBox, QRadioButton {{
    background-color: transparent;
    color: {P.fg};
    spacing: {px(6)};
}}

QCheckBox:hover, QRadioButton:hover {{
    color: {P.gold};
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: {px(14)};
    height: {px(14)};
    border: 1px solid {P.border};
    border-radius: {px(2)};
    background-color: {P.bg_input};
}}

QCheckBox::indicator:checked {{
    background-color: {P.bg_hover};
    border-color: {P.border_light};
    image: none;
}}

QCheckBox::indicator:hover {{
    border-color: {P.border_focus};
}}

/* ── Tooltips ────────────────────────────────────────────────────────────*/
QToolTip {{
    background-color: {P.bg_dialog};
    color: {P.fg};
    border: 1px solid {P.border_light};
    padding: {px(4)} {px(8)};
    border-radius: {px(3)};
    font-size: {px(10)};
}}

/* ── Dialogs ─────────────────────────────────────────────────────────────*/
QDialog {{
    background-color: {P.bg_dialog};
    border: 1px solid {P.border_light};
}}

/* ── Menu ────────────────────────────────────────────────────────────────*/
QMenu {{
    background-color: {P.bg_panel};
    border: 1px solid {P.border_light};
    padding: {px(4)};
}}

QMenu::item {{
    padding: {px(6)} {px(24)};
    border-radius: {px(2)};
}}

QMenu::item:selected {{
    background-color: {P.bg_hover};
    color: {P.gold};
}}

QMenu::separator {{
    background-color: {P.border};
    height: 1px;
    margin: {px(4)} {px(8)};
}}

/* ── Splitter ────────────────────────────────────────────────────────────*/
QSplitter::handle {{
    background-color: {P.border};
}}

QSplitter::handle:hover {{
    background-color: {P.border_light};
}}

/* ── SpinBox ─────────────────────────────────────────────────────────────*/
QSpinBox, QDoubleSpinBox {{
    background-color: {P.bg_input};
    color: {P.fg};
    border: 1px solid {P.border};
    border-radius: {px(3)};
    padding: {px(3)} {px(6)};
}}

QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {P.border_focus};
}}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background-color: {P.bg_button};
    border: none;
    width: {px(16)};
}}

QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {P.bg_hover};
}}

/* ── Nav rail items ─────────────────────────────────────────────── */
QPushButton[role="navItem"] {{
    background: transparent;
    color: {P.fg_dim};
    border: none;
    border-left: 3px solid transparent;
    text-align: left;
    padding-left: {px(8)};
    font-size: {px(13)};
}}
QPushButton[role="navItem"]:hover {{
    background: rgba(92, 66, 24, 90);
    color: {P.amber};
    border-left: 3px solid {P.amber};
}}
QPushButton[role="navItem"]:checked {{
    background: {P.bg_hover};
    color: {P.gold};
    border-left: 3px solid {P.gold};
    font-weight: bold;
}}

/* ── Hub cards ───────────────────────────────────────────────────── */
#hubCard {{
    background: {P.bg_panel};
    border: 1px solid {P.border};
    border-radius: 5px;
}}
#hubCard:hover {{
    background: {P.bg_hover};
    border: 1px solid {P.border_light};
}}

/* ── Game header ─────────────────────────────────────────────────── */
#gameHeader {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {P.bg_panel}, stop:1 {P.bg});
    border-bottom: 1px solid {P.border_light};
}}

/* ── App footer ──────────────────────────────────────────────────── */
#appFooter {{
    background: {P.bg};
    border-top: 1px solid {P.border};
}}
"""

# ══════════════════════════════════════════════════════════════════════════════
# ANIMATION UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

class Easing:
    """
    Curated easing curve constants used consistently throughout the UI.
    Using named aliases prevents magic QEasingCurve.Type values scattered
    across the codebase.
    """
    # Screen transitions
    TRANSITION_IN  = QEasingCurve.Type.OutCubic
    TRANSITION_OUT = QEasingCurve.Type.InCubic

    # Button / interactive element feedback
    BUTTON_PRESS   = QEasingCurve.Type.OutBack
    BUTTON_RELEASE = QEasingCurve.Type.InOutCubic

    # Slide panels (sidebars, drawers)
    SLIDE_OPEN  = QEasingCurve.Type.OutQuart
    SLIDE_CLOSE = QEasingCurve.Type.InQuart

    # Toast / notification fly-in
    TOAST_IN  = QEasingCurve.Type.OutBack
    TOAST_OUT = QEasingCurve.Type.InQuart

    # Value counters (gold change flash)
    VALUE_POP  = QEasingCurve.Type.OutElastic
    VALUE_FADE = QEasingCurve.Type.InQuad

    # Generic smooth
    SMOOTH = QEasingCurve.Type.InOutCubic
    LINEAR = QEasingCurve.Type.Linear


class FadeEffect:
    """
    Manages a QGraphicsOpacityEffect + QPropertyAnimation on a target widget.
    Provides  fade_in(ms) / fade_out(ms, on_done)  methods.
    The effect is owned by the target widget (reparented to it).
    """

    def __init__(self, widget: QWidget) -> None:
        self._w = widget
        self._effect = QGraphicsOpacityEffect(widget)
        self._effect.setOpacity(1.0)
        widget.setGraphicsEffect(self._effect)
        self._anim: Optional[QPropertyAnimation] = None

    def fade_in(self, duration_ms: int = 220,
                easing: QEasingCurve.Type = Easing.TRANSITION_IN) -> None:
        self._run(0.0, 1.0, duration_ms, easing)

    def fade_out(self, duration_ms: int = 180,
                 easing: QEasingCurve.Type = Easing.TRANSITION_OUT,
                 on_done: Optional[Callable] = None) -> None:
        self._run(1.0, 0.0, duration_ms, easing, on_done)

    def _run(self, start: float, end: float, ms: int,
             easing: QEasingCurve.Type,
             on_done: Optional[Callable] = None) -> None:
        if self._anim and self._anim.state() == QAbstractAnimation.State.Running:
            self._anim.stop()
        a = QPropertyAnimation(self._effect, b"opacity", self._effect)
        a.setDuration(ms)
        a.setStartValue(start)
        a.setEndValue(end)
        a.setEasingCurve(easing)
        if on_done:
            a.finished.connect(on_done)
        self._anim = a
        a.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


class SlideEffect:
    """
    Animates a widget's geometry to slide in from a given edge.
    Only suitable for top-level panels / drawers.
    """

    class Edge(Enum):
        TOP    = "top"
        BOTTOM = "bottom"
        LEFT   = "left"
        RIGHT  = "right"

    def __init__(self, widget: QWidget, edge: "SlideEffect.Edge") -> None:
        self._w    = widget
        self._edge = edge
        self._anim: Optional[QPropertyAnimation] = None

    def slide_in(self, duration_ms: int = 280) -> None:
        self._run(show=True, ms=duration_ms)

    def slide_out(self, duration_ms: int = 220,
                  on_done: Optional[Callable] = None) -> None:
        self._run(show=False, ms=duration_ms, on_done=on_done)

    def _run(self, show: bool, ms: int,
             on_done: Optional[Callable] = None) -> None:
        if self._anim and self._anim.state() == QAbstractAnimation.State.Running:
            self._anim.stop()

        w = self._w
        parent = w.parent()
        if parent is None:
            return

        pw, ph = parent.width(), parent.height()
        ww, wh = w.width() or UIScale.px(300), w.height() or ph

        hidden_geo = w.geometry()
        shown_geo  = w.geometry()

        edge = self._edge
        if edge == SlideEffect.Edge.RIGHT:
            hidden_geo.moveLeft(pw)
            shown_geo.moveLeft(pw - ww)
        elif edge == SlideEffect.Edge.LEFT:
            hidden_geo.moveLeft(-ww)
            shown_geo.moveLeft(0)
        elif edge == SlideEffect.Edge.TOP:
            hidden_geo.moveTop(-wh)
            shown_geo.moveTop(0)
        elif edge == SlideEffect.Edge.BOTTOM:
            hidden_geo.moveTop(ph)
            shown_geo.moveTop(ph - wh)

        start_geo = hidden_geo if show else shown_geo
        end_geo   = shown_geo  if show else hidden_geo

        w.setGeometry(start_geo)
        w.show() if show else None

        a = QPropertyAnimation(w, b"geometry", w)
        a.setDuration(ms)
        a.setStartValue(start_geo)
        a.setEndValue(end_geo)
        a.setEasingCurve(Easing.SLIDE_OPEN if show else Easing.SLIDE_CLOSE)
        if on_done:
            a.finished.connect(on_done)
        if not show:
            a.finished.connect(w.hide)
        self._anim = a
        a.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


# ══════════════════════════════════════════════════════════════════════════════
# WORKER / THREAD POOL  —  safe non-blocking background tasks
# ══════════════════════════════════════════════════════════════════════════════

class WorkerSignals(QObject):
    """Signals emitted by Worker back to the GUI thread."""
    result   = Signal(object)   # any result payload
    error    = Signal(str)      # error message string
    progress = Signal(int)      # 0-100 progress value
    finished = Signal()         # always emitted last


class Worker(QRunnable):
    """
    Generic background worker.  Use for any network / IO operation.

    Usage:
        def my_task(progress_fn):
            result = do_work()
            return result

        worker = Worker(my_task)
        worker.signals.result.connect(handle_result)
        worker.signals.error.connect(handle_error)
        QThreadPool.globalInstance().start(worker)
    """

    def __init__(self, fn: Callable, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn     = fn
        self.args   = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(
                *self.args,
                progress=self.signals.progress,
                **self.kwargs,
            )
        except TypeError:
            # fn doesn't accept progress kwarg — call without it
            try:
                result = self.fn(*self.args, **self.kwargs)
            except Exception as exc:
                self.signals.error.emit(str(exc))
                self.signals.finished.emit()
                return
        except Exception as exc:
            self.signals.error.emit(str(exc))
            self.signals.finished.emit()
            return
        self.signals.result.emit(result)
        self.signals.finished.emit()


def run_async(fn: Callable, *args: Any,
              on_result: Optional[Callable]  = None,
              on_error:  Optional[Callable]  = None,
              on_done:   Optional[Callable]  = None,
              **kwargs: Any) -> Worker:
    """
    Convenience: submit a callable to the global QThreadPool.
    Returns the Worker so callers can connect additional signals if needed.
    """
    worker = Worker(fn, *args, **kwargs)
    if on_result: worker.signals.result.connect(on_result)
    if on_error:  worker.signals.error.connect(on_error)
    if on_done:   worker.signals.finished.connect(on_done)
    QThreadPool.globalInstance().start(worker)
    return worker

# ══════════════════════════════════════════════════════════════════════════════
# HOTKEY MANAGER  —  global keyboard shortcut registry
# ══════════════════════════════════════════════════════════════════════════════

class HotkeyManager(QObject):
    """
    Manages named global shortcuts bound to a parent QMainWindow.
    Shortcuts are derived from  game.settings.hotkeys  (DEFAULT_HOTKEYS dict).
    Call  reload()  after any hotkey remapping to rebuild all QShortcuts.
    """

    triggered = Signal(str)  # emits the action name

    def __init__(self, parent: "GameApp") -> None:
        super().__init__(parent)
        self._parent   = parent
        self._shortcuts: Dict[str, QShortcut] = {}

    def reload(self, hotkeys: Dict[str, str]) -> None:
        """Destroy all existing shortcuts and rebuild from  hotkeys  dict."""
        for sc in self._shortcuts.values():
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts.clear()

        for action, binding in hotkeys.items():
            key_seq = self._parse(binding)
            if not key_seq:
                continue
            sc = QShortcut(key_seq, self._parent)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            # Capture action name in closure
            sc.activated.connect(lambda a=action: self.triggered.emit(a))
            self._shortcuts[action] = sc

    @staticmethod
    def _parse(binding: str) -> Optional[QKeySequence]:
        """Convert e.g. 'Control-s' or 'F10' or 't' to QKeySequence."""
        if not binding:
            return None
        # Tkinter-style modifiers → Qt-style
        binding = (binding
                   .replace("Control-", "Ctrl+")
                   .replace("Shift-",   "Shift+")
                   .replace("Alt-",     "Alt+"))
        ks = QKeySequence(binding)
        return ks if not ks.isEmpty() else None

# ══════════════════════════════════════════════════════════════════════════════
# SCREEN BASE CLASS
# ══════════════════════════════════════════════════════════════════════════════

class Screen(QWidget):
    """
    Base class for every game screen.

    Lifecycle (called by GameApp.show()):
        build()    — create all widgets; called exactly once on first show
        refresh()  — pull current game state into widgets; called on every show
        on_show()  — hook called each time this screen becomes active
        on_hide()  — hook called each time this screen is concealed

    Convenience helpers:
        self.app          → GameApp
        self.game         → Game model
        self.msg          → MessageBar  (ok / warn / err)

    Layout helpers:
        self.section_label(text)        → gold divider label
        self.action_button(text, fn)    → standard primary button
        self.back_button(text)          → back-navigation button
        self.colored_label(text, color) → label with explicit colour
        self.h_sep()                    → horizontal separator line
    """

    def __init__(self, app: "GameApp") -> None:
        parent = app.content_stack
        super().__init__(parent)
        self.app    = app
        self.game   = app.game
        self.msg    = app.message_bar
        self._built = False
        self._fade  = FadeEffect(self)

        self.setObjectName("screen")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def activate(self) -> None:
        """Called by GameApp to make this screen visible."""
        if not self._built:
            self.build()
            self._built = True
        self.refresh()
        self.on_show()
        self._fade.fade_in(220)

    def deactivate(self) -> None:
        """Called by GameApp to hide this screen."""
        self.on_hide()

    # ── Subclass API ──────────────────────────────────────────────────────────

    def build(self) -> None:
        """Override: create all widgets here.  Called exactly once."""
        pass

    def refresh(self) -> None:
        """Override: update widget values from current game state."""
        pass

    def on_show(self) -> None:
        """Override: runs each time this screen becomes the active screen."""
        pass

    def on_hide(self) -> None:
        """Override: runs each time this screen is concealed."""
        pass

    # ── Widget factory helpers ────────────────────────────────────────────────

    def section_label(self, text: str, parent: Optional[QWidget] = None) -> QLabel:
        lbl = QLabel(f"  ✦  {text.upper()}  ✦", parent or self)
        lbl.setFont(Fonts.body_bold)
        lbl.setProperty("role", "section")
        lbl.setStyleSheet(f"color: {P.gold}; padding: 4px 0px;")
        return lbl

    def action_button(self, text: str, command: Callable,
                      parent: Optional[QWidget] = None,
                      role: str = "primary") -> "MtButton":
        btn = MtButton(text, parent or self, role=role)
        btn.clicked.connect(command)
        return btn

    def back_button(self, text: str = "◄  Back",
                    parent: Optional[QWidget] = None) -> "MtButton":
        btn = MtButton(text, parent or self, role="nav")
        btn.clicked.connect(self.app.go_back)
        return btn

    def colored_label(self, text: str, color: str,
                      font: Optional[QFont] = None,
                      parent: Optional[QWidget] = None) -> QLabel:
        lbl = QLabel(text, parent or self)
        lbl.setFont(font or Fonts.body)
        lbl.setStyleSheet(f"color: {color}; background: transparent;")
        return lbl

    def h_sep(self, parent: Optional[QWidget] = None) -> QFrame:
        line = QFrame(parent or self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {P.border}; background-color: {P.border};")
        line.setFixedHeight(1)
        return line

    def make_panel(self, parent: Optional[QWidget] = None,
                   object_name: str = "panel") -> QFrame:
        """A styled panel frame."""
        f = QFrame(parent or self)
        f.setObjectName(object_name)
        f.setProperty("class", object_name)
        return f

# ══════════════════════════════════════════════════════════════════════════════
# MT BUTTON  —  custom QPushButton with press animation
# ══════════════════════════════════════════════════════════════════════════════

class MtButton(QPushButton):
    """
    Standard Merchant Tycoon button.
    Adds a subtle scale-down press animation and correct role styling.
    """

    def __init__(self, text: str = "",
                 parent: Optional[QWidget] = None,
                 role: str = "primary",
                 icon: Optional[QIcon] = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", role)
        if icon:
            self.setIcon(icon)
        self.setFont(Fonts.body_bold)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def setRole(self, role: str) -> None:
        self.setProperty("role", role)
        self.style().unpolish(self)
        self.style().polish(self)

# ══════════════════════════════════════════════════════════════════════════════
# STATUS BAR  —  persistent HUD strip
# ══════════════════════════════════════════════════════════════════════════════

class StatusBar(QWidget):
    """
    Persistent top strip — always visible, refreshed after every action.
    Displays: player name, title, date/season, gold, bank, location,
              net worth, action slots, heat, active events.
    """

    def __init__(self, game: Game, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.game = game
        self._prev_gold: float = -1.0
        self.setObjectName("statusBar")
        self.setFixedHeight(UIScale.px(90))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"""
            #statusBar {{
                background-color: {P.bg_panel};
                border-bottom: 2px solid {P.border_light};
            }}
        """)
        self._build()

    # ── Private build ─────────────────────────────────────────────────────────

    def _mk_label(self, text: str = "", font: Optional[QFont] = None,
                  colour: str = P.fg) -> QLabel:
        lbl = QLabel(text, self)
        lbl.setFont(font or Fonts.body)
        lbl.setStyleSheet(f"color: {colour}; background: transparent;")
        return lbl

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(10), UIScale.px(4),
                                UIScale.px(10), UIScale.px(4))
        root.setSpacing(UIScale.px(2))

        # Row 1: player name · date/season · reputation
        r1 = QHBoxLayout()
        r1.setSpacing(UIScale.px(12))
        self._player   = self._mk_label(font=Fonts.body_bold, colour=P.fg_dim)
        self._title_lbl = self._mk_label(font=Fonts.body_small, colour=P.gold)
        self._date     = self._mk_label(font=Fonts.body_small, colour=P.fg_dim)
        self._rep      = self._mk_label(font=Fonts.body_small, colour=P.green)
        r1.addWidget(self._player)
        r1.addWidget(self._title_lbl)
        r1.addSpacing(UIScale.px(6))
        r1.addWidget(self._date)
        r1.addStretch()
        r1.addWidget(self._rep)

        # Row 2: gold / bank / location / net worth
        r2 = QHBoxLayout()
        r2.setSpacing(UIScale.px(12))
        self._gold     = self._mk_label(font=Fonts.body_bold, colour=P.amber)
        self._location = self._mk_label(font=Fonts.body,      colour=P.gold)
        self._nw       = self._mk_label(font=Fonts.body_small, colour=P.fg_dim)
        r2.addWidget(self._gold)
        r2.addSpacing(UIScale.px(6))
        r2.addWidget(self._location)
        r2.addStretch()
        r2.addWidget(self._nw)

        # Row 3: action slots · heat · events
        r3 = QHBoxLayout()
        r3.setSpacing(UIScale.px(12))
        self._slots  = self._mk_label(font=Fonts.body_small, colour=P.gold)
        self._heat   = self._mk_label(font=Fonts.body_small, colour=P.red)
        self._events = self._mk_label(font=Fonts.body_small, colour=P.amber)
        r3.addWidget(self._slots)
        r3.addWidget(self._heat)
        r3.addWidget(self._events)
        r3.addStretch()

        root.addLayout(r1)
        root.addLayout(r2)
        root.addLayout(r3)

        # Gold flash effect
        self._gold_fade = FadeEffect(self._gold)

    # ── Public refresh ────────────────────────────────────────────────────────

    def refresh(self) -> None:
        g = self.game

        # Player name + active title
        name = g.player_name or "Merchant"
        self._player.setText(f"⚘  {name}")
        active_title = getattr(g, "active_title_id", None)
        title_text   = ""
        if active_title and active_title in TITLES_BY_ID:
            title_text = f"〔{TITLES_BY_ID[active_title]['name']}〕"
        self._title_lbl.setText(title_text)

        # Date / season
        season_col = SEASON_COLOURS.get(g.season, P.fg)
        self._date.setText(f"Year {g.year}  ·  Day {g.day}  ·  {g.season.value}")
        self._date.setStyleSheet(f"color: {season_col}; background: transparent;")

        # Reputation
        rep_lbl_text, rep_col = rep_label(g.reputation)
        self._rep.setText(f"Rep: {g.reputation}  ({rep_lbl_text})")
        self._rep.setStyleSheet(f"color: {rep_col}; background: transparent;")

        # Gold (with flash on change)
        new_gold = g.inventory.gold
        self._gold.setText(f"◆ {new_gold:,.0f}g   Bank: {g.bank_balance:,.0f}g")
        if self._prev_gold >= 0 and new_gold != self._prev_gold:
            flash_col = P.green if new_gold > self._prev_gold else P.red
            self._flash_gold(flash_col)
        self._prev_gold = new_gold

        # Location
        self._location.setText(f"📍  {g.current_area.value}")

        # Net worth
        self._nw.setText(f"Net Worth: {g._net_worth():,.2f}g")

        # Action slots
        used = g.daily_time_units
        left = g.DAILY_TIME_UNITS - used
        bar  = "●" * used + "○" * left
        slot_col = P.red if left == 0 else P.amber if left <= 2 else P.gold
        self._slots.setText(f"⌛ {bar}  ({left} actions left)")
        self._slots.setStyleSheet(f"color: {slot_col}; background: transparent;")

        # Heat
        if g.heat > 0:
            heat_col = P.red if g.heat > 50 else P.amber
            self._heat.setText(f"🔥 Heat: {g.heat}/100")
            self._heat.setStyleSheet(f"color: {heat_col}; background: transparent;")
        else:
            self._heat.setText("")

        # Active events
        events: List[str] = []
        for mkt in g.markets.values():
            events.extend(mkt.active_events)
        if events:
            unique = list(dict.fromkeys(events))[:3]
            self._events.setText("Events: " + "  ·  ".join(unique))
        else:
            self._events.setText("")

    def _flash_gold(self, colour: str) -> None:
        """Brief colour flash on gold label when value changes."""
        self._gold.setStyleSheet(f"color: {colour}; background: transparent;")
        QTimer.singleShot(600, lambda: self._gold.setStyleSheet(
            f"color: {P.amber}; background: transparent;"))


# ══════════════════════════════════════════════════════════════════════════════
# MESSAGE BAR  —  bottom feedback strip
# ══════════════════════════════════════════════════════════════════════════════

class MessageBar(QWidget):
    """
    Slim bottom strip for user feedback.
    Messages animate in (height expand), auto-clear after _CLEAR_MS.
    Severity: ok (green) / warn (amber) / err (red) / info (gold).
    """

    _CLEAR_MS   = 6_000
    _TARGET_H   = UIScale.px(32)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("messageBar")
        self.setFixedHeight(0)  # hidden initially
        self.setStyleSheet(f"""
            #messageBar {{
                background-color: {P.bg_panel};
                border-top: 1px solid {P.border};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(UIScale.px(12), 0, UIScale.px(12), 0)
        self._label = QLabel("", self)
        self._label.setFont(Fonts.body_small)
        self._label.setStyleSheet("background: transparent;")
        layout.addWidget(self._label)

        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(self._clear)

        self._anim = QPropertyAnimation(self, b"maximumHeight", self)
        self._anim.setEasingCurve(Easing.SMOOTH)

        self._toast_fn: Optional[Callable] = None   # set by GameApp

    # ── Public API ────────────────────────────────────────────────────────────

    def ok(self,   text: str) -> None: self._show(f"  ✔  {text}", P.green)
    def warn(self, text: str) -> None: self._show(f"  ⚠  {text}", P.amber)
    def err(self,  text: str) -> None: self._show(f"  ✘  {text}", P.red)
    def info(self, text: str) -> None: self._show(f"  ›  {text}", P.gold)

    # ── Private ───────────────────────────────────────────────────────────────

    def _show(self, text: str, colour: str) -> None:
        self._label.setText(text)
        self._label.setStyleSheet(f"color: {colour}; background: transparent;")

        if self._anim.state() == QAbstractAnimation.State.Running:
            self._anim.stop()

        self._anim.setDuration(120)
        self._anim.setStartValue(self.height())
        self._anim.setEndValue(self._TARGET_H)
        self.setMaximumHeight(self.height())
        self.setMinimumHeight(0)
        self._anim.start()

        self._clear_timer.start(self._CLEAR_MS)

        if self._toast_fn:
            try:
                self._toast_fn(text.strip().lstrip("✔⚠✘› "), colour)
            except Exception:
                pass

    def _clear(self) -> None:
        if self._anim.state() == QAbstractAnimation.State.Running:
            self._anim.stop()
        self._anim.setDuration(180)
        self._anim.setStartValue(self.height())
        self._anim.setEndValue(0)
        self._anim.start()
        self._label.setText("")


# ══════════════════════════════════════════════════════════════════════════════
# GAME TOAST  —  floating transient notification overlay
# ══════════════════════════════════════════════════════════════════════════════

class GameToast(QWidget):
    """
    Small floating notification that slides up from the bottom-right,
    lingers, then fades out.  Does not steal focus.
    """

    _DURATION_MS  = 3_000
    _SLIDE_IN_MS  = 280
    _FADE_OUT_MS  = 400
    _MAX_VISIBLE  = 4   # stack limit before oldest is dismissed

    _active: List["GameToast"] = []   # class-level live list

    def __init__(self, parent: QWidget, text: str,
                 colour: str = P.amber) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.ToolTip |
                            Qt.WindowType.WindowStaysOnTopHint)

        # Limit active toasts
        while len(GameToast._active) >= self._MAX_VISIBLE:
            oldest = GameToast._active.pop(0)
            try:
                oldest._dismiss_now()
            except Exception:
                pass

        GameToast._active.append(self)

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {P.bg_dialog};
                border: 1px solid {colour};
                border-radius: 5px;
                padding: 4px 12px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(UIScale.px(12), UIScale.px(6),
                                  UIScale.px(12), UIScale.px(6))
        lbl = QLabel(text, self)
        lbl.setFont(Fonts.body_small)
        lbl.setStyleSheet(f"color: {colour}; background: transparent; border: none;")
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(UIScale.px(300))
        layout.addWidget(lbl)

        self.adjustSize()

        # Position: bottom-right of parent, stacked
        idx        = len(GameToast._active) - 1
        margin     = UIScale.px(16)
        pgeom      = parent.rect()
        px_        = parent.mapToGlobal(QPoint(0, 0))
        start_x    = px_.x() + pgeom.width() - self.width() - margin
        start_y    = px_.y() + pgeom.height()  # off-screen bottom
        end_y      = (px_.y() + pgeom.height() - margin
                      - (self.height() + margin) * (idx + 1))

        self.move(start_x, start_y)
        self.show()

        # Slide in
        self._pos_anim = QPropertyAnimation(self, b"pos", self)
        self._pos_anim.setDuration(self._SLIDE_IN_MS)
        self._pos_anim.setStartValue(QPoint(start_x, start_y))
        self._pos_anim.setEndValue(QPoint(start_x, end_y))
        self._pos_anim.setEasingCurve(Easing.TOAST_IN)
        self._pos_anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

        # Auto-dismiss
        QTimer.singleShot(self._DURATION_MS, self._start_fade_out)

    def _start_fade_out(self) -> None:
        self._opacity_eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_eff)
        self._fade_anim = QPropertyAnimation(self._opacity_eff, b"opacity", self)
        self._fade_anim.setDuration(self._FADE_OUT_MS)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(Easing.TOAST_OUT)
        self._fade_anim.finished.connect(self._dismiss_now)
        self._fade_anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _dismiss_now(self) -> None:
        try:
            GameToast._active.remove(self)
        except ValueError:
            pass
        self.hide()
        self.deleteLater()


# ══════════════════════════════════════════════════════════════════════════════
# DATA TABLE  —  high-performance themed QTableWidget wrapper
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class _TableColumn:
    """Column definition for DataTable."""
    key:       str
    heading:   str
    width:     int
    alignment: Qt.AlignmentFlag = field(
        default_factory=lambda: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)


class DataTable(QWidget):
    """
    Scrollable table for game data.  Wraps QTableWidget with Merchant Tycoon
    theming, column definitions, hover highlighting, and row-colour tagging.

    columns — list of (key, heading, pixel_width, alignment)
    alignment is optional; default is  Qt.AlignmentFlag.AlignLeft

    Usage:
        cols = [("name","Item",200), ("price","Price",80), ("stock","Stock",60)]
        table = DataTable(parent, cols)
        table.load([
            {"name": "Fish", "price": "12g", "stock": "45", "_tag": "green"},
            …
        ])
        row = table.selected()   # → row dict or None
    """

    # Colour tags mapped to QColor
    TAG_COLOURS: Dict[str, QColor] = {}  # populated after class definition

    # Column type alias for external use
    Column = _TableColumn

    row_double_clicked = Signal(dict)   # emits the row data dict
    row_selected       = Signal(dict)   # emits on selection change
    row_right_clicked  = Signal(dict)   # emits on right-click

    def __init__(self,
                 parent: Optional[QWidget],
                 columns: List[Tuple],
                 row_height: int = 24,
                 alternating: bool = True,
                 multi_select: bool = False) -> None:
        super().__init__(parent)

        self._col_defs: List[_TableColumn] = []
        for col in columns:
            key, heading, width = col[0], col[1], col[2]
            align = col[3] if len(col) > 3 else (Qt.AlignmentFlag.AlignLeft |
                                                  Qt.AlignmentFlag.AlignVCenter)
            self._col_defs.append(_TableColumn(key, heading, width, align))

        self._rows: List[Dict] = []
        self._row_height = UIScale.px(row_height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._table = QTableWidget(0, len(self._col_defs), self)
        self._table.setObjectName("dataTable")
        self._table.setAlternatingRowColors(alternating)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
            if multi_select else
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_right_click)
        self._table.itemDoubleClicked.connect(lambda _: self._emit_double())
        self._table.itemSelectionChanged.connect(self._emit_select)
        self._table.setMouseTracking(True)

        # Column headers
        hdr = self._table.horizontalHeader()
        hdr.setHighlightSections(False)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        for i, col in enumerate(self._col_defs):
            item = QTableWidgetItem(col.heading)
            item.setFont(Fonts.body_bold)
            self._table.setHorizontalHeaderItem(i, item)
            self._table.setColumnWidth(i, UIScale.px(col.width))

        hdr.setStretchLastSection(True)
        self._table.verticalHeader().setDefaultSectionSize(self._row_height)

        layout.addWidget(self._table)

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, rows: List[Dict], tag_key: str = "_tag") -> None:
        """Replace all rows.  Optional  tag_key  sets foreground colour per row."""
        self._rows = list(rows)
        self._table.setUpdatesEnabled(False)
        self._table.setRowCount(0)
        self._table.setRowCount(len(rows))

        for r_idx, row in enumerate(rows):
            colour = None
            if tag_key and tag_key in row:
                colour = self.TAG_COLOURS.get(row[tag_key])

            for c_idx, col in enumerate(self._col_defs):
                val  = row.get(col.key, "")
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(col.alignment)
                item.setFont(Fonts.mono if self._is_numeric(str(val))
                             else Fonts.body)
                if colour:
                    item.setForeground(colour)
                item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                self._table.setItem(r_idx, c_idx, item)

        self._table.setUpdatesEnabled(True)

    def selected(self) -> Optional[Dict]:
        """Return the original row dict for the first selected row, or None."""
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if 0 <= idx < len(self._rows):
            return self._rows[idx]
        return None

    def selected_all(self) -> List[Dict]:
        """Return all selected row dicts (multi-select mode)."""
        idxs = sorted({i.row() for i in self._table.selectionModel().selectedRows()})
        return [self._rows[i] for i in idxs if 0 <= i < len(self._rows)]

    def clear(self) -> None:
        self._rows = []
        self._table.setRowCount(0)

    def sort_by(self, col_key: str, ascending: bool = True) -> None:
        """Sort rows by a given column key."""
        idx = next((i for i, c in enumerate(self._col_defs) if c.key == col_key), None)
        if idx is None:
            return
        order = Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder
        self._table.sortItems(idx, order)

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _is_numeric(s: str) -> bool:
        try:
            float(s.replace(",", "").replace("g", ""))
            return True
        except ValueError:
            return False

    def _emit_double(self) -> None:
        row = self.selected()
        if row:
            self.row_double_clicked.emit(row)

    def _emit_select(self) -> None:
        row = self.selected()
        if row:
            self.row_selected.emit(row)

    def _on_right_click(self, pos: QPoint) -> None:
        item = self._table.itemAt(pos)
        if item is None:
            return
        r = item.row()
        if 0 <= r < len(self._rows):
            self.row_right_clicked.emit(self._rows[r])


# Populate TAG_COLOURS after QColor is usable (requires QApplication to exist
# at runtime; deferred so module import is safe without a running app)
def _init_table_tag_colours() -> None:
    DataTable.TAG_COLOURS = {
        "green":  P.qcolor(P.green),
        "yellow": P.qcolor(P.amber),
        "amber":  P.qcolor(P.amber),
        "red":    P.qcolor(P.red),
        "gold":   P.qcolor(P.gold),
        "cyan":   P.qcolor(P.gold),
        "dim":    P.qcolor(P.fg_dim),
        "blue":   P.qcolor(P.blue),
        "purple": P.qcolor(P.purple),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SCROLLABLE FRAME  —  vertical scroll container
# ══════════════════════════════════════════════════════════════════════════════

class ScrollableFrame(QScrollArea):
    """
    Vertically scrollable container.
    Pack child widgets into  self.inner  as if it were a normal QWidget.

    Usage:
        sf = ScrollableFrame(parent)
        layout = QVBoxLayout(sf.inner)
        layout.addWidget(SomeWidget())
    """

    def __init__(self, parent: Optional[QWidget] = None,
                 horizontal: bool = False) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if horizontal else
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.inner = QWidget()
        self.inner.setObjectName("scrollInner")
        self.inner.setStyleSheet(f"#scrollInner {{ background-color: {P.bg}; }}")
        self.setWidget(self.inner)

    def wheelEvent(self, event) -> None:
        # Smooth wheel scrolling via vertical scroll bar
        delta = event.angleDelta().y()
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() - delta // 3
        )

# ══════════════════════════════════════════════════════════════════════════════
# CUSTOM TITLE BAR  —  frameless window chrome
# ══════════════════════════════════════════════════════════════════════════════

class CustomTitleBar(QWidget):
    """
    Frameless custom window chrome.
    Supports drag-to-move, double-click-to-maximise, and standard
    min/max/close controls with PySide6 animations.
    """

    _BUTTON_W = 46   # slightly wider for comfortable click targets

    # Per-button hover background colours
    _BTN_HOVER = {
        "Minimise": "rgba(255, 180, 40, 35)",
        "Maximise": "rgba(80, 220, 60, 30)",
        "Close":    "rgba(240, 50, 50, 50)",
    }

    def __init__(self, window: "GameApp") -> None:
        super().__init__(window)
        self._window     = window
        self._drag_pos:  Optional[QPoint] = None
        self._maximised  = False
        self._max_btn:   Optional[QPushButton] = None

        self.setObjectName("titleBar")
        self.setFixedHeight(UIScale.px(38))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_style()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(UIScale.px(12), 0, 0, 0)
        layout.setSpacing(2)

        # Decorative icon + game title
        icon_lbl = QLabel("⚔", self)
        icon_lbl.setStyleSheet(f"color: {P.border_light}; background: transparent; font-size: 14px;")
        self._title_lbl = QLabel("  Merchant Tycoon", self)
        self._title_lbl.setFont(Fonts.heading)
        self._title_lbl.setStyleSheet(f"color: {P.gold}; background: transparent; letter-spacing: 1px;")

        layout.addWidget(icon_lbl)
        layout.addWidget(self._title_lbl)
        layout.addStretch()

        # Scale indicator label (hidden by default, shown during Ctrl+Wheel)
        self._scale_lbl = QLabel("", self)
        self._scale_lbl.setFont(Fonts.tiny)
        self._scale_lbl.setStyleSheet(f"color: {P.fg_dim}; background: transparent; padding-right: 10px;")
        layout.addWidget(self._scale_lbl)

        # Window control buttons: — ⬜/❐ ✕
        btn_defs = [
            ("—",  P.amber, P.amber, "Minimise", window.showMinimized),
            ("⬜", P.green, P.green, "Maximise", self._toggle_maximise),
            ("✕",  P.red,  P.red,   "Close",    window.quit_game),
        ]
        for symbol, colour, hover_fg, tip, slot in btn_defs:
            btn = QPushButton(symbol, self)
            btn.setFixedSize(UIScale.px(self._BUTTON_W), UIScale.px(38))
            btn.setToolTip(tip)
            hover_bg = self._BTN_HOVER.get(tip, "rgba(255,255,255,20)")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {colour};
                    border: none;
                    font-size: 15px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background: {hover_bg};
                    color: {hover_fg};
                }}
                QPushButton:pressed {{
                    background: rgba(255, 255, 255, 45);
                }}
            """)
            btn.clicked.connect(slot)
            layout.addWidget(btn)
            if tip == "Maximise":
                self._max_btn = btn

    def _apply_style(self) -> None:
        self.setStyleSheet(f"""
            #titleBar {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {P.grad_header_top},
                    stop:1 {P.grad_header_bot}
                );
                border-bottom: 2px solid {P.border_light};
            }}
        """)

    def show_scale(self, pct: int) -> None:
        """Briefly display the current UI scale percentage in the title bar."""
        self._scale_lbl.setText(f"UI Scale  {pct}%")
        if hasattr(self, "_scale_timer"):
            self._scale_timer.stop()
        self._scale_timer = QTimer(self)
        self._scale_timer.setSingleShot(True)
        self._scale_timer.timeout.connect(lambda: self._scale_lbl.setText(""))
        self._scale_timer.start(1800)

    # ── Drag to move ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._window.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (self._drag_pos is not None and
                event.buttons() & Qt.MouseButton.LeftButton):
            if self._maximised:
                # Restore first, then recalculate drag origin relative to restored pos
                self._toggle_maximise()
                self._drag_pos = event.globalPosition().toPoint() - self._window.pos()
            self._window.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximise()

    def _toggle_maximise(self) -> None:
        if self._maximised:
            self._window.showNormal()
            if self._max_btn:
                self._max_btn.setText("⬜")
                self._max_btn.setToolTip("Maximise")
        else:
            self._window.showMaximized()
            if self._max_btn:
                self._max_btn.setText("❐")
                self._max_btn.setToolTip("Restore")
        self._maximised = not self._maximised


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN TRANSITION MANAGER  —  animated cross-fade between screens
# ══════════════════════════════════════════════════════════════════════════════

class ScreenTransitionManager:
    """
    Manages animated transitions between Screen instances in a QStackedWidget.
    Uses QGraphicsOpacityEffect animations so transitions are GPU-composited
    and do not block the event loop.
    """

    def __init__(self, stack: QStackedWidget) -> None:
        self._stack      = stack
        self._in_transit = False
        self._duration   = 200   # ms per leg; total = 2 × this

    def switch_to(self, index: int,
                  on_switched: Optional[Callable] = None) -> None:
        """
        Fade out the current widget, switch stack index, fade in new widget.
        If a transition is already running the switch is deferred.
        """
        if self._in_transit:
            QTimer.singleShot(self._duration + 50,
                              lambda: self.switch_to(index, on_switched))
            return

        current_widget = self._stack.currentWidget()
        if self._stack.currentIndex() == index:
            if on_switched:
                on_switched()
            return

        self._in_transit = True

        # Apply opacity effect to the outgoing widget
        out_effect = QGraphicsOpacityEffect(current_widget)
        current_widget.setGraphicsEffect(out_effect)

        fade_out = QPropertyAnimation(out_effect, b"opacity", current_widget)
        fade_out.setDuration(self._duration)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(Easing.TRANSITION_OUT)

        def _do_switch() -> None:
            current_widget.setGraphicsEffect(None)
            self._stack.setCurrentIndex(index)
            new_widget = self._stack.currentWidget()

            in_effect = QGraphicsOpacityEffect(new_widget)
            new_widget.setGraphicsEffect(in_effect)

            fade_in = QPropertyAnimation(in_effect, b"opacity", new_widget)
            fade_in.setDuration(self._duration)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(Easing.TRANSITION_IN)

            def _done() -> None:
                new_widget.setGraphicsEffect(None)
                self._in_transit = False
                if on_switched:
                    on_switched()

            fade_in.finished.connect(_done)
            fade_in.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

        fade_out.finished.connect(_do_switch)
        fade_out.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


# ══════════════════════════════════════════════════════════════════════════════
# GAME HEADER  —  compact persistent top bar (day / stats / action buttons)
# ══════════════════════════════════════════════════════════════════════════════

class GameHeader(QWidget):
    """
    Persistent one-row game info bar shown below the title bar.
    Left  : Day · Season · Year  |  action-slot dots
    Center: Gold  |  Reputation  |  Networth  |  Location
    Right : Inbox · Profile · Cloud sync  (+ min/max/close gap)
    """

    H = 46   # nominal unscaled height (px)

    def __init__(self, game: "Game", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._game = game
        self.setObjectName("gameHeader")
        self.setFixedHeight(UIScale.px(self.H))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(
            UIScale.px(10), UIScale.px(4),
            UIScale.px(8),  UIScale.px(4),
        )
        lay.setSpacing(0)

        # ── Left block: day / season / slots ────────────────────────────────────
        left_col = QVBoxLayout()
        left_col.setSpacing(2)

        self._day_lbl = QLabel("Day 1  ·  Spring  ·  Year 1", self)
        self._day_lbl.setFont(Fonts.body_bold)
        self._day_lbl.setStyleSheet(
            f"color:{P.gold}; background:transparent;"
        )
        left_col.addWidget(self._day_lbl)

        self._slots_lbl = QLabel("●●●●●  5 / 5  actions left", self)
        self._slots_lbl.setFont(Fonts.tiny)
        self._slots_lbl.setStyleSheet(
            f"color:{P.fg_dim}; background:transparent;"
        )
        left_col.addWidget(self._slots_lbl)

        lay.addLayout(left_col)
        lay.addSpacing(UIScale.px(18))

        # ── Vertical divider helper ──────────────────────────────────────────
        def _vdiv() -> QFrame:
            f = QFrame(self)
            f.setFrameShape(QFrame.Shape.VLine)
            f.setFixedWidth(1)
            f.setFixedHeight(UIScale.px(26))
            f.setStyleSheet(
                f"background:{P.border}; border:none; color:{P.border};"
            )
            return f

        # ── Center stat pills ─────────────────────────────────────────────────
        def _stat(attr: str, colour: str) -> QLabel:
            lbl = QLabel("—", self)
            lbl.setFont(Fonts.body_bold)
            lbl.setStyleSheet(f"color:{colour}; background:transparent;")
            lbl.setAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            )
            setattr(self, attr, lbl)
            return lbl

        center = QHBoxLayout()
        center.setSpacing(UIScale.px(14))
        center.addWidget(_stat("_gold_lbl",    P.gold))
        center.addWidget(_vdiv())
        center.addWidget(_stat("_rep_lbl",     P.amber))
        center.addWidget(_vdiv())
        center.addWidget(_stat("_net_lbl",     P.cream))
        center.addWidget(_vdiv())
        center.addWidget(_stat("_loc_lbl",     P.fg_dim))
        lay.addLayout(center)
        lay.addStretch()

        # ── Right: icon action buttons ───────────────────────────────────────
        def _icon_btn(sym: str, tip: str) -> QPushButton:
            btn = QPushButton(sym, self)
            btn.setFixedSize(UIScale.px(34), UIScale.px(34))
            btn.setToolTip(tip)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {P.fg_dim};
                    border: none;
                    border-radius: 4px;
                    font-size: 14px;
                }}
                QPushButton:hover {{
                    background: {P.bg_hover};
                    color: {P.gold};
                }}
            """)
            return btn

        self._inbox_btn   = _icon_btn("🔔", "Inbox")
        self._profile_btn = _icon_btn("👤", "Profile")
        self._sync_btn    = _icon_btn("☁",  "Cloud sync")

        right = QHBoxLayout()
        right.setSpacing(UIScale.px(2))
        right.addWidget(self._inbox_btn)
        right.addWidget(self._profile_btn)
        right.addWidget(self._sync_btn)
        lay.addLayout(right)

    def refresh(self) -> None:
        g   = self._game
        inv = getattr(g, "inventory", None)

        # Gold
        gold = getattr(inv, "gold", 0) if inv else 0
        self._gold_lbl.setText(f"💰 {gold:,.0f}g")

        # Reputation
        rep      = getattr(g, "reputation", 0)
        rl, rc   = rep_label(rep)
        self._rep_lbl.setText(f"⭐ {rl}  ({rep})")
        self._rep_lbl.setStyleSheet(f"color:{rc}; background:transparent;")

        # Networth
        nw = getattr(g, "net_worth", gold)
        if callable(nw):
            nw = nw()
        self._net_lbl.setText(f"💎 {nw:,.0f}g")

        # Location
        loc   = getattr(g, "area", None)
        loc_s = loc.value if loc and hasattr(loc, "value") else str(loc or "?")
        self._loc_lbl.setText(f"📍 {loc_s}")

        # Day / Season / Year
        day    = getattr(g, "day",    1)
        year   = getattr(g, "year",   1)
        season = getattr(g, "season", None)
        sea_s  = season.value if season and hasattr(season, "value") else "?"
        sea_c  = SEASON_COLOURS.get(season, P.gold)
        self._day_lbl.setText(f"Day {day}  ·  {sea_s}  ·  Year {year}")
        self._day_lbl.setStyleSheet(f"color:{sea_c}; background:transparent;")

        # Slots
        used = getattr(g, "slots_used", 0)
        mxs  = getattr(g, "action_slots", 5)
        free = max(0, mxs - used)
        dots = "●" * used + "○" * free
        col  = P.red if free == 0 else P.amber if free <= 1 else P.fg_dim
        self._slots_lbl.setText(f"{dots}  {free}/{mxs} actions remaining")
        self._slots_lbl.setStyleSheet(f"color:{col}; background:transparent;")

    def set_inbox_badge(self, n: int) -> None:
        """Update the inbox button to show an unread count."""
        if n > 0:
            self._inbox_btn.setText(f"🔔 {min(n, 9)}")
            self._inbox_btn.setStyleSheet(
                f"QPushButton{{background:transparent; color:{P.red};"
                f" border:none; border-radius:4px; font-size:14px;}}"
                f"QPushButton:hover{{background:{P.bg_hover}; color:{P.gold};}}"
            )
        else:
            self._inbox_btn.setText("🔔")
            self._inbox_btn.setStyleSheet(
                f"QPushButton{{background:transparent; color:{P.fg_dim};"
                f" border:none; border-radius:4px; font-size:14px;}}"
                f"QPushButton:hover{{background:{P.bg_hover}; color:{P.gold};}}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# NAV RAIL  —  collapsible left domain navigation panel
# ══════════════════════════════════════════════════════════════════════════════

# Map any screen key → nav-section key (used to highlight the right item)
_NAV_SECTION_MAP: Dict[str, str] = {
    "dashboard":       "dashboard",
    "trade_hub":       "trade",
    "trade":           "trade",  "travel":     "trade",
    "inventory":       "trade",  "wait":       "trade",
    "operations_hub":  "operations",
    "businesses":      "operations", "managers":   "operations",
    "contracts":       "operations", "real_estate": "operations",
    "voyage":          "operations", "skills":     "operations",
    "smuggling":       "operations", "gamble":     "operations",
    "finance_hub":     "finance",
    "finance":         "finance",  "lending":    "finance",
    "stocks":          "finance",  "funds":      "finance",
    "intelligence_hub": "intelligence",
    "market":          "intelligence", "news":      "intelligence",
    "social_hub":      "social",
    "social":          "social",   "influence":  "social",
    "profile_hub":     "profile",
    "licenses":        "profile",  "progress":   "profile",
    "reputation":      "profile",
    "help":            "profile",
    "settings":        "settings",
}


class NavRail(QWidget):
    """
    Collapsible left navigation panel with domain sections.

    Collapsed  (52 px wide): icon-only strip.
    Expanded  (196 px wide): icon + label.

    Clicking a domain navigates to its hub screen.  The currently active
    domain is highlighted with a gold left border.
    """

    COLLAPSED_W = 52
    EXPANDED_W  = 196

    _ITEMS: List[Tuple[str, str, str]] = [
        ("dashboard",    "🏠", "Dashboard"),
        ("trade",        "⚖",  "Trade & Travel"),
        ("operations",   "🏥", "Operations"),
        ("finance",      "🏦", "Finance"),
        ("intelligence", "📊", "Intelligence"),
        ("social",       "🌐", "Social"),
        ("profile",      "📋", "Character"),
    ]
    _BOTTOM: List[Tuple[str, str, str]] = [
        ("settings", "⚙",  "Settings"),
    ]
    _SECTION_SCREEN: Dict[str, str] = {
        "dashboard":    "dashboard",
        "trade":        "trade_hub",
        "operations":   "operations_hub",
        "finance":      "finance_hub",
        "intelligence": "intelligence_hub",
        "social":       "social_hub",
        "profile":      "profile_hub",
        "settings":     "settings",
    }

    def __init__(self, app: "GameApp", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._app      = app
        self._expanded = True
        self._active   = "dashboard"
        self._btns:    Dict[str, QPushButton] = {}

        self.setObjectName("navRail")
        self.setFixedWidth(UIScale.px(self.EXPANDED_W))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            f"#navRail{{background:{P.bg_panel};"
            f" border-right:1px solid {P.border};}}"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Toggle row ───────────────────────────────────────────────────────────
        hdr = QFrame(self)
        hdr.setFixedHeight(UIScale.px(46))
        hdr.setStyleSheet(
            f"background:{P.bg_panel}; border-bottom:1px solid {P.border};"
        )
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(0, 0, 0, 0)
        hdr_lay.setSpacing(0)

        self._toggle_btn = QPushButton("≡", hdr)
        self._toggle_btn.setFixedSize(
            UIScale.px(self.COLLAPSED_W), UIScale.px(46)
        )
        self._toggle_btn.setFont(Fonts.heading)
        self._toggle_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._toggle_btn.clicked.connect(self.toggle)
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {P.fg_dim};
                border: none; font-size: 18px;
            }}
            QPushButton:hover {{
                color: {P.gold}; background: {P.bg_hover};
            }}
        """)
        hdr_lay.addWidget(self._toggle_btn)

        self._rail_title = QLabel("NAVIGATION", hdr)
        self._rail_title.setFont(Fonts.tiny)
        self._rail_title.setStyleSheet(
            f"color:{P.fg_dim}; background:transparent;"
            " letter-spacing:2px; padding-left:4px;"
        )
        self._rail_title.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        hdr_lay.addWidget(self._rail_title, 1)
        lay.addWidget(hdr)

        # ── Main nav items ──────────────────────────────────────────────────────────
        for section, icon, label in self._ITEMS:
            btn = self._make_btn(section, icon, label)
            lay.addWidget(btn)
            self._btns[section] = btn

        lay.addStretch()

        # ── Bottom items ──────────────────────────────────────────────────────────────
        bot_sep = QFrame(self)
        bot_sep.setFrameShape(QFrame.Shape.HLine)
        bot_sep.setFixedHeight(1)
        bot_sep.setStyleSheet(f"background:{P.border}; border:none;")
        lay.addWidget(bot_sep)

        for section, icon, label in self._BOTTOM:
            btn = self._make_btn(section, icon, label)
            lay.addWidget(btn)
            self._btns[section] = btn
        lay.addSpacing(UIScale.px(6))

        self.set_active("dashboard")

    def _make_btn(self, section: str, icon: str, label: str) -> QPushButton:
        btn = QPushButton(f"  {icon}   {label}", self)
        btn.setCheckable(True)
        btn.setFixedHeight(UIScale.px(48))
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        btn.setProperty("role", "navItem")
        btn.clicked.connect(lambda _=False, s=section: self._on_click(s))
        return btn

    def set_active(self, section: str) -> None:
        self._active = section
        for sec, btn in self._btns.items():
            btn.setChecked(sec == section)

    def _on_click(self, section: str) -> None:
        screen_key = self._SECTION_SCREEN.get(section, section)
        if screen_key not in self._app.screens:
            self._app.message_bar.warn(f"Screen '{screen_key}' not available yet.")
            return
        # Collapse stack: hub navigation always resets to [dashboard, hub]
        # (or just ["dashboard"] for dashboard itself)
        if section == "dashboard":
            self._app._stack = ["dashboard"]
        else:
            self._app._stack = ["dashboard", screen_key]
        self._app.show_screen(screen_key)

    def toggle(self) -> None:
        self._expanded = not self._expanded
        w = UIScale.px(
            self.EXPANDED_W if self._expanded else self.COLLAPSED_W
        )
        self.setFixedWidth(w)
        self._rail_title.setVisible(self._expanded)
        for section, icon, label in (self._ITEMS + self._BOTTOM):
            btn = self._btns.get(section)
            if btn is None:
                continue
            if self._expanded:
                btn.setText(f"  {icon}   {label}")
                btn.setToolTip("")
            else:
                btn.setText(f"  {icon}")
                btn.setToolTip(label)


# ══════════════════════════════════════════════════════════════════════════════
# APP FOOTER  —  persistent bottom bar with Back / Save / Help / Quit
# ══════════════════════════════════════════════════════════════════════════════

class AppFooter(QWidget):
    """Bottom action bar: ◄ Back  (stretch)  💾 Save  ❓ Help  ✕ Quit."""

    H = 36

    def __init__(self, app: "GameApp", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._app = app
        self.setObjectName("appFooter")
        self.setFixedHeight(UIScale.px(self.H))
        self._build()

    def _build(self) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(
            UIScale.px(8), UIScale.px(4),
            UIScale.px(8), UIScale.px(4),
        )
        lay.setSpacing(UIScale.px(6))

        def _btn(text: str, tip: str, role: str, slot: Callable) -> QPushButton:
            b = QPushButton(text, self)
            b.setFixedHeight(UIScale.px(self.H - 8))
            b.setFont(Fonts.small)
            b.setToolTip(tip)
            b.setProperty("role", role)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(slot)
            return b

        self._back_btn = _btn("◄  Back", "Go back", "nav", self._app.go_back)
        self._back_btn.setVisible(False)  # hidden on dashboard

        save_btn = _btn("💾  Save",  "Save game",  "nav",   self._app._do_save)
        help_btn = _btn("❓  Help",  "Open help",  "nav",
                        lambda: self._app.show_screen("help")
                        if "help" in self._app.screens else None)
        quit_btn = _btn("✕  Quit",  "Quit game",  "danger", self._app.quit_game)

        lay.addWidget(self._back_btn)
        lay.addStretch()
        lay.addWidget(save_btn)
        lay.addWidget(help_btn)
        lay.addWidget(quit_btn)

    def update_back(self, stack_depth: int) -> None:
        """Show Back button only when there is somewhere to go back to."""
        self._back_btn.setVisible(stack_depth > 1)


# ══════════════════════════════════════════════════════════════════════════════
# WINDOW RESIZER  —  edge-drag resize for frameless windows
# ══════════════════════════════════════════════════════════════════════════════

class WindowResizer(QObject):
    """
    Provides edge-drag resize for a frameless QMainWindow.

    Installed at the QApplication level so it intercepts mouse events from any
    child widget.  Supports all 8 directions (N/S/E/W + 4 corners).

    On Windows, GameApp.nativeEvent() also intercepts WM_NCHITTEST using the
    same edge detection, giving full Aero-Snap / magnetic-edge support.
    """

    GRIP: int = 8   # pixel width of the detectable resize zone along each edge

    # Windows WM_NCHITTEST return codes for each direction
    _HIT_CODE: Dict[str, int] = {
        "N": 12, "S": 15, "E": 11, "W": 10,
        "NW": 13, "NE": 14, "SW": 16, "SE": 17,
    }

    _CURSORS: Dict[str, Qt.CursorShape] = {
        "N":  Qt.CursorShape.SizeVerCursor,
        "S":  Qt.CursorShape.SizeVerCursor,
        "E":  Qt.CursorShape.SizeHorCursor,
        "W":  Qt.CursorShape.SizeHorCursor,
        "NE": Qt.CursorShape.SizeBDiagCursor,
        "SW": Qt.CursorShape.SizeBDiagCursor,
        "NW": Qt.CursorShape.SizeFDiagCursor,
        "SE": Qt.CursorShape.SizeFDiagCursor,
    }

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self._win:        QMainWindow      = window
        self._dir:        str              = ""
        self._press_gpos: Optional[QPoint] = None
        self._press_geo:  Optional[QRect]  = None
        QApplication.instance().installEventFilter(self)

    def uninstall(self) -> None:
        QApplication.instance().removeEventFilter(self)

    # ── Edge detection ────────────────────────────────────────────────────────

    def edge_for(self, local: QPoint) -> str:
        """Return resize-direction string for a window-local position, or ''."""
        g  = self.GRIP
        x, y = local.x(), local.y()
        w, h = self._win.width(), self._win.height()
        top    = y <= g
        bottom = y >= h - g
        left   = x <= g
        right  = x >= w - g
        if top    and left:  return "NW"
        if top    and right: return "NE"
        if bottom and left:  return "SW"
        if bottom and right: return "SE"
        if top:              return "N"
        if bottom:           return "S"
        if left:             return "W"
        if right:            return "E"
        return ""

    # ── Event filter ──────────────────────────────────────────────────────────

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        t = event.type()

        if t == QEvent.Type.MouseMove:
            gp = event.globalPosition().toPoint()
            lp = self._win.mapFromGlobal(gp)
            if self._dir:
                self._apply_resize(gp)
                return True
            # Hover cursor update (only when not maximised/fullscreen)
            if not self._win.isMaximized() and not self._win.isFullScreen():
                if self._win.rect().contains(lp):
                    d = self.edge_for(lp)
                    if d:
                        self._win.setCursor(self._CURSORS[d])
                    else:
                        # Only reset if we previously set a resize cursor
                        shape = self._win.cursor().shape()
                        if shape in self._CURSORS.values():
                            self._win.unsetCursor()
            return False

        elif t == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                gp = event.globalPosition().toPoint()
                lp = self._win.mapFromGlobal(gp)
                if (not self._win.isMaximized() and
                        self._win.rect().contains(lp)):
                    d = self.edge_for(lp)
                    if d:
                        self._dir        = d
                        self._press_gpos = gp
                        self._press_geo  = self._win.geometry()
                        return True
            return False

        elif t == QEvent.Type.MouseButtonRelease:
            if self._dir and event.button() == Qt.MouseButton.LeftButton:
                self._dir        = ""
                self._press_gpos = None
                self._press_geo  = None
                return True
            return False

        return False

    def _apply_resize(self, gp: QPoint) -> None:
        """Compute and apply new window geometry during a resize drag."""
        if not self._press_gpos or not self._press_geo:
            return
        dx = gp.x() - self._press_gpos.x()
        dy = gp.y() - self._press_gpos.y()
        g  = self._press_geo
        d  = self._dir
        mw = self._win.minimumWidth()
        mh = self._win.minimumHeight()
        x, y, w, h = g.x(), g.y(), g.width(), g.height()
        if "E" in d:
            w = max(mw, g.width()  + dx)
        if "S" in d:
            h = max(mh, g.height() + dy)
        if "W" in d:
            nw = max(mw, g.width()  - dx)
            x  = g.right() - nw + 1
            w  = nw
        if "N" in d:
            nh = max(mh, g.height() - dy)
            y  = g.bottom() - nh + 1
            h  = nh
        self._win.setGeometry(x, y, w, h)


# ══════════════════════════════════════════════════════════════════════════════
# GAME APP  —  root window and navigation controller
# ══════════════════════════════════════════════════════════════════════════════

class GameApp(QMainWindow):
    """
    Root window and screen orchestrator.

    Screen registry:   self.screens  { name → Screen instance }
    Navigation stack:  self._stack   [ name, … ]  (active = last)

    Public API:
        show(name)    — navigate to a named screen
        go_back()     — pop stack; return to previous screen
        goto(name)    — flat jump (collapses nav stack, always Back=main)
        refresh()     — update status bar + re-render current screen
        quit_game()   — prompt save then close
    """

    TITLE  = "Merchant Tycoon — Expanded Edition"
    WIN_W  = 1280
    WIN_H  = 820
    MIN_W  = 960
    MIN_H  = 640

    # Screen registry will be populated in Phase 5+
    # Format: logical_name → Screen subclass
    _SCREEN_MAP: Dict[str, Type[Screen]] = {
        # Screens are registered here as each phase is implemented.
        # Stub entries will be added progressively.
    }

    def __init__(self) -> None:
        super().__init__()

        # ── Hide console window on Windows ───────────────────────────────
        if sys.platform == "win32":
            import ctypes
            hwnd_console = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd_console:
                ctypes.windll.user32.ShowWindow(hwnd_console, 0)

        # ── DPI awareness ────────────────────────────────────────────────
        if sys.platform == "win32":
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor v2
            except Exception:
                pass

        # ── Frameless window ─────────────────────────────────────────────
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setWindowTitle(self.TITLE)
        self.setMinimumSize(self.MIN_W, self.MIN_H)

        # ── Geometry: centre on primary screen ───────────────────────────
        screen_geo = QGuiApplication.primaryScreen().availableGeometry()
        cx = max(0, (screen_geo.width()  - self.WIN_W) // 2)
        cy = max(0, (screen_geo.height() - self.WIN_H) // 2)
        self.setGeometry(cx, cy, self.WIN_W, self.WIN_H)

        # ── Game model ───────────────────────────────────────────────────
        self.game   = Game()
        self._session_start: float = time.time()
        self._last_synced_day: int = 0

        # ── Online services ──────────────────────────────────────────────
        try:
            from merchant_tycoon_online import OnlineServices as _OnlineSvc
            self.online = _OnlineSvc()
        except Exception:
            self.online = None

        # ── Thread pool ──────────────────────────────────────────────────
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max(4, self._pool.maxThreadCount()))

        # ── Build UI ─────────────────────────────────────────────────────
        self._build_ui()

        # ── Hotkeys ──────────────────────────────────────────────────────
        self.hotkeys = HotkeyManager(self)
        self.hotkeys.triggered.connect(self._on_hotkey)
        self.hotkeys.reload(self.game.settings.hotkeys
                            if hasattr(self.game, "settings") and
                               hasattr(self.game.settings, "hotkeys")
                            else DEFAULT_HOTKEYS)

        # ── Global shortcuts not managed by HotkeyManager ────────────────
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(
            self._on_escape)
        QShortcut(QKeySequence("F5"), self).activated.connect(self.refresh)

        # ── Apply saved settings ─────────────────────────────────────────
        if hasattr(self.game, "settings"):
            s = self.game.settings
            if hasattr(s, "ui_scale") and s.ui_scale != 1.0:
                UIScale.set(s.ui_scale)

        # ── Connect UIScale → live QSS rebuild + UI refresh ───────────────
        UIScale.connect(self._on_scale_changed)

        # ── Window resizer — edge-drag resize for frameless window ────────
        self._resizer = WindowResizer(self)

        # ── Ctrl+Wheel → UI scale (application-level event filter) ────────
        QApplication.instance().installEventFilter(self)

        # ── Window close handler ─────────────────────────────────────────
        # (closeEvent is overridden below)

        # ── Navigate to dashboard ─────────────────────────────────────────
        # Deferred to after the event loop starts so sizing is finalised.
        QTimer.singleShot(0, lambda: self.show_screen("dashboard")
                          if "dashboard" in self.screens else None)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Construct the full window layout."""
        central = QWidget(self)
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 1. Custom title bar (window chrome) ───────────────────────────
        self.title_bar = CustomTitleBar(self)
        root.addWidget(self.title_bar)

        # ── 2. Game header (persistent info bar) ──────────────────────────
        self.game_header = GameHeader(self.game, central)
        # status_bar alias kept for any legacy calls
        self.status_bar = self.game_header
        root.addWidget(self.game_header)

        # Thin gold separator
        sep = QFrame(central)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{P.border_light}; border:none;")
        root.addWidget(sep)

        # ── 3. Main area: nav rail (left) + content stack (right) ─────────
        main_area = QHBoxLayout()
        main_area.setContentsMargins(0, 0, 0, 0)
        main_area.setSpacing(0)

        self.nav_rail = NavRail(self, central)
        main_area.addWidget(self.nav_rail)

        self.content_stack = QStackedWidget(central)
        self.content_stack.setObjectName("contentStack")
        main_area.addWidget(self.content_stack, 1)

        root.addLayout(main_area, 1)

        # ── Transition manager ────────────────────────────────────────────
        self._transition = ScreenTransitionManager(self.content_stack)

        # ── 4. App footer ─────────────────────────────────────────────────
        self.app_footer = AppFooter(self, central)
        root.addWidget(self.app_footer)

        # ── 5. Message bar ────────────────────────────────────────────────
        self.message_bar = MessageBar(central)
        root.addWidget(self.message_bar)
        self.message_bar._toast_fn = lambda text, col: GameToast(self, text, col)

        # ── Register screens ──────────────────────────────────────────────
        self.screens: Dict[str, Screen] = {}
        self._stack:  List[str]         = []
        self._register_screens()

    def _register_screens(self) -> None:
        """Instantiate every screen and add to the QStackedWidget."""
        for name, cls in self._SCREEN_MAP.items():
            screen = cls(self)
            self.screens[name] = screen
            self.content_stack.addWidget(screen)

    def register_screen(self, name: str, screen: Screen) -> None:
        """
        Dynamically register a single Screen instance.
        Call this from screen module init code so screens self-register.
        """
        self.screens[name] = screen
        self.content_stack.addWidget(screen)

    # ── Navigation ────────────────────────────────────────────────────────────

    def show_screen(self, name: str) -> None:
        """Navigate to the named screen, pushing it onto the stack."""
        if name not in self.screens:
            self.message_bar.err(f"Unknown screen: '{name}'")
            return

        if self._stack and self._stack[-1] != name:
            # Notify outgoing screen
            try:
                self.screens[self._stack[-1]].deactivate()
            except Exception:
                pass

        if not self._stack or self._stack[-1] != name:
            self._stack.append(name)

        target = self.screens[name]
        target_idx = self.content_stack.indexOf(target)

        # Sync nav rail active state
        section = _NAV_SECTION_MAP.get(name, "")
        if section and hasattr(self, "nav_rail"):
            self.nav_rail.set_active(section)

        # Sync footer back-button visibility
        if hasattr(self, "app_footer"):
            self.app_footer.update_back(len(self._stack))

        def _on_switched() -> None:
            target.activate()
            if hasattr(self, "game_header"):
                self.game_header.refresh()

        self._transition.switch_to(target_idx, on_switched=_on_switched)

    # Keep "show" as an alias for compatibility but prefer show_screen
    def show(self, *args, **kwargs):
        # If called with a string (screen name), route to show_screen
        if args and isinstance(args[0], str):
            return self.show_screen(args[0])
        # Otherwise delegate to QMainWindow.show() (no-arg call to make window visible)
        return super().show()

    def goto(self, name: str) -> None:
        """
        Flat / hotkey navigation: jump to a screen, collapsing the stack.
        Back always returns to the dashboard.
        """
        if name not in self.screens:
            self.message_bar.err(f"Unknown screen: '{name}'")
            return
        if self._stack:
            try:
                self.screens[self._stack[-1]].deactivate()
            except Exception:
                pass
        if name == "dashboard":
            self._stack = ["dashboard"]
        else:
            self._stack = ["dashboard", name]
        self.show_screen(name)

    def go_back(self) -> None:
        """Return to the previous screen."""
        if len(self._stack) <= 1:
            return
        leaving = self._stack.pop()
        try:
            self.screens[leaving].deactivate()
        except Exception:
            pass
        if hasattr(self, "app_footer"):
            self.app_footer.update_back(len(self._stack))
        self.show_screen(self._stack[-1])

    def refresh(self) -> None:
        """Refresh game header and re-render currently visible screen."""
        if hasattr(self, "game_header"):
            self.game_header.refresh()
        if self._stack and self._stack[-1] in self.screens:
            self.screens[self._stack[-1]].refresh()

    # ── Hotkey handler ────────────────────────────────────────────────────────

    @Slot(str)
    def _on_hotkey(self, action: str) -> None:
        routes = {
            "trade":      "trade",
            "travel":     "travel",
            "inventory":  "inventory",
            "wait":       "wait",
            "businesses": "businesses",
            "finance":    "finance",
            "contracts":  "contracts",
            "market":     "market",
            "news":       "news",
            "progress":   "progress",
            "skills":     "skills",
            "help":       "help",
            "settings":   "settings",
            "voyage":     "voyage",
        }
        if action == "save":
            self._do_save()
            return
        dest = routes.get(action)
        if dest and dest in self.screens:
            self.goto(dest)

    def _on_escape(self) -> None:
        self.go_back()

    # ── Application-level event filter ───────────────────────────────────────

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """
        Intercepts Ctrl+MouseWheel globally to scale the UI up / down.
        Step: ±0.1 per wheel notch.  Clamped to 0.7 – 2.5 by UIScale.set().
        """
        if event.type() == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                if delta != 0:
                    step  = 0.1 if delta > 0 else -0.1
                    UIScale.set(round(UIScale.factor() + step, 1))
                return True   # always consume Ctrl+Wheel
        return super().eventFilter(obj, event)

    def _do_save(self) -> None:
        try:
            self.game.save_game()
            self.message_bar.ok("Game saved.")
        except Exception as exc:
            self.message_bar.err(f"Save failed: {exc}")

    # ── Window close ─────────────────────────────────────────────────────────

    def quit_game(self) -> None:
        """Prompt save confirmation then close."""
        # For now, just close — Phase 5 (MainMenuScreen) will add the confirm dialog
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        # Accumulate session time
        if hasattr(self.game, "settings"):
            session_secs = int(time.time() - self._session_start)
            if hasattr(self.game.settings, "time_played"):
                self.game.settings.time_played = (
                    getattr(self.game.settings, "time_played", 0) + session_secs)
        event.accept()

    # ── UIScale change ────────────────────────────────────────────────────────

    def _on_scale_changed(self, scale: float) -> None:
        """Re-apply QSS and rebuild dynamic-height widgets when UI scale changes."""
        QApplication.instance().setStyleSheet(_build_qss(scale))
        self.title_bar.setFixedHeight(UIScale.px(38))
        if hasattr(self, "game_header"):
            self.game_header.setFixedHeight(UIScale.px(GameHeader.H))
        if hasattr(self, "app_footer"):
            self.app_footer.setFixedHeight(UIScale.px(AppFooter.H))
        self.title_bar.show_scale(int(scale * 100))
        if hasattr(self.game, "settings") and hasattr(self.game.settings, "ui_scale"):
            self.game.settings.ui_scale = scale
        self.update()

    # ── Windows native resize (WM_NCHITTEST → Aero Snap) ─────────────────────

    def nativeEvent(self, event_type: QByteArray, message: object) -> tuple:
        """
        On Windows: delegate edge-zone hit-testing to the OS via WM_NCHITTEST
        so the window benefits from Aero Snap, magnetic screen edges, and the
        native resize shadow — without losing our custom frameless look.
        On other platforms: pass through to Qt default handling.
        """
        if sys.platform == "win32" and event_type == b"windows_generic_MSG":
            try:
                import ctypes
                import ctypes.wintypes as wt
                WM_NCHITTEST = 0x0084
                msg = ctypes.cast(int(message),
                                  ctypes.POINTER(wt.MSG)).contents
                if msg.message == WM_NCHITTEST and not self.isMaximized():
                    # Decode LPARAM as two signed 16-bit screen coords
                    sx = ctypes.c_int16(msg.lParam & 0xFFFF).value
                    sy = ctypes.c_int16((msg.lParam >> 16) & 0xFFFF).value
                    local = self.mapFromGlobal(QPoint(sx, sy))
                    d = self._resizer.edge_for(local)
                    if d:
                        return True, WindowResizer._HIT_CODE[d]
            except Exception:
                pass
        return super().nativeEvent(event_type, message)


# ══════════════════════════════════════════════════════════════════════════════
# STUB SCREENS  —  minimal placeholders; will be fully implemented per phase
# ══════════════════════════════════════════════════════════════════════════════

class _StubScreen(Screen):
    """
    Generic placeholder for screens not yet ported to PySide6.
    Displays the screen name so navigation is immediately testable.
    """

    _LABEL: str = "Stub Screen"

    def build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = QLabel(f"[ {self._LABEL} ]", self)
        lbl.setFont(Fonts.title)
        lbl.setStyleSheet(f"color: {P.gold}; background: transparent;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl)

        sub = QLabel("This screen is being ported to PySide6.", self)
        sub.setFont(Fonts.body)
        sub.setStyleSheet(f"color: {P.fg_dim}; background: transparent;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)

        btn = self.back_button()
        btn.setFixedWidth(UIScale.px(160))
        lay.addSpacing(UIScale.px(20))
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)


def _make_stub(label: str) -> Type[_StubScreen]:
    """Factory: create a named stub screen class."""
    return type(f"{label.replace(' ', '')}Screen", (_StubScreen,), {"_LABEL": label})


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD SCREEN  —  home screen with key stats + quick actions
# ══════════════════════════════════════════════════════════════════════════════


class DashboardScreen(Screen):
    """
    Home dashboard shown on startup.  Three-column layout:
      Left  (30%): Player Pulse — day, season, year, slots, gold, rep, location
                   + three quick-action buttons
      Right (70%): top half = Active Contracts table
                   bottom half = Recent News / Events feed
    """

    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(12), UIScale.px(10),
                                UIScale.px(12), UIScale.px(10))
        root.setSpacing(UIScale.px(10))

        # \u2500\u2500 Title row
        title_row = QHBoxLayout()
        t = QLabel("\ud83c\udfe0  Dashboard", self)
        t.setFont(Fonts.title)
        t.setStyleSheet(f"color:{P.gold}; background:transparent;")
        title_row.addWidget(t)
        title_row.addStretch()
        sub = QLabel("Overview of your empire", self)
        sub.setFont(Fonts.small)
        sub.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        title_row.addWidget(sub)
        root.addLayout(title_row)

        # \u2500\u2500 Main two-column area
        cols = QHBoxLayout()
        cols.setSpacing(UIScale.px(10))

        # Left: player pulse panel
        left = self._build_pulse_panel()
        left.setFixedWidth(UIScale.px(240))
        cols.addWidget(left)

        # Right: contracts + news stacked vertically
        right = QVBoxLayout()
        right.setSpacing(UIScale.px(10))
        right.addWidget(self._build_contracts_panel(), 1)
        right.addWidget(self._build_news_panel(), 1)
        cols.addLayout(right, 1)

        root.addLayout(cols, 1)

    def _panel(self, title: str) -> Tuple["QFrame", "QVBoxLayout"]:
        """Helper: create a titled panel frame; return (frame, inner_layout)."""
        frame = QFrame(self)
        frame.setObjectName("dashPanel")
        frame.setStyleSheet(
            f"#dashPanel{{background:{P.bg_panel}; border:1px solid {P.border};"
            f" border-radius:5px;}}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(UIScale.px(10), UIScale.px(8),
                               UIScale.px(10), UIScale.px(8))
        lay.setSpacing(UIScale.px(6))
        hdr = QLabel(title, frame)
        hdr.setFont(Fonts.small_bold)
        hdr.setStyleSheet(
            f"color:{P.amber}; background:transparent; border:none;"
        )
        lay.addWidget(hdr)
        sep = QFrame(frame)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{P.border}; border:none;")
        lay.addWidget(sep)
        return frame, lay

    def _stat_row(self, parent: QWidget, label: str,
                  value: str, val_col: str) -> QLabel:
        """Add a label+value row to parent layout; return the value QLabel."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(label, parent)
        lab.setFont(Fonts.small)
        lab.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        row.addWidget(lab)
        row.addStretch()
        val = QLabel(value, parent)
        val.setFont(Fonts.small_bold)
        val.setStyleSheet(f"color:{val_col}; background:transparent;")
        row.addWidget(val)
        parent.layout().addLayout(row)
        return val

    def _build_pulse_panel(self) -> QFrame:
        frame, lay = self._panel("\u26a1  Player Pulse")

        # Stat rows (refs stored for refresh())
        self._d_day_val  = self._stat_row(frame, "Day",      "\u2014", P.gold)
        self._d_sea_val  = self._stat_row(frame, "Season",   "\u2014", P.amber)
        self._d_yr_val   = self._stat_row(frame, "Year",     "\u2014", P.fg)
        self._d_slot_val = self._stat_row(frame, "Actions",  "\u2014", P.green)

        sep2 = QFrame(frame)
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background:{P.border}; border:none;")
        lay.addWidget(sep2)

        self._d_gold_val = self._stat_row(frame, "\ud83d\udcb0 Gold",    "\u2014", P.gold)
        self._d_rep_val  = self._stat_row(frame, "\u2b50 Rep",     "\u2014", P.amber)
        self._d_nw_val   = self._stat_row(frame, "\ud83d\udc8e Networth", "\u2014", P.cream)
        self._d_loc_val  = self._stat_row(frame, "\ud83d\udccd Location", "\u2014", P.fg_dim)

        sep3 = QFrame(frame)
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setFixedHeight(1)
        sep3.setStyleSheet(f"background:{P.border}; border:none;")
        lay.addWidget(sep3)

        # Quick actions
        def _qbtn(label: str, screen: str) -> None:
            b = MtButton(label, parent=frame)
            b.setFixedHeight(UIScale.px(30))
            b.clicked.connect(lambda: self.app.show_screen(screen)
                              if screen in self.app.screens else None)
            lay.addWidget(b)

        _qbtn("\u2696  Trade",   "trade")
        _qbtn("\ud83d\udec3  Travel", "travel")
        _qbtn("\u23f3  Rest",    "wait")

        lay.addStretch()
        return frame

    def _build_contracts_panel(self) -> QFrame:
        frame, lay = self._panel("\ud83d\udcdc  Active Contracts")
        self._d_contracts_lbl = QLabel("No active contracts.", frame)
        self._d_contracts_lbl.setFont(Fonts.small)
        self._d_contracts_lbl.setStyleSheet(
            f"color:{P.fg_dim}; background:transparent;"
        )
        self._d_contracts_lbl.setWordWrap(True)
        lay.addWidget(self._d_contracts_lbl)
        lay.addStretch()
        return frame

    def _build_news_panel(self) -> QFrame:
        frame, lay = self._panel("\ud83d\udcf0  Recent Events")
        self._d_news_lbl = QLabel("No recent news.", frame)
        self._d_news_lbl.setFont(Fonts.small)
        self._d_news_lbl.setStyleSheet(
            f"color:{P.fg_dim}; background:transparent;"
        )
        self._d_news_lbl.setWordWrap(True)
        lay.addWidget(self._d_news_lbl)
        lay.addStretch()
        return frame

    def refresh(self) -> None:
        if not self._built:
            return
        g   = self.game
        inv = getattr(g, "inventory", None)

        # Day / season / year
        day    = getattr(g, "day",    1)
        year   = getattr(g, "year",   1)
        season = getattr(g, "season", None)
        sea_s  = season.value if season and hasattr(season, "value") else "?"
        sea_c  = SEASON_COLOURS.get(season, P.gold)
        self._d_day_val.setText(str(day))
        self._d_sea_val.setText(sea_s)
        self._d_sea_val.setStyleSheet(f"color:{sea_c}; background:transparent;")
        self._d_yr_val.setText(str(year))

        # Slots
        used = getattr(g, "slots_used",    0)
        mxs  = getattr(g, "action_slots",  5)
        free = max(0, mxs - used)
        slot_col = P.red if free == 0 else P.amber if free <= 1 else P.green
        self._d_slot_val.setText(f"{free} / {mxs}")
        self._d_slot_val.setStyleSheet(
            f"color:{slot_col}; background:transparent;"
        )

        # Economy
        gold = getattr(inv, "gold", 0) if inv else 0
        self._d_gold_val.setText(f"{gold:,.0f} g")

        rep    = getattr(g, "reputation", 0)
        rl, rc = rep_label(rep)
        self._d_rep_val.setText(f"{rl}  ({rep})")
        self._d_rep_val.setStyleSheet(f"color:{rc}; background:transparent;")

        nw = getattr(g, "net_worth", gold)
        if callable(nw):
            nw = nw()
        self._d_nw_val.setText(f"{nw:,.0f} g")

        loc   = getattr(g, "area", None)
        loc_s = loc.value if loc and hasattr(loc, "value") else str(loc or "?")
        self._d_loc_val.setText(loc_s)

        # Contracts
        abs_day  = getattr(g, "_absolute_day", lambda: 0)
        abs_day  = abs_day() if callable(abs_day) else 0
        active_c = [c for c in getattr(g, "contracts", [])
                    if not getattr(c, "fulfilled", True)]
        if active_c:
            lines = []
            for c in active_c[:5]:
                dl  = getattr(c, "deadline_day", abs_day + 999) - abs_day
                nm  = ALL_ITEMS.get(
                    getattr(c, "item_key", ""), type("_",(),{"name":"?"})()
                ).name
                dest = getattr(c, "destination", None)
                dest_s = dest.value if dest and hasattr(dest,"value") else "?"
                mark = "\ud83d\udd34" if dl <= 3 else "\ud83d\udfe1" if dl <= 7 else "\ud83d\udfe2"
                lines.append(
                    f"{mark}  {getattr(c,'quantity',0)}\u00d7 {nm}"
                    f" \u2192 {dest_s}  [{dl}d]"
                )
            self._d_contracts_lbl.setText("\n".join(lines))
        else:
            self._d_contracts_lbl.setText("No active contracts.")

        # News
        news = getattr(g, "news_feed", [])
        if news:
            lines = []
            for entry in news[:5]:
                hl = entry[-1] if isinstance(entry, (list, tuple)) else str(entry)
                lines.append(f"\u2022  {str(hl)[:80]}")
            self._d_news_lbl.setText("\n".join(lines))
        else:
            self._d_news_lbl.setText("No recent news.")


# ══════════════════════════════════════════════════════════════════════════════
# HUB CARD  +  DOMAIN HUB SCREENS
# ══════════════════════════════════════════════════════════════════════════════


class _HubCard(QFrame):
    """
    Compact (58 px) navigation card used in domain hub screens.
    Uniform gold-accent styling \u2014 no per-section colour variation.
    """

    clicked = Signal()

    def __init__(
        self,
        icon: str,
        title: str,
        subtitle: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("hubCard")
        self.setFixedHeight(UIScale.px(62))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, UIScale.px(10), 0)
        lay.setSpacing(0)

        # Gold left accent bar
        bar = QFrame(self)
        bar.setFixedWidth(UIScale.px(3))
        bar.setStyleSheet(
            f"background:{P.gold}; border:none; border-radius:2px;"
        )
        lay.addWidget(bar)
        lay.addSpacing(UIScale.px(10))

        # Icon
        icon_lbl = QLabel(icon, self)
        icon_lbl.setFont(Fonts.heading)
        icon_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        icon_lbl.setFixedWidth(UIScale.px(32))
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(icon_lbl)
        lay.addSpacing(UIScale.px(8))

        # Text block
        txt = QVBoxLayout()
        txt.setSpacing(2)
        t_lbl = QLabel(title, self)
        t_lbl.setFont(Fonts.body_bold)
        t_lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        t_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        s_lbl = QLabel(subtitle, self)
        s_lbl.setFont(Fonts.tiny)
        s_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        s_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        txt.addWidget(t_lbl)
        txt.addWidget(s_lbl)
        lay.addLayout(txt, 1)

        # Badge / arrow
        self._badge_lbl = QLabel("\u203a", self)
        self._badge_lbl.setFont(Fonts.heading)
        self._badge_lbl.setStyleSheet(f"color:{P.border_light}; background:transparent;")
        lay.addWidget(self._badge_lbl)

    def set_badge(self, n: int, col: str = P.amber) -> None:
        if n > 0:
            self._badge_lbl.setText(str(n))
            self._badge_lbl.setStyleSheet(
                f"color:{col}; background:transparent; font-weight:bold;"
            )
        else:
            self.clear_badge()

    def clear_badge(self) -> None:
        self._badge_lbl.setText("\u203a")
        self._badge_lbl.setStyleSheet(
            f"color:{P.border_light}; background:transparent;"
        )

    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class _DomainHubScreen(Screen):
    """
    Base class for domain hub screens.
    Subclasses define the domain metadata and card list.
    """

    _DOMAIN_ICON:  str = "\ud83d\udccc"
    _DOMAIN_TITLE: str = "Domain"
    _DOMAIN_DESC:  str = "Select a section."
    _CARDS: List[Tuple[str, str, str, str]] = []
    # Each entry: (screen_key, icon, title, subtitle)

    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12),
                                UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(12))

        # Domain header
        hdr_row = QHBoxLayout()
        icon_lbl = QLabel(self._DOMAIN_ICON, self)
        icon_lbl.setFont(Fonts.title)
        icon_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        hdr_row.addWidget(icon_lbl)
        hdr_row.addSpacing(UIScale.px(8))
        ttl = QVBoxLayout()
        name_lbl = QLabel(self._DOMAIN_TITLE, self)
        name_lbl.setFont(Fonts.title)
        name_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        desc_lbl = QLabel(self._DOMAIN_DESC, self)
        desc_lbl.setFont(Fonts.small)
        desc_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        ttl.addWidget(name_lbl)
        ttl.addWidget(desc_lbl)
        hdr_row.addLayout(ttl)
        hdr_row.addStretch()
        root.addLayout(hdr_row)

        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{P.border_light}; border:none;")
        root.addWidget(sep)

        # Optional domain summary (can be overridden)
        summary = self._build_summary()
        if summary:
            root.addWidget(summary)

        # Card grid (2-column)
        grid_widget = QWidget(self)
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(UIScale.px(10))
        grid.setVerticalSpacing(UIScale.px(8))

        for i, (key, icon, title, subtitle) in enumerate(self._CARDS):
            card = _HubCard(icon, title, subtitle, grid_widget)
            card.clicked.connect(
                lambda _=False, k=key: self.app.goto(k)
                if k in self.app.screens else
                self.app.message_bar.warn(f"'{title}' not yet implemented.")
            )
            grid.addWidget(card, i // 2, i % 2)

        root.addWidget(grid_widget)
        root.addStretch()

    def _build_summary(self) -> Optional[QWidget]:
        """Override to return a summary widget shown above the card grid."""
        return None


class TradeHubScreen(_DomainHubScreen):
    _DOMAIN_ICON  = "\u2696"
    _DOMAIN_TITLE = "Trade & Travel"
    _DOMAIN_DESC  = "Buy, sell, and move goods across the realm."
    _CARDS = [
        ("trade",     "\ud83d\uded2", "Trade",        "Buy and sell goods at the market"),
        ("travel",    "\ud83d\udec3", "Travel",        "Move to a different location"),
        ("inventory", "\ud83c\udf92", "Inventory",     "Manage your carried goods & weight"),
        ("wait",      "\u23f3",  "Rest & Wait",   "Pass time and recover action slots"),
    ]


class OperationsHubScreen(_DomainHubScreen):
    _DOMAIN_ICON  = "\ud83c\udfe5"
    _DOMAIN_TITLE = "Operations"
    _DOMAIN_DESC  = "Manage businesses, contracts and logistical assets."
    _CARDS = [
        ("businesses",  "\ud83c\udfe2", "Businesses",   "Own and operate commercial enterprises"),
        ("managers",    "\ud83d\udc64", "Managers",     "Hire and assign workforce managers"),
        ("contracts",   "\ud83d\udcdc", "Contracts",    "Fulfil delivery and supply contracts"),
        ("real_estate", "\ud83c\udfe0", "Real Estate",  "Buy and manage property holdings"),
        ("voyage",      "\u26f5",  "Voyage",       "Send ships on trading voyages"),
        ("skills",      "\ud83d\udcda", "Skills",       "Spend experience points and train"),
        ("smuggling",   "\ud83d\udd75", "Smuggling",    "Illicit trade \u2014 high risk, high reward"),
        ("gamble",      "\ud83c\udfb2", "Gambling",     "Try your luck at the gaming tables"),
    ]


class FinanceHubScreen(_DomainHubScreen):
    _DOMAIN_ICON  = "\ud83c\udfe6"
    _DOMAIN_TITLE = "Finance"
    _DOMAIN_DESC  = "Banking, investments, lending and market instruments."
    _CARDS = [
        ("finance",  "\ud83d\udcb3", "Banking",       "Deposits, withdrawals and interest"),
        ("lending",  "\ud83e\udd1d", "Lending",       "Issue or take citizen loans"),
        ("stocks",   "\ud83d\udcc8", "Stock Market",  "Trade company shares and equities"),
        ("funds",    "\ud83d\udcb9", "Fund Mgmt",     "Manage investment portfolios"),
    ]


class IntelligenceHubScreen(_DomainHubScreen):
    _DOMAIN_ICON  = "\ud83d\udcca"
    _DOMAIN_TITLE = "Intelligence"
    _DOMAIN_DESC  = "Market data, price trends and world news."
    _CARDS = [
        ("market", "\ud83d\udcb1", "Market Info",   "Price lists, trends and forecasts"),
        ("news",   "\ud83d\udcf0", "News & Events", "World headlines and trade disruptions"),
    ]


class SocialHubScreen(_DomainHubScreen):
    _DOMAIN_ICON  = "\ud83c\udf10"
    _DOMAIN_TITLE = "Social"
    _DOMAIN_DESC  = "Build alliances, manage reputation and exert influence."
    _CARDS = [
        ("social",    "\ud83e\udd1d", "Social Hub",   "Diplomacy, relationships and favours"),
        ("influence", "\u2b50",  "Influence",     "Spend and earn reputation points"),
    ]


class ProfileHubScreen(_DomainHubScreen):
    _DOMAIN_ICON  = "\ud83d\udccb"
    _DOMAIN_TITLE = "Character"
    _DOMAIN_DESC  = "Your skills, progress, licenses and personal profile."
    _CARDS = [
        ("skills",    "\ud83d\udcda", "Skills",        "Skill tree and ability upgrades"),
        ("licenses",  "\ud83d\udcc4", "Licenses",      "Trade and travel permits"),
        ("progress",  "\ud83c\udfc6", "Achievements",  "Milestones and long-term goals"),
        ("settings",  "\u2699",  "Settings",      "Game options and preferences"),
    ]


# ══════════════════════════════════════════════════════════════════════════════
# (legacy nav-card classes kept for compatibility — no longer rendered)
# ══════════════════════════════════════════════════════════════════════════════

class _PrimaryNavCard(QFrame):
    """
    Large navigation card for the four core action slots at the top of the
    main menu.  Shows: big icon / title / subtitle / optional hotkey pill /
    optional context line / optional alert badge.

    All child labels have WA_TransparentForMouseEvents so every mouse event
    reaches the frame directly.
    """

    clicked = Signal()

    _STYLE_BASE  = "background:{bg}; border:1px solid {border}; border-radius:6px;"
    _STYLE_HOVER = "background:{bg}; border:1px solid {border}; border-radius:6px;"

    def __init__(
        self,
        icon:     str,
        title:    str,
        subtitle: str,
        accent:   str,
        hotkey:   str = "",
        parent:   Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._accent = accent
        self.setObjectName("primaryCard")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumHeight(UIScale.px(104))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            UIScale.px(14), UIScale.px(10),
            UIScale.px(14), UIScale.px(8),
        )
        root.setSpacing(UIScale.px(3))

        # ── Top row: icon + hotkey pill ───────────────────────────────────────
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(0)

        self._icon_lbl = QLabel(icon, self)
        self._icon_lbl.setFont(Fonts.icon)
        self._icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        top.addWidget(self._icon_lbl)
        top.addStretch()

        if hotkey:
            self._hk_lbl = QLabel(f" {hotkey.upper()} ", self)
            self._hk_lbl.setFont(Fonts.tiny)
            self._hk_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            top.addWidget(self._hk_lbl)
        else:
            self._hk_lbl = None

        root.addLayout(top)

        # ── Title ─────────────────────────────────────────────────────────────
        self._title_lbl = QLabel(title, self)
        self._title_lbl.setFont(Fonts.heading)
        self._title_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        root.addWidget(self._title_lbl)

        # ── Subtitle ──────────────────────────────────────────────────────────
        self._sub_lbl = QLabel(subtitle, self)
        self._sub_lbl.setFont(Fonts.small)
        self._sub_lbl.setWordWrap(True)
        self._sub_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        root.addWidget(self._sub_lbl)

        # ── Context line (live game info; hidden until set) ───────────────────
        self._ctx_lbl = QLabel("", self)
        self._ctx_lbl.setFont(Fonts.tiny)
        self._ctx_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._ctx_lbl.hide()
        root.addWidget(self._ctx_lbl)

        root.addStretch()

        # ── Bottom accent line ────────────────────────────────────────────────
        self._accent_line = QFrame(self)
        self._accent_line.setFrameShape(QFrame.Shape.HLine)
        self._accent_line.setFixedHeight(2)
        self._accent_line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        root.addWidget(self._accent_line)

        # ── Alert badge (floated top-right, shown when count > 0) ────────────
        self._badge = QLabel("", self)
        self._badge.setFixedSize(UIScale.px(22), UIScale.px(22))
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFont(Fonts.tiny)
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._badge.hide()

        self._refresh_style(False)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_badge(self, count: int, color: str = "") -> None:
        if count <= 0:
            self._badge.hide()
            return
        col = color or P.red
        self._badge.setStyleSheet(
            f"background:{col}; color:white; border-radius:{UIScale.px(11)}px;"
            f" font-weight:bold;"
        )
        self._badge.setText(str(min(count, 9)))
        self._badge.show()
        self._badge.move(self.width() - UIScale.px(28), UIScale.px(6))

    def set_context(self, text: str, color: str = "") -> None:
        if text:
            self._ctx_lbl.setStyleSheet(
                f"color:{color or P.fg_dim}; background:transparent;"
            )
            self._ctx_lbl.setText(text)
            self._ctx_lbl.show()
        else:
            self._ctx_lbl.hide()

    # ── Internal style helpers ────────────────────────────────────────────────

    def _refresh_style(self, hovered: bool) -> None:
        bg         = P.bg_hover  if hovered else P.bg_panel
        border     = P.border_light if hovered else P.border
        title_col  = P.fg_header if hovered else self._accent
        icon_col   = P.fg_header if hovered else self._accent
        sub_col    = P.fg        if hovered else P.fg_dim

        self.setStyleSheet(
            f"#primaryCard{{background:{bg};border:1px solid {border};"
            f"border-radius:6px;}}"
        )
        self._title_lbl.setStyleSheet(
            f"color:{title_col}; background:transparent;"
        )
        self._icon_lbl.setStyleSheet(
            f"color:{icon_col}; background:transparent;"
        )
        self._sub_lbl.setStyleSheet(
            f"color:{sub_col}; background:transparent;"
        )
        if self._hk_lbl:
            hk_bg  = P.bg_panel if hovered else P.bg
            hk_fg  = P.fg       if hovered else P.fg_dim
            hk_bd  = P.border_light if hovered else P.border
            self._hk_lbl.setStyleSheet(
                f"color:{hk_fg}; background:{hk_bg}; border:1px solid {hk_bd};"
                f" border-radius:3px;"
            )
        self._accent_line.setStyleSheet(
            f"background:{self._accent}; border:none;"
        )

    # ── Qt events ─────────────────────────────────────────────────────────────

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._badge.isVisible():
            self._badge.move(self.width() - UIScale.px(28), UIScale.px(6))

    def enterEvent(self, event: QEvent) -> None:
        self._refresh_style(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._refresh_style(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Slight dim on press for tactile feel
        if event.button() == Qt.MouseButton.LeftButton:
            self.setStyleSheet(
                f"#primaryCard{{background:{P.bg}; border:1px solid {P.border_light};"
                f"border-radius:6px;}}"
            )
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._refresh_style(self.underMouse())
            if self.underMouse():
                self.clicked.emit()
        super().mouseReleaseEvent(event)


# ─────────────────────────────────────────────────────────────────────────────

class _SecNavCard(QFrame):
    """
    Compact navigation card used in the section grid below the primary row.
    Left accent bar · icon · title / subtitle · optional context text · badge.
    """

    clicked = Signal()

    def __init__(
        self,
        icon:     str,
        title:    str,
        subtitle: str,
        accent:   str,
        parent:   Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._accent = accent
        self.setObjectName("secCard")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFixedHeight(UIScale.px(62))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, UIScale.px(8), 0)
        lay.setSpacing(0)

        # Left colour bar
        self._accent_bar = QFrame(self)
        self._accent_bar.setFixedWidth(4)
        self._accent_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._accent_bar.setStyleSheet(
            f"background:{accent}; border:none; border-radius:0px;"
        )
        lay.addWidget(self._accent_bar)

        # Icon
        self._icon_lbl = QLabel(icon, self)
        self._icon_lbl.setFixedWidth(UIScale.px(46))
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setFont(Fonts.icon)
        self._icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._icon_lbl)

        # Text VBox
        txt = QVBoxLayout()
        txt.setContentsMargins(0, UIScale.px(8), 0, UIScale.px(8))
        txt.setSpacing(UIScale.px(2))

        self._title_lbl = QLabel(title, self)
        self._title_lbl.setFont(Fonts.body_bold)
        self._title_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        txt.addWidget(self._title_lbl)

        self._sub_lbl = QLabel(subtitle, self)
        self._sub_lbl.setFont(Fonts.small)
        self._sub_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        txt.addWidget(self._sub_lbl)

        lay.addLayout(txt, 1)

        # Context label (right-aligned, optional)
        self._ctx_lbl = QLabel("", self)
        self._ctx_lbl.setFont(Fonts.tiny)
        self._ctx_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._ctx_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._ctx_lbl.hide()
        lay.addWidget(self._ctx_lbl)

        # Badge circle
        self._badge = QLabel("", self)
        self._badge.setFixedSize(UIScale.px(20), UIScale.px(20))
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFont(Fonts.tiny)
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._badge.hide()
        lay.addWidget(self._badge)

        self._refresh_style(False)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_badge(self, count: int, color: str = "") -> None:
        if count <= 0:
            self._badge.hide()
            return
        col = color or P.red
        self._badge.setStyleSheet(
            f"background:{col}; color:white; border-radius:{UIScale.px(10)}px;"
            f" font-weight:bold;"
        )
        self._badge.setText(str(min(count, 99)))
        self._badge.show()

    def set_context(self, text: str, color: str = "") -> None:
        if text:
            self._ctx_lbl.setStyleSheet(
                f"color:{color or P.fg_dim}; background:transparent;"
                f" padding-right:4px;"
            )
            self._ctx_lbl.setText(text)
            self._ctx_lbl.show()
        else:
            self._ctx_lbl.hide()

    def clear_badge(self) -> None:
        self.set_badge(0)

    def clear_context(self) -> None:
        self.set_context("")

    # ── Style helpers ─────────────────────────────────────────────────────────

    def _refresh_style(self, hovered: bool) -> None:
        bg        = P.bg_hover  if hovered else P.bg_panel
        border    = P.border_light if hovered else P.border
        title_col = P.fg_header if hovered else P.fg
        sub_col   = P.fg        if hovered else P.fg_dim

        self.setStyleSheet(
            f"#secCard{{background:{bg}; border:1px solid {border};"
            f" border-radius:5px;}}"
        )
        self._title_lbl.setStyleSheet(
            f"color:{title_col}; background:transparent;"
        )
        self._sub_lbl.setStyleSheet(
            f"color:{sub_col}; background:transparent;"
        )
        self._icon_lbl.setStyleSheet(
            f"color:{P.fg_header if hovered else self._accent}; background:transparent;"
        )

    # ── Qt events ─────────────────────────────────────────────────────────────

    def enterEvent(self, event: QEvent) -> None:
        self._refresh_style(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._refresh_style(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setStyleSheet(
                f"#secCard{{background:{P.bg}; border:1px solid {P.border_light};"
                f" border-radius:5px;}}"
            )
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._refresh_style(self.underMouse())
            if self.underMouse():
                self.clicked.emit()
        super().mouseReleaseEvent(event)


# ══════════════════════════════════════════════════════════════════════════════

class MainMenuScreen(Screen):
    """
    Navigation hub — the player's home base between turns.

    Layout (top → bottom):
        1. Alert strip   — urgent game warnings (hidden when nothing urgent)
        2. Primary row   — 4 large cards: Trade / Travel / Inventory / Rest & Wait
        3. Scrollable section grid — all other screens in labelled groups
        4. System footer — Save · Bankruptcy · Quit

    Badge / context lines in the section grid are refreshed on every  refresh()
    call so the player always sees live counts (active contracts, broken
    businesses, active voyages, etc.) at a glance.
    """

    # ── Navigation data ───────────────────────────────────────────────────────

    # (screen_key, emoji, title, subtitle, accent_colour)
    _PRIMARY: List[Tuple[str, str, str, str, str]] = [
        ("trade",     "⚖",  "Trade",       "Buy & sell at the local market",  P.gold),
        ("travel",    "🗺", "Travel",      "Journey to a new region",         P.amber),
        ("inventory", "🎒", "Inventory",   "Manage cargo & equipment",        P.gold),
        ("wait",      "⌛", "Rest & Wait", "Pass time · advance the day",     P.amber),
    ]

    # (section_name, accent_colour, [(key, emoji, title, subtitle), ...])
    _SECTIONS: List[Tuple[str, str, List[Tuple[str, str, str, str]]]] = [
        ("OPERATIONS", P.amber, [
            ("businesses",  "🏭", "Businesses",    "Production & workshops"),
            ("managers",    "👔", "Managers",      "Hire & manage NPC staff"),
            ("finance",     "🏦", "Finance",       "Banking & certificates"),
            ("contracts",   "📜", "Contracts",     "Delivery orders"),
            ("lending",     "⊛",  "Lending",       "Issue citizen loans"),
            ("stocks",      "📈", "Stock Market",  "Buy & sell shares"),
            ("funds",       "💰", "Fund Mgmt",     "Manage client capital"),
            ("real_estate", "🏠", "Real Estate",   "Buy, build & lease"),
            ("skills",      "⚡", "Skills",        "Improve your character"),
            ("smuggling",   "🦝", "Smuggling Den", "Black market deals"),
            ("gamble",      "🎲", "Gamble",        "Try the Mystery Coffer"),
            ("voyage",      "⛵", "Voyage",        "International sea routes"),
        ]),
        ("INTELLIGENCE", P.blue, [
            ("market",  "📊", "Market Info",   "Prices & trade routes"),
            ("news",    "📰", "News & Events", "World events & impacts"),
            ("social",  "🌐", "Social Hub",    "Leaderboard, friends & guilds"),
        ]),
        ("CHARACTER", P.purple, [
            ("influence", "⭐", "Influence",  "Reputation & market power"),
            ("licenses",  "📋", "Licenses",   "Unlock new capabilities"),
            ("progress",  "🏆", "Progress",   "Achievements & milestones"),
            ("settings",  "⚙",  "Settings",  "Options & hotkeys"),
        ]),
    ]

    # Populated in build():
    _primary_cards: Dict[str, _PrimaryNavCard]
    _sec_cards:     Dict[str, _SecNavCard]

    # ── Build ─────────────────────────────────────────────────────────────────

    def build(self) -> None:
        self._primary_cards = {}
        self._sec_cards     = {}

        # Read hotkey map once
        hk_map: Dict[str, str] = {}
        if (hasattr(self.game, "settings") and
                hasattr(self.game.settings, "hotkeys")):
            hk_map = self.game.settings.hotkeys or {}
        if not hk_map:
            hk_map = DEFAULT_HOTKEYS

        root = QVBoxLayout(self)
        root.setContentsMargins(
            UIScale.px(14), UIScale.px(8),
            UIScale.px(14), UIScale.px(8),
        )
        root.setSpacing(0)

        # ── 1. Alert strip ────────────────────────────────────────────────────
        self._alert_strip = QFrame(self)
        self._alert_strip.setObjectName("alertStrip")
        self._alert_strip.hide()   # shown only when there are actual alerts

        a_lay = QHBoxLayout(self._alert_strip)
        a_lay.setContentsMargins(
            UIScale.px(10), UIScale.px(5),
            UIScale.px(10), UIScale.px(5),
        )
        a_lay.setSpacing(UIScale.px(10))

        self._alert_icon_lbl = QLabel("⚠", self._alert_strip)
        self._alert_icon_lbl.setFont(Fonts.body_bold)
        a_lay.addWidget(self._alert_icon_lbl)

        self._alert_text_lbl = QLabel("", self._alert_strip)
        self._alert_text_lbl.setFont(Fonts.small)
        self._alert_text_lbl.setWordWrap(False)
        # Reduce elide so short alerts never wrap the strip
        self._alert_text_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        a_lay.addWidget(self._alert_text_lbl, 1)

        root.addWidget(self._alert_strip)
        root.addSpacing(UIScale.px(6))

        # ── 2. Primary action row ─────────────────────────────────────────────
        primary_row = QHBoxLayout()
        primary_row.setSpacing(UIScale.px(8))
        primary_row.setContentsMargins(0, 0, 0, 0)

        for key, icon, title, subtitle, accent in self._PRIMARY:
            hk   = hk_map.get(key, "")
            card = _PrimaryNavCard(icon, title, subtitle, accent, hk, self)
            card.clicked.connect(
                lambda checked_=False, k=key: self.app.show_screen(k)
            )
            self._primary_cards[key] = card
            primary_row.addWidget(card, 1)

        root.addLayout(primary_row)
        root.addSpacing(UIScale.px(10))

        # ── 3. Scrollable section grid ────────────────────────────────────────
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setStyleSheet("background:transparent; border:none;")

        inner = QWidget()
        inner.setStyleSheet("background:transparent;")
        grid_outer = QVBoxLayout(inner)
        grid_outer.setContentsMargins(0, 0, UIScale.px(4), UIScale.px(4))
        grid_outer.setSpacing(0)

        COLS = 4

        for sec_name, sec_accent, items in self._SECTIONS:
            # Section header: label + thin ruled line
            hdr_lay = QHBoxLayout()
            hdr_lay.setContentsMargins(0, UIScale.px(10), 0, UIScale.px(4))
            hdr_lay.setSpacing(UIScale.px(8))

            sec_lbl = QLabel(f"  ✦  {sec_name}", inner)
            sec_lbl.setFont(Fonts.body_bold)
            sec_lbl.setStyleSheet(
                f"color:{sec_accent}; background:transparent;"
                f" letter-spacing:1px;"
            )
            sec_lbl.setSizePolicy(
                QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
            )
            hdr_lay.addWidget(sec_lbl)

            rule = QFrame(inner)
            rule.setFrameShape(QFrame.Shape.HLine)
            rule.setFixedHeight(1)
            rule.setStyleSheet(
                f"background:{sec_accent}; border:none; color:{sec_accent};"
            )
            rule.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            hdr_lay.addWidget(rule, 1)
            hdr_lay.setAlignment(rule, Qt.AlignmentFlag.AlignVCenter)
            grid_outer.addLayout(hdr_lay)

            # Card grid
            grid = QGridLayout()
            grid.setSpacing(UIScale.px(6))
            grid.setContentsMargins(0, 0, 0, 0)
            for c in range(COLS):
                grid.setColumnStretch(c, 1)

            for i, (key, icon, title, subtitle) in enumerate(items):
                card = _SecNavCard(icon, title, subtitle, sec_accent, inner)
                card.clicked.connect(
                    lambda checked_=False, k=key: self.app.show_screen(k)
                )
                self._sec_cards[key] = card
                grid.addWidget(card, i // COLS, i % COLS)

            grid_outer.addLayout(grid)

        grid_outer.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # ── 4. System footer ──────────────────────────────────────────────────
        root.addSpacing(UIScale.px(6))
        sep_line = QFrame(self)
        sep_line.setFrameShape(QFrame.Shape.HLine)
        sep_line.setFixedHeight(1)
        sep_line.setStyleSheet(f"background:{P.border}; border:none;")
        root.addWidget(sep_line)
        root.addSpacing(UIScale.px(6))

        footer = QHBoxLayout()
        footer.setSpacing(UIScale.px(8))
        footer.setContentsMargins(0, 0, 0, 0)

        save_btn = self.action_button("💾  Save", self._do_save)
        save_btn.setFixedHeight(UIScale.px(32))

        bk_btn = self.action_button(
            "⚠  File Bankruptcy", self._file_bankruptcy, role="danger"
        )
        bk_btn.setFixedHeight(UIScale.px(32))

        footer.addWidget(save_btn)
        footer.addWidget(bk_btn)
        footer.addStretch()

        quit_btn = self.action_button(
            "✕  Save & Quit", self.app.quit_game, role="danger"
        )
        quit_btn.setFixedHeight(UIScale.px(32))
        footer.addWidget(quit_btn)

        root.addLayout(footer)

    # ── Refresh — sync live game state into badges / alerts ───────────────────

    def refresh(self) -> None:
        if not self._built:
            return
        g = self.game

        # ── Helpers ───────────────────────────────────────────────────────────
        def _day() -> int:
            fn = getattr(g, "_absolute_day", None)
            return fn() if callable(fn) else 0

        abs_day   = _day()
        broken    = [b for b in getattr(g, "businesses", [])
                     if getattr(b, "broken_down", False)]
        active_c  = [c for c in getattr(g, "contracts",  [])
                     if not getattr(c, "fulfilled", True)]
        heat      = getattr(g, "heat",     0)
        news      = getattr(g, "news_feed", [])
        voyages   = [v for v in getattr(g, "voyages", [])
                     if not getattr(v, "arrived", True)]
        loans     = getattr(g, "loans",          [])
        cds       = getattr(g, "cds",            [])
        holdings  = getattr(g, "stock_holdings", [])
        props     = getattr(g, "properties",     [])

        # ── Alert strip ───────────────────────────────────────────────────────
        alerts: List[str] = []
        urgent = False

        if broken:
            n = len(broken)
            alerts.append(
                f"🔴  {n} business{'es' if n > 1 else ''} broken — needs repair"
            )
            urgent = True

        if active_c:
            nearest = min(active_c, key=lambda c: c.deadline_day - abs_day)
            dl = nearest.deadline_day - abs_day
            nm = ALL_ITEMS.get(
                nearest.item_key, type("_", (), {"name": "?"})()
            ).name
            marker = "🔴" if dl <= 3 else "🟡"
            alerts.append(
                f"{marker}  Contract: {nearest.quantity}× {nm}"
                f" → {nearest.destination.value}  [{dl}d left]"
            )
            if dl <= 3:
                urgent = True

        if heat > 70:
            alerts.append(f"🔥  Heat {heat}/100 — smuggling risk critical")
            urgent = True
        elif heat > 50:
            alerts.append(f"🔶  Heat {heat}/100 — cool down advised")

        if news and not alerts:
            # Only show news headline if there's nothing more pressing
            _, _, _, hl = news[0]
            alerts.append(f"📰  {hl[:90]}")

        if alerts:
            accent   = P.red if urgent else P.amber
            bg_strip = f"rgba(180,20,20,18)" if urgent else f"rgba(160,100,20,18)"
            self._alert_icon_lbl.setStyleSheet(
                f"color:{accent}; background:transparent;"
            )
            self._alert_text_lbl.setStyleSheet(
                f"color:{P.fg}; background:transparent;"
            )
            self._alert_text_lbl.setText("   ·   ".join(alerts))
            self._alert_strip.setStyleSheet(
                f"#alertStrip{{background:{bg_strip}; border:1px solid {accent};"
                f" border-radius:5px;}}"
            )
            self._alert_strip.show()
        else:
            self._alert_strip.hide()

        # ── Primary card badges / context ─────────────────────────────────────
        # Inventory weight
        inv   = getattr(g, "inventory", None)
        if inv and "inventory" in self._primary_cards:
            used = int(getattr(inv, "weight",    0))
            cap  = int(getattr(inv, "capacity",  0))
            if cap:
                col = P.red if used >= cap else P.amber if used > cap * 0.8 else P.green
                self._primary_cards["inventory"].set_context(
                    f"Weight  {used}/{cap}", col
                )

        # ── Section card badges / context ─────────────────────────────────────

        # Businesses
        if "businesses" in self._sec_cards:
            self._sec_cards["businesses"].set_badge(len(broken), P.red)
            n_biz = len(getattr(g, "businesses", []))
            if n_biz and not broken:
                self._sec_cards["businesses"].set_context(
                    f"{n_biz} active", P.green
                )
            elif not n_biz:
                self._sec_cards["businesses"].clear_context()

        # Contracts
        if "contracts" in self._sec_cards:
            if active_c:
                min_dl = min(c.deadline_day - abs_day for c in active_c)
                col    = P.red if min_dl <= 3 else P.amber
                self._sec_cards["contracts"].set_badge(len(active_c), col)
                self._sec_cards["contracts"].set_context(
                    f"{len(active_c)} active · ⏱ {min_dl}d", col
                )
            else:
                self._sec_cards["contracts"].clear_badge()
                self._sec_cards["contracts"].clear_context()

        # Finance: show count of active loans + CDs
        if "finance" in self._sec_cards:
            n_fin = len(loans) + len(cds)
            if n_fin:
                self._sec_cards["finance"].set_context(
                    f"{n_fin} active", P.gold
                )
            else:
                self._sec_cards["finance"].clear_context()

        # Voyage: ships at sea
        if "voyage" in self._sec_cards:
            self._sec_cards["voyage"].set_badge(len(voyages), P.blue)
            if voyages:
                self._sec_cards["voyage"].set_context(
                    f"{len(voyages)} at sea", P.blue
                )
            else:
                self._sec_cards["voyage"].clear_context()

        # Stocks held
        if "stocks" in self._sec_cards:
            if holdings:
                self._sec_cards["stocks"].set_context(
                    f"{len(holdings)} held", P.gold
                )
            else:
                self._sec_cards["stocks"].clear_context()

        # Real estate
        if "real_estate" in self._sec_cards:
            if props:
                self._sec_cards["real_estate"].set_context(
                    f"{len(props)} owned", P.gold
                )
            else:
                self._sec_cards["real_estate"].clear_context()

        # Heat badge on smuggling
        if "smuggling" in self._sec_cards and heat > 0:
            col = P.red if heat > 70 else P.amber if heat > 40 else P.fg_dim
            self._sec_cards["smuggling"].set_context(f"⚡ heat {heat}", col)

    # ── System actions ─────────────────────────────────────────────────────────

    def _do_save(self) -> None:
        import time as _time
        if hasattr(self.app, "_session_start"):
            elapsed = _time.time() - self.app._session_start
            self.game.time_played_seconds = (
                getattr(self.game, "time_played_seconds", 0) + elapsed
            )
            self.app._session_start = _time.time()
        try:
            self.game.save_game(silent=True)
            self.msg.ok("Game saved.")
            if hasattr(self.app, "_push_cloud_save"):
                self.app._push_cloud_save()
        except Exception as exc:
            self.msg.err(f"Save failed: {exc}")

    def _file_bankruptcy(self) -> None:
        dlg = QMessageBox(self)
        dlg.setWindowTitle("File Bankruptcy")
        dlg.setIcon(QMessageBox.Icon.Warning)
        dlg.setText(
            "⚠  This will erase ALL progress and start a brand-new game.\n\n"
            "This cannot be undone."
        )
        dlg.setStandardButtons(
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.Cancel
        )
        dlg.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if (dlg.exec() == QMessageBox.StandardButton.Yes and
                hasattr(self.app, "_do_bankruptcy_restart")):
            self.app._do_bankruptcy_restart()


# ── Remaining stub screen classes (replaced phase by phase) ──────────────────
TradeScreen        = _make_stub("Trade")
TravelScreen       = _make_stub("Travel")
InventoryScreen    = _make_stub("Inventory")
WaitScreen         = _make_stub("Wait / Rest")
BusinessesScreen   = _make_stub("Businesses")
FinanceScreen      = _make_stub("Finance")
ContractsScreen    = _make_stub("Contracts")
SkillsScreen       = _make_stub("Skills")
SmugglingScreen    = _make_stub("Smuggling")
MarketInfoScreen   = _make_stub("Market Info")
NewsScreen         = _make_stub("News & Events")
ProgressScreen     = _make_stub("Progress")
InfluenceScreen    = _make_stub("Influence")
LicensesScreen     = _make_stub("Licenses")
CitizenLendingScreen  = _make_stub("Citizen Lending")
StockMarketScreen  = _make_stub("Stock Market")
FundManagementScreen  = _make_stub("Fund Management")
RealEstateScreen   = _make_stub("Real Estate")
ManagersScreen     = _make_stub("Managers")
HelpScreen         = _make_stub("Help")
SettingsScreen     = _make_stub("Settings")
GambleScreen       = _make_stub("Gambling")
VoyageScreen       = _make_stub("Voyage")
SocialScreen       = _make_stub("Social")


# ── Register stub screens in GameApp._SCREEN_MAP ──────────────────────────────
GameApp._SCREEN_MAP = {
    # \u2500\u2500 Hub screens (domain entry points)
    "dashboard":        DashboardScreen,
    "trade_hub":        TradeHubScreen,
    "operations_hub":   OperationsHubScreen,
    "finance_hub":      FinanceHubScreen,
    "intelligence_hub": IntelligenceHubScreen,
    "social_hub":       SocialHubScreen,
    "profile_hub":      ProfileHubScreen,
    # \u2500\u2500 Individual screens (stubs until fully implemented)
    "trade":            TradeScreen,
    "travel":           TravelScreen,
    "inventory":        InventoryScreen,
    "wait":             WaitScreen,
    "businesses":       BusinessesScreen,
    "finance":          FinanceScreen,
    "contracts":        ContractsScreen,
    "skills":           SkillsScreen,
    "smuggling":        SmugglingScreen,
    "market":           MarketInfoScreen,
    "news":             NewsScreen,
    "progress":         ProgressScreen,
    "influence":        InfluenceScreen,
    "licenses":         LicensesScreen,
    "lending":          CitizenLendingScreen,
    "stocks":           StockMarketScreen,
    "funds":            FundManagementScreen,
    "real_estate":      RealEstateScreen,
    "reputation":       InfluenceScreen,
    "managers":         ManagersScreen,
    "help":             HelpScreen,
    "settings":         SettingsScreen,
    "gamble":           GambleScreen,
    "voyage":           VoyageScreen,
    "social":           SocialScreen,
}


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    """Launch the PySide6 Merchant Tycoon GUI."""
    # ── High-DPI setup (must happen before QApplication) ─────────────────
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Merchant Tycoon")
    app.setApplicationDisplayName("Merchant Tycoon — Expanded Edition")
    app.setOrganizationName("MerchantTycoon")

    # Initialise deferred colour tables (requires QApplication)
    _init_table_tag_colours()

    # Apply global QSS
    app.setStyleSheet(_build_qss(UIScale.factor()))
    # Scale-change QSS rebuild is handled inside GameApp._on_scale_changed
    # (connected via UIScale.connect in GameApp.__init__)

    # Create and show the main window
    window = GameApp()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
