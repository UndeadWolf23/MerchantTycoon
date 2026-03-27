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
import shutil
import weakref
import json
import base64
import glob
import zlib
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Type, Any

# ── PySide6 ───────────────────────────────────────────────────────────────────
from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QSize, QRect, QRectF,
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
    small_bold:  QFont
    mono:        QFont
    mono_small:  QFont
    mono_large:  QFont
    small:       QFont
    tiny:        QFont
    icon:             QFont   # pure Segoe UI Symbol 12pt
    icon_small:       QFont   # pure Segoe UI Symbol 9pt
    mixed:            QFont   # Palatino 11pt + Segoe fallback
    mixed_bold:       QFont   # Palatino 11pt bold + Segoe fallback
    mixed_heading:    QFont   # Palatino 13pt bold + Segoe fallback
    mixed_small:      QFont   # Palatino 9pt + Segoe fallback
    mixed_small_bold: QFont   # Palatino 9pt bold + Segoe fallback

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
        cls.small_bold  = _f(fant,  9, bold=True)
        cls.tiny        = _f(fant,  8)
        cls.mono        = _f(mono, 10)
        cls.mono_small  = _f(mono,  9)
        cls.mono_large  = _f(mono, 12)
        # Icon labels: use Segoe UI Symbol (monochrome) so symbols render
        # as crisp glyph art rather than colorful emoji.
        cls.icon        = _f("Segoe UI Symbol" if sys.platform == "win32"
                             else fant, 12)
        # Mixed labels / buttons that combine readable text with symbol glyphs
        # (e.g. NavRail buttons with "  ⌂   Dashboard"):
        # primary family = Palatino for text; symbols fall back to Segoe UI Symbol.
        cls.mixed       = _f(fant, 11)
        cls.mixed.setFamilies([fant, "Segoe UI Symbol"]
                              if sys.platform == "win32" else [fant])
        # Additional sized variants with same Segoe fallback
        _seg  = "Segoe UI Symbol" if sys.platform == "win32" else fant
        _fams = [fant, _seg] if sys.platform == "win32" else [fant]
        cls.icon_small       = _f(_seg,  9)
        cls.mixed_bold       = _f(fant, 11, bold=True)
        cls.mixed_bold.setFamilies(_fams)
        cls.mixed_heading    = _f(fant, 13, bold=True)
        cls.mixed_heading.setFamilies(_fams)
        cls.mixed_small      = _f(fant,  9)
        cls.mixed_small.setFamilies(_fams)
        cls.mixed_small_bold = _f(fant,  9, bold=True)
        cls.mixed_small_bold.setFamilies(_fams)

    @classmethod
    def metrics(cls, font: QFont) -> QFontMetrics:
        return QFontMetrics(font)

# Initialise fonts at module load
Fonts._rebuild(1.0)

# ══════════════════════════════════════════════════════════════════════════════
# SYMBOL REGISTRY  —  curated monochrome BMP Unicode glyphs
# ══════════════════════════════════════════════════════════════════════════════

class Sym:
    """
    Central registry of UI symbol glyphs.
    Every entry is a BMP Unicode character (≤ U+FFFF) present in
    'Segoe UI Symbol' on Windows — monochrome, scale-independent, and
    immune to emoji substitution.

    Labels that display pure symbols should use Fonts.icon.
    Mixed text+symbol labels should set font-family "Segoe UI Symbol" in QSS.
    """

    # ── Navigation (domain) icons ─────────────────────────────────────────────
    DASHBOARD    = "\u2302"   # ⌂  house                         (home base)
    TRADE        = "\u2696"   # ⚖  balance scales                (buy/sell)
    OPERATIONS   = "\u2692"   # ⚒  hammer and pick               (production)
    FINANCE      = "\u25c6"   # ◆  black diamond                 (capital)
    INTELLIGENCE = "\u25ce"   # ◎  bullseye / target             (data focus)
    SOCIAL       = "\u2736"   # ✶  six-pointed black star        (connections)
    PROFILE      = "\u2299"   # ⊙  circled dot                   (identity)
    SETTINGS     = "\u2699"   # ⚙  gear                          (config)

    # ── Feature / action icons ────────────────────────────────────────────────
    TRAVEL       = "\u25b6"   # ▶  filled right triangle         (move/go)
    INVENTORY    = "\u25c8"   # ◈  rotated square hollow insert  (cargo bag)
    WAIT_REST    = "\u29d7"   # ⧗  black hourglass               (time/rest)
    MANAGER      = "\u229b"   # ⊛  circled asterisk              (staff)
    CONTRACT     = "\u2712"   # ✒  black nib / pen               (signing)
    REAL_ESTATE  = "\u25a6"   # ▦  square crosshatch fill        (building plan)
    VOYAGE       = "\u2693"   # ⚓  anchor                        (sea journey)
    SKILLS       = "\u2605"   # ★  black five-pointed star       (levelling)
    SMUGGLING    = "\u25d1"   # ◑  circle right-half black       (shadow trade)
    GAMBLE       = "\u2660"   # ♠  black spade suit              (card games)
    LENDING      = "\u2295"   # ⊕  circled plus                  (credit)
    STOCKS       = "\u25b4"   # ▴  small up-pointing triangle    (growth)
    EXCHANGE     = "\u2194"   # ↔  left-right arrow              (market swap)
    NEWS         = "\u25a4"   # ▤  square with horizontal fill   (headlines)
    INFLUENCE    = "\u2726"   # ✦  four-pointed black star       (power/reach)
    LICENSES     = "\u25ad"   # ▭  white rectangle               (card/permit)
    PROGRESS     = "\u2611"   # ☑  ballot box with check         (achievement)
    TREND_UP     = "\u2197"   # ↗  north-east arrow              (positive trend)

    # ── HUD / status bar ──────────────────────────────────────────────────────
    PLAYER       = "\u2698"   # ⚘  flower                        (player name)
    GOLD         = "\u2666"   # ♦  diamond suit                  (wealth)
    LOCATION     = "\u2316"   # ⌖  position indicator crosshair  (current area)
    SLOT_FULL    = "\u25a0"   # ■  black square                  (used action slot)
    SLOT_EMPTY   = "\u25a1"   # □  white square                  (free action slot)
    HEAT         = "\u25b2"   # ▲  up-pointing triangle          (rising danger)
    REP          = "\u2729"   # ✩  outlined star                 (reputation/fame)
    NETWORTH     = "\u00a4"   # ¤  currency sign                 (total value)

    # ── Game header ───────────────────────────────────────────────────────────
    INBOX        = "\u2709"   # ✉  envelope                      (mail/inbox)
    SYNC         = "\u21bb"   # ↻  clockwise open circle arrow   (refresh/sync)
    CLOUD        = "\u2601"   # ☁  cloud                          (sync/online)

    # ── Confirm / status markers ──────────────────────────────────────────────
    YES          = "\u2714"   # ✔  heavy check mark
    NO           = "\u2715"   # ✕  multiplication x
    WARNING      = "\u25b2"   # ▲  warning triangle

    # ── Window chrome ─────────────────────────────────────────────────────────
    TITLE_ICON   = "\u2756"   # ❖  black diamond minus white X   (game logo)

    # ── UI controls / navigation ──────────────────────────────────────────────
    BACK         = "\u25c4"   # ◄  left-pointing triangle        (back/history)
    MENU         = "\u2261"   # ≡  identical-to / three lines    (hamburger)
    SAVE         = "\u2756"   # ❖  black diamond minus white X   (save)
    SECTION      = "\u2727"   # ✧  white four-pointed star       (section divider)
    INFO         = "\u203a"   # ›  single right angle quotation  (info/more)

# ══════════════════════════════════════════════════════════════════════════════
# QSS (Qt Style Sheet)  —  full application theme
# ══════════════════════════════════════════════════════════════════════════════

def _build_qss(scale: float = 1.0) -> str:
    """
    Generate the complete QSS string for the application theme.
    Regenerated on UIScale change.  Uses Palette constants for all colours.
    """
    px = lambda n: f"{max(1, round(n * scale))}px"
    check_icon = os.path.join(_HERE, "ui_checkmark.svg").replace("\\", "/")

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
    border: 2px solid {P.border};
}}

/* ── Panels ─────────────────────────────────────────────────────────────*/
QFrame#panel, QFrame.panel {{
    background-color: {P.bg_panel};
    border: 1px solid {P.border_light};
    border-radius: {px(4)};
}}

QFrame#card, QFrame.card {{
    background-color: {P.bg_card};
    border: 1px solid {P.border_light};
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
    font-family: "Palatino Linotype", "Segoe UI Symbol";
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
    border: 1px solid {P.border_light};
    border-radius: {px(4)};
    padding: {px(6)} {px(14)};
    font-family: "Palatino Linotype", "Segoe UI Symbol";
    font-weight: bold;
}}

QPushButton:hover {{
    background-color: {P.bg_hover};
    border-color: {P.gold};
    color: {P.gold};
}}

QPushButton:pressed {{
    background-color: {P.bg_button_act};
    border-color: {P.border_focus};
    color: {P.fg_header};
    padding-top: {px(7)};
    padding-bottom: {px(5)};
}}

QPushButton:disabled {{
    background-color: {P.bg};
    color: {P.fg_disabled};
    border-color: {P.border};
}}

QPushButton[role="primary"] {{
    background-color: {P.bg_button_act};
    border: 1px solid {P.border_light};
    color: {P.gold};
    font-weight: bold;
}}

QPushButton[role="secondary"] {{
    background-color: {P.bg_panel};
    border: 1px solid {P.border_focus};
    color: {P.cream};
}}

QPushButton[role="secondary"]:hover {{
    background-color: {P.bg_hover};
    border-color: {P.gold};
    color: {P.gold};
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
    border: 1px solid transparent;
    color: {P.fg_dim};
    padding: {px(4)} {px(10)};
    text-align: left;
    font-weight: normal;
}}

QPushButton[role="nav"]:hover {{
    color: {P.gold};
    background-color: {P.bg_panel};
    border-color: {P.border};
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
    padding: {px(4)} {px(30)} {px(4)} {px(8)};
    min-width: {px(80)};
}}

QComboBox:focus {{
    border-color: {P.border_focus};
}}

QComboBox::drop-down {{
    width: {px(24)};
    subcontrol-origin: padding;
    subcontrol-position: top right;
    background-color: {P.bg_button};
    border-left: 1px solid {P.border_light};
    border-top-right-radius: {px(3)};
    border-bottom-right-radius: {px(3)};
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
    padding: {px(4)};
}}

QComboBox QAbstractItemView::item {{
    min-height: {px(22)};
    padding: {px(4)} {px(8)};
}}

QComboBox QAbstractItemView::item:selected {{
    background-color: {P.bg_hover};
    color: {P.gold};
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
    image: url({check_icon});
}}

QRadioButton::indicator {{
    border-radius: {px(7)};
}}

QRadioButton::indicator:checked {{
    background-color: {P.bg_hover};
    border-color: {P.border_light};
    image: url({check_icon});
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
    color: {P.fg};
    border: none;
    border-left: {px(3)} solid transparent;
    text-align: left;
    padding: {px(4)} {px(6)} {px(4)} {px(8)};
    font-family: "Palatino Linotype", "Segoe UI Symbol";
    font-size: {px(13)};
}}
QPushButton[role="navItem"]:hover {{
    background: rgba(120, 80, 20, 80);
    color: {P.amber};
    border-left: {px(3)} solid {P.amber};
}}
QPushButton[role="navItem"]:checked {{
    background: rgba(122, 78, 28, 110);
    color: {P.gold};
    border-left: {px(3)} solid {P.gold};
    font-weight: bold;
}}

/* ── Hub cards ───────────────────────────────────────────────────── */
#hubCard {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #38240f, stop:1 #2a1b0b);
    border: 1px solid {P.border};
    border-left: {px(3)} solid {P.border_light};
    border-radius: {px(5)};
}}
#hubCard:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {P.bg_hover}, stop:1 #3a2810);
    border: 1px solid {P.border_light};
    border-left: {px(3)} solid {P.gold};
}}

/* ── Dashboard panels ────────────────────────────────────────────── */
#dashPanel {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #38240f, stop:1 {P.bg_panel});
    border: 1px solid {P.border_light};
    border-radius: 5px;
}}

/* ── Game header ─────────────────────────────────────────────────── */
#gameHeader {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #3a2810, stop:1 {P.bg});
    border-bottom: 2px solid {P.border_light};
}}

/* ── App footer ──────────────────────────────────────────────────── */
#appFooter {{
    background: #161008;
    border-top: 1px solid {P.border_light};
}}

/* ── Nav rail ─────────────────────────────────────────────────────── */
#navRail {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #141008, stop:1 {P.bg_panel});
    border-right: 1px solid {P.border_light};
}}

/* ── Content stack ────────────────────────────────────────────────── */
#contentStack {{
    background: {P.bg};
    border: none;
}}

/* ── Primary / secondary nav cards ───────────────────────────────── */
#primaryCard {{
    background: {P.bg_panel};
    border: 1px solid {P.border};
    border-radius: 6px;
}}
#secCard {{
    background: {P.bg_panel};
    border: 1px solid {P.border};
    border-radius: 5px;
}}

/* ── Message bar ──────────────────────────────────────────────────── */
#messageBar {{
    background-color: #191208;
    border-top: 1px solid {P.border_light};
}}

/* ── Title bar ────────────────────────────────────────────────────── */
#titleBar {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {P.grad_header_top},
        stop:1 {P.grad_header_bot}
    );
    border-bottom: 2px solid {P.border_light};
}}

/* ── Status bar ────────────────────────────────────────────────────── */
#statusBar {{
    background-color: {P.bg_panel};
    border-bottom: 2px solid {P.border_light};
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
        # Stop any running animation
        try:
            if self._anim and self._anim.state() == QAbstractAnimation.State.Running:
                self._anim.stop()
        except RuntimeError:
            pass
        self._anim = None

        # Create a fresh effect for this animation only; remove it when done
        # so the widget never has a permanent QGraphicsEffect (which would
        # cause nested-painter QPainter errors if a child also sets one).
        eff = QGraphicsOpacityEffect(self._w)
        eff.setOpacity(start)
        self._w.setGraphicsEffect(eff)

        a = QPropertyAnimation(eff, b"opacity", self._w)
        a.setDuration(ms)
        a.setStartValue(start)
        a.setEndValue(end)
        a.setEasingCurve(easing)

        def _cleanup() -> None:
            self._w.setGraphicsEffect(None)
            self._anim = None
            if on_done:
                on_done()

        a.finished.connect(_cleanup)
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
        try:
            if self._anim and self._anim.state() == QAbstractAnimation.State.Running:
                self._anim.stop()
        except RuntimeError:
            pass
        self._anim = None

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
        a.finished.connect(lambda: setattr(self, '_anim', None))
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
        lbl = QLabel(f"  {Sym.SECTION}  {text.upper()}  {Sym.SECTION}", parent or self)
        lbl.setFont(Fonts.mixed_bold)
        lbl.setProperty("role", "section")
        lbl.setStyleSheet(f"color: {P.gold}; padding: 4px 0px;")
        return lbl

    def action_button(self, text: str, command: Callable,
                      parent: Optional[QWidget] = None,
                      role: str = "primary") -> "MtButton":
        btn = MtButton(text, parent or self, role=role)
        btn.clicked.connect(command)
        return btn

    def back_button(self, text: str = f"{Sym.BACK}  Back",
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
    Adds a brief opacity-dip press animation and correct role styling.
    Hover effects are handled entirely by QSS (border-color + bg change).
    """

    def __init__(self, text: str = "",
                 parent: Optional[QWidget] = None,
                 role: str = "primary",
                 icon: Optional[QIcon] = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", role)
        if icon:
            self.setIcon(icon)
        self.setFont(Fonts.mixed_bold)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._press_anim: Optional[QPropertyAnimation] = None
        self._opacity_eff: Optional[QGraphicsOpacityEffect] = None

    def setRole(self, role: str) -> None:
        self.setProperty("role", role)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            eff = QGraphicsOpacityEffect(self)
            eff.setOpacity(1.0)
            self.setGraphicsEffect(eff)
            self._opacity_eff = eff
            anim = QPropertyAnimation(eff, b"opacity", self)
            anim.setDuration(80)
            anim.setStartValue(1.0)
            anim.setEndValue(0.6)
            anim.setEasingCurve(Easing.BUTTON_PRESS)
            self._press_anim = anim
            anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._opacity_eff is not None:
            anim = QPropertyAnimation(self._opacity_eff, b"opacity", self)
            anim.setDuration(120)
            anim.setStartValue(self._opacity_eff.opacity())
            anim.setEndValue(1.0)
            anim.setEasingCurve(Easing.BUTTON_RELEASE)
            anim.finished.connect(lambda: self.setGraphicsEffect(None))
            self._press_anim = anim
            anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
            self._opacity_eff = None
        super().mouseReleaseEvent(event)


class ProfileIconButton(QPushButton):
    """Circular header button with a simple bust glyph for profile access."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("", parent)
        self._hovered = False
        self.setToolTip("Profile")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFixedSize(UIScale.px(40), UIScale.px(34))
        self.setStyleSheet("QPushButton{background:transparent;border:none;padding:0px;}")

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        outer = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        hovered = self._hovered or self.isDown()
        bg = Palette.rgba(P.bg_hover if hovered else P.bg_panel, 220 if hovered else 170)
        border = QColor(P.gold if hovered else P.border)
        fg = QColor(P.gold if hovered else P.fg_dim)

        painter.setPen(QPen(border, 1.2))
        painter.setBrush(bg)
        painter.drawEllipse(outer)

        painter.setPen(QPen(fg, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        head = QRectF(
            outer.center().x() - outer.width() * 0.13,
            outer.top() + outer.height() * 0.22,
            outer.width() * 0.26,
            outer.height() * 0.26,
        )
        painter.drawEllipse(head)

        shoulders = QRectF(
            outer.center().x() - outer.width() * 0.26,
            outer.top() + outer.height() * 0.46,
            outer.width() * 0.52,
            outer.height() * 0.28,
        )
        painter.drawArc(shoulders, 25 * 16, 130 * 16)

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
        self._player.setText(f"{Sym.PLAYER}  {name}")
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
        self._gold.setText(f"{Sym.GOLD} {new_gold:,.0f}g   Bank: {g.bank_balance:,.0f}g")
        if self._prev_gold >= 0 and new_gold != self._prev_gold:
            flash_col = P.green if new_gold > self._prev_gold else P.red
            self._flash_gold(flash_col)
        self._prev_gold = new_gold

        # Location
        self._location.setText(f"{Sym.LOCATION}  {g.current_area.value}")

        # Net worth
        self._nw.setText(f"Net Worth: {g._net_worth():,.2f}g")

        # Action slots
        used = g.daily_time_units
        left = g.DAILY_TIME_UNITS - used
        bar  = "●" * used + "○" * left
        slot_col = P.red if left == 0 else P.amber if left <= 2 else P.gold
        self._slots.setText(f"{Sym.SLOT_FULL} {bar}  ({left} actions left)")
        self._slots.setStyleSheet(f"color: {slot_col}; background: transparent;")

        # Heat
        if g.heat > 0:
            heat_col = P.red if g.heat > 50 else P.amber
            self._heat.setText(f"{Sym.HEAT} Heat: {g.heat}/100")
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
        self._label.setFont(Fonts.mixed)
        self._label.setStyleSheet("background: transparent;")
        layout.addWidget(self._label)

        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(self._clear)

        self._anim = QPropertyAnimation(self, b"maximumHeight", self)
        self._anim.setEasingCurve(Easing.SMOOTH)

        self._toast_fn: Optional[Callable] = None   # set by GameApp

    # ── Public API ────────────────────────────────────────────────────────────

    def ok(self,   text: str) -> None: self._show(f"  {Sym.YES}  {text}", P.green)
    def warn(self, text: str) -> None: self._show(f"  {Sym.WARNING}  {text}", P.amber)
    def err(self,  text: str) -> None: self._show(f"  {Sym.NO}  {text}", P.red)
    def info(self, text: str) -> None: self._show(f"  {Sym.INFO}  {text}", P.gold)

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
    _STACK_MARGIN = 16

    _active: List["GameToast"] = []   # class-level live list

    def __init__(self, parent: QWidget, text: str,
                 colour: str = P.amber,
                 duration_ms: Optional[int] = None) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip)
        self._host = parent
        self._duration_ms = duration_ms or self._DURATION_MS
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.ToolTip |
                            Qt.WindowType.WindowStaysOnTopHint)

        # Limit active toasts
        while len(self._stack_for(parent)) >= self._MAX_VISIBLE:
            oldest = self._stack_for(parent)[0]
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

        start_pos, end_pos = self._positions_for(parent)

        self.move(start_pos)
        self.show()

        self._reflow(parent, exclude=self)

        # Slide in
        self._pos_anim = QPropertyAnimation(self, b"pos", self)
        self._pos_anim.setDuration(self._SLIDE_IN_MS)
        self._pos_anim.setStartValue(start_pos)
        self._pos_anim.setEndValue(end_pos)
        self._pos_anim.setEasingCurve(Easing.TOAST_IN)
        self._pos_anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

        # Auto-dismiss
        QTimer.singleShot(self._duration_ms, self._start_fade_out)

    @classmethod
    def _stack_for(cls, parent: QWidget) -> List["GameToast"]:
        return [toast for toast in cls._active
                if getattr(toast, "_host", None) is parent and not toast.isHidden()]

    @classmethod
    def _target_pos(cls, parent: QWidget, toast: "GameToast", index: int) -> QPoint:
        margin = UIScale.px(cls._STACK_MARGIN)
        pgeom = parent.rect()
        origin = parent.mapToGlobal(QPoint(0, 0))
        x = origin.x() + pgeom.width() - toast.width() - margin
        y = origin.y() + pgeom.height() - margin - (toast.height() + margin) * (index + 1)
        return QPoint(x, y)

    def _positions_for(self, parent: QWidget) -> Tuple[QPoint, QPoint]:
        stack = self._stack_for(parent)
        idx = max(0, len(stack) - 1)
        end_pos = self._target_pos(parent, self, idx)
        origin = parent.mapToGlobal(QPoint(0, 0))
        start_pos = QPoint(end_pos.x(), origin.y() + parent.height())
        return start_pos, end_pos

    @classmethod
    def _reflow(cls, parent: QWidget, exclude: Optional["GameToast"] = None) -> None:
        for idx, toast in enumerate(cls._stack_for(parent)):
            if toast is exclude:
                continue
            toast.move(cls._target_pos(parent, toast, idx))

    @classmethod
    def reflow_for(cls, parent: QWidget) -> None:
        cls._reflow(parent)

    def _start_fade_out(self) -> None:
        if self.graphicsEffect() is not None:
            return
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
        host = getattr(self, "_host", None)
        self.hide()
        self.deleteLater()
        if host is not None:
            self._reflow(host)


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
                 multi_select: bool = False,
                 stretch_last: bool = True) -> None:
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
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        for i, col in enumerate(self._col_defs):
            item = QTableWidgetItem(col.heading)
            item.setFont(Fonts.body_bold)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setHorizontalHeaderItem(i, item)
            self._table.setColumnWidth(i, UIScale.px(col.width))

        hdr.setStretchLastSection(stretch_last)
        self._table.verticalHeader().setDefaultSectionSize(self._row_height)
        self._table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

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
# WINDOW CONTROL BUTTON  —  painted min / max / close icons
# ══════════════════════════════════════════════════════════════════════════════

class _WinCtrlButton(QPushButton):
    """
    Window-chrome button whose icon is drawn via QPainter rather than
    rendered from a font glyph.  Eliminates all emoji-substitution risk and
    ensures pixel-perfect, correctly-coloured controls on every platform.
    """

    MINIMISE = "minimise"
    MAXIMISE = "maximise"
    RESTORE  = "restore"
    CLOSE    = "close"

    _HOVER_BG: Dict[str, str] = {
        "minimise": "rgba(255, 180,  40, 50)",
        "maximise": "rgba( 80, 220,  60, 40)",
        "restore":  "rgba( 80, 220,  60, 40)",
        "close":    "rgba(240,  50,  50, 60)",
    }
    _STROKE: Dict[str, str] = {
        "minimise": P.amber,
        "maximise": P.green,
        "restore":  P.green,
        "close":    P.red,
    }

    def __init__(self, kind: str, slot: Callable,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__("", parent)
        self._kind = kind
        self.setFixedSize(UIScale.px(46), UIScale.px(38))
        self.setToolTip(kind.title())
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self._apply_style()
        self.clicked.connect(slot)

    def set_kind(self, kind: str) -> None:
        """Switch between maximise and restore glyphs without recreating."""
        self._kind = kind
        self.setToolTip(kind.title())
        self._apply_style()
        self.update()

    def _apply_style(self) -> None:
        hbg = self._HOVER_BG.get(self._kind, "rgba(255,255,255,25)")
        self.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; }}
            QPushButton:hover {{ background: {hbg}; }}
            QPushButton:pressed {{ background: rgba(255,255,255,45); }}
        """)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)   # draw QSS bg / hover tint first
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w // 2, h // 2
        s   = max(4, UIScale.px(5))   # glyph half-size in pixels
        col = QColor(self._STROKE.get(self._kind, P.fg))
        p.setPen(QPen(col, 1.6,
                      Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)

        if self._kind == self.MINIMISE:
            # Horizontal bar  ─
            p.drawLine(cx - s, cy, cx + s, cy)

        elif self._kind == self.MAXIMISE:
            # Open square  □
            p.drawRect(cx - s, cy - s, s * 2, s * 2)

        elif self._kind == self.RESTORE:
            # Classic Windows restore: back-window stub + front window
            off = max(2, s // 2)
            p.drawLine(cx - s + off, cy - s - off, cx + s,       cy - s - off)
            p.drawLine(cx + s,       cy - s - off, cx + s,       cy - s + off - 1)
            p.drawRect(cx - s, cy - s + off, s * 2 - off, s * 2 - off)

        elif self._kind == self.CLOSE:
            # Diagonal cross  ×
            p.drawLine(cx - s, cy - s, cx + s, cy + s)
            p.drawLine(cx - s, cy + s, cx + s, cy - s)

        p.end()


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
        icon_lbl = QLabel(Sym.TITLE_ICON, self)
        icon_lbl.setFont(Fonts.icon)
        icon_lbl.setStyleSheet(f"color: {P.border_light}; background: transparent;")
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

        # Window control buttons: min / max / close  (drawn via QPainter)
        for kind, slot in [
            (_WinCtrlButton.MINIMISE, window.showMinimized),
            (_WinCtrlButton.MAXIMISE, self._toggle_maximise),
            (_WinCtrlButton.CLOSE,    window.quit_game),
        ]:
            btn = _WinCtrlButton(kind, slot, self)
            layout.addWidget(btn)
            if kind == _WinCtrlButton.MAXIMISE:
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
                self._max_btn.set_kind(_WinCtrlButton.MAXIMISE)
        else:
            self._window.showMaximized()
            if self._max_btn:
                self._max_btn.set_kind(_WinCtrlButton.RESTORE)
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
            # Clear the outgoing widget's temp effect, then switch.
            # Do NOT set any effect on the incoming widget — its FadeEffect
            # (set up in BaseScreen.__init__) handles the fade-in via activate().
            current_widget.setGraphicsEffect(None)
            self._stack.setCurrentIndex(index)
            self._in_transit = False
            if on_switched:
                on_switched()

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
            UIScale.px(12),  UIScale.px(4),
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
        self._slots_lbl.setFont(Fonts.mixed_small)
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
            lbl.setFont(Fonts.mixed_bold)
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
            btn.setFixedSize(UIScale.px(40), UIScale.px(34))
            btn.setToolTip(tip)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {P.fg_dim};
                    border: none;
                    border-radius: {UIScale.px(6)}px;
                    padding: 0px {UIScale.px(6)}px;
                    font-family: 'Segoe UI Symbol';
                    font-size: {UIScale.px(16)}px;
                }}
                QPushButton:hover {{
                    background: {P.bg_hover};
                    color: {P.gold};
                }}
            """)
            return btn

        self._inbox_btn   = _icon_btn(Sym.INBOX,     "Inbox")
        self._profile_btn = ProfileIconButton(self)
        self._sync_btn    = _icon_btn(Sym.CLOUD,     "Cloud sync — click to save & sync")
        self._rest_btn    = _icon_btn(Sym.WAIT_REST, "Rest & Wait")

        def _debug_btn(text: str, tip: str, role: str, slot: Callable) -> MtButton:
            btn = MtButton(text, self, role=role)
            btn.setToolTip(tip)
            btn.setFont(Fonts.tiny)
            btn.setFixedHeight(UIScale.px(24))
            btn.clicked.connect(slot)
            return btn

        self._dbg_mail_btn = _debug_btn("Mail", "Debug: stage fake inbox mail", "secondary", self.window()._debug_send_mail)
        self._dbg_gold_btn = _debug_btn("+5000g", "Debug: add 5000 gold", "secondary", self.window()._debug_add_gold)
        self._dbg_cloud_btn = _debug_btn("Restore", "Debug: restore from cloud save", "secondary", self.window()._debug_cloud_restore)
        self._dbg_purge_btn = _debug_btn("Purge", "Debug: purge local save files", "danger", self.window()._debug_purge_saves)

        self._sync_lbl = QLabel("", self)
        self._sync_lbl.setFont(Fonts.tiny)
        self._sync_lbl.setStyleSheet(
            f"color:{P.fg_dim}; background:transparent;"
        )
        self._sync_lbl.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        self._sync_lbl.setMaximumWidth(UIScale.px(168))

        right = QHBoxLayout()
        right.setSpacing(UIScale.px(4))
        right.addWidget(self._dbg_mail_btn)
        right.addWidget(self._dbg_gold_btn)
        right.addWidget(self._dbg_cloud_btn)
        right.addWidget(self._dbg_purge_btn)
        right.addSpacing(UIScale.px(10))
        right.addWidget(self._rest_btn)
        right.addWidget(self._inbox_btn)
        right.addWidget(self._profile_btn)
        right.addWidget(self._sync_btn)
        right.addWidget(self._sync_lbl)
        lay.addLayout(right)

    def refresh(self) -> None:
        g   = self._game
        inv = getattr(g, "inventory", None)

        # Gold
        gold = getattr(inv, "gold", 0) if inv else 0
        self._gold_lbl.setText(f"{Sym.GOLD} {gold:,.0f}g")

        # Reputation
        rep      = getattr(g, "reputation", 0)
        rl, rc   = rep_label(rep)
        self._rep_lbl.setText(f"{Sym.REP} {rl}  ({rep})")
        self._rep_lbl.setStyleSheet(f"color:{rc}; background:transparent;")

        # Networth
        nw = getattr(g, "net_worth", gold)
        if callable(nw):
            nw = nw()
        self._net_lbl.setText(f"{Sym.NETWORTH} {nw:,.0f}g")

        # Location
        loc   = getattr(g, "current_area", None)
        loc_s = loc.value if loc and hasattr(loc, "value") else str(loc or "?")
        self._loc_lbl.setText(f"{Sym.LOCATION} {loc_s}")

        # Day / Season / Year
        day    = getattr(g, "day",    1)
        year   = getattr(g, "year",   1)
        season = getattr(g, "season", None)
        sea_s  = season.value if season and hasattr(season, "value") else "?"
        sea_c  = SEASON_COLOURS.get(season, P.gold)
        self._day_lbl.setText(f"Day {day}  ·  {sea_s}  ·  Year {year}")
        self._day_lbl.setStyleSheet(f"color:{sea_c}; background:transparent;")

        # Slots
        used = int(getattr(g, "daily_time_units", getattr(g, "slots_used", 0)) or 0)
        mxs  = int(getattr(g, "DAILY_TIME_UNITS", getattr(g, "action_slots", 5)) or 5)
        free = max(0, mxs - used)
        dots = Sym.SLOT_FULL * used + Sym.SLOT_EMPTY * free
        col  = P.red if free == 0 else P.amber if free <= 1 else P.fg_dim
        self._slots_lbl.setText(f"{dots}  ({free} actions left)")
        self._slots_lbl.setStyleSheet(f"color:{col}; background:transparent;")

    def set_inbox_badge(self, n: int) -> None:
        """Update the inbox button to show an unread count."""
        br  = UIScale.px(6)
        fsz = UIScale.px(16)
        self._inbox_btn.setFixedSize(UIScale.px(54 if n > 0 else 40), UIScale.px(34))
        _s  = (f"border:none; border-radius:{br}px; padding:0px {UIScale.px(6)}px;"
               f" font-family:'Segoe UI Symbol'; font-size:{fsz}px;")
        if n > 0:
            self._inbox_btn.setText(f"{Sym.INBOX}  {min(n, 9)}")
            self._inbox_btn.setStyleSheet(
                f"QPushButton{{background:transparent; color:{P.red}; {_s}}}"
                f"QPushButton:hover{{background:{P.bg_hover}; color:{P.gold};}}"
            )
        else:
            self._inbox_btn.setText(Sym.INBOX)
            self._inbox_btn.setStyleSheet(
                f"QPushButton{{background:transparent; color:{P.fg_dim}; {_s}}}"
                f"QPushButton:hover{{background:{P.bg_hover}; color:{P.gold};}}"
            )

    def set_sync_status(self, text: str, colour: str = "") -> None:
        """Update the cloud-sync status label text and colour."""
        self._sync_lbl.setText(text)
        c = colour or P.fg_dim
        self._sync_lbl.setStyleSheet(
            f"color:{c}; background:transparent;"
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
    "voyage":          "operations", "smuggling":  "operations",
    "gamble":          "operations",
    "finance_hub":     "finance",
    "finance":         "finance",  "lending":    "finance",
    "stocks":          "finance",  "funds":      "finance",
    "intelligence_hub": "info",
    "market":          "info", "news":      "info", "help": "info",
    "social_hub":      "social",
    "social":          "social",   "influence":  "social",
    "profile_hub":     "player",
    "licenses":        "player",  "progress":   "player",
    "reputation":      "player",  "skills":     "player",
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
        ("dashboard",    Sym.DASHBOARD,    "Dashboard"),
        ("trade",        Sym.TRADE,        "Trade & Travel"),
        ("operations",   Sym.OPERATIONS,   "Operations"),
        ("finance",      Sym.FINANCE,      "Finance"),
        ("info",         Sym.INTELLIGENCE, "Info"),
        ("social",       Sym.SOCIAL,       "Social"),
        ("player",       Sym.PROFILE,      "Player"),
    ]
    _BOTTOM: List[Tuple[str, str, str]] = [
        ("settings", Sym.SETTINGS, "Settings"),
    ]
    _SECTION_SCREEN: Dict[str, str] = {
        "dashboard":    "dashboard",
        "settings":     "settings",
    }
    _SUBMENUS: Dict[str, List[Tuple[str, str, str]]] = {
        "trade": [
            ("trade", Sym.TRADE, "Trade"),
            ("travel", Sym.TRAVEL, "Travel"),
        ],
        "operations": [
            ("businesses", Sym.OPERATIONS, "Businesses"),
            ("contracts", Sym.CONTRACT, "Contracts"),
            ("gamble", Sym.GAMBLE, "Gambling"),
            ("smuggling", Sym.SMUGGLING, "Smuggling"),
            ("managers", Sym.MANAGER, "Managers"),
            ("real_estate", Sym.REAL_ESTATE, "Real Estate"),
            ("voyage", Sym.VOYAGE, "Voyages"),
        ],
        "finance": [
            ("finance", Sym.FINANCE, "Banking"),
            ("lending", Sym.LENDING, "Lending"),
            ("funds", Sym.NETWORTH, "Fund Management"),
            ("stocks", Sym.STOCKS, "Stock Market"),
        ],
        "info": [
            ("market", Sym.INTELLIGENCE, "Market Info"),
            ("news", Sym.NEWS, "News & Events"),
            ("help", Sym.INFO, "Help"),
        ],
        "social": [
            ("social", Sym.SOCIAL, "Social Hub"),
            ("influence", Sym.INFLUENCE, "Influence"),
        ],
        "player": [
            ("profile_hub", Sym.PROFILE, "Profile"),
            ("skills", Sym.SKILLS, "Skills"),
            ("licenses", Sym.LICENSES, "Licenses"),
            ("progress", Sym.PROGRESS, "Achievements & Stats"),
        ],
    }

    def __init__(self, app: "GameApp", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._app      = app
        self._expanded = False   # start collapsed — user can expand when needed
        self._active   = "dashboard"
        self._btns:    Dict[str, QPushButton] = {}

        self.setObjectName("navRail")
        self.setFixedWidth(UIScale.px(self.COLLAPSED_W))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        # Styling handled by global QSS #navRail rule; no inline override needed

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

        self._toggle_btn = QPushButton(Sym.MENU, hdr)
        self._toggle_btn.setFixedSize(
            UIScale.px(self.COLLAPSED_W), UIScale.px(46)
        )
        self._toggle_btn.setFont(Fonts.icon)
        self._toggle_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._toggle_btn.clicked.connect(self.toggle)
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {P.fg_dim};
                border: none;
                font-family: 'Segoe UI Symbol';
                font-size: {UIScale.px(18)}px;
                padding: 0px;
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
        self._rail_title.setVisible(False)   # hidden when collapsed
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
        # Respect initial expanded/collapsed state when building buttons
        text = f"  {icon}   {label}" if self._expanded else f"  {icon}"
        btn = QPushButton(text, self)
        btn.setCheckable(True)
        btn.setFixedHeight(UIScale.px(48))
        btn.setFont(Fonts.mixed)
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
        if section in self._SUBMENUS:
            self._show_submenu(section)
            return
        screen_key = self._SECTION_SCREEN.get(section, section)
        if screen_key not in self._app.screens:
            self._app.message_bar.warn(f"Screen '{screen_key}' not available yet.")
            return
        self._navigate_to(screen_key)

    def _navigate_to(self, screen_key: str) -> None:
        if screen_key not in self._app.screens:
            self._app.message_bar.warn(f"Screen '{screen_key}' not available yet.")
            return
        if screen_key == "dashboard":
            self._app._stack = ["dashboard"]
        else:
            self._app._stack = ["dashboard", screen_key]
        self._app.show_screen(screen_key)

    def _show_submenu(self, section: str) -> None:
        btn = self._btns.get(section)
        items = self._SUBMENUS.get(section, [])
        if btn is None or not items:
            return
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        for screen_key, icon, label in items:
            action = menu.addAction(f"{icon}  {label}")
            if screen_key == "profile_hub":
                action.triggered.connect(self._app._open_profile_dialog)
            else:
                action.triggered.connect(lambda checked=False, target=screen_key: self._navigate_to(target))
        anchor = btn.mapToGlobal(QPoint(btn.width() - UIScale.px(2), 0))
        menu.exec(anchor)

    def toggle(self) -> None:
        self._expanded = not self._expanded
        target_w = UIScale.px(
            self.EXPANDED_W if self._expanded else self.COLLAPSED_W
        )
        start_w = self.width()

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

        # Animate the width change smoothly
        self.setMinimumWidth(min(start_w, target_w))
        self.setMaximumWidth(max(start_w, target_w))
        grp = QParallelAnimationGroup(self)
        for prop in (b"minimumWidth", b"maximumWidth"):
            a = QPropertyAnimation(self, prop, self)
            a.setDuration(220)
            a.setStartValue(start_w)
            a.setEndValue(target_w)
            a.setEasingCurve(
                Easing.SLIDE_OPEN if self._expanded else Easing.SLIDE_CLOSE
            )
            grp.addAnimation(a)
        grp.finished.connect(lambda: self.setFixedWidth(target_w))
        grp.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


# ══════════════════════════════════════════════════════════════════════════════
# APP FOOTER  —  persistent bottom bar with Back / Save / Help / Quit
# ══════════════════════════════════════════════════════════════════════════════

class AppFooter(QWidget):
    """Bottom action bar: ◄ Back  (stretch)  ❖ Save  ? Help  ✕ Quit."""

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

        self._back_btn = _btn(f"{Sym.BACK}  Back", "Go back", "nav", self._app.go_back)
        self._back_btn.setVisible(False)  # hidden on dashboard

        save_btn     = _btn(f"{Sym.SAVE}  Save",         "Save game",  "nav",
                            self._app._do_save)
        help_btn     = _btn("?  Help",                    "Open help",  "nav",
                            lambda: self._app.show_screen("help")
                            if "help" in self._app.screens else None)
        quit_btn     = _btn(f"{Sym.NO}  Quit",            "Quit game",  "danger",
                            self._app.quit_game)

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
        self._last_sync_time: Optional[float] = None
        self._cached_disc: int = 0
        self._cached_guild_id: str = ""
        self._cached_guild_name: str = ""
        self._cached_guild_role: str = ""
        self._cloud_sync_timer = QTimer(self)
        self._cloud_sync_timer.setInterval(3 * 60 * 1000)
        self._cloud_sync_timer.timeout.connect(self._auto_save_and_sync)

        # ── Online services ──────────────────────────────────────────────
        try:
            from merchant_tycoon_online import OnlineServices as _OnlineSvc
            self.online = _OnlineSvc()
            self._had_online_session = bool(self.online.startup())
        except Exception:
            self.online = None
            self._had_online_session = False

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

        # ── Launch/auth flow ──────────────────────────────────────────────
        # Deferred to after the event loop starts so sizing is finalised.
        QTimer.singleShot(0, self._begin_startup_flow)

        # ── Sync status polling ───────────────────────────────────────────
        self._sync_status_timer = QTimer(self)
        self._sync_status_timer.timeout.connect(self._update_sync_status)
        self._sync_status_timer.start(30_000)  # refresh label every 30 s
        QTimer.singleShot(600, self._update_sync_status)  # initial update

        self._inbox_status_timer = QTimer(self)
        self._inbox_status_timer.timeout.connect(self._refresh_inbox_badge)
        self._inbox_status_timer.start(30_000)
        QTimer.singleShot(900, self._refresh_inbox_badge)

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
        self.game_header._rest_btn.clicked.connect(self._open_wait_dialog)
        self.game_header._inbox_btn.clicked.connect(self._open_inbox_dialog)
        self.game_header._profile_btn.clicked.connect(self._open_profile_dialog)
        self.game_header._sync_btn.clicked.connect(self._do_sync)

        # Thin gold separator
        self._header_sep = QFrame(central)
        self._header_sep.setFrameShape(QFrame.Shape.HLine)
        self._header_sep.setFixedHeight(1)
        self._header_sep.setStyleSheet(f"background:{P.border_light}; border:none;")
        root.addWidget(self._header_sep)

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
        screen_map = {"launch": LaunchScreen, **self._SCREEN_MAP}
        for name, cls in screen_map.items():
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

        self._set_game_shell_visible(name != "launch")

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
            self._update_sync_status()
        if self._stack and self._stack[-1] in self.screens:
            self.screens[self._stack[-1]].refresh()
        self._flush_unlock_toasts()

    def _flush_unlock_toasts(self) -> None:
        ach_queue = list(getattr(self.game, "ach_queue", []) or [])
        if ach_queue:
            for ach_id in ach_queue:
                ach = next((entry for entry in ACHIEVEMENTS if entry.get("id") == ach_id), None)
                if not ach:
                    continue
                text = f"{ach.get('icon', Sym.PROGRESS)} Achievement unlocked: {ach['name']}"
                GameToast(self, text, P.gold, duration_ms=4_200)
            self.game.ach_queue.clear()

        title_queue = list(getattr(self.game, "title_queue", []) or [])
        if title_queue:
            for title_id in title_queue:
                title = TITLES_BY_ID.get(title_id)
                if not title:
                    continue
                text = f"{title.get('icon', '★')} Title earned: {title['name']}"
                GameToast(self, text, P.cream, duration_ms=4_600)
            self.game.title_queue.clear()

    def total_play_time_seconds(self) -> int:
        total = float(getattr(self.game, "time_played_seconds", 0.0) or 0.0)
        if hasattr(self, "_session_start"):
            total += max(0.0, time.time() - self._session_start)
        return int(total)

    def _accumulate_session_time(self) -> None:
        if not hasattr(self, "_session_start"):
            return
        elapsed = max(0.0, time.time() - self._session_start)
        self.game.time_played_seconds = float(getattr(self.game, "time_played_seconds", 0.0) or 0.0) + elapsed
        self._session_start = time.time()
        if hasattr(self.game, "settings") and hasattr(self.game.settings, "time_played"):
            self.game.settings.time_played = int(self.game.time_played_seconds)
            self.game.settings.save()

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
        if action == "wait":
            self._open_wait_dialog()
            return
        dest = routes.get(action)
        if dest and dest in self.screens:
            self.goto(dest)

    def _on_escape(self) -> None:
        self.go_back()

    def _open_wait_dialog(self) -> None:
        """Open the Rest & Wait popup dialog from the header button."""
        dlg = WaitDialog(self, self)
        dlg.exec()

    def _open_inbox_dialog(self) -> None:
        """Open the Inbox popup dialog from the header button."""
        dlg = InboxDialog(self, self)
        dlg.exec()
        self._refresh_inbox_badge()

    def _open_profile_dialog(self) -> None:
        """Open the player profile popup dialog from the header button."""
        dlg = ProfileDialog(self, self)
        dlg.exec()

    def _set_game_shell_visible(self, visible: bool) -> None:
        if hasattr(self, "game_header"):
            self.game_header.setVisible(visible)
        if hasattr(self, "_header_sep"):
            self._header_sep.setVisible(visible)
        if hasattr(self, "nav_rail"):
            self.nav_rail.setVisible(visible)
        if hasattr(self, "app_footer"):
            self.app_footer.setVisible(visible)
        if hasattr(self, "message_bar"):
            self.message_bar.setVisible(visible)

    def _begin_startup_flow(self) -> None:
        if self._had_online_session and self.online and self.online.auth.is_authenticated:
            self._set_game_shell_visible(False)
            self._complete_authenticated_startup(self.online.auth.username or "Merchant")
            return
        if "launch" in self.screens:
            self._stack = ["launch"]
            self.show_screen("launch")
        elif "dashboard" in self.screens:
            self._stack = ["dashboard"]
            self.show_screen("dashboard")

    def _stop_verification_server(self) -> None:
        if self.online and hasattr(self.online, "verification"):
            try:
                self.online.verification.stop()
            except Exception:
                pass

    def _peek_local_save(self, path: str, bound_user_id: str = "") -> Optional[Dict[str, Any]]:
        if not path or not os.path.exists(path):
            return None
        probe = Game()
        probe.SAVE_FILE = path
        probe.bound_user_id = bound_user_id
        if not probe.load_game():
            return None
        try:
            stamp = os.path.getmtime(path)
        except Exception:
            stamp = 0.0
        return {
            "day": probe._absolute_day(),
            "gold": float(getattr(probe.inventory, "gold", 0.0) or 0.0),
            "timestamp": stamp,
            "path": path,
        }

    @staticmethod
    def _parse_remote_timestamp(value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    def _format_save_timestamp(self, value: Any) -> str:
        if isinstance(value, (int, float)) and float(value) > 0:
            try:
                return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M")
            except Exception:
                return "unknown"
        parsed = self._parse_remote_timestamp(str(value or ""))
        if parsed is None:
            return "unknown"
        try:
            return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
        except Exception:
            return parsed.strftime("%Y-%m-%d %H:%M")

    def _local_save_is_newer(self, local_meta: Dict[str, Any], cloud_meta: Dict[str, Any]) -> bool:
        local_ts = float(local_meta.get("timestamp", 0.0) or 0.0)
        remote_dt = self._parse_remote_timestamp(str(cloud_meta.get("updated_at", "") or ""))
        if local_ts > 0 and remote_dt is not None:
            try:
                return local_ts >= remote_dt.timestamp()
            except Exception:
                pass
        return int(local_meta.get("day", 0) or 0) >= int(cloud_meta.get("day", 0) or 0)

    def _complete_offline_startup(self) -> None:
        self.game.SAVE_FILE = Game.SAVE_FILE
        self.game.bound_user_id = ""
        self._resolve_startup_save(None)

    def _complete_authenticated_startup(self, online_greeting: Optional[str]) -> None:
        self._resolve_startup_save(online_greeting or "Merchant")

    def _resolve_startup_save(self, online_greeting: Optional[str]) -> None:
        is_online = bool(
            online_greeting and self.online and getattr(self.online, "is_online", False)
            and self.online.auth.user_id
        )
        is_new_game = True
        cloud_meta: Optional[Dict[str, Any]] = None

        if is_online and self.online and self.online.auth.user_id:
            user_id = self.online.auth.user_id
            acct_file = Game.save_path_for_user(user_id)
            self.game.SAVE_FILE = acct_file
            self.game.bound_user_id = user_id

            has_local = os.path.exists(acct_file)
            unbound_path = Game.SAVE_FILE
            if not has_local and os.path.exists(unbound_path):
                unbound_meta = self._peek_local_save(unbound_path)
                if unbound_meta:
                    bind_pick = BindSaveDialog(
                        self,
                        online_greeting or "Merchant",
                        int(unbound_meta.get("day", 0) or 0),
                        float(unbound_meta.get("gold", 0.0) or 0.0),
                    ).choose()
                    if bind_pick == "bind":
                        shutil.copy2(unbound_path, acct_file)
                        has_local = True
        else:
            self.game.SAVE_FILE = Game.SAVE_FILE
            self.game.bound_user_id = ""
            has_local = os.path.exists(self.game.SAVE_FILE)

        local_meta = self._peek_local_save(self.game.SAVE_FILE, self.game.bound_user_id if is_online else "") if has_local else None

        if is_online and self.online:
            try:
                meta_res = self.online.saves.list_saves()
                if meta_res and getattr(meta_res, "success", False):
                    rows = meta_res.data if isinstance(meta_res.data, list) else []
                    if rows:
                        cloud_meta = rows[0]
            except Exception:
                cloud_meta = None

        if local_meta and cloud_meta and self.online:
            local_newer = self._local_save_is_newer(local_meta, cloud_meta)
            pick = CloudSaveChoiceDialog(
                self,
                username=online_greeting or "Merchant",
                local_day=int(local_meta.get("day", 0) or 0),
                local_ts=self._format_save_timestamp(local_meta.get("timestamp", 0.0)),
                local_gold=float(local_meta.get("gold", 0.0) or 0.0),
                cloud_day=int(cloud_meta.get("day", 0) or 0),
                cloud_ts=self._format_save_timestamp(cloud_meta.get("updated_at", "")),
                cloud_gold=float(cloud_meta.get("gold", 0.0) or 0.0),
                local_newer=local_newer,
            ).choose()

            if pick == "cloud":
                pull_res = self.online.saves.download_save()
                if pull_res and getattr(pull_res, "success", False) and self._write_cloud_to_disk(pull_res) and self.game.load_game():
                    is_new_game = False
                    self._last_synced_day = self.game._absolute_day()
                else:
                    err = str(getattr(pull_res, "error", "no response") if pull_res else "no response")
                    self.message_bar.warn(f"Cloud fetch failed ({err}) — local save loaded.")
                    if local_meta and self.game.load_game():
                        is_new_game = False
                        self._last_synced_day = self.game._absolute_day()
            elif pick == "local":
                if self.game.load_game():
                    is_new_game = False
                    self._last_synced_day = self.game._absolute_day()
                    QTimer.singleShot(2500, self._push_cloud_save)
            else:
                is_new_game = True

        elif local_meta:
            if self.game.load_game():
                is_new_game = False
                self._last_synced_day = self.game._absolute_day()

        elif cloud_meta and self.online:
            pull_res = self.online.saves.download_save()
            if pull_res and getattr(pull_res, "success", False) and self._write_cloud_to_disk(pull_res) and self.game.load_game():
                is_new_game = False
                self._last_synced_day = self.game._absolute_day()
            else:
                self.message_bar.warn("Cloud load failed — starting a new game.")

        if is_new_game:
            if online_greeting:
                self.game.player_name = online_greeting.strip() or "Merchant"
            else:
                default_name = self.game.player_name or "Merchant"
                name = _popup_get_text(
                    self,
                    "New Game",
                    "Enter your merchant name.",
                    default=default_name,
                    placeholder="Merchant",
                    confirm_text="Start Game",
                )
                self.game.player_name = (name or default_name or "Merchant").strip() or "Merchant"

        self._stop_verification_server()
        self.goto("dashboard")
        self.refresh()

        if online_greeting:
            self.message_bar.ok(f"Signed in as {online_greeting}.")
            QTimer.singleShot(250, self._refresh_inbox_badge)
            QTimer.singleShot(400, self._push_online_presence)
            QTimer.singleShot(650, self._push_leaderboard)
            QTimer.singleShot(900, self._update_sync_status)
            QTimer.singleShot(1200, self._start_cloud_sync)

    def _do_sync(self) -> None:
        """Trigger a cloud save and update the sync status label."""
        if self.online is None:
            if hasattr(self, "game_header"):
                self.game_header.set_sync_status("not connected", P.amber)
            self.message_bar.err("Not connected to online services.")
            return
        if hasattr(self, "game_header"):
            self.game_header.set_sync_status("syncing\u2026", P.amber)
        self._do_save()
        self._push_online_presence()
        self._push_leaderboard()
        self._push_cloud_save()

    def _start_cloud_sync(self) -> None:
        if self.online is None or not getattr(self.online, "is_online", False):
            self._cloud_sync_timer.stop()
            return
        if not self._cloud_sync_timer.isActive():
            self._cloud_sync_timer.start()
        self._auto_save_and_sync()

    def _auto_save_and_sync(self) -> None:
        if self.online is None or not getattr(self.online, "is_online", False):
            self._cloud_sync_timer.stop()
            self._update_sync_status()
            return
        try:
            self._accumulate_session_time()
            self.game.save_game(silent=True)
        except Exception as exc:
            self.message_bar.err(f"Auto-save failed: {exc}")
            if hasattr(self, "game_header"):
                self.game_header.set_sync_status("(sync failed)", P.red)
            return
        self._push_online_presence()
        self._push_leaderboard()
        self._push_cloud_save(show_failures=False)

    def _push_online_presence(self) -> None:
        """Push lightweight presence state for friends and public profile surfaces."""
        online = getattr(self, "online", None)
        if online is None or not getattr(online, "is_online", False):
            return
        try:
            online.profile.update_presence(
                self.game._net_worth(),
                getattr(getattr(self.game, "current_area", None), "value", ""),
                guild_id=getattr(self, "_cached_guild_id", "") or "",
                guild_name=getattr(self, "_cached_guild_name", "") or "",
                guild_role=getattr(self, "_cached_guild_role", "") or "",
            )
        except Exception:
            pass

    def _push_leaderboard(self, done_callback: Optional[Callable[[], None]] = None) -> None:
        """Upsert the current player's leaderboard row."""
        online = getattr(self, "online", None)
        if online is None or not getattr(online, "is_online", False):
            if done_callback is not None:
                _queue_ui(self, done_callback)
            return
        try:
            def _cb(_result: Any) -> None:
                if done_callback is not None:
                    _queue_ui(self, done_callback)

            online.leaderboard.submit_score(
                gold=self.game.inventory.gold,
                reputation=self.game.reputation,
                day=self.game._absolute_day(),
                net_worth=self.game._net_worth(),
                lifetime_gold=float(getattr(self.game, "lifetime_gold", self.game.inventory.gold) or self.game.inventory.gold),
                title=str(getattr(self.game, "active_title", "") or ""),
                player_name=self.game.player_name or "",
                guild_id=getattr(self, "_cached_guild_id", "") or "",
                guild_name=getattr(self, "_cached_guild_name", "") or "",
                guild_role=getattr(self, "_cached_guild_role", "") or "",
                area=getattr(getattr(self.game, "current_area", None), "value", ""),
                callback=_cb,
            )
        except Exception:
            if done_callback is not None:
                _queue_ui(self, done_callback)

    def _push_cloud_save(self, *, show_failures: bool = True) -> None:
        """Push the latest local save to cloud storage if online auth is active."""
        online = getattr(self, "online", None)
        if online is None or not getattr(online, "is_online", False):
            self._update_sync_status()
            return
        try:
            with open(self.game.SAVE_FILE, "rb") as f:
                payload = f.read()
        except Exception as exc:
            if show_failures:
                self.message_bar.err(f"Cloud sync preparation failed: {exc}")
            if hasattr(self, "game_header"):
                self.game_header.set_sync_status("(sync failed)", P.red)
            return

        meta = {
            "day": self.game._absolute_day(),
            "gold": float(getattr(self.game.inventory, "gold", 0.0) or 0.0),
            "reputation": int(getattr(self.game, "reputation", 0) or 0),
            "version": str(getattr(self.game, "version", 2) or 2),
        }
        save_data = {"compressed_b64": base64.b64encode(payload).decode("ascii")}

        def _on_done(result: Any) -> None:
            def _apply() -> None:
                if result and getattr(result, "success", False):
                    self._last_sync_time = time.time()
                    self._update_sync_status()
                else:
                    if hasattr(self, "game_header"):
                        self.game_header.set_sync_status("(sync failed)", P.red)
                    err_txt = (
                        getattr(result, "error", "Cloud sync failed.")
                        if result else "Cloud sync failed."
                    )
                    if show_failures:
                        self.message_bar.err(err_txt)
            _queue_ui(self, _apply)

        online.sync.push(save_data, meta=meta, slot=1, callback=_on_done)

    def _update_sync_status(self) -> None:
        """Update the sync status label in the header."""
        if not hasattr(self, "game_header"):
            return
        if self.online is None or not getattr(self.online, "is_online", False):
            self.game_header.set_sync_status("(offline)", P.fg_dim)
            return
        if self._last_sync_time is None:
            queue_depth = getattr(getattr(self.online, "sync", None), "queue_depth", 0)
            if queue_depth:
                self.game_header.set_sync_status(f"(queued {queue_depth})", P.amber)
            else:
                self.game_header.set_sync_status("(awaiting first sync)", P.amber)
            return
        elapsed = int(time.time() - self._last_sync_time)
        if elapsed < 60:
            self.game_header.set_sync_status("(synced < 1 min ago)", P.green)
        elif elapsed < 3600:
            mins = elapsed // 60
            self.game_header.set_sync_status(f"(synced {mins} min ago)", P.fg_dim)
        else:
            hrs = elapsed // 3600
            self.game_header.set_sync_status(f"(synced {hrs} hr ago)", P.amber)

    def _refresh_inbox_badge(self) -> None:
        """Poll unread inbox count and surface it in the header."""
        if not hasattr(self, "game_header"):
            return
        online = getattr(self, "online", None)
        inbox = getattr(online, "inbox", None) if online else None
        if inbox is None or not getattr(online, "is_online", False):
            self.game_header.set_inbox_badge(0)
            return

        def _on_done(result: Any) -> None:
            def _apply() -> None:
                unread = (
                    int(getattr(result, "data", 0) or 0)
                    if getattr(result, "success", False) else 0
                )
                self.game_header.set_inbox_badge(unread)
            _queue_ui(self, _apply)

        inbox.get_unread_count(callback=_on_done)

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
            self._accumulate_session_time()
            self.game.save_game()
            self.message_bar.ok("Game saved.")
        except Exception as exc:
            self.message_bar.err(f"Save failed: {exc}")

    def _write_cloud_to_disk(self, res: Any) -> bool:
        try:
            if not res or not getattr(res, "success", False):
                return False
            data = getattr(res, "data", None)
            if not isinstance(data, dict):
                return False
            payload_b64 = str(data.get("payload_b64", "") or "")
            if not payload_b64:
                save_blob = data.get("save_data", {})
                if isinstance(save_blob, str):
                    try:
                        save_blob = json.loads(save_blob)
                    except Exception:
                        save_blob = {}
                if isinstance(save_blob, dict):
                    payload_b64 = str(save_blob.get("compressed_b64", "") or save_blob.get("payload_b64", "") or "")
            if not payload_b64:
                return False
            raw_bytes = base64.b64decode(payload_b64)
            os.makedirs(os.path.dirname(self.game.SAVE_FILE), exist_ok=True)
            with open(self.game.SAVE_FILE, "wb") as handle:
                handle.write(raw_bytes)
            return True
        except Exception:
            return False

    def _restore_cloud_save(self) -> None:
        if not (self.online and getattr(self.online, "is_online", False)):
            self.message_bar.warn("Not online — cannot restore from cloud.")
            return
        try:
            def _cb(res: Any) -> None:
                _queue_ui(self, lambda: self._apply_cloud_restore(res))
            self.online.sync.pull(callback=_cb)
            self.message_bar.info("Fetching cloud save...")
        except Exception:
            self.message_bar.warn("Cloud restore not available.")

    def _apply_cloud_restore(self, res: Any) -> None:
        if not self._write_cloud_to_disk(res):
            self.message_bar.err(
                "Cloud restore failed — no valid data returned." if not (res and getattr(res, "success", False)) else
                "Cloud save data is empty or in an unrecognised format."
            )
            return
        try:
            if self.game.load_game():
                if hasattr(self, "status_bar"):
                    self.status_bar._game = self.game
                for screen in self.screens.values():
                    screen.game = self.game
                self._session_start = time.time()
                self.refresh()
                self.message_bar.ok(f"Cloud save loaded! Welcome back, {self.game.player_name}.")
            else:
                self.message_bar.err("Cloud save corrupted — keeping current state.")
        except Exception as exc:
            self.message_bar.err(f"Cloud restore error: {exc}")

    def _debug_add_gold(self) -> None:
        self.game.inventory.gold += 5000
        self.refresh()
        self.message_bar.ok("+5000g added (debug).")

    def _debug_send_mail(self) -> None:
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        self._debug_messages = [
            {
                "id": 99001,
                "msg_type": "notification",
                "subject": "New Friend Request",
                "body": "Debug friend request mail for inbox rendering tests.",
                "reward_gold": 0,
                "reward_items": {},
                "reward_title": "",
                "reward_description": "",
                "is_read": False,
                "reward_claimed": False,
                "created_at": now,
                "expires_at": None,
            },
            {
                "id": 99002,
                "msg_type": "reward",
                "subject": "Seasonal Reward",
                "body": "Debug reward payload for inbox and claim tests.",
                "reward_gold": 2500,
                "reward_items": {"spice": 10, "silk": 5},
                "reward_title": "",
                "reward_description": "2,500g  ·  10x Spice  ·  5x Silk",
                "is_read": False,
                "reward_claimed": False,
                "created_at": now,
                "expires_at": None,
            },
            {
                "id": 99003,
                "msg_type": "maintenance",
                "subject": "Maintenance Notice",
                "body": "Debug maintenance notice for badge and inbox flow checks.",
                "reward_gold": 0,
                "reward_items": {},
                "reward_title": "",
                "reward_description": "",
                "is_read": False,
                "reward_claimed": False,
                "created_at": now,
                "expires_at": None,
            },
        ]
        if hasattr(self, "game_header"):
            self.game_header.set_inbox_badge(3)
        self.message_bar.ok("Debug: 3 fake inbox messages ready — click Inbox to view.")

    def _debug_cloud_restore(self) -> None:
        if not _popup_confirm(
            self,
            "Cloud Restore",
            "Restore the cloud save into the local slot? This overwrites local save data.",
            confirm_text="Restore Save",
            confirm_role="danger",
        ):
            return
        self._restore_cloud_save()

    def _debug_purge_saves(self) -> None:
        if not _popup_confirm(
            self,
            "Purge Local Saves",
            "Delete local save files from disk for testing? The current in-memory game stays loaded.",
            confirm_text="Purge Saves",
            confirm_role="danger",
        ):
            return
        deleted: List[str] = []
        for path in [
            self.game.SAVE_FILE,
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "merchant_savegame.json"),
        ]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                    deleted.append(os.path.basename(path))
                except Exception as exc:
                    self.message_bar.warn(f"Could not delete {os.path.basename(path)}: {exc}")
        data_dir = os.path.dirname(self.game.SAVE_FILE)
        for pattern in ["savegame*.dat", "savegame*.json"]:
            for path in glob.glob(os.path.join(data_dir, pattern)):
                if path == self.game.SAVE_FILE:
                    continue
                try:
                    os.remove(path)
                    deleted.append(os.path.basename(path))
                except Exception:
                    pass
        if deleted:
            self.message_bar.ok(f"Purged: {', '.join(deleted)}")
        else:
            self.message_bar.info("No local save files found to purge.")

    def _do_bankruptcy_restart(self) -> None:
        deleted: List[str] = []
        primary_save = getattr(self.game, "SAVE_FILE", "")
        legacy_save = os.path.join(os.path.dirname(os.path.abspath(__file__)), "merchant_savegame.json")

        for path in [primary_save, legacy_save]:
            if not path or not os.path.exists(path):
                continue
            try:
                os.remove(path)
                deleted.append(os.path.basename(path))
            except Exception as exc:
                self.message_bar.warn(f"Could not delete {os.path.basename(path)}: {exc}")

        data_dir = os.path.dirname(primary_save) if primary_save else ""
        if data_dir:
            for pattern in ["savegame*.dat", "savegame*.json"]:
                for path in glob.glob(os.path.join(data_dir, pattern)):
                    if path in {primary_save, legacy_save}:
                        continue
                    try:
                        os.remove(path)
                        deleted.append(os.path.basename(path))
                    except Exception:
                        pass

        old_screens = list(getattr(self, "screens", {}).values())
        self.game = Game()
        self._session_start = time.time()
        self._last_synced_day = 0
        self._last_sync_time = None
        self._debug_messages = []

        if hasattr(self, "game_header"):
            self.game_header._game = self.game
        if hasattr(self, "hotkeys"):
            self.hotkeys.reload(
                self.game.settings.hotkeys
                if hasattr(self.game, "settings") and hasattr(self.game.settings, "hotkeys")
                else DEFAULT_HOTKEYS
            )

        for screen in old_screens:
            try:
                screen.deactivate()
            except Exception:
                pass
            try:
                self.content_stack.removeWidget(screen)
            except Exception:
                pass
            screen.deleteLater()

        self.screens = {}
        self._stack = []
        self._register_screens()

        try:
            self.game.save_game(silent=True)
        except Exception:
            pass

        self.show_screen("dashboard")
        self.refresh()
        if deleted:
            cleared = ", ".join(sorted(set(deleted)))
            self.message_bar.ok(f"Bankruptcy filed. Fresh profile started. Cleared: {cleared}")
        else:
            self.message_bar.ok("Bankruptcy filed. Fresh profile started.")

    # ── Window close ─────────────────────────────────────────────────────────

    def quit_game(self) -> None:
        """Prompt save confirmation then close."""
        # For now, just close — Phase 5 (MainMenuScreen) will add the confirm dialog
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._accumulate_session_time()
        try:
            self.game.save_game(silent=True)
        except Exception:
            pass
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

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        GameToast.reflow_for(self)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        GameToast.reflow_for(self)

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


_QUILL_CURSOR_CACHE: Dict[int, QCursor] = {}


def _load_quill_cursor() -> QCursor:
    target_h = max(32, UIScale.px(54))
    cached = _QUILL_CURSOR_CACHE.get(target_h)
    if cached is not None:
        return cached

    pix = QPixmap(os.path.join(_HERE, "quill.png"))
    if pix.isNull():
        cursor = QCursor(Qt.CursorShape.CrossCursor)
    else:
        scaled = pix.scaledToHeight(target_h, Qt.TransformationMode.SmoothTransformation)
        hotspot_x = max(0, int(scaled.width() * 0.055))
        hotspot_y = max(0, scaled.height() - UIScale.px(6))
        cursor = QCursor(scaled, hotspot_x, hotspot_y)
    _QUILL_CURSOR_CACHE[target_h] = cursor
    return cursor


class _PopupTitleBar(QWidget):
    def __init__(self, dialog: "AppDialog", title: str) -> None:
        super().__init__(dialog)
        self._dialog = weakref.proxy(dialog)
        self._drag_offset: Optional[QPoint] = None
        self.setObjectName("popupTitleBar")
        self.setFixedHeight(UIScale.px(38))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(UIScale.px(12), 0, UIScale.px(6), 0)
        lay.setSpacing(UIScale.px(8))

        self._title_lbl = QLabel(title, self)
        self._title_lbl.setObjectName("popupTitleLabel")
        self._title_lbl.setFont(Fonts.mixed_bold)
        lay.addWidget(self._title_lbl, 1)

        close_btn = QPushButton(Sym.NO, self)
        close_btn.setObjectName("popupCloseBtn")
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setFixedSize(UIScale.px(24), UIScale.px(24))
        close_btn.clicked.connect(dialog.reject)
        lay.addWidget(close_btn)

    def set_title(self, title: str) -> None:
        self._title_lbl.setText(title)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drag_offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        self.window().move(event.globalPosition().toPoint() - self._drag_offset)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        event.accept()


class AppDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        *,
        modal: bool = True,
        frame_bg: str = "",
        body_bg: str = "",
        title_bg: str = "",
        border: str = "",
        title_fg: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setModal(modal)
        self.setObjectName("appPopup")
        self.setWindowTitle(title)

        self._frame_bg = frame_bg or P.bg_panel
        self._body_bg = body_bg or self._frame_bg
        self._title_bg = title_bg or P.bg_card
        self._border = border or P.border_light
        self._title_fg = title_fg or P.gold
        self._radius = UIScale.px(8)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._title_bar = _PopupTitleBar(self, title)
        root.addWidget(self._title_bar)

        self._body = QWidget(self)
        self._body.setObjectName("popupBody")
        root.addWidget(self._body, 1)

        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16))
        self._body_layout.setSpacing(UIScale.px(10))
        self._apply_style()

    def _apply_style(self) -> None:
        radius = self._radius
        inner = max(0, radius - UIScale.px(2))
        self.setStyleSheet(
            f"QDialog{{background:{self._frame_bg};border:2px solid {self._border};border-radius:{radius}px;}}"
            f"#popupTitleBar{{background:{self._title_bg};border-top-left-radius:{inner}px;border-top-right-radius:{inner}px;"
            f"border-bottom:1px solid {self._border};}}"
            f"#popupBody{{background:{self._body_bg};border-bottom-left-radius:{inner}px;border-bottom-right-radius:{inner}px;}}"
            f"#popupTitleLabel{{color:{self._title_fg};background:transparent;}}"
            f"#popupCloseBtn{{background:transparent;color:{P.fg_dim};border:none;font-family:'Segoe UI Symbol';"
            f"font-size:{UIScale.px(13)}px;padding:0px;}}"
            f"#popupCloseBtn:hover{{color:{P.red};}}"
        )

    def set_popup_title(self, title: str) -> None:
        self._title_bar.set_title(title)
        self.setWindowTitle(title)

    def body_layout(
        self,
        *,
        margins: Optional[Tuple[int, int, int, int]] = None,
        spacing: Optional[int] = None,
    ) -> QVBoxLayout:
        if margins is not None:
            self._body_layout.setContentsMargins(*margins)
        if spacing is not None:
            self._body_layout.setSpacing(spacing)
        return self._body_layout

    def center_on_parent(self) -> None:
        par = self.parentWidget()
        host = par.window() if par is not None else None
        if host and hasattr(host, "geometry"):
            if self.width() <= UIScale.px(120) or self.height() <= UIScale.px(100):
                self.adjustSize()
            pg = host.geometry()
            self.move(
                pg.x() + max(0, (pg.width() - self.width()) // 2),
                pg.y() + max(0, (pg.height() - self.height()) // 2),
            )


class ConfirmDialog(AppDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        *,
        confirm_text: str = "Confirm",
        cancel_text: str = "Cancel",
        confirm_role: str = "primary",
    ) -> None:
        super().__init__(parent, title)
        self.setFixedWidth(UIScale.px(420))

        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )
        lbl = QLabel(message, self._body)
        lbl.setFont(Fonts.mixed)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(lbl)

        btns = QHBoxLayout()
        cancel_btn = MtButton(cancel_text, self._body, role="secondary")
        cancel_btn.clicked.connect(self.reject)
        confirm_btn = MtButton(confirm_text, self._body, role=confirm_role)
        confirm_btn.clicked.connect(self.accept)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(confirm_btn)
        root.addLayout(btns)

        self.center_on_parent()

    def ask(self) -> bool:
        return self.exec() == QDialog.DialogCode.Accepted


class InfoDialog(AppDialog):
    def __init__(self, parent: Optional[QWidget], title: str, message: str) -> None:
        super().__init__(parent, title)
        self.setFixedWidth(UIScale.px(420))
        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )
        lbl = QLabel(message, self._body)
        lbl.setFont(Fonts.mixed)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(lbl)

        btns = QHBoxLayout()
        btns.addStretch()
        ok_btn = MtButton("OK", self._body)
        ok_btn.clicked.connect(self.accept)
        btns.addWidget(ok_btn)
        root.addLayout(btns)

        self.center_on_parent()

    def show_message(self) -> None:
        self.exec()


class IntegerPromptDialog(AppDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        prompt: str,
        *,
        value: int,
        minimum: int,
        maximum: int,
        step: int = 1,
        confirm_text: str = "Confirm",
    ) -> None:
        super().__init__(parent, title)
        self.setFixedWidth(UIScale.px(420))

        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )
        lbl = QLabel(prompt, self._body)
        lbl.setFont(Fonts.mixed)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(lbl)

        self._spin = QSpinBox(self._body)
        self._spin.setMinimum(minimum)
        self._spin.setMaximum(maximum)
        self._spin.setSingleStep(step)
        self._spin.setValue(max(minimum, min(maximum, value)))
        self._spin.setFont(Fonts.mixed_bold)
        root.addWidget(self._spin)

        btns = QHBoxLayout()
        cancel_btn = MtButton("Cancel", self._body, role="secondary")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = MtButton(confirm_text, self._body)
        ok_btn.clicked.connect(self.accept)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        root.addLayout(btns)

        self.center_on_parent()

    def get_value(self) -> Tuple[int, bool]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return self._spin.value(), False
        return self._spin.value(), True


class TextPromptDialog(AppDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        prompt: str,
        *,
        default: str = "",
        placeholder: str = "",
        confirm_text: str = "Confirm",
    ) -> None:
        super().__init__(parent, title)
        self.setFixedWidth(UIScale.px(460))

        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )
        lbl = QLabel(prompt, self._body)
        lbl.setFont(Fonts.mixed)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(lbl)

        self._edit = QLineEdit(self._body)
        self._edit.setText(default)
        self._edit.setPlaceholderText(placeholder)
        self._edit.setFont(Fonts.mixed_bold)
        self._edit.returnPressed.connect(self.accept)
        root.addWidget(self._edit)

        btns = QHBoxLayout()
        cancel_btn = MtButton("Cancel", self._body, role="secondary")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = MtButton(confirm_text, self._body)
        ok_btn.clicked.connect(self.accept)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        root.addLayout(btns)

        self.center_on_parent()
        QTimer.singleShot(0, self._focus_input)

    def _focus_input(self) -> None:
        self._edit.setFocus()
        self._edit.selectAll()

    def get_value(self) -> Optional[str]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return self._edit.text()


class ChoiceListDialog(AppDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        prompt: str,
        items: List[str],
        *,
        confirm_text: str = "Select",
    ) -> None:
        super().__init__(parent, title)
        self._selected_text = ""
        self.resize(UIScale.px(560), UIScale.px(420))

        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )
        lbl = QLabel(prompt, self._body)
        lbl.setFont(Fonts.mixed)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(lbl)

        self._list = QListWidget(self._body)
        self._list.setFont(Fonts.mixed_small)
        self._list.addItems(items)
        self._list.itemDoubleClicked.connect(lambda _item: self._accept())
        root.addWidget(self._list, 1)

        btns = QHBoxLayout()
        cancel_btn = MtButton("Cancel", self._body, role="secondary")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = MtButton(confirm_text, self._body)
        ok_btn.clicked.connect(self._accept)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        root.addLayout(btns)

        self.center_on_parent()

    def _accept(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        self._selected_text = item.text()
        self.accept()

    def choose(self) -> Tuple[str, bool]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return "", False
        return self._selected_text, bool(self._selected_text)


class ApplicantHireDialog(AppDialog):
    _COLS = [
        ("name", "Name", 180),
        ("wage", "Wage/day", 86, Qt.AlignmentFlag.AlignCenter),
        ("prod", "Productivity", 98, Qt.AlignmentFlag.AlignCenter),
        ("trait", "Trait", 110, Qt.AlignmentFlag.AlignCenter),
    ]

    def __init__(
        self,
        parent: Optional[QWidget],
        business_name: str,
        applicant_factory: Callable[[], List[Dict[str, Any]]],
    ) -> None:
        super().__init__(parent, f"Hire — {business_name}")
        self._applicant_factory = applicant_factory
        self._business_name = business_name
        self._applicants: List[Dict[str, Any]] = []
        self._selected: Optional[Dict[str, Any]] = None
        self.resize(UIScale.px(820), UIScale.px(460))

        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )
        intro = QLabel(
            f"Review applicants for {business_name}. Double-click a row to hire immediately, or refresh for a new slate.",
            self._body,
        )
        intro.setFont(Fonts.mixed)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(intro)

        split = QSplitter(Qt.Orientation.Horizontal, self._body)
        split.setChildrenCollapsible(False)

        left = QWidget(split)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(UIScale.px(8))
        self._table = DataTable(left, self._COLS, row_height=28, stretch_last=False)
        self._table.row_selected.connect(self._on_select)
        self._table.row_double_clicked.connect(lambda _row: self._accept())
        left_lay.addWidget(self._table, 1)

        right = QFrame(split)
        right.setObjectName("dashPanel")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(UIScale.px(12), UIScale.px(12), UIScale.px(12), UIScale.px(12))
        right_lay.setSpacing(UIScale.px(8))
        self._name_lbl = QLabel("Select an applicant", right)
        self._name_lbl.setFont(Fonts.title)
        self._name_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        right_lay.addWidget(self._name_lbl)
        self._summary_lbl = QLabel("", right)
        self._summary_lbl.setFont(Fonts.mono_small)
        self._summary_lbl.setWordWrap(True)
        self._summary_lbl.setStyleSheet(f"color:{P.cream}; background:transparent;")
        right_lay.addWidget(self._summary_lbl)
        self._detail_lbl = QLabel(
            "Productivity multiplies daily output. Wage is deducted each day from business income.",
            right,
        )
        self._detail_lbl.setFont(Fonts.mixed_small)
        self._detail_lbl.setWordWrap(True)
        self._detail_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        right_lay.addWidget(self._detail_lbl)
        right_lay.addStretch()

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        btns = QHBoxLayout()
        refresh_btn = MtButton("New Applicants", self._body, role="secondary")
        refresh_btn.clicked.connect(self._refresh_applicants)
        cancel_btn = MtButton("Cancel", self._body, role="secondary")
        cancel_btn.clicked.connect(self.reject)
        hire_btn = MtButton("Hire Selected", self._body)
        hire_btn.clicked.connect(self._accept)
        btns.addWidget(refresh_btn)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(hire_btn)
        root.addLayout(btns)

        self._refresh_applicants()
        self.center_on_parent()

    def _refresh_applicants(self) -> None:
        self._applicants = list(self._applicant_factory())
        rows: List[Dict[str, Any]] = []
        for idx, applicant in enumerate(self._applicants, 1):
            productivity = float(applicant.get("productivity", 1.0) or 1.0)
            wage = float(applicant.get("wage", 0.0) or 0.0)
            trait = str(applicant.get("trait", "Average"))
            tag = (
                "green" if productivity >= 1.15 else
                ("red" if productivity <= 0.90 or wage >= 10.5 else "gold")
            )
            rows.append({
                "name": applicant.get("name", f"Applicant {idx}"),
                "wage": f"{wage:.1f}g",
                "prod": f"{productivity:.2f}×",
                "trait": trait,
                "applicant_idx": idx - 1,
                "_tag": tag,
            })
        self._selected = None
        self._table.load(rows)
        self._on_select(rows[0] if rows else {})

    def _on_select(self, row: Dict[str, Any]) -> None:
        idx = row.get("applicant_idx") if row else None
        applicant = self._applicants[idx] if isinstance(idx, int) and 0 <= idx < len(self._applicants) else None
        self._selected = applicant
        if applicant is None:
            self._name_lbl.setText("Select an applicant")
            self._summary_lbl.setText("")
            self._detail_lbl.setText("Productivity multiplies daily output. Wage is deducted each day from business income.")
            return
        productivity = float(applicant.get("productivity", 1.0) or 1.0)
        wage = float(applicant.get("wage", 0.0) or 0.0)
        trait = str(applicant.get("trait", "Average"))
        verdict = (
            "Strong producer with premium output." if productivity >= 1.15 else
            ("Budget hire with weaker output." if productivity <= 0.90 else "Balanced all-round worker.")
        )
        self._name_lbl.setText(str(applicant.get("name", "Applicant")))
        self._summary_lbl.setText(
            f"Wage: {wage:.1f}g/day\n"
            f"Productivity: {productivity:.2f}×\n"
            f"Trait: {trait}"
        )
        self._detail_lbl.setText(verdict)

    def _accept(self) -> None:
        if self._selected is None:
            return
        self.accept()

    def choose(self) -> Optional[Dict[str, Any]]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return self._selected


class CaptainHireDialog(AppDialog):
    _COLS = [
        ("name", "Captain", 160),
        ("title", "Title", 90, Qt.AlignmentFlag.AlignCenter),
        ("nav", "Nav", 50, Qt.AlignmentFlag.AlignCenter),
        ("com", "Combat", 62, Qt.AlignmentFlag.AlignCenter),
        ("sea", "Sea", 52, Qt.AlignmentFlag.AlignCenter),
        ("cha", "Charm", 62, Qt.AlignmentFlag.AlignCenter),
        ("wage", "Voyage Wage", 96, Qt.AlignmentFlag.AlignCenter),
    ]

    def __init__(self, parent: Optional[QWidget], captains: List[Captain]) -> None:
        super().__init__(parent, "Hire Captain")
        self._captains = list(captains)
        self._selected: Optional[Captain] = None
        self.resize(UIScale.px(900), UIScale.px(460))

        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )
        intro = QLabel(
            "Review the available captains. Double-click a row to hire immediately, or select one and use Hire Selected.",
            self._body,
        )
        intro.setFont(Fonts.mixed)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(intro)

        split = QSplitter(Qt.Orientation.Horizontal, self._body)
        split.setChildrenCollapsible(False)

        left = QWidget(split)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        self._table = DataTable(left, self._COLS, row_height=28, stretch_last=False)
        self._table.row_selected.connect(self._on_select)
        self._table.row_double_clicked.connect(lambda _row: self._accept())
        left_lay.addWidget(self._table)

        right = QFrame(split)
        right.setObjectName("dashPanel")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(UIScale.px(12), UIScale.px(12), UIScale.px(12), UIScale.px(12))
        right_lay.setSpacing(UIScale.px(8))
        self._name_lbl = QLabel("Select a captain", right)
        self._name_lbl.setFont(Fonts.title)
        self._name_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        right_lay.addWidget(self._name_lbl)
        self._detail_lbl = QLabel("", right)
        self._detail_lbl.setFont(Fonts.mono_small)
        self._detail_lbl.setWordWrap(True)
        self._detail_lbl.setStyleSheet(f"color:{P.cream}; background:transparent;")
        right_lay.addWidget(self._detail_lbl)
        self._notes_lbl = QLabel("Navigation shortens routes. Combat and seamanship reduce voyage loss risk. Charisma improves final payout.", right)
        self._notes_lbl.setFont(Fonts.mixed_small)
        self._notes_lbl.setWordWrap(True)
        self._notes_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        right_lay.addWidget(self._notes_lbl)
        right_lay.addStretch()

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        rows: List[Dict[str, Any]] = []
        for idx, captain in enumerate(self._captains):
            rows.append({
                "name": captain.name,
                "title": captain.title,
                "nav": str(captain.navigation),
                "com": str(captain.combat),
                "sea": str(captain.seamanship),
                "cha": str(captain.charisma),
                "wage": f"{captain.wage_per_voyage:.0f}g",
                "captain_idx": idx,
                "_tag": "gold" if captain.navigation >= 4 else "green",
            })
        self._table.load(rows)
        self._on_select(rows[0] if rows else {})

        btns = QHBoxLayout()
        cancel_btn = MtButton("Cancel", self._body, role="secondary")
        cancel_btn.clicked.connect(self.reject)
        hire_btn = MtButton("Hire Selected", self._body)
        hire_btn.clicked.connect(self._accept)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(hire_btn)
        root.addLayout(btns)

        self.center_on_parent()

    def _on_select(self, row: Dict[str, Any]) -> None:
        idx = row.get("captain_idx") if row else None
        captain = self._captains[idx] if isinstance(idx, int) and 0 <= idx < len(self._captains) else None
        self._selected = captain
        if captain is None:
            self._name_lbl.setText("Select a captain")
            self._detail_lbl.setText("")
            return
        self._name_lbl.setText(f"{captain.title} {captain.name}")
        self._detail_lbl.setText(
            f"Navigation: {captain.navigation}  ·  Combat: {captain.combat}  ·  Seamanship: {captain.seamanship}  ·  Charisma: {captain.charisma}\n"
            f"Voyage wage: {captain.wage_per_voyage:.0f}g  ·  Crew wage: {captain.crew_wage:.0f}g each\n"
            f"Route time: -{captain.day_reduction:.0%}  ·  Piracy: ×{captain.piracy_mult:.2f}  ·  Wreck: ×{captain.wreck_mult:.2f}  ·  Profit: ×{captain.profit_mult:.2f}"
        )

    def _accept(self) -> None:
        if self._selected is None:
            return
        self.accept()

    def choose(self) -> Optional[Captain]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return self._selected


class VoyageCargoDialog(AppDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        cargo_capacity: int,
        inventory_rows: List[Tuple[str, int]],
        port_name: str,
        profit_mult: Dict[str, float],
    ) -> None:
        super().__init__(parent, f"Load Cargo — {port_name}")
        self.resize(UIScale.px(980), UIScale.px(620))
        self._capacity = max(0, cargo_capacity)
        self._selected: Dict[str, int] = {}
        self._row_widgets: Dict[str, Dict[str, Any]] = {}
        self._syncing = False

        sorted_rows = sorted(
            inventory_rows,
            key=lambda pair: (
                -profit_mult.get(getattr(ALL_ITEMS.get(pair[0]), "category", ItemCategory.RAW_MATERIAL).name, 1.0),
                getattr(ALL_ITEMS.get(pair[0]), "name", pair[0]).lower(),
            ),
        )

        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )
        intro = QLabel(
            "Set cargo amounts with the sliders. The manifest updates live and stops at the ship's cargo limit.",
            self._body,
        )
        intro.setFont(Fonts.mixed)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(intro)

        self._summary_lbl = QLabel("", self._body)
        self._summary_lbl.setFont(Fonts.mono_small)
        self._summary_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        root.addWidget(self._summary_lbl)

        scroll = QScrollArea(self._body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background:transparent; border:none;")
        inner = QWidget(scroll)
        grid = QGridLayout(inner)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(UIScale.px(10))
        grid.setVerticalSpacing(UIScale.px(6))

        headers = ["Item", "Have", "Category", "Base", "Port Mult", "Load", "Selected"]
        for col, title in enumerate(headers):
            hdr = QLabel(title, inner)
            hdr.setFont(Fonts.mixed_small_bold)
            hdr.setStyleSheet(f"color:{P.amber}; background:transparent;")
            hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(hdr, 0, col)

        for row_idx, (item_key, available_qty) in enumerate(sorted_rows, 1):
            item = ALL_ITEMS.get(item_key)
            if item is None:
                continue
            category_name = item.category.name.replace("_", " ").title()
            dest_mult = profit_mult.get(item.category.name, 1.0)

            name_lbl = QLabel(item.name, inner)
            name_lbl.setFont(Fonts.mixed_small)
            name_lbl.setStyleSheet(f"color:{P.cream}; background:transparent;")
            grid.addWidget(name_lbl, row_idx, 0)

            have_lbl = QLabel(str(available_qty), inner)
            have_lbl.setFont(Fonts.mono_small)
            have_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            have_lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
            grid.addWidget(have_lbl, row_idx, 1)

            cat_lbl = QLabel(category_name, inner)
            cat_lbl.setFont(Fonts.mixed_small)
            cat_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cat_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
            grid.addWidget(cat_lbl, row_idx, 2)

            base_lbl = QLabel(f"{item.base_price:.0f}g", inner)
            base_lbl.setFont(Fonts.mono_small)
            base_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            base_lbl.setStyleSheet(f"color:{P.cream}; background:transparent;")
            grid.addWidget(base_lbl, row_idx, 3)

            mult_col = P.green if dest_mult > 1.0 else (P.red if dest_mult < 1.0 else P.fg_dim)
            mult_lbl = QLabel(f"×{dest_mult:.1f}", inner)
            mult_lbl.setFont(Fonts.mono_small)
            mult_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            mult_lbl.setStyleSheet(f"color:{mult_col}; background:transparent;")
            grid.addWidget(mult_lbl, row_idx, 4)

            control = QWidget(inner)
            control_lay = QHBoxLayout(control)
            control_lay.setContentsMargins(0, 0, 0, 0)
            control_lay.setSpacing(UIScale.px(6))
            slider = QSlider(Qt.Orientation.Horizontal, control)
            slider.setMinimum(0)
            slider.setMaximum(available_qty)
            slider.setValue(0)
            spin = QSpinBox(control)
            spin.setMinimum(0)
            spin.setMaximum(available_qty)
            spin.setValue(0)
            spin.setFixedWidth(UIScale.px(72))
            slider.valueChanged.connect(lambda value, key=item_key: self._set_value(key, value, source="slider"))
            spin.valueChanged.connect(lambda value, key=item_key: self._set_value(key, value, source="spin"))
            control_lay.addWidget(slider, 1)
            control_lay.addWidget(spin)
            grid.addWidget(control, row_idx, 5)

            selected_lbl = QLabel("0", inner)
            selected_lbl.setFont(Fonts.mono_small)
            selected_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            selected_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
            grid.addWidget(selected_lbl, row_idx, 6)

            self._row_widgets[item_key] = {
                "slider": slider,
                "spin": spin,
                "selected": selected_lbl,
                "available": available_qty,
            }
            self._selected[item_key] = 0

        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(5, 3)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        self._error_lbl = QLabel("", self._body)
        self._error_lbl.setFont(Fonts.mixed_small)
        self._error_lbl.setStyleSheet(f"color:{P.red}; background:transparent;")
        root.addWidget(self._error_lbl)

        btns = QHBoxLayout()
        clear_btn = MtButton("Clear All", self._body, role="secondary")
        clear_btn.clicked.connect(self._clear_all)
        cancel_btn = MtButton("Cancel", self._body, role="secondary")
        cancel_btn.clicked.connect(self.reject)
        load_btn = MtButton("Load Cargo", self._body)
        load_btn.clicked.connect(self._accept)
        btns.addWidget(clear_btn)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(load_btn)
        root.addLayout(btns)

        self._update_summary()
        self.center_on_parent()

    def _used_capacity(self) -> int:
        return sum(self._selected.values())

    def _selected_cost(self) -> float:
        return round(sum((ALL_ITEMS[item_key].base_price * qty) for item_key, qty in self._selected.items() if qty > 0 and item_key in ALL_ITEMS), 2)

    def _set_value(self, item_key: str, value: int, source: str) -> None:
        if self._syncing or item_key not in self._row_widgets:
            return
        prev = self._selected.get(item_key, 0)
        used_without_current = self._used_capacity() - prev
        clamped = min(max(0, int(value)), max(0, self._capacity - used_without_current), self._row_widgets[item_key]["available"])
        self._selected[item_key] = clamped
        self._syncing = True
        try:
            if source != "slider":
                self._row_widgets[item_key]["slider"].setValue(clamped)
            if source != "spin":
                self._row_widgets[item_key]["spin"].setValue(clamped)
            self._row_widgets[item_key]["selected"].setText(str(clamped))
        finally:
            self._syncing = False
        if clamped != value:
            self._error_lbl.setText("Cargo capped at ship capacity.")
        else:
            self._error_lbl.setText("")
        self._update_summary()

    def _clear_all(self) -> None:
        self._error_lbl.setText("")
        self._syncing = True
        try:
            for item_key, widgets in self._row_widgets.items():
                self._selected[item_key] = 0
                widgets["slider"].setValue(0)
                widgets["spin"].setValue(0)
                widgets["selected"].setText("0")
        finally:
            self._syncing = False
        self._update_summary()

    def _update_summary(self) -> None:
        used = self._used_capacity()
        remaining = max(0, self._capacity - used)
        self._summary_lbl.setText(
            f"Manifest: {used}/{self._capacity} units  ·  Remaining: {remaining}  ·  Estimated cargo value: {self._selected_cost():,.0f}g"
        )

    def _accept(self) -> None:
        if self._used_capacity() <= 0:
            self._error_lbl.setText("Load at least one item before launching.")
            return
        self.accept()

    def choose(self) -> Tuple[Dict[str, int], float, bool]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return {}, 0.0, False
        cargo = {item_key: qty for item_key, qty in self._selected.items() if qty > 0}
        return cargo, self._selected_cost(), bool(cargo)


_TENANT_RELIABILITY: List[Tuple[str, str, str, Tuple[float, float]]] = [
    ("Excellent", "Reliable payer, keeps the property well.", P.green, (1.08, 1.22)),
    ("Good", "Generally dependable, occasional minor delay.", P.gold, (1.00, 1.10)),
    ("Average", "Pays on time most months.", P.fg, (0.92, 1.02)),
    ("Risky", "May be late with payments some months.", P.amber, (0.80, 0.94)),
    ("Troublesome", "History of payment issues; expect friction.", P.red, (0.70, 0.86)),
]

_TENANT_FIRST = [
    "Aldric", "Bram", "Cora", "Dag", "Elra", "Finn", "Greta", "Holt", "Isa", "Jorin",
    "Kev", "Lena", "Mira", "Ned", "Ora", "Pip", "Quinn", "Rolf", "Sable", "Tilda",
    "Ulf", "Vera", "Wren", "Xan", "Yara", "Zane",
]

_TENANT_LAST = [
    "Miller", "Cooper", "Smith", "Tanner", "Fisher", "Brewer", "Mason", "Wright",
    "Fletcher", "Barrow", "Cotter", "Dyer", "Galloway", "Hayward", "Saltmarsh", "Underhill",
]


def _generate_lease_applicants(daily_rate: float, count: int = 3) -> List[Dict[str, Any]]:
    applicants: List[Dict[str, Any]] = []
    for _ in range(count):
        reliability, desc, color, rate_range = random.choice(_TENANT_RELIABILITY)
        rate_mult = round(random.uniform(*rate_range), 2)
        applicants.append({
            "name": f"{random.choice(_TENANT_FIRST)} {random.choice(_TENANT_LAST)}",
            "reliability": reliability,
            "desc": desc,
            "rate_mult": rate_mult,
            "daily_rate": round(daily_rate * rate_mult, 2),
            "color": color,
        })
    return applicants


class LeaseApplicantDialog(AppDialog):
    _COLS = [
        ("name", "Applicant", 170),
        ("reliability", "Reliability", 100),
        ("rate", "Offer/day", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("mult", "Rate %", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]

    def __init__(self, parent: Optional[QWidget], property_name: str, daily_rate: float) -> None:
        super().__init__(parent, f"Lease {property_name}")
        self._selected: Optional[Dict[str, Any]] = None
        self._applicants = _generate_lease_applicants(daily_rate, 3)
        self.resize(UIScale.px(720), UIScale.px(440))

        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )
        intro = QLabel(
            f"Review prospective tenants for {property_name}. Higher offers usually mean higher tenant risk.",
            self._body,
        )
        intro.setFont(Fonts.mixed)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(intro)

        split = QSplitter(Qt.Orientation.Horizontal, self._body)
        split.setChildrenCollapsible(False)

        left = QWidget(split)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        self._table = DataTable(left, self._COLS, row_height=28)
        self._table.row_selected.connect(self._on_select)
        self._table.row_double_clicked.connect(lambda _row: self._accept())
        left_lay.addWidget(self._table)

        right = QFrame(split)
        right.setObjectName("dashPanel")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(UIScale.px(12), UIScale.px(12), UIScale.px(12), UIScale.px(12))
        right_lay.setSpacing(UIScale.px(8))
        self._name_lbl = QLabel("Select an applicant", right)
        self._name_lbl.setFont(Fonts.title)
        self._name_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        right_lay.addWidget(self._name_lbl)
        self._detail_lbl = QLabel("Choose a tenant on the left to inspect the lease offer.", right)
        self._detail_lbl.setFont(Fonts.mixed_small)
        self._detail_lbl.setWordWrap(True)
        self._detail_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        right_lay.addWidget(self._detail_lbl, 1)
        self._status_lbl = QLabel("", right)
        self._status_lbl.setFont(Fonts.mixed_bold)
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(f"color:{P.amber}; background:transparent;")
        right_lay.addWidget(self._status_lbl)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        btns = QHBoxLayout()
        cancel_btn = MtButton("Cancel", self._body, role="secondary")
        cancel_btn.clicked.connect(self.reject)
        self._accept_btn = MtButton("Lease to Selected Tenant", self._body)
        self._accept_btn.setEnabled(False)
        self._accept_btn.clicked.connect(self._accept)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(self._accept_btn)
        root.addLayout(btns)

        rows: List[Dict[str, Any]] = []
        for idx, applicant in enumerate(self._applicants):
            rows.append({
                "name": applicant["name"],
                "reliability": applicant["reliability"],
                "rate": f"{applicant['daily_rate']:.2f}g",
                "mult": f"{applicant['rate_mult'] * 100:.0f}%",
                "applicant_index": idx,
                "_tag": "green" if applicant["rate_mult"] >= 1.0 else ("yellow" if applicant["rate_mult"] >= 0.9 else "red"),
            })
        self._table.load(rows)
        self.center_on_parent()

    def _on_select(self, row: Dict[str, Any]) -> None:
        idx = row.get("applicant_index") if row else None
        if not isinstance(idx, int) or not (0 <= idx < len(self._applicants)):
            return
        applicant = self._applicants[idx]
        self._selected = applicant
        self._name_lbl.setText(applicant["name"])
        self._detail_lbl.setText(
            f"Reliability: {applicant['reliability']}\n"
            f"Offer: {applicant['daily_rate']:.2f}g/day ({applicant['rate_mult'] * 100:.0f}% of standard rate)\n\n"
            f"{applicant['desc']}"
        )
        self._status_lbl.setText(
            "Higher-rate tenants can juice short-term income, but safer applicants are better for stable property cashflow."
        )
        self._status_lbl.setStyleSheet(f"color:{applicant['color']}; background:transparent;")
        self._accept_btn.setEnabled(True)

    def _accept(self) -> None:
        if self._selected is None:
            return
        self.accept()

    def choose(self) -> Optional[Dict[str, Any]]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return self._selected


class BuildProjectDialog(AppDialog):
    _COLS = [
        ("name", "Project", 150),
        ("cost", "Cost", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("days", "Build Days", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("value", "Finished Value", 110, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("lease", "Lease/day", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]

    def __init__(self, parent: Optional[QWidget], title: str, buildable: List[str], area_mult: float) -> None:
        super().__init__(parent, title)
        self._selected_key: Optional[str] = None
        self._buildable = buildable
        self._area_mult = area_mult
        self.resize(UIScale.px(760), UIScale.px(470))

        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )
        intro = QLabel(
            "Choose a construction project. Values shown reflect the current region multiplier and baseline economics.",
            self._body,
        )
        intro.setFont(Fonts.mixed)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(intro)

        split = QSplitter(Qt.Orientation.Horizontal, self._body)
        split.setChildrenCollapsible(False)
        left = QWidget(split)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        self._table = DataTable(left, self._COLS, row_height=28)
        self._table.row_selected.connect(self._on_select)
        self._table.row_double_clicked.connect(lambda _row: self._accept())
        left_lay.addWidget(self._table)

        right = QFrame(split)
        right.setObjectName("dashPanel")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(UIScale.px(12), UIScale.px(12), UIScale.px(12), UIScale.px(12))
        self._name_lbl = QLabel("Select a project", right)
        self._name_lbl.setFont(Fonts.title)
        self._name_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        right_lay.addWidget(self._name_lbl)
        self._detail_lbl = QLabel("Choose a project on the left to inspect its cost, build time, and finished yield.", right)
        self._detail_lbl.setFont(Fonts.mixed_small)
        self._detail_lbl.setWordWrap(True)
        self._detail_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        right_lay.addWidget(self._detail_lbl, 1)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        btns = QHBoxLayout()
        cancel_btn = MtButton("Cancel", self._body, role="secondary")
        cancel_btn.clicked.connect(self.reject)
        self._accept_btn = MtButton("Start Construction", self._body)
        self._accept_btn.setEnabled(False)
        self._accept_btn.clicked.connect(self._accept)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(self._accept_btn)
        root.addLayout(btns)

        rows: List[Dict[str, Any]] = []
        for key in buildable:
            cat = PROPERTY_CATALOGUE.get(key, {})
            rows.append({
                "name": cat.get("name", key.title()),
                "cost": f"{round(cat.get('build_cost', 0) * area_mult):,.0f}g",
                "days": str(cat.get("build_days", 0)),
                "value": f"{round(cat.get('base_value', 0) * area_mult):,.0f}g",
                "lease": f"{cat.get('base_lease', 0) * area_mult:.1f}g",
                "project_key": key,
                "_tag": "cyan",
            })
        self._table.load(rows)
        self.center_on_parent()

    def _on_select(self, row: Dict[str, Any]) -> None:
        key = row.get("project_key") if row else None
        if not isinstance(key, str):
            return
        cat = PROPERTY_CATALOGUE.get(key, {})
        self._selected_key = key
        self._name_lbl.setText(cat.get("name", key.title()))
        self._detail_lbl.setText(
            f"Build cost: {round(cat.get('build_cost', 0) * self._area_mult):,.0f}g\n"
            f"Duration: {cat.get('build_days', 0)} days\n"
            f"Finished value: ~{round(cat.get('base_value', 0) * self._area_mult):,.0f}g\n"
            f"Lease potential: ~{cat.get('base_lease', 0) * self._area_mult:.1f}g/day\n\n"
            f"Area restriction: {', '.join(cat.get('areas', [])) if cat.get('areas') else 'None'}"
        )
        self._accept_btn.setEnabled(True)

    def _accept(self) -> None:
        if self._selected_key is None:
            return
        self.accept()

    def choose(self) -> Optional[str]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return self._selected_key


class ManagerConfigDialog(AppDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        manager: HiredManager,
        fields: List[Dict[str, Any]],
    ) -> None:
        super().__init__(parent, f"Configure {manager.name}")
        self._fields = fields
        self._widgets: Dict[str, QWidget] = {}
        self._config = manager.config
        self.resize(UIScale.px(620), UIScale.px(520))

        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )
        intro = QLabel(
            f"Adjust automation rules for {manager.manager_type}. Changes are saved to this manager immediately.",
            self._body,
        )
        intro.setFont(Fonts.mixed)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(intro)

        form = QGridLayout()
        form.setHorizontalSpacing(UIScale.px(10))
        form.setVerticalSpacing(UIScale.px(8))

        row_idx = 0
        for field in fields:
            key = field["key"]
            kind = field.get("kind", "float")
            note = field.get("note", "")
            if kind == "bool":
                cb = QCheckBox(field["label"], self._body)
                cb.setChecked(bool(self._config.get(key, field.get("default", False))))
                cb.setFont(Fonts.mixed_small_bold)
                cb.setStyleSheet(f"color:{P.fg_header}; background:transparent;")
                form.addWidget(cb, row_idx, 0, 1, 2)
                self._widgets[key] = cb
                row_idx += 1
            else:
                lbl = QLabel(field["label"], self._body)
                lbl.setFont(Fonts.mixed_small)
                lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
                form.addWidget(lbl, row_idx, 0)
                if kind == "choice":
                    combo = QComboBox(self._body)
                    combo.setFont(Fonts.mixed_small)
                    for option in field.get("options", []):
                        combo.addItem(str(option), option)
                    current = self._config.get(key, field.get("default"))
                    current_idx = combo.findData(current)
                    combo.setCurrentIndex(max(0, current_idx))
                    self._widgets[key] = combo
                    form.addWidget(combo, row_idx, 1)
                else:
                    edit = QLineEdit(self._body)
                    edit.setFont(Fonts.mono_small)
                    edit.setText(str(self._config.get(key, field.get("default", ""))))
                    self._widgets[key] = edit
                    form.addWidget(edit, row_idx, 1)
                row_idx += 1
            if note:
                note_lbl = QLabel(note, self._body)
                note_lbl.setFont(Fonts.tiny)
                note_lbl.setWordWrap(True)
                note_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
                form.addWidget(note_lbl, row_idx, 0, 1, 2)
                row_idx += 1

        root.addLayout(form, 1)

        self._status_lbl = QLabel("", self._body)
        self._status_lbl.setFont(Fonts.mixed_small)
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(f"color:{P.red}; background:transparent;")
        root.addWidget(self._status_lbl)

        btns = QHBoxLayout()
        cancel_btn = MtButton("Cancel", self._body, role="secondary")
        cancel_btn.clicked.connect(self.reject)
        save_btn = MtButton("Save Configuration", self._body)
        save_btn.clicked.connect(self._save)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)
        root.addLayout(btns)

        self.center_on_parent()

    def _save(self) -> None:
        updated: Dict[str, Any] = {}
        try:
            for field in self._fields:
                key = field["key"]
                kind = field.get("kind", "float")
                widget = self._widgets[key]
                if kind == "bool":
                    updated[key] = bool(widget.isChecked())
                elif kind == "choice":
                    updated[key] = widget.currentData()
                elif kind == "int":
                    updated[key] = int(str(widget.text()).strip())
                else:
                    value = float(str(widget.text()).strip())
                    if field.get("clamp"):
                        lo, hi = field["clamp"]
                        value = max(lo, min(hi, value))
                    updated[key] = value
        except ValueError:
            self._status_lbl.setText("One or more values are invalid. Use numeric values where required.")
            return

        self._config.update(updated)
        self.accept()


class BusinessPurchaseDialog(AppDialog):
    _COLS = [
        ("name", "Business", 220),
        ("area", "Area", 120),
        ("buy", "Buy", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("output", "Produces", 130),
        ("rate", "Prod/day", 74, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("opex", "Cost/day", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("net", "Net/day", 84, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]

    def __init__(self, parent: "BusinessesScreen") -> None:
        self._screen = parent
        self._selected_key: Optional[str] = None
        self._all_rows: List[Dict[str, Any]] = []
        super().__init__(parent, "Purchase Business")
        self.resize(UIScale.px(980), UIScale.px(620))

        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )

        top = QHBoxLayout()
        intro = QLabel(
            "Review available businesses by region, output, and expected operating margin before committing capital.",
            self._body,
        )
        intro.setFont(Fonts.mixed)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{P.fg}; background:transparent;")
        top.addWidget(intro, 1)
        self._gold_lbl = QLabel(self._body)
        self._gold_lbl.setFont(Fonts.mono)
        self._gold_lbl.setStyleSheet(f"color:{P.amber}; background:transparent;")
        top.addWidget(self._gold_lbl)
        root.addLayout(top)

        search_row = QHBoxLayout()
        search_lbl = QLabel("Filter", self._body)
        search_lbl.setFont(Fonts.mixed_small)
        search_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        self._search = QLineEdit(self._body)
        self._search.setPlaceholderText("Search by business, product, or area")
        self._search.textChanged.connect(self._apply_filter)
        search_row.addWidget(search_lbl)
        search_row.addWidget(self._search, 1)
        root.addLayout(search_row)

        split = QSplitter(Qt.Orientation.Horizontal, self._body)
        split.setChildrenCollapsible(False)

        left = QWidget(split)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(UIScale.px(8))
        self._table = DataTable(left, self._COLS, row_height=28)
        self._table.row_selected.connect(self._on_select)
        self._table.row_double_clicked.connect(lambda _row: self._accept_selection())
        left_lay.addWidget(self._table, 1)

        right = QFrame(split)
        right.setObjectName("dashPanel")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(UIScale.px(12), UIScale.px(12), UIScale.px(12), UIScale.px(12))
        right_lay.setSpacing(UIScale.px(8))

        self._name_lbl = QLabel("Select a business", right)
        self._name_lbl.setFont(Fonts.title)
        self._name_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        right_lay.addWidget(self._name_lbl)

        self._summary_lbl = QLabel("", right)
        self._summary_lbl.setFont(Fonts.mono_small)
        self._summary_lbl.setWordWrap(True)
        self._summary_lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        right_lay.addWidget(self._summary_lbl)

        self._detail_lbl = QLabel("Choose a listing on the left to inspect its economics and production profile.", right)
        self._detail_lbl.setFont(Fonts.mixed_small)
        self._detail_lbl.setWordWrap(True)
        self._detail_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        right_lay.addWidget(self._detail_lbl, 1)

        self._status_lbl = QLabel("", right)
        self._status_lbl.setFont(Fonts.mixed_bold)
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(f"color:{P.amber}; background:transparent;")
        right_lay.addWidget(self._status_lbl)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        btns = QHBoxLayout()
        cancel_btn = MtButton("Cancel", self._body, role="secondary")
        cancel_btn.clicked.connect(self.reject)
        self._buy_btn = MtButton(f"{Sym.YES}  Purchase Business", self._body)
        self._buy_btn.setEnabled(False)
        self._buy_btn.clicked.connect(self._accept_selection)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(self._buy_btn)
        root.addLayout(btns)

        self._load_rows()
        self.center_on_parent()

    def _load_rows(self) -> None:
        gold = float(self._screen.game.inventory.gold)
        self._gold_lbl.setText(f"Available Gold: {gold:,.0f}g")
        rows: List[Dict[str, Any]] = []
        for key, data in BUSINESS_CATALOGUE.items():
            item = ALL_ITEMS.get(data["item"])
            item_name = item.name if item else data["item"]
            base_price = float(item.base_price) if item else 0.0
            gross = base_price * float(data["rate"])
            net = gross - float(data["cost"])
            search = f"{data['name']} {data['area'].value} {item_name}".lower()
            rows.append({
                "name": data["name"],
                "area": data["area"].value,
                "buy": f"{float(data['buy']):.0f}g",
                "output": item_name,
                "rate": str(data["rate"]),
                "opex": f"{float(data['cost']):.0f}g",
                "net": f"{net:+.0f}g",
                "biz_key": key,
                "gross_num": gross,
                "net_num": net,
                "cost_num": float(data["buy"]),
                "search": search,
                "_tag": "green" if gold >= float(data["buy"]) else "red",
            })
        self._all_rows = rows
        self._apply_filter("")

    def _apply_filter(self, text: str) -> None:
        query = (text or "").strip().lower()
        rows = [row for row in self._all_rows if not query or query in row.get("search", "")]
        self._table.load(rows)
        self._buy_btn.setEnabled(False)
        if not rows:
            self._name_lbl.setText("No matching businesses")
            self._summary_lbl.setText("")
            self._detail_lbl.setText("Try a different filter term.")
            self._status_lbl.setText("")

    def _on_select(self, row: Dict[str, Any]) -> None:
        key = row.get("biz_key") if row else None
        if not isinstance(key, str) or key not in BUSINESS_CATALOGUE:
            return
        data = BUSINESS_CATALOGUE[key]
        gold = float(self._screen.game.inventory.gold)
        item = ALL_ITEMS.get(data["item"])
        item_name = item.name if item else data["item"]
        gross = float(row.get("gross_num", 0.0))
        net = float(row.get("net_num", 0.0))
        cost = float(row.get("cost_num", 0.0))
        payback = cost / net if net > 0 else None
        self._name_lbl.setText(f"{data['name']}  ·  {data['area'].value}")
        self._summary_lbl.setText(
            f"Buy-in {cost:,.0f}g  ·  Produces {data['rate']}/day {item_name}\n"
            f"Estimated gross {gross:,.0f}g/day  ·  Operating cost {float(data['cost']):,.0f}g/day"
        )
        self._detail_lbl.setText(
            f"This site produces {item_name} in {data['area'].value}. Net operating margin is roughly {net:+,.0f}g/day "
            f"before wider market swings and staffing modifiers."
            + (f"\nEstimated payback: about {payback:.1f} days of operation." if payback is not None else "\nEstimated payback: unprofitable at baseline pricing.")
        )
        if gold >= cost:
            self._status_lbl.setText(f"Affordable now. Wallet after purchase: {gold - cost:,.0f}g")
            self._status_lbl.setStyleSheet(f"color:{P.green}; background:transparent;")
            self._buy_btn.setEnabled(True)
        else:
            self._status_lbl.setText(f"Need {cost - gold:,.0f}g more to purchase this business.")
            self._status_lbl.setStyleSheet(f"color:{P.red}; background:transparent;")
            self._buy_btn.setEnabled(False)

    def _accept_selection(self) -> None:
        row = self._table.selected()
        key = row.get("biz_key") if row else None
        cost = float(row.get("cost_num", 0.0)) if row else 0.0
        if not isinstance(key, str):
            return
        if self._screen.game.inventory.gold < cost:
            self._status_lbl.setText(f"Need {cost - self._screen.game.inventory.gold:,.0f}g more to purchase this business.")
            self._status_lbl.setStyleSheet(f"color:{P.red}; background:transparent;")
            return
        self._selected_key = key
        self.accept()

    def choose(self) -> Optional[str]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return self._selected_key


def _popup_confirm(
    parent: Optional[QWidget],
    title: str,
    message: str,
    *,
    confirm_text: str = "Confirm",
    cancel_text: str = "Cancel",
    confirm_role: str = "primary",
) -> bool:
    return ConfirmDialog(
        parent,
        title,
        message,
        confirm_text=confirm_text,
        cancel_text=cancel_text,
        confirm_role=confirm_role,
    ).ask()


def _popup_info(parent: Optional[QWidget], title: str, message: str) -> None:
    InfoDialog(parent, title, message).show_message()


def _popup_get_int(
    parent: Optional[QWidget],
    title: str,
    prompt: str,
    *,
    value: int,
    minimum: int,
    maximum: int,
    step: int = 1,
    confirm_text: str = "Confirm",
) -> Tuple[int, bool]:
    return IntegerPromptDialog(
        parent,
        title,
        prompt,
        value=value,
        minimum=minimum,
        maximum=maximum,
        step=step,
        confirm_text=confirm_text,
    ).get_value()


def _popup_get_text(
    parent: Optional[QWidget],
    title: str,
    prompt: str,
    *,
    default: str = "",
    placeholder: str = "",
    confirm_text: str = "Confirm",
) -> Optional[str]:
    return TextPromptDialog(
        parent,
        title,
        prompt,
        default=default,
        placeholder=placeholder,
        confirm_text=confirm_text,
    ).get_value()


def _popup_choose(
    parent: Optional[QWidget],
    title: str,
    prompt: str,
    items: List[str],
    *,
    confirm_text: str = "Select",
) -> Tuple[str, bool]:
    return ChoiceListDialog(parent, title, prompt, items, confirm_text=confirm_text).choose()


def _queue_ui(target: QObject, fn: Callable[[], None]) -> None:
    """Run *fn* on the target object's thread at the next event-loop turn."""
    QTimer.singleShot(0, target, fn)


class RegisterDialog(AppDialog):
    """Create-account dialog for the launch screen."""

    def __init__(self, app: "GameApp", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent or app, "Create Merchant Account")
        self._app = app
        self._result_message = ""
        self.setFixedWidth(UIScale.px(430))

        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )

        intro = QLabel(
            "Create an online merchant account to sync saves, climb the leaderboard, and use guilds and friends.",
            self._body,
        )
        intro.setFont(Fonts.mixed)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(intro)

        self._username = self._add_field(root, "Merchant Name")
        self._email = self._add_field(root, "Email Address")
        self._password = self._add_field(root, "Password", password=True)
        self._confirm = self._add_field(root, "Confirm Password", password=True)

        self._status = QLabel("", self._body)
        self._status.setFont(Fonts.mixed_small)
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color:{P.red}; background:transparent;")
        root.addWidget(self._status)

        btns = QHBoxLayout()
        cancel_btn = MtButton("Cancel", self._body, role="secondary")
        cancel_btn.clicked.connect(self.reject)
        self._create_btn = MtButton("Create Account", self._body)
        self._create_btn.clicked.connect(self._do_register)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(self._create_btn)
        root.addLayout(btns)

        self.center_on_parent()
        QTimer.singleShot(0, self._username.setFocus)

    def _add_field(self, layout: QVBoxLayout, label: str, password: bool = False) -> QLineEdit:
        lbl = QLabel(label, self._body)
        lbl.setFont(Fonts.mixed_small)
        lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        layout.addWidget(lbl)

        edit = QLineEdit(self._body)
        edit.setFont(Fonts.mixed_bold)
        if password:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(edit)
        return edit

    def _set_status(self, text: str, color: str = "") -> None:
        self._status.setText(text)
        self._status.setStyleSheet(f"color:{color or P.red}; background:transparent;")

    def _set_busy(self, busy: bool) -> None:
        self._create_btn.setEnabled(not busy)
        self._username.setEnabled(not busy)
        self._email.setEnabled(not busy)
        self._password.setEnabled(not busy)
        self._confirm.setEnabled(not busy)

    def _do_register(self) -> None:
        username = self._username.text().strip()
        email = self._email.text().strip()
        password = self._password.text()
        confirm = self._confirm.text()

        if not username:
            self._set_status("Please enter a merchant name.")
            return
        if not email or "@" not in email:
            self._set_status("Please enter a valid email address.")
            return
        if len(password) < 6:
            self._set_status("Password must be at least 6 characters.")
            return
        if password != confirm:
            self._set_status("Passwords do not match.")
            return
        if not self._app.online:
            self._set_status("Online services are unavailable.")
            return

        self._set_busy(True)
        self._set_status("Creating account…", P.fg_dim)

        redirect_url = ""
        if hasattr(self._app.online, "verification"):
            self._app.online.verification.start()
            redirect_url = self._app.online.verification.REDIRECT_URL

        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._handle_result(r))

        self._app.online.auth.sign_up(
            email,
            password,
            username,
            redirect_to=redirect_url,
            callback=_cb,
        )

    def _handle_result(self, res: Any) -> None:
        if not getattr(res, "success", False):
            msg = str(getattr(res, "error", "Registration failed.") or "Registration failed.")
            msg_lo = msg.lower()
            if "already registered" in msg_lo or "already exists" in msg_lo:
                msg = "An account with this email already exists."
            elif "invalid email" in msg_lo:
                msg = "Please enter a valid email address."
            elif "password" in msg_lo and ("weak" in msg_lo or "short" in msg_lo):
                msg = "Password is too weak. Use at least 8 characters."
            self._set_status(msg)
            self._set_busy(False)
            return

        action = (getattr(res, "data", None) or {}).get("action")
        if action == "confirm_email":
            self._result_message = "Account created. Check your inbox, confirm your email, then sign in here."
        else:
            self._result_message = "Account created. You can sign in now."
        self.accept()

    def outcome_message(self) -> str:
        return self._result_message


class BindSaveDialog(AppDialog):
    """Prompt to bind an unlinked local save to the signed-in account."""

    def __init__(self, parent: Optional[QWidget], username: str, unbound_day: int, unbound_gold: float) -> None:
        super().__init__(parent, f"Welcome, {username}!")
        self._choice = "fresh"
        self.setFixedWidth(UIScale.px(460))

        root = self.body_layout(
            margins=(UIScale.px(18), UIScale.px(16), UIScale.px(18), UIScale.px(18)),
            spacing=UIScale.px(10),
        )
        title = QLabel("An unlinked local save was found on this device.", self._body)
        title.setFont(Fonts.mixed_bold)
        title.setStyleSheet(f"color:{P.gold}; background:transparent;")
        root.addWidget(title)

        summary = QLabel(f"Day {unbound_day:,}  •  {unbound_gold:,.0f}g", self._body)
        summary.setFont(Fonts.mono)
        summary.setStyleSheet(f"color:{P.amber}; background:transparent;")
        root.addWidget(summary)

        warn = QLabel(
            "Linking copies this device save into your account-specific save slot. Future saves on this account will be bound to this profile.",
            self._body,
        )
        warn.setWordWrap(True)
        warn.setFont(Fonts.mixed_small)
        warn.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        root.addWidget(warn)

        btns = QHBoxLayout()
        bind_btn = MtButton("Link Existing Save", self._body)
        bind_btn.clicked.connect(lambda: self._pick("bind"))
        fresh_btn = MtButton("Start Fresh", self._body, role="danger")
        fresh_btn.clicked.connect(lambda: self._pick("fresh"))
        btns.addWidget(bind_btn)
        btns.addWidget(fresh_btn)
        btns.addStretch()
        root.addLayout(btns)

        self.center_on_parent()

    def _pick(self, value: str) -> None:
        self._choice = value
        self.accept()

    def choose(self) -> str:
        self.exec()
        return self._choice


class CloudSaveChoiceDialog(AppDialog):
    """Choose between local and cloud saves after sign-in."""

    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        username: str,
        local_day: int,
        local_ts: str,
        local_gold: float,
        cloud_day: int,
        cloud_ts: str,
        cloud_gold: float,
        local_newer: bool,
    ) -> None:
        super().__init__(parent, f"Welcome back, {username}!")
        self._choice: Optional[str] = None
        self.resize(UIScale.px(760), UIScale.px(360))

        root = self.body_layout(
            margins=(UIScale.px(18), UIScale.px(16), UIScale.px(18), UIScale.px(18)),
            spacing=UIScale.px(14),
        )
        intro = QLabel("Choose which progress you want to continue with.", self._body)
        intro.setFont(Fonts.mixed_bold)
        intro.setStyleSheet(f"color:{P.gold}; background:transparent;")
        root.addWidget(intro)

        cards = QHBoxLayout()
        cards.setSpacing(UIScale.px(14))
        cards.addWidget(self._build_card(
            "Local Save",
            local_day,
            local_gold,
            local_ts,
            local_newer,
            "local",
        ))
        cards.addWidget(self._build_card(
            "Cloud Save",
            cloud_day,
            cloud_gold,
            cloud_ts,
            not local_newer,
            "cloud",
        ))
        root.addLayout(cards)

        new_btn = MtButton("Start New Game Instead", self._body, role="danger")
        new_btn.clicked.connect(self.reject)
        root.addWidget(new_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self.center_on_parent()

    def _build_card(
        self,
        label: str,
        day: int,
        gold: float,
        stamp: str,
        newer: bool,
        value: str,
    ) -> QFrame:
        frame = QFrame(self._body)
        frame.setObjectName("dashPanel")
        frame.setStyleSheet(
            f"QFrame#dashPanel{{background:{P.bg_card}; border:1px solid {P.border_light if newer else P.border}; border-radius:{UIScale.px(8)}px;}}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(14))
        lay.setSpacing(UIScale.px(8))

        hdr = QLabel(label, frame)
        hdr.setFont(Fonts.title)
        hdr.setStyleSheet(f"color:{P.cream}; background:transparent;")
        lay.addWidget(hdr)

        badge = QLabel("Newer copy" if newer else "Available", frame)
        badge.setFont(Fonts.mixed_small_bold)
        badge.setStyleSheet(f"color:{P.gold if newer else P.fg_dim}; background:transparent;")
        lay.addWidget(badge)

        body = QLabel(
            f"Day {day:,}\n{gold:,.0f}g\n{stamp}",
            frame,
        )
        body.setFont(Fonts.mono_small)
        body.setStyleSheet(f"color:{P.fg}; background:transparent;")
        lay.addWidget(body)
        lay.addStretch()

        btn = MtButton("Load This Save", frame, role="primary" if newer else "secondary")
        btn.clicked.connect(lambda: self._pick(value))
        lay.addWidget(btn)
        return frame

    def _pick(self, value: str) -> None:
        self._choice = value
        self.accept()

    def choose(self) -> Optional[str]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return self._choice


class LaunchScreen(Screen):
    """Startup auth screen shown before entering the main game shell."""

    def build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(UIScale.px(24), UIScale.px(24), UIScale.px(24), UIScale.px(24))
        outer.setSpacing(0)

        top_band = QFrame(self)
        top_band.setFixedHeight(UIScale.px(30))
        top_band.setStyleSheet(f"background:{P.bg_dialog_hdr}; border:none;")
        outer.addWidget(top_band)

        mid = QWidget(self)
        mid.setStyleSheet(f"background:{P.bg};")
        mid_lay = QVBoxLayout(mid)
        mid_lay.setContentsMargins(0, 0, 0, 0)
        mid_lay.addStretch()

        wrap = QHBoxLayout()
        wrap.addStretch()

        card = QFrame(mid)
        card.setObjectName("launchCard")
        card.setStyleSheet(
            f"QFrame#launchCard{{background:{P.bg_panel}; border:2px solid {P.border_light}; border-radius:{UIScale.px(10)}px;}}"
        )
        card.setFixedWidth(UIScale.px(520))
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(UIScale.px(28), UIScale.px(24), UIScale.px(28), UIScale.px(24))
        card_lay.setSpacing(UIScale.px(10))

        title = QLabel("MERCHANT TYCOON", card)
        title.setFont(Fonts.title_large)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color:{P.border_light}; background:transparent;")
        card_lay.addWidget(title)

        subtitle = QLabel("Expanded Edition", card)
        subtitle.setFont(Fonts.mixed_small)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        card_lay.addWidget(subtitle)

        line = QFrame(card)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{P.border_light}; border:none;")
        card_lay.addWidget(line)

        portal = QLabel("Merchant Portal", card)
        portal.setFont(Fonts.heading)
        portal.setStyleSheet(f"color:{P.gold}; background:transparent;")
        card_lay.addWidget(portal)

        self._email = self._field(card_lay, "Email Address")
        self._password = self._field(card_lay, "Password", password=True)

        extra = QHBoxLayout()
        self._remember = QCheckBox("Remember me", card)
        self._remember.setChecked(True)
        self._remember.setFont(Fonts.mixed_small)
        self._remember.setStyleSheet(f"color:{P.fg}; background:transparent;")
        extra.addWidget(self._remember)
        extra.addStretch()
        forgot_btn = QPushButton("Reset password", card)
        forgot_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        forgot_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{P.border_light};border:none;padding:0px;}}"
            f"QPushButton:hover{{color:{P.gold};}}"
        )
        forgot_btn.setFont(Fonts.mixed_small)
        forgot_btn.clicked.connect(self._forgot_password)
        extra.addWidget(forgot_btn)
        card_lay.addLayout(extra)

        btns = QHBoxLayout()
        self._signin_btn = MtButton("Sign In", card)
        self._signin_btn.clicked.connect(self._do_sign_in)
        signup_btn = MtButton("Create Account", card, role="secondary")
        signup_btn.clicked.connect(self._do_register)
        btns.addWidget(self._signin_btn)
        btns.addWidget(signup_btn)
        card_lay.addLayout(btns)

        sep_row = QHBoxLayout()
        left_sep = QFrame(card)
        left_sep.setFrameShape(QFrame.Shape.HLine)
        left_sep.setStyleSheet(f"background:{P.border}; border:none;")
        right_sep = QFrame(card)
        right_sep.setFrameShape(QFrame.Shape.HLine)
        right_sep.setStyleSheet(f"background:{P.border}; border:none;")
        sep_row.addWidget(left_sep, 1)
        or_lbl = QLabel("or", card)
        or_lbl.setFont(Fonts.mixed_small)
        or_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        sep_row.addWidget(or_lbl)
        sep_row.addWidget(right_sep, 1)
        card_lay.addLayout(sep_row)

        self._offline_btn = MtButton("Play Offline (local save only)", card, role="nav")
        self._offline_btn.clicked.connect(self._play_offline)
        card_lay.addWidget(self._offline_btn)

        self._status = QLabel("", card)
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setFont(Fonts.mixed_small)
        self._status.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        card_lay.addWidget(self._status)

        wrap.addWidget(card)
        wrap.addStretch()
        mid_lay.addLayout(wrap)
        mid_lay.addStretch()
        outer.addWidget(mid, 1)

        bottom_band = QFrame(self)
        bottom_band.setFixedHeight(UIScale.px(30))
        bottom_band.setStyleSheet(f"background:{P.bg_dialog_hdr}; border:none;")
        outer.addWidget(bottom_band)

        self._email.returnPressed.connect(self._password.setFocus)
        self._password.returnPressed.connect(self._do_sign_in)

        if not self.app.online:
            self._set_status("Online services are unavailable. You can still play offline.", P.amber)
            self._signin_btn.setEnabled(False)

    def on_show(self) -> None:
        QTimer.singleShot(0, self._email.setFocus)

    def _field(self, layout: QVBoxLayout, label: str, password: bool = False) -> QLineEdit:
        lbl = QLabel(label, self)
        lbl.setFont(Fonts.mixed_small)
        lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        layout.addWidget(lbl)
        edit = QLineEdit(self)
        edit.setFont(Fonts.mixed_bold)
        if password:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(edit)
        return edit

    def _set_status(self, text: str, color: str = "") -> None:
        self._status.setText(text)
        self._status.setStyleSheet(f"color:{color or P.fg_dim}; background:transparent;")

    def _set_busy(self, busy: bool) -> None:
        self._signin_btn.setEnabled(not busy and bool(self.app.online))
        self._offline_btn.setEnabled(not busy)
        self._email.setEnabled(not busy)
        self._password.setEnabled(not busy)
        self._remember.setEnabled(not busy)

    def _do_sign_in(self) -> None:
        if not self.app.online:
            self._set_status("Online services are unavailable. Use offline mode instead.", P.amber)
            return

        email = self._email.text().strip()
        password = self._password.text()
        if not email or "@" not in email:
            self._set_status("Please enter a valid email address.", P.red)
            return
        if not password:
            self._set_status("Please enter your password.", P.red)
            return

        self._set_busy(True)
        self._set_status("Signing in…", P.fg_dim)

        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._handle_sign_in(r))

        self.app.online.auth.sign_in(email, password, callback=_cb)

    def _handle_sign_in(self, res: Any) -> None:
        if not getattr(res, "success", False):
            msg = str(getattr(res, "error", "Sign-in failed.") or "Sign-in failed.")
            msg_lo = msg.lower()
            if "invalid login" in msg_lo or "invalid credentials" in msg_lo:
                msg = "Invalid email or password."
            elif "email not confirmed" in msg_lo:
                msg = "Email not confirmed. Check your inbox, then sign in again."
            elif "too many requests" in msg_lo:
                msg = "Too many attempts. Wait a moment and try again."
            self._set_status(msg, P.red)
            self._set_busy(False)
            return

        if not self._remember.isChecked():
            self.app.online.auth.clear_saved_session()

        username = self.app.online.auth.username or "Merchant"
        self._set_status(f"Welcome back, {username}. Preparing your save data…", P.green)
        QTimer.singleShot(250, lambda: self.app._complete_authenticated_startup(username))

    def _do_register(self) -> None:
        dlg = RegisterDialog(self.app, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._set_status(dlg.outcome_message(), P.green)

    def _forgot_password(self) -> None:
        if not self.app.online:
            self._set_status("Online services are unavailable.", P.red)
            return
        email = _popup_get_text(
            self,
            "Reset Password",
            "Enter the email address for your account.",
            default=self._email.text().strip(),
            placeholder="merchant@example.com",
            confirm_text="Send Email",
        )
        if email is None:
            return
        email = email.strip()
        if not email or "@" not in email:
            self._set_status("Please enter a valid email address.", P.red)
            return

        self._set_status("Sending reset email…", P.fg_dim)

        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res, addr=email: self._handle_reset(r, addr))

        self.app.online.auth.request_password_reset(email, callback=_cb)

    def _handle_reset(self, res: Any, email: str) -> None:
        if getattr(res, "success", False):
            self._set_status(f"Reset email sent to {email}. Follow the link in your inbox.", P.green)
            return
        self._set_status(str(getattr(res, "error", "Could not send reset email.") or "Could not send reset email."), P.red)

    def _play_offline(self) -> None:
        self._set_busy(True)
        self._set_status("Loading local save…", P.fg_dim)
        QTimer.singleShot(100, self.app._complete_offline_startup)


# ══════════════════════════════════════════════════════════════════════════════
# SIGNATURE DIALOG  —  parchment-style signing prompt for binding agreements
# ══════════════════════════════════════════════════════════════════════════════

class _SignaturePad(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(UIScale.px(92))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(_load_quill_cursor())
        self._paths: List[QPainterPath] = []
        self._current: Optional[QPainterPath] = None

    def clear(self) -> None:
        self._paths.clear()
        self._current = None
        self.update()

    def has_signature(self) -> bool:
        return bool(self._paths) or self._current is not None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        path = QPainterPath()
        path.moveTo(event.position())
        self._current = path
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._current is None:
            return
        self._current.lineTo(event.position())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._current is None:
            return
        self._current.lineTo(event.position())
        self._paths.append(self._current)
        self._current = None
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#e6d4a2"))
        p.setPen(QPen(QColor("#8b6a20"), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        base_y = self.height() - UIScale.px(24)
        p.setPen(QPen(QColor("#7a5e25"), 1, Qt.PenStyle.DashLine))
        p.drawLine(UIScale.px(24), base_y, self.width() - UIScale.px(18), base_y)
        p.setPen(QColor("#6b5422"))
        p.setFont(Fonts.tiny)
        p.drawText(UIScale.px(24), self.height() - UIScale.px(8), "Signature of Merchant")
        ink_pen = QPen(QColor("#1a1060"), max(2, UIScale.px(2)), Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(ink_pen)
        for path in self._paths:
            p.drawPath(path)
        if self._current is not None:
            p.drawPath(self._current)


class SignatureDialog(AppDialog):
    _DOCS: Dict[str, Dict[str, str]] = {
        "license": {
            "title": "Letters Patent",
            "subtitle": "Official Grant of Trade License",
            "body": (
                "Be it known that the undersigned merchant is hereby granted the license described herein, "
                "subject to guild law, taxes, and the usual inconvenient obligations of civil commerce.\n\n"
                "This authority permits the holder to conduct the relevant branch of trade without challenge, "
                "provided the realm is not embarrassed by the results.\n\n"
                "Agreement: {detail}"
            ),
            "seal": "GUILD SEAL",
        },
        "contract": {
            "title": "Contract of Delivery",
            "subtitle": "Binding Commercial Agreement",
            "body": (
                "The carrier agrees to deliver the listed goods to the named destination within the allotted term. "
                "Late delivery may incur penalties, and all parties agree to act surprised when deadlines matter.\n\n"
                "The client affirms the cargo is legal, or at least legal enough for this document to exist.\n\n"
                "Agreement: {detail}"
            ),
            "seal": "TRADE SEAL",
        },
        "loan": {
            "title": "Promissory Note",
            "subtitle": "Deed of Financial Obligation",
            "body": (
                "The borrower acknowledges receipt of the sum herein described and agrees to repay it according to the stated terms.\n\n"
                "Default, delay, and creative arithmetic are strongly discouraged.\n\n"
                "Agreement: {detail}"
            ),
            "seal": "BANK SEAL",
        },
        "fund_client": {
            "title": "Investment Mandate",
            "subtitle": "Private Fund Management Agreement",
            "body": (
                "The client entrusts the listed capital to the undersigned manager for the stated term, in exchange for the promised return and the usual heroic amount of paperwork.\n\n"
                "Management fees are understood, market losses are regrettable, and panic at maturity is considered impolite.\n\n"
                "Agreement: {detail}"
            ),
            "seal": "INVESTMENT SEAL",
        },
        "real_estate": {
            "title": "Deed of Conveyance",
            "subtitle": "Transfer of Property Rights",
            "body": (
                "The seller conveys the described property to the undersigned buyer, together with the rights, liabilities, drafts, damp corners, and future hopes associated with the premises.\n\n"
                "All taxes, repairs, and tenant complaints henceforth become the buyer's problem.\n\n"
                "Agreement: {detail}"
            ),
            "seal": "LAND SEAL",
        },
        "land": {
            "title": "Charter of Land Purchase",
            "subtitle": "Grant of Development Rights",
            "body": (
                "The undersigned is granted lawful possession of the described parcel, with the right to improve, develop, speculate upon, and otherwise burden it with ambitious building plans.\n\n"
                "Boundary disputes, mud, and surveyor fees remain outside the guild's sympathies.\n\n"
                "Agreement: {detail}"
            ),
            "seal": "ESTATE SEAL",
        },
        "default": {
            "title": "Commercial Instrument",
            "subtitle": "Binding Agreement",
            "body": "The undersigned merchant acknowledges and accepts the agreement described below.\n\nAgreement: {detail}",
            "seal": "SEAL",
        },
    }

    def __init__(self, parent: QWidget, doc_type: str, detail: str = "") -> None:
        doc = self._DOCS.get(doc_type, self._DOCS["default"])
        super().__init__(
            parent,
            doc["title"],
            frame_bg="#f0e4be",
            body_bg="#f0e4be",
            title_bg="#dbc88e",
            border="#8b6914",
            title_fg="#231500",
        )
        self._accepted = False
        self.setObjectName("signatureDialog")
        self.resize(UIScale.px(560), UIScale.px(680))
        self._build(doc, detail)
        self.center_on_parent()

    def _build(self, doc: Dict[str, str], detail: str) -> None:
        root = self.body_layout(
            margins=(UIScale.px(18), UIScale.px(16), UIScale.px(18), UIScale.px(16)),
            spacing=UIScale.px(10),
        )

        title = QLabel(doc["title"], self._body)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(Fonts.title)
        title.setStyleSheet("color:#231500;background:transparent;")
        root.addWidget(title)

        subtitle = QLabel(doc["subtitle"], self._body)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setFont(Fonts.mixed_small)
        subtitle.setStyleSheet("color:#5a3e14;background:transparent;")
        root.addWidget(subtitle)

        sep = QFrame(self._body)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#8b6914;border:none;")
        sep.setFixedHeight(1)
        root.addWidget(sep)

        date_lbl = QLabel("Dated this Day of Commerce", self._body)
        date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        date_lbl.setFont(Fonts.tiny)
        date_lbl.setStyleSheet("color:#5a3e14;background:transparent;")
        root.addWidget(date_lbl)

        body_row = QHBoxLayout()
        body = QTextEdit(self._body)
        body.setReadOnly(True)
        body.setFont(Fonts.mixed)
        body.setPlainText(doc["body"].format(detail=detail or "the agreement herein"))
        body.setStyleSheet(
            "QTextEdit{background:#f0e4be;color:#180e00;border:none;padding:4px;}"
        )
        body_row.addWidget(body, 1)

        seal = QFrame(self._body)
        seal.setFixedSize(UIScale.px(84), UIScale.px(84))
        seal.setStyleSheet(
            f"background:#881414;border:2px solid #5a0808;border-radius:{UIScale.px(42)}px;"
        )
        seal_lay = QVBoxLayout(seal)
        seal_lay.setContentsMargins(0, 0, 0, 0)
        seal_text = QLabel(doc["seal"], seal)
        seal_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        seal_text.setFont(Fonts.small)
        seal_text.setStyleSheet("color:#f0c0b0;background:transparent;")
        seal_lay.addWidget(seal_text)
        body_row.addWidget(seal, 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(body_row, 1)

        sign_lbl = QLabel("Sign below: drawing is optional; accepting is required.", self._body)
        sign_lbl.setFont(Fonts.tiny)
        sign_lbl.setStyleSheet("color:#5a3e14;background:transparent;")
        root.addWidget(sign_lbl)

        self._pad = _SignaturePad(self._body)
        root.addWidget(self._pad)

        btns = QHBoxLayout()
        clear_btn = MtButton("Clear", self._body, role="secondary")
        clear_btn.clicked.connect(self._pad.clear)
        sign_btn = MtButton(f"{Sym.CONTRACT}  Sign & Accept", self._body)
        sign_btn.clicked.connect(self._accept)
        decline_btn = MtButton(f"{Sym.NO}  Decline", self._body, role="danger")
        decline_btn.clicked.connect(self.reject)
        btns.addWidget(clear_btn)
        btns.addStretch()
        btns.addWidget(decline_btn)
        btns.addWidget(sign_btn)
        root.addLayout(btns)

    def _accept(self) -> None:
        self._accepted = True
        self.accept()

    def wait(self) -> bool:
        self.exec()
        return self._accepted


def _maybe_sign(screen: "Screen", doc_type: str, detail: str = "") -> bool:
    if not getattr(screen.game.settings, "enable_signatures", False):
        return True
    return SignatureDialog(screen, doc_type, detail).wait()


# ══════════════════════════════════════════════════════════════════════════════
# WAIT / REST DIALOG  —  popup to advance game time without leaving the screen
# ══════════════════════════════════════════════════════════════════════════════

class WaitDialog(AppDialog):
    """
    Modal popup: drag a slider (1–30 days) to advance in-game time.
    Opened from the ⧗ Rest button in the GameHeader.
    Calls game._advance_day() N times then refreshes the app.
    """

    def __init__(self, app: "GameApp", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent or app, "Rest & Wait")
        self._app = app
        self.setObjectName("waitDialog")
        self.setFixedWidth(UIScale.px(400))
        self._build()
        self.center_on_parent()

    def _season_info(self) -> Tuple[int, int, str, str, int]:
        g        = self._app.game
        season   = getattr(g, "season", None)
        day      = int(getattr(g, "day",    1))
        year     = int(getattr(g, "year",   1))
        dps      = getattr(g, "DAYS_PER_SEASON", 30)
        seas_lst = list(Season)
        next_s   = (seas_lst[(seas_lst.index(season) + 1) % 4]
                    if season in seas_lst else None)
        days_till = dps - ((day - 1) % dps)
        sea_s = season.value if season and hasattr(season, "value") else "?"
        ns_s  = next_s.value  if next_s  else "?"
        return day, year, sea_s, ns_s, days_till

    def _build(self) -> None:
        day, year, sea_s, ns_s, days_till = self._season_info()
        root = self.body_layout(
            margins=(UIScale.px(18), UIScale.px(14), UIScale.px(18), UIScale.px(16)),
            spacing=UIScale.px(10),
        )

        sep = QFrame(self._body)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{P.border}; border:none;")
        root.addWidget(sep)

        # ── Status text ──────────────────────────────────────────────────
        status = QLabel(
            f"Current:  Day {day}  \u00b7  {sea_s}  \u00b7  Year {year}\n"
            f"Next season ({ns_s}) in {days_till} day(s).\n"
            "Businesses produce, markets restock, heat cools while you wait.",
            self._body,
        )
        status.setFont(Fonts.mixed_small)
        status.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        status.setWordWrap(True)
        root.addWidget(status)

        # ── Slider row ───────────────────────────────────────────────────
        s_row = QHBoxLayout()
        s_row.setSpacing(UIScale.px(8))

        lbl1 = QLabel("1", self._body)
        lbl1.setFont(Fonts.small)
        lbl1.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        s_row.addWidget(lbl1)

        self._slider = QSlider(Qt.Orientation.Horizontal, self._body)
        self._slider.setMinimum(1)
        self._slider.setMaximum(30)
        self._slider.setValue(1)
        self._slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._slider.setTickInterval(5)
        self._slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: {UIScale.px(4)}px;
                background: {P.border};
                border-radius: {UIScale.px(2)}px;
            }}
            QSlider::handle:horizontal {{
                background: {P.gold};
                border: none;
                width: {UIScale.px(16)}px;
                height: {UIScale.px(16)}px;
                margin: {UIScale.px(-6)}px 0;
                border-radius: {UIScale.px(8)}px;
            }}
            QSlider::sub-page:horizontal {{
                background: {P.amber};
                border-radius: {UIScale.px(2)}px;
            }}
        """)
        s_row.addWidget(self._slider, 1)

        lbl30 = QLabel("30", self._body)
        lbl30.setFont(Fonts.small)
        lbl30.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        s_row.addWidget(lbl30)
        root.addLayout(s_row)

        # ── Days display label ────────────────────────────────────────────
        self._days_lbl = QLabel(f"Wait  1  day", self._body)
        self._days_lbl.setFont(Fonts.mixed_bold)
        self._days_lbl.setStyleSheet(f"color:{P.amber}; background:transparent;")
        self._days_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._days_lbl)
        self._slider.valueChanged.connect(self._on_value)

        # ── Quick shortcuts ───────────────────────────────────────────────
        skip_btn = QPushButton(
            f"{Sym.TRAVEL}  Skip to next season  ({days_till} day{'s' if days_till != 1 else ''})",
            self._body,
        )
        skip_btn.setFont(Fonts.mixed_small)
        skip_btn.setFixedHeight(UIScale.px(28))
        skip_btn.setProperty("role", "secondary")
        skip_btn.clicked.connect(lambda: self._set_days(days_till))
        root.addWidget(skip_btn)

        # ── Accept / Cancel ───────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(UIScale.px(8))
        cancel_btn = MtButton(f"{Sym.NO}  Cancel", parent=self, role="danger")
        cancel_btn.setFixedHeight(UIScale.px(34))
        cancel_btn.clicked.connect(self.reject)
        accept_btn = MtButton(f"{Sym.YES}  Wait", parent=self)
        accept_btn.setFixedHeight(UIScale.px(34))
        accept_btn.clicked.connect(self._accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(accept_btn)
        root.addLayout(btn_row)

    def _set_days(self, n: int) -> None:
        self._slider.setValue(min(30, max(1, n)))

    def _on_value(self, v: int) -> None:
        self._days_lbl.setText(f"Wait  {v}  day{'s' if v != 1 else ''}")

    def _accept(self) -> None:
        n = self._slider.value()
        g = self._app.game
        for _ in range(n):
            g._advance_day()
            g.ach_stats["wait_streak"] = g.ach_stats.get("wait_streak", 0) + 1
        try:
            g._check_achievements()
        except Exception:
            pass
        self._app.refresh()
        sea_s = getattr(g.season, "value", "?") if g.season else "?"
        self._app.message_bar.ok(
            f"Rested {n} day{'s' if n != 1 else ''}. "
            f"Now: {sea_s}, Day {g.day}"
        )
        self.accept()


# ══════════════════════════════════════════════════════════════════════════════
# INBOX DIALOG  —  popup inbox / notifications from the ✉ header button
# ══════════════════════════════════════════════════════════════════════════════

class InboxDialog(AppDialog):
    """
    Modal popup showing online messages and the in-game activity log.
    Opened from the ✉ Inbox button in the GameHeader.
    """

    def __init__(self, app: "GameApp", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent or app, "Inbox")
        self._app = app
        self.setObjectName("inboxDialog")
        self.setFixedSize(UIScale.px(520), UIScale.px(560))
        self._build()
        self.center_on_parent()

    # ── Tiny widget helpers ────────────────────────────────────────────────

    def _lbl(self, text: str, font: QFont, color: str,
             parent: Optional[QWidget] = None, wrap: bool = False) -> QLabel:
        w = QLabel(text, parent or self)
        w.setFont(font)
        w.setStyleSheet(f"color:{color}; background:transparent;")
        if wrap:
            w.setWordWrap(True)
        return w

    def _close_btn(self) -> QPushButton:
        btn = QPushButton(Sym.NO, self)
        btn.setFixedSize(UIScale.px(22), UIScale.px(22))
        btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{P.fg_dim};"
            f"border:none;font-family:'Segoe UI Symbol';"
            f"font-size:{UIScale.px(13)}px;padding:0px;}}"
            f"QPushButton:hover{{color:{P.red};}}"
        )
        btn.clicked.connect(self.reject)
        return btn

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(12), UIScale.px(16), UIScale.px(14)),
            spacing=UIScale.px(8),
        )

        hrow = QHBoxLayout()
        hrow.addWidget(self._lbl(
            f"{Sym.INBOX}  Inbox", Fonts.mixed_bold, P.gold, self._body))
        hrow.addStretch()

        mark_all = QPushButton(f"{Sym.YES}  Mark All Read", self._body)
        mark_all.setFont(Fonts.mixed_small)
        mark_all.setFixedHeight(UIScale.px(24))
        mark_all.setProperty("role", "secondary")
        mark_all.clicked.connect(self._mark_all_read)
        hrow.addWidget(mark_all)
        root.addLayout(hrow)

        sep = QFrame(self._body)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{P.border}; border:none;")
        root.addWidget(sep)

        # ── Tab widget ─────────────────────────────────────────────────
        _tab_qss = (
            f"QTabWidget::pane{{border:none; background:{P.bg};}}"
            f"QTabBar::tab{{background:{P.bg_panel}; color:{P.fg_dim};"
            f"  padding:{UIScale.px(4)}px {UIScale.px(10)}px;"
            f"  border:1px solid {P.border}; border-bottom:none;"
            f"  border-radius:{UIScale.px(4)}px {UIScale.px(4)}px 0 0;"
            f"  margin-right:{UIScale.px(2)}px;}}"
            f"QTabBar::tab:selected{{background:{P.bg}; color:{P.gold};"
            f"  border-bottom:2px solid {P.gold};}}"
        )
        tabs = QTabWidget(self._body)
        tabs.setFont(Fonts.mixed_small)
        tabs.setStyleSheet(_tab_qss)

        # ── Tab 1: Messages (online inbox) ─────────────────────────────
        msg_w = QWidget()
        msg_w.setStyleSheet("background:transparent;")
        msg_lay = QVBoxLayout(msg_w)
        msg_lay.setContentsMargins(UIScale.px(4), UIScale.px(8), UIScale.px(4), UIScale.px(4))
        msg_lay.setSpacing(0)

        self._msg_scroll = QScrollArea(msg_w)
        self._msg_scroll.setWidgetResizable(True)
        self._msg_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._msg_scroll.setStyleSheet("background:transparent; border:none;")

        self._msg_inner = QWidget()
        self._msg_inner.setStyleSheet("background:transparent;")
        self._msg_vlay = QVBoxLayout(self._msg_inner)
        self._msg_vlay.setSpacing(UIScale.px(5))
        self._msg_vlay.setContentsMargins(
            UIScale.px(8), UIScale.px(6), UIScale.px(8), UIScale.px(8))
        self._msg_vlay.addStretch()
        self._msg_scroll.setWidget(self._msg_inner)
        msg_lay.addWidget(self._msg_scroll)
        tabs.addTab(msg_w, f"{Sym.INBOX}  Messages")

        # ── Tab 2: Activity (event log + news feed) ────────────────────
        act_w = QWidget()
        act_w.setStyleSheet("background:transparent;")
        act_lay = QVBoxLayout(act_w)
        act_lay.setContentsMargins(UIScale.px(4), UIScale.px(8), UIScale.px(4), UIScale.px(4))
        act_lay.setSpacing(0)

        act_scroll = QScrollArea(act_w)
        act_scroll.setWidgetResizable(True)
        act_scroll.setFrameShape(QFrame.Shape.NoFrame)
        act_scroll.setStyleSheet("background:transparent; border:none;")

        act_inner = QWidget()
        act_inner.setStyleSheet("background:transparent;")
        act_vlay = QVBoxLayout(act_inner)
        act_vlay.setSpacing(UIScale.px(4))
        act_vlay.setContentsMargins(
            UIScale.px(4), UIScale.px(4), UIScale.px(4), UIScale.px(4))
        self._populate_activity(act_vlay)
        act_vlay.addStretch()
        act_scroll.setWidget(act_inner)
        act_lay.addWidget(act_scroll)
        tabs.addTab(act_w, f"{Sym.NEWS}  Activity")

        root.addWidget(tabs, 1)

        # Load messages last (may show placeholder)
        self._load_messages()

    # ── Activity tab ───────────────────────────────────────────────────────

    def _populate_activity(self, lay: QVBoxLayout) -> None:
        """Fill the Activity tab with news feed and event log entries."""
        g      = self._app.game
        news   = list(getattr(g, "news_feed",  []))
        events = list(getattr(g, "event_log",  []))

        def _hdg(txt: str) -> None:
            lay.addWidget(self._lbl(txt, Fonts.mixed_small_bold, P.gold))
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setFixedHeight(1)
            sep.setStyleSheet(f"background:{P.border}; border:none;")
            lay.addWidget(sep)

        if news:
            _hdg(f"{Sym.NEWS}  Recent News")
            for entry in reversed(news[-20:]):
                try:
                    abs_day, area_name, _ev, headline = entry
                    txt = f"Day {abs_day}  \u00b7  {area_name}:  {headline}"
                except (TypeError, ValueError):
                    txt = str(entry)
                lay.addWidget(self._lbl(txt, Fonts.mixed_small, P.fg_dim,
                                        wrap=True))

        if events:
            if news:
                lay.addSpacing(UIScale.px(6))
            _hdg(f"{Sym.PROGRESS}  Activity Log")
            for entry in reversed(list(events)[-30:]):
                lay.addWidget(self._lbl(
                    f"\u2022  {entry}", Fonts.mixed_small, P.fg_dim, wrap=True))

        if not news and not events:
            ph = self._lbl(
                "No activity recorded yet.\n"
                "Events will appear here as you trade and explore.",
                Fonts.mixed, P.fg_dim)
            ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(ph)

    # ── Messages tab ───────────────────────────────────────────────────────

    def _load_messages(self) -> None:
        """Fetch online messages; fall back to a placeholder when offline."""
        staged = getattr(self._app, "_debug_messages", None)
        if staged is not None:
            self._app._debug_messages = None
            msgs = list(staged)
            self._populate_messages(msgs)
            self._app.game_header.set_inbox_badge(sum(0 if bool(msg.get("is_read", False)) else 1 for msg in msgs))
            return
        online = getattr(self._app, "online", None)
        inbox  = getattr(online, "inbox", None) if online else None
        if inbox is None or not getattr(online, "is_online", False):
            self._show_no_messages("Sign in to online services to receive messages.")
            return

        self._show_no_messages("Loading messages…")
        result = inbox.list_messages(limit=50)
        if result and getattr(result, "success", False):
            msgs = result.data if isinstance(result.data, list) else []
            self._populate_messages(msgs)
            unread = sum(0 if bool(msg.get("is_read", False)) else 1 for msg in msgs)
            self._app.game_header.set_inbox_badge(unread)
            return
        self._show_no_messages(getattr(result, "error", "No messages."))

    def _show_no_messages(self, text: str) -> None:
        while self._msg_vlay.count() > 1:
            item = self._msg_vlay.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()
        ph = self._lbl(text, Fonts.mixed, P.fg_dim, wrap=True)
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.setSizePolicy(QSizePolicy.Policy.Expanding,
                         QSizePolicy.Policy.MinimumExpanding)
        ph.setMinimumHeight(UIScale.px(72))
        ph.setContentsMargins(
            UIScale.px(12), UIScale.px(20), UIScale.px(12), UIScale.px(20))
        self._msg_vlay.insertWidget(0, ph)

    def _populate_messages(self, msgs: List[Dict]) -> None:
        while self._msg_vlay.count() > 1:
            item = self._msg_vlay.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()
        if not msgs:
            self._show_no_messages("No messages.")
            return
        for idx, msg in enumerate(msgs):
            self._msg_vlay.insertWidget(idx, self._build_message_card(msg))

    def _build_message_card(self, msg: Dict) -> QFrame:
        is_read      = bool(msg.get("is_read",        False))
        reward_claim = bool(msg.get("reward_claimed",  False))
        subject      = str(msg.get("subject",          "(no subject)"))
        body         = str(msg.get("body",             ""))
        created      = str(msg.get("created_at",       ""))[:10]
        msg_type     = str(msg.get("msg_type",         "notification"))
        msg_id       = msg.get("id")

        frame = QFrame()
        frame.setObjectName("dashPanel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(UIScale.px(8), UIScale.px(6),
                               UIScale.px(8), UIScale.px(6))
        lay.setSpacing(UIScale.px(3))

        # Header row
        hrow = QHBoxLayout()
        hrow.addWidget(self._lbl(
            "\u25cf" if not is_read else "\u25cb",
            Fonts.tiny,
            P.amber if not is_read else P.fg_dim, frame))
        hrow.addWidget(self._lbl(
            subject,
            Fonts.mixed_bold if not is_read else Fonts.mixed,
            P.gold if not is_read else P.fg, frame), 1)
        hrow.addWidget(self._lbl(created, Fonts.tiny, P.fg_dim, frame))
        lay.addLayout(hrow)

        if msg_id and not is_read:
            online = getattr(self._app, "online", None)
            inbox = getattr(online, "inbox", None) if online else None
            if inbox:
                try:
                    inbox.mark_read(int(msg_id))
                    msg["is_read"] = True
                except Exception:
                    pass

        # Type badge
        type_colors: Dict[str, str] = {
            "reward": P.gold, "seasonal": P.amber,
            "mail": P.cream,  "maintenance": P.green,
        }
        lay.addWidget(self._lbl(
            f"[{msg_type.upper()}]", Fonts.tiny,
            type_colors.get(msg_type, P.fg_dim), frame))

        # Body preview
        if body:
            preview = body[:200] + ("\u2026" if len(body) > 200 else "")
            lay.addWidget(self._lbl(preview, Fonts.mixed_small, P.fg_dim,
                                    frame, wrap=True))

        # Reward
        reward_desc = str(msg.get("reward_description", "") or "")
        if reward_desc and not reward_claim:
            lay.addWidget(self._lbl(
                f"\U0001f381  {reward_desc}",
                Fonts.mixed_small, P.gold, frame))
            claim_btn = QPushButton(f"{Sym.YES}  Claim Reward", frame)
            claim_btn.setFont(Fonts.small)
            claim_btn.setFixedHeight(UIScale.px(24))
            claim_btn.clicked.connect(
                lambda _, mid=msg_id, m=msg: self._claim_reward(mid, m))
            lay.addWidget(claim_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Delete button
        del_btn = QPushButton(f"{Sym.NO}  Delete", frame)
        del_btn.setFont(Fonts.small)
        del_btn.setFixedHeight(UIScale.px(22))
        del_btn.setProperty("role", "danger")
        del_btn.clicked.connect(
            lambda _, f=frame, mid=msg_id: self._delete_message(f, mid))
        lay.addWidget(del_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        return frame

    # ── Actions ────────────────────────────────────────────────────────────

    def _claim_reward(self, msg_id: int, msg: Dict) -> None:
        g   = self._app.game
        inv = getattr(g, "inventory", None)
        online = getattr(self._app, "online", None)
        inbox  = getattr(online, "inbox", None) if online else None
        reward = None
        if inbox:
            try:
                reward = inbox.claim_reward(msg_id)
            except Exception:
                reward = None

        if reward and getattr(reward, "success", False):
            data = reward.data if isinstance(reward.data, dict) else {}
            gold = int(float(data.get("reward_gold", 0) or 0))
            if gold and inv:
                inv.gold = getattr(inv, "gold", 0) + gold
            reward_items = data.get("reward_items", {}) or {}
            if inv and isinstance(reward_items, dict):
                for item_key, qty in reward_items.items():
                    if item_key in ALL_ITEMS and int(qty) > 0:
                        inv.add(item_key, int(qty))
            title = str(data.get("reward_title", "") or "")
            if title and hasattr(g, "earned_titles"):
                g.earned_titles.add(title)
            msg["reward_claimed"] = True
            msg["is_read"] = True
            self._app.message_bar.ok("Reward claimed.")
        else:
            self._app.message_bar.err(
                getattr(reward, "error", "Reward could not be claimed.")
                if reward else "Reward could not be claimed."
            )
            return

        self._load_messages()
        self._app._refresh_inbox_badge()
        self._app.refresh()

    def _delete_message(self, card: QFrame, msg_id: int) -> None:
        online = getattr(self._app, "online", None)
        inbox  = getattr(online, "inbox", None) if online else None
        if inbox:
            try:
                inbox.delete_message(msg_id)
            except Exception:
                pass
        card.deleteLater()
        self._app._refresh_inbox_badge()

    def _mark_all_read(self) -> None:
        online = getattr(self._app, "online", None)
        inbox  = getattr(online, "inbox", None) if online else None
        if inbox:
            try:
                inbox.mark_all_read()
            except Exception:
                pass
        if hasattr(self._app, "game_header"):
            self._app.game_header.set_inbox_badge(0)
        self._load_messages()


class ProfileDialog(AppDialog):
    """Modal player profile dialog with identity, stats, and social summary."""

    _STAT_COLS = [
        ("label", "Statistic", 240),
        ("value", "Value", 320),
    ]
    _FRIEND_COLS = [
        ("status", "Status", 84),
        ("merchant", "Merchant", 230),
        ("net_worth", "Net Worth", 120, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]

    def __init__(self, app: "GameApp", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent or app, "Profile")
        self._app = app
        self._profile_data: Optional[Dict[str, Any]] = None
        self._guild_data: Optional[Dict[str, Any]] = None
        self._friends_data: List[Dict[str, Any]] = []
        self._pending_data: List[Dict[str, Any]] = []
        self.resize(UIScale.px(760), UIScale.px(700))
        self._build()
        self.refresh()
        self.center_on_parent()

    def _build(self) -> None:
        root = self.body_layout(
            margins=(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(14)),
            spacing=UIScale.px(10),
        )

        hero = QFrame(self._body)
        hero.setObjectName("dashPanel")
        hero_lay = QVBoxLayout(hero)
        hero_lay.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        hero_lay.setSpacing(UIScale.px(6))

        name_row = QHBoxLayout()
        name_row.setSpacing(UIScale.px(8))
        self._name_lbl = QLabel("Merchant", hero)
        self._name_lbl.setFont(Fonts.title)
        self._name_lbl.setStyleSheet(f"color:{P.cream}; background:transparent;")
        name_row.addWidget(self._name_lbl)

        self._disc_lbl = QLabel("", hero)
        self._disc_lbl.setFont(Fonts.mono_small)
        self._disc_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        name_row.addWidget(self._disc_lbl)
        name_row.addStretch()

        self._status_lbl = QLabel("Offline mode", hero)
        self._status_lbl.setFont(Fonts.mixed_small_bold)
        self._status_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        name_row.addWidget(self._status_lbl)
        hero_lay.addLayout(name_row)

        self._title_lbl = QLabel("No title equipped", hero)
        self._title_lbl.setFont(Fonts.mixed)
        self._title_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        hero_lay.addWidget(self._title_lbl)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(UIScale.px(12))
        self._uuid_lbl = QLabel("UUID: —", hero)
        self._uuid_lbl.setFont(Fonts.mono_small)
        self._uuid_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        meta_row.addWidget(self._uuid_lbl)
        self._email_lbl = QLabel("Email: —", hero)
        self._email_lbl.setFont(Fonts.mono_small)
        self._email_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        meta_row.addWidget(self._email_lbl)
        meta_row.addStretch()
        hero_lay.addLayout(meta_row)

        button_row = QHBoxLayout()
        button_row.setSpacing(UIScale.px(6))
        edit_name_btn = MtButton(f"{Sym.PROFILE}  Edit Name", hero, role="secondary")
        edit_name_btn.clicked.connect(self._edit_name)
        button_row.addWidget(edit_name_btn)
        edit_title_btn = MtButton(f"{Sym.SKILLS}  Equip Title", hero, role="secondary")
        edit_title_btn.clicked.connect(self._edit_title)
        button_row.addWidget(edit_title_btn)
        copy_uuid_btn = MtButton(f"{Sym.INFO}  Copy UUID", hero, role="secondary")
        copy_uuid_btn.clicked.connect(self._copy_uuid)
        button_row.addWidget(copy_uuid_btn)
        button_row.addStretch()
        social_btn = MtButton(f"{Sym.SOCIAL}  Open Social Hub", hero, role="primary")
        social_btn.clicked.connect(self._open_social)
        button_row.addWidget(social_btn)
        hero_lay.addLayout(button_row)
        root.addWidget(hero)

        scroll = ScrollableFrame(self._body)
        root.addWidget(scroll, 1)
        body = QVBoxLayout(scroll.inner)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(UIScale.px(10))

        stats_panel = QFrame(scroll.inner)
        stats_panel.setObjectName("dashPanel")
        stats_lay = QVBoxLayout(stats_panel)
        stats_lay.setContentsMargins(UIScale.px(12), UIScale.px(10), UIScale.px(12), UIScale.px(12))
        stats_lay.setSpacing(UIScale.px(8))
        stats_hdr = QLabel(f"{Sym.NETWORTH}  Player Stats", stats_panel)
        stats_hdr.setFont(Fonts.mixed_bold)
        stats_hdr.setStyleSheet(f"color:{P.gold}; background:transparent;")
        stats_lay.addWidget(stats_hdr)
        self._stats_table = DataTable(stats_panel, self._STAT_COLS, row_height=24)
        stats_lay.addWidget(self._stats_table)
        body.addWidget(stats_panel)

        social_panel = QFrame(scroll.inner)
        social_panel.setObjectName("dashPanel")
        social_lay = QVBoxLayout(social_panel)
        social_lay.setContentsMargins(UIScale.px(12), UIScale.px(10), UIScale.px(12), UIScale.px(12))
        social_lay.setSpacing(UIScale.px(8))
        social_hdr = QLabel(f"{Sym.SOCIAL}  Social Summary", social_panel)
        social_hdr.setFont(Fonts.mixed_bold)
        social_hdr.setStyleSheet(f"color:{P.gold}; background:transparent;")
        social_lay.addWidget(social_hdr)

        self._guild_lbl = QLabel("Guild: Offline", social_panel)
        self._guild_lbl.setFont(Fonts.mixed)
        self._guild_lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        social_lay.addWidget(self._guild_lbl)
        self._friend_summary_lbl = QLabel("Friends: —", social_panel)
        self._friend_summary_lbl.setFont(Fonts.mixed_small)
        self._friend_summary_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        social_lay.addWidget(self._friend_summary_lbl)
        self._recent_lbl = QLabel("Recent friends: —", social_panel)
        self._recent_lbl.setWordWrap(True)
        self._recent_lbl.setFont(Fonts.mixed_small)
        self._recent_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        social_lay.addWidget(self._recent_lbl)
        self._friends_table = DataTable(social_panel, self._FRIEND_COLS, row_height=24)
        social_lay.addWidget(self._friends_table)
        body.addWidget(social_panel)

        progress_panel = QFrame(scroll.inner)
        progress_panel.setObjectName("dashPanel")
        progress_lay = QVBoxLayout(progress_panel)
        progress_lay.setContentsMargins(UIScale.px(12), UIScale.px(10), UIScale.px(12), UIScale.px(12))
        progress_lay.setSpacing(UIScale.px(8))
        progress_hdr = QLabel(f"{Sym.PROGRESS}  Progress", progress_panel)
        progress_hdr.setFont(Fonts.mixed_bold)
        progress_hdr.setStyleSheet(f"color:{P.gold}; background:transparent;")
        progress_lay.addWidget(progress_hdr)
        self._ach_lbl = QLabel("Achievements: —", progress_panel)
        self._ach_lbl.setFont(Fonts.mixed)
        self._ach_lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        progress_lay.addWidget(self._ach_lbl)
        self._title_count_lbl = QLabel("Titles: —", progress_panel)
        self._title_count_lbl.setFont(Fonts.mixed_small)
        self._title_count_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        progress_lay.addWidget(self._title_count_lbl)
        prog_btn_row = QHBoxLayout()
        prog_btn_row.setSpacing(UIScale.px(6))
        prog_btn = MtButton(f"{Sym.PROGRESS}  View Progress", progress_panel, role="secondary")
        prog_btn.clicked.connect(self._open_progress)
        prog_btn_row.addWidget(prog_btn)
        settings_btn = MtButton(f"{Sym.SETTINGS}  Settings", progress_panel, role="secondary")
        settings_btn.clicked.connect(self._open_settings)
        prog_btn_row.addWidget(settings_btn)
        prog_btn_row.addStretch()
        progress_lay.addLayout(prog_btn_row)
        body.addWidget(progress_panel)

        options_panel = QFrame(scroll.inner)
        options_panel.setObjectName("dashPanel")
        options_lay = QHBoxLayout(options_panel)
        options_lay.setContentsMargins(UIScale.px(12), UIScale.px(10), UIScale.px(12), UIScale.px(10))
        options_lay.setSpacing(UIScale.px(8))
        self._sign_out_btn = MtButton(f"{Sym.NO}  Sign Out", options_panel, role="danger")
        self._sign_out_btn.clicked.connect(self._sign_out)
        options_lay.addWidget(self._sign_out_btn)
        options_lay.addStretch()
        body.addWidget(options_panel)
        body.addStretch()

    def refresh(self) -> None:
        self._refresh_identity()
        self._refresh_stats()
        self._refresh_progress()
        self._show_social_loading()
        if self._app.online and self._app.online.is_online:
            self._app._push_online_presence()
            self._load_profile_async()
            self._load_social_async()
        else:
            self._show_social_offline()

    def _refresh_identity(self) -> None:
        g = self._app.game
        self._name_lbl.setText(g.player_name or "Merchant")
        active_title = getattr(g, "active_title", "") or ""
        title_def = TITLES_BY_ID.get(active_title)
        self._title_lbl.setText(title_def["name"] if title_def else (active_title or "No title equipped"))

        online = getattr(self._app, "online", None)
        auth = getattr(online, "auth", None) if online else None
        if not (online and online.is_online and auth):
            self._disc_lbl.setText("")
            self._status_lbl.setText("Offline mode")
            self._status_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
            self._uuid_lbl.setText("UUID: —")
            self._email_lbl.setText("Email: —")
            self._sign_out_btn.setEnabled(False)
            return

        uid = auth.user_id or ""
        disc = getattr(self._app, "_cached_disc", 0) or 0
        self._disc_lbl.setText(f"#{disc:04d}" if disc else "")
        self._status_lbl.setText("Online")
        self._status_lbl.setStyleSheet(f"color:{P.green}; background:transparent;")
        shown_uid = f"{uid[:8]}…{uid[-4:]}" if len(uid) > 12 else (uid or "—")
        self._uuid_lbl.setText(f"UUID: {shown_uid}")
        self._email_lbl.setText(f"Email: {self._obfuscate_email(auth.email or '—')}")
        self._sign_out_btn.setEnabled(True)

    def _refresh_stats(self) -> None:
        g = self._app.game
        total_secs = float(getattr(g, "time_played_seconds", 0.0) or 0.0)
        if hasattr(self._app, "_session_start"):
            total_secs += max(0.0, time.time() - self._app._session_start)
        hours = int(total_secs // 3600)
        minutes = int((total_secs % 3600) // 60)
        rows = [
            {"label": "Net Worth", "value": f"{g._net_worth():,.0f}g"},
            {"label": "Gold (wallet)", "value": f"{g.inventory.gold:,.0f}g"},
            {"label": "Bank Balance", "value": f"{g.bank_balance:,.2f}g"},
            {"label": "Reputation", "value": str(g.reputation)},
            {"label": "Time Played", "value": f"{hours}h {minutes}m"},
            {"label": "Days In-Game", "value": str(g._absolute_day())},
            {"label": "Current Area", "value": g.current_area.value},
            {"label": "Lifetime Trades", "value": str(g.lifetime_trades)},
            {"label": "Contracts Done", "value": str(g.ach_stats.get("contracts_completed", 0))},
            {"label": "Titles Earned", "value": f"{len(getattr(g, 'earned_titles', []))}"},
        ]
        self._stats_table.load(rows)

    def _refresh_progress(self) -> None:
        g = self._app.game
        ach_count = len(getattr(g, "achievements", set()))
        total_ach = len(ACHIEVEMENTS)
        title_count = len(getattr(g, "earned_titles", []))
        self._ach_lbl.setText(f"Achievements: {ach_count} / {total_ach} unlocked")
        self._title_count_lbl.setText(f"Titles: {title_count} / {len(TITLE_DEFINITIONS)} earned")

    def _show_social_loading(self) -> None:
        self._guild_lbl.setText("Guild: Loading…")
        self._friend_summary_lbl.setText("Friends: Loading…")
        self._recent_lbl.setText("Recent friends: Loading…")
        self._friends_table.load([])

    def _show_social_offline(self) -> None:
        self._guild_lbl.setText("Guild: Offline")
        self._friend_summary_lbl.setText("Friends: Sign in to use online social features")
        self._recent_lbl.setText("Recent friends: —")
        self._friends_table.load([])

    def _load_profile_async(self) -> None:
        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._apply_profile_result(r))
        self._app.online.profile.get_profile(callback=_cb)

    def _load_social_async(self) -> None:
        online = self._app.online
        if not online:
            return
        def _guild_cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._apply_guild_result(r))
        def _friends_cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._apply_friends_result(r))
        def _pending_cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._apply_pending_result(r))
        online.guilds.get_my_guild(callback=_guild_cb)
        online.friends.list_friends_with_profiles(callback=_friends_cb)
        online.friends.list_pending_requests(callback=_pending_cb)

    def _apply_profile_result(self, res: Any) -> None:
        if not self.isVisible():
            return
        if getattr(res, "success", False) and res.data is None:
            username = self._app.online.auth.username or self._app.game.player_name or "Merchant"
            def _create_cb(_result: Any) -> None:
                _queue_ui(self, self._load_profile_async)
            self._app.online.profile.create_profile(username=username, callback=_create_cb)
            return
        if not getattr(res, "success", False) or not isinstance(res.data, dict):
            return
        self._profile_data = res.data
        disc = int(res.data.get("discriminator") or 0)
        if disc:
            self._app._cached_disc = disc
            self._disc_lbl.setText(f"#{disc:04d}")
        title_key = str(res.data.get("title", "") or "")
        if title_key and not getattr(self._app.game, "active_title", ""):
            self._app.game.active_title = title_key
            title_def = TITLES_BY_ID.get(title_key)
            self._title_lbl.setText(title_def["name"] if title_def else title_key)

    def _apply_guild_result(self, res: Any) -> None:
        self._guild_data = res.data if (getattr(res, "success", False) and isinstance(res.data, dict)) else None
        if self._guild_data:
            name = self._guild_data.get("name", "Unknown Guild")
            count = int(self._guild_data.get("member_count", 0) or 0)
            role_label = str(self._guild_data.get("my_role_label", self._guild_data.get("my_role", "")) or "")
            self._app._cached_guild_id = str(self._guild_data.get("id", "") or "")
            self._app._cached_guild_name = str(name or "")
            self._app._cached_guild_role = role_label
            role_text = f"  •  {role_label}" if role_label else ""
            self._guild_lbl.setText(f"Guild: {name}{role_text}  •  {count} member{'s' if count != 1 else ''}")
        else:
            self._app._cached_guild_id = ""
            self._app._cached_guild_name = ""
            self._app._cached_guild_role = ""
            self._guild_lbl.setText("Guild: No guild")

    def _apply_friends_result(self, res: Any) -> None:
        self._friends_data = res.data if (getattr(res, "success", False) and isinstance(res.data, list)) else []
        self._render_social_summary()

    def _apply_pending_result(self, res: Any) -> None:
        self._pending_data = res.data if (getattr(res, "success", False) and isinstance(res.data, list)) else []
        self._render_social_summary()

    def _render_social_summary(self) -> None:
        friend_count = len(self._friends_data)
        pending_count = len(self._pending_data)
        self._friend_summary_lbl.setText(f"Friends: {friend_count}  •  Pending requests: {pending_count}")
        preview: List[str] = []
        rows: List[Dict[str, Any]] = []
        for item in self._friends_data[:5]:
            profile = item.get("profile") or {}
            status_text, _status_colour, tag = self._presence_label(profile.get("last_seen", ""))
            name = self._player_label(profile)
            nw = float(profile.get("last_networth", 0) or 0)
            preview.append(name)
            rows.append({
                "status": status_text,
                "merchant": name,
                "net_worth": f"{nw:,.0f}g" if nw > 0 else "—",
                "_tag": tag,
            })
        self._recent_lbl.setText("Recent friends: " + (", ".join(preview) if preview else "—"))
        self._friends_table.load(rows)

    def _edit_name(self) -> None:
        current = self._app.game.player_name or "Merchant"
        new_name = TextPromptDialog(
            self,
            "Edit Merchant Name",
            "Enter your merchant name.",
            default=current,
            placeholder="Merchant name",
            confirm_text="Save Name",
        ).get_value()
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name:
            self._app.message_bar.warn("Merchant name cannot be empty.")
            return
        self._app.game.player_name = new_name
        self._app.message_bar.ok(f"Merchant name updated to {new_name}.")
        online = self._app.online
        if online and online.is_online:
            try:
                online.auth.update_username(new_name)
                online.profile.update_profile({"username": new_name})
            except Exception:
                pass
            self._app._push_leaderboard()
        self.refresh()
        self._app.refresh()

    def _edit_title(self) -> None:
        earned = list(getattr(self._app.game, "earned_titles", []))
        options: List[str] = ["(No title)"]
        label_to_id: Dict[str, str] = {"(No title)": ""}
        for title_id in earned:
            title_def = TITLES_BY_ID.get(title_id)
            label = title_def["name"] if title_def else title_id
            if label in label_to_id:
                label = f"{label} [{title_id}]"
            label_to_id[label] = title_id
            options.append(label)
        if len(options) == 1:
            self._app.message_bar.info("Earn a title first, then equip it here.")
            return
        choice, ok = ChoiceListDialog(
            self,
            "Equip Title",
            "Choose which earned title to display.",
            options,
            confirm_text="Equip",
        ).choose()
        if not ok:
            return
        title_id = label_to_id.get(choice, "")
        self._app.game.active_title = title_id
        if self._app.online and self._app.online.is_online:
            try:
                self._app.online.profile.set_active_title(title_id)
            except Exception:
                pass
            self._app._push_leaderboard()
        self.refresh()
        self._app.refresh()
        self._app.message_bar.ok("Active title updated.")

    def _copy_uuid(self) -> None:
        online = self._app.online
        uid = online.auth.user_id if (online and online.is_online and online.auth.user_id) else ""
        if not uid:
            self._app.message_bar.warn("No UUID available while offline.")
            return
        QApplication.clipboard().setText(uid)
        self._app.message_bar.ok("UUID copied to clipboard.")

    def _open_social(self) -> None:
        self.accept()
        self._app.goto("social")

    def _open_progress(self) -> None:
        self.accept()
        self._app.goto("progress")

    def _open_settings(self) -> None:
        self.accept()
        self._app.goto("settings")

    def _sign_out(self) -> None:
        online = self._app.online
        if not (online and online.is_online):
            self._app.message_bar.warn("Not currently signed in.")
            return
        if not ConfirmDialog(
            self,
            "Sign Out",
            "Sign out of your online account? Local play will remain available.",
            confirm_text="Sign Out",
            confirm_role="danger",
        ).ask():
            return

        def _cb(_res: Any) -> None:
            _queue_ui(self, self._after_sign_out)

        online.auth.sign_out(callback=_cb)

    def _after_sign_out(self) -> None:
        self._app._cached_disc = 0
        self._app._cached_guild_id = ""
        self._app._cached_guild_name = ""
        self._app._cached_guild_role = ""
        self._app.game_header.set_inbox_badge(0)
        self._app._update_sync_status()
        self._app.message_bar.ok("Signed out successfully.")
        self.refresh()
        self._app.refresh()

    @staticmethod
    def _obfuscate_email(email: str) -> str:
        if "@" not in email:
            return email
        local, domain = email.split("@", 1)
        if len(local) <= 2:
            return f"{'*' * len(local)}@{domain}"
        return f"{local[:2]}{'*' * (len(local) - 2)}@{domain}"

    @staticmethod
    def _player_label(profile: Dict[str, Any]) -> str:
        name = str(profile.get("username", "Unknown") or "Unknown")
        disc = profile.get("discriminator", 0)
        if isinstance(disc, int) and disc:
            return f"{name} #{disc:04d}"
        if disc:
            return f"{name} #{disc}"
        return name

    @staticmethod
    def _presence_label(last_seen: str) -> Tuple[str, str, str]:
        if not last_seen:
            return ("Offline", P.fg_dim, "dim")
        try:
            stamp = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
            now = datetime.now(stamp.tzinfo) if stamp.tzinfo else datetime.utcnow()
            age = (now - stamp).total_seconds()
            if age < 300:
                return ("Online", P.green, "green")
            if age < 1800:
                return ("Away", P.amber, "yellow")
        except Exception:
            pass
        return ("Offline", P.fg_dim, "dim")


class GuildRoleEditorDialog(AppDialog):
    PERMISSION_LABELS: Tuple[Tuple[str, str], ...] = (
        ("invite_members", "Invite members"),
        ("kick_members", "Remove members"),
        ("assign_roles", "Assign roles"),
        ("edit_roles", "Edit roles"),
        ("edit_policies", "Edit policies"),
        ("edit_guild_profile", "Edit guild profile"),
    )

    def __init__(self, parent: Optional[QWidget], role: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(parent, "Guild Role")
        self._role = role or {}
        self.setFixedWidth(UIScale.px(460))

        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )

        intro = QLabel("Define the role name, rank, and permissions. Higher rank appears higher in the roster.", self._body)
        intro.setWordWrap(True)
        intro.setFont(Fonts.mixed)
        intro.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(intro)

        name_lbl = QLabel("Role name", self._body)
        name_lbl.setFont(Fonts.mixed_small_bold)
        root.addWidget(name_lbl)
        self._name_edit = QLineEdit(self._body)
        self._name_edit.setText(str(self._role.get("label", "") or ""))
        self._name_edit.setPlaceholderText("Vice President")
        self._name_edit.setFont(Fonts.mixed_bold)
        root.addWidget(self._name_edit)

        key_lbl = QLabel("Role key", self._body)
        key_lbl.setFont(Fonts.mixed_small_bold)
        root.addWidget(key_lbl)
        self._key_edit = QLineEdit(self._body)
        self._key_edit.setText(str(self._role.get("role_key", "") or ""))
        self._key_edit.setPlaceholderText("vice_president")
        self._key_edit.setFont(Fonts.mono_small)
        root.addWidget(self._key_edit)

        rank_lbl = QLabel("Role rank", self._body)
        rank_lbl.setFont(Fonts.mixed_small_bold)
        root.addWidget(rank_lbl)
        self._rank_spin = QSpinBox(self._body)
        self._rank_spin.setRange(1, 999)
        self._rank_spin.setValue(int(self._role.get("rank", 100) or 100))
        self._rank_spin.setFont(Fonts.mixed_bold)
        root.addWidget(self._rank_spin)

        perms_lbl = QLabel("Permissions", self._body)
        perms_lbl.setFont(Fonts.mixed_small_bold)
        root.addWidget(perms_lbl)

        self._permission_checks: Dict[str, QCheckBox] = {}
        perms = self._role.get("permissions") if isinstance(self._role.get("permissions"), dict) else {}
        for key, label in self.PERMISSION_LABELS:
            cb = QCheckBox(label, self._body)
            cb.setChecked(bool(perms.get(key, False)))
            cb.setFont(Fonts.mixed_small)
            cb.setStyleSheet(f"color:{P.fg}; background:transparent;")
            self._permission_checks[key] = cb
            root.addWidget(cb)

        role_key = str(self._role.get("role_key", "") or "")
        if role_key:
            self._key_edit.setEnabled(False)
        if role_key == "president":
            self._key_edit.setEnabled(False)
            self._name_edit.setEnabled(False)
            for cb in self._permission_checks.values():
                cb.setEnabled(False)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = MtButton("Cancel", self._body, role="secondary")
        cancel_btn.clicked.connect(self.reject)
        save_btn = MtButton("Save Role", self._body)
        save_btn.clicked.connect(self.accept)
        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)
        root.addLayout(btns)

        self.center_on_parent()

    def payload(self) -> Optional[Dict[str, Any]]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        role_name = self._name_edit.text().strip() or self._key_edit.text().replace("_", " ").title().strip()
        role_key = self._key_edit.text().strip() or role_name.lower().replace(" ", "_")
        permissions = {key: cb.isChecked() for key, cb in self._permission_checks.items()}
        return {
            "role_key": role_key,
            "label": role_name,
            "rank": int(self._rank_spin.value()),
            "permissions": permissions,
        }


class GuildPolicyEditorDialog(AppDialog):
    def __init__(self, parent: Optional[QWidget], policy: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(parent, "Guild Policies")
        self._policy = policy or {}
        self.resize(UIScale.px(520), UIScale.px(560))

        root = self.body_layout(
            margins=(UIScale.px(16), UIScale.px(14), UIScale.px(16), UIScale.px(16)),
            spacing=UIScale.px(10),
        )

        intro = QLabel("Set how your guild recruits, who can see it, and what culture you want members to feel in-game.", self._body)
        intro.setWordWrap(True)
        intro.setFont(Fonts.mixed)
        intro.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(intro)

        self._recruitment = QComboBox(self._body)
        self._recruitment.setFont(Fonts.mixed_small)
        for value, label in (("open", "Open enlistment"), ("application", "Application required"), ("closed", "Closed / invite only")):
            self._recruitment.addItem(label, value)
        self._recruitment.setCurrentIndex(max(0, self._recruitment.findData(str(self._policy.get("recruitment_mode", "open") or "open"))))
        root.addWidget(QLabel("Recruitment mode", self._body))
        root.addWidget(self._recruitment)

        self._visibility = QComboBox(self._body)
        self._visibility.setFont(Fonts.mixed_small)
        for value, label in (("public", "Public"), ("private", "Private")):
            self._visibility.addItem(label, value)
        self._visibility.setCurrentIndex(max(0, self._visibility.findData(str(self._policy.get("visibility", "public") or "public"))))
        root.addWidget(QLabel("Visibility", self._body))
        root.addWidget(self._visibility)

        self._allow_member_invites = QCheckBox("Allow non-officers with permission to send invites", self._body)
        self._allow_member_invites.setChecked(bool(self._policy.get("allow_member_invites", False)))
        root.addWidget(self._allow_member_invites)

        root.addWidget(QLabel("Minimum reputation", self._body))
        self._min_rep = QSpinBox(self._body)
        self._min_rep.setRange(0, 100000)
        self._min_rep.setValue(int(self._policy.get("minimum_reputation", 0) or 0))
        root.addWidget(self._min_rep)

        root.addWidget(QLabel("Minimum net worth", self._body))
        self._min_networth = QSpinBox(self._body)
        self._min_networth.setRange(0, 2_000_000_000)
        self._min_networth.setSingleStep(1000)
        self._min_networth.setValue(int(float(self._policy.get("minimum_net_worth", 0) or 0)))
        root.addWidget(self._min_networth)

        self._focus = QComboBox(self._body)
        self._focus.setFont(Fonts.mixed_small)
        for value, label in (("balanced", "Balanced"), ("trade", "Trade empire"), ("industry", "Industry"), ("exploration", "Exploration"), ("social", "Social / community")):
            self._focus.addItem(label, value)
        self._focus.setCurrentIndex(max(0, self._focus.findData(str(self._policy.get("event_focus", "balanced") or "balanced"))))
        root.addWidget(QLabel("Guild focus", self._body))
        root.addWidget(self._focus)

        root.addWidget(QLabel("Message of the day", self._body))
        self._motd = QTextEdit(self._body)
        self._motd.setFont(Fonts.mixed_small)
        self._motd.setPlainText(str(self._policy.get("message_of_the_day", "") or ""))
        self._motd.setFixedHeight(UIScale.px(90))
        root.addWidget(self._motd)

        root.addWidget(QLabel("Application prompt", self._body))
        self._application_prompt = QTextEdit(self._body)
        self._application_prompt.setFont(Fonts.mixed_small)
        self._application_prompt.setPlainText(str(self._policy.get("application_prompt", "") or ""))
        self._application_prompt.setFixedHeight(UIScale.px(90))
        root.addWidget(self._application_prompt)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = MtButton("Cancel", self._body, role="secondary")
        cancel_btn.clicked.connect(self.reject)
        save_btn = MtButton("Save Policies", self._body)
        save_btn.clicked.connect(self.accept)
        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)
        root.addLayout(btns)

        self.center_on_parent()

    def payload(self) -> Optional[Dict[str, Any]]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return {
            "recruitment_mode": self._recruitment.currentData(),
            "visibility": self._visibility.currentData(),
            "allow_member_invites": self._allow_member_invites.isChecked(),
            "minimum_reputation": int(self._min_rep.value()),
            "minimum_net_worth": float(self._min_networth.value()),
            "event_focus": self._focus.currentData(),
            "message_of_the_day": self._motd.toPlainText().strip(),
            "application_prompt": self._application_prompt.toPlainText().strip(),
        }


class GuildManagementDialog(AppDialog):
    _MEMBER_COLS = [
        ("merchant", "Merchant", 210),
        ("role", "Role", 160),
        ("joined", "Joined", 140),
        ("contribution", "Contribution", 120, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]
    _ROLE_COLS = [
        ("label", "Role", 180),
        ("rank", "Rank", 80, Qt.AlignmentFlag.AlignCenter),
        ("permissions", "Permissions", 360),
    ]

    def __init__(self, app: "GameApp", guild_id: str, parent: Optional[QWidget] = None, on_change: Optional[Callable[[], None]] = None) -> None:
        super().__init__(parent or app, "Guild Command")
        self._app = app
        self._guild_id = guild_id
        self._on_change = on_change
        self._dashboard: Dict[str, Any] = {}
        self.setMinimumSize(UIScale.px(860), UIScale.px(640))
        self.resize(UIScale.px(920), UIScale.px(720))
        self._build()
        self._load_dashboard()
        self.center_on_parent()

    def _build(self) -> None:
        root = self.body_layout(
            margins=(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(14)),
            spacing=UIScale.px(10),
        )

        self._status_lbl = QLabel("Loading guild command deck…", self._body)
        self._status_lbl.setFont(Fonts.mixed_small)
        self._status_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        root.addWidget(self._status_lbl)

        self._tabs = QTabWidget(self._body)
        root.addWidget(self._tabs, 1)

        overview = QWidget(self._tabs)
        ov_lay = QVBoxLayout(overview)
        ov_lay.setContentsMargins(0, 0, 0, 0)
        ov_lay.setSpacing(UIScale.px(8))
        self._guild_name_lbl = QLabel("Guild", overview)
        self._guild_name_lbl.setFont(Fonts.title)
        self._guild_name_lbl.setStyleSheet(f"color:{P.cream}; background:transparent;")
        ov_lay.addWidget(self._guild_name_lbl)
        self._guild_meta_lbl = QLabel("", overview)
        self._guild_meta_lbl.setFont(Fonts.mono_small)
        self._guild_meta_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        ov_lay.addWidget(self._guild_meta_lbl)
        self._guild_desc_lbl = QLabel("", overview)
        self._guild_desc_lbl.setWordWrap(True)
        self._guild_desc_lbl.setFont(Fonts.mixed)
        self._guild_desc_lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        ov_lay.addWidget(self._guild_desc_lbl)
        self._guild_policy_lbl = QLabel("", overview)
        self._guild_policy_lbl.setWordWrap(True)
        self._guild_policy_lbl.setFont(Fonts.mixed_small)
        self._guild_policy_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        ov_lay.addWidget(self._guild_policy_lbl)
        ov_btns = QHBoxLayout()
        self._edit_guild_btn = MtButton(f"{Sym.SETTINGS}  Edit Guild", overview, role="secondary")
        self._edit_guild_btn.clicked.connect(self._edit_guild_profile)
        ov_btns.addWidget(self._edit_guild_btn)
        self._edit_policy_btn = MtButton(f"{Sym.INFO}  Edit Policies", overview, role="secondary")
        self._edit_policy_btn.clicked.connect(self._edit_policies)
        ov_btns.addWidget(self._edit_policy_btn)
        ov_btns.addStretch()
        self._refresh_btn = MtButton(f"{Sym.SYNC}  Refresh", overview, role="secondary")
        self._refresh_btn.clicked.connect(self._load_dashboard)
        ov_btns.addWidget(self._refresh_btn)
        ov_lay.addLayout(ov_btns)
        ov_lay.addStretch()
        self._tabs.addTab(overview, f"{Sym.INFO}  Overview")

        members = QWidget(self._tabs)
        mem_lay = QVBoxLayout(members)
        mem_lay.setContentsMargins(0, 0, 0, 0)
        mem_lay.setSpacing(UIScale.px(8))
        self._members_table = DataTable(members, self._MEMBER_COLS, row_height=24)
        mem_lay.addWidget(self._members_table, 1)
        mem_btns = QHBoxLayout()
        self._invite_btn = MtButton(f"{Sym.YES}  Invite Merchant", members)
        self._invite_btn.clicked.connect(self._invite_member)
        mem_btns.addWidget(self._invite_btn)
        self._assign_role_btn = MtButton(f"{Sym.SKILLS}  Assign Role", members, role="secondary")
        self._assign_role_btn.clicked.connect(self._assign_selected_role)
        mem_btns.addWidget(self._assign_role_btn)
        self._kick_btn = MtButton(f"{Sym.NO}  Remove Member", members, role="danger")
        self._kick_btn.clicked.connect(self._remove_selected_member)
        mem_btns.addWidget(self._kick_btn)
        mem_btns.addStretch()
        mem_lay.addLayout(mem_btns)
        self._tabs.addTab(members, f"{Sym.SOCIAL}  Members")

        roles = QWidget(self._tabs)
        role_lay = QVBoxLayout(roles)
        role_lay.setContentsMargins(0, 0, 0, 0)
        role_lay.setSpacing(UIScale.px(8))
        self._roles_table = DataTable(roles, self._ROLE_COLS, row_height=24)
        role_lay.addWidget(self._roles_table, 1)
        role_btns = QHBoxLayout()
        self._new_role_btn = MtButton(f"{Sym.YES}  New Role", roles)
        self._new_role_btn.clicked.connect(self._create_role)
        role_btns.addWidget(self._new_role_btn)
        self._edit_role_btn = MtButton(f"{Sym.SETTINGS}  Edit Role", roles, role="secondary")
        self._edit_role_btn.clicked.connect(self._edit_selected_role)
        role_btns.addWidget(self._edit_role_btn)
        self._delete_role_btn = MtButton(f"{Sym.NO}  Delete Role", roles, role="danger")
        self._delete_role_btn.clicked.connect(self._delete_selected_role)
        role_btns.addWidget(self._delete_role_btn)
        role_btns.addStretch()
        role_lay.addLayout(role_btns)
        self._tabs.addTab(roles, f"{Sym.SKILLS}  Roles")

    def _permissions(self) -> Dict[str, bool]:
        perms = self._dashboard.get("permissions")
        if isinstance(perms, dict) and perms:
            return perms
        membership = self._dashboard.get("membership") if isinstance(self._dashboard.get("membership"), dict) else {}
        guild = self._dashboard.get("guild") if isinstance(self._dashboard.get("guild"), dict) else {}
        current_user_id = str(self._app.online.auth.user_id if self._app.online and self._app.online.auth.user_id else "")
        owner_id = str(guild.get("owner_id", "") or "")
        if current_user_id and owner_id and current_user_id == owner_id:
            return {
                "invite_members": True,
                "kick_members": True,
                "assign_roles": True,
                "edit_roles": True,
                "edit_policies": True,
                "edit_guild_profile": True,
            }
        role_key = str(membership.get("role", "member") or "member")
        default_perms: Dict[str, Dict[str, bool]] = {
            "owner": {
                "invite_members": True,
                "kick_members": True,
                "assign_roles": True,
                "edit_roles": True,
                "edit_policies": True,
                "edit_guild_profile": True,
            },
            "president": {
                "invite_members": True,
                "kick_members": True,
                "assign_roles": True,
                "edit_roles": True,
                "edit_policies": True,
                "edit_guild_profile": True,
            },
            "officer": {
                "invite_members": True,
                "kick_members": True,
                "assign_roles": True,
                "edit_roles": True,
                "edit_policies": True,
                "edit_guild_profile": True,
            },
            "vice_president": {
                "invite_members": True,
                "kick_members": True,
                "assign_roles": True,
                "edit_roles": True,
                "edit_policies": True,
                "edit_guild_profile": True,
            },
            "governor": {
                "invite_members": True,
                "kick_members": False,
                "assign_roles": False,
                "edit_roles": False,
                "edit_policies": True,
                "edit_guild_profile": True,
            },
            "quartermaster": {
                "invite_members": True,
                "kick_members": False,
                "assign_roles": False,
                "edit_roles": False,
                "edit_policies": False,
                "edit_guild_profile": False,
            },
            "recruiter": {
                "invite_members": True,
                "kick_members": False,
                "assign_roles": False,
                "edit_roles": False,
                "edit_policies": False,
                "edit_guild_profile": False,
            },
        }
        return default_perms.get(role_key, {})

    def _can(self, permission: str) -> bool:
        return bool(self._permissions().get(permission, False))

    def _load_dashboard(self) -> None:
        online = getattr(self._app, "online", None)
        if not (online and online.is_online):
            self._status_lbl.setText("Sign in to manage your guild.")
            return
        self._status_lbl.setText("Loading guild command deck…")

        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._apply_dashboard(r))

        online.guilds.get_guild_dashboard(self._guild_id, callback=_cb)

    def _apply_dashboard(self, res: Any) -> None:
        if not getattr(res, "success", False) or not isinstance(res.data, dict):
            self._status_lbl.setText(str(getattr(res, "error", "Guild command deck unavailable.")))
            return
        self._dashboard = res.data
        guild = self._dashboard.get("guild") or {}
        membership = self._dashboard.get("membership") or {}
        policy = self._dashboard.get("policy") or {}
        roles = self._dashboard.get("roles") or []
        members = self._dashboard.get("members") or []

        self._guild_name_lbl.setText(str(guild.get("name", "Guild") or "Guild"))
        motto = str(guild.get("motto", "") or "")
        description = str(guild.get("description", "") or "")
        desc_text = description or "No description yet."
        if motto:
            desc_text = f"{motto}\n\n{desc_text}"
        self._guild_desc_lbl.setText(desc_text)
        self._guild_meta_lbl.setText(
            f"Your role: {membership.get('role_label', membership.get('role', 'Member'))}  •  {int(guild.get('member_count', len(members)) or len(members))} members"
        )
        self._guild_policy_lbl.setText(
            f"Recruitment: {str(policy.get('recruitment_mode', 'open') or 'open').replace('_', ' ').title()}  •  "
            f"Visibility: {str(policy.get('visibility', 'public') or 'public').title()}  •  "
            f"Focus: {str(policy.get('event_focus', 'balanced') or 'balanced').replace('_', ' ').title()}"
        )

        member_rows: List[Dict[str, Any]] = []
        for member in members:
            joined = str(member.get("joined_at", "") or "")
            if "T" in joined:
                joined = joined.split("T", 1)[0]
            member_rows.append({
                "merchant": str(member.get("username", "Unknown") or "Unknown"),
                "role": str(member.get("role_label", member.get("role", "Member")) or "Member"),
                "joined": joined or "—",
                "contribution": f"{int(member.get('contribution_score', 0) or 0):,}",
                "user_id": str(member.get("user_id", "") or ""),
                "role_key": str(member.get("role", "member") or "member"),
                "_tag": "cyan" if str(member.get("user_id", "") or "") == str(getattr(getattr(self._app, 'online', None), 'auth', None).user_id if getattr(self._app, 'online', None) else "") else "dim",
            })
        self._members_table.load(member_rows)

        role_rows: List[Dict[str, Any]] = []
        for role in roles:
            perms = role.get("permissions") if isinstance(role.get("permissions"), dict) else {}
            enabled = [label for key, label in GuildRoleEditorDialog.PERMISSION_LABELS if perms.get(key)]
            role_rows.append({
                "label": str(role.get("label", "Role") or "Role"),
                "rank": str(int(role.get("rank", 0) or 0)),
                "permissions": ", ".join(enabled) if enabled else "No elevated permissions",
                "role_key": str(role.get("role_key", "member") or "member"),
                "is_system": bool(role.get("is_system", False)),
                "payload": role,
                "_tag": "gold" if str(role.get("role_key", "")) == "president" else "dim",
            })
        self._roles_table.load(role_rows)

        self._invite_btn.setEnabled(self._can("invite_members"))
        self._assign_role_btn.setEnabled(self._can("assign_roles"))
        self._kick_btn.setEnabled(self._can("kick_members"))
        self._new_role_btn.setEnabled(self._can("edit_roles"))
        self._edit_role_btn.setEnabled(self._can("edit_roles"))
        self._delete_role_btn.setEnabled(self._can("edit_roles"))
        self._edit_policy_btn.setEnabled(self._can("edit_policies"))
        self._edit_guild_btn.setEnabled(self._can("edit_guild_profile"))
        self._status_lbl.setText("Guild command deck synchronized.")

    def _after_change(self, success_message: str) -> None:
        self._app.message_bar.ok(success_message)
        self._load_dashboard()
        self._app._push_online_presence()
        self._app._push_leaderboard()
        if self._on_change is not None:
            self._on_change()

    def _invite_member(self) -> None:
        if not self._can("invite_members"):
            self._app.message_bar.warn("Your role cannot send guild invites.")
            return
        query = TextPromptDialog(
            self,
            "Invite Merchant",
            "Search for a merchant by name tag or UUID.",
            placeholder="Merchant #1234 or UUID",
            confirm_text="Search",
        ).get_value()
        if not query:
            return

        def _search_cb(res: Any) -> None:
            _queue_ui(self, lambda r=res, q=query: self._handle_invite_search(r, q))

        self._app.online.profile.search_players(query, callback=_search_cb)

    def _handle_invite_search(self, res: Any, query: str) -> None:
        if not getattr(res, "success", False):
            self._app.message_bar.err(str(getattr(res, "error", "Search failed.")))
            return
        players = res.data if isinstance(res.data, list) else []
        if not players:
            self._app.message_bar.warn(f"No merchant matched {query}.")
            return
        player = players[0]
        if len(players) > 1:
            items: List[str] = []
            mapping: Dict[str, Dict[str, Any]] = {}
            for row in players:
                disc = row.get("discriminator", 0)
                suffix = f" #{int(disc):04d}" if isinstance(disc, int) and disc else (f" #{disc}" if disc else "")
                label = f"{row.get('username', 'Unknown')}{suffix}  •  {float(row.get('last_networth', 0) or 0):,.0f}g NW"
                mapping[label] = row
                items.append(label)
            choice, ok = ChoiceListDialog(self, "Choose Merchant", "Choose who to invite.", items, confirm_text="Invite").choose()
            if not ok:
                return
            player = mapping[choice]
        player_id = str(player.get("id") or "")
        if not player_id:
            self._app.message_bar.err("That merchant record is missing an ID.")
            return

        def _invite_cb(invite_res: Any) -> None:
            _queue_ui(self, lambda r=invite_res: self._handle_invite_sent(r, str(player.get('username', 'merchant') or 'merchant')))

        self._app.online.guilds.send_invite(self._guild_id, player_id, callback=_invite_cb)

    def _handle_invite_sent(self, res: Any, name: str) -> None:
        if getattr(res, "success", False):
            self._after_change(f"Guild invite sent to {name}.")
            return
        self._app.message_bar.err(str(getattr(res, "error", "Failed to send guild invite.")))

    def _assign_selected_role(self) -> None:
        if not self._can("assign_roles"):
            self._app.message_bar.warn("Your role cannot assign guild roles.")
            return
        row = self._members_table.selected()
        if not row:
            self._app.message_bar.warn("Select a member first.")
            return
        user_id = str(row.get("user_id", "") or "")
        if not user_id:
            self._app.message_bar.err("That member record is missing an ID.")
            return
        if str(row.get("role_key", "")) == "president":
            self._app.message_bar.warn("Use a dedicated leadership-transfer flow before changing the president role.")
            return
        role_rows = self._dashboard.get("roles") if isinstance(self._dashboard.get("roles"), list) else []
        choices: List[str] = []
        mapping: Dict[str, str] = {}
        for role in role_rows:
            role_key = str(role.get("role_key", "member") or "member")
            if role_key == "president":
                continue
            label = f"{role.get('label', role_key)}  •  rank {int(role.get('rank', 0) or 0)}"
            mapping[label] = role_key
            choices.append(label)
        if not choices:
            self._app.message_bar.warn("No assignable roles are available yet.")
            return
        choice, ok = ChoiceListDialog(self, "Assign Guild Role", "Choose the new role for this member.", choices, confirm_text="Assign").choose()
        if not ok:
            return

        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._handle_role_assigned(r, str(row.get('merchant', 'member') or 'member')))

        self._app.online.guilds.assign_member_role(self._guild_id, user_id, mapping[choice], callback=_cb)

    def _handle_role_assigned(self, res: Any, merchant: str) -> None:
        if getattr(res, "success", False):
            self._after_change(f"Updated {merchant}'s guild role.")
            return
        self._app.message_bar.err(str(getattr(res, "error", "Failed to assign role.")))

    def _remove_selected_member(self) -> None:
        if not self._can("kick_members"):
            self._app.message_bar.warn("Your role cannot remove guild members.")
            return
        row = self._members_table.selected()
        if not row:
            self._app.message_bar.warn("Select a member first.")
            return
        if str(row.get("user_id", "") or "") == str(self._app.online.auth.user_id if self._app.online else ""):
            self._app.message_bar.warn("Use Leave Guild for your own account.")
            return
        if str(row.get("role_key", "")) == "president":
            self._app.message_bar.warn("Transfer leadership before removing the president.")
            return
        merchant = str(row.get("merchant", "member") or "member")
        if not ConfirmDialog(self, "Remove Member", f"Remove {merchant} from the guild?", confirm_text="Remove", confirm_role="danger").ask():
            return

        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._handle_member_removed(r, merchant))

        self._app.online.guilds.remove_member(self._guild_id, str(row.get("user_id", "") or ""), callback=_cb)

    def _handle_member_removed(self, res: Any, merchant: str) -> None:
        if getattr(res, "success", False):
            self._after_change(f"Removed {merchant} from the guild.")
            return
        self._app.message_bar.err(str(getattr(res, "error", "Failed to remove member.")))

    def _create_role(self) -> None:
        if not self._can("edit_roles"):
            self._app.message_bar.warn("Your role cannot edit guild roles.")
            return
        payload = GuildRoleEditorDialog(self).payload()
        if payload is None:
            return

        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._handle_role_saved(r, str(payload.get('label', 'role') or 'role')))

        self._app.online.guilds.upsert_guild_role(
            self._guild_id,
            str(payload.get("role_key", "") or "member"),
            str(payload.get("label", "Role") or "Role"),
            int(payload.get("rank", 100) or 100),
            payload.get("permissions") if isinstance(payload.get("permissions"), dict) else {},
            callback=_cb,
        )

    def _edit_selected_role(self) -> None:
        if not self._can("edit_roles"):
            self._app.message_bar.warn("Your role cannot edit guild roles.")
            return
        row = self._roles_table.selected()
        if not row:
            self._app.message_bar.warn("Select a role first.")
            return
        payload = GuildRoleEditorDialog(self, row.get("payload") if isinstance(row.get("payload"), dict) else None).payload()
        if payload is None:
            return

        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._handle_role_saved(r, str(payload.get('label', 'role') or 'role')))

        self._app.online.guilds.upsert_guild_role(
            self._guild_id,
            str(payload.get("role_key", "") or row.get("role_key", "member")),
            str(payload.get("label", row.get("label", "Role")) or row.get("label", "Role")),
            int(payload.get("rank", row.get("rank", 100)) or 100),
            payload.get("permissions") if isinstance(payload.get("permissions"), dict) else {},
            is_system=bool(row.get("is_system", False)),
            callback=_cb,
        )

    def _handle_role_saved(self, res: Any, label: str) -> None:
        if getattr(res, "success", False):
            self._after_change(f"Saved guild role {label}.")
            return
        self._app.message_bar.err(str(getattr(res, "error", "Failed to save role.")))

    def _delete_selected_role(self) -> None:
        if not self._can("edit_roles"):
            self._app.message_bar.warn("Your role cannot edit guild roles.")
            return
        row = self._roles_table.selected()
        if not row:
            self._app.message_bar.warn("Select a role first.")
            return
        role_key = str(row.get("role_key", "") or "")
        if role_key in {"president", "member"}:
            self._app.message_bar.warn("Core system roles cannot be deleted.")
            return
        label = str(row.get("label", "role") or "role")
        if not ConfirmDialog(self, "Delete Role", f"Delete {label}? Members must be reassigned first.", confirm_text="Delete", confirm_role="danger").ask():
            return

        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._handle_role_deleted(r, label))

        self._app.online.guilds.delete_guild_role(self._guild_id, role_key, callback=_cb)

    def _handle_role_deleted(self, res: Any, label: str) -> None:
        if getattr(res, "success", False):
            self._after_change(f"Deleted guild role {label}.")
            return
        self._app.message_bar.err(str(getattr(res, "error", "Failed to delete role.")))

    def _edit_policies(self) -> None:
        if not self._can("edit_policies"):
            self._app.message_bar.warn("Your role cannot edit guild policies.")
            return
        payload = GuildPolicyEditorDialog(self, self._dashboard.get("policy") if isinstance(self._dashboard.get("policy"), dict) else None).payload()
        if payload is None:
            return

        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._handle_policy_saved(r))

        self._app.online.guilds.update_guild_policy(self._guild_id, payload, callback=_cb)

    def _handle_policy_saved(self, res: Any) -> None:
        if getattr(res, "success", False):
            self._after_change("Updated guild policies.")
            return
        self._app.message_bar.err(str(getattr(res, "error", "Failed to update guild policies.")))

    def _edit_guild_profile(self) -> None:
        if not self._can("edit_guild_profile"):
            self._app.message_bar.warn("Your role cannot edit guild details.")
            return
        guild = self._dashboard.get("guild") if isinstance(self._dashboard.get("guild"), dict) else {}
        motto = TextPromptDialog(
            self,
            "Guild Motto",
            "Set a short motto or rallying phrase.",
            default=str(guild.get("motto", "") or ""),
            placeholder="We profit together.",
            confirm_text="Continue",
        ).get_value()
        if motto is None:
            return
        description = TextPromptDialog(
            self,
            "Guild Description",
            "Describe the guild's mission and vibe.",
            default=str(guild.get("description", "") or ""),
            placeholder="A disciplined trading coalition.",
            confirm_text="Save Guild",
        ).get_value()
        if description is None:
            return

        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._handle_guild_profile_saved(r))

        self._app.online.guilds.update_guild(
            self._guild_id,
            {"motto": motto.strip(), "description": description.strip()},
            callback=_cb,
        )

    def _handle_guild_profile_saved(self, res: Any) -> None:
        if getattr(res, "success", False):
            self._after_change("Updated guild details.")
            return
        self._app.message_bar.err(str(getattr(res, "error", "Failed to update guild details.")))


# ══════════════════════════════════════════════════════════════════════════════
# CHART WIDGETS  —  QPainter-drawn line and bar charts for the dashboard
# ══════════════════════════════════════════════════════════════════════════════

class _LineChart(QWidget):
    """
    Custom QPainter line chart.
    series: List[Tuple[label:str, color:str, points:List[Tuple[x, y]]]]
    Multiple series are drawn as overlapping lines with a small legend.
    """

    _PL, _PT, _PR, _PB = 46, 12, 10, 22   # logical-px margins

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._series: List[Tuple[str, str, List[Tuple[float, float]]]] = []
        self.setMinimumSize(UIScale.px(120), UIScale.px(100))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def set_data(
        self,
        series: List[Tuple[str, str, List[Tuple[float, float]]]],
        x_label: str = "",
        y_label: str = "",
    ) -> None:
        self._series = series
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            self._paint(p)
        finally:
            p.end()

    def _paint(self, p: QPainter) -> None:
        w, h  = self.width(), self.height()
        pl    = UIScale.px(self._PL)
        pt    = UIScale.px(self._PT)
        pr    = UIScale.px(self._PR)
        pb    = UIScale.px(self._PB)
        cw    = max(1, w - pl - pr)
        ch    = max(1, h - pt - pb)

        p.fillRect(0, 0, w, h, QColor(P.bg))

        # Collect all data points
        all_pts: List[Tuple[float, float]] = [
            pt2 for _, _, pts in self._series for pt2 in pts
        ]
        if not all_pts:
            p.setPen(QColor(P.fg_dim))
            p.setFont(Fonts.small)
            p.drawText(
                QRect(0, 0, w, h),
                Qt.AlignmentFlag.AlignCenter,
                "No data \u2014 advance time to populate charts",
            )
            return

        xs = [x for x, _ in all_pts]
        ys = [y for _, y in all_pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        if max_x == min_x:
            max_x += 1
        y_range = max_y - min_y
        if y_range < 0.001:
            y_range = 1.0
        min_y = max(0.0, min_y - y_range * 0.08)
        max_y = max_y + y_range * 0.08
        if max_y == min_y:
            max_y += 1.0

        def sx(x: float) -> int:
            return pl + int((x - min_x) / (max_x - min_x) * cw)

        def sy(y: float) -> int:
            return pt + max(0, min(ch, int((1.0 - (y - min_y) / (max_y - min_y)) * ch)))

        # Horizontal grid (dotted)
        grid_pen = QPen(QColor(P.border), 1, Qt.PenStyle.DotLine)
        p.setPen(grid_pen)
        for i in range(5):
            gy = pt + ch * i // 4
            p.drawLine(pl, gy, pl + cw, gy)

        # Axes
        p.setPen(QPen(QColor(P.border_light), 1))
        p.drawLine(pl, pt, pl, pt + ch)
        p.drawLine(pl, pt + ch, pl + cw, pt + ch)

        # Y-axis labels
        p.setPen(QColor(P.fg_dim))
        p.setFont(Fonts.tiny)
        for i in range(5):
            frac = i / 4.0
            yv   = min_y + (max_y - min_y) * frac
            gy   = pt + int((1.0 - frac) * ch)
            label_str = f"{yv:,.0f}" if abs(yv) >= 100 else f"{yv:.1f}"
            p.drawText(
                QRect(2, gy - UIScale.px(6), pl - 4, UIScale.px(12)),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label_str,
            )

        # X-axis ticks
        x_ticks = min(6, max(2, len(all_pts) - 1))
        for i in range(x_ticks + 1):
            frac = i / x_ticks
            xv   = min_x + (max_x - min_x) * frac
            gx   = pl + int(frac * cw)
            p.drawText(
                QRect(gx - UIScale.px(18), pt + ch + 2, UIScale.px(36), UIScale.px(14)),
                Qt.AlignmentFlag.AlignCenter,
                f"{int(xv)}",
            )

        # Series lines
        for _label, color, pts in self._series:
            if len(pts) < 2:
                continue
            pen = QPen(QColor(color), max(1, UIScale.px(2)))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            coords = [(sx(x), sy(y)) for x, y in pts]
            for j in range(1, len(coords)):
                p.drawLine(coords[j-1][0], coords[j-1][1], coords[j][0], coords[j][1])

        # Legend (top-right, only if multiple series)
        if len(self._series) > 1:
            fm = QFontMetrics(Fonts.tiny)
            ly = pt + UIScale.px(4)
            for lbl, color, _pts in self._series:
                tw  = fm.horizontalAdvance(lbl)
                bx  = pl + cw - tw - UIScale.px(24)
                p.setPen(QPen(QColor(color), max(1, UIScale.px(2))))
                p.drawLine(bx, ly + UIScale.px(5), bx + UIScale.px(14), ly + UIScale.px(5))
                p.setPen(QColor(P.fg))
                p.setFont(Fonts.tiny)
                p.drawText(
                    QRect(bx + UIScale.px(16), ly, tw + 4, UIScale.px(12)),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    lbl,
                )
                ly += UIScale.px(13)


class _BarChart(QWidget):
    """
    Custom QPainter bar chart with grouped bars.
    groups: List[Tuple[group_label:str, bars:List[Tuple[value, color, bar_label]]]]
    """

    _PL, _PT, _PR, _PB = 46, 12, 8, 40    # logical-px margins

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._groups: List[Tuple[str, List[Tuple[float, str, str]]]] = []
        self.setMinimumSize(UIScale.px(120), UIScale.px(100))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def set_data(
        self, groups: List[Tuple[str, List[Tuple[float, str, str]]]]
    ) -> None:
        self._groups = groups
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            self._paint(p)
        finally:
            p.end()

    def _paint(self, p: QPainter) -> None:
        w, h = self.width(), self.height()
        pl   = UIScale.px(self._PL)
        pt   = UIScale.px(self._PT)
        pr   = UIScale.px(self._PR)
        pb   = UIScale.px(self._PB)
        cw   = max(1, w - pl - pr)
        ch   = max(1, h - pt - pb)

        p.fillRect(0, 0, w, h, QColor(P.bg))

        if not self._groups:
            p.setPen(QColor(P.fg_dim))
            p.setFont(Fonts.small)
            p.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "No data")
            return

        all_vals = [v for _, bars in self._groups for v, _, _ in bars if v > 0]
        max_val  = max(all_vals, default=1.0) * 1.12
        if max_val <= 0:
            max_val = 1.0

        n_groups = len(self._groups)
        group_w  = cw / max(n_groups, 1)

        # Dotted grid
        p.setPen(QPen(QColor(P.border), 1, Qt.PenStyle.DotLine))
        for i in range(1, 5):
            gy = pt + int(ch * i / 4)
            p.drawLine(pl, gy, pl + cw, gy)

        # Y-axis labels
        p.setPen(QColor(P.fg_dim))
        p.setFont(Fonts.tiny)
        for i in range(5):
            frac = i / 4.0
            yv   = max_val * (1.0 - frac)
            gy   = pt + int(ch * frac)
            label_str = f"{yv:,.0f}" if abs(yv) >= 100 else f"{yv:.1f}"
            p.drawText(
                QRect(2, gy - UIScale.px(6), pl - 4, UIScale.px(12)),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label_str,
            )

        # Axes
        p.setPen(QPen(QColor(P.border_light), 1))
        p.drawLine(pl, pt, pl, pt + ch)
        p.drawLine(pl, pt + ch, pl + cw, pt + ch)

        # Bars + group labels
        for gi, (group_label, bars) in enumerate(self._groups):
            n_bars = len(bars)
            if n_bars == 0:
                continue
            gx    = pl + int(gi * group_w)
            sub_w = group_w / n_bars

            for bi, (val, color, _bar_label) in enumerate(bars):
                bx = int(gx + bi * sub_w + sub_w * 0.125)
                bw = max(1, int(sub_w * 0.75))
                bh = max(1, int(val / max_val * ch))
                by = pt + ch - bh
                p.setBrush(QBrush(QColor(color)))
                p.setPen(QPen(QColor(color).lighter(115), 1))
                p.drawRect(bx, by, bw, bh)

            p.setPen(QColor(P.fg_dim))
            p.setFont(Fonts.tiny)
            p.drawText(
                QRect(int(gx), pt + ch + UIScale.px(3), int(group_w), UIScale.px(14)),
                Qt.AlignmentFlag.AlignCenter,
                group_label[:9],
            )


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD SCREEN  —  home screen with key stats + quick actions
# ══════════════════════════════════════════════════════════════════════════════


class DashboardScreen(Screen):
    """
    Full home dashboard.
    Layout — 3-column + bottom news strip:
      Left  (210 px fixed)  : Player stats card  /  Inventory  /  Businesses
      Center (stretch)      : Market chart widget (5 tabs: Overview, History,
                              Compare, Trends, Net Worth)
      Right  (200 px fixed) : Obligations tabs (Contracts / Loans / Voyages)
      Bottom (80 px)        : News & events strip
    """

    _OVERVIEW_COLS = [
        ("item", "Item", 150, Qt.AlignmentFlag.AlignCenter),
        ("cat", "Category", 96, Qt.AlignmentFlag.AlignCenter),
        ("buy", "Buy (g/u)", 92, Qt.AlignmentFlag.AlignCenter),
        ("sell", "Sell (g/u)", 92, Qt.AlignmentFlag.AlignCenter),
        ("base", "Base (g/u)", 92, Qt.AlignmentFlag.AlignCenter),
        ("buy_base", "Buy vs Base", 90, Qt.AlignmentFlag.AlignCenter),
        ("sell_base", "Sell vs Base", 90, Qt.AlignmentFlag.AlignCenter),
        ("trend", "7d Trend", 94, Qt.AlignmentFlag.AlignCenter),
    ]
    _COMPARE_COLS = [
        ("area", "Area", 110, Qt.AlignmentFlag.AlignCenter),
        ("buy", "Buy (g/u)", 92, Qt.AlignmentFlag.AlignCenter),
        ("sell", "Sell (g/u)", 92, Qt.AlignmentFlag.AlignCenter),
        ("vs_buy", "vs Current Buy", 106, Qt.AlignmentFlag.AlignCenter),
        ("vs_sell", "vs Current Sell", 108, Qt.AlignmentFlag.AlignCenter),
        ("trend", "7d Trend", 94, Qt.AlignmentFlag.AlignCenter),
        ("base_delta", "Sell vs Base", 98, Qt.AlignmentFlag.AlignCenter),
    ]
    _TREND_COLS = [
        ("item", "Item", 170, Qt.AlignmentFlag.AlignCenter),
        ("current", "Current (g/u)", 104, Qt.AlignmentFlag.AlignCenter),
        ("avg7", "7d Avg (g/u)", 104, Qt.AlignmentFlag.AlignCenter),
        ("delta", "7d Change", 96, Qt.AlignmentFlag.AlignCenter),
        ("base_delta", "vs Base", 86, Qt.AlignmentFlag.AlignCenter),
        ("state", "Trend", 90, Qt.AlignmentFlag.AlignCenter),
    ]

    # ── Build ──────────────────────────────────────────────────────────────

    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(8), UIScale.px(6),
                                UIScale.px(8), UIScale.px(6))
        root.setSpacing(UIScale.px(6))

        # Title row
        title_row = QHBoxLayout()
        t = QLabel(f"{Sym.DASHBOARD}  Dashboard", self)
        t.setFont(Fonts.mixed_heading)
        t.setStyleSheet(f"color:{P.gold}; background:transparent;")
        title_row.addWidget(t)
        title_row.addStretch()
        self._time_lbl = QLabel("\u2014", self)
        self._time_lbl.setFont(Fonts.mixed_small)
        self._time_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        title_row.addWidget(self._time_lbl)
        root.addLayout(title_row)

        # 3-column main area
        cols = QHBoxLayout()
        cols.setSpacing(UIScale.px(6))

        left = self._build_left_panel()
        left.setFixedWidth(UIScale.px(210))
        cols.addWidget(left)

        self._chart_tabs = self._build_center_panel()
        cols.addWidget(self._chart_tabs, 1)

        right = self._build_right_panel()
        right.setFixedWidth(UIScale.px(204))
        cols.addWidget(right)

        root.addLayout(cols, 1)

        # Bottom news strip
        root.addWidget(self._build_news_strip())

    # ── Panel builders ──────────────────────────────────────────────────────

    def _panel_frame(self, title: str, icon: str = "") -> Tuple["QFrame", "QVBoxLayout"]:
        """Helper: titled panel frame; returns (frame, inner_layout)."""
        frame = QFrame(self)
        frame.setObjectName("dashPanel")
        lay   = QVBoxLayout(frame)
        lay.setContentsMargins(UIScale.px(8), UIScale.px(6),
                               UIScale.px(8), UIScale.px(6))
        lay.setSpacing(UIScale.px(3))
        hdr_text = f"{icon}  {title}" if icon else title
        hdr = QLabel(hdr_text, frame)
        hdr.setFont(Fonts.mixed_small_bold)
        hdr.setStyleSheet(
            f"color:{P.amber}; background:transparent; "
            "border:none; padding-bottom:1px;"
        )
        lay.addWidget(hdr)
        sep = QFrame(frame)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{P.border}; border:none;")
        lay.addWidget(sep)
        return frame, lay

    def _stat_row(
        self,
        parent_lay: "QVBoxLayout",
        label: str,
        value: str,
        val_col: str,
        parent: QWidget,
    ) -> QLabel:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(UIScale.px(4))
        lbl = QLabel(label, parent)
        lbl.setFont(Fonts.mixed_small)
        lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        row.addWidget(lbl)
        row.addStretch()
        val = QLabel(value, parent)
        val.setFont(Fonts.small_bold)
        val.setStyleSheet(f"color:{val_col}; background:transparent;")
        row.addWidget(val)
        parent_lay.addLayout(row)
        return val

    def _build_left_panel(self) -> QFrame:
        """Left column: player stats, inventory snapshot, businesses."""
        outer = QFrame(self)
        outer.setObjectName("dashPanel")
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(UIScale.px(4))

        # ── Player Stats ─────────────────────────────────────────────────
        ps_frame, ps_lay = self._panel_frame("Player Stats", Sym.PLAYER)
        self._d_name_val  = self._stat_row(ps_lay, "Name",       "\u2014", P.fg,    ps_frame)
        self._d_day_val   = self._stat_row(ps_lay, "Day",        "\u2014", P.gold,  ps_frame)
        self._d_sea_val   = self._stat_row(ps_lay, "Season",     "\u2014", P.amber, ps_frame)
        self._d_yr_val    = self._stat_row(ps_lay, "Year",       "\u2014", P.fg,    ps_frame)
        self._d_slot_val  = self._stat_row(ps_lay, "Actions",    "\u2014", P.green, ps_frame)
        ps_sep = QFrame(ps_frame)
        ps_sep.setFrameShape(QFrame.Shape.HLine)
        ps_sep.setFixedHeight(1)
        ps_sep.setStyleSheet(f"background:{P.border}; border:none;")
        ps_lay.addWidget(ps_sep)
        self._d_gold_val  = self._stat_row(
            ps_lay, f"{Sym.GOLD} Gold",       "\u2014", P.gold,   ps_frame)
        self._d_rep_val   = self._stat_row(
            ps_lay, f"{Sym.REP} Reputation",  "\u2014", P.amber,  ps_frame)
        self._d_nw_val    = self._stat_row(
            ps_lay, f"{Sym.NETWORTH} Worth",  "\u2014", P.cream,  ps_frame)
        self._d_loc_val   = self._stat_row(
            ps_lay, f"{Sym.LOCATION} Area",   "\u2014", P.fg_dim, ps_frame)
        self._d_heat_val  = self._stat_row(
            ps_lay, f"{Sym.HEAT} Heat",       "\u2014", P.red,    ps_frame)
        self._d_title_val = self._stat_row(
            ps_lay, f"{Sym.INFLUENCE} Title", "\u2014", P.gold,   ps_frame)
        outer_lay.addWidget(ps_frame)

        # ── Inventory Snapshot ────────────────────────────────────────────
        inv_frame, inv_lay = self._panel_frame("Inventory", Sym.INVENTORY)
        self._d_inv_lbl = QLabel("Empty", inv_frame)
        self._d_inv_lbl.setFont(Fonts.mixed_small)
        self._d_inv_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        self._d_inv_lbl.setWordWrap(True)
        inv_lay.addWidget(self._d_inv_lbl)
        inv_lay.addStretch()
        outer_lay.addWidget(inv_frame, 1)

        # ── Businesses Snapshot ────────────────────────────────────────────
        biz_frame, biz_lay = self._panel_frame("Businesses", Sym.OPERATIONS)
        self._d_biz_lbl = QLabel("None owned.", biz_frame)
        self._d_biz_lbl.setFont(Fonts.mixed_small)
        self._d_biz_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        self._d_biz_lbl.setWordWrap(True)
        biz_lay.addWidget(self._d_biz_lbl)
        biz_lay.addStretch()
        outer_lay.addWidget(biz_frame)

        return outer

    def _chart_tab_style(self) -> str:
        return f"""
            QTabWidget::pane {{
                background: {P.bg};
                border: 1px solid {P.border};
                border-radius: {UIScale.px(3)}px;
                border-top-left-radius: 0px;
            }}
            QTabBar::tab {{
                background: {P.bg};
                color: {P.fg_dim};
                font-family: "Palatino Linotype", "Segoe UI Symbol";
                font-size: {UIScale.px(9)}pt;
                padding: {UIScale.px(4)}px {UIScale.px(8)}px;
                border: 1px solid {P.border};
                border-bottom: none;
                border-top-left-radius: {UIScale.px(3)}px;
                border-top-right-radius: {UIScale.px(3)}px;
                min-width: {UIScale.px(68)}px;
            }}
            QTabBar::tab:selected {{
                background: {P.bg_panel};
                color: {P.gold};
                border-bottom: 2px solid {P.gold};
            }}
            QTabBar::tab:hover:!selected {{
                background: {P.bg_hover};
                color: {P.amber};
            }}
        """

    def _metric_card(self, parent: QWidget, title: str, color: str = P.amber) -> Tuple[QFrame, QLabel]:
        frame = QFrame(parent)
        frame.setObjectName("dashPanel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(UIScale.px(10), UIScale.px(8), UIScale.px(10), UIScale.px(8))
        lay.setSpacing(UIScale.px(3))
        hdr = QLabel(title, frame)
        hdr.setFont(Fonts.tiny)
        hdr.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        lay.addWidget(hdr)
        value = QLabel("—", frame)
        value.setFont(Fonts.mixed_small_bold)
        value.setWordWrap(True)
        value.setStyleSheet(f"color:{color}; background:transparent;")
        lay.addWidget(value)
        lay.addStretch()
        return frame, value

    def _market_trend(self, history: List[Any], fallback: float) -> Tuple[float, float, str, str]:
        if not history:
            return 0.0, 0.0, "Flat", "dim"
        anchor_idx = max(0, len(history) - 7)
        anchor = float(getattr(history[anchor_idx], "price", fallback) or fallback)
        current = float(getattr(history[-1], "price", fallback) or fallback)
        delta = current - anchor
        pct = (delta / anchor * 100.0) if anchor else 0.0
        if pct >= 8:
            return delta, pct, "Rising", "green"
        if pct <= -8:
            return delta, pct, "Falling", "red"
        return delta, pct, "Flat", "yellow"

    def _refresh_overview_detail(self, row: Optional[Dict[str, Any]]) -> None:
        if not hasattr(self, "_ov_detail_lbl"):
            return
        if not row:
            self._ov_detail_lbl.setText("Select a good to inspect its local pricing, base-value gap, and short-term trend.")
            return
        self._ov_detail_lbl.setText(
            f"{row['item']}  ·  {row['cat']}\n"
            f"Local buy: {row['buy']}  ·  Local sell: {row['sell']}\n"
            f"Base price: {row['base']}  ·  Buy vs base: {row['buy_base']}  ·  Sell vs base: {row['sell_base']}\n"
            f"7-day trend: {row['trend']}"
        )

    def _refresh_compare_detail(self, row: Optional[Dict[str, Any]]) -> None:
        if not hasattr(self, "_pc_detail_lbl"):
            return
        if not row:
            self._pc_detail_lbl.setText("Select an area to compare it directly against your current market for the selected good.")
            return
        self._pc_detail_lbl.setText(
            f"{row['area']}\n"
            f"Buy here: {row['buy']}  ·  Sell here: {row['sell']}\n"
            f"Versus current area: buy {row['vs_buy']}  ·  sell {row['vs_sell']}\n"
            f"7-day trend: {row['trend']}  ·  Sell vs base: {row['base_delta']}"
        )

    def _refresh_trend_detail(self, row: Optional[Dict[str, Any]]) -> None:
        if not hasattr(self, "_lt_detail_lbl"):
            return
        if not row:
            self._lt_detail_lbl.setText("Select a good to inspect its price path in this area.")
            return
        pts = row.get("points", []) if isinstance(row, dict) else []
        label = row.get("item", "Selected") if isinstance(row, dict) else "Selected"
        if pts:
            self._lt_chart.set_data([(label[:12], P.gold, pts)], x_label="Day", y_label="Price (g/u)")
        self._lt_detail_lbl.setText(
            f"{row['item']}\n"
            f"Current: {row['current']}  ·  7d avg: {row['avg7']}\n"
            f"7d change: {row['delta']}  ·  vs base: {row['base_delta']}\n"
            f"Trend: {row['state']}"
        )

    def _build_center_panel(self) -> QTabWidget:
        """Center: 5-tab market chart widget."""
        tabs = QTabWidget(self)
        tabs.setObjectName("marketChartTabs")
        tabs.setStyleSheet(self._chart_tab_style())

        # ── Tab 1: Market Overview (numeric board) ────────────────────────
        ov_w = QWidget(); ov_lay = QVBoxLayout(ov_w)
        ov_lay.setContentsMargins(UIScale.px(6), UIScale.px(4),
                                  UIScale.px(6), UIScale.px(4))
        ov_lay.setSpacing(UIScale.px(6))
        ov_ctrl = QHBoxLayout()
        _lbl_a = QLabel(f"{Sym.LOCATION} Area:", ov_w)
        _lbl_a.setFont(Fonts.mixed_small)
        _lbl_a.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        ov_ctrl.addWidget(_lbl_a)
        self._ov_area = QComboBox(ov_w)
        self._ov_area.setFont(Fonts.small)
        self._ov_area.setFixedHeight(UIScale.px(22))
        for area in Area:
            self._ov_area.addItem(area.value, area)
        self._ov_area.currentIndexChanged.connect(self._refresh_overview)
        ov_ctrl.addWidget(self._ov_area)
        ov_ctrl.addStretch()
        ov_lay.addLayout(ov_ctrl)

        ov_note = QLabel("All prices are shown in gold per unit (g/u). Use buy vs base to spot cheap inventory and 7d trend to see movement direction.", ov_w)
        ov_note.setFont(Fonts.tiny)
        ov_note.setWordWrap(True)
        ov_note.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        ov_lay.addWidget(ov_note)

        ov_metrics = QHBoxLayout()
        self._ov_metrics: Dict[str, QLabel] = {}
        for key, title, color in [
            ("cheap", "Cheapest Local Buy", P.green),
            ("payout", "Highest Local Sell", P.gold),
            ("discount", "Best Buy Discount", P.amber),
            ("trend", "Strongest 7d Move", P.cream),
        ]:
            card, value = self._metric_card(ov_w, title, color)
            self._ov_metrics[key] = value
            ov_metrics.addWidget(card, 1)
        ov_lay.addLayout(ov_metrics)

        self._ov_table = DataTable(ov_w, self._OVERVIEW_COLS, row_height=28, stretch_last=False)
        self._ov_table.row_selected.connect(self._refresh_overview_detail)
        ov_lay.addWidget(self._ov_table, 1)
        self._ov_detail_lbl = QLabel("Select a good to inspect its local pricing, base-value gap, and short-term trend.", ov_w)
        self._ov_detail_lbl.setFont(Fonts.mono_small)
        self._ov_detail_lbl.setWordWrap(True)
        self._ov_detail_lbl.setStyleSheet(f"color:{P.cream}; background:transparent;")
        ov_lay.addWidget(self._ov_detail_lbl)
        tabs.addTab(ov_w, f"{Sym.TRADE}  Overview")

        # ── Tab 2: Price History (line chart, single item over time) ──────
        ph_w = QWidget(); ph_lay = QVBoxLayout(ph_w)
        ph_lay.setContentsMargins(UIScale.px(6), UIScale.px(4),
                                  UIScale.px(6), UIScale.px(4))
        ph_lay.setSpacing(UIScale.px(4))
        ph_ctrl = QHBoxLayout()
        _lbl_pa = QLabel(f"{Sym.LOCATION} Area:", ph_w)
        _lbl_pa.setFont(Fonts.mixed_small)
        _lbl_pa.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        ph_ctrl.addWidget(_lbl_pa)
        self._ph_area = QComboBox(ph_w)
        self._ph_area.setFont(Fonts.small)
        self._ph_area.setFixedHeight(UIScale.px(22))
        for area in Area:
            self._ph_area.addItem(area.value, area)
        ph_ctrl.addWidget(self._ph_area)
        _lbl_pi = QLabel("  Item:", ph_w)
        _lbl_pi.setFont(Fonts.mixed_small)
        _lbl_pi.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        ph_ctrl.addWidget(_lbl_pi)
        self._ph_item = QComboBox(ph_w)
        self._ph_item.setFont(Fonts.small)
        self._ph_item.setFixedHeight(UIScale.px(22))
        ph_ctrl.addWidget(self._ph_item, 1)
        self._ph_area.currentIndexChanged.connect(self._on_ph_area_change)
        self._ph_item.currentIndexChanged.connect(self._refresh_price_history)
        ph_lay.addLayout(ph_ctrl)
        self._ph_chart = _LineChart(ph_w)
        ph_lay.addWidget(self._ph_chart, 1)
        tabs.addTab(ph_w, f"{Sym.TREND_UP}  History")

        # ── Tab 3: Price Comparison (cross-area board) ────────────────────
        pc_w = QWidget(); pc_lay = QVBoxLayout(pc_w)
        pc_lay.setContentsMargins(UIScale.px(6), UIScale.px(4),
                                  UIScale.px(6), UIScale.px(4))
        pc_lay.setSpacing(UIScale.px(6))
        pc_ctrl = QHBoxLayout()
        _lbl_ci = QLabel("Item:", pc_w)
        _lbl_ci.setFont(Fonts.mixed_small)
        _lbl_ci.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        pc_ctrl.addWidget(_lbl_ci)
        self._pc_item = QComboBox(pc_w)
        self._pc_item.setFont(Fonts.small)
        self._pc_item.setFixedHeight(UIScale.px(22))
        # Populate with items that appear in at least one market
        _seen_keys: set = set()
        for _a2 in Area:
            _m2 = getattr(self.game, "markets", {}).get(_a2)
            if _m2:
                _seen_keys.update(_m2.item_keys)
        for _key2 in sorted(_seen_keys):
            _itm2 = ALL_ITEMS.get(_key2)
            if _itm2:
                self._pc_item.addItem(_itm2.name, _key2)
        self._pc_item.currentIndexChanged.connect(self._refresh_comparison)
        pc_ctrl.addWidget(self._pc_item, 1)
        pc_ctrl.addStretch()
        pc_lay.addLayout(pc_ctrl)

        pc_note = QLabel("Compare one good across every area. Values show gold per unit and relative difference versus your current area.", pc_w)
        pc_note.setFont(Fonts.tiny)
        pc_note.setWordWrap(True)
        pc_note.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        pc_lay.addWidget(pc_note)

        pc_metrics = QHBoxLayout()
        self._pc_metrics: Dict[str, QLabel] = {}
        for key, title, color in [
            ("buy", "Cheapest Buy Area", P.green),
            ("sell", "Best Sell Area", P.gold),
            ("spread", "Buy Price Range", P.amber),
            ("focus", "Current Area Delta", P.cream),
        ]:
            card, value = self._metric_card(pc_w, title, color)
            self._pc_metrics[key] = value
            pc_metrics.addWidget(card, 1)
        pc_lay.addLayout(pc_metrics)

        self._pc_table = DataTable(pc_w, self._COMPARE_COLS, row_height=28, stretch_last=False)
        self._pc_table.row_selected.connect(self._refresh_compare_detail)
        pc_lay.addWidget(self._pc_table, 1)
        self._pc_detail_lbl = QLabel("Select an area to compare it directly against your current market for the selected good.", pc_w)
        self._pc_detail_lbl.setFont(Fonts.mono_small)
        self._pc_detail_lbl.setWordWrap(True)
        self._pc_detail_lbl.setStyleSheet(f"color:{P.cream}; background:transparent;")
        pc_lay.addWidget(self._pc_detail_lbl)
        tabs.addTab(pc_w, f"{Sym.EXCHANGE}  Compare")

        # ── Tab 4: Local Trends (multi-line, top items in selected area) ──
        lt_w = QWidget(); lt_lay = QVBoxLayout(lt_w)
        lt_lay.setContentsMargins(UIScale.px(6), UIScale.px(4),
                                  UIScale.px(6), UIScale.px(4))
        lt_lay.setSpacing(UIScale.px(4))
        lt_ctrl = QHBoxLayout()
        _lbl_la = QLabel(f"{Sym.LOCATION} Area:", lt_w)
        _lbl_la.setFont(Fonts.mixed_small)
        _lbl_la.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        lt_ctrl.addWidget(_lbl_la)
        self._lt_area = QComboBox(lt_w)
        self._lt_area.setFont(Fonts.small)
        self._lt_area.setFixedHeight(UIScale.px(22))
        for area in Area:
            self._lt_area.addItem(area.value, area)
        self._lt_area.currentIndexChanged.connect(self._refresh_trends)
        lt_ctrl.addWidget(self._lt_area)
        lt_ctrl.addStretch()
        lt_lay.addLayout(lt_ctrl)
        lt_note = QLabel("Top movers in the selected area. Values show current gold-per-unit price against the trailing 7-day average.", lt_w)
        lt_note.setFont(Fonts.tiny)
        lt_note.setWordWrap(True)
        lt_note.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        lt_lay.addWidget(lt_note)
        lt_split = QSplitter(Qt.Orientation.Horizontal, lt_w)
        lt_split.setChildrenCollapsible(False)
        lt_left = QWidget(lt_split)
        lt_left_lay = QVBoxLayout(lt_left)
        lt_left_lay.setContentsMargins(0, 0, 0, 0)
        self._lt_table = DataTable(lt_left, self._TREND_COLS, row_height=28, stretch_last=False)
        self._lt_table.row_selected.connect(self._refresh_trend_detail)
        lt_left_lay.addWidget(self._lt_table)
        lt_right = QWidget(lt_split)
        lt_right_lay = QVBoxLayout(lt_right)
        lt_right_lay.setContentsMargins(0, 0, 0, 0)
        self._lt_chart = _LineChart(lt_right)
        lt_right_lay.addWidget(self._lt_chart, 1)
        self._lt_detail_lbl = QLabel("Select a good to inspect its price path in this area.", lt_right)
        self._lt_detail_lbl.setFont(Fonts.mono_small)
        self._lt_detail_lbl.setWordWrap(True)
        self._lt_detail_lbl.setStyleSheet(f"color:{P.cream}; background:transparent;")
        lt_right_lay.addWidget(self._lt_detail_lbl)
        lt_split.addWidget(lt_left)
        lt_split.addWidget(lt_right)
        lt_split.setStretchFactor(0, 3)
        lt_split.setStretchFactor(1, 2)
        lt_lay.addWidget(lt_split, 1)
        tabs.addTab(lt_w, f"{Sym.NEWS}  Trends")

        # ── Tab 5: Net Worth (line chart of player's wealth over time) ────
        nw_w = QWidget(); nw_lay = QVBoxLayout(nw_w)
        nw_lay.setContentsMargins(UIScale.px(6), UIScale.px(4),
                                  UIScale.px(6), UIScale.px(4))
        self._nw_chart = _LineChart(nw_w)
        nw_lay.addWidget(self._nw_chart, 1)
        tabs.addTab(nw_w, f"{Sym.NETWORTH}  Net Worth")

        tabs.currentChanged.connect(self._on_chart_tab_change)
        return tabs

    def _build_right_panel(self) -> QTabWidget:
        """Right column: Contracts / Loans / Voyages tabs."""
        tabs = QTabWidget(self)
        tabs.setObjectName("obligationsTabs")
        tabs.setStyleSheet(self._chart_tab_style())

        # Contracts tab
        c_w = QWidget(); c_lay = QVBoxLayout(c_w)
        c_lay.setContentsMargins(UIScale.px(6), UIScale.px(6),
                                 UIScale.px(6), UIScale.px(6))
        c_lay.setSpacing(UIScale.px(4))
        self._d_contracts_lbl = QLabel("No active contracts.", c_w)
        self._d_contracts_lbl.setFont(Fonts.mixed_small)
        self._d_contracts_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        self._d_contracts_lbl.setWordWrap(True)
        self._d_contracts_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        c_lay.addWidget(self._d_contracts_lbl)
        c_lay.addStretch()
        tabs.addTab(c_w, f"{Sym.CONTRACT}  Contracts")

        # Loans tab
        l_w = QWidget(); l_lay = QVBoxLayout(l_w)
        l_lay.setContentsMargins(UIScale.px(6), UIScale.px(6),
                                 UIScale.px(6), UIScale.px(6))
        l_lay.setSpacing(UIScale.px(4))
        self._d_loans_lbl = QLabel("No active loans.", l_w)
        self._d_loans_lbl.setFont(Fonts.mixed_small)
        self._d_loans_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        self._d_loans_lbl.setWordWrap(True)
        self._d_loans_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        l_lay.addWidget(self._d_loans_lbl)
        l_lay.addStretch()
        tabs.addTab(l_w, f"{Sym.FINANCE}  Loans")

        # Voyages tab
        v_w = QWidget(); v_lay = QVBoxLayout(v_w)
        v_lay.setContentsMargins(UIScale.px(6), UIScale.px(6),
                                 UIScale.px(6), UIScale.px(6))
        v_lay.setSpacing(UIScale.px(4))
        self._d_voyages_lbl = QLabel("No active voyages.", v_w)
        self._d_voyages_lbl.setFont(Fonts.mixed_small)
        self._d_voyages_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        self._d_voyages_lbl.setWordWrap(True)
        self._d_voyages_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        v_lay.addWidget(self._d_voyages_lbl)
        v_lay.addStretch()
        tabs.addTab(v_w, f"{Sym.VOYAGE}  Voyages")

        return tabs

    def _build_news_strip(self) -> QFrame:
        frame = QFrame(self)
        frame.setObjectName("dashPanel")
        frame.setFixedHeight(UIScale.px(82))
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(UIScale.px(8), UIScale.px(4),
                               UIScale.px(8), UIScale.px(4))
        lay.setSpacing(UIScale.px(2))
        hrow = QHBoxLayout()
        hdr = QLabel(f"{Sym.NEWS}  Recent News & Events", frame)
        hdr.setFont(Fonts.mixed_small_bold)
        hdr.setStyleSheet(f"color:{P.amber}; background:transparent; border:none;")
        hrow.addWidget(hdr)
        hrow.addStretch()
        lay.addLayout(hrow)
        sep = QFrame(frame)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{P.border}; border:none;")
        lay.addWidget(sep)
        self._d_news_lbl = QLabel("No recent news.", frame)
        self._d_news_lbl.setFont(Fonts.mixed_small)
        self._d_news_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        self._d_news_lbl.setWordWrap(True)
        lay.addWidget(self._d_news_lbl)
        return frame

    # ── Chart refresh helpers ──────────────────────────────────────────────

    def _get_area(self, combo: QComboBox) -> "Area":
        data = combo.currentData()
        return data if isinstance(data, Area) else Area.CITY

    def _on_chart_tab_change(self, idx: int) -> None:
        self._refresh_chart_by_idx(idx)

    def _refresh_chart_by_idx(self, idx: Optional[int] = None) -> None:
        if not self._built:
            return
        if idx is None:
            idx = self._chart_tabs.currentIndex()
        if   idx == 0: self._refresh_overview()
        elif idx == 1: self._refresh_price_history()
        elif idx == 2: self._refresh_comparison()
        elif idx == 3: self._refresh_trends()
        elif idx == 4: self._refresh_networth()

    def _refresh_overview(self) -> None:
        g      = self.game
        area   = self._get_area(self._ov_area)
        mkt    = getattr(g, "markets", {}).get(area)
        if not mkt:
            self._ov_table.load([])
            for lbl in getattr(self, "_ov_metrics", {}).values():
                lbl.setText("—")
            self._refresh_overview_detail(None)
            return
        season  = getattr(g, "season", Season.SPRING)
        trading = getattr(getattr(g, "skills", None), "trading", 1)
        rows: List[Dict[str, Any]] = []
        cheapest_row: Optional[Dict[str, Any]] = None
        highest_sell: Optional[Dict[str, Any]] = None
        best_discount: Optional[Dict[str, Any]] = None
        biggest_move: Optional[Dict[str, Any]] = None
        biggest_move_pct = -1.0
        for key in sorted(mkt.item_keys, key=lambda item_key: getattr(ALL_ITEMS.get(item_key), "name", item_key)):
            item_obj = ALL_ITEMS.get(key)
            if not item_obj:
                continue
            buy_p  = mkt.get_buy_price(key, season, trading)
            sell_p = mkt.get_sell_price(key, season, trading)
            base_p = float(getattr(item_obj, "base_price", buy_p) or buy_p)
            _, trend_pct, trend_label, trend_tag = self._market_trend(mkt.history.get(key, []), buy_p)
            buy_delta = ((buy_p / base_p) - 1.0) * 100.0 if base_p else 0.0
            sell_delta = ((sell_p / base_p) - 1.0) * 100.0 if base_p else 0.0
            row = {
                "item": item_obj.name,
                "cat": item_obj.category.name.replace("_", " ").title(),
                "buy": f"{buy_p:,.1f}",
                "sell": f"{sell_p:,.1f}",
                "base": f"{base_p:,.1f}",
                "buy_base": f"{buy_delta:+.0f}%",
                "sell_base": f"{sell_delta:+.0f}%",
                "trend": f"{trend_label} {trend_pct:+.0f}%",
                "_tag": "green" if buy_delta <= -10 else ("gold" if sell_delta >= 10 else trend_tag),
            }
            rows.append(row)
            if cheapest_row is None or buy_p < float(cheapest_row["buy"].replace(",", "")):
                cheapest_row = row
            if highest_sell is None or sell_p > float(highest_sell["sell"].replace(",", "")):
                highest_sell = row
            if best_discount is None or buy_delta < float(best_discount["buy_base"].replace("%", "")):
                best_discount = row
            if abs(trend_pct) > biggest_move_pct:
                biggest_move_pct = abs(trend_pct)
                biggest_move = row
        self._ov_table.load(rows)
        if cheapest_row:
            self._ov_metrics["cheap"].setText(f"{cheapest_row['item']}  ·  {cheapest_row['buy']} g/u")
        if highest_sell:
            self._ov_metrics["payout"].setText(f"{highest_sell['item']}  ·  {highest_sell['sell']} g/u")
        if best_discount:
            self._ov_metrics["discount"].setText(f"{best_discount['item']}  ·  {best_discount['buy_base']}")
        if biggest_move:
            self._ov_metrics["trend"].setText(f"{biggest_move['item']}  ·  {biggest_move['trend']}")
        self._refresh_overview_detail(rows[0] if rows else None)

    def _on_ph_area_change(self) -> None:
        area = self._get_area(self._ph_area)
        mkt  = getattr(self.game, "markets", {}).get(area)
        self._ph_item.blockSignals(True)
        self._ph_item.clear()
        if mkt:
            for key in mkt.item_keys:
                item_obj = ALL_ITEMS.get(key)
                if item_obj:
                    self._ph_item.addItem(item_obj.name, key)
        self._ph_item.blockSignals(False)
        self._refresh_price_history()

    def _refresh_price_history(self) -> None:
        area     = self._get_area(self._ph_area)
        mkt      = getattr(self.game, "markets", {}).get(area)
        item_key = self._ph_item.currentData()
        if not mkt or not item_key:
            self._ph_chart.set_data([])
            return
        history  = mkt.history.get(item_key, [])
        pts      = [(float(pp.day), float(pp.price)) for pp in history]
        item_obj = ALL_ITEMS.get(item_key)
        label    = item_obj.name if item_obj else item_key
        self._ph_chart.set_data([(label, P.gold, pts)], x_label="Day", y_label="Price")

    def _refresh_comparison(self) -> None:
        g        = self.game
        item_key = self._pc_item.currentData()
        if not item_key:
            self._pc_table.load([])
            for lbl in getattr(self, "_pc_metrics", {}).values():
                lbl.setText("—")
            self._refresh_compare_detail(None)
            return
        season   = getattr(g, "season", Season.SPRING)
        cur_area = getattr(g, "current_area", Area.CITY)
        current_market = getattr(g, "markets", {}).get(cur_area)
        current_buy = current_market.get_buy_price(item_key, season) if current_market and item_key in current_market.item_keys else 0.0
        current_sell = current_market.get_sell_price(item_key, season) if current_market and item_key in current_market.item_keys else 0.0
        item_obj = ALL_ITEMS.get(item_key)
        base_p = float(getattr(item_obj, "base_price", 0.0) or 0.0)
        rows: List[Dict[str, Any]] = []
        best_buy: Optional[Tuple[Area, float]] = None
        best_sell: Optional[Tuple[Area, float]] = None
        buy_vals: List[float] = []
        for area in Area:
            mkt = getattr(g, "markets", {}).get(area)
            if not mkt or item_key not in mkt.item_keys:
                continue
            buy_p  = mkt.get_buy_price(item_key, season)
            sell_p = mkt.get_sell_price(item_key, season)
            _, trend_pct, trend_label, trend_tag = self._market_trend(mkt.history.get(item_key, []), buy_p)
            row = {
                "area": area.value,
                "buy": f"{buy_p:,.1f}",
                "sell": f"{sell_p:,.1f}",
                "vs_buy": f"{buy_p - current_buy:+,.1f}",
                "vs_sell": f"{sell_p - current_sell:+,.1f}",
                "trend": f"{trend_label} {trend_pct:+.0f}%",
                "base_delta": f"{(((sell_p / base_p) - 1.0) * 100.0):+.0f}%" if base_p else "—",
                "_tag": "gold" if area == cur_area else trend_tag,
                "area_enum": area,
            }
            rows.append(row)
            buy_vals.append(buy_p)
            if best_buy is None or buy_p < best_buy[1]:
                best_buy = (area, buy_p)
            if best_sell is None or sell_p > best_sell[1]:
                best_sell = (area, sell_p)
        self._pc_table.load(rows)
        if best_buy:
            self._pc_metrics["buy"].setText(f"{best_buy[0].value}  ·  {best_buy[1]:,.1f} g/u")
        if best_sell:
            self._pc_metrics["sell"].setText(f"{best_sell[0].value}  ·  {best_sell[1]:,.1f} g/u")
        if buy_vals:
            self._pc_metrics["spread"].setText(f"{min(buy_vals):,.1f} to {max(buy_vals):,.1f} g/u")
        self._pc_metrics["focus"].setText(f"Current area: {cur_area.value}  ·  Buy {current_buy:,.1f} g/u  ·  Sell {current_sell:,.1f} g/u")
        self._refresh_compare_detail(rows[0] if rows else None)

    def _refresh_trends(self) -> None:
        g      = self.game
        area   = self._get_area(self._lt_area)
        mkt    = getattr(g, "markets", {}).get(area)
        if not mkt:
            if hasattr(self, "_lt_table"):
                self._lt_table.load([])
            self._lt_chart.set_data([])
            self._refresh_trend_detail(None)
            return
        season  = getattr(g, "season", Season.SPRING)
        rows: List[Dict[str, Any]] = []
        for key in sorted(mkt.item_keys, key=lambda item_key: mkt.get_price(item_key, season, noise=False), reverse=True)[:8]:
            current = float(mkt.get_price(key, season, noise=False))
            history = list(mkt.history.get(key, []))
            pts = [(float(pp.day), float(pp.price)) for pp in history[-40:]]
            if len(pts) < 2:
                day_now = float(getattr(self.game, "day", 1))
                pts = [(max(0.0, day_now - 1.0), current), (day_now, current)]
            trailing = [price for _, price in pts[-7:]] or [current]
            avg7 = sum(trailing) / max(1, len(trailing))
            delta_pct = ((current / avg7) - 1.0) * 100.0 if avg7 else 0.0
            item_obj = ALL_ITEMS.get(key)
            base_price = float(getattr(item_obj, "base_price", current) or current)
            base_delta = ((current / base_price) - 1.0) * 100.0 if base_price else 0.0
            if delta_pct >= 8.0:
                state, tag = "Rising", "green"
            elif delta_pct <= -8.0:
                state, tag = "Falling", "red"
            else:
                state, tag = "Stable", "yellow"
            rows.append({
                "item": getattr(item_obj, "name", key),
                "current": f"{current:,.1f}",
                "avg7": f"{avg7:,.1f}",
                "delta": f"{delta_pct:+.0f}%",
                "base_delta": f"{base_delta:+.0f}%",
                "state": state,
                "item_key": key,
                "points": pts,
                "_tag": tag,
            })
        if hasattr(self, "_lt_table"):
            self._lt_table.load(rows)
        self._refresh_trend_detail(rows[0] if rows else None)

    def _refresh_networth(self) -> None:
        nw_hist = getattr(self.game, "net_worth_history", [])
        if not nw_hist:
            self._nw_chart.set_data([])
            return
        pts = [(float(i), float(v)) for i, v in enumerate(nw_hist)]
        self._nw_chart.set_data(
            [("Net Worth", P.gold, pts)], x_label="Day", y_label="Gold (g)"
        )

    # ── Main refresh ──────────────────────────────────────────────────────

    def refresh(self) -> None:
        if not self._built:
            return
        g   = self.game
        inv = getattr(g, "inventory", None)

        # ── Time label ────────────────────────────────────────────────────
        day    = int(getattr(g, "day",    1))
        year   = int(getattr(g, "year",   1))
        season = getattr(g, "season", None)
        sea_s  = season.value if season and hasattr(season, "value") else "?"
        sea_c  = SEASON_COLOURS.get(season, P.gold)
        self._time_lbl.setText(f"Day {day}  \u00b7  {sea_s}  \u00b7  Year {year}")
        self._time_lbl.setStyleSheet(f"color:{sea_c}; background:transparent;")

        # ── Player stats ──────────────────────────────────────────────────
        self._d_name_val.setText(getattr(g, "player_name", "Merchant"))
        self._d_day_val.setText(str(day))
        self._d_sea_val.setText(sea_s)
        self._d_sea_val.setStyleSheet(f"color:{sea_c}; background:transparent;")
        self._d_yr_val.setText(str(year))

        used = int(getattr(g, "daily_time_units",  0))
        mxs  = int(getattr(g, "DAILY_TIME_UNITS",  6))
        free = max(0, mxs - used)
        slot_col = P.red if free == 0 else P.amber if free <= 1 else P.green
        self._d_slot_val.setText(f"{free}/{mxs}")
        self._d_slot_val.setStyleSheet(f"color:{slot_col}; background:transparent;")

        gold = getattr(inv, "gold", 0.0) if inv else 0.0
        self._d_gold_val.setText(f"{gold:,.0f} g")

        rep      = int(getattr(g, "reputation", 0))
        rl, rc   = rep_label(rep)
        self._d_rep_val.setText(f"{rl} ({rep})")
        self._d_rep_val.setStyleSheet(f"color:{rc}; background:transparent;")

        nw_fn = getattr(g, "_net_worth", None)
        nw    = nw_fn() if callable(nw_fn) else float(getattr(g, "net_worth", gold))
        self._d_nw_val.setText(f"{nw:,.0f} g")

        loc   = getattr(g, "current_area", None)
        loc_s = loc.value if loc and hasattr(loc, "value") else str(loc or "?")
        self._d_loc_val.setText(loc_s)

        heat     = int(getattr(g, "heat", 0))
        heat_col = P.red if heat > 60 else P.amber if heat > 30 else P.green
        self._d_heat_val.setText(str(heat))
        self._d_heat_val.setStyleSheet(f"color:{heat_col}; background:transparent;")

        at       = getattr(g, "active_title", "")
        td       = TITLES_BY_ID.get(at, {}) if at else {}
        title_s  = td.get("name", at) if td else (at or "\u2014")
        self._d_title_val.setText(title_s or "\u2014")

        # ── Inventory snapshot ────────────────────────────────────────────
        items_d = (getattr(inv, "items", {}) if inv else {}) or {}
        if items_d:
            ranked = sorted(
                ((k, v) for k, v in items_d.items() if v > 0),
                key=lambda kv: (
                    getattr(ALL_ITEMS.get(kv[0]), "base_price", 0.0) * kv[1]
                ),
                reverse=True,
            )[:8]
            self._d_inv_lbl.setText(
                "\n".join(
                    f"{Sym.SECTION}  {qty:>4}\u00d7  "
                    f"{getattr(ALL_ITEMS.get(k), 'name', k)}"
                    for k, qty in ranked
                )
            )
        else:
            self._d_inv_lbl.setText("Nothing in inventory.")

        # ── Businesses snapshot ───────────────────────────────────────────
        bizs = getattr(g, "businesses", [])
        if bizs:
            lines = []
            for b in bizs[:7]:
                lvl  = getattr(b, "level", 1)
                brok = f"{Sym.WARNING} " if getattr(b, "broken_down", False) else ""
                lines.append(f"{brok}{b.name} Lv{lvl}")
            if len(bizs) > 7:
                lines.append(f"\u2026 +{len(bizs) - 7} more")
            self._d_biz_lbl.setText("\n".join(lines))
        else:
            self._d_biz_lbl.setText("No businesses owned.")

        # ── Contracts ─────────────────────────────────────────────────────
        abs_day  = getattr(g, "_absolute_day", lambda: 0)
        abs_day  = abs_day() if callable(abs_day) else 0
        active_c = [c for c in getattr(g, "contracts", [])
                    if not getattr(c, "fulfilled", True)]
        if active_c:
            lines = []
            for c in active_c[:8]:
                dl     = getattr(c, "deadline_day", abs_day + 999) - abs_day
                ik     = getattr(c, "item_key", "")
                nm     = getattr(ALL_ITEMS.get(ik), "name", ik)
                dest   = getattr(c, "destination", None)
                dest_s = dest.value if dest and hasattr(dest, "value") else "?"
                qty    = getattr(c, "quantity", 0)
                mark   = Sym.WARNING if dl <= 3 else Sym.PROGRESS
                col    = P.red if dl <= 3 else P.amber if dl <= 7 else P.fg_dim
                lines.append(
                    f"{mark}  {qty}\u00d7 {nm[:12]} \u2192 {dest_s[:8]}  [{dl}d]"
                )
            self._d_contracts_lbl.setText("\n".join(lines))
        else:
            self._d_contracts_lbl.setText("No active contracts.")

        # ── Loans & CDs ───────────────────────────────────────────────────
        loans = getattr(g, "loans", [])
        cds   = getattr(g, "cds",   [])
        if loans or cds:
            lines = []
            for loan in loans[:4]:
                pmt = getattr(loan, "monthly_payment", 0.0)
                mo  = getattr(loan, "months_remaining", 0)
                lines.append(f"{Sym.FINANCE}  {pmt:.0f}g/mo  \u00b7  {mo} mo left")
            for cd in cds[:4]:
                pr  = getattr(cd, "principal", 0.0)
                rt  = getattr(cd, "rate", 0.0)
                lines.append(f"{Sym.GOLD}  {pr:.0f}g CD  +{rt*100:.0f}%")
            self._d_loans_lbl.setText("\n".join(lines))
        else:
            self._d_loans_lbl.setText("No active loans.")

        # ── Active voyages ────────────────────────────────────────────────
        sailing = [v for v in getattr(g, "voyages", [])
                   if getattr(v, "status", "") == "sailing"]
        if sailing:
            lines = []
            for v in sailing[:7]:
                dr  = getattr(v, "days_remaining", 0)
                dk  = getattr(v, "destination_key", "")
                dn  = VOYAGE_PORTS.get(dk, {}).get("name", dk)
                sn  = getattr(v, "ship_name", "?")
                lines.append(f"{Sym.VOYAGE}  {sn} \u2192 {dn[:8]}  [{dr}d]")
            self._d_voyages_lbl.setText("\n".join(lines))
        else:
            self._d_voyages_lbl.setText("No voyages sailing.")

        # ── News ──────────────────────────────────────────────────────────
        news = list(getattr(g, "news_feed", []))
        if news:
            recent = news[-3:]
            lines  = []
            for entry in recent:
                if isinstance(entry, (list, tuple)) and entry:
                    hl = str(entry[-1])
                else:
                    hl = str(entry)
                lines.append(f"{Sym.SECTION}  {hl[:80]}")
            self._d_news_lbl.setText("     ".join(lines))
        else:
            self._d_news_lbl.setText("No recent news.")

        # ── Sync area combos to current player location ───────────────────
        cur_area = getattr(g, "current_area", Area.CITY)
        for combo in (self._ov_area, self._ph_area, self._lt_area):
            idx = combo.findData(cur_area)
            if idx >= 0 and combo.currentIndex() != idx:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)

        # Populate price-history item combo on first refresh
        if self._ph_item.count() == 0:
            self._on_ph_area_change()

        # Refresh whichever chart tab is currently visible
        self._refresh_chart_by_idx()


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
        icon_lbl.setFont(Fonts.icon)
        icon_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        icon_lbl.setFixedWidth(UIScale.px(32))
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(icon_lbl)
        lay.addSpacing(UIScale.px(8))

        # Text block
        txt = QVBoxLayout()
        txt.setSpacing(2)
        self._t_lbl = QLabel(title, self)
        self._t_lbl.setFont(Fonts.body_bold)
        self._t_lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        self._t_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._s_lbl = QLabel(subtitle, self)
        self._s_lbl.setFont(Fonts.tiny)
        self._s_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        self._s_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        txt.addWidget(self._t_lbl)
        txt.addWidget(self._s_lbl)
        lay.addLayout(txt, 1)

        # Store icon label ref for hover colour change
        self._icon_lbl = icon_lbl

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
            # Brief darken on click
            self._set_hovered_style(True, pressed=True)
            self.clicked.emit()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        self._set_hovered_style(self.underMouse())
        super().mouseReleaseEvent(ev)

    def enterEvent(self, event: QEvent) -> None:
        self._set_hovered_style(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._set_hovered_style(False)
        super().leaveEvent(event)

    def _set_hovered_style(self, hovered: bool, pressed: bool = False) -> None:
        icon_col  = P.fg_header if hovered else P.gold
        title_col = P.fg_header if hovered else P.fg
        subs_col  = P.fg        if hovered else P.fg_dim
        if pressed:
            icon_col  = P.amber
            title_col = P.amber
        self._icon_lbl.setStyleSheet(f"color:{icon_col}; background:transparent;")
        self._t_lbl.setStyleSheet(f"color:{title_col}; background:transparent;")
        self._s_lbl.setStyleSheet(f"color:{subs_col}; background:transparent;")


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
        icon_lbl.setFont(Fonts.icon)
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
                lambda _=False, k=key, t=title: self.app.goto(k)
                if k in self.app.screens else
                self.app.message_bar.warn(f"'{t}' not yet implemented.")
            )
            grid.addWidget(card, i // 2, i % 2)

        root.addWidget(grid_widget)
        root.addStretch()

    def _build_summary(self) -> Optional[QWidget]:
        """Override to return a summary widget shown above the card grid."""
        return None


class TradeHubScreen(_DomainHubScreen):
    _DOMAIN_ICON  = Sym.TRADE
    _DOMAIN_TITLE = "Trade & Travel"
    _DOMAIN_DESC  = "Trade local markets, scout arbitrage, and travel routes."
    _CARDS = [
        ("trade",     Sym.TRADE,     "Trade",       "Buy, sell, haggle, and scout arbitrage"),
        ("travel",    Sym.TRAVEL,    "Travel",      "Plan routes, costs, risks, and departures"),
        ("inventory", Sym.INVENTORY, "Inventory",    "Manage your carried goods & weight"),
        ("wait",      Sym.WAIT_REST, "Rest & Wait",  "Pass time and recover action slots"),
    ]


class OperationsHubScreen(_DomainHubScreen):
    _DOMAIN_ICON  = Sym.OPERATIONS
    _DOMAIN_TITLE = "Operations"
    _DOMAIN_DESC  = "Manage businesses, contracts and logistical assets."
    _CARDS = [
        ("businesses",  Sym.OPERATIONS,  "Businesses",  "Own and operate commercial enterprises"),
        ("managers",    Sym.MANAGER,     "Managers",    "Hire and assign workforce managers"),
        ("contracts",   Sym.CONTRACT,    "Contracts",   "Fulfil delivery and supply contracts"),
        ("real_estate", Sym.REAL_ESTATE, "Real Estate", "Buy and manage property holdings"),
        ("voyage",      Sym.VOYAGE,      "Voyage",      "Send ships on trading voyages"),
        ("skills",      Sym.SKILLS,      "Skills",      "Spend experience points and train"),
        ("smuggling",   Sym.SMUGGLING,   "Smuggling",   "Illicit trade — high risk, high reward"),
        ("gamble",      Sym.GAMBLE,      "Gambling",    "Try your luck at the gaming tables"),
    ]


class FinanceHubScreen(_DomainHubScreen):
    _DOMAIN_ICON  = Sym.FINANCE
    _DOMAIN_TITLE = "Finance"
    _DOMAIN_DESC  = "Banking, investments, lending and market instruments."
    _CARDS = [
        ("finance",  Sym.FINANCE,   "Banking",       "Deposits, withdrawals and interest"),
        ("lending",  Sym.LENDING,   "Lending",       "Issue or take citizen loans"),
        ("stocks",   Sym.TREND_UP,  "Stock Market",  "Trade company shares and equities"),
        ("funds",    Sym.NETWORTH,  "Fund Mgmt",     "Manage investment portfolios"),
    ]


class IntelligenceHubScreen(_DomainHubScreen):
    _DOMAIN_ICON  = Sym.INTELLIGENCE
    _DOMAIN_TITLE = "Intelligence"
    _DOMAIN_DESC  = "Market data, price trends and world news."
    _CARDS = [
        ("market", Sym.EXCHANGE, "Market Info",   "Price lists, trends and forecasts"),
        ("news",   Sym.NEWS,     "News & Events", "World headlines and trade disruptions"),
    ]


class SocialHubScreen(_DomainHubScreen):
    _DOMAIN_ICON  = Sym.SOCIAL
    _DOMAIN_TITLE = "Social"
    _DOMAIN_DESC  = "Build alliances, manage reputation and exert influence."
    _CARDS = [
        ("social",    Sym.SOCIAL,    "Social Hub",  "Diplomacy, relationships and favours"),
        ("influence", Sym.INFLUENCE, "Influence",   "Spend and earn reputation points"),
    ]


class ProfileHubScreen(_DomainHubScreen):
    _DOMAIN_ICON  = Sym.PROFILE
    _DOMAIN_TITLE = "Character"
    _DOMAIN_DESC  = "Your skills, progress, licenses and personal profile."
    _CARDS = [
        ("skills",    Sym.SKILLS,    "Skills",       "Skill tree and ability upgrades"),
        ("licenses",  Sym.LICENSES,  "Licenses",     "Trade and travel permits"),
        ("progress",  Sym.PROGRESS,  "Achievements", "Milestones and long-term goals"),
        ("settings",  Sym.SETTINGS,  "Settings",     "Game options and preferences"),
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
            f"color:{P.fg_header if hovered else P.gold}; background:transparent;"
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
        ("trade",     Sym.TRADE,     "Trade",       "Buy & sell at the local market",  P.gold),
        ("travel",    Sym.TRAVEL,    "Travel",       "Journey to a new region",         P.amber),
        ("inventory", Sym.INVENTORY, "Inventory",   "Manage cargo & equipment",        P.gold),
        ("wait",      Sym.WAIT_REST, "Rest & Wait", "Pass time · advance the day",     P.amber),
    ]

    # (section_name, accent_colour, [(key, emoji, title, subtitle), ...])
    _SECTIONS: List[Tuple[str, str, List[Tuple[str, str, str, str]]]] = [
        ("OPERATIONS", P.gold, [
            ("businesses",  Sym.OPERATIONS,  "Businesses",    "Production & workshops"),
            ("managers",    Sym.MANAGER,     "Managers",      "Hire & manage NPC staff"),
            ("finance",     Sym.FINANCE,     "Finance",       "Banking & certificates"),
            ("contracts",   Sym.CONTRACT,    "Contracts",     "Delivery orders"),
            ("lending",     Sym.LENDING,     "Lending",       "Issue citizen loans"),
            ("stocks",      Sym.STOCKS,      "Stock Market",  "Buy & sell shares"),
            ("funds",       Sym.FINANCE,     "Fund Mgmt",     "Manage client capital"),
            ("real_estate", Sym.REAL_ESTATE, "Real Estate",   "Buy, build & lease"),
            ("skills",      Sym.SKILLS,      "Skills",        "Improve your character"),
            ("smuggling",   Sym.SMUGGLING,   "Smuggling Den", "Black market deals"),
            ("gamble",      Sym.GAMBLE,      "Gamble",        "Try the Mystery Coffer"),
            ("voyage",      Sym.VOYAGE,      "Voyage",        "International sea routes"),
        ]),
        ("INTELLIGENCE", P.gold, [
            ("market",  Sym.INTELLIGENCE, "Market Info",   "Prices & trade routes"),
            ("news",    Sym.NEWS,         "News & Events", "World events & impacts"),
            ("social",  Sym.SOCIAL,       "Social Hub",    "Leaderboard, friends & guilds"),
        ]),
        ("CHARACTER", P.gold, [
            ("influence", Sym.INFLUENCE, "Influence",  "Reputation & market power"),
            ("licenses",  Sym.LICENSES,  "Licenses",   "Unlock new capabilities"),
            ("progress",  Sym.PROGRESS,  "Progress",   "Achievements & milestones"),
            ("settings",  Sym.SETTINGS,  "Settings",   "Options & hotkeys"),
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

        self._alert_icon_lbl = QLabel(Sym.WARNING, self._alert_strip)
        self._alert_icon_lbl.setFont(Fonts.icon)
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

            sec_lbl = QLabel(f"  {Sym.SECTION}  {sec_name}", inner)
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

        save_btn = self.action_button(f"{Sym.SAVE}  Save", self._do_save)
        save_btn.setFixedHeight(UIScale.px(32))

        bk_btn = self.action_button(
            f"{Sym.WARNING}  File Bankruptcy", self._file_bankruptcy, role="danger"
        )
        bk_btn.setFixedHeight(UIScale.px(32))

        footer.addWidget(save_btn)
        footer.addWidget(bk_btn)
        footer.addStretch()

        quit_btn = self.action_button(
            f"{Sym.NO}  Save & Quit", self.app.quit_game, role="danger"
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
                f"[!]  {n} business{'es' if n > 1 else ''} broken — needs repair"
            )
            urgent = True

        if active_c:
            nearest = min(active_c, key=lambda c: c.deadline_day - abs_day)
            dl = nearest.deadline_day - abs_day
            nm = ALL_ITEMS.get(
                nearest.item_key, type("_", (), {"name": "?"})()
            ).name
            marker = "[!]" if dl <= 3 else "[~]"
            alerts.append(
                f"{marker}  Contract: {nearest.quantity}× {nm}"
                f" → {nearest.destination.value}  [{dl}d left]"
            )
            if dl <= 3:
                urgent = True

        if heat > 70:
            alerts.append(f"{Sym.HEAT}  Heat {heat}/100 — smuggling risk critical")
            urgent = True
        elif heat > 50:
            alerts.append(f"{Sym.WARNING}  Heat {heat}/100 — cool down advised")

        if news and not alerts:
            # Only show news headline if there's nothing more pressing
            _, _, _, hl = news[0]
            alerts.append(f"{Sym.INVENTORY}  {hl[:90]}")

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
            self._sec_cards["smuggling"].set_context(f"{Sym.HEAT} heat {heat}", col)

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
        if (_popup_confirm(
                self,
                "File Bankruptcy",
                "This will erase ALL progress and start a brand-new game.\n\nThis cannot be undone.",
                confirm_text="Erase Save",
                confirm_role="danger",
            ) and hasattr(self.app, "_do_bankruptcy_restart")):
            self.app._do_bankruptcy_restart()


# ══════════════════════════════════════════════════════════════════════════════
# TRADE SCREEN  —  buy, sell, haggle, and arbitrage routes
# ══════════════════════════════════════════════════════════════════════════════

class TradeScreen(Screen):
    _BUY_COLS = [
        ("item", "Item", 180),
        ("category", "Category", 110),
        ("price", "Price", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("stock", "Stock", 64, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("trend", "Trend", 60, Qt.AlignmentFlag.AlignCenter),
        ("rarity", "Rarity", 88),
    ]
    _SELL_COLS = [
        ("item", "Item", 180),
        ("have", "Have", 60, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("sell_price", "Sell @", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("paid", "Paid @", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("return_pct", "Return", 72, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("profit", "Est. Profit", 88, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("local", "Local?", 62, Qt.AlignmentFlag.AlignCenter),
    ]
    _ARB_COLS = [
        ("item", "Item", 160),
        ("buy", "Buy", 72, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("sell", "Sell", 72, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("dest", "To", 120),
        ("profit_pct", "Profit%", 72, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("days", "Days", 56, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("gpd", "g/day", 68, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("stock", "Stock", 60, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]

    def build(self) -> None:
        self._haggle_item: Optional[str] = None
        self._haggle_discount: float = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12),
                                UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        hdr = QHBoxLayout()
        hdr.addWidget(self.section_label("Trade"))
        hdr.addStretch()
        self._status_lbl = QLabel(self)
        self._status_lbl.setFont(Fonts.mono_small)
        self._status_lbl.setStyleSheet(f"color:{P.amber}; background:transparent;")
        hdr.addWidget(self._status_lbl)
        root.addLayout(hdr)
        root.addWidget(self.h_sep())

        tabs = QTabWidget(self)
        tabs.setFont(Fonts.mixed_small)
        root.addWidget(tabs, 1)

        buy_tab = QWidget(self)
        buy_lay = QVBoxLayout(buy_tab)
        buy_lay.setContentsMargins(0, 0, 0, 0)
        buy_lay.setSpacing(UIScale.px(8))
        self._buy_table = DataTable(buy_tab, self._BUY_COLS, row_height=26)
        self._buy_table.row_selected.connect(self._on_buy_select)
        self._buy_table.row_double_clicked.connect(self._on_buy_double)
        self._buy_table.row_right_clicked.connect(self._on_buy_right_click)
        buy_lay.addWidget(self._buy_table, 1)
        buy_actions = QHBoxLayout()
        self._buy_btn = self.action_button(f"{Sym.YES}  Buy Selected", self._do_buy)
        self._buy_btn.setFixedHeight(UIScale.px(30))
        haggle_btn = self.action_button(f"{Sym.TRADE}  Haggle", self._do_haggle, role="secondary")
        haggle_btn.setFixedHeight(UIScale.px(30))
        buy_actions.addWidget(self._buy_btn)
        buy_actions.addWidget(haggle_btn)
        buy_actions.addStretch()
        self._buy_info = QLabel("Select an item to inspect pricing and limits.", buy_tab)
        self._buy_info.setFont(Fonts.mono_small)
        self._buy_info.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        buy_actions.addWidget(self._buy_info, 1)
        buy_lay.addLayout(buy_actions)
        tabs.addTab(buy_tab, f"{Sym.YES}  Buy")

        sell_tab = QWidget(self)
        sell_lay = QVBoxLayout(sell_tab)
        sell_lay.setContentsMargins(0, 0, 0, 0)
        sell_lay.setSpacing(UIScale.px(8))
        self._sell_table = DataTable(sell_tab, self._SELL_COLS, row_height=26)
        self._sell_table.row_selected.connect(self._on_sell_select)
        self._sell_table.row_double_clicked.connect(self._on_sell_double)
        sell_lay.addWidget(self._sell_table, 1)
        sell_actions = QHBoxLayout()
        sell_btn = self.action_button(f"{Sym.EXCHANGE}  Sell Selected", self._do_sell, role="danger")
        sell_btn.setFixedHeight(UIScale.px(30))
        sell_all_btn = self.action_button(f"{Sym.EXCHANGE}  Sell All", self._do_sell_all, role="danger")
        sell_all_btn.setFixedHeight(UIScale.px(30))
        sell_actions.addWidget(sell_btn)
        sell_actions.addWidget(sell_all_btn)
        sell_actions.addStretch()
        self._sell_info = QLabel("Select inventory to sell into the local market.", sell_tab)
        self._sell_info.setFont(Fonts.mono_small)
        self._sell_info.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        sell_actions.addWidget(self._sell_info, 1)
        sell_lay.addLayout(sell_actions)
        tabs.addTab(sell_tab, f"{Sym.EXCHANGE}  Sell")

        arb_tab = QWidget(self)
        arb_lay = QVBoxLayout(arb_tab)
        arb_lay.setContentsMargins(0, 0, 0, 0)
        arb_lay.setSpacing(UIScale.px(8))
        self._arb_table = DataTable(arb_tab, self._ARB_COLS, row_height=26)
        arb_lay.addWidget(self._arb_table, 1)
        arb_info = QLabel(
            "Top routes ranked by gold per day from your current market.",
            arb_tab,
        )
        arb_info.setFont(Fonts.mono_small)
        arb_info.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        arb_lay.addWidget(arb_info)
        tabs.addTab(arb_tab, f"{Sym.TREND_UP}  Arbitrage")

        foot = QHBoxLayout()
        foot.addWidget(self.back_button())
        foot.addStretch()
        root.addLayout(foot)

    def refresh(self) -> None:
        if not hasattr(self, "_buy_table"):
            return
        g = self.game
        market = g.markets[g.current_area]
        self._status_lbl.setText(
            f"{g.current_area.value}  ·  Gold {g.inventory.gold:,.0f}g  ·  "
            f"Weight {g._current_weight():.1f}/{g._max_carry_weight():.0f}"
        )

        buy_rows: List[Dict[str, Any]] = []
        for item_key in sorted(market.item_keys, key=lambda key: ALL_ITEMS[key].name if key in ALL_ITEMS else key):
            item = ALL_ITEMS.get(item_key)
            if not item:
                continue
            price = market.get_buy_price(item_key, g.season, g.skills.trading)
            stock = market.stock.get(item_key, 0)
            hist = list(market.history.get(item_key, []))
            if len(hist) >= 2:
                diff = hist[-1].price - hist[-2].price
                trend = "▲" if diff > 0.01 else "▼" if diff < -0.01 else "─"
                tag = "green" if diff > 0.01 else "red" if diff < -0.01 else "dim"
            else:
                trend = "─"
                tag = "dim"
            if item.illegal:
                tag = "red"
            buy_rows.append({
                "item": f"{item.name} [!]" if item.illegal else item.name,
                "category": getattr(item.category, "value", str(item.category)),
                "price": f"{price:.1f}g",
                "stock": str(stock),
                "trend": trend,
                "rarity": getattr(item.rarity, "value", str(item.rarity)),
                "item_key": item_key,
                "_tag": tag,
            })
        self._buy_table.load(buy_rows)

        sell_rows: List[Dict[str, Any]] = []
        for item_key, qty in sorted(g.inventory.items.items(), key=lambda pair: ALL_ITEMS[pair[0]].name if pair[0] in ALL_ITEMS else pair[0]):
            item = ALL_ITEMS.get(item_key)
            if not item:
                continue
            is_local = item_key in market.item_keys
            sell_price = market.get_sell_price(item_key, g.season, g.skills.trading)
            if sell_price <= 0 or not is_local:
                sell_price = round(item.base_price * 0.65, 2)
            avg_cost = g.inventory.cost_basis.get(item_key)
            if avg_cost is not None:
                ret_pct = (sell_price - avg_cost) / max(avg_cost, 0.01) * 100
                return_pct = f"{ret_pct:+.0f}%"
                est_profit = f"{(sell_price - avg_cost) * qty:+.0f}g"
                tag = "green" if ret_pct >= 0 else "red"
                paid = f"{avg_cost:.1f}g"
            else:
                return_pct = "—"
                est_profit = "—"
                paid = "—"
                tag = "dim"
            if item.illegal:
                tag = "red"
            sell_rows.append({
                "item": f"{item.name} [!]" if item.illegal else item.name,
                "have": str(qty),
                "sell_price": f"{sell_price:.1f}g",
                "paid": paid,
                "return_pct": return_pct,
                "profit": est_profit,
                "local": "yes" if is_local else "pawn",
                "item_key": item_key,
                "_tag": tag,
            })
        self._sell_table.load(sell_rows)

        self._arb_table.load(self._build_arbitrage_rows())
        self._buy_info.setText("Select an item to inspect pricing and limits.")
        self._buy_info.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        self._sell_info.setText("Select inventory to sell into the local market.")
        self._sell_info.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")

    def _build_arbitrage_rows(self) -> List[Dict[str, str]]:
        g = self.game
        market = g.markets[g.current_area]
        rows: List[Dict[str, Any]] = []
        for item_key in market.item_keys:
            item = ALL_ITEMS.get(item_key)
            if not item:
                continue
            buy_price = market.get_buy_price(item_key, g.season, g.skills.trading)
            if buy_price <= 0:
                continue
            for dest in Area:
                if dest == g.current_area:
                    continue
                dest_mkt = g.markets[dest]
                if item_key not in dest_mkt.item_keys:
                    continue
                sell_price = dest_mkt.get_sell_price(item_key, g.season, g.skills.trading)
                if sell_price <= buy_price:
                    continue
                days = AREA_INFO[g.current_area]["travel_days"].get(dest, 3)
                margin = sell_price - buy_price
                rows.append({
                    "item": item.name,
                    "buy": f"{buy_price:.1f}g",
                    "sell": f"{sell_price:.1f}g",
                    "dest": dest.value,
                    "profit_pct": f"{(margin / buy_price) * 100:.0f}%",
                    "days": str(days),
                    "gpd": f"{margin / max(days, 1):.1f}",
                    "stock": str(market.stock.get(item_key, 0)),
                    "_rank": margin / max(days, 1),
                })
        rows.sort(key=lambda row: row["_rank"], reverse=True)
        for row in rows:
            row.pop("_rank", None)
        return rows[:15]

    def _on_buy_select(self, row: Dict[str, Any]) -> None:
        item_key = row.get("item_key") if row else None
        if not item_key or item_key not in ALL_ITEMS:
            return
        g = self.game
        market = g.markets[g.current_area]
        item = ALL_ITEMS[item_key]
        price = market.get_buy_price(item_key, g.season, g.skills.trading)
        if self._haggle_item == item_key and self._haggle_discount > 0:
            price = round(price * (1.0 - self._haggle_discount), 2)
        stock = market.stock.get(item_key, 0)
        free_weight = max(0.0, g._max_carry_weight() - g._current_weight())
        max_by_weight = int(free_weight / item.weight) if item.weight > 0 else stock
        max_by_gold = int(g.inventory.gold / max(price, 0.01)) if price > 0 else stock
        max_qty = max(0, min(stock, max_by_weight, max_by_gold))
        detail = f"{item.name}  @{price:.1f}g  ·  stock {stock}  ·  max {max_qty}"
        if self._haggle_item == item_key and self._haggle_discount > 0:
            detail += f"  ·  haggle {int(self._haggle_discount * 100)}%"
        self._buy_info.setText(detail)
        self._buy_info.setStyleSheet(f"color:{P.amber}; background:transparent;")

    def _on_sell_select(self, row: Dict[str, Any]) -> None:
        item_key = row.get("item_key") if row else None
        if not item_key or item_key not in ALL_ITEMS:
            return
        item = ALL_ITEMS[item_key]
        self._sell_info.setText(
            f"{item.name}  ·  Have {self.game.inventory.items.get(item_key, 0)}  ·  "
            f"Sell at {row.get('sell_price', '—')}"
        )
        self._sell_info.setStyleSheet(f"color:{P.amber}; background:transparent;")

    def _on_buy_double(self, _row: Dict[str, Any]) -> None:
        if self.game.settings.double_click_action:
            self._do_buy()

    def _on_sell_double(self, _row: Dict[str, Any]) -> None:
        if self.game.settings.double_click_action:
            self._do_sell()

    def _on_buy_right_click(self, _row: Dict[str, Any]) -> None:
        if self.game.settings.right_click_haggle:
            self._do_haggle()

    def _do_buy(self) -> None:
        row = self._buy_table.selected()
        item_key = row.get("item_key") if row else None
        if not item_key or item_key not in ALL_ITEMS:
            self.msg.warn("Select an item first.")
            return
        g = self.game
        market = g.markets[g.current_area]
        item = ALL_ITEMS[item_key]
        unit_price = market.get_buy_price(item_key, g.season, g.skills.trading)
        if self._haggle_item == item_key and self._haggle_discount > 0:
            unit_price = round(unit_price * (1.0 - self._haggle_discount), 2)
        stock = market.stock.get(item_key, 0)
        free_weight = max(0.0, g._max_carry_weight() - g._current_weight())
        max_by_weight = int(free_weight / item.weight) if item.weight > 0 else stock
        max_by_gold = int(g.inventory.gold / max(unit_price, 0.01)) if unit_price > 0 else stock
        max_qty = max(0, min(stock, max_by_weight, max_by_gold))
        if max_qty <= 0:
            self.msg.err("Cannot buy: no stock, insufficient gold, or overweight.")
            return
        qty, ok = _popup_get_int(
            self,
            "Buy Item",
            f"Buy {item.name} at {unit_price:.1f}g each\n\nMax quantity: {max_qty}",
            value=min(max_qty, 1),
            minimum=1,
            maximum=max_qty,
            step=1,
            confirm_text="Buy",
        )
        if not ok:
            return
        result = market.buy_from_market(item_key, qty, g.season, g.skills.trading)
        if result < 0:
            self.msg.err("The market rejected the purchase.")
            return
        discount = self._haggle_discount if self._haggle_item == item_key else 0.0
        total = round(result * (1.0 - discount), 2)
        g.inventory.gold -= total
        g.inventory.record_purchase(item_key, qty, total / max(qty, 1))
        g.inventory.add(item_key, qty)
        g.lifetime_trades += 1
        g._gain_skill_xp(SkillType.TRADING, 5)
        g._use_time(1)
        g._check_achievements()
        if discount > 0:
            self._haggle_item = None
            self._haggle_discount = 0.0
        self.msg.ok(f"Bought {qty}× {item.name} for {total:.0f}g.")
        self.app.refresh()

    def _do_haggle(self) -> None:
        row = self._buy_table.selected()
        item_key = row.get("item_key") if row else None
        if not item_key or item_key not in ALL_ITEMS:
            self.msg.warn("Select an item to haggle on.")
            return
        chance = 0.10 + self.game.skills.haggling * 0.08
        self.game._use_time(1)
        self.game._gain_skill_xp(SkillType.HAGGLING, 10)
        if random.random() < chance:
            self._haggle_item = item_key
            self._haggle_discount = random.uniform(0.05, 0.15 + self.game.skills.haggling * 0.02)
            self.msg.ok(
                f"Haggled {int(self._haggle_discount * 100)}% off {ALL_ITEMS[item_key].name}."
            )
        else:
            self._haggle_item = None
            self._haggle_discount = 0.0
            self.msg.warn("Haggling failed.")
        self.app.refresh()

    def _do_sell(self) -> None:
        row = self._sell_table.selected()
        item_key = row.get("item_key") if row else None
        if not item_key or item_key not in ALL_ITEMS:
            self.msg.warn("Select an item to sell.")
            return
        self._execute_sell(item_key)

    def _do_sell_all(self) -> None:
        if not self.game.inventory.items:
            self.msg.err("Inventory is empty.")
            return
        if not _popup_confirm(
            self,
            "Sell All",
            "Sell every item in your inventory at the current market?",
            confirm_text="Sell All",
            confirm_role="danger",
        ):
            return
        total = 0.0
        for item_key in list(self.game.inventory.items.keys()):
            qty = self.game.inventory.items.get(item_key, 0)
            if qty <= 0:
                continue
            total += self._execute_sell(item_key, qty_override=qty, silent=True)
        self.msg.ok(f"Sold all cargo for {total:.0f}g.")
        self.app.refresh()

    def _execute_sell(self, item_key: str, qty_override: Optional[int] = None,
                      silent: bool = False) -> float:
        g = self.game
        market = g.markets[g.current_area]
        item = ALL_ITEMS[item_key]
        max_qty = g.inventory.items.get(item_key, 0)
        if max_qty <= 0:
            if not silent:
                self.msg.err("You do not have that item.")
            return 0.0
        sell_price = market.get_sell_price(item_key, g.season, g.skills.trading)
        is_local = item_key in market.item_keys
        if sell_price <= 0 or not is_local:
            sell_price = round(item.base_price * 0.65, 2)
        if qty_override is None:
            qty, ok = _popup_get_int(
                self,
                "Sell Item",
                f"Sell {item.name} at {sell_price:.1f}g each\n\nYou have: {max_qty}",
                value=max_qty,
                minimum=1,
                maximum=max_qty,
                step=1,
                confirm_text="Sell",
            )
            if not ok:
                return 0.0
        else:
            qty = qty_override
        if item.illegal and g.current_area != Area.SWAMP:
            guard = AREA_INFO[g.current_area].get("guard_strength", 0.0)
            if random.random() < guard * 0.10:
                fine = round(item.base_price * qty * 0.6, 2)
                g.inventory.remove(item_key, qty)
                g.inventory.gold = max(0.0, g.inventory.gold - fine)
                g.reputation = max(0, g.reputation - 12)
                g.heat = min(100, g.heat + 22)
                if not silent:
                    self.msg.err(
                        f"Guards seized {qty}× {item.name} and fined you {fine:.0f}g."
                    )
                return 0.0
        earnings = market.sell_to_market(item_key, qty, g.season, g.skills.trading)
        if earnings < 0:
            earnings = round(item.base_price * 0.65 * qty, 2)
        earnings = round(earnings * g._sell_mult(), 2)
        avg_cost = g.inventory.cost_basis.get(item_key)
        g.inventory.remove(item_key, qty)
        g.inventory.gold += earnings
        g.total_profit += earnings
        g.lifetime_trades += 1
        g._gain_skill_xp(SkillType.TRADING, 5)
        g._use_time(1)
        g._check_achievements()
        if not silent:
            pl = ""
            if avg_cost is not None:
                profit = earnings - avg_cost * qty
                pct = ((earnings / max(qty, 1)) - avg_cost) / max(avg_cost, 0.01) * 100
                pl = f"  P/L {profit:+.0f}g ({pct:+.0f}%)"
            self.msg.ok(f"Sold {qty}× {item.name} for {earnings:.0f}g.{pl}")
            self.app.refresh()
        return earnings


# ══════════════════════════════════════════════════════════════════════════════
# TRAVEL SCREEN  —  route planning, destination details, and journey execution
# ══════════════════════════════════════════════════════════════════════════════

class TravelScreen(Screen):
    _COLS = [
        ("area", "Destination", 160),
        ("days", "Days", 56, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("risk", "Risk", 64, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("cost", "Cost", 76, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("goods", "Local Goods", 240),
    ]

    def build(self) -> None:
        self._selected_area: Optional[Area] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12),
                                UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        hdr = QHBoxLayout()
        hdr.addWidget(self.section_label("Travel"))
        hdr.addStretch()
        self._overload_lbl = QLabel(self)
        self._overload_lbl.setFont(Fonts.mono_small)
        self._overload_lbl.setStyleSheet(f"color:{P.red}; background:transparent;")
        hdr.addWidget(self._overload_lbl)
        root.addLayout(hdr)

        self._info_lbl = QLabel(self)
        self._info_lbl.setFont(Fonts.mono_small)
        self._info_lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        root.addWidget(self._info_lbl)

        split = QSplitter(Qt.Orientation.Vertical, self)
        split.setChildrenCollapsible(False)

        top = QWidget(split)
        top_lay = QVBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(UIScale.px(8))
        self._table = DataTable(top, self._COLS, row_height=26)
        self._table.row_selected.connect(self._on_select)
        self._table.row_double_clicked.connect(self._on_double)
        top_lay.addWidget(self._table)

        bottom = QFrame(split)
        bottom.setObjectName("dashPanel")
        bottom_lay = QVBoxLayout(bottom)
        bottom_lay.setContentsMargins(UIScale.px(12), UIScale.px(10), UIScale.px(12), UIScale.px(12))
        bottom_lay.setSpacing(UIScale.px(8))
        title = QLabel("Destination Details", bottom)
        title.setFont(Fonts.mixed_bold)
        title.setStyleSheet(f"color:{P.gold}; background:transparent;")
        bottom_lay.addWidget(title)
        self._detail_lbl = QLabel("Select a destination to see route details.", bottom)
        self._detail_lbl.setFont(Fonts.mixed_small)
        self._detail_lbl.setWordWrap(True)
        self._detail_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        bottom_lay.addWidget(self._detail_lbl, 1)
        actions = QHBoxLayout()
        self._travel_btn = self.action_button(f"{Sym.TRAVEL}  Travel", self._do_travel)
        self._travel_btn.setFixedHeight(UIScale.px(32))
        self._travel_btn.setEnabled(False)
        actions.addWidget(self._travel_btn)
        actions.addWidget(self.back_button())
        actions.addStretch()
        bottom_lay.addLayout(actions)

        split.addWidget(top)
        split.addWidget(bottom)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

    def refresh(self) -> None:
        if not hasattr(self, "_table"):
            return
        g = self.game
        current_weight = g._current_weight()
        max_weight = g._max_carry_weight()
        excess = max(0.0, current_weight - max_weight)
        extra_days = int(excess / 15)
        self._info_lbl.setText(
            f"From {g.current_area.value}  ·  Gold {g.inventory.gold:,.0f}g  ·  "
            f"Weight {current_weight:.1f}/{max_weight:.0f}"
        )
        if excess > 0:
            self._overload_lbl.setText(
                f"Overloaded +{excess:.1f}wt  ·  +{extra_days} day(s) per route"
            )
        else:
            self._overload_lbl.setText("")

        rows: List[Dict[str, Any]] = []
        for area in Area:
            if area == g.current_area:
                continue
            days = AREA_INFO[g.current_area]["travel_days"].get(area, 3) + extra_days
            risk = AREA_INFO[area]["travel_risk"]
            cost = days * 3.0 * g.settings.cost_mult
            goods = ", ".join(
                ALL_ITEMS[key].name
                for key in AREA_INFO[area].get("base_items", [])[:4]
                if key in ALL_ITEMS
            )
            rows.append({
                "area": area.value,
                "days": str(days),
                "risk": f"{risk * 100:.0f}%",
                "cost": f"{cost:.0f}g",
                "goods": goods,
                "area_enum": area,
            })
        self._table.load(rows)
        self._selected_area = None
        self._travel_btn.setEnabled(False)
        self._detail_lbl.setText("Select a destination to see route details.")
        self._detail_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")

    def _on_select(self, row: Dict[str, Any]) -> None:
        area = row.get("area_enum") if row else None
        if area is None:
            self._selected_area = None
            self._travel_btn.setEnabled(False)
            return
        self._selected_area = area
        self._travel_btn.setEnabled(True)
        base_items = AREA_INFO[area].get("base_items", [])
        goods = ", ".join(
            ALL_ITEMS[key].name for key in base_items[:5] if key in ALL_ITEMS
        )
        desc = AREA_INFO[area].get("description", "")
        guard = AREA_INFO[area].get("guard_strength", 0)
        self._detail_lbl.setText(
            f"{area.value}  ·  {row.get('days', '?')} day(s)  ·  risk {row.get('risk', '?')}  ·  "
            f"cost {row.get('cost', '?')}\n"
            f"Produces: {goods or 'Unknown'}\n"
            f"Guard strength: {'★' * guard if guard else '—'}\n"
            f"{desc}"
        )
        self._detail_lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")

    def _on_double(self, _row: Dict[str, Any]) -> None:
        if self.game.settings.double_click_action:
            self._do_travel()

    def _do_travel(self) -> None:
        if self._selected_area is None:
            self.msg.warn("Select a destination first.")
            return
        g = self.game
        dest = self._selected_area
        excess = max(0.0, g._current_weight() - g._max_carry_weight())
        extra_days = int(excess / 15)
        days = AREA_INFO[g.current_area]["travel_days"].get(dest, 3) + extra_days
        risk = AREA_INFO[dest]["travel_risk"]
        travel_cost = days * 3.0 * g.settings.cost_mult
        if g.inventory.gold < travel_cost:
            self.msg.err(f"Not enough gold. Need {travel_cost:.0f}g.")
            return
        if not _popup_confirm(
            self,
            "Confirm Travel",
            f"Travel to {dest.value}?\n\nJourney: {days} day(s)\nCost: {travel_cost:.0f}g\nRisk: {risk * 100:.0f}%",
            confirm_text="Travel",
        ):
            return

        hired_bodyguard = False
        if risk > 0:
            guard_cost = max(10, round(risk * 120 * g.settings.cost_mult))
            if _popup_confirm(
                self,
                "Hire Bodyguard",
                f"Hire a bodyguard for {guard_cost}g?\nReduces armed attack risk by 60%.",
                confirm_text="Hire Guard",
                cancel_text="No Guard",
            ):
                if g.inventory.gold >= travel_cost + guard_cost:
                    g.inventory.gold -= guard_cost
                    hired_bodyguard = True
                    self.msg.info("Bodyguard hired for the journey.")
                else:
                    self.msg.warn("Not enough gold for both travel and bodyguard.")

        g.inventory.gold -= travel_cost
        effective_risk = risk * (1.5 if extra_days > 0 else 1.0)
        for _ in range(days):
            g._advance_day()
        g.current_area = dest
        g._track_stat("areas_visited", dest.value)
        g._track_stat("journeys")
        g._track_stat("travel_days", days)
        g.heat = max(0, g.heat - days * 3)

        incident = ""
        if random.random() < effective_risk:
            incident = self._run_incident(dest, 0.4 if hired_bodyguard else 1.0)

        g._check_achievements()
        self.app.refresh()
        txt = f"Arrived in {dest.value}.\n\nJourney: {days} day(s)\nCost: {travel_cost:.0f}g"
        if incident:
            txt += f"\n\nTravel event:\n{incident}"
        _popup_info(self, "Travel Complete", txt)

    def _run_incident(self, dest: Area, attack_mult: float) -> str:
        g = self.game
        roll = random.random()
        if roll < 0.25 * attack_mult:
            if attack_mult < 1.0 and random.random() < 0.5:
                return "Armed attackers were driven off by your bodyguard."
            gold_loss = round(g.inventory.gold * random.uniform(0.10, 0.30), 2)
            g.inventory.gold = max(0.0, g.inventory.gold - gold_loss)
            g.reputation = max(0, g.reputation - 3)
            item_keys = list(g.inventory.items.keys())
            if item_keys:
                stolen_key = random.choice(item_keys)
                g.inventory.remove(stolen_key, 1)
                return f"Armed attack: lost {gold_loss:.0f}g and 1× {ALL_ITEMS[stolen_key].name}."
            return f"Armed attack: lost {gold_loss:.0f}g."
        if roll < 0.50:
            item_keys = list(g.inventory.items.keys())
            if item_keys:
                stolen_key = random.choice(item_keys)
                stolen_qty = max(1, g.inventory.items[stolen_key] // 3)
                g.inventory.remove(stolen_key, stolen_qty)
                return f"Bandits stole {stolen_qty}× {ALL_ITEMS[stolen_key].name}."
            return "Bandits found nothing worth stealing."
        illegal = {
            key: qty for key, qty in g.inventory.items.items()
            if ALL_ITEMS.get(key) and ALL_ITEMS[key].illegal
        }
        guard = AREA_INFO[dest].get("guard_strength", 0.0)
        if roll < 0.62 and illegal and guard > 0:
            fine = 0.0
            seized: List[str] = []
            for key, qty in list(illegal.items()):
                fine += ALL_ITEMS[key].base_price * qty * 0.8
                g.inventory.remove(key, qty)
                seized.append(f"{qty}× {ALL_ITEMS[key].name}")
            fine = round(fine, 2)
            g.inventory.gold = max(0.0, g.inventory.gold - fine)
            g.reputation = max(0, g.reputation - 15)
            g.heat = min(100, g.heat + 30)
            return f"Border inspection seized {', '.join(seized)} and fined you {fine:.0f}g."
        if roll < 0.78:
            lucky = [key for key in ("herbs", "gold_dust", "gem", "spice", "fur") if key in ALL_ITEMS]
            if lucky:
                found_key = random.choice(lucky)
                qty = random.randint(1, 5)
                g.inventory.add(found_key, qty)
                return f"Lucky find: discovered {qty}× {ALL_ITEMS[found_key].name} on the road."
        item_keys = list(g.inventory.items.keys())
        if item_keys:
            spoiled_key = random.choice(item_keys)
            spoiled_qty = max(1, g.inventory.items.get(spoiled_key, 0) // 4)
            g.inventory.remove(spoiled_key, spoiled_qty)
            return f"Bad weather ruined {spoiled_qty}× {ALL_ITEMS[spoiled_key].name}."
        return "Bad weather slowed the trip, but you lost no cargo."


# ══════════════════════════════════════════════════════════════════════════════
# BUSINESSES SCREEN  —  buy, upgrade, staff, repair, and sell enterprises
# ══════════════════════════════════════════════════════════════════════════════

class BusinessesScreen(Screen):
    _COLS = [
        ("num", "#", 42, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("name", "Name", 190),
        ("item", "Produces", 120),
        ("level", "Level", 60, Qt.AlignmentFlag.AlignCenter),
        ("workers", "Workers", 82, Qt.AlignmentFlag.AlignCenter),
        ("prod", "Prod/day", 74, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("cost", "Cost/day", 82, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("status", "Status", 90),
    ]
    _FIRST_NAMES = [
        "Aldric", "Bram", "Cora", "Delia", "Edwyn", "Faye", "Gareth", "Hilda",
        "Isa", "Jorin", "Kira", "Lena", "Mira", "Ned", "Ora", "Pip",
    ]
    _LAST_NAMES = [
        "Miller", "Cooper", "Smith", "Tanner", "Fisher", "Brewer", "Mason", "Wright",
        "Fletcher", "Dyer", "Eastman", "Saltmarsh", "Hayward", "Ironsides",
    ]
    _TRAITS = [
        ("Diligent", 1.08, 1.22, 1.6),
        ("Steady", 0.98, 1.10, 0.8),
        ("Cheap", 0.86, 1.00, -0.9),
        ("Gifted", 1.15, 1.32, 2.0),
        ("Green", 0.80, 0.94, -1.2),
    ]

    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12),
                                UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        hdr = QHBoxLayout()
        hdr.addWidget(self.section_label("Businesses"))
        hdr.addStretch()
        self._lic_lbl = QLabel(self)
        self._lic_lbl.setFont(Fonts.mono_small)
        self._lic_lbl.setStyleSheet(f"color:{P.red}; background:transparent;")
        hdr.addWidget(self._lic_lbl)
        root.addLayout(hdr)

        self._table = DataTable(self, self._COLS, row_height=26)
        self._table.row_selected.connect(self._on_select)
        root.addWidget(self._table, 1)

        detail = QFrame(self)
        detail.setObjectName("dashPanel")
        detail_lay = QVBoxLayout(detail)
        detail_lay.setContentsMargins(UIScale.px(12), UIScale.px(10), UIScale.px(12), UIScale.px(10))
        detail_lay.setSpacing(UIScale.px(6))

        r1 = QHBoxLayout()
        self._det_name = QLabel("Select a business to see details.", detail)
        self._det_name.setFont(Fonts.mixed_bold)
        self._det_name.setStyleSheet(f"color:{P.gold}; background:transparent;")
        self._det_status = QLabel("", detail)
        self._det_status.setFont(Fonts.mixed_bold)
        self._det_status.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        r1.addWidget(self._det_name, 1)
        r1.addWidget(self._det_status)
        detail_lay.addLayout(r1)

        r2 = QHBoxLayout()
        self._det_metrics = QLabel("", detail)
        self._det_metrics.setFont(Fonts.mono_small)
        self._det_metrics.setStyleSheet(f"color:{P.fg}; background:transparent;")
        self._det_metrics.setWordWrap(True)
        self._det_cost = QLabel("", detail)
        self._det_cost.setFont(Fonts.mono_small)
        self._det_cost.setStyleSheet(f"color:{P.amber}; background:transparent;")
        self._det_cost.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self._det_cost.setWordWrap(True)
        r2.addWidget(self._det_metrics, 1)
        r2.addWidget(self._det_cost, 0)
        detail_lay.addLayout(r2)
        root.addWidget(detail)

        act = QHBoxLayout()
        buttons = [
            (f"{Sym.YES}  Buy Business", self._do_purchase, "primary"),
            (f"{Sym.TREND_UP}  Upgrade", self._do_upgrade, "secondary"),
            (f"{Sym.YES}  Hire Worker", self._do_hire, "secondary"),
            (f"{Sym.NO}  Fire Worker", self._do_fire, "secondary"),
            (f"{Sym.SYNC}  Repair", self._do_repair, "secondary"),
            (f"{Sym.NO}  Sell Business", self._do_sell, "danger"),
        ]
        for text, handler, role in buttons:
            btn = self.action_button(text, handler, role=role)
            btn.setFixedHeight(UIScale.px(30))
            act.addWidget(btn)
        act.addStretch()
        root.addLayout(act)

        foot = QHBoxLayout()
        foot.addWidget(self.back_button())
        foot.addStretch()
        root.addLayout(foot)

    def refresh(self) -> None:
        g = self.game
        has_license = LicenseType.BUSINESS in g.licenses
        self._lic_lbl.setText("" if has_license else "No Business Permit — buy from Licenses")

        rows: List[Dict[str, Any]] = []
        for index, business in enumerate(g.businesses, 1):
            item = ALL_ITEMS.get(business.item_produced)
            status = "BROKEN" if business.broken_down else ("Running" if business.workers > 0 else "No workers")
            tag = "red" if business.broken_down else ("green" if business.workers > 0 else "yellow")
            rows.append({
                "num": str(index),
                "name": business.name,
                "item": item.name if item else business.item_produced,
                "level": f"Lv{business.level}",
                "workers": f"{business.workers}/{business.max_workers}",
                "prod": str(business.daily_production()),
                "cost": f"{business.daily_cost:.0f}g",
                "status": status,
                "biz_index": index - 1,
                "_tag": tag,
            })
        self._table.load(rows)
        if not rows:
            self._det_name.setText("No businesses owned yet.")
            self._det_status.setText("")
            self._det_metrics.setText("Buy a workshop, farm, or industrial site to begin passive production.")
            self._det_cost.setText("")

    def _selected_business(self) -> Optional[Any]:
        row = self._table.selected()
        idx = row.get("biz_index") if row else None
        if isinstance(idx, int) and 0 <= idx < len(self.game.businesses):
            return self.game.businesses[idx]
        return None

    def _on_select(self, row: Dict[str, Any]) -> None:
        idx = row.get("biz_index") if row else None
        if not isinstance(idx, int) or not (0 <= idx < len(self.game.businesses)):
            return
        business = self.game.businesses[idx]
        item = ALL_ITEMS.get(business.item_produced)
        item_name = item.name if item else business.item_produced
        upgrade_cost = round(business.level * 200 + business.purchase_cost * 0.3)
        wage = business.worker_daily_wage()
        status_text = "BROKEN" if business.broken_down else ("Running" if business.workers > 0 else "No workers")
        status_color = P.red if business.broken_down else (P.green if business.workers > 0 else P.amber)
        sale_value = round(business.purchase_cost * 0.5 * (1 + (business.level - 1) * 0.2))

        self._det_name.setText(f"{business.name}  ·  Lv{business.level}  ·  {business.area.value}")
        self._det_status.setText(status_text)
        self._det_status.setStyleSheet(f"color:{status_color}; background:transparent;")
        self._det_metrics.setText(
            f"Produces {business.daily_production()}/day {item_name}  ·  "
            f"Workers {business.workers}/{business.max_workers}  ·  "
            f"Daily wages {wage:.0f}g  ·  Daily cost {business.daily_cost:.0f}g"
        )
        parts = [f"Upgrade {upgrade_cost}g"]
        if business.broken_down:
            parts.append(f"Repair {business.repair_cost:.0f}g")
        parts.append(f"Sale value ~{sale_value}g")
        self._det_cost.setText("  ·  ".join(parts))

    def _do_purchase(self) -> None:
        g = self.game
        if LicenseType.BUSINESS not in g.licenses:
            self.msg.err("You need a Business Permit to buy businesses.")
            return
        entries = list(BUSINESS_CATALOGUE.items())
        labels: List[str] = []
        label_map: Dict[str, str] = {}
        for key, data in entries:
            item = ALL_ITEMS.get(data["item"])
            item_name = item.name if item else data["item"]
            base_price = item.base_price if item else 0.0
            net = base_price * data["rate"] - data["cost"]
            label = (
                f"{data['name']}  [{data['area'].value}]  {data['buy']:.0f}g  ·  "
                f"{data['rate']}/day {item_name}  ·  net~{net:+.0f}g/day"
            )
            labels.append(label)
            label_map[label] = key
        key = BusinessPurchaseDialog(self).choose()
        if not key:
            return
        data = BUSINESS_CATALOGUE[key]
        cost = float(data["buy"])
        if g.inventory.gold < cost:
            self.msg.err(f"Need {cost:.0f}g, have {g.inventory.gold:.0f}g.")
            return
        g.inventory.gold -= cost
        business = make_business(key, data["area"])
        g.businesses.append(business)
        g._gain_skill_xp(SkillType.INDUSTRY, 20)
        g._check_achievements()
        self.msg.ok(f"Purchased {business.name} for {cost:.0f}g in {business.area.value}.")
        self.app.refresh()

    def _do_upgrade(self) -> None:
        business = self._selected_business()
        if business is None:
            self.msg.warn("Select a business to upgrade.")
            return
        cost = round(business.level * 200 + business.purchase_cost * 0.3)
        if not _popup_confirm(
            self,
            "Upgrade Business",
            f"Upgrade {business.name} to Lv{business.level + 1} for {cost:.0f}g?",
            confirm_text="Upgrade",
        ):
            return
        if self.game.inventory.gold < cost:
            self.msg.err(f"Need {cost:.0f}g.")
            return
        self.game.inventory.gold -= cost
        business.level += 1
        self.game._gain_skill_xp(SkillType.INDUSTRY, 10)
        self.game._check_achievements()
        self.msg.ok(f"{business.name} upgraded to Lv{business.level}.")
        self.app.refresh()

    def _generate_applicants(self) -> List[Dict[str, Any]]:
        applicants: List[Dict[str, Any]] = []
        for _ in range(4):
            trait, prod_min, prod_max, wage_delta = random.choice(self._TRAITS)
            first = random.choice(self._FIRST_NAMES)
            last = random.choice(self._LAST_NAMES)
            productivity = round(random.uniform(prod_min, prod_max), 2)
            wage = round(max(3.5, random.uniform(5.0, 8.5) + wage_delta), 1)
            applicants.append({
                "name": f"{first} {last}",
                "wage": wage,
                "productivity": productivity,
                "trait": trait,
            })
        return applicants

    def _do_hire(self) -> None:
        business = self._selected_business()
        if business is None:
            self.msg.warn("Select a business to hire for.")
            return
        if business.workers >= business.max_workers:
            self.msg.err(f"{business.name} is fully staffed.")
            return
        candidate = ApplicantHireDialog(self, business.name, self._generate_applicants).choose()
        if not candidate:
            return
        business.hired_workers.append(candidate)
        business.workers = len(business.hired_workers)
        self.msg.ok(
            f"Hired {candidate['name']} at {candidate['wage']:.1f}g/day "
            f"({candidate['productivity']:.2f}×, {candidate['trait']})."
        )
        self.app.refresh()

    def _do_fire(self) -> None:
        business = self._selected_business()
        if business is None:
            self.msg.warn("Select a business to fire from.")
            return
        if business.workers <= 0:
            self.msg.err(f"{business.name} has no workers.")
            return
        if not _popup_confirm(
            self,
            "Fire Worker",
            f"Fire a worker from {business.name}?",
            confirm_text="Fire",
            confirm_role="danger",
        ):
            return
        if business.hired_workers:
            business.hired_workers.pop()
        business.workers = max(0, len(business.hired_workers) if business.hired_workers else business.workers - 1)
        self.msg.ok(f"Fired a worker from {business.name}.")
        self.app.refresh()

    def _do_repair(self) -> None:
        business = self._selected_business()
        if business is None:
            self.msg.warn("Select a business to repair.")
            return
        if not business.broken_down:
            self.msg.info(f"{business.name} is not broken.")
            return
        cost = float(business.repair_cost)
        if not _popup_confirm(
            self,
            "Repair Business",
            f"Repair {business.name} for {cost:.0f}g?",
            confirm_text="Repair",
        ):
            return
        if self.game.inventory.gold < cost:
            self.msg.err(f"Need {cost:.0f}g.")
            return
        self.game.inventory.gold -= cost
        business.broken_down = False
        business.repair_cost = 0.0
        self.msg.ok(f"{business.name} repaired.")
        self.app.refresh()

    def _do_sell(self) -> None:
        row = self._table.selected()
        idx = row.get("biz_index") if row else None
        if not isinstance(idx, int) or not (0 <= idx < len(self.game.businesses)):
            self.msg.warn("Select a business to sell.")
            return
        business = self.game.businesses[idx]
        sell_price = round(business.purchase_cost * 0.5 * (1 + (business.level - 1) * 0.2))
        if not _popup_confirm(
            self,
            "Sell Business",
            f"Sell {business.name} for {sell_price:.0f}g?\n\n50% resale plus a level bonus.",
            confirm_text="Sell Business",
            confirm_role="danger",
        ):
            return
        self.game.businesses.pop(idx)
        self.game.inventory.gold += sell_price
        self.msg.ok(f"Sold {business.name} for {sell_price:.0f}g.")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# CONTRACTS SCREEN  —  generate, accept, and fulfill delivery contracts
# ══════════════════════════════════════════════════════════════════════════════

class ContractsScreen(Screen):
    _OFFER_COLS = [
        ("item", "Item", 160),
        ("qty", "Qty", 52, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("dest", "Deliver To", 140),
        ("ppu", "Contract/ea", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("mkt", "Market@", 82, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("vs", "Vs.Mkt", 66, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("bonus", "Bonus", 74, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("penalty", "Penalty", 78, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("days", "Deadline", 72, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]
    _ACTIVE_COLS = [
        ("item", "Item", 160),
        ("qty", "Qty", 52, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("dest", "Deliver To", 140),
        ("ppu", "Contract/ea", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("bonus", "Bonus", 74, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("penalty", "Penalty", 78, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("days", "Days Left", 74, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("status", "Status", 92),
    ]

    def __init__(self, app: "GameApp") -> None:
        super().__init__(app)
        self._pending: List[Contract] = []

    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        hdr = QHBoxLayout()
        hdr.addWidget(self.section_label("Contracts"))
        hdr.addStretch()
        self._lic_lbl = QLabel(self)
        self._lic_lbl.setFont(Fonts.mono_small)
        self._lic_lbl.setStyleSheet(f"color:{P.red}; background:transparent;")
        hdr.addWidget(self._lic_lbl)
        root.addLayout(hdr)

        offer_title = QLabel("Step 1 — Contract Offers", self)
        offer_title.setFont(Fonts.mixed_bold)
        offer_title.setStyleSheet(f"color:{P.gold}; background:transparent;")
        root.addWidget(offer_title)
        offer_note = QLabel(
            "Generate fresh offers, review the terms, then accept the contracts you want to carry.",
            self,
        )
        offer_note.setFont(Fonts.mono_small)
        offer_note.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        offer_note.setWordWrap(True)
        root.addWidget(offer_note)

        self._offer_table = DataTable(self, self._OFFER_COLS, row_height=26)
        self._offer_table.row_double_clicked.connect(self._on_offer_double)
        root.addWidget(self._offer_table)

        offer_actions = QHBoxLayout()
        for text, handler, role in [
            (f"{Sym.SYNC}  Generate New Offers", self._do_generate, "secondary"),
            (f"{Sym.YES}  Accept Selected", self._do_accept, "primary"),
            (f"{Sym.YES}  Accept All", self._do_accept_all, "primary"),
            (f"{Sym.NO}  Discard All", self._do_discard, "danger"),
        ]:
            btn = self.action_button(text, handler, role=role)
            btn.setFixedHeight(UIScale.px(30))
            offer_actions.addWidget(btn)
        offer_actions.addStretch()
        root.addLayout(offer_actions)

        root.addWidget(self.h_sep())

        active_title = QLabel("Step 2 — Active Contracts", self)
        active_title.setFont(Fonts.mixed_bold)
        active_title.setStyleSheet(f"color:{P.gold}; background:transparent;")
        root.addWidget(active_title)
        active_note = QLabel(
            "Travel to the destination with the goods, then fulfill the contract for locked-in payment.",
            self,
        )
        active_note.setFont(Fonts.mono_small)
        active_note.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        active_note.setWordWrap(True)
        root.addWidget(active_note)

        self._table = DataTable(self, self._ACTIVE_COLS, row_height=26)
        self._table.row_double_clicked.connect(self._on_active_double)
        root.addWidget(self._table, 1)

        act = QHBoxLayout()
        for text, handler, role in [
            (f"{Sym.YES}  Fulfill Selected", self._do_fulfill, "primary"),
            (f"{Sym.EXCHANGE}  Fulfill All Eligible", self._do_fulfill_all, "secondary"),
        ]:
            btn = self.action_button(text, handler, role=role)
            btn.setFixedHeight(UIScale.px(30))
            act.addWidget(btn)
        act.addWidget(self.back_button())
        act.addStretch()
        root.addLayout(act)

    def refresh(self) -> None:
        g = self.game
        has_license = LicenseType.CONTRACTS in g.licenses
        self._lic_lbl.setText("" if has_license else "No Contract Seal — buy from Licenses")

        offer_rows: List[Dict[str, Any]] = []
        for contract in self._pending:
            item = ALL_ITEMS.get(contract.item_key)
            if not item:
                continue
            dest_market = g.markets[contract.destination]
            market_ref = (
                dest_market.get_sell_price(contract.item_key, g.season, g.skills.trading)
                if contract.item_key in dest_market.item_keys
                else item.base_price
            )
            vs_market = (contract.price_per_unit - market_ref) / max(market_ref, 0.01) * 100
            days = contract.deadline_day - g._absolute_day()
            offer_rows.append({
                "item": item.name,
                "qty": str(contract.quantity),
                "dest": contract.destination.value,
                "ppu": f"{contract.price_per_unit:.1f}g",
                "mkt": f"{market_ref:.1f}g",
                "vs": f"{vs_market:+.0f}%",
                "bonus": f"+{contract.reward_bonus:.0f}g",
                "penalty": f"-{contract.penalty:.0f}g",
                "days": f"{days}d",
                "contract_id": contract.id,
                "_tag": "green" if vs_market >= 3 else ("red" if vs_market < -10 else "yellow"),
            })
        if not offer_rows:
            offer_rows = [{
                "item": "No offers generated yet — click Generate New Offers.",
                "qty": "", "dest": "", "ppu": "", "mkt": "", "vs": "",
                "bonus": "", "penalty": "", "days": "", "contract_id": -1, "_tag": "dim",
            }]
        self._offer_table.load(offer_rows)

        active_rows: List[Dict[str, Any]] = []
        for contract in g.contracts:
            if contract.fulfilled:
                continue
            item = ALL_ITEMS.get(contract.item_key)
            name = item.name if item else contract.item_key
            days_left = contract.deadline_day - g._absolute_day()
            ready = g.current_area == contract.destination and g.inventory.items.get(contract.item_key, 0) >= contract.quantity
            status = "READY" if ready else ("EXPIRED" if days_left <= 0 else "Pending")
            if ready:
                tag = "green"
            elif days_left <= 0:
                tag = "red"
            elif days_left < 5:
                tag = "red"
            elif days_left < 15:
                tag = "yellow"
            else:
                tag = "dim"
            active_rows.append({
                "item": name,
                "qty": str(contract.quantity),
                "dest": contract.destination.value,
                "ppu": f"{contract.price_per_unit:.2f}g",
                "bonus": f"+{contract.reward_bonus:.0f}g",
                "penalty": f"-{contract.penalty:.0f}g",
                "days": str(max(0, days_left)),
                "status": status,
                "contract_id": contract.id,
                "_tag": tag,
            })
        self._table.load(active_rows)

    def _on_offer_double(self, _row: Dict[str, Any]) -> None:
        if self.game.settings.double_click_action:
            self._do_accept()

    def _on_active_double(self, _row: Dict[str, Any]) -> None:
        if self.game.settings.double_click_action:
            self._do_fulfill()

    def _do_generate(self) -> None:
        g = self.game
        if LicenseType.CONTRACTS not in g.licenses:
            self.msg.err("You need a Trade Contract Seal to access contracts.")
            return
        available = [key for key, item in ALL_ITEMS.items() if not item.illegal]
        other_areas = [area for area in Area if area != g.current_area]
        if not other_areas:
            self.msg.err("No other destinations are available.")
            return
        self._pending.clear()
        for _ in range(3):
            item_key = random.choice(available)
            item = ALL_ITEMS[item_key]
            destination = random.choice(other_areas)
            dest_market = g.markets[destination]
            market_ref = (
                dest_market.get_sell_price(item_key, g.season, g.skills.trading)
                if item_key in dest_market.item_keys
                else item.base_price
            )
            modifier = random.choices(
                [random.uniform(0.80, 0.92), random.uniform(0.92, 1.05), random.uniform(1.05, 1.15)],
                weights=[30, 50, 20],
            )[0]
            quantity = random.randint(8, 50) if item.base_price < 40 else random.randint(3, 20)
            contract = Contract(
                id=g.next_contract_id,
                item_key=item_key,
                quantity=quantity,
                price_per_unit=round(market_ref * modifier, 2),
                destination=destination,
                deadline_day=g._absolute_day() + random.randint(12, 45),
                reward_bonus=round(quantity * item.base_price * random.uniform(0.10, 0.25), 2),
                penalty=round(quantity * item.base_price * random.uniform(0.15, 0.35), 2),
            )
            self._pending.append(contract)
            g.next_contract_id += 1
        self.msg.ok("Generated 3 contract offers.")
        self.app.refresh()

    def _confirm_accept(self, detail: str) -> bool:
        return _maybe_sign(self, "contract", detail=detail)

    def _do_accept(self) -> None:
        row = self._offer_table.selected()
        contract_id = row.get("contract_id") if row else None
        if not isinstance(contract_id, int) or contract_id < 0:
            self.msg.warn("Select an offer to accept.")
            return
        contract = next((con for con in self._pending if con.id == contract_id), None)
        if contract is None:
            self.msg.warn("Could not find the selected offer.")
            return
        item = ALL_ITEMS.get(contract.item_key)
        item_name = item.name if item else contract.item_key
        detail = (
            f"{contract.quantity}× {item_name}\n"
            f"Destination: {contract.destination.value}\n"
            f"Pay: {contract.price_per_unit:.1f}g/ea\n"
            f"Bonus: +{contract.reward_bonus:.0f}g"
        )
        if not self._confirm_accept(detail):
            return
        self._pending.remove(contract)
        self.game.contracts.append(contract)
        self.msg.ok(
            f"Accepted {contract.quantity}× {item_name} to {contract.destination.value} "
            f"@ {contract.price_per_unit:.1f}g/ea."
        )
        self.app.refresh()

    def _do_accept_all(self) -> None:
        if not self._pending:
            self.msg.warn("No pending offers to accept.")
            return
        if not self._confirm_accept(f"{len(self._pending)} contract offer(s)"):
            return
        self.game.contracts.extend(self._pending)
        count = len(self._pending)
        self._pending.clear()
        self.msg.ok(f"Accepted all {count} contract offer(s).")
        self.app.refresh()

    def _do_discard(self) -> None:
        if not self._pending:
            self.msg.warn("No pending offers to discard.")
            return
        count = len(self._pending)
        self._pending.clear()
        self.msg.ok(f"Discarded {count} pending offer(s).")
        self.app.refresh()

    def _find_active_contract(self) -> Optional[Contract]:
        row = self._table.selected()
        contract_id = row.get("contract_id") if row else None
        if isinstance(contract_id, int):
            return next((con for con in self.game.contracts if not con.fulfilled and con.id == contract_id), None)
        return None

    def _do_fulfill(self) -> None:
        contract = self._find_active_contract()
        if contract is None:
            self.msg.warn("Select a contract to fulfill.")
            return
        g = self.game
        if g.current_area != contract.destination:
            self.msg.err(f"You must be in {contract.destination.value} to fulfill this contract.")
            return
        have = g.inventory.items.get(contract.item_key, 0)
        item = ALL_ITEMS.get(contract.item_key)
        item_name = item.name if item else contract.item_key
        if have < contract.quantity:
            self.msg.err(f"Need {contract.quantity}× {item_name}, only have {have}.")
            return
        days_left = contract.deadline_day - g._absolute_day()
        on_time = days_left >= 0
        payment = contract.price_per_unit * contract.quantity
        total = payment + (contract.reward_bonus if on_time else -contract.penalty)
        g.inventory.remove(contract.item_key, contract.quantity)
        g.inventory.gold = max(0.0, g.inventory.gold + total)
        contract.fulfilled = True
        g._gain_skill_xp(SkillType.TRADING, 25)
        g._track_stat("contracts_completed")
        if on_time:
            g.reputation = min(100, g.reputation + 3)
            g._track_stat("contracts_ontime")
            g.ach_stats["contracts_streak"] = g.ach_stats.get("contracts_streak", 0) + 1
            if contract.reward_bonus > g.ach_stats.get("max_contract_bonus", 0):
                g.ach_stats["max_contract_bonus"] = contract.reward_bonus
            if days_left == 0:
                g._track_stat("contract_close_call", True)
            self.msg.ok(
                f"Contract fulfilled on time: +{payment:.0f}g and +{contract.reward_bonus:.0f}g bonus."
            )
        else:
            g.reputation = max(0, g.reputation - 5)
            g.ach_stats["contracts_streak"] = 0
            self.msg.warn(
                f"Contract fulfilled late: +{payment:.0f}g and -{contract.penalty:.0f}g penalty."
            )
        g._check_achievements()
        self.app.refresh()

    def _do_fulfill_all(self) -> None:
        g = self.game
        eligible = [
            con for con in g.contracts
            if not con.fulfilled
            and con.destination == g.current_area
            and g.inventory.items.get(con.item_key, 0) >= con.quantity
        ]
        if not eligible:
            self.msg.warn("No eligible contracts to fulfill here.")
            return
        total_gold = 0.0
        count = 0
        for contract in eligible:
            if g.inventory.items.get(contract.item_key, 0) < contract.quantity:
                continue
            days_left = contract.deadline_day - g._absolute_day()
            on_time = days_left >= 0
            payment = contract.price_per_unit * contract.quantity
            total = payment + (contract.reward_bonus if on_time else -contract.penalty)
            g.inventory.remove(contract.item_key, contract.quantity)
            g.inventory.gold = max(0.0, g.inventory.gold + total)
            contract.fulfilled = True
            g._gain_skill_xp(SkillType.TRADING, 25)
            g._track_stat("contracts_completed")
            if on_time:
                g.reputation = min(100, g.reputation + 3)
                g._track_stat("contracts_ontime")
                g.ach_stats["contracts_streak"] = g.ach_stats.get("contracts_streak", 0) + 1
                if contract.reward_bonus > g.ach_stats.get("max_contract_bonus", 0):
                    g.ach_stats["max_contract_bonus"] = contract.reward_bonus
            else:
                g.reputation = max(0, g.reputation - 5)
                g.ach_stats["contracts_streak"] = 0
            total_gold += total
            count += 1
        if count == 0:
            self.msg.warn("Could not fulfill any contracts.")
            return
        g._check_achievements()
        self.msg.ok(f"Fulfilled {count} contract{'s' if count != 1 else ''} for {total_gold:.0f}g total.")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# SKILLS SCREEN  —  inspect levels and buy permanent upgrades
# ══════════════════════════════════════════════════════════════════════════════

class SkillsScreen(Screen):
    _DESCS = {
        SkillType.TRADING: "Improves buy and sell price margins.",
        SkillType.HAGGLING: "Increases your chance and size of purchase discounts.",
        SkillType.LOGISTICS: "Raises maximum carry weight for trading runs.",
        SkillType.INDUSTRY: "Boosts business production efficiency.",
        SkillType.ESPIONAGE: "Improves black-market odds and information access.",
        SkillType.BANKING: "Improves interest rates, lending, and finance terms.",
    }
    _COLS = [
        ("skill", "Skill", 128),
        ("level", "Level", 62, Qt.AlignmentFlag.AlignCenter),
        ("xp", "XP", 72, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("cost", "Upgrade Cost", 110, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("desc", "Description", 440),
    ]

    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        hdr = QHBoxLayout()
        hdr.addWidget(self.section_label("Skills & Upgrades"))
        hdr.addStretch()
        self._gold_lbl = QLabel(self)
        self._gold_lbl.setFont(Fonts.mono)
        self._gold_lbl.setStyleSheet(f"color:{P.amber}; background:transparent;")
        hdr.addWidget(self._gold_lbl)
        root.addLayout(hdr)

        self._table = DataTable(self, self._COLS, row_height=26)
        self._table.row_selected.connect(self._on_select)
        self._table.row_double_clicked.connect(self._on_double)
        root.addWidget(self._table)

        self._detail_lbl = QLabel("Select a skill to see details.", self)
        self._detail_lbl.setFont(Fonts.mono_small)
        self._detail_lbl.setWordWrap(True)
        self._detail_lbl.setStyleSheet(
            f"color:{P.fg_dim}; background:{P.bg_panel}; border:1px solid {P.border};"
            f"padding:{UIScale.px(8)}px; border-radius:{UIScale.px(4)}px;"
        )
        root.addWidget(self._detail_lbl)

        act = QHBoxLayout()
        upgrade_btn = self.action_button(f"{Sym.TREND_UP}  Upgrade Selected Skill", self._do_upgrade)
        upgrade_btn.setFixedHeight(UIScale.px(30))
        act.addWidget(upgrade_btn)
        act.addWidget(self.back_button())
        act.addStretch()
        root.addLayout(act)

    def refresh(self) -> None:
        g = self.game
        self._gold_lbl.setText(f"Gold: {g.inventory.gold:,.0f}g")
        rows: List[Dict[str, Any]] = []
        for skill in SkillType:
            level = getattr(g.skills, skill.value.lower())
            xp = g.skills.xp.get(skill.value, 0)
            cost = g.skills.level_up_cost(skill)
            rows.append({
                "skill": skill.value,
                "level": f"Lv{level}",
                "xp": str(xp),
                "cost": f"{cost}g",
                "desc": self._DESCS.get(skill, ""),
                "skill_enum": skill,
                "_tag": "green" if g.inventory.gold >= cost else "dim",
            })
        self._table.load(rows)

    def _on_select(self, row: Dict[str, Any]) -> None:
        skill = row.get("skill_enum") if row else None
        if not isinstance(skill, SkillType):
            return
        g = self.game
        level = getattr(g.skills, skill.value.lower())
        xp = g.skills.xp.get(skill.value, 0)
        cost = g.skills.level_up_cost(skill)
        if g.inventory.gold >= cost:
            afford = "can afford"
            color = P.green
        else:
            afford = f"need {cost - g.inventory.gold:.0f}g more"
            color = P.red
        self._detail_lbl.setText(
            f"{skill.value}  ·  Lv{level}  ·  XP {xp}  ·  Next level {cost}g  ·  {afford}\n"
            f"{self._DESCS.get(skill, '')}"
        )
        self._detail_lbl.setStyleSheet(
            f"color:{color}; background:{P.bg_panel}; border:1px solid {P.border};"
            f"padding:{UIScale.px(8)}px; border-radius:{UIScale.px(4)}px;"
        )

    def _on_double(self, _row: Dict[str, Any]) -> None:
        if self.game.settings.double_click_action:
            self._do_upgrade()

    def _do_upgrade(self) -> None:
        row = self._table.selected()
        skill = row.get("skill_enum") if row else None
        if not isinstance(skill, SkillType):
            self.msg.warn("Select a skill to upgrade.")
            return
        g = self.game
        current_level = getattr(g.skills, skill.value.lower())
        cost = g.skills.level_up_cost(skill)
        if not _popup_confirm(
            self,
            "Upgrade Skill",
            f"Upgrade {skill.value} from Lv{current_level} to Lv{current_level + 1}?\n\nCost: {cost}g",
            confirm_text="Upgrade",
        ):
            return
        success, new_gold = g.skills.try_level_up(skill, g.inventory.gold)
        if not success:
            self.msg.err(f"Not enough gold. Need {cost}g, have {g.inventory.gold:.0f}g.")
            return
        g.inventory.gold = new_gold
        g._check_achievements()
        self.msg.ok(f"{skill.value} upgraded to Lv{getattr(g.skills, skill.value.lower())}.")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# SMUGGLING SCREEN  —  black market buy/sell with heat and bust risk
# ══════════════════════════════════════════════════════════════════════════════

class SmugglingScreen(Screen):
    _BUY_COLS = [
        ("item", "Contraband", 170),
        ("price", "Informant", 82, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("wt", "Wt/ea", 58, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("catch", "Catch", 74, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]
    _SELL_COLS = [
        ("item", "Contraband", 160),
        ("qty", "Have", 58, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("value", "Fence Value", 92, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("base", "Base Price", 84, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]

    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        root.addWidget(self.section_label("Smuggling Den"))
        self._heat_lbl = QLabel(self)
        self._heat_lbl.setFont(Fonts.mono)
        self._heat_lbl.setStyleSheet(f"color:{P.red}; background:transparent;")
        root.addWidget(self._heat_lbl)
        self._detail_lbl = QLabel(self)
        self._detail_lbl.setFont(Fonts.mono_small)
        self._detail_lbl.setWordWrap(True)
        self._detail_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        root.addWidget(self._detail_lbl)

        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.setChildrenCollapsible(False)

        left = QWidget(split)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(UIScale.px(8))
        lbl = QLabel("Buy From Informant", left)
        lbl.setFont(Fonts.mixed_bold)
        lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        left_lay.addWidget(lbl)
        note = QLabel("1.25× base price  ·  +8 heat per deal", left)
        note.setFont(Fonts.mono_small)
        note.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        left_lay.addWidget(note)
        self._buy_table = DataTable(left, self._BUY_COLS, row_height=26)
        self._buy_table.row_double_clicked.connect(self._on_buy_double)
        left_lay.addWidget(self._buy_table, 1)
        buy_act = QHBoxLayout()
        buy_act.addWidget(QLabel("Qty:", left))
        self._buy_qty = QSpinBox(left)
        self._buy_qty.setRange(1, 999)
        self._buy_qty.setValue(1)
        self._buy_qty.setFixedWidth(UIScale.px(80))
        buy_act.addWidget(self._buy_qty)
        buy_btn = self.action_button(f"{Sym.YES}  Buy Selected", self._do_buy, role="secondary")
        buy_btn.setFixedHeight(UIScale.px(30))
        buy_act.addWidget(buy_btn)
        buy_act.addStretch()
        left_lay.addLayout(buy_act)

        right = QWidget(split)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(UIScale.px(8))
        rlbl = QLabel("Sell To Fence", right)
        rlbl.setFont(Fonts.mixed_bold)
        rlbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        right_lay.addWidget(rlbl)
        rnote = QLabel("Fence payout scales with area risk  ·  selling adds heat", right)
        rnote.setFont(Fonts.mono_small)
        rnote.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        right_lay.addWidget(rnote)
        self._sell_table = DataTable(right, self._SELL_COLS, row_height=26)
        self._sell_table.row_double_clicked.connect(self._on_sell_double)
        right_lay.addWidget(self._sell_table, 1)
        sell_act = QHBoxLayout()
        sell_act.addWidget(QLabel("Qty:", right))
        self._sell_qty = QSpinBox(right)
        self._sell_qty.setRange(1, 999)
        self._sell_qty.setValue(1)
        self._sell_qty.setFixedWidth(UIScale.px(80))
        sell_act.addWidget(self._sell_qty)
        sell_btn = self.action_button(f"{Sym.EXCHANGE}  Sell Selected", self._do_sell, role="danger")
        sell_btn.setFixedHeight(UIScale.px(30))
        sell_all_btn = self.action_button(f"{Sym.NO}  Sell All", self._do_sell_all, role="danger")
        sell_all_btn.setFixedHeight(UIScale.px(30))
        sell_act.addWidget(sell_btn)
        sell_act.addWidget(sell_all_btn)
        sell_act.addStretch()
        right_lay.addLayout(sell_act)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

        bot = QHBoxLayout()
        bribe_btn = self.action_button(f"{Sym.CONTRACT}  Bribe Guards", self._do_bribe, role="secondary")
        bribe_btn.setFixedHeight(UIScale.px(30))
        bot.addWidget(bribe_btn)
        bot.addWidget(self.back_button())
        bot.addStretch()
        root.addLayout(bot)

    def refresh(self) -> None:
        g = self.game
        espionage = g.skills.espionage
        guard = AREA_INFO[g.current_area].get("guard_strength", 0)
        catch_base = max(0.04, min(0.65, 0.20 + g.heat / 200 - espionage * 0.025))
        heat_color = P.red if g.heat > 60 else (P.amber if g.heat > 30 else P.green)
        fence_mult = g._fence_multiplier()
        fence_label = g._fence_area_label()
        if g.heat >= 80:
            self._heat_lbl.setText("HEAT TOO HIGH — travel or wait before using the den.")
            self._heat_lbl.setStyleSheet(f"color:{P.red}; background:transparent;")
        else:
            self._heat_lbl.setText(
                f"Heat {g.heat}/100  ·  Espionage Lv{espionage}  ·  Guard {guard}/3  ·  {g.current_area.value}"
            )
            self._heat_lbl.setStyleSheet(f"color:{heat_color}; background:transparent;")
        self._detail_lbl.setText(
            f"Catch chance {catch_base * 100:.0f}%  ·  Fence ({fence_label}) {fence_mult * 100:.0f}% of base  ·  Gold {g.inventory.gold:.0f}g"
        )

        contraband = sorted(
            [(key, item) for key, item in ALL_ITEMS.items() if item.illegal],
            key=lambda pair: pair[1].name,
        )
        buy_rows: List[Dict[str, Any]] = []
        for key, item in contraband:
            buy_rows.append({
                "item": item.name,
                "price": f"{item.base_price * 1.25:.1f}g",
                "wt": f"{item.weight:.1f}",
                "catch": f"{catch_base * 100:.0f}%",
                "item_key": key,
                "_tag": "yellow",
            })
        self._buy_table.load(buy_rows)

        sell_rows: List[Dict[str, Any]] = []
        for key, item in contraband:
            qty = g.inventory.items.get(key, 0)
            if qty <= 0:
                continue
            sell_rows.append({
                "item": item.name,
                "qty": str(qty),
                "value": f"{item.base_price * fence_mult * qty:.0f}g",
                "base": f"{item.base_price:.1f}g",
                "item_key": key,
                "_tag": "yellow",
            })
        if not sell_rows:
            sell_rows = [{"item": "No contraband held.", "qty": "", "value": "", "base": "", "item_key": None, "_tag": "dim"}]
        self._sell_table.load(sell_rows)

    def _on_buy_double(self, _row: Dict[str, Any]) -> None:
        if self.game.settings.double_click_action:
            self._do_buy()

    def _on_sell_double(self, _row: Dict[str, Any]) -> None:
        if self.game.settings.double_click_action:
            self._do_sell()

    def _do_buy(self) -> None:
        g = self.game
        row = self._buy_table.selected()
        item_key = row.get("item_key") if row else None
        if not item_key or item_key not in ALL_ITEMS:
            self.msg.warn("Select contraband to buy.")
            return
        if g.heat >= 80:
            self.msg.err("Heat too high — cool down first.")
            return
        qty = self._buy_qty.value()
        item = ALL_ITEMS[item_key]
        price = round(item.base_price * 1.25, 2)
        total = round(price * qty, 2)
        if total > g.inventory.gold:
            self.msg.err(f"Need {total:.0f}g, have {g.inventory.gold:.0f}g.")
            return
        catch_base = max(0.04, min(0.65, 0.20 + g.heat / 200 - g.skills.espionage * 0.025))
        if random.random() < catch_base:
            fine = round(total * 0.60, 2)
            g.inventory.gold = max(0.0, g.inventory.gold - fine)
            g.heat = min(100, g.heat + 35)
            g.reputation = max(0, g.reputation - 20)
            g._track_stat("smuggle_busts")
            g._check_achievements()
            self.msg.err(f"Sting operation. Fine {fine:.0f}g, heat +35, rep -20.")
            self.app.refresh()
            return
        g.inventory.gold -= total
        g.inventory.record_purchase(item_key, qty, price)
        g.inventory.add(item_key, qty)
        g.heat = min(100, g.heat + 8)
        g._gain_skill_xp(SkillType.ESPIONAGE, 10)
        g._use_time(1)
        g._check_achievements()
        self.msg.ok(f"Acquired {qty}× {item.name} for {total:.0f}g. Heat +8.")
        self.app.refresh()

    def _do_sell(self) -> None:
        row = self._sell_table.selected()
        item_key = row.get("item_key") if row else None
        if not item_key or item_key not in ALL_ITEMS:
            self.msg.warn("Select contraband to sell.")
            return
        if self.game.heat >= 80:
            self.msg.err("Heat too high — cool down first.")
            return
        max_qty = self.game.inventory.items.get(item_key, 0)
        qty = self._sell_qty.value()
        if qty < 1 or qty > max_qty:
            self.msg.err(f"Quantity must be 1–{max_qty}.")
            return
        self._execute_sell(item_key, qty)

    def _do_sell_all(self) -> None:
        g = self.game
        if g.heat >= 80:
            self.msg.err("Heat too high — cool down first.")
            return
        row = self._sell_table.selected()
        item_key = row.get("item_key") if row else None
        if item_key and item_key in ALL_ITEMS:
            qty = g.inventory.items.get(item_key, 0)
            if qty > 0:
                self._execute_sell(item_key, qty)
            return
        illegal_keys = [
            key for key, qty in g.inventory.items.items()
            if qty > 0 and ALL_ITEMS.get(key) and ALL_ITEMS[key].illegal
        ]
        if not illegal_keys:
            self.msg.warn("No contraband in inventory.")
            return
        total = 0.0
        count = 0
        for key in illegal_keys:
            if g.heat >= 80:
                break
            qty = g.inventory.items.get(key, 0)
            if qty <= 0:
                continue
            total += self._execute_sell(key, qty, silent=True)
            count += 1
        self.msg.ok(f"Sold {count} contraband stack{'s' if count != 1 else ''} for {total:.0f}g.")
        self.app.refresh()

    def _execute_sell(self, item_key: str, qty: int, silent: bool = False) -> float:
        g = self.game
        item = ALL_ITEMS[item_key]
        fence_mult = g._fence_multiplier()
        catch_base = max(0.04, min(0.65, 0.20 + g.heat / 200 - g.skills.espionage * 0.025))
        sell_catch = min(0.70, catch_base + 0.05)
        total = round(item.base_price * fence_mult * qty, 2)
        if random.random() < sell_catch:
            fine = round(total * 0.50, 2)
            g.inventory.remove(item_key, qty)
            g.inventory.gold = max(0.0, g.inventory.gold - fine)
            g.reputation = max(0, g.reputation - 25)
            g.heat = min(100, g.heat + 35)
            g._track_stat("smuggle_busts")
            g._check_achievements()
            if not silent:
                self.msg.err(f"Busted. {qty}× {item.name} seized, fine {fine:.0f}g, heat +35.")
                self.app.refresh()
            return 0.0
        g.inventory.remove(item_key, qty)
        g.inventory.gold += total
        g.total_profit += total
        g.heat = min(100, g.heat + 10)
        g._gain_skill_xp(SkillType.ESPIONAGE, 15)
        g._track_stat("smuggle_success")
        g._track_stat("smuggle_gold", total)
        g._use_time(1)
        g._check_achievements()
        if not silent:
            self.msg.ok(f"Sold {qty}× {item.name} for {total:.0f}g. Heat +10.")
            self.app.refresh()
        return total

    def _do_bribe(self) -> None:
        g = self.game
        guard = AREA_INFO[g.current_area].get("guard_strength", 0)
        if g.heat <= 0:
            self.msg.ok("No heat right now.")
            return
        if guard == 0:
            self.msg.ok("No guards in this area — heat fades naturally while you travel or rest.")
            return
        bribe_cost = round(g.heat * (3 + guard * 4))
        reduction = random.randint(20, 38)
        backfire = max(0.03, min(0.40, 0.10 + g.heat / 200 - g.skills.espionage * 0.012))
        if not _popup_confirm(
            self,
            "Bribe Guards",
            f"Heat now: {g.heat}/100\nCost: {bribe_cost}g\nExpected reduction: ~{reduction}\nBackfire risk: {backfire * 100:.0f}%",
            confirm_text="Bribe",
        ):
            return
        if g.inventory.gold < bribe_cost:
            self.msg.err(f"Need {bribe_cost}g.")
            return
        g.inventory.gold -= bribe_cost
        if random.random() < backfire:
            g.heat = min(100, g.heat + 15)
            g.reputation = max(0, g.reputation - 10)
            self.msg.warn(f"The guard took {bribe_cost}g and filed a report. Heat +15, rep -10.")
        else:
            g.heat = max(0, g.heat - reduction)
            g._gain_skill_xp(SkillType.ESPIONAGE, 8)
            g._track_stat("bribes")
            g._check_achievements()
            self.msg.ok(f"The bribe worked. Heat -{reduction} to {g.heat}/100.")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# NEWS SCREEN  —  active events, headlines, and historical logs
# ══════════════════════════════════════════════════════════════════════════════

class NewsScreen(Screen):
    _HINTS = {
        "Drought": "Grain and fibre are scarce; agricultural prices tend to rise.",
        "Flood": "Farms and coastal supply chains are disrupted.",
        "Bumper Harvest": "Crop prices usually soften while supply is strong.",
        "Mine Collapse": "Ore, gems, and coal become harder to source.",
        "Piracy Surge": "Sea trade is unstable and coastal goods tighten.",
        "Trade Boom": "Demand is stronger across many goods.",
        "Plague": "Medicine and herbs surge in strategic value.",
        "Border War": "Steel and ore demand rise with conflict.",
        "Gold Rush": "Gold dust tends to lose scarcity value.",
        "Grand Festival": "Luxury items see stronger demand.",
    }

    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        root.addWidget(self.section_label("News & Events"))

        tabs = QTabWidget(self)
        tabs.setFont(Fonts.mixed_small)
        root.addWidget(tabs, 1)

        ev_tab = QWidget(self)
        ev_lay = QVBoxLayout(ev_tab)
        ev_lay.setContentsMargins(0, 0, 0, 0)
        self._ev_table = DataTable(ev_tab, [
            ("area", "Area", 160),
            ("event", "Event", 180),
            ("effect", "Effect", 520),
        ], row_height=26)
        ev_lay.addWidget(self._ev_table)
        tabs.addTab(ev_tab, f"{Sym.WARNING}  Active Events")

        feed_tab = QWidget(self)
        feed_lay = QVBoxLayout(feed_tab)
        feed_lay.setContentsMargins(0, 0, 0, 0)
        self._feed_table = DataTable(feed_tab, [
            ("date", "Date", 86),
            ("area", "Area", 130),
            ("event", "Event", 170),
            ("headline", "Headline", 500),
        ], row_height=26)
        feed_lay.addWidget(self._feed_table)
        tabs.addTab(feed_tab, f"{Sym.NEWS}  Headlines")

        log_tab = QWidget(self)
        log_lay = QVBoxLayout(log_tab)
        log_lay.setContentsMargins(0, 0, 0, 0)
        self._log_table = DataTable(log_tab, [("entry", "Event Log", 920)], row_height=24)
        log_lay.addWidget(self._log_table)
        tabs.addTab(log_tab, f"{Sym.PROGRESS}  Event Log")

        trade_tab = QWidget(self)
        trade_lay = QVBoxLayout(trade_tab)
        trade_lay.setContentsMargins(0, 0, 0, 0)
        self._trade_table = DataTable(trade_tab, [("entry", "Trade Log", 920)], row_height=24)
        trade_lay.addWidget(self._trade_table)
        tabs.addTab(trade_tab, f"{Sym.TRADE}  Trade Log")

        foot = QHBoxLayout()
        foot.addWidget(self.back_button())
        foot.addStretch()
        root.addLayout(foot)

    def refresh(self) -> None:
        g = self.game
        seen: set[Tuple[str, str]] = set()
        active_rows: List[Dict[str, Any]] = []
        for area, market in g.markets.items():
            for event_name in getattr(market, "active_events", []):
                key = (area.value, event_name)
                if key in seen:
                    continue
                seen.add(key)
                active_rows.append({
                    "area": area.value,
                    "event": event_name,
                    "effect": self._HINTS.get(event_name, "Market conditions are shifting in this area."),
                    "_tag": "yellow",
                })
        self._ev_table.load(active_rows)

        feed_rows: List[Dict[str, str]] = []
        for abs_day, area_name, event_name, headline in list(getattr(g, "news_feed", [])):
            year = (abs_day - 1) // 360 + 1
            day = (abs_day - 1) % 360 + 1
            feed_rows.append({
                "date": f"Y{year}D{day}",
                "area": str(area_name),
                "event": str(event_name),
                "headline": str(headline),
            })
        self._feed_table.load(feed_rows)
        self._log_table.load([{"entry": str(entry)} for entry in list(getattr(g, "event_log", []))[:40]])
        self._trade_table.load([{"entry": str(entry)} for entry in list(getattr(g, "trade_log", []))[:40]])


# ══════════════════════════════════════════════════════════════════════════════
# PROGRESS SCREEN  —  statistics, achievements, and title progression
# ══════════════════════════════════════════════════════════════════════════════

class ProgressScreen(Screen):
    _STAT_COLS = [
        ("stat", "Statistic", 280),
        ("value", "Value", 260),
    ]
    _ACH_COLS = [
        ("status", "Status", 64, Qt.AlignmentFlag.AlignCenter),
        ("tier", "Tier", 84),
        ("icon", "Icon", 48, Qt.AlignmentFlag.AlignCenter),
        ("name", "Name", 220),
        ("desc", "Description / Hint", 470),
    ]
    _TITLE_COLS = [
        ("status", "Status", 64, Qt.AlignmentFlag.AlignCenter),
        ("tier", "Tier", 90),
        ("icon", "Icon", 48, Qt.AlignmentFlag.AlignCenter),
        ("name", "Title", 230),
        ("desc", "Description", 430),
    ]

    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        root.addWidget(self.section_label("Progress"))

        tabs = QTabWidget(self)
        tabs.setFont(Fonts.mixed_small)
        root.addWidget(tabs, 1)

        stats_tab = QWidget(self)
        stats_lay = QVBoxLayout(stats_tab)
        stats_lay.setContentsMargins(0, 0, 0, 0)
        self._stats_table = DataTable(stats_tab, self._STAT_COLS, row_height=24)
        stats_lay.addWidget(self._stats_table)
        tabs.addTab(stats_tab, f"{Sym.INFO}  Statistics")

        ach_tab = QWidget(self)
        ach_lay = QVBoxLayout(ach_tab)
        ach_lay.setContentsMargins(0, 0, 0, 0)
        self._ach_lbl = QLabel(ach_tab)
        self._ach_lbl.setFont(Fonts.mono_small)
        self._ach_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        ach_lay.addWidget(self._ach_lbl)
        self._ach_table = DataTable(ach_tab, self._ACH_COLS, row_height=24)
        ach_lay.addWidget(self._ach_table)
        tabs.addTab(ach_tab, f"{Sym.PROGRESS}  Achievements")

        title_tab = QWidget(self)
        title_lay = QVBoxLayout(title_tab)
        title_lay.setContentsMargins(0, 0, 0, 0)
        self._title_lbl = QLabel(title_tab)
        self._title_lbl.setFont(Fonts.mono_small)
        self._title_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        title_lay.addWidget(self._title_lbl)
        self._title_table = DataTable(title_tab, self._TITLE_COLS, row_height=24)
        title_lay.addWidget(self._title_table)
        tabs.addTab(title_tab, f"{Sym.SKILLS}  Titles")

        foot = QHBoxLayout()
        foot.addWidget(self.back_button())
        foot.addStretch()
        root.addLayout(foot)

    def refresh(self) -> None:
        g = self.game
        abs_day = g._absolute_day()
        year = (abs_day - 1) // 360 + 1
        portfolio_value = g._portfolio_value() if hasattr(g, "_portfolio_value") else 0.0
        active_citizen_loans = sum(
            1 for loan in getattr(g, "citizen_loans", [])
            if not getattr(loan, "defaulted", False) and getattr(loan, "weeks_remaining", 0) > 0
        )
        active_fund_clients = sum(
            1 for client in getattr(g, "fund_clients", [])
            if not getattr(client, "withdrawn", False)
        )
        weekly_income = sum(
            getattr(loan, "weekly_payment", 0.0) for loan in getattr(g, "citizen_loans", [])
            if not getattr(loan, "defaulted", False) and getattr(loan, "weeks_remaining", 0) > 0
        )
        stats_rows = [
            {"stat": "Player", "value": g.player_name},
            {"stat": "Days Played", "value": f"{abs_day} (Year {year})"},
            {"stat": "Current Area", "value": g.current_area.value},
            {"stat": "Gold in Wallet", "value": f"{g.inventory.gold:,.2f}g"},
            {"stat": "Bank Balance", "value": f"{g.bank_balance:,.2f}g"},
            {"stat": "Net Worth", "value": f"{g._net_worth():,.2f}g"},
            {"stat": "Total Profit", "value": f"{g.total_profit:,.0f}g"},
            {"stat": "Reputation", "value": f"{g.reputation}"},
            {"stat": "Heat", "value": f"{g.heat}"},
            {"stat": "Licenses Held", "value": f"{len(g.licenses)} / {len(LicenseType)}"},
            {"stat": "Lifetime Trades", "value": f"{g.lifetime_trades}"},
            {"stat": "Contracts Completed", "value": f"{g.ach_stats.get('contracts_completed', 0)}"},
            {"stat": "Smuggling Busts", "value": f"{g.ach_stats.get('smuggle_busts', 0)}"},
            {"stat": "Journeys Made", "value": f"{g.ach_stats.get('journeys', 0)}"},
            {"stat": "Travel Days", "value": f"{g.ach_stats.get('travel_days', 0)}"},
            {"stat": "Max Single Sale", "value": f"{g.ach_stats.get('max_single_sale', 0):,.0f}g"},
            {"stat": "Businesses Owned", "value": f"{len(g.businesses)}"},
            {"stat": "Active Contracts", "value": f"{sum(1 for c in g.contracts if not c.fulfilled)}"},
            {"stat": "Citizen Loans Active", "value": f"{active_citizen_loans} (weekly {weekly_income:.1f}g)"},
            {"stat": "Fund Clients Active", "value": f"{active_fund_clients}"},
            {"stat": "Stock Portfolio", "value": f"{portfolio_value:,.0f}g" if portfolio_value > 0 else "No holdings"},
            {"stat": "Trading Skill", "value": f"Lv {g.skills.trading}"},
            {"stat": "Haggling Skill", "value": f"Lv {g.skills.haggling}"},
            {"stat": "Logistics Skill", "value": f"Lv {g.skills.logistics}"},
            {"stat": "Industry Skill", "value": f"Lv {g.skills.industry}"},
            {"stat": "Espionage Skill", "value": f"Lv {g.skills.espionage}"},
            {"stat": "Banking Skill", "value": f"Lv {g.skills.banking}"},
        ]
        self._stats_table.load(stats_rows)

        unlocked = set(getattr(g, "achievements", set()))
        total = len(ACHIEVEMENTS)
        unlocked_count = len(unlocked)
        self._ach_lbl.setText(f"Unlocked: {unlocked_count} / {total} ({unlocked_count * 100 // max(total, 1)}%)")
        ach_rows: List[Dict[str, Any]] = []
        for ach in ACHIEVEMENTS:
            is_unlocked = ach["id"] in unlocked
            hidden = bool(ach.get("hidden", False))
            ach_rows.append({
                "status": "✓" if is_unlocked else "○",
                "tier": str(ach.get("tier", "")).title(),
                "icon": str(ach.get("icon", "★")),
                "name": ach.get("name", "") if (is_unlocked or not hidden) else "???",
                "desc": ach.get("desc", "") if is_unlocked else (ach.get("hint", "") if not hidden else "Hidden achievement"),
                "_tag": "green" if is_unlocked else "dim",
                "_order": 0 if is_unlocked else 1,
            })
        ach_rows.sort(key=lambda row: (row["_order"], row["tier"], row["name"]))
        for row in ach_rows:
            row.pop("_order", None)
        self._ach_table.load(ach_rows)

        earned_titles = list(getattr(g, "earned_titles", []))
        active_title = getattr(g, "active_title_id", None)
        self._title_lbl.setText(
            f"Earned titles: {len(earned_titles)} / {len(TITLE_DEFINITIONS)}"
            + (f"  ·  Active: {TITLES_BY_ID[active_title]['name']}" if active_title in TITLES_BY_ID else "")
        )
        title_rows: List[Dict[str, Any]] = []
        for title_def in TITLE_DEFINITIONS:
            title_id = title_def["id"]
            unlocked_title = title_id in earned_titles
            hidden = bool(title_def.get("hidden", False))
            title_rows.append({
                "status": "✓" if unlocked_title else ("◉" if title_id == active_title else "○"),
                "tier": str(title_def.get("tier", "")).title(),
                "icon": str(title_def.get("icon", "★")),
                "name": title_def.get("name", "") if (unlocked_title or not hidden) else "???",
                "desc": title_def.get("desc", "") if (unlocked_title or not hidden) else "Hidden title",
                "_tag": "green" if unlocked_title else "dim",
                "_order": 0 if unlocked_title else 1,
            })
        title_rows.sort(key=lambda row: (row["_order"], row["tier"], row["name"]))
        for row in title_rows:
            row.pop("_order", None)
        self._title_table.load(title_rows)


# ══════════════════════════════════════════════════════════════════════════════
# LICENSES SCREEN  —  buy permits and inspect unlock requirements
# ══════════════════════════════════════════════════════════════════════════════

class LicensesScreen(Screen):
    _COLS = [
        ("status", "Have", 58, Qt.AlignmentFlag.AlignCenter),
        ("name", "License", 220),
        ("cost", "Cost", 76, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("rep_req", "Rep Req", 76, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("bank_req", "Banking", 76, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("tier", "Tier", 82),
        ("desc", "Description", 350),
    ]

    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        root.addWidget(self.section_label("Licenses & Permits"))

        intro = QLabel(
            "Purchase licenses to unlock additional systems. Reputation and, for some permits, Banking skill gate access.",
            self,
        )
        intro.setFont(Fonts.mono_small)
        intro.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        intro.setWordWrap(True)
        root.addWidget(intro)

        self._table = DataTable(self, self._COLS, row_height=26)
        self._table.row_selected.connect(self._on_select)
        root.addWidget(self._table, 1)

        self._detail = QLabel("Select a license to inspect requirements and unlocks.", self)
        self._detail.setFont(Fonts.mono_small)
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet(
            f"color:{P.fg_dim}; background:{P.bg_panel}; border:1px solid {P.border};"
            f"padding:{UIScale.px(8)}px; border-radius:{UIScale.px(4)}px;"
        )
        root.addWidget(self._detail)

        act = QHBoxLayout()
        buy_btn = self.action_button(f"{Sym.YES}  Purchase Selected License", self._do_buy_license)
        buy_btn.setFixedHeight(UIScale.px(30))
        act.addWidget(buy_btn)
        act.addWidget(self.back_button())
        act.addStretch()
        root.addLayout(act)

    def refresh(self) -> None:
        g = self.game
        rows: List[Dict[str, Any]] = []
        for license_type in LicenseType:
            info = LICENSE_INFO.get(license_type, {})
            cost = float(info.get("cost", 0))
            rep_req = int(info.get("rep", 0))
            bank_req = int(info.get("banking", 0))
            have = license_type in g.licenses
            can_buy = g._can_buy_license(license_type) and g.inventory.gold >= cost
            rows.append({
                "status": "✓" if have else "",
                "name": license_type.value,
                "cost": "Free" if cost <= 0 else f"{cost:.0f}g",
                "rep_req": str(rep_req),
                "bank_req": str(bank_req),
                "tier": str(info.get("tier", "")).title(),
                "desc": str(info.get("desc", "")),
                "license_enum": license_type,
                "_tag": "green" if have else ("cyan" if can_buy else "dim"),
            })
        self._table.load(rows)

    def _on_select(self, row: Dict[str, Any]) -> None:
        license_type = row.get("license_enum") if row else None
        if not isinstance(license_type, LicenseType):
            return
        g = self.game
        info = LICENSE_INFO.get(license_type, {})
        cost = float(info.get("cost", 0))
        rep_req = int(info.get("rep", 0))
        bank_req = int(info.get("banking", 0))
        unlocks = str(info.get("unlocks", ""))
        have = license_type in g.licenses
        status = "Owned" if have else "Available" if g._can_buy_license(license_type) else "Locked"
        status_color = P.green if have else P.gold if g._can_buy_license(license_type) else P.red
        self._detail.setText(
            f"{license_type.value}  ·  {status}\n"
            f"Cost: {'Free' if cost <= 0 else f'{cost:.0f}g'}  ·  Reputation {g.reputation}/{rep_req}  ·  Banking {g.skills.banking}/{bank_req}\n"
            f"{info.get('desc', '')}\n"
            f"Unlocks: {unlocks}"
        )
        self._detail.setStyleSheet(
            f"color:{status_color}; background:{P.bg_panel}; border:1px solid {P.border};"
            f"padding:{UIScale.px(8)}px; border-radius:{UIScale.px(4)}px;"
        )

    def _do_buy_license(self) -> None:
        row = self._table.selected()
        license_type = row.get("license_enum") if row else None
        if not isinstance(license_type, LicenseType):
            self.msg.warn("Select a license to purchase.")
            return
        g = self.game
        if license_type in g.licenses:
            self.msg.info("You already hold this license.")
            return
        info = LICENSE_INFO.get(license_type, {})
        cost = float(info.get("cost", 0))
        rep_req = int(info.get("rep", 0))
        bank_req = int(info.get("banking", 0))
        if g.reputation < rep_req:
            self.msg.err(f"Reputation too low ({g.reputation}/{rep_req}).")
            return
        if g.skills.banking < bank_req:
            self.msg.err(f"Banking skill too low (Lv {g.skills.banking}/{bank_req}).")
            return
        if g.inventory.gold < cost:
            self.msg.err(f"Need {cost:.0f}g. Have {g.inventory.gold:.0f}g.")
            return
        if not _popup_confirm(
            self,
            "Purchase License",
            f"Purchase {license_type.value} for {cost:.0f}g?",
            confirm_text="Purchase",
        ):
            return
        if not _maybe_sign(self, "license", detail=f"{license_type.value} for {cost:.0f}g"):
            return
        g.inventory.gold -= cost
        g.licenses.add(license_type)
        g._track_stat("licenses_purchased")
        g._check_achievements()
        self.msg.ok(f"Licensed: {license_type.value}.")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# FINANCE SCREEN  —  banking, loans, and certificates of deposit
# ══════════════════════════════════════════════════════════════════════════════

class FinanceScreen(Screen):
    _CD_COLS = [
        ("principal", "Principal", 110, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("rate", "Rate", 78, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("payout", "Payout", 110, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("profit", "Profit", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("days_left", "Days Left", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("term", "Term", 70, Qt.AlignmentFlag.AlignCenter),
    ]
    _LOAN_COLS = [
        ("principal", "Principal", 110, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("rate", "Rate/mo", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("monthly", "Monthly", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("months", "Months Left", 95, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("total", "Total Left", 100, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]
    _CD_TIERS = [
        (30, "Short-Term (30 days)", 0.08),
        (90, "Standard (90 days)", 0.26),
        (180, "Extended (180 days)", 0.55),
        (360, "Long-Term (360 days)", 1.20),
    ]

    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        root.addWidget(self.section_label("Banking & Finance"))

        tabs = QTabWidget(self)
        tabs.setFont(Fonts.mixed_small)
        root.addWidget(tabs, 1)

        ov_tab = QWidget(self)
        ov_lay = QVBoxLayout(ov_tab)
        ov_lay.setContentsMargins(0, 0, 0, 0)
        ov_lay.setSpacing(UIScale.px(8))
        self._overview_txt = QTextEdit(ov_tab)
        self._overview_txt.setReadOnly(True)
        self._overview_txt.setFont(Fonts.mono)
        self._overview_txt.setStyleSheet(
            f"QTextEdit{{background:{P.bg}; color:{P.fg}; border:1px solid {P.border};"
            f"border-radius:{UIScale.px(4)}px; padding:{UIScale.px(8)}px;}}"
        )
        ov_lay.addWidget(self._overview_txt)
        ov_act = QHBoxLayout()
        for text, handler, role in [
            (f"{Sym.YES}  Deposit", self._do_deposit, "primary"),
            (f"{Sym.EXCHANGE}  Withdraw", self._do_withdraw, "secondary"),
            (f"{Sym.CONTRACT}  Take Loan", self._do_loan, "secondary"),
            (f"{Sym.YES}  Open CD", self._do_cd, "secondary"),
        ]:
            btn = self.action_button(text, handler, role=role)
            btn.setFixedHeight(UIScale.px(30))
            ov_act.addWidget(btn)
        ov_act.addStretch()
        ov_lay.addLayout(ov_act)
        tabs.addTab(ov_tab, f"{Sym.INFO}  Overview")

        cd_tab = QWidget(self)
        cd_lay = QVBoxLayout(cd_tab)
        cd_lay.setContentsMargins(0, 0, 0, 0)
        self._cd_table = DataTable(cd_tab, self._CD_COLS, row_height=26)
        cd_lay.addWidget(self._cd_table)
        tabs.addTab(cd_tab, f"{Sym.SAVE}  Certificates")

        loan_tab = QWidget(self)
        loan_lay = QVBoxLayout(loan_tab)
        loan_lay.setContentsMargins(0, 0, 0, 0)
        loan_lay.setSpacing(UIScale.px(8))
        self._loan_table = DataTable(loan_tab, self._LOAN_COLS, row_height=26)
        loan_lay.addWidget(self._loan_table, 1)
        repay_btn = self.action_button(f"{Sym.NO}  Repay Selected Loan", self._do_repay, role="danger")
        repay_btn.setFixedHeight(UIScale.px(30))
        loan_lay.addWidget(repay_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        tabs.addTab(loan_tab, f"{Sym.CONTRACT}  Loans")

        foot = QHBoxLayout()
        foot.addWidget(self.back_button())
        foot.addStretch()
        root.addLayout(foot)

    def refresh(self) -> None:
        g = self.game
        monthly_rate = 0.015 + g.skills.banking * 0.002
        abs_day = g._absolute_day()
        text = (
            f"Wallet:        {g.inventory.gold:>12.2f}g\n"
            f"Bank Balance:  {g.bank_balance:>12.2f}g\n"
            f"Net Worth:     {g._net_worth():>12.2f}g\n\n"
            f"Savings Rate:  {monthly_rate * 100:.1f}%/month\n"
            f"Banking Skill: Lv{g.skills.banking}  (+{g.skills.banking * 0.2:.1f}%/month)\n"
            f"Active CDs:    {len(g.cds)}\n"
            f"Active Loans:  {len(g.loans)}"
        )
        self._overview_txt.setPlainText(text)

        cd_rows: List[Dict[str, Any]] = []
        for idx, cd in enumerate(g.cds):
            days_left = cd.maturity_day - abs_day
            payout = round(cd.principal * (1 + cd.rate), 2)
            profit = round(payout - cd.principal, 2)
            cd_rows.append({
                "principal": f"{cd.principal:.0f}g",
                "rate": f"{cd.rate * 100:.0f}%",
                "payout": f"{payout:.0f}g",
                "profit": f"+{profit:.0f}g",
                "days_left": str(max(0, days_left)),
                "term": f"{cd.term_days}d",
                "cd_index": idx,
                "_tag": "red" if days_left <= 5 else ("yellow" if days_left <= 15 else "green"),
            })
        self._cd_table.load(cd_rows)

        loan_rows: List[Dict[str, Any]] = []
        for idx, loan in enumerate(g.loans):
            total_left = round(loan.monthly_payment * loan.months_remaining, 2)
            loan_rows.append({
                "principal": f"{loan.principal:.0f}g",
                "rate": f"{loan.interest_rate * 100:.2f}%",
                "monthly": f"{loan.monthly_payment:.2f}g",
                "months": str(loan.months_remaining),
                "total": f"{total_left:.0f}g",
                "loan_index": idx,
            })
        self._loan_table.load(loan_rows)

    def _do_deposit(self) -> None:
        g = self.game
        raw = _popup_get_text(
            self,
            "Deposit",
            f"Deposit into savings.\n\nWallet: {g.inventory.gold:.0f}g\nAmount:",
            placeholder="100",
            confirm_text="Deposit",
        )
        if raw is None:
            return
        try:
            amount = float(raw)
        except ValueError:
            self.msg.err("Invalid amount.")
            return
        if amount <= 0 or amount > g.inventory.gold:
            self.msg.err("Invalid amount.")
            return
        g.inventory.gold -= amount
        g.bank_balance += amount
        self.msg.ok(f"Deposited {amount:.2f}g.")
        self.app.refresh()

    def _do_withdraw(self) -> None:
        g = self.game
        raw = _popup_get_text(
            self,
            "Withdraw",
            f"Withdraw from savings.\n\nBank: {g.bank_balance:.0f}g\nAmount:",
            placeholder="100",
            confirm_text="Withdraw",
        )
        if raw is None:
            return
        try:
            amount = float(raw)
        except ValueError:
            self.msg.err("Invalid amount.")
            return
        if amount <= 0 or amount > g.bank_balance:
            self.msg.err("Invalid amount.")
            return
        g.bank_balance -= amount
        g.inventory.gold += amount
        self.msg.ok(f"Withdrew {amount:.2f}g.")
        self.app.refresh()

    def _do_loan(self) -> None:
        g = self.game
        credit_penalty = max(0.0, (50 - g.reputation) / 100)
        rate = round(max(0.006, min(0.040, 0.018 + credit_penalty * 0.008 - g.skills.banking * 0.001)), 4)
        max_loan = max(500.0, g._net_worth() * 0.4)
        term_text, ok = _popup_choose(
            self,
            "Loan Term",
            f"Select a loan term.\n\nRate: {rate * 100:.2f}%/month\nMax available: {max_loan:.0f}g",
            ["6 months", "12 months"],
            confirm_text="Choose Term",
        )
        if not ok:
            return
        months = 6 if term_text.startswith("6") else 12
        raw = _popup_get_text(
            self,
            "Take Loan",
            f"Loan amount (1–{max_loan:.0f}g)\nRate: {rate * 100:.2f}%/mo  ·  Term: {months} months",
            placeholder="250",
            confirm_text="Continue",
        )
        if raw is None:
            return
        try:
            amount = float(raw)
        except ValueError:
            self.msg.err("Invalid amount.")
            return
        if not (1 <= amount <= max_loan):
            self.msg.err(f"Amount must be 1–{max_loan:.0f}g.")
            return
        monthly = round(amount * (rate * (1 + rate) ** months) / ((1 + rate) ** months - 1), 2)
        total_repaid = round(monthly * months, 2)
        total_interest = round(total_repaid - amount, 2)
        if not _popup_confirm(
            self,
            "Confirm Loan",
            f"Loan: {amount:.0f}g\nMonthly payment: {monthly:.2f}g\nTerm: {months} months\nTotal interest: {total_interest:.0f}g",
            confirm_text="Accept Loan",
        ):
            return
        if not _maybe_sign(self, "loan", detail=f"{amount:.0f}g · {months} months · {rate * 100:.2f}%/mo"):
            return
        g.inventory.gold += amount
        g.loans.append(LoanRecord(
            principal=amount,
            interest_rate=rate,
            months_remaining=months,
            monthly_payment=monthly,
        ))
        if hasattr(g, "_log_event"):
            g._log_event(f"Took loan of {amount:.0f}g @ {rate*100:.2f}%/mo for {months}mo")
        g._gain_skill_xp(SkillType.BANKING, 10)
        g._track_stat("loans_taken")
        g._check_achievements()
        self.msg.ok(f"Loan of {amount:.0f}g approved. Monthly: {monthly:.2f}g × {months} months.")
        self.app.refresh()

    def _do_cd(self) -> None:
        g = self.game
        bonus = g.skills.banking * 0.02
        if g.bank_balance <= 0:
            self.msg.err("No bank balance to invest.")
            return
        tier_labels = [f"{label}  →  {(rate + bonus) * 100:.0f}% return" for _, label, rate in self._CD_TIERS]
        choice, ok = _popup_choose(
            self,
            "Open CD",
            f"Choose a CD term.\n\nBank Balance: {g.bank_balance:.0f}g\nBanking skill bonus: +{bonus * 100:.0f}%",
            tier_labels,
            confirm_text="Choose Tier",
        )
        if not ok:
            return
        idx = tier_labels.index(choice)
        term_days, label, base_rate = self._CD_TIERS[idx]
        rate = round(base_rate + bonus, 4)
        raw = _popup_get_text(
            self,
            "Open CD",
            f"{label}\nReturn: {rate * 100:.0f}%\nBank Balance: {g.bank_balance:.0f}g\nAmount to invest:",
            placeholder="250",
            confirm_text="Open CD",
        )
        if raw is None:
            return
        try:
            amount = float(raw)
        except ValueError:
            self.msg.err("Invalid amount.")
            return
        if amount <= 0 or amount > g.bank_balance:
            self.msg.err(f"Need {amount:.0f}g in bank (have {g.bank_balance:.0f}g).")
            return
        g.bank_balance -= amount
        g.cds.append(CDRecord(
            principal=amount,
            rate=rate,
            maturity_day=g._absolute_day() + term_days,
            term_days=term_days,
        ))
        payout = round(amount * (1 + rate), 2)
        g._check_achievements()
        self.msg.ok(
            f"CD opened: {amount:.0f}g → {payout:.0f}g in {term_days} days (+{payout - amount:.0f}g)."
        )
        self.app.refresh()

    def _do_repay(self) -> None:
        row = self._loan_table.selected()
        idx = row.get("loan_index") if row else None
        if not isinstance(idx, int) or not (0 <= idx < len(self.game.loans)):
            self.msg.warn("Select a loan to repay.")
            return
        g = self.game
        loan = g.loans[idx]
        payoff = round(loan.monthly_payment * loan.months_remaining, 2)
        if not _popup_confirm(
            self,
            "Repay Loan",
            f"Repay this loan in full?\n\nTotal due: {payoff:.2f}g",
            confirm_text="Repay Loan",
            confirm_role="danger",
        ):
            return
        if g.inventory.gold < payoff:
            self.msg.err(f"Need {payoff:.2f}g. Have {g.inventory.gold:.2f}g.")
            return
        g.inventory.gold -= payoff
        g.loans.pop(idx)
        g.reputation = min(100, g.reputation + 5)
        g._gain_skill_xp(SkillType.BANKING, 15)
        g._track_stat("loans_repaid")
        g._check_achievements()
        self.msg.ok(f"Loan fully repaid ({payoff:.0f}g).")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# CITIZEN LENDING SCREEN  —  issue personal loans and manage repayment ledger
# ══════════════════════════════════════════════════════════════════════════════

class CitizenLendingScreen(Screen):
    _LOAN_COLS = [
        ("borrower", "Borrower", 160),
        ("principal", "Principal", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("rate", "Rate/wk", 70, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("weeks", "Wks Left", 68, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("payment", "Wk Payment", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("received", "Received", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("status", "Status", 90),
    ]
    _APPL_COLS = [
        ("name", "Applicant", 155),
        ("amount", "Amount", 75, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("purpose", "Purpose", 140),
        ("weeks", "Weeks", 55, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("max_rate", "Max Rate", 70, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("risk", "Default Risk", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("cw", "Credit", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]

    def build(self) -> None:
        self._applicants: List[Dict[str, Any]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        hdr = QHBoxLayout()
        hdr.addWidget(self.section_label("Citizen Lending"))
        hdr.addStretch()
        self._summary_lbl = QLabel(self)
        self._summary_lbl.setFont(Fonts.mono_small)
        self._summary_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        hdr.addWidget(self._summary_lbl)
        root.addLayout(hdr)

        tabs = QTabWidget(self)
        tabs.setFont(Fonts.mixed_small)
        root.addWidget(tabs, 1)

        active_tab = QWidget(self)
        active_lay = QVBoxLayout(active_tab)
        active_lay.setContentsMargins(0, 0, 0, 0)
        active_lay.setSpacing(UIScale.px(8))
        self._loan_table = DataTable(active_tab, self._LOAN_COLS, row_height=26)
        active_lay.addWidget(self._loan_table, 1)
        recall_btn = self.action_button(f"{Sym.NO}  Recall Loan Early", self._recall_loan, role="danger")
        recall_btn.setFixedHeight(UIScale.px(30))
        active_lay.addWidget(recall_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        tabs.addTab(active_tab, f"{Sym.CONTRACT}  Active Loans")

        appl_tab = QWidget(self)
        appl_lay = QVBoxLayout(appl_tab)
        appl_lay.setContentsMargins(0, 0, 0, 0)
        appl_lay.setSpacing(UIScale.px(8))
        pool_row = QHBoxLayout()
        refresh_btn = self.action_button(f"{Sym.SYNC}  New Pool", self._refresh_pool, role="secondary")
        refresh_btn.setFixedHeight(UIScale.px(28))
        pool_row.addWidget(refresh_btn)
        pool_hint = QLabel("Offer a rate at or below the applicant's max rate to proceed.", appl_tab)
        pool_hint.setFont(Fonts.mono_small)
        pool_hint.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        pool_row.addWidget(pool_hint)
        pool_row.addStretch()
        appl_lay.addLayout(pool_row)
        self._appl_table = DataTable(appl_tab, self._APPL_COLS, row_height=26)
        appl_lay.addWidget(self._appl_table, 1)
        issue_btn = self.action_button(f"{Sym.YES}  Issue Loan", self._issue_loan)
        issue_btn.setFixedHeight(UIScale.px(30))
        appl_lay.addWidget(issue_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        tabs.addTab(appl_tab, f"{Sym.YES}  New Applicants")

        foot = QHBoxLayout()
        foot.addWidget(self.back_button())
        foot.addStretch()
        root.addLayout(foot)

    def refresh(self) -> None:
        g = self.game
        if LicenseType.LENDER not in g.licenses:
            self._summary_lbl.setText("Lending Charter required")
            self._summary_lbl.setStyleSheet(f"color:{P.red}; background:transparent;")
            self._loan_table.load([])
            self._appl_table.load([])
            return

        active = [cl for cl in g.citizen_loans if not cl.defaulted and cl.weeks_remaining > 0]
        outstanding = sum(cl.principal for cl in active)
        weekly_income = sum(cl.weekly_payment for cl in active)
        self._summary_lbl.setText(
            f"Active: {len(active)}  ·  Capital out: {outstanding:.0f}g  ·  Weekly income: {weekly_income:.1f}g"
        )
        self._summary_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")

        loan_rows: List[Dict[str, Any]] = []
        for idx, cl in enumerate(g.citizen_loans):
            if cl.defaulted:
                status, tag = "Defaulted", "red"
            elif cl.weeks_remaining <= 0:
                status, tag = "Repaid", "dim"
            elif cl.weeks_remaining <= 2:
                status, tag = f"{cl.weeks_remaining}wk left", "yellow"
            else:
                status, tag = f"{cl.weeks_remaining}wk left", "green"
            loan_rows.append({
                "borrower": cl.borrower_name,
                "principal": f"{cl.principal:.0f}g",
                "rate": f"{cl.interest_rate * 100:.1f}%",
                "weeks": str(cl.weeks_remaining),
                "payment": f"{cl.weekly_payment:.1f}g",
                "received": f"{cl.total_received:.0f}g",
                "status": status,
                "loan_index": idx,
                "_tag": tag,
            })
        self._loan_table.load(loan_rows)

        if not self._applicants:
            self._applicants = g._gen_loan_applicants(6)
        self._load_applicant_rows()

    def _load_applicant_rows(self) -> None:
        rows: List[Dict[str, Any]] = []
        for idx, applicant in enumerate(self._applicants):
            cw = applicant["creditworthiness"]
            rows.append({
                "name": applicant["name"],
                "amount": f"{applicant['amount']:.0f}g",
                "purpose": applicant["purpose"],
                "weeks": str(applicant["weeks"]),
                "max_rate": f"{applicant['max_rate'] * 100:.1f}%",
                "risk": f"{applicant['default_risk'] * 100:.1f}%",
                "cw": f"{cw:.2f}",
                "applicant_index": idx,
                "_tag": "red" if cw < 0.85 else ("yellow" if cw < 1.15 else "green"),
            })
        self._appl_table.load(rows)

    def _refresh_pool(self) -> None:
        self._applicants = self.game._gen_loan_applicants(6)
        self._load_applicant_rows()

    def _issue_loan(self) -> None:
        g = self.game
        if LicenseType.LENDER not in g.licenses:
            self.msg.err("Lending Charter required.")
            return
        row = self._appl_table.selected()
        idx = row.get("applicant_index") if row else None
        if not isinstance(idx, int) or not (0 <= idx < len(self._applicants)):
            self.msg.warn("Select an applicant first.")
            return
        applicant = self._applicants[idx]
        if g.inventory.gold < applicant["amount"]:
            self.msg.err(f"Need {applicant['amount']:.0f}g. Have {g.inventory.gold:.0f}g.")
            return

        rate_str = _popup_get_text(
            self,
            "Issue Loan",
            f"Loan to {applicant['name']}: {applicant['amount']:.0f}g / {applicant['weeks']} weeks\n"
            f"Purpose: {applicant['purpose']}\n"
            f"Max rate they'll accept: {applicant['max_rate'] * 100:.1f}%/wk\n\n"
            "Enter your interest rate as a decimal (example: 0.04 for 4%/wk):",
            default="0.04",
            confirm_text="Continue",
        )
        if rate_str is None:
            return
        try:
            rate = float(rate_str)
        except ValueError:
            self.msg.err("Invalid rate. Enter a decimal like 0.05.")
            return
        if rate <= 0:
            self.msg.err("Rate must be positive.")
            return
        if rate > applicant["max_rate"]:
            self.msg.err(
                f"Rate {rate * 100:.1f}% exceeds max {applicant['max_rate'] * 100:.1f}%. Applicant refused."
            )
            return

        weeks = applicant["weeks"]
        principal = applicant["amount"]
        weekly_payment = round(principal * (rate + 1.0 / weeks), 2)
        total_return = round(weekly_payment * weeks, 2)
        profit = round(total_return - principal, 2)
        if not _popup_confirm(
            self,
            "Confirm Loan",
            f"Lend {principal:.0f}g to {applicant['name']}\n"
            f"@ {rate * 100:.1f}%/wk  ·  {weeks} weeks\n"
            f"Weekly payment: {weekly_payment:.2f}g\n"
            f"Total return: {total_return:.2f}g\n"
            f"Expected profit: +{profit:.2f}g",
            confirm_text="Issue Loan",
        ):
            return

        g.inventory.gold -= principal
        g.citizen_loans.append(CitizenLoan(
            id=g.next_citizen_loan_id,
            borrower_name=applicant["name"],
            principal=principal,
            interest_rate=rate,
            weeks_remaining=weeks,
            weekly_payment=weekly_payment,
            creditworthiness=applicant["creditworthiness"],
        ))
        g.next_citizen_loan_id += 1
        self._applicants.pop(idx)
        if hasattr(g, "_log_event"):
            g._log_event(f"Citizen loan: {principal:.0f}g to {applicant['name']}")
        g._check_achievements()
        self.msg.ok(
            f"Loaned {principal:.0f}g to {applicant['name']} @ {rate * 100:.1f}%/wk. Expected profit: +{profit:.2f}g."
        )
        self.app.refresh()

    def _recall_loan(self) -> None:
        row = self._loan_table.selected()
        idx = row.get("loan_index") if row else None
        if not isinstance(idx, int) or not (0 <= idx < len(self.game.citizen_loans)):
            self.msg.warn("Select an active loan to recall.")
            return
        g = self.game
        loan = g.citizen_loans[idx]
        if loan.defaulted or loan.weeks_remaining <= 0:
            self.msg.warn("Loan not found or already closed.")
            return
        remainder = round(loan.weeks_remaining * loan.weekly_payment, 2)
        recall = round(remainder * 0.80, 2)
        if not _popup_confirm(
            self,
            "Confirm Recall",
            f"Recall loan to {loan.borrower_name}?\nRemaining value: {remainder:.2f}g\nYou receive: {recall:.2f}g (−20% fee)",
            confirm_text="Recall Loan",
            confirm_role="danger",
        ):
            return
        g.inventory.gold += recall
        loan.defaulted = True
        loan.weeks_remaining = 0
        if hasattr(g, "_log_event"):
            g._log_event(f"Recalled citizen loan from {loan.borrower_name}: +{recall:.0f}g")
        self.msg.ok(f"Loan recalled. +{recall:.2f}g deposited.")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# STOCK MARKET SCREEN  —  trade shares in listed companies
# ══════════════════════════════════════════════════════════════════════════════

class StockMarketScreen(Screen):
    _COLS = [
        ("sym", "Sym", 52, Qt.AlignmentFlag.AlignCenter),
        ("name", "Company", 200),
        ("sector", "Sector", 92),
        ("price", "Price", 72, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("chg", "Today%", 68, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("week7", "7d%", 68, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("base", "Base", 72, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("range", "30d Range", 122, Qt.AlignmentFlag.AlignCenter),
        ("hold", "Your Shares", 82, Qt.AlignmentFlag.AlignCenter),
    ]
    _PORT_COLS = [
        ("sym", "Sym", 56, Qt.AlignmentFlag.AlignCenter),
        ("shares", "Shares", 70, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("avg", "Avg Cost", 84, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("current", "Current", 84, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("value", "Value", 92, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("pnl", "Unrealized P/L", 110, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("pnl_pct", "P/L %", 74, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]

    def _metric_card(self, title: str, color: str) -> Tuple[QFrame, QLabel]:
        frame = QFrame(self)
        frame.setObjectName("dashPanel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(UIScale.px(10), UIScale.px(8), UIScale.px(10), UIScale.px(8))
        lay.setSpacing(UIScale.px(3))
        hdr = QLabel(title, frame)
        hdr.setFont(Fonts.tiny)
        hdr.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        lay.addWidget(hdr)
        value = QLabel("—", frame)
        value.setFont(Fonts.mixed_small_bold)
        value.setWordWrap(True)
        value.setStyleSheet(f"color:{color}; background:transparent;")
        lay.addWidget(value)
        lay.addStretch()
        return frame, value

    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        hdr = QHBoxLayout()
        hdr.addWidget(self.section_label("Stock Exchange"))
        hdr.addStretch()
        self._port_lbl = QLabel(self)
        self._port_lbl.setFont(Fonts.mono_small)
        self._port_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        hdr.addWidget(self._port_lbl)
        root.addLayout(hdr)

        metric_row = QHBoxLayout()
        self._metrics: Dict[str, QLabel] = {}
        for key, title, color in [
            ("leader", "Top Mover Today", P.green),
            ("laggard", "Weakest Today", P.red),
            ("value", "Portfolio Value", P.gold),
            ("pnl", "Open P/L", P.cream),
        ]:
            card, value = self._metric_card(title, color)
            self._metrics[key] = value
            metric_row.addWidget(card, 1)
        root.addLayout(metric_row)

        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.setChildrenCollapsible(False)

        left = QFrame(split)
        left.setObjectName("dashPanel")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(UIScale.px(10), UIScale.px(10), UIScale.px(10), UIScale.px(10))
        left_lay.setSpacing(UIScale.px(8))
        left_title = QLabel("Exchange Board", left)
        left_title.setFont(Fonts.mixed_bold)
        left_title.setStyleSheet(f"color:{P.amber}; background:transparent;")
        left_lay.addWidget(left_title)

        self._table = DataTable(left, self._COLS, row_height=26, stretch_last=False)
        self._table.row_selected.connect(self._on_select_market)
        self._table.row_double_clicked.connect(self._on_double)
        left_lay.addWidget(self._table, 1)

        note = QLabel("Green = price rose today  ·  Red = price fell  ·  Gold = you hold shares", left)
        note.setFont(Fonts.mono_small)
        note.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        left_lay.addWidget(note)

        act = QHBoxLayout()
        for text, handler, role in [
            (f"{Sym.YES}  Buy Shares", self._buy, "primary"),
            (f"{Sym.NO}  Sell Shares", self._sell, "danger"),
            (f"{Sym.SYNC}  Refresh", self.refresh, "secondary"),
        ]:
            btn = self.action_button(text, handler, role=role)
            btn.setFixedHeight(UIScale.px(30))
            act.addWidget(btn)
        act.addStretch()
        left_lay.addLayout(act)

        right = QFrame(split)
        right.setObjectName("dashPanel")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(UIScale.px(12), UIScale.px(12), UIScale.px(12), UIScale.px(12))
        right_lay.setSpacing(UIScale.px(8))
        self._detail_name = QLabel("Select a company", right)
        self._detail_name.setFont(Fonts.title)
        self._detail_name.setStyleSheet(f"color:{P.gold}; background:transparent;")
        right_lay.addWidget(self._detail_name)
        self._detail_stats = QLabel("", right)
        self._detail_stats.setFont(Fonts.mono_small)
        self._detail_stats.setWordWrap(True)
        self._detail_stats.setStyleSheet(f"color:{P.cream}; background:transparent;")
        right_lay.addWidget(self._detail_stats)
        self._detail_chart = _LineChart(right)
        right_lay.addWidget(self._detail_chart, 1)
        self._detail_holding = QLabel("", right)
        self._detail_holding.setFont(Fonts.mono_small)
        self._detail_holding.setWordWrap(True)
        self._detail_holding.setStyleSheet(f"color:{P.gold}; background:transparent;")
        right_lay.addWidget(self._detail_holding)
        self._detail_notes = QLabel("", right)
        self._detail_notes.setFont(Fonts.mixed_small)
        self._detail_notes.setWordWrap(True)
        self._detail_notes.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        right_lay.addWidget(self._detail_notes)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        portfolio = QFrame(self)
        portfolio.setObjectName("dashPanel")
        port_lay = QVBoxLayout(portfolio)
        port_lay.setContentsMargins(UIScale.px(10), UIScale.px(10), UIScale.px(10), UIScale.px(10))
        port_lay.setSpacing(UIScale.px(8))
        port_title = QLabel("My Shares", portfolio)
        port_title.setFont(Fonts.mixed_bold)
        port_title.setStyleSheet(f"color:{P.amber}; background:transparent;")
        port_lay.addWidget(port_title)
        self._hold_table = DataTable(portfolio, self._PORT_COLS, row_height=26, stretch_last=False)
        self._hold_table.row_selected.connect(self._on_select_holding)
        port_lay.addWidget(self._hold_table)
        self._hold_summary = QLabel("", portfolio)
        self._hold_summary.setFont(Fonts.mono_small)
        self._hold_summary.setWordWrap(True)
        self._hold_summary.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        port_lay.addWidget(self._hold_summary)
        root.addWidget(portfolio)

        foot = QHBoxLayout()
        foot.addWidget(self.back_button())
        foot.addStretch()
        root.addLayout(foot)

        self._detail_symbol: Optional[str] = None

    def refresh(self) -> None:
        g = self.game
        if LicenseType.FUND_MGR not in g.licenses:
            self._port_lbl.setText("Fund Manager License required")
            self._port_lbl.setStyleSheet(f"color:{P.red}; background:transparent;")
            self._table.load([])
            self._hold_table.load([])
            self._detail_name.setText("Fund Manager License required")
            self._detail_stats.setText("")
            self._detail_holding.setText("")
            self._detail_notes.setText("")
            self._detail_chart.set_data([])
            return

        portfolio = g._portfolio_value()
        self._port_lbl.setText(f"Portfolio: {portfolio:,.0f}g  ·  Wallet: {g.inventory.gold:,.0f}g")
        self._port_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")

        rows: List[Dict[str, Any]] = []
        movers: List[Tuple[str, float]] = []
        for sym, stock in g.stock_market.stocks.items():
            price = stock["price"]
            hist = list(stock["history"])
            prev = hist[-2] if len(hist) >= 2 else price
            chg = (price - prev) / max(prev, 0.01) * 100
            w7 = hist[-7:] if len(hist) >= 7 else hist
            week_change = ((w7[-1] - w7[0]) / max(w7[0], 0.01) * 100) if len(w7) > 1 else 0.0
            hi = max(hist) if hist else price
            lo = min(hist) if hist else price
            holding = g.stock_holdings.get(sym)
            if holding:
                holding_text = str(holding.shares)
                tag = "gold"
            else:
                holding_text = "—"
                tag = "green" if chg > 0 else ("red" if chg < 0 else "dim")
            rows.append({
                "sym": sym,
                "name": stock["name"],
                "sector": stock["sector"],
                "price": f"{price:.2f}g",
                "chg": f"{'+' if chg >= 0 else ''}{chg:.2f}%",
                "week7": f"{'+' if week_change >= 0 else ''}{week_change:.1f}%",
                "base": f"{stock['base_price']:.2f}g",
                "range": f"{lo:.1f}–{hi:.1f}g",
                "hold": holding_text,
                "symbol": sym,
                "_tag": tag,
            })
            movers.append((sym, chg))
        self._table.load(rows)

        port_rows: List[Dict[str, Any]] = []
        open_pnl = 0.0
        cost_basis = 0.0
        for sym, hold in sorted(g.stock_holdings.items(), key=lambda item: -(item[1].shares * g.stock_market.stocks.get(item[0], {}).get('price', 0.0))):
            stock = g.stock_market.stocks.get(sym)
            if not stock:
                continue
            current = float(stock["price"])
            value = round(hold.shares * current, 2)
            pnl = round(value - hold.shares * hold.avg_cost, 2)
            pnl_pct = (pnl / max(hold.shares * hold.avg_cost, 0.01)) * 100
            open_pnl += pnl
            cost_basis += hold.shares * hold.avg_cost
            port_rows.append({
                "sym": sym,
                "shares": str(hold.shares),
                "avg": f"{hold.avg_cost:.2f}g",
                "current": f"{current:.2f}g",
                "value": f"{value:.0f}g",
                "pnl": f"{'+' if pnl >= 0 else ''}{pnl:.0f}g",
                "pnl_pct": f"{'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}%",
                "symbol": sym,
                "_tag": "green" if pnl >= 0 else "red",
            })
        self._hold_table.load(port_rows)
        self._hold_summary.setText(
            f"Holdings: {len(port_rows)}  ·  Cost basis: {cost_basis:,.0f}g  ·  Open P/L: {'+' if open_pnl >= 0 else ''}{open_pnl:,.0f}g"
            if port_rows else
            "No shares held yet. Buy into a company to start tracking your positions here."
        )

        if movers:
            best_sym, best_chg = max(movers, key=lambda item: item[1])
            worst_sym, worst_chg = min(movers, key=lambda item: item[1])
            self._metrics["leader"].setText(f"{best_sym}  {best_chg:+.2f}%")
            self._metrics["laggard"].setText(f"{worst_sym}  {worst_chg:+.2f}%")
        else:
            self._metrics["leader"].setText("—")
            self._metrics["laggard"].setText("—")
        self._metrics["value"].setText(f"{portfolio:,.0f}g")
        self._metrics["pnl"].setText(f"{'+' if open_pnl >= 0 else ''}{open_pnl:,.0f}g")

        target_symbol = self._detail_symbol
        valid_symbols = {row["symbol"] for row in rows}
        if target_symbol not in valid_symbols:
            target_symbol = rows[0]["symbol"] if rows else None
        self._show_symbol(target_symbol)

    def _show_symbol(self, sym: Optional[str]) -> None:
        self._detail_symbol = sym
        if not sym or sym not in self.game.stock_market.stocks:
            self._detail_name.setText("Select a company")
            self._detail_stats.setText("")
            self._detail_holding.setText("")
            self._detail_notes.setText("")
            self._detail_chart.set_data([])
            return
        stock = self.game.stock_market.stocks[sym]
        hist = list(stock.get("history", []))
        price = float(stock["price"])
        hi = max(hist) if hist else price
        lo = min(hist) if hist else price
        avg = sum(hist) / len(hist) if hist else price
        holding = self.game.stock_holdings.get(sym)
        points = [(index + 1, value) for index, value in enumerate(hist or [price])]
        series: List[Tuple[str, str, List[Tuple[float, float]]]] = [(sym, P.gold, points)]
        if holding:
            series.append(("Avg Cost", P.cream, [(index + 1, holding.avg_cost) for index, _ in enumerate(hist or [price])]))
        self._detail_chart.set_data(series)
        self._detail_name.setText(f"{stock['name']}  ({sym})")
        self._detail_stats.setText(
            f"Sector: {stock['sector']}  ·  Price: {price:.2f}g  ·  Base: {stock['base_price']:.2f}g  ·  Volatility: {stock['volatility'] * 100:.1f}%/day\n"
            f"30d High: {hi:.2f}g  ·  30d Low: {lo:.2f}g  ·  30d Avg: {avg:.2f}g  ·  Listed shares: {stock['shares']:,}"
        )
        linked_items = ", ".join(ALL_ITEMS[item_key].name if item_key in ALL_ITEMS else item_key for item_key in stock.get("linked_items", [])) or "None"
        event_text = "  ·  ".join(f"{event}:{impact:+.0%}" for event, impact in stock.get("linked_events", {}).items()) or "No direct event links"
        if holding:
            value = holding.shares * price
            pnl = value - holding.shares * holding.avg_cost
            self._detail_holding.setText(
                f"Your holding: {holding.shares} shares  ·  Avg cost: {holding.avg_cost:.2f}g  ·  Current value: {value:,.0f}g  ·  Unrealized P/L: {'+' if pnl >= 0 else ''}{pnl:,.0f}g"
            )
        else:
            self._detail_holding.setText("You do not currently hold this company.")
        self._detail_notes.setText(f"Linked goods: {linked_items}\nEvent impact map: {event_text}")

    def _on_select_market(self, row: Dict[str, Any]) -> None:
        self._show_symbol(row.get("symbol") if row else None)

    def _on_select_holding(self, row: Dict[str, Any]) -> None:
        self._show_symbol(row.get("symbol") if row else None)

    def _on_double(self, _row: Dict[str, Any]) -> None:
        if self.game.settings.double_click_action:
            self._buy()

    def _buy(self) -> None:
        g = self.game
        if LicenseType.FUND_MGR not in g.licenses:
            self.msg.err("Fund Manager License required.")
            return
        row = self._table.selected()
        sym = row.get("symbol") if row else None
        if not isinstance(sym, str) or sym not in g.stock_market.stocks:
            self.msg.warn("Select a company to buy shares in.")
            return
        stock = g.stock_market.stocks[sym]
        price = float(stock["price"])
        max_shares = int(g.inventory.gold / price) if price > 0 else 0
        if max_shares <= 0:
            self.msg.err(f"Not enough gold. Need at least {price:.2f}g.")
            return
        qty, ok = _popup_get_int(
            self,
            "Buy Shares",
            f"Buy shares of {stock['name']} ({sym})\nCurrent price: {price:.2f}g/share\nMax affordable: {max_shares}",
            value=1,
            minimum=1,
            maximum=max_shares,
            step=1,
            confirm_text="Buy Shares",
        )
        if not ok:
            return
        cost = round(qty * price, 2)
        if not _popup_confirm(
            self,
            "Confirm Purchase",
            f"Buy {qty}× {sym} @ {price:.2f}g = {cost:.2f}g total?",
            confirm_text="Confirm Buy",
        ):
            return
        g.inventory.gold -= cost
        if sym in g.stock_holdings:
            hold = g.stock_holdings[sym]
            new_avg = (hold.shares * hold.avg_cost + cost) / (hold.shares + qty)
            hold.shares += qty
            hold.avg_cost = round(new_avg, 2)
        else:
            g.stock_holdings[sym] = StockHolding(sym, qty, round(price, 2))
        if hasattr(g, "_log_event"):
            g._log_event(f"Bought {qty}× {sym} @ {price:.2f}g")
        g._check_achievements()
        self.msg.ok(f"Bought {qty}× {sym} @ {price:.2f}g (−{cost:.2f}g).")
        self.app.refresh()

    def _sell(self) -> None:
        g = self.game
        if LicenseType.FUND_MGR not in g.licenses:
            self.msg.err("Fund Manager License required.")
            return
        row = self._table.selected()
        sym = row.get("symbol") if row else None
        if not isinstance(sym, str):
            self.msg.warn("Select a company to sell shares in.")
            return
        hold = g.stock_holdings.get(sym)
        if hold is None or hold.shares <= 0:
            self.msg.err(f"No shares held in {sym}.")
            return
        stock = g.stock_market.stocks.get(sym)
        if stock is None:
            self.msg.err("Unknown symbol.")
            return
        price = float(stock["price"])
        qty, ok = _popup_get_int(
            self,
            "Sell Shares",
            f"Sell shares of {stock['name']} ({sym})\nYou hold: {hold.shares} shares\nAvg cost: {hold.avg_cost:.2f}g\nCurrent price: {price:.2f}g",
            value=hold.shares,
            minimum=1,
            maximum=hold.shares,
            step=1,
            confirm_text="Sell Shares",
        )
        if not ok:
            return
        proceeds = round(qty * price, 2)
        profit = round((price - hold.avg_cost) * qty, 2)
        if not _popup_confirm(
            self,
            "Confirm Sale",
            f"Sell {qty}× {sym} @ {price:.2f}g = {proceeds:.2f}g\nP/L: {'+' if profit >= 0 else ''}{profit:.2f}g",
            confirm_text="Confirm Sale",
            confirm_role="danger",
        ):
            return
        g.inventory.gold += proceeds
        g.total_profit += profit
        hold.shares -= qty
        if hold.shares <= 0:
            del g.stock_holdings[sym]
        if hasattr(g, "_log_event"):
            g._log_event(f"Sold {qty}× {sym} @ {price:.2f}g  P/L:{profit:+.0f}g")
        if profit > 0:
            g._track_stat("stock_profit", profit)
        g._check_achievements()
        self.msg.ok(f"Sold {qty}× {sym} @ {price:.2f}g  +{proceeds:.2f}g  (P/L: {'+' if profit >= 0 else ''}{profit:.2f}g)")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# FUND MANAGEMENT SCREEN  —  accept client capital and manage obligations
# ══════════════════════════════════════════════════════════════════════════════

class FundManagementScreen(Screen):
    _CLIENT_COLS = [
        ("name", "Client", 180),
        ("capital", "Capital", 82, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("rate", "Promised%", 82, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("fee", "Fee/mo", 70, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("days", "Days Left", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("fees_pd", "Fees Paid", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("owed", "Owed", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]
    _POOL_COLS = [
        ("name", "Prospective Client", 195),
        ("cap", "Capital", 82, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("dur", "Duration", 70, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("rate", "Promised%", 82, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("fee", "Mgmt Fee/mo", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]

    def build(self) -> None:
        self._pool: List[Dict[str, Any]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        hdr = QHBoxLayout()
        hdr.addWidget(self.section_label("Fund Management"))
        hdr.addStretch()
        self._aum_lbl = QLabel(self)
        self._aum_lbl.setFont(Fonts.mono_small)
        self._aum_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        hdr.addWidget(self._aum_lbl)
        root.addLayout(hdr)

        tabs = QTabWidget(self)
        tabs.setFont(Fonts.mixed_small)
        root.addWidget(tabs, 1)

        active_tab = QWidget(self)
        active_lay = QVBoxLayout(active_tab)
        active_lay.setContentsMargins(0, 0, 0, 0)
        active_lay.setSpacing(UIScale.px(8))
        self._client_table = DataTable(active_tab, self._CLIENT_COLS, row_height=26)
        active_lay.addWidget(self._client_table, 1)
        early_btn = self.action_button(f"{Sym.NO}  Return Funds Early", self._early_return, role="danger")
        early_btn.setFixedHeight(UIScale.px(30))
        active_lay.addWidget(early_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        tabs.addTab(active_tab, f"{Sym.PROFILE}  Active Clients")

        pool_tab = QWidget(self)
        pool_lay = QVBoxLayout(pool_tab)
        pool_lay.setContentsMargins(0, 0, 0, 0)
        pool_lay.setSpacing(UIScale.px(8))
        pool_row = QHBoxLayout()
        refresh_btn = self.action_button(f"{Sym.SYNC}  New Pool", self._refresh_pool, role="secondary")
        refresh_btn.setFixedHeight(UIScale.px(28))
        pool_row.addWidget(refresh_btn)
        pool_hint = QLabel("You receive client capital now, then owe principal plus promised return at maturity.", pool_tab)
        pool_hint.setFont(Fonts.mono_small)
        pool_hint.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        pool_row.addWidget(pool_hint)
        pool_row.addStretch()
        pool_lay.addLayout(pool_row)
        self._pool_table = DataTable(pool_tab, self._POOL_COLS, row_height=26)
        pool_lay.addWidget(self._pool_table, 1)
        accept_btn = self.action_button(f"{Sym.YES}  Accept Selected Client", self._accept_client)
        accept_btn.setFixedHeight(UIScale.px(30))
        pool_lay.addWidget(accept_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        tabs.addTab(pool_tab, f"{Sym.YES}  Accept New Client")

        foot = QHBoxLayout()
        foot.addWidget(self.back_button())
        foot.addStretch()
        root.addLayout(foot)

    def refresh(self) -> None:
        g = self.game
        locked = LicenseType.FUND_MGR not in g.licenses
        low_rep = g.reputation < 55
        if locked or low_rep:
            self._aum_lbl.setText("Fund Manager License required" if locked else f"Reputation {g.reputation}/100 — need 55+")
            self._aum_lbl.setStyleSheet(f"color:{P.red}; background:transparent;")
            self._client_table.load([])
            self._pool_table.load([])
            return

        active_clients = [fc for fc in g.fund_clients if not fc.withdrawn]
        aum = sum(fc.capital for fc in active_clients)
        self._aum_lbl.setText(f"Clients: {len(active_clients)}  ·  AUM: {aum:,.0f}g  ·  Wallet: {g.inventory.gold:,.0f}g")
        self._aum_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")

        today = g._absolute_day()
        client_rows: List[Dict[str, Any]] = []
        for idx, client in enumerate(active_clients):
            days_left = client.maturity_day - today
            owed = round(client.capital * (1 + client.promised_rate), 2)
            client_rows.append({
                "name": client.name,
                "capital": f"{client.capital:.0f}g",
                "rate": f"{client.promised_rate * 100:.1f}%",
                "fee": f"{client.fee_rate * 100:.1f}%",
                "days": f"{days_left}d",
                "fees_pd": f"{client.fees_collected:.0f}g",
                "owed": f"{owed:.0f}g",
                "client_id": client.id,
                "_tag": "red" if days_left <= 5 else ("yellow" if days_left <= 15 else "green"),
            })
        self._client_table.load(client_rows)

        if not self._pool:
            self._pool = g._gen_fund_client_pool(4)
        self._load_pool_rows()

    def _load_pool_rows(self) -> None:
        rows: List[Dict[str, Any]] = []
        for idx, prospect in enumerate(self._pool):
            rows.append({
                "name": prospect["name"],
                "cap": f"{prospect['capital']:.0f}g",
                "dur": f"{prospect['duration']}d",
                "rate": f"{prospect['promised_rate'] * 100:.1f}%",
                "fee": f"{prospect['fee_rate'] * 100:.1f}%",
                "pool_index": idx,
            })
        self._pool_table.load(rows)

    def _refresh_pool(self) -> None:
        self._pool = self.game._gen_fund_client_pool(4)
        self._load_pool_rows()

    def _accept_client(self) -> None:
        g = self.game
        if LicenseType.FUND_MGR not in g.licenses:
            self.msg.err("Fund Manager License required.")
            return
        if g.reputation < 55:
            self.msg.err(f"Reputation {g.reputation}/100 — need 55+.")
            return
        row = self._pool_table.selected()
        idx = row.get("pool_index") if row else None
        if not isinstance(idx, int) or not (0 <= idx < len(self._pool)):
            self.msg.warn("Select a prospective client.")
            return
        prospect = self._pool[idx]
        owed = round(prospect["capital"] * (1 + prospect["promised_rate"]), 2)
        if not _popup_confirm(
            self,
            "Accept Client",
            f"Accept {prospect['name']}\nCapital: {prospect['capital']:.0f}g\nDuration: {prospect['duration']}d\n\n"
            f"You receive {prospect['capital']:.0f}g now.\n"
            f"At maturity you must pay back: {owed:.0f}g\n"
            f"Management fee: {prospect['fee_rate'] * 100:.1f}%/mo",
            confirm_text="Accept Client",
        ):
            return
        if not _maybe_sign(self, "fund_client", detail=prospect["name"]):
            return
        today = g._absolute_day()
        g.inventory.gold += prospect["capital"]
        g.fund_clients.append(FundClient(
            id=g.next_fund_client_id,
            name=prospect["name"],
            capital=prospect["capital"],
            promised_rate=prospect["promised_rate"],
            start_day=today,
            duration_days=prospect["duration"],
            maturity_day=today + prospect["duration"],
            fee_rate=prospect["fee_rate"],
        ))
        g.next_fund_client_id += 1
        self._pool.pop(idx)
        if hasattr(g, "_log_event"):
            g._log_event(f"Fund client {prospect['name']}: {prospect['capital']:.0f}g / {prospect['duration']}d")
        g._check_achievements()
        self.msg.ok(f"Accepted {prospect['name']}. +{prospect['capital']:.0f}g received. Repay {owed:.0f}g in {prospect['duration']}d.")
        self.app.refresh()

    def _early_return(self) -> None:
        row = self._client_table.selected()
        client_id = row.get("client_id") if row else None
        if not isinstance(client_id, int):
            self.msg.warn("Select a client to return funds to.")
            return
        g = self.game
        client = next((fc for fc in g.fund_clients if fc.id == client_id and not fc.withdrawn), None)
        if client is None:
            self.msg.warn("Client not found or already closed.")
            return
        owed = round(client.capital * (1 + client.promised_rate) * 0.85, 2)
        if g.inventory.gold < owed:
            self.msg.err(f"Need {owed:.0f}g. Have {g.inventory.gold:.0f}g.")
            return
        if not _popup_confirm(
            self,
            "Confirm Early Return",
            f"Return funds early to {client.name}?\nYou pay: {owed:.0f}g\nReputation −3 for early termination.",
            confirm_text="Return Funds",
            confirm_role="danger",
        ):
            return
        g.inventory.gold -= owed
        client.withdrawn = True
        g.reputation = max(0, g.reputation - 3)
        if hasattr(g, "_log_event"):
            g._log_event(f"Early fund return to {client.name}: −{owed:.0f}g")
        self.msg.ok(f"Funds returned to {client.name}. −{owed:.0f}g. Rep −3.")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# INFLUENCE SCREEN  —  reputation management and market pressure operations
# ══════════════════════════════════════════════════════════════════════════════

class InfluenceScreen(Screen):
    _MKT_COLS = [
        ("item", "Item", 170),
        ("price", "Price", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("pressure", "Pressure", 82, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("trend", "Trend", 78, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("rarity", "Rarity", 90),
        ("camp_cost", "Camp Cost", 86, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]

    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        root.addWidget(self.section_label("Influence & Reputation"))

        tabs = QTabWidget(self)
        tabs.setFont(Fonts.mixed_small)
        root.addWidget(tabs, 1)

        overview = QWidget(self)
        ov_lay = QVBoxLayout(overview)
        ov_lay.setContentsMargins(0, 0, 0, 0)
        self._overview_txt = QTextEdit(overview)
        self._overview_txt.setReadOnly(True)
        self._overview_txt.setFont(Fonts.mono)
        self._overview_txt.setStyleSheet(
            f"QTextEdit{{background:{P.bg}; color:{P.fg}; border:1px solid {P.border};"
            f"border-radius:{UIScale.px(4)}px; padding:{UIScale.px(8)}px;}}"
        )
        ov_lay.addWidget(self._overview_txt)
        tabs.addTab(overview, "Overview")

        social = QWidget(self)
        social_lay = QVBoxLayout(social)
        social_lay.setContentsMargins(0, 0, 0, 0)
        social_lay.setSpacing(UIScale.px(8))
        social_info = QLabel(
            "Donate to charity to gain reputation. Rough conversion: 15g = +1 rep, with diminishing returns above 80 reputation.",
            social,
        )
        social_info.setFont(Fonts.mono_small)
        social_info.setWordWrap(True)
        social_info.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        social_lay.addWidget(social_info)
        donate_row = QHBoxLayout()
        for amount in (20, 50, 120, 300):
            btn = self.action_button(f"Donate {amount}g", lambda checked=False, amt=amount: self._do_donate(amt), role="secondary")
            btn.setFixedHeight(UIScale.px(30))
            donate_row.addWidget(btn)
        custom_btn = self.action_button("Donate Custom", lambda: self._do_donate(None))
        custom_btn.setFixedHeight(UIScale.px(30))
        donate_row.addWidget(custom_btn)
        donate_row.addStretch()
        social_lay.addLayout(donate_row)
        tabs.addTab(social, "Social Actions")

        market_tab = QWidget(self)
        market_lay = QVBoxLayout(market_tab)
        market_lay.setContentsMargins(0, 0, 0, 0)
        market_lay.setSpacing(UIScale.px(8))
        market_info = QLabel(
            "Campaign increases demand pressure for a market item. Slander suppresses demand, but costs reputation and carries a cooldown.",
            market_tab,
        )
        market_info.setFont(Fonts.mono_small)
        market_info.setWordWrap(True)
        market_info.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        market_lay.addWidget(market_info)
        self._mkt_table = DataTable(market_tab, self._MKT_COLS, row_height=26)
        market_lay.addWidget(self._mkt_table, 1)
        market_act = QHBoxLayout()
        camp_btn = self.action_button("Campaign Up", self._do_market_campaign)
        camp_btn.setFixedHeight(UIScale.px(30))
        slander_btn = self.action_button("Slander Down", self._do_slander, role="danger")
        slander_btn.setFixedHeight(UIScale.px(30))
        market_act.addWidget(camp_btn)
        market_act.addWidget(slander_btn)
        market_act.addStretch()
        market_lay.addLayout(market_act)
        tabs.addTab(market_tab, "Market Campaigns")

        foot = QHBoxLayout()
        foot.addWidget(self.back_button())
        foot.addStretch()
        root.addLayout(foot)

    def _campaign_cost(self, item: Item) -> int:
        return {"common": 60, "uncommon": 100, "rare": 150, "legendary": 200}.get(getattr(item, "rarity", "common"), 80)

    def refresh(self) -> None:
        g = self.game
        rep_name, _rep_color = rep_label(g.reputation)
        donate_gain_20 = max(1, int(20 / 15) - max(0, (g.reputation - 80) // 10))
        donate_gain_50 = max(1, int(50 / 15) - max(0, (g.reputation - 80) // 10))
        donate_gain_120 = max(1, int(120 / 15) - max(0, (g.reputation - 80) // 10))
        text = (
            f"Reputation:  {g.reputation:>4}   ({rep_name})\n"
            f"Heat:        {g.heat:>4} / 100\n"
            f"Licenses:    {len(g.licenses)} / {len(LicenseType)}\n\n"
            f"Donate 20g  -> +{donate_gain_20} rep\n"
            f"Donate 50g  -> +{donate_gain_50} rep\n"
            f"Donate 120g -> +{donate_gain_120} rep\n"
            f"Diminishing returns apply above 80 reputation."
        )
        self._overview_txt.setPlainText(text)

        market = g.markets[g.current_area]
        rows: List[Dict[str, Any]] = []
        for item_key in market.item_keys:
            item = ALL_ITEMS.get(item_key)
            if item is None:
                continue
            price = market.get_price(item_key, g.season, noise=False)
            pressure = market.pressure.get(item_key, 1.0)
            natural = market.natural_pressure.get(item_key, 1.0)
            hist = list(market.history.get(item_key, []))
            if len(hist) >= 2:
                delta = (hist[-1].price - hist[-2].price) / max(hist[-2].price, 0.01) * 100
                trend = f"{'▲' if delta >= 0 else '▼'}{abs(delta):.1f}%"
                trend_tag = "green" if delta > 0 else ("red" if delta < 0 else "dim")
            else:
                trend = "─"
                trend_tag = "dim"
            pressure_ratio = pressure / max(natural, 0.01)
            tag = "red" if pressure_ratio > 1.2 else ("green" if pressure_ratio < 0.85 else trend_tag)
            rows.append({
                "item": item.name,
                "price": f"{price:.2f}g",
                "pressure": f"{pressure:.3f}",
                "trend": trend,
                "rarity": getattr(item, "rarity", "common").title(),
                "camp_cost": f"{self._campaign_cost(item)}g",
                "item_key": item_key,
                "_tag": tag,
            })
        self._mkt_table.load(rows)

    def _do_donate(self, preset_amount: Optional[int]) -> None:
        g = self.game
        if preset_amount is None:
            raw = _popup_get_text(
                self,
                "Donate to Charity",
                f"Wallet: {g.inventory.gold:.0f}g\nEnter donation amount:",
                placeholder="50",
                confirm_text="Donate",
            )
            if raw is None:
                return
            try:
                amount = float(raw)
            except ValueError:
                self.msg.err("Invalid amount.")
                return
        else:
            amount = float(preset_amount)
        if amount < 15:
            self.msg.err("Minimum donation is 15g.")
            return
        if amount > g.inventory.gold:
            self.msg.err(f"Not enough gold. Have {g.inventory.gold:.0f}g.")
            return
        rep_gain = max(1, int(amount / 15) - max(0, (g.reputation - 80) // 10))
        rep_gain = min(rep_gain, 100 - g.reputation)
        if rep_gain <= 0:
            self.msg.warn("Your reputation is already at maximum.")
            return
        g.inventory.gold -= amount
        g.reputation = min(100, g.reputation + rep_gain)
        g._check_achievements()
        self.msg.ok(f"Donated {amount:.0f}g. Rep +{rep_gain} -> {g.reputation}.")
        self.app.refresh()

    def _do_market_campaign(self) -> None:
        g = self.game
        row = self._mkt_table.selected()
        item_key = row.get("item_key") if row else None
        if not isinstance(item_key, str):
            self.msg.warn("Select an item from the market campaign table first.")
            return
        market = g.markets[g.current_area]
        if item_key not in market.item_keys:
            self.msg.err("That item is not traded in this area.")
            return
        item = ALL_ITEMS[item_key]
        cost = self._campaign_cost(item)
        if g.inventory.gold < cost:
            self.msg.err(f"Need {cost}g for a campaign on {item.name}.")
            return
        cooldown_key = f"{g.current_area.name}:{item_key}:campaign"
        expires = g.influence_cooldowns.get(cooldown_key, 0)
        if expires > g._absolute_day():
            days_left = expires - g._absolute_day()
            self.msg.err(f"Campaign already on cooldown for {item.name}. {days_left} day(s) remaining.")
            return
        if not _popup_confirm(
            self,
            "Market Campaign",
            f"Run a demand campaign for {item.name}?\nCost: {cost}g\nPressure +25%\nHeat +5",
            confirm_text="Launch Campaign",
        ):
            return
        old_pressure = market.pressure.get(item_key, 1.0)
        market.pressure[item_key] = min(getattr(market, "MAX_PRESSURE", 2.0), old_pressure * 1.25)
        g.inventory.gold -= cost
        g.heat = min(100, g.heat + 5)
        g.influence_cooldowns[cooldown_key] = g._absolute_day() + 30
        g._track_stat("campaigns_run")
        g._check_achievements()
        self.msg.ok(f"Campaign launched for {item.name}. Pressure {old_pressure:.3f} -> {market.pressure[item_key]:.3f}.")
        self.app.refresh()

    def _do_slander(self) -> None:
        import math

        g = self.game
        row = self._mkt_table.selected()
        item_key = row.get("item_key") if row else None
        if not isinstance(item_key, str):
            self.msg.warn("Select an item from the market campaign table first.")
            return
        market = g.markets[g.current_area]
        if item_key not in market.item_keys:
            self.msg.err("That item is not traded in this area.")
            return
        item = ALL_ITEMS[item_key]
        rep_cost = max(5, min(10, int(math.ceil((100 - g.reputation) * 0.1)) + 5))
        if g.reputation - rep_cost < 0:
            self.msg.err(f"Reputation too low. Slander costs {rep_cost} rep.")
            return
        cooldown_key = f"{g.current_area.name}:{item_key}:slander"
        expires = g.influence_cooldowns.get(cooldown_key, 0)
        if expires > g._absolute_day():
            days_left = expires - g._absolute_day()
            self.msg.err(f"Slander already on cooldown for {item.name}. {days_left} day(s) remaining.")
            return
        if not _popup_confirm(
            self,
            "Slander",
            f"Spread slander about {item.name}?\nPressure -20%\nCost: -{rep_cost} reputation",
            confirm_text="Spread Slander",
            confirm_role="danger",
        ):
            return
        old_pressure = market.pressure.get(item_key, 1.0)
        market.pressure[item_key] = max(getattr(market, "MIN_PRESSURE", 0.3), old_pressure * 0.80)
        g.reputation = max(0, g.reputation - rep_cost)
        g.influence_cooldowns[cooldown_key] = g._absolute_day() + 20
        g._track_stat("slanders_run")
        g._check_achievements()
        self.msg.ok(f"Slander spread on {item.name}. Pressure {old_pressure:.3f} -> {market.pressure[item_key]:.3f}. Rep -{rep_cost}.")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# REAL ESTATE SCREEN  —  buy, build, lease, repair, and flip properties
# ══════════════════════════════════════════════════════════════════════════════

class RealEstateScreen(Screen):
    _PORT_COLS = [
        ("name", "Property", 230),
        ("area", "Area", 110),
        ("type", "Type", 105),
        ("cond", "Condition", 110),
        ("value", "Value", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("lease", "Lease/day", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("status", "Status", 160),
        ("days", "Days Owned", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]
    _LIST_COLS = [
        ("name", "Property", 210),
        ("type", "Type", 95),
        ("cond", "Condition", 100),
        ("asking", "Asking", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("repair", "Est. Repair", 95, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("lease", "Lease/day", 88, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("haggle", "Negotiable", 84),
        ("flavour", "Notes", 220),
    ]
    _LAND_COLS = [
        ("area", "Area", 120),
        ("size", "Size", 80),
        ("cost", "Cost", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("status", "Status", 180),
        ("progress", "Progress", 100),
    ]

    def build(self) -> None:
        self._listings_data: List[Dict[str, Any]] = []
        self._listings_area_cache = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        hdr = QHBoxLayout()
        hdr.addWidget(self.section_label("Real Estate & Land Development"))
        hdr.addStretch()
        self._stats_lbl = QLabel(self)
        self._stats_lbl.setFont(Fonts.mono_small)
        self._stats_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        hdr.addWidget(self._stats_lbl)
        root.addLayout(hdr)

        self._locked_lbl = QLabel(
            "Real Estate Charter required. Purchase the license to unlock this feature.",
            self,
        )
        self._locked_lbl.setFont(Fonts.mixed_bold)
        self._locked_lbl.setWordWrap(True)
        self._locked_lbl.setStyleSheet(
            f"color:{P.amber}; background:{P.bg_panel}; border:1px solid {P.border};"
            f"padding:{UIScale.px(10)}px; border-radius:{UIScale.px(4)}px;"
        )
        root.addWidget(self._locked_lbl)

        self._tabs = QTabWidget(self)
        self._tabs.setFont(Fonts.mixed_small)
        root.addWidget(self._tabs, 1)

        portfolio = QWidget(self)
        port_lay = QVBoxLayout(portfolio)
        port_lay.setContentsMargins(0, 0, 0, 0)
        port_lay.setSpacing(UIScale.px(8))
        self._port_table = DataTable(portfolio, self._PORT_COLS, row_height=26)
        port_lay.addWidget(self._port_table, 1)
        self._port_summary = QLabel(portfolio)
        self._port_summary.setFont(Fonts.mono_small)
        self._port_summary.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        self._port_summary.setWordWrap(True)
        port_lay.addWidget(self._port_summary)
        port_act = QHBoxLayout()
        for text, handler, role in [
            ("Toggle Lease", self._do_toggle_lease, "secondary"),
            ("Repair Property", self._do_repair, "primary"),
            ("Add Upgrade", self._do_upgrade, "secondary"),
            ("Sell Property", self._do_sell_property, "danger"),
        ]:
            btn = self.action_button(text, handler, role=role)
            btn.setFixedHeight(UIScale.px(30))
            port_act.addWidget(btn)
        port_act.addStretch()
        port_lay.addLayout(port_act)
        self._tabs.addTab(portfolio, "My Portfolio")

        listings = QWidget(self)
        list_lay = QVBoxLayout(listings)
        list_lay.setContentsMargins(0, 0, 0, 0)
        list_lay.setSpacing(UIScale.px(8))
        list_ctrl = QHBoxLayout()
        area_lbl = QLabel("Area", listings)
        area_lbl.setFont(Fonts.mixed_small)
        area_lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        list_ctrl.addWidget(area_lbl)
        self._list_area_combo = QComboBox(listings)
        self._list_area_combo.setFont(Fonts.mixed_small)
        for area in Area:
            self._list_area_combo.addItem(area.value, area)
        self._list_area_combo.currentIndexChanged.connect(lambda _idx: self._refresh_listings(force=True))
        list_ctrl.addWidget(self._list_area_combo)
        refresh_btn = self.action_button("Refresh Listings", self._do_refresh_listings, role="secondary")
        refresh_btn.setFixedHeight(UIScale.px(28))
        list_ctrl.addWidget(refresh_btn)
        list_ctrl.addStretch()
        self._list_info_lbl = QLabel(listings)
        self._list_info_lbl.setFont(Fonts.mono_small)
        self._list_info_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        list_ctrl.addWidget(self._list_info_lbl)
        list_lay.addLayout(list_ctrl)
        self._list_table = DataTable(listings, self._LIST_COLS, row_height=26)
        self._list_table.row_double_clicked.connect(self._on_dbl_buy_listing)
        list_lay.addWidget(self._list_table, 1)
        list_act = QHBoxLayout()
        buy_btn = self.action_button("Buy at Asking", lambda: self._do_buy_listing(False))
        haggle_btn = self.action_button("Haggle", lambda: self._do_buy_listing(True), role="secondary")
        buy_btn.setFixedHeight(UIScale.px(30))
        haggle_btn.setFixedHeight(UIScale.px(30))
        list_act.addWidget(buy_btn)
        list_act.addWidget(haggle_btn)
        list_act.addStretch()
        list_lay.addLayout(list_act)
        self._tabs.addTab(listings, "Browse Listings")

        land = QWidget(self)
        land_lay = QVBoxLayout(land)
        land_lay.setContentsMargins(0, 0, 0, 0)
        land_lay.setSpacing(UIScale.px(8))
        land_lay.addWidget(self.section_label("Your Land Plots", land))
        self._land_table = DataTable(land, self._LAND_COLS, row_height=26)
        land_lay.addWidget(self._land_table)
        build_row = QHBoxLayout()
        build_btn = self.action_button("Start Construction", self._do_start_build)
        build_btn.setFixedHeight(UIScale.px(30))
        build_row.addWidget(build_btn)
        build_row.addStretch()
        land_lay.addLayout(build_row)
        land_lay.addWidget(self.h_sep(land))

        buy_grid = QGridLayout()
        buy_grid.setHorizontalSpacing(UIScale.px(10))
        buy_grid.setVerticalSpacing(UIScale.px(8))
        size_lbl = QLabel("Plot Size", land)
        size_lbl.setFont(Fonts.mixed_small)
        size_lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        buy_grid.addWidget(size_lbl, 0, 0)
        self._plot_size_combo = QComboBox(land)
        self._plot_size_combo.setFont(Fonts.mixed_small)
        for size in ("small", "medium", "large"):
            self._plot_size_combo.addItem(size.title(), size)
        self._plot_size_combo.currentIndexChanged.connect(lambda _idx: self._update_plot_cost())
        buy_grid.addWidget(self._plot_size_combo, 0, 1)

        plot_area_lbl = QLabel("Area", land)
        plot_area_lbl.setFont(Fonts.mixed_small)
        plot_area_lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        buy_grid.addWidget(plot_area_lbl, 1, 0)
        self._plot_area_combo = QComboBox(land)
        self._plot_area_combo.setFont(Fonts.mixed_small)
        for area in Area:
            self._plot_area_combo.addItem(area.value, area)
        self._plot_area_combo.currentIndexChanged.connect(lambda _idx: self._update_plot_cost())
        buy_grid.addWidget(self._plot_area_combo, 1, 1)

        self._plot_cost_lbl = QLabel(land)
        self._plot_cost_lbl.setFont(Fonts.mono_small)
        self._plot_cost_lbl.setWordWrap(True)
        self._plot_cost_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        buy_grid.addWidget(self._plot_cost_lbl, 2, 0, 1, 2)

        plot_btn = self.action_button("Buy Plot", self._do_buy_plot)
        plot_btn.setFixedHeight(UIScale.px(30))
        buy_grid.addWidget(plot_btn, 3, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignLeft)
        land_lay.addLayout(buy_grid)
        land_lay.addStretch()
        self._tabs.addTab(land, "Build on Land")

        foot = QHBoxLayout()
        foot.addWidget(self.back_button())
        foot.addStretch()
        root.addLayout(foot)

    def refresh(self) -> None:
        g = self.game
        locked = LicenseType.REAL_ESTATE not in g.licenses
        self._locked_lbl.setVisible(locked)
        self._tabs.setEnabled(not locked)

        prop_count = sum(1 for prop in g.real_estate if not prop.under_construction)
        lease_count = sum(1 for prop in g.real_estate if prop.is_leased and not prop.under_construction)
        total_daily = sum(prop.daily_lease for prop in g.real_estate if prop.is_leased and not prop.under_construction)
        under_construction = sum(1 for prop in g.real_estate if prop.under_construction) + len([plot for plot in g.land_plots if plot.build_project])
        self._stats_lbl.setText(
            f"Properties: {prop_count}  ·  Leased: {lease_count}  ·  Income: {total_daily:.1f}g/day  ·  Under construction: {under_construction}"
        )

        if self._list_area_combo.currentIndex() < 0:
            self._list_area_combo.setCurrentIndex(max(0, self._list_area_combo.findText(g.current_area.value)))
        if self._plot_area_combo.currentIndex() < 0:
            self._plot_area_combo.setCurrentIndex(max(0, self._plot_area_combo.findText(g.current_area.value)))
        self._refresh_portfolio()
        self._refresh_listings()
        self._refresh_land()
        self._update_plot_cost()

    def _refresh_portfolio(self) -> None:
        g = self.game
        rows: List[Dict[str, Any]] = []
        total_value = 0.0
        total_lease = 0.0
        for prop in g.real_estate:
            cond_label_str, _desc = condition_label(prop.condition)
            if prop.under_construction:
                status = f"Building ({prop.construction_days_left}d)"
                tag = "dim"
            elif prop.is_leased:
                status = f"Leased: {(prop.tenant_name or 'Tenant')[:18]}"
                tag = "green"
            else:
                status = "Available"
                tag = "cyan"
            if not prop.under_construction:
                total_value += prop.current_value
                if prop.is_leased:
                    total_lease += prop.daily_lease
            rows.append({
                "name": prop.name,
                "area": prop.area.value,
                "type": PROPERTY_CATALOGUE.get(prop.prop_type, {}).get("name", prop.prop_type.title()),
                "cond": f"{cond_label_str} ({prop.condition:.0%})",
                "value": f"{prop.current_value:,.0f}g",
                "lease": "—" if prop.under_construction else f"{prop.daily_lease:.1f}g",
                "status": status,
                "days": str(prop.days_owned),
                "property_id": prop.id,
                "plot_id": None,
                "_tag": tag,
            })
        for plot in g.land_plots:
            if plot.build_project:
                cat = PROPERTY_CATALOGUE.get(plot.build_project, {})
                status = f"Building: {cat.get('name', plot.build_project)}"
                progress = f"{plot.build_days_left}d left"
                tag = "yellow"
            else:
                status = "Undeveloped"
                progress = "—"
                tag = "dim"
            rows.append({
                "name": f"Land Plot ({plot.size.title()})",
                "area": plot.area.value,
                "type": "Land Plot",
                "cond": "N/A",
                "value": f"{round(plot.purchase_price * 1.05):,.0f}g",
                "lease": "—",
                "status": f"{status} {progress}".strip(),
                "days": "—",
                "property_id": None,
                "plot_id": plot.id,
                "_tag": tag,
            })
        self._port_table.load(rows)
        self._port_summary.setText(
            f"Properties: {len(g.real_estate)}  ·  Total value: {total_value:,.0f}g  ·  Lease income: {total_lease:.1f}g/day  ·  Lifetime lease: {g.ach_stats.get('re_lease_income', 0):,.0f}g"
        )

    def _refresh_listings(self, force: bool = False) -> None:
        g = self.game
        area = self._list_area_combo.currentData()
        if not isinstance(area, Area):
            area = g.current_area
        if force or not self._listings_data or self._listings_area_cache != area.value:
            self._listings_data = g._generate_property_listings(area, count=10)
            self._listings_area_cache = area.value
        rows: List[Dict[str, Any]] = []
        for idx, listing in enumerate(self._listings_data):
            rows.append({
                "name": listing["name"],
                "type": PROPERTY_CATALOGUE.get(listing["prop_type"], {}).get("name", listing["prop_type"].title()),
                "cond": f"{listing['cond_label']} ({listing['condition']:.0%})",
                "asking": f"{listing['asking_price']:,.0f}g",
                "repair": f"~{listing['repair_cost']:,.0f}g",
                "lease": f"{listing['daily_lease']:.1f}g/day",
                "haggle": "Yes" if listing["is_negotiable"] else "No",
                "flavour": listing["flavour"],
                "listing_index": idx,
                "_tag": "dim" if listing["condition"] <= 0.22 else ("green" if listing["condition"] >= 0.80 else "cyan"),
            })
        self._list_table.load(rows)
        self._list_info_lbl.setText(f"Showing {len(self._listings_data)} listings in {area.value}")

    def _refresh_land(self) -> None:
        rows: List[Dict[str, Any]] = []
        for plot in self.game.land_plots:
            if plot.build_project:
                cat = PROPERTY_CATALOGUE.get(plot.build_project, {})
                progress = f"{cat.get('build_days', 1) - plot.build_days_left}/{cat.get('build_days', 1)}d"
                status = f"Building: {cat.get('name', plot.build_project)}"
                tag = "yellow"
            else:
                progress = "—"
                status = "Undeveloped — ready to build"
                tag = "cyan"
            rows.append({
                "area": plot.area.value,
                "size": plot.size.title(),
                "cost": f"{plot.purchase_price:,.0f}g",
                "status": status,
                "progress": progress,
                "plot_id": plot.id,
                "_tag": tag,
            })
        self._land_table.load(rows)

    def _selected_property(self) -> Optional[Property]:
        row = self._port_table.selected()
        prop_id = row.get("property_id") if row else None
        if not isinstance(prop_id, int):
            return None
        return next((prop for prop in self.game.real_estate if prop.id == prop_id), None)

    def _selected_plot(self) -> Optional[LandPlot]:
        row = self._port_table.selected() or self._land_table.selected()
        plot_id = row.get("plot_id") if row else None
        if not isinstance(plot_id, int):
            return None
        return next((plot for plot in self.game.land_plots if plot.id == plot_id), None)

    def _do_toggle_lease(self) -> None:
        prop = self._selected_property()
        if prop is None:
            self.msg.warn("Select a property first.")
            return
        if prop.under_construction:
            self.msg.warn("Cannot lease a property still under construction.")
            return
        if prop.condition < 0.25:
            self.msg.warn("Property is too derelict to lease — repair it first.")
            return
        if prop.is_leased:
            tenant_name = prop.tenant_name or "current tenant"
            if not _popup_confirm(self, "End Lease", f"End lease with {tenant_name} for {prop.name}?", confirm_text="End Lease", confirm_role="danger"):
                return
            prop.is_leased = False
            prop.tenant_name = ""
            prop.lease_rate_mult = 1.0
            self.msg.ok("Lease ended.")
        else:
            applicant = LeaseApplicantDialog(self, prop.name, prop.daily_lease or 1.0).choose()
            if applicant is None:
                return
            prop.is_leased = True
            prop.tenant_name = applicant["name"]
            prop.lease_rate_mult = applicant["rate_mult"]
            actual_rate = round((prop.daily_lease / max(prop.lease_rate_mult, 0.01)) * applicant["rate_mult"], 2)
            self.game.ach_stats["re_leases_active"] = sum(1 for owned in self.game.real_estate if owned.is_leased and not owned.under_construction)
            self.msg.ok(f"{prop.name} leased to {applicant['name']} — {actual_rate:.2f}g/day.")
        self.app.refresh()

    def _do_repair(self) -> None:
        prop = self._selected_property()
        if prop is None:
            self.msg.warn("Select a property first.")
            return
        if prop.under_construction:
            self.msg.warn("Property is still being built.")
            return
        if prop.condition >= 1.0:
            self.msg.info("Property is already in perfect condition.")
            return
        repair_cost = prop.repair_cost
        g = self.game
        if g.inventory.gold < repair_cost:
            self.msg.err(f"Need {repair_cost:,.0f}g for repairs. You have {g.inventory.gold:,.0f}g.")
            return
        if not _popup_confirm(
            self,
            "Confirm Repair",
            f"Repair {prop.name} for {repair_cost:,.0f}g?\nCondition {prop.condition:.0%} -> 100%",
            confirm_text="Repair Property",
        ):
            return
        g.inventory.gold -= repair_cost
        prop.condition = 1.0
        if hasattr(g, "_log_event"):
            g._log_event(f"Repaired {prop.name} for {repair_cost:.0f}g -> pristine")
        g._check_achievements()
        self.msg.ok(f"{prop.name} fully repaired — now worth {prop.current_value:,.0f}g.")
        self.app.refresh()

    def _do_upgrade(self) -> None:
        prop = self._selected_property()
        if prop is None:
            self.msg.warn("Select a property first.")
            return
        if prop.under_construction:
            self.msg.warn("Cannot upgrade a property under construction.")
            return
        available = [(key, data) for key, data in PROPERTY_UPGRADES.items() if key not in prop.upgrades]
        if not available:
            self.msg.info("All upgrades have already been applied to this property.")
            return
        labels = [
            f"{data['desc']}  (cost {round(prop.current_value * data['cost_frac']):,.0f}g  ·  +{data['value_frac']:.0%} value  ·  +{data['lease_frac']:.0%} lease)"
            for key, data in available
        ]
        choice, ok = _popup_choose(self, "Add Upgrade", f"Choose an upgrade for {prop.name}:", labels, confirm_text="Select Upgrade")
        if not ok:
            return
        idx = labels.index(choice)
        upgrade_key, upgrade_data = available[idx]
        cost = round(prop.current_value * upgrade_data["cost_frac"], 2)
        if self.game.inventory.gold < cost:
            self.msg.err(f"Need {cost:,.0f}g for this upgrade. Have {self.game.inventory.gold:,.0f}g.")
            return
        if not _popup_confirm(self, "Confirm Upgrade", f"Apply {upgrade_key.replace('_', ' ').title()} to {prop.name} for {cost:,.0f}g?", confirm_text="Apply Upgrade"):
            return
        self.game.inventory.gold -= cost
        prop.upgrades.append(upgrade_key)
        self.game.ach_stats["re_upgrades_applied"] = self.game.ach_stats.get("re_upgrades_applied", 0) + 1
        if hasattr(self.game, "_log_event"):
            self.game._log_event(f"Upgraded {prop.name}: {upgrade_key}")
        self.game._check_achievements()
        self.msg.ok(f"Upgrade applied. New value: {prop.current_value:,.0f}g  ·  Lease: {prop.daily_lease:.1f}g/day")
        self.app.refresh()

    def _do_sell_property(self) -> None:
        prop = self._selected_property()
        if prop is None:
            plot = self._selected_plot()
            if plot is not None:
                self._do_sell_plot(plot)
            else:
                self.msg.warn("Select a property to sell.")
            return
        sell_price = round(prop.current_value * 0.88, 2)
        if not _popup_confirm(
            self,
            "Confirm Sale",
            f"Sell {prop.name} for {sell_price:,.0f}g?\nAppraised value: {prop.current_value:,.0f}g",
            confirm_text="Sell Property",
            confirm_role="danger",
        ):
            return
        profit = round(sell_price - prop.purchase_price_paid, 2)
        g = self.game
        g.inventory.gold += sell_price
        g.real_estate.remove(prop)
        g.ach_stats["re_properties_sold"] = g.ach_stats.get("re_properties_sold", 0) + 1
        g.ach_stats["re_flip_profit"] = g.ach_stats.get("re_flip_profit", 0.0) + max(0, profit)
        if profit > g.ach_stats.get("re_max_flip_profit", 0.0):
            g.ach_stats["re_max_flip_profit"] = profit
        g.total_profit += max(0, profit)
        if hasattr(g, "_log_event"):
            g._log_event(f"Sold {prop.name} for {sell_price:.0f}g (profit {profit:+.0f}g)")
        g._check_achievements()
        self.msg.ok(f"Sold {prop.name} for {sell_price:,.0f}g (profit {profit:+,.0f}g).")
        self.app.refresh()

    def _do_sell_plot(self, plot: LandPlot) -> None:
        sell_price = round(plot.purchase_price * 0.85, 2)
        if not _popup_confirm(
            self,
            "Sell Land Plot",
            f"Sell {plot.size.title()} plot in {plot.area.value} for {sell_price:,.0f}g?",
            confirm_text="Sell Plot",
            confirm_role="danger",
        ):
            return
        self.game.inventory.gold += sell_price
        self.game.land_plots.remove(plot)
        self.msg.ok(f"Land plot sold for {sell_price:,.0f}g.")
        self.app.refresh()

    def _do_refresh_listings(self) -> None:
        self._refresh_listings(force=True)

    def _do_buy_listing(self, haggle: bool) -> None:
        row = self._list_table.selected()
        idx = row.get("listing_index") if row else None
        if not isinstance(idx, int) or not (0 <= idx < len(self._listings_data)):
            self.msg.warn("Select a listing first.")
            return
        listing = self._listings_data[idx]
        g = self.game
        asking = listing["asking_price"]
        final_price = asking
        if haggle:
            if not listing["is_negotiable"]:
                self.msg.warn("This seller is firm on their price.")
                return
            success_chance = 0.20 + g.skills.haggling * 0.10
            if random.random() > success_chance:
                if not _popup_confirm(
                    self,
                    "Haggle Failed",
                    f"Your haggling attempt failed. The seller will not budge from {asking:,.0f}g. Buy anyway?",
                    confirm_text="Buy at Full Price",
                ):
                    return
            else:
                discount = min(0.28, g.skills.haggling * random.uniform(0.025, 0.07))
                final_price = round(asking * (1.0 - discount), 2)
                if not _popup_confirm(
                    self,
                    "Haggle Success",
                    f"Original asking: {asking:,.0f}g\nDiscount: {discount:.1%}\nYour price: {final_price:,.0f}g",
                    confirm_text="Accept Offer",
                ):
                    return
                g._gain_skill_xp(SkillType.HAGGLING, 8)
        else:
            if not _popup_confirm(
                self,
                "Confirm Purchase",
                f"Buy {listing['name']} ({listing['cond_label']}) for {final_price:,.0f}g?\nEst. repair to pristine: ~{listing['repair_cost']:,.0f}g\nLease income at current condition: {listing['daily_lease']:.1f}g/day",
                confirm_text="Purchase Property",
            ):
                return
        if LicenseType.REAL_ESTATE not in g.licenses:
            self.msg.err("Real Estate Charter required.")
            return
        if g.inventory.gold < final_price:
            self.msg.err(f"Need {final_price:,.0f}g. Have {g.inventory.gold:,.0f}g.")
            return
        if not _maybe_sign(self, "real_estate", detail=f"{listing['name']} for {final_price:,.0f}g"):
            return
        g.inventory.gold -= final_price
        new_prop = Property(
            id=g.next_property_id,
            prop_type=listing["prop_type"],
            name=listing["name"],
            area=listing["area"],
            condition=listing["condition"],
            base_value=listing["pristine_value"] / listing["area_mult"],
            area_mult=listing["area_mult"],
            purchase_price_paid=final_price,
        )
        g.next_property_id += 1
        g.real_estate.append(new_prop)
        g.ach_stats["re_properties_owned"] = g.ach_stats.get("re_properties_owned", 0) + 1
        areas_list = g.ach_stats.setdefault("re_properties_areas", [])
        if new_prop.area.name not in areas_list:
            areas_list.append(new_prop.area.name)
        self._listings_data.pop(idx)
        if hasattr(g, "_log_event"):
            g._log_event(f"Purchased {new_prop.name} in {new_prop.area.value} for {final_price:.0f}g")
        g._check_achievements()
        self.msg.ok(f"{new_prop.name} purchased for {final_price:,.0f}g.")
        self.app.refresh()

    def _on_dbl_buy_listing(self, _row: Dict[str, Any]) -> None:
        if self.game.settings.double_click_action:
            self._do_buy_listing(False)

    def _update_plot_cost(self) -> None:
        size = self._plot_size_combo.currentData()
        area = self._plot_area_combo.currentData()
        if not isinstance(size, str) or not isinstance(area, Area):
            return
        area_mult = AREA_PROPERTY_MULT.get(area.name, 1.0)
        base_cost = LAND_PLOT_SIZES[size]["base_cost"]
        cost = round(base_cost * area_mult, 0)
        buildable = ", ".join(sorted(LAND_PLOT_SIZES[size]["max_build"]))
        self._plot_cost_lbl.setText(f"Plot cost: {cost:,.0f}g  ·  Buildable: {buildable}")

    def _do_buy_plot(self) -> None:
        g = self.game
        if LicenseType.REAL_ESTATE not in g.licenses:
            self.msg.err("Real Estate Charter required.")
            return
        size = self._plot_size_combo.currentData()
        area = self._plot_area_combo.currentData()
        if not isinstance(size, str) or not isinstance(area, Area):
            self.msg.err("Select a valid plot size and area.")
            return
        cost = round(LAND_PLOT_SIZES[size]["base_cost"] * AREA_PROPERTY_MULT.get(area.name, 1.0), 0)
        if g.inventory.gold < cost:
            self.msg.err(f"Need {cost:,.0f}g. Have {g.inventory.gold:,.0f}g.")
            return
        if not _popup_confirm(self, "Buy Land Plot", f"Buy {size.title()} plot in {area.value} for {cost:,.0f}g?", confirm_text="Buy Plot"):
            return
        if not _maybe_sign(self, "land", detail=f"{size.title()} plot in {area.value} for {cost:,.0f}g"):
            return
        g.inventory.gold -= cost
        g.land_plots.append(LandPlot(id=g.next_plot_id, area=area, size=size, purchase_price=cost))
        g.next_plot_id += 1
        if hasattr(g, "_log_event"):
            g._log_event(f"Bought {size} land plot in {area.value} for {cost:.0f}g")
        self.msg.ok(f"{size.title()} land plot purchased in {area.value} for {cost:,.0f}g.")
        self.app.refresh()

    def _do_start_build(self) -> None:
        row = self._land_table.selected()
        plot_id = row.get("plot_id") if row else None
        if not isinstance(plot_id, int):
            self.msg.warn("Select a land plot first.")
            return
        plot = next((candidate for candidate in self.game.land_plots if candidate.id == plot_id), None)
        if plot is None:
            self.msg.warn("Selected land plot could not be found.")
            return
        if plot.build_project:
            self.msg.warn(f"Construction already underway: {plot.build_project}.")
            return
        max_build = LAND_PLOT_SIZES[plot.size]["max_build"]
        buildable = [
            key for key in max_build
            if (cat := PROPERTY_CATALOGUE.get(key)) and (cat.get("areas") is None or plot.area.name in cat["areas"])
        ]
        if not buildable:
            self.msg.warn("No buildable property types for this plot in this area.")
            return
        area_mult = AREA_PROPERTY_MULT.get(plot.area.name, 1.0)
        key = BuildProjectDialog(self, f"Build on {plot.size.title()} Plot — {plot.area.value}", buildable, area_mult).choose()
        if not key:
            return
        cat = PROPERTY_CATALOGUE[key]
        cost = round(cat["build_cost"] * area_mult, 0)
        if self.game.inventory.gold < cost:
            self.msg.err(f"Need {cost:,.0f}g to start construction. Have {self.game.inventory.gold:,.0f}g.")
            return
        if not _popup_confirm(
            self,
            "Confirm Build",
            f"Build {cat['name']} on this {plot.size} plot in {plot.area.value}?\nCost: {cost:,.0f}g\nDuration: {cat['build_days']} days\nFinished value: ~{round(cat['base_value'] * area_mult):,}g",
            confirm_text="Start Construction",
        ):
            return
        self.game.inventory.gold -= cost
        plot.build_project = key
        plot.build_days_left = cat["build_days"]
        plot.build_cost_paid = cost
        if hasattr(self.game, "_log_event"):
            self.game._log_event(f"Started building {cat['name']} in {plot.area.value}: {cost:.0f}g, {cat['build_days']}d")
        self.msg.ok(f"Construction started. {cat['name']} will be ready in {cat['build_days']} days.")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# MANAGERS SCREEN  —  hire, inspect, configure, and fire NPC managers
# ══════════════════════════════════════════════════════════════════════════════

class ManagersScreen(Screen):
    _LEVEL_COLOURS = {1: P.fg_dim, 2: P.green, 3: P.gold, 4: P.amber, 5: P.red}
    _NAME_FIRST = [
        "Aldric", "Benedict", "Cassius", "Dorian", "Edmund", "Flavian", "Gerald", "Humphrey",
        "Isolde", "Jasmine", "Kira", "Leopold", "Mabel", "Neville", "Octavia", "Percival",
        "Quincy", "Rosalind", "Seward", "Tilda", "Upton", "Viola", "Weston", "Ysabel", "Zorn",
        "Agnes", "Bertram", "Constance", "Draven", "Elspeth", "Fiona", "Gregory", "Helena",
    ]
    _NAME_LAST = [
        "the Able", "the Bold", "Ironhand", "Silverquill", "the Shrewd", "of Ashford",
        "Coldwater", "Emberstone", "of the Guilds", "Goldsworth", "Farsight", "Briarwick",
        "Copperlock", "of the Watch", "Saltmarsh", "Blackledger", "Fairweather", "the Keen",
    ]

    def build(self) -> None:
        self._selected_manager_id: Optional[str] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        hdr = QHBoxLayout()
        hdr.addWidget(self.section_label("Managers & Staff"))
        hdr.addStretch()
        self._wage_lbl = QLabel(self)
        self._wage_lbl.setFont(Fonts.mono_small)
        self._wage_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        hdr.addWidget(self._wage_lbl)
        root.addLayout(hdr)

        body = QHBoxLayout()
        body.setSpacing(UIScale.px(10))

        left = QFrame(self)
        left.setObjectName("dashPanel")
        left.setMinimumWidth(UIScale.px(330))
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(UIScale.px(12), UIScale.px(10), UIScale.px(12), UIScale.px(12))
        left_lay.setSpacing(UIScale.px(8))
        left_hdr = QLabel("Your Staff", left)
        left_hdr.setFont(Fonts.mixed_bold)
        left_hdr.setStyleSheet(f"color:{P.gold}; background:transparent;")
        left_lay.addWidget(left_hdr)
        self._roster = QListWidget(left)
        self._roster.setFont(Fonts.mixed_small)
        self._roster.currentRowChanged.connect(self._on_select_manager)
        left_lay.addWidget(self._roster, 1)
        hire_btn = self.action_button("Hire a Manager", self._do_hire)
        hire_btn.setFixedHeight(UIScale.px(32))
        left_lay.addWidget(hire_btn)
        body.addWidget(left, 1)

        right = QFrame(self)
        right.setObjectName("dashPanel")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(UIScale.px(12), UIScale.px(10), UIScale.px(12), UIScale.px(12))
        right_lay.setSpacing(UIScale.px(8))
        right_hdr = QLabel("Manager Details", right)
        right_hdr.setFont(Fonts.mixed_bold)
        right_hdr.setStyleSheet(f"color:{P.gold}; background:transparent;")
        right_lay.addWidget(right_hdr)
        self._detail_title = QLabel("Select a manager", right)
        self._detail_title.setFont(Fonts.title)
        self._detail_title.setStyleSheet(f"color:{P.cream}; background:transparent;")
        right_lay.addWidget(self._detail_title)
        self._detail_desc = QLabel("Choose a manager from the roster to inspect their stats and automation config.", right)
        self._detail_desc.setFont(Fonts.mixed_small)
        self._detail_desc.setWordWrap(True)
        self._detail_desc.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        right_lay.addWidget(self._detail_desc)
        self._stats_txt = QTextEdit(right)
        self._stats_txt.setReadOnly(True)
        self._stats_txt.setFont(Fonts.mono_small)
        self._stats_txt.setStyleSheet(
            f"QTextEdit{{background:{P.bg}; color:{P.fg}; border:1px solid {P.border};"
            f"border-radius:{UIScale.px(4)}px; padding:{UIScale.px(8)}px;}}"
        )
        right_lay.addWidget(self._stats_txt, 1)
        act_row = QHBoxLayout()
        self._cfg_btn = self.action_button("Edit Config", self._do_configure, role="secondary")
        self._fire_btn = self.action_button("Fire Manager", self._do_fire, role="danger")
        self._cfg_btn.setFixedHeight(UIScale.px(30))
        self._fire_btn.setFixedHeight(UIScale.px(30))
        self._cfg_btn.setEnabled(False)
        self._fire_btn.setEnabled(False)
        act_row.addWidget(self._cfg_btn)
        act_row.addWidget(self._fire_btn)
        act_row.addStretch()
        right_lay.addLayout(act_row)
        body.addWidget(right, 2)

        root.addLayout(body, 1)

        log_panel = QFrame(self)
        log_panel.setObjectName("dashPanel")
        log_lay = QVBoxLayout(log_panel)
        log_lay.setContentsMargins(UIScale.px(12), UIScale.px(10), UIScale.px(12), UIScale.px(12))
        log_hdr = QLabel("Recent Manager Activity", log_panel)
        log_hdr.setFont(Fonts.mixed_bold)
        log_hdr.setStyleSheet(f"color:{P.amber}; background:transparent;")
        log_lay.addWidget(log_hdr)
        self._log_txt = QTextEdit(log_panel)
        self._log_txt.setReadOnly(True)
        self._log_txt.setMaximumHeight(UIScale.px(120))
        self._log_txt.setFont(Fonts.mono_small)
        self._log_txt.setStyleSheet(
            f"QTextEdit{{background:{P.bg}; color:{P.fg_dim}; border:1px solid {P.border};"
            f"border-radius:{UIScale.px(4)}px; padding:{UIScale.px(8)}px;}}"
        )
        log_lay.addWidget(self._log_txt)
        root.addWidget(log_panel)

        foot = QHBoxLayout()
        foot.addWidget(self.back_button())
        foot.addStretch()
        root.addLayout(foot)

    def refresh(self) -> None:
        total_wage = sum(mgr.weekly_wage for mgr in self.game.hired_managers if mgr.is_active)
        self._wage_lbl.setText(f"Weekly payroll: {total_wage:.0f}g/wk")

        self._roster.blockSignals(True)
        self._roster.clear()
        for mgr in self.game.hired_managers:
            defn = MANAGER_DEFS.get(mgr.type_enum(), {})
            icon = defn.get("icon", "⚙")
            item = QListWidgetItem(f"{icon}  {mgr.name}  ·  {mgr.manager_type}  ·  Lv{mgr.level}")
            item.setData(Qt.ItemDataRole.UserRole, mgr.name)
            item.setForeground(QColor(self._LEVEL_COLOURS.get(mgr.level, P.fg)))
            self._roster.addItem(item)
        self._roster.blockSignals(False)

        if self._selected_manager_id is not None:
            for idx in range(self._roster.count()):
                item = self._roster.item(idx)
                if item.data(Qt.ItemDataRole.UserRole) == self._selected_manager_id:
                    self._roster.setCurrentRow(idx)
                    break
            else:
                self._selected_manager_id = None
        if self._selected_manager_id is None and self._roster.count() > 0:
            self._roster.setCurrentRow(0)
        if self._roster.count() == 0:
            self._show_no_selection()
        self._refresh_log()

    def _refresh_log(self) -> None:
        logs = list(self.game._manager_action_log)[:20]
        self._log_txt.setPlainText("\n".join(logs) if logs else "No manager activity yet.")

    def _show_no_selection(self) -> None:
        self._detail_title.setText("No manager selected")
        self._detail_desc.setText("Hire a manager or select one from the roster to inspect details.")
        self._stats_txt.setPlainText("")
        self._cfg_btn.setEnabled(False)
        self._fire_btn.setEnabled(False)

    def _selected_manager(self) -> Optional[HiredManager]:
        if self._selected_manager_id is None:
            return None
        return next((mgr for mgr in self.game.hired_managers if mgr.name == self._selected_manager_id), None)

    def _on_select_manager(self, row: int) -> None:
        if row < 0 or row >= self._roster.count():
            self._selected_manager_id = None
            self._show_no_selection()
            return
        item = self._roster.item(row)
        self._selected_manager_id = item.data(Qt.ItemDataRole.UserRole)
        mgr = self._selected_manager()
        if mgr is None:
            self._show_no_selection()
            return
        defn = MANAGER_DEFS.get(mgr.type_enum(), {})
        self._detail_title.setText(f"{defn.get('icon', '⚙')}  {mgr.name}  ·  Lv{mgr.level}")
        self._detail_desc.setText(f"{defn.get('desc', '')}\n\n{defn.get('detail', '')}")
        stats = mgr.stats
        last_action = stats.get("last_action_desc", "—")
        cfg_preview = "\n".join(f"{key}: {value}" for key, value in list(mgr.config.items())[:8]) or "Default settings"
        self._stats_txt.setPlainText(
            f"Type: {mgr.manager_type}\n"
            f"Efficiency: {mgr.efficiency * 100:.0f}%\n"
            f"Weekly Wage: {mgr.weekly_wage:.0f}g\n"
            f"Days Employed: {mgr.days_employed}\n"
            f"XP: {mgr.xp}\n"
            f"XP To Next: {mgr.xp_to_next()}\n\n"
            f"Actions Taken: {stats.get('total_actions', 0)}\n"
            f"Gold Generated: {stats.get('total_gold_generated', 0.0):,.0f}g\n"
            f"Wages Paid: {stats.get('total_wages_paid', 0.0):,.0f}g\n"
            f"Operating Costs: {stats.get('total_gold_cost', 0.0):,.0f}g\n"
            f"Mistakes: {stats.get('mistakes', 0)}\n"
            f"Level-ups: {stats.get('level_ups', 0)}\n"
            f"Last Action: {last_action}\n\n"
            f"Configuration\n{cfg_preview}"
        )
        self._cfg_btn.setEnabled(True)
        self._fire_btn.setEnabled(True)

    def _random_name(self) -> str:
        return f"{random.choice(self._NAME_FIRST)} {random.choice(self._NAME_LAST)}"

    def _do_hire(self) -> None:
        g = self.game
        available: List[Tuple[ManagerType, Dict[str, Any], bool, bool]] = []
        labels: List[str] = []
        for mt, defn in MANAGER_DEFS.items():
            required = defn.get("license")
            unlocked = required is None or required in g.licenses
            already = any(mgr.manager_type == mt.value for mgr in g.hired_managers)
            available.append((mt, defn, unlocked, already))
            status = "Hired" if already else ("Available" if unlocked else f"Need {required.value}")
            labels.append(f"{defn.get('icon', '⚙')}  {mt.value}  —  {defn['wage']:.0f}g/wk  [{status}]")
        choice, ok = _popup_choose(self, "Hire Manager", "Choose a manager type to recruit:", labels, confirm_text="Select")
        if not ok:
            return
        idx = labels.index(choice)
        mt, defn, unlocked, already = available[idx]
        if already:
            self.msg.warn(f"You already have a {mt.value} hired.")
            return
        if not unlocked:
            required = defn.get("license")
            self.msg.err(f"You need {required.value} to hire this manager.")
            return
        name = self._random_name()
        if not _popup_confirm(
            self,
            "Hire Manager",
            f"Hire {name} as {mt.value}?\nWeekly wage: {defn['wage']:.0f}g/week\nStarting efficiency: 65% (Lv1)",
            confirm_text="Hire Manager",
        ):
            return
        cfg = dict(_MANAGER_DEFAULT_CONFIGS.get(mt.value, {}))
        g.hired_managers.append(HiredManager(manager_type=mt.value, name=name, weekly_wage=defn["wage"], config=cfg))
        if hasattr(g, "_log_trade"):
            g._log_trade(f"Hired {name} as {mt.value} at {defn['wage']:.0f}g/wk")
        self._selected_manager_id = name
        self.msg.ok(f"Hired {name} as {mt.value}.")
        self.app.refresh()

    def _do_fire(self) -> None:
        mgr = self._selected_manager()
        if mgr is None:
            self.msg.warn("Select a manager to fire.")
            return
        if not _popup_confirm(
            self,
            "Fire Manager",
            f"Fire {mgr.name}? XP and manager history will be lost.",
            confirm_text="Fire Manager",
            confirm_role="danger",
        ):
            return
        if hasattr(self.game, "_log_trade"):
            self.game._log_trade(f"Fired manager {mgr.name} ({mgr.manager_type})")
        self.game.hired_managers = [candidate for candidate in self.game.hired_managers if candidate.name != mgr.name]
        self._selected_manager_id = None
        self.msg.ok(f"Fired {mgr.name}.")
        self.app.refresh()

    def _config_fields(self, mgr: HiredManager) -> List[Dict[str, Any]]:
        mt = mgr.type_enum()
        if mt == ManagerType.BUSINESS_FOREMAN:
            return [
                {"key": "auto_repair", "label": "Auto-repair broken businesses", "kind": "bool"},
                {"key": "auto_hire", "label": "Auto-hire workers to fill slots", "kind": "bool"},
                {"key": "auto_fire_lazy", "label": "Auto-fire lazy or overpaid workers", "kind": "bool"},
                {"key": "repair_threshold", "label": "Max repair cost (g)", "kind": "float", "default": 500.0},
                {"key": "min_worker_productivity", "label": "Min worker productivity", "kind": "float", "default": 0.6, "clamp": (0.0, 1.0)},
                {"key": "max_wage_per_worker", "label": "Max wage per worker (g)", "kind": "float", "default": 8.0},
            ]
        if mt == ManagerType.TRADE_STEWARD:
            return [
                {"key": "sell_business_output", "label": "Sell business-produced goods", "kind": "bool"},
                {"key": "sell_purchased_goods", "label": "Sell manually purchased goods", "kind": "bool"},
                {"key": "auto_buy_for_resale", "label": "Auto-buy for resale", "kind": "bool"},
                {"key": "allow_travel", "label": "Allow steward travel", "kind": "bool"},
                {"key": "sell_min_quantity", "label": "Min quantity to sell", "kind": "int", "default": 1},
                {"key": "keep_quantity", "label": "Always keep quantity", "kind": "int", "default": 0},
                {"key": "max_buy_gold", "label": "Max buy budget (g)", "kind": "float", "default": 200.0},
                {"key": "min_profit_pct", "label": "Min profit pct", "kind": "float", "default": 0.08, "clamp": (0.0, 5.0)},
                {"key": "patience_days", "label": "Patience days", "kind": "int", "default": 5},
                {"key": "max_travel_days", "label": "Max travel days", "kind": "int", "default": 2},
            ]
        if mt == ManagerType.PROPERTY_STEWARD:
            return [
                {"key": "auto_lease", "label": "Auto-lease vacant properties", "kind": "bool"},
                {"key": "reject_risky_tenants", "label": "Reject risky tenants", "kind": "bool"},
                {"key": "auto_repair", "label": "Auto-repair damaged properties", "kind": "bool"},
                {"key": "auto_evict_low_condition", "label": "Auto-evict for low condition", "kind": "bool"},
                {"key": "min_condition_to_repair", "label": "Repair below condition", "kind": "float", "default": 0.55, "clamp": (0.0, 1.0)},
                {"key": "max_repair_cost", "label": "Max repair cost (g)", "kind": "float", "default": 1000.0},
                {"key": "evict_condition_threshold", "label": "Evict below condition", "kind": "float", "default": 0.30, "clamp": (0.0, 1.0)},
            ]
        if mt == ManagerType.CONTRACT_AGENT:
            return [
                {"key": "auto_fulfill", "label": "Auto-fulfill contracts", "kind": "bool"},
                {"key": "auto_procure", "label": "Auto-procure missing goods", "kind": "bool"},
                {"key": "min_profit_per_unit", "label": "Min profit per unit", "kind": "float", "default": 0.5},
                {"key": "max_deadline_days", "label": "Max deadline days", "kind": "int", "default": 30},
                {"key": "max_procure_gold", "label": "Max procurement budget (g)", "kind": "float", "default": 300.0},
            ]
        if mt == ManagerType.LENDING_ADVISOR:
            return [
                {"key": "auto_issue", "label": "Auto-issue loans", "kind": "bool"},
                {"key": "prefer_short_loans", "label": "Prefer short loans", "kind": "bool"},
                {"key": "auto_write_off", "label": "Auto-write off defaults", "kind": "bool"},
                {"key": "min_creditworthiness", "label": "Min creditworthiness", "kind": "float", "default": 0.7, "clamp": (0.5, 1.5)},
                {"key": "max_loan_amount", "label": "Max loan amount (g)", "kind": "float", "default": 300.0},
                {"key": "max_active_loans", "label": "Max active loans", "kind": "int", "default": 5},
                {"key": "max_total_loaned", "label": "Max total loaned (g)", "kind": "float", "default": 1000.0},
            ]
        if mt == ManagerType.INVESTMENT_BROKER:
            return [
                {"key": "auto_buy", "label": "Auto-buy stocks", "kind": "bool"},
                {"key": "auto_sell", "label": "Auto-sell stocks", "kind": "bool"},
                {"key": "max_investment_per_stock", "label": "Max per-stock investment (g)", "kind": "float", "default": 200.0},
                {"key": "max_portfolio_value", "label": "Max portfolio value (g)", "kind": "float", "default": 1000.0},
                {"key": "risk_tolerance", "label": "Risk tolerance", "kind": "float", "default": 0.5, "clamp": (0.0, 1.0)},
                {"key": "min_gain_to_sell", "label": "Min gain to sell", "kind": "float", "default": 0.15, "clamp": (0.0, 10.0)},
                {"key": "stop_loss_pct", "label": "Stop-loss pct", "kind": "float", "default": 0.20, "clamp": (0.0, 10.0)},
            ]
        if mt == ManagerType.FUND_CUSTODIAN:
            return [
                {"key": "auto_accept", "label": "Auto-accept fund clients", "kind": "bool"},
                {"key": "max_clients", "label": "Max active clients", "kind": "int", "default": 4},
                {"key": "min_client_capital", "label": "Min client capital (g)", "kind": "float", "default": 300.0},
                {"key": "min_fee_rate", "label": "Min fee rate", "kind": "float", "default": 0.01, "clamp": (0.0, 10.0)},
                {"key": "min_duration_days", "label": "Min duration days", "kind": "int", "default": 30},
            ]
        if mt == ManagerType.CAMPAIGN_HANDLER:
            return [
                {"key": "skip_if_last_loss", "label": "Skip if last campaign lost money", "kind": "bool"},
                {"key": "campaign_frequency_days", "label": "Campaign frequency days", "kind": "int", "default": 14},
                {"key": "max_campaign_cost", "label": "Max campaign cost (g)", "kind": "float", "default": 50.0},
                {"key": "preferred_area", "label": "Preferred area", "kind": "choice", "options": [area.name for area in Area], "default": "CITY"},
            ]
        return [
            {"key": "heat_pause_after_bust", "label": "Pause after bust", "kind": "bool"},
            {"key": "max_heat", "label": "Max heat", "kind": "int", "default": 60},
            {"key": "ops_frequency_days", "label": "Ops frequency days", "kind": "int", "default": 7},
            {"key": "max_bust_risk", "label": "Max bust risk", "kind": "float", "default": 0.25, "clamp": (0.0, 1.0)},
            {"key": "min_net_profit", "label": "Min net profit (g)", "kind": "float", "default": 0.0},
        ]

    def _do_configure(self) -> None:
        mgr = self._selected_manager()
        if mgr is None:
            self.msg.warn("Select a manager to configure.")
            return
        dlg = ManagerConfigDialog(self, mgr, self._config_fields(mgr))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.msg.ok(f"Updated config for {mgr.name}.")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# VOYAGE SCREEN  —  fleet, captains, and international trade voyages
# ══════════════════════════════════════════════════════════════════════════════

class VoyageScreen(Screen):
    _FLEET_COLS = [
        ("ship_name", "Ship Name", 170),
        ("ship_type", "Type", 108),
        ("cargo_cap", "Cargo", 70, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("status", "Status", 90),
        ("upgrades", "Upgrades", 280),
    ]
    _CAPTAIN_COLS = [
        ("cap_name", "Name", 150),
        ("title", "Title", 90),
        ("nav", "Nav", 48, Qt.AlignmentFlag.AlignCenter),
        ("com", "Combat", 60, Qt.AlignmentFlag.AlignCenter),
        ("sea", "Sea", 50, Qt.AlignmentFlag.AlignCenter),
        ("cha", "Charm", 60, Qt.AlignmentFlag.AlignCenter),
        ("wage", "Voyage Wage", 90, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("cap_status", "Status", 90),
    ]
    _VOYAGE_COLS = [
        ("ship", "Ship", 120),
        ("captain", "Captain", 150),
        ("dest", "Destination", 120),
        ("days", "Days Left", 80, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("status", "Status", 110),
        ("outcome", "Outcome", 360),
    ]
    _DEST_COLS = [
        ("port_name", "Port", 150),
        ("best_cat", "Best Cargo", 360),
        ("time_mod", "Voyage Time", 120),
    ]

    def _summary_card(self, parent: QWidget, title: str, color: str) -> Tuple[QFrame, QLabel]:
        frame = QFrame(parent)
        frame.setObjectName("dashPanel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(UIScale.px(10), UIScale.px(8), UIScale.px(10), UIScale.px(8))
        lay.setSpacing(UIScale.px(3))
        hdr = QLabel(title, frame)
        hdr.setFont(Fonts.tiny)
        hdr.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        lay.addWidget(hdr)
        value = QLabel("—", frame)
        value.setFont(Fonts.mixed_small_bold)
        value.setWordWrap(True)
        value.setStyleSheet(f"color:{color}; background:transparent;")
        lay.addWidget(value)
        lay.addStretch()
        return frame, value

    def _detail_box(self, parent: QWidget) -> QTextEdit:
        box = QTextEdit(parent)
        box.setReadOnly(True)
        box.setMaximumHeight(UIScale.px(112))
        box.setFont(Fonts.mono_small)
        box.setStyleSheet(
            f"QTextEdit{{background:{P.bg}; color:{P.cream}; border:1px solid {P.border};"
            f"border-radius:{UIScale.px(4)}px; padding:{UIScale.px(8)}px;}}"
        )
        return box

    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        hdr = QHBoxLayout()
        hdr.addWidget(self.section_label("Voyage — International Trade"))
        hdr.addStretch()
        self._info_lbl = QLabel(self)
        self._info_lbl.setFont(Fonts.mono_small)
        self._info_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        hdr.addWidget(self._info_lbl)
        root.addLayout(hdr)

        self._gate_lbl = QLabel(self)
        self._gate_lbl.setFont(Fonts.mixed_bold)
        self._gate_lbl.setWordWrap(True)
        self._gate_lbl.setStyleSheet(f"color:{P.red}; background:transparent;")
        root.addWidget(self._gate_lbl)

        sum_row = QHBoxLayout()
        self._sum_vals: Dict[str, QLabel] = {}
        for key, title, color in [
            ("fleet", "Fleet Status", P.gold),
            ("captains", "Captains Ready", P.green),
            ("voyages", "Voyages Active", P.amber),
            ("cargo", "Cargo at Sea", P.cream),
        ]:
            card, value = self._summary_card(self, title, color)
            self._sum_vals[key] = value
            sum_row.addWidget(card, 1)
        root.addLayout(sum_row)

        tabs = QTabWidget(self)

        command = QWidget(self)
        command_lay = QVBoxLayout(command)
        command_lay.setContentsMargins(UIScale.px(8), UIScale.px(8), UIScale.px(8), UIScale.px(8))
        command_lay.setSpacing(UIScale.px(8))
        note = QLabel(
            "Select a ship and captain, then launch from here. Even if nothing is selected, the voyage flow will still prompt you through setup.",
            command,
        )
        note.setFont(Fonts.tiny)
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        command_lay.addWidget(note)

        split = QSplitter(Qt.Orientation.Horizontal, command)
        split.setChildrenCollapsible(False)

        fleet_panel = QFrame(split)
        fleet_panel.setObjectName("dashPanel")
        fleet_lay = QVBoxLayout(fleet_panel)
        fleet_lay.setContentsMargins(UIScale.px(10), UIScale.px(10), UIScale.px(10), UIScale.px(10))
        fleet_lay.setSpacing(UIScale.px(6))
        fleet_lbl = QLabel("Fleet", fleet_panel)
        fleet_lbl.setFont(Fonts.mixed_bold)
        fleet_lbl.setStyleSheet(f"color:{P.amber}; background:transparent;")
        fleet_lay.addWidget(fleet_lbl)
        self._fleet_table = DataTable(fleet_panel, self._FLEET_COLS, row_height=28)
        self._fleet_table.row_selected.connect(self._on_select_ship)
        fleet_lay.addWidget(self._fleet_table, 1)
        self._fleet_detail = self._detail_box(fleet_panel)
        fleet_lay.addWidget(self._fleet_detail)
        fleet_act = QHBoxLayout()
        for text, handler, role in [
            ("Buy Ship", self._buy_ship, "primary"),
            ("Upgrade Ship", self._upgrade_ship, "secondary"),
            ("Sell Ship", self._sell_ship, "danger"),
        ]:
            btn = self.action_button(text, handler, role=role)
            btn.setFixedHeight(UIScale.px(30))
            fleet_act.addWidget(btn)
        fleet_act.addStretch()
        fleet_lay.addLayout(fleet_act)

        cap_panel = QFrame(split)
        cap_panel.setObjectName("dashPanel")
        cap_lay = QVBoxLayout(cap_panel)
        cap_lay.setContentsMargins(UIScale.px(10), UIScale.px(10), UIScale.px(10), UIScale.px(10))
        cap_lay.setSpacing(UIScale.px(6))
        cap_lbl = QLabel("Captain Roster", cap_panel)
        cap_lbl.setFont(Fonts.mixed_bold)
        cap_lbl.setStyleSheet(f"color:{P.amber}; background:transparent;")
        cap_lay.addWidget(cap_lbl)
        self._cap_table = DataTable(cap_panel, self._CAPTAIN_COLS, row_height=28)
        self._cap_table.row_selected.connect(self._on_select_captain)
        cap_lay.addWidget(self._cap_table, 1)
        self._cap_detail = self._detail_box(cap_panel)
        cap_lay.addWidget(self._cap_detail)
        cap_act = QHBoxLayout()
        for text, handler, role in [
            ("Hire Captain", self._hire_captain, "primary"),
            ("Dismiss Captain", self._dismiss_captain, "danger"),
            ("Launch Voyage", self._launch_voyage, "secondary"),
        ]:
            btn = self.action_button(text, handler, role=role)
            btn.setFixedHeight(UIScale.px(30))
            cap_act.addWidget(btn)
        cap_act.addStretch()
        cap_lay.addLayout(cap_act)

        split.addWidget(fleet_panel)
        split.addWidget(cap_panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        command_lay.addWidget(split, 1)
        tabs.addTab(command, f"{Sym.VOYAGE}  Command")

        voyages_tab = QWidget(self)
        voyages_lay = QVBoxLayout(voyages_tab)
        voyages_lay.setContentsMargins(UIScale.px(8), UIScale.px(8), UIScale.px(8), UIScale.px(8))
        voyages_lay.setSpacing(UIScale.px(8))
        self._voyage_table = DataTable(voyages_tab, self._VOYAGE_COLS, row_height=28)
        self._voyage_table.row_selected.connect(self._on_select_voyage)
        voyages_lay.addWidget(self._voyage_table, 1)
        self._voyage_detail = self._detail_box(voyages_tab)
        voyages_lay.addWidget(self._voyage_detail)
        voyage_act = QHBoxLayout()
        for text, handler, role in [
            ("Collect Results", self._collect_results, "secondary"),
            ("Clear Completed", self._clear_completed, "danger"),
        ]:
            btn = self.action_button(text, handler, role=role)
            btn.setFixedHeight(UIScale.px(30))
            voyage_act.addWidget(btn)
        voyage_act.addStretch()
        voyages_lay.addLayout(voyage_act)
        tabs.addTab(voyages_tab, f"{Sym.PROGRESS}  Voyages")

        ports_tab = QWidget(self)
        ports_lay = QVBoxLayout(ports_tab)
        ports_lay.setContentsMargins(UIScale.px(8), UIScale.px(8), UIScale.px(8), UIScale.px(8))
        ports_lay.setSpacing(UIScale.px(8))
        port_note = QLabel("Destination guide values show the strongest cargo categories and route-time modifier for each port.", ports_tab)
        port_note.setFont(Fonts.tiny)
        port_note.setWordWrap(True)
        port_note.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        ports_lay.addWidget(port_note)
        self._dest_table = DataTable(ports_tab, self._DEST_COLS, row_height=28)
        self._dest_table.row_selected.connect(self._on_select_port)
        ports_lay.addWidget(self._dest_table, 1)
        self._port_detail = self._detail_box(ports_tab)
        ports_lay.addWidget(self._port_detail)
        tabs.addTab(ports_tab, f"{Sym.LOCATION}  Ports")

        root.addWidget(tabs, 1)

        foot = QHBoxLayout()
        foot.addWidget(self.back_button())
        foot.addStretch()
        root.addLayout(foot)

    def refresh(self) -> None:
        g = self.game
        has_license = LicenseType.VOYAGE in g.licenses
        self._info_lbl.setText(f"Wallet: {g.inventory.gold:,.0f}g  ·  Reputation: {g.reputation}  ·  Ships: {len(g.ships)}")
        if has_license:
            self._gate_lbl.setText("")
        else:
            info = LICENSE_INFO.get(LicenseType.VOYAGE, {})
            self._gate_lbl.setText(
                f"Voyage Charter required. Cost: {info.get('cost', 3000):,.0f}g  ·  Reputation needed: {info.get('rep', 100)}"
            )

        active_voyages = [voy for voy in g.voyages if voy.status == "sailing"]
        docked = [ship for ship in g.ships if ship.status == "docked"]
        sailing_ids = {voy.captain_id for voy in active_voyages}
        free_captains = [captain for captain in g.captains if captain.is_hired and captain.id not in sailing_ids]
        cargo_units = sum(sum(voyage.cargo.values()) for voyage in active_voyages)
        self._sum_vals["fleet"].setText(f"{len(docked)} docked  ·  {len(g.ships) - len(docked)} sailing")
        self._sum_vals["captains"].setText(f"{len(free_captains)} ready  ·  {len([c for c in g.captains if c.is_hired])} hired")
        self._sum_vals["voyages"].setText(f"{len(active_voyages)} active  ·  {len(g.voyages) - len(active_voyages)} completed")
        self._sum_vals["cargo"].setText(f"{cargo_units} units at sea")

        fleet_rows: List[Dict[str, Any]] = []
        for ship in g.ships:
            ship_info = SHIP_TYPES.get(ship.ship_type, {})
            fleet_rows.append({
                "ship_name": ship.name,
                "ship_type": ship_info.get("name", ship.ship_type),
                "cargo_cap": str(ship.cargo_capacity),
                "status": "Sailing" if ship.status == "sailing" else "Docked",
                "upgrades": ", ".join(SHIP_UPGRADES[upgrade]["name"] for upgrade in ship.upgrades) or "—",
                "ship_id": ship.id,
                "_tag": "yellow" if ship.status == "sailing" else "cyan",
            })
        self._fleet_table.load(fleet_rows)
        cap_rows: List[Dict[str, Any]] = []
        for captain in g.captains:
            if captain.is_hired and captain.id in sailing_ids:
                status = "Sailing"
                tag = "yellow"
            elif captain.is_hired:
                status = "Hired"
                tag = "green"
            else:
                status = "Available"
                tag = "dim"
            cap_rows.append({
                "cap_name": captain.name,
                "title": captain.title,
                "nav": str(captain.navigation),
                "com": str(captain.combat),
                "sea": str(captain.seamanship),
                "cha": str(captain.charisma),
                "wage": f"{captain.wage_per_voyage:.0f}g",
                "cap_status": status,
                "captain_id": captain.id,
                "_tag": tag,
            })
        self._cap_table.load(cap_rows)

        voyage_rows: List[Dict[str, Any]] = []
        for voyage in reversed(g.voyages):
            port = VOYAGE_PORTS.get(voyage.destination_key, {})
            if voyage.status == "sailing":
                outcome = f"{voyage.days_remaining}d remaining"
                tag = "yellow"
            elif voyage.status == "arrived":
                outcome = f"+{voyage.outcome_gold:,.0f}g"
                tag = "green"
            else:
                outcome = voyage.outcome_text[:80]
                tag = "red"
            voyage_rows.append({
                "ship": voyage.ship_name,
                "captain": voyage.captain_name,
                "dest": port.get("name", voyage.destination_key),
                "days": str(voyage.days_remaining) if voyage.status == "sailing" else "—",
                "status": voyage.status.replace("_", " ").title(),
                "outcome": outcome,
                "ship_name": voyage.ship_name,
                "_tag": tag,
            })
        self._voyage_table.load(voyage_rows)

        dest_rows: List[Dict[str, Any]] = []
        for port_key, port in VOYAGE_PORTS.items():
            best = ", ".join(
                f"{name} ×{mult:.1f}"
                for name, mult in sorted(port.get("profit_mult", {}).items(), key=lambda item: -item[1])
            )
            days_mod = port.get("days_mod", 1.0)
            if days_mod < 1.0:
                time_mod = f"Shorter ({days_mod:.0%})"
            elif days_mod > 1.0:
                time_mod = f"Longer ({days_mod:.0%})"
            else:
                time_mod = "Standard"
            dest_rows.append({"port_name": port.get("name", port_key), "best_cat": best, "time_mod": time_mod, "port_key": port_key})
        self._dest_table.load(dest_rows)

        self._on_select_ship(self._fleet_table.selected() or (fleet_rows[0] if fleet_rows else {}))
        self._on_select_captain(self._cap_table.selected() or (cap_rows[0] if cap_rows else {}))
        self._on_select_voyage(self._voyage_table.selected() or (voyage_rows[0] if voyage_rows else {}))
        self._on_select_port(self._dest_table.selected() or (dest_rows[0] if dest_rows else {}))

    def _on_select_ship(self, row: Dict[str, Any]) -> None:
        ship_id = row.get("ship_id") if row else None
        ship = next((candidate for candidate in self.game.ships if candidate.id == ship_id), None) if isinstance(ship_id, int) else None
        if ship is None:
            self._fleet_detail.setPlainText("Select a ship to inspect cargo capacity, route speed, and risk profile.")
            return
        ship_info = SHIP_TYPES.get(ship.ship_type, {})
        self._fleet_detail.setPlainText(
            f"{ship.name}  ·  {ship_info.get('name', ship.ship_type)}\n"
            f"Cargo capacity: {ship.cargo_capacity} units\n"
            f"Route time modifier: ×{ship.days_mult:.2f}\n"
            f"Piracy risk: {ship.piracy_risk:.1%}  ·  Wreck risk: {ship.wreck_risk:.1%}\n"
            f"Profit modifier: ×{ship.profit_mult:.2f}\n"
            f"Upgrades: {', '.join(SHIP_UPGRADES[upgrade]['name'] for upgrade in ship.upgrades) or 'None'}"
        )

    def _on_select_captain(self, row: Dict[str, Any]) -> None:
        captain_id = row.get("captain_id") if row else None
        captain = next((candidate for candidate in self.game.captains if candidate.id == captain_id), None) if isinstance(captain_id, int) else None
        if captain is None:
            self._cap_detail.setPlainText("Select a captain to inspect speed bonus, risk reduction, and voyage wages.")
            return
        self._cap_detail.setPlainText(
            f"{captain.title} {captain.name}\n"
            f"Navigation {captain.navigation}  ·  Combat {captain.combat}  ·  Seamanship {captain.seamanship}  ·  Charisma {captain.charisma}\n"
            f"Voyage wage: {captain.wage_per_voyage:.0f}g  ·  Crew wage: {captain.crew_wage:.0f}g each\n"
            f"Time reduction: {captain.day_reduction:.0%}  ·  Piracy modifier: ×{captain.piracy_mult:.2f}\n"
            f"Wreck modifier: ×{captain.wreck_mult:.2f}  ·  Profit modifier: ×{captain.profit_mult:.2f}"
        )

    def _on_select_voyage(self, row: Dict[str, Any]) -> None:
        ship_name = row.get("ship_name") if row else None
        voyage = next((candidate for candidate in self.game.voyages if candidate.ship_name == ship_name), None) if isinstance(ship_name, str) else None
        if voyage is None:
            self._voyage_detail.setPlainText("Select a voyage to inspect cargo, destination, and current result details.")
            return
        cargo_desc = ", ".join(
            f"{qty}× {getattr(ALL_ITEMS.get(item_key), 'name', item_key)}"
            for item_key, qty in voyage.cargo.items()
        ) or "None"
        outcome = voyage.outcome_text or (f"+{voyage.outcome_gold:,.0f}g" if voyage.outcome_gold else "Pending")
        self._voyage_detail.setPlainText(
            f"{voyage.ship_name}  ·  {voyage.captain_name}\n"
            f"Destination: {VOYAGE_PORTS.get(voyage.destination_key, {}).get('name', voyage.destination_key)}\n"
            f"Status: {voyage.status.replace('_', ' ').title()}  ·  Days remaining: {voyage.days_remaining}\n"
            f"Cargo: {cargo_desc}\n"
            f"Cargo value: {voyage.cargo_cost:,.0f}g\n"
            f"Outcome: {outcome}"
        )

    def _on_select_port(self, row: Dict[str, Any]) -> None:
        port_key = row.get("port_key") if row else None
        port = VOYAGE_PORTS.get(port_key, {}) if isinstance(port_key, str) else None
        if not port:
            self._port_detail.setPlainText("Select a port to inspect its route-time modifier and strongest cargo categories.")
            return
        best_lines = "\n".join(
            f"{category.replace('_', ' ').title()}: ×{mult:.1f}"
            for category, mult in sorted(port.get("profit_mult", {}).items(), key=lambda item: -item[1])
        )
        self._port_detail.setPlainText(
            f"{port.get('name', port_key)}\n"
            f"Travel time modifier: ×{port.get('days_mod', 1.0):.2f}\n\n"
            f"Best cargo categories\n{best_lines}"
        )

    def _buy_ship(self) -> None:
        if LicenseType.VOYAGE not in self.game.licenses:
            self.msg.err("Voyage Charter required.")
            return
        ship_keys = list(SHIP_TYPES.keys())
        labels = [
            f"{data['name']}  —  Cargo {data['cargo']}  ·  Cost {data['cost']:,}g  ·  Piracy {data['piracy_risk']:.0%}  ·  Wreck {data['wreck_risk']:.0%}"
            for data in SHIP_TYPES.values()
        ]
        choice, ok = _popup_choose(self, "Buy Ship", "Select a ship type to purchase:", labels, confirm_text="Choose Ship")
        if not ok:
            return
        idx = labels.index(choice)
        ship_key = ship_keys[idx]
        data = SHIP_TYPES[ship_key]
        if self.game.inventory.gold < data["cost"]:
            self.msg.err(f"Need {data['cost']:,}g — you only have {self.game.inventory.gold:,.0f}g.")
            return
        default_name = f"{random.choice(_SHIP_NAME_PREFIXES)} {random.choice(_SHIP_NAME_SUFFIXES)}"
        raw_name = _popup_get_text(self, "Name Your Ship", f"Name your new {data['name']}:", default=default_name, confirm_text="Confirm Name")
        if raw_name is None:
            return
        ship_name = raw_name.strip() or default_name
        if not _popup_confirm(self, "Confirm Purchase", f"Purchase {ship_name} ({data['name']}) for {data['cost']:,}g?", confirm_text="Purchase Ship"):
            return
        self.game.inventory.gold -= data["cost"]
        self.game.ships.append(Ship(id=self.game.next_ship_id, ship_type=ship_key, name=ship_name))
        self.game.next_ship_id += 1
        self.msg.ok(f"{ship_name} purchased for {data['cost']:,}g.")
        self.app.refresh()

    def _upgrade_ship(self) -> None:
        docked = [ship for ship in self.game.ships if ship.status == "docked"]
        if not docked:
            self.msg.err("No docked ships to upgrade.")
            return
        labels = [f"{ship.name}  ({SHIP_TYPES[ship.ship_type]['name']})" for ship in docked]
        choice, ok = _popup_choose(self, "Upgrade Ship", "Select a ship to upgrade:", labels, confirm_text="Choose Ship")
        if not ok:
            return
        ship = docked[labels.index(choice)]
        available = [(key, data) for key, data in SHIP_UPGRADES.items() if key not in ship.upgrades]
        if not available:
            self.msg.err(f"{ship.name} already has all upgrades.")
            return
        upgrade_labels = [f"{data['name']}  —  {data['cost']}g  ·  {data['desc']}" for key, data in available]
        upgrade_choice, ok = _popup_choose(self, "Choose Upgrade", f"Select an upgrade for {ship.name}:", upgrade_labels, confirm_text="Choose Upgrade")
        if not ok:
            return
        upgrade_key, upgrade_data = available[upgrade_labels.index(upgrade_choice)]
        if self.game.inventory.gold < upgrade_data["cost"]:
            self.msg.err(f"Need {upgrade_data['cost']}g — not enough gold.")
            return
        if not _popup_confirm(self, "Confirm Upgrade", f"Install {upgrade_data['name']} on {ship.name} for {upgrade_data['cost']}g?", confirm_text="Install Upgrade"):
            return
        self.game.inventory.gold -= upgrade_data["cost"]
        ship.upgrades.append(upgrade_key)
        self.msg.ok(f"{upgrade_data['name']} installed on {ship.name}.")
        self.app.refresh()

    def _sell_ship(self) -> None:
        docked = [ship for ship in self.game.ships if ship.status == "docked"]
        if not docked:
            self.msg.err("No docked ships to sell.")
            return
        labels = [f"{ship.name}  ({SHIP_TYPES[ship.ship_type]['name']})" for ship in docked]
        choice, ok = _popup_choose(self, "Sell Ship", "Select a ship to sell:", labels, confirm_text="Choose Ship")
        if not ok:
            return
        ship = docked[labels.index(choice)]
        base_value = SHIP_TYPES[ship.ship_type]["cost"]
        upgrade_value = sum(SHIP_UPGRADES[upgrade]["cost"] for upgrade in ship.upgrades)
        sale_price = round((base_value + upgrade_value) * 0.55)
        if not _popup_confirm(
            self,
            "Confirm Sale",
            f"Sell {ship.name} for {sale_price:,}g?\nBase: {base_value:,}g  ·  Upgrades: {upgrade_value:,}g at 55% return.",
            confirm_text="Sell Ship",
            confirm_role="danger",
        ):
            return
        self.game.inventory.gold += sale_price
        self.game.ships.remove(ship)
        self.msg.ok(f"{ship.name} sold for {sale_price:,}g.")
        self.app.refresh()

    def _hire_captain(self) -> None:
        available = [captain for captain in self.game.captains if not captain.is_hired]
        if not available:
            self.msg.err("No captains available to hire.")
            return
        captain = CaptainHireDialog(self, available).choose()
        if captain is None:
            return
        captain.is_hired = True
        self.msg.ok(f"{captain.title} {captain.name} is now on your crew.")
        self.app.refresh()

    def _dismiss_captain(self) -> None:
        hired = [captain for captain in self.game.captains if captain.is_hired]
        if not hired:
            self.msg.err("No hired captains to dismiss.")
            return
        sailing_ids = {voyage.captain_id for voyage in self.game.voyages if voyage.status == "sailing"}
        labels = [f"{'[ON VOYAGE] ' if captain.id in sailing_ids else ''}{captain.title} {captain.name}" for captain in hired]
        choice, ok = _popup_choose(self, "Dismiss Captain", "Select a captain to dismiss:", labels, confirm_text="Choose Captain")
        if not ok:
            return
        captain = hired[labels.index(choice)]
        if captain.id in sailing_ids:
            self.msg.err("Cannot dismiss a captain who is currently on a voyage.")
            return
        if not _popup_confirm(self, "Dismiss Captain", f"Dismiss {captain.title} {captain.name}?", confirm_text="Dismiss Captain", confirm_role="danger"):
            return
        captain.is_hired = False
        self.msg.ok(f"{captain.title} {captain.name} dismissed.")
        self.app.refresh()

    def _restore_cargo(self, cargo: Dict[str, int]) -> None:
        for item_key, qty in cargo.items():
            self.game.inventory.items[item_key] = self.game.inventory.items.get(item_key, 0) + qty

    def _launch_voyage(self) -> None:
        g = self.game
        if LicenseType.VOYAGE not in g.licenses:
            self.msg.err("Voyage Charter required.")
            return
        docked = [ship for ship in g.ships if ship.status == "docked"]
        if not docked:
            self.msg.err("No docked ships available — buy a ship first.")
            return
        sailing_ids = {voyage.captain_id for voyage in g.voyages if voyage.status == "sailing"}
        free_captains = [captain for captain in g.captains if captain.is_hired and captain.id not in sailing_ids]
        if not free_captains:
            self.msg.err("No available captain — hire a captain first.")
            return
        ship_labels = [f"{ship.name}  ({SHIP_TYPES[ship.ship_type]['name']}, {ship.cargo_capacity} cargo)" for ship in docked]
        choice, ok = _popup_choose(self, "Launch Voyage", "Select a ship for this voyage:", ship_labels, confirm_text="Choose Ship")
        if not ok:
            return
        ship = docked[ship_labels.index(choice)]

        cap_labels = [
            f"{captain.title} {captain.name}  —  Nav {captain.navigation}  ·  Combat {captain.combat}  ·  Sea {captain.seamanship}  ·  Charm {captain.charisma}  ·  Wage {captain.wage_per_voyage:.0f}g"
            for captain in free_captains
        ]
        choice, ok = _popup_choose(self, "Launch Voyage", "Select a captain:", cap_labels, confirm_text="Choose Captain")
        if not ok:
            return
        captain = free_captains[cap_labels.index(choice)]

        port_keys = list(VOYAGE_PORTS.keys())
        port_labels = [
            f"{VOYAGE_PORTS[key]['name']}  —  Best ×{max(VOYAGE_PORTS[key]['profit_mult'].values(), default=1.0):.1f}"
            for key in port_keys
        ]
        choice, ok = _popup_choose(self, "Launch Voyage", "Select a destination port:", port_labels, confirm_text="Choose Port")
        if not ok:
            return
        dest_key = port_keys[port_labels.index(choice)]
        port = VOYAGE_PORTS[dest_key]

        inv_items = [(key, qty) for key, qty in g.inventory.items.items() if qty > 0]
        if not inv_items:
            self.msg.err("Your inventory is empty — nothing to load as cargo.")
            return

        cargo, cargo_cost, ok = VoyageCargoDialog(
            self,
            ship.cargo_capacity,
            inv_items,
            port['name'],
            port.get('profit_mult', {}),
        ).choose()
        if not ok:
            return
        if not cargo:
            self.msg.err("No cargo loaded — voyage cancelled.")
            return

        for item_key, qty in cargo.items():
            g.inventory.items[item_key] -= qty
            if g.inventory.items[item_key] <= 0:
                del g.inventory.items[item_key]

        low, high = SHIP_TYPES[ship.ship_type]["base_days"]
        days_total = max(5, round(random.randint(low, high) * port.get("days_mod", 1.0) * ship.days_mult * (1.0 - captain.day_reduction)))
        total_wage = captain.wage_per_voyage + captain.crew_wage * 3
        if g.inventory.gold < total_wage:
            self._restore_cargo(cargo)
            self.msg.err(f"Need {total_wage:.0f}g for wages — not enough gold.")
            return
        summary = (
            f"Ship: {ship.name} ({SHIP_TYPES[ship.ship_type]['name']})\n"
            f"Captain: {captain.title} {captain.name}\n"
            f"Destination: {port['name']}\n"
            f"Cargo: {sum(cargo.values())} units (~{cargo_cost:,.0f}g value)\n"
            f"Voyage time: ~{days_total} days\n"
            f"Wages: {total_wage:.0f}g\n"
            f"Piracy risk: {ship.piracy_risk * captain.piracy_mult:.1%}  ·  Wreck risk: {ship.wreck_risk * captain.wreck_mult:.1%}"
        )
        if not _popup_confirm(self, "Confirm Voyage", summary, confirm_text="Launch Voyage"):
            self._restore_cargo(cargo)
            return
        g.inventory.gold -= total_wage
        voyage = Voyage(
            id=g.next_voyage_id,
            ship_id=ship.id,
            ship_name=ship.name,
            captain_id=captain.id,
            captain_name=f"{captain.title} {captain.name}",
            destination_key=dest_key,
            cargo=cargo,
            cargo_cost=cargo_cost,
            days_total=days_total,
            days_remaining=days_total,
            departure_day=g._absolute_day(),
        )
        g.next_voyage_id += 1
        g.voyages.append(voyage)
        ship.status = "sailing"
        ship.voyage_id = voyage.id
        self.msg.ok(f"{ship.name} has set sail for {port['name']}. Expected back in ~{days_total} days.")
        self.app.refresh()

    def _collect_results(self) -> None:
        done = [voyage for voyage in self.game.voyages if voyage.status in ("arrived", "lost_piracy", "lost_wreck")]
        if not done:
            self.msg.err("No completed voyages to report on.")
            return
        lines: List[str] = []
        for voyage in done:
            port_name = VOYAGE_PORTS.get(voyage.destination_key, {}).get("name", "?")
            if voyage.status == "arrived":
                lines.append(f"{voyage.ship_name}: +{voyage.outcome_gold:,.0f}g from {port_name}")
            else:
                lines.append(voyage.outcome_text)
        _popup_info(self, "Voyage Results", "\n".join(lines))
        self.app.refresh()

    def _clear_completed(self) -> None:
        before = len(self.game.voyages)
        self.game.voyages = [voyage for voyage in self.game.voyages if voyage.status == "sailing"]
        cleared = before - len(self.game.voyages)
        if cleared:
            self.msg.ok(f"Cleared {cleared} completed voyage record(s).")
        else:
            self.msg.err("No completed voyages to clear.")
        self.app.refresh()


class SocialScreen(Screen):
    """Online social hub: leaderboard, friends, and guilds."""

    _LB_COLS = [
        ("rank", "#", 64, Qt.AlignmentFlag.AlignCenter),
        ("merchant", "Merchant", 220),
        ("title", "Title", 180),
        ("guild", "Guild", 170),
        ("net_worth", "Net Worth", 140, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("area", "Area", 120),
    ]
    _PENDING_COLS = [
        ("merchant", "Merchant", 280),
        ("net_worth", "Net Worth", 140, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ]
    _FRIEND_COLS = [
        ("status", "Status", 84),
        ("merchant", "Merchant", 260),
        ("net_worth", "Net Worth", 140, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        ("seen", "Last Seen", 160),
    ]
    _GUILD_COLS = [
        ("name", "Guild", 220),
        ("members", "Members", 90, Qt.AlignmentFlag.AlignCenter),
        ("focus", "Focus", 120),
        ("description", "Description", 400),
    ]
    _INVITE_COLS = [
        ("guild", "Guild", 220),
        ("from", "Invited By", 220),
        ("sent", "Sent", 140),
    ]

    def build(self) -> None:
        self._lb_rows: List[Dict[str, Any]] = []
        self._pending_rows: List[Dict[str, Any]] = []
        self._friends_rows: List[Dict[str, Any]] = []
        self._guild_rows: List[Dict[str, Any]] = []
        self._guild_invite_rows: List[Dict[str, Any]] = []
        self._my_guild: Optional[Dict[str, Any]] = None
        self._my_rank: int = 0
        self._lb_last_fetch: float = 0.0

        self._lb_refresh_timer = QTimer(self)
        self._lb_refresh_timer.setInterval(60_000)
        self._lb_refresh_timer.timeout.connect(lambda: self._load_leaderboard(force=True))

        root = QVBoxLayout(self)
        root.setContentsMargins(UIScale.px(14), UIScale.px(12), UIScale.px(14), UIScale.px(12))
        root.setSpacing(UIScale.px(10))

        root.addWidget(self.section_label("Social Hub"))

        self._tabs = QTabWidget(self)
        self._tabs.setFont(Fonts.mixed_small)
        self._tabs.currentChanged.connect(lambda _index: self._load_active_tab(force=False))
        root.addWidget(self._tabs, 1)

        self._build_leaderboard_tab()
        self._build_friends_tab()
        self._build_guilds_tab()

        foot = QHBoxLayout()
        foot.addWidget(self.back_button())
        foot.addStretch()
        root.addLayout(foot)

    def on_show(self) -> None:
        self._lb_refresh_timer.start()
        self._load_active_tab(force=True)
        self.app._push_online_presence()

    def on_hide(self) -> None:
        self._lb_refresh_timer.stop()

    def refresh(self) -> None:
        self._render_lb_footer()
        self._render_guild_summary()

    def _build_leaderboard_tab(self) -> None:
        tab = QWidget(self)
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(UIScale.px(8))

        hdr = QHBoxLayout()
        title = QLabel(f"{Sym.PROGRESS}  Global leaderboard ranked by net worth", tab)
        title.setFont(Fonts.mixed_bold)
        title.setStyleSheet(f"color:{P.gold}; background:transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        self._lb_status_lbl = QLabel("", tab)
        self._lb_status_lbl.setFont(Fonts.mono_small)
        self._lb_status_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        hdr.addWidget(self._lb_status_lbl)
        refresh_btn = MtButton(f"{Sym.SYNC}  Refresh", tab, role="secondary")
        refresh_btn.clicked.connect(lambda: self._load_leaderboard(force=True))
        hdr.addWidget(refresh_btn)
        lay.addLayout(hdr)

        self._lb_table = DataTable(tab, self._LB_COLS, row_height=26)
        lay.addWidget(self._lb_table, 1)

        self._lb_footer_lbl = QLabel("", tab)
        self._lb_footer_lbl.setWordWrap(True)
        self._lb_footer_lbl.setFont(Fonts.mixed_small_bold)
        self._lb_footer_lbl.setStyleSheet(
            f"color:{P.gold}; background:{P.bg_panel}; border:1px solid {P.border}; padding:{UIScale.px(8)}px;"
        )
        lay.addWidget(self._lb_footer_lbl)

        self._tabs.addTab(tab, f"{Sym.PROGRESS}  Leaderboard")

    def _build_friends_tab(self) -> None:
        tab = QWidget(self)
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(UIScale.px(8))

        hdr = QHBoxLayout()
        title = QLabel(f"{Sym.SOCIAL}  Friends and pending requests", tab)
        title.setFont(Fonts.mixed_bold)
        title.setStyleSheet(f"color:{P.gold}; background:transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        self._friends_status_lbl = QLabel("", tab)
        self._friends_status_lbl.setFont(Fonts.mono_small)
        self._friends_status_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        hdr.addWidget(self._friends_status_lbl)
        friends_refresh_btn = MtButton(f"{Sym.SYNC}  Refresh", tab, role="secondary")
        friends_refresh_btn.clicked.connect(lambda: self._load_friends(force=True))
        hdr.addWidget(friends_refresh_btn)
        lay.addLayout(hdr)

        search_row = QHBoxLayout()
        self._friend_query = QLineEdit(tab)
        self._friend_query.setPlaceholderText("Search by Name #1234 or UUID")
        self._friend_query.setFont(Fonts.mixed)
        self._friend_query.returnPressed.connect(self._send_friend_request)
        search_row.addWidget(self._friend_query, 1)
        add_btn = MtButton(f"{Sym.INBOX}  Send Request", tab)
        add_btn.clicked.connect(self._send_friend_request)
        search_row.addWidget(add_btn)
        lay.addLayout(search_row)

        pending_frame = QFrame(tab)
        pending_frame.setObjectName("dashPanel")
        pending_lay = QVBoxLayout(pending_frame)
        pending_lay.setContentsMargins(UIScale.px(10), UIScale.px(10), UIScale.px(10), UIScale.px(10))
        pending_lay.setSpacing(UIScale.px(8))
        pending_hdr = QLabel("Pending Requests", pending_frame)
        pending_hdr.setFont(Fonts.mixed_bold)
        pending_hdr.setStyleSheet(f"color:{P.amber}; background:transparent;")
        pending_lay.addWidget(pending_hdr)
        self._pending_table = DataTable(pending_frame, self._PENDING_COLS, row_height=24)
        pending_lay.addWidget(self._pending_table)
        pending_btns = QHBoxLayout()
        accept_btn = MtButton(f"{Sym.YES}  Accept", pending_frame, role="secondary")
        accept_btn.clicked.connect(lambda: self._respond_to_request(True))
        pending_btns.addWidget(accept_btn)
        decline_btn = MtButton(f"{Sym.NO}  Decline", pending_frame, role="danger")
        decline_btn.clicked.connect(lambda: self._respond_to_request(False))
        pending_btns.addWidget(decline_btn)
        pending_btns.addStretch()
        pending_lay.addLayout(pending_btns)
        lay.addWidget(pending_frame)

        friends_frame = QFrame(tab)
        friends_frame.setObjectName("dashPanel")
        friends_lay = QVBoxLayout(friends_frame)
        friends_lay.setContentsMargins(UIScale.px(10), UIScale.px(10), UIScale.px(10), UIScale.px(10))
        friends_lay.setSpacing(UIScale.px(8))
        friends_hdr = QLabel("Your Friends", friends_frame)
        friends_hdr.setFont(Fonts.mixed_bold)
        friends_hdr.setStyleSheet(f"color:{P.gold}; background:transparent;")
        friends_lay.addWidget(friends_hdr)
        self._friends_table = DataTable(friends_frame, self._FRIEND_COLS, row_height=24)
        friends_lay.addWidget(self._friends_table, 1)
        friends_btns = QHBoxLayout()
        remove_btn = MtButton(f"{Sym.NO}  Remove Friend", friends_frame, role="danger")
        remove_btn.clicked.connect(self._remove_friend)
        friends_btns.addWidget(remove_btn)
        friends_btns.addStretch()
        friends_lay.addLayout(friends_btns)
        lay.addWidget(friends_frame, 1)

        self._tabs.addTab(tab, f"{Sym.SOCIAL}  Friends")

    def _build_guilds_tab(self) -> None:
        tab = QWidget(self)
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(UIScale.px(8))

        hdr = QHBoxLayout()
        title = QLabel(f"{Sym.INFLUENCE}  Guild roster and discovery", tab)
        title.setFont(Fonts.mixed_bold)
        title.setStyleSheet(f"color:{P.gold}; background:transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        self._guilds_status_lbl = QLabel("", tab)
        self._guilds_status_lbl.setFont(Fonts.mono_small)
        self._guilds_status_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        hdr.addWidget(self._guilds_status_lbl)
        guild_refresh_btn = MtButton(f"{Sym.SYNC}  Refresh", tab, role="secondary")
        guild_refresh_btn.clicked.connect(lambda: self._load_guilds(force=True))
        hdr.addWidget(guild_refresh_btn)
        lay.addLayout(hdr)

        self._guild_summary = QFrame(tab)
        self._guild_summary.setObjectName("dashPanel")
        sum_lay = QVBoxLayout(self._guild_summary)
        sum_lay.setContentsMargins(UIScale.px(12), UIScale.px(10), UIScale.px(12), UIScale.px(10))
        sum_lay.setSpacing(UIScale.px(6))
        self._guild_name_lbl = QLabel("No guild", self._guild_summary)
        self._guild_name_lbl.setFont(Fonts.title)
        self._guild_name_lbl.setStyleSheet(f"color:{P.cream}; background:transparent;")
        sum_lay.addWidget(self._guild_name_lbl)
        self._guild_desc_lbl = QLabel("Sign in to browse or found a guild.", self._guild_summary)
        self._guild_desc_lbl.setWordWrap(True)
        self._guild_desc_lbl.setFont(Fonts.mixed_small)
        self._guild_desc_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        sum_lay.addWidget(self._guild_desc_lbl)
        self._guild_meta_lbl = QLabel("", self._guild_summary)
        self._guild_meta_lbl.setFont(Fonts.mono_small)
        self._guild_meta_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        sum_lay.addWidget(self._guild_meta_lbl)
        sum_btns = QHBoxLayout()
        create_btn = MtButton(f"{Sym.YES}  Found Guild", self._guild_summary)
        create_btn.clicked.connect(self._create_guild)
        sum_btns.addWidget(create_btn)
        self._manage_guild_btn = MtButton(f"{Sym.SETTINGS}  Manage Guild", self._guild_summary, role="secondary")
        self._manage_guild_btn.clicked.connect(self._open_guild_management)
        sum_btns.addWidget(self._manage_guild_btn)
        leave_btn = MtButton(f"{Sym.NO}  Leave Guild", self._guild_summary, role="danger")
        leave_btn.clicked.connect(self._leave_guild)
        sum_btns.addWidget(leave_btn)
        sum_btns.addStretch()
        self._join_btn = MtButton(f"{Sym.INFO}  Join Selected", self._guild_summary, role="secondary")
        self._join_btn.clicked.connect(self._join_selected_guild)
        sum_btns.addWidget(self._join_btn)
        sum_lay.addLayout(sum_btns)
        lay.addWidget(self._guild_summary)

        self._guilds_table = DataTable(tab, self._GUILD_COLS, row_height=24)
        lay.addWidget(self._guilds_table, 1)

        invite_frame = QFrame(tab)
        invite_frame.setObjectName("dashPanel")
        invite_lay = QVBoxLayout(invite_frame)
        invite_lay.setContentsMargins(UIScale.px(10), UIScale.px(10), UIScale.px(10), UIScale.px(10))
        invite_lay.setSpacing(UIScale.px(8))
        invite_hdr = QLabel("Pending Invites", invite_frame)
        invite_hdr.setFont(Fonts.mixed_bold)
        invite_hdr.setStyleSheet(f"color:{P.amber}; background:transparent;")
        invite_lay.addWidget(invite_hdr)
        self._guild_invites_table = DataTable(invite_frame, self._INVITE_COLS, row_height=24)
        invite_lay.addWidget(self._guild_invites_table)
        invite_btns = QHBoxLayout()
        accept_invite_btn = MtButton(f"{Sym.YES}  Accept", invite_frame, role="secondary")
        accept_invite_btn.clicked.connect(lambda: self._respond_to_selected_guild_invite(True))
        invite_btns.addWidget(accept_invite_btn)
        decline_invite_btn = MtButton(f"{Sym.NO}  Decline", invite_frame, role="danger")
        decline_invite_btn.clicked.connect(lambda: self._respond_to_selected_guild_invite(False))
        invite_btns.addWidget(decline_invite_btn)
        invite_btns.addStretch()
        invite_lay.addLayout(invite_btns)
        lay.addWidget(invite_frame)

        self._tabs.addTab(tab, f"{Sym.INFLUENCE}  Guilds")

    def _active_tab_key(self) -> str:
        index = self._tabs.currentIndex()
        if index == 0:
            return "leaderboard"
        if index == 1:
            return "friends"
        return "guilds"

    def _load_active_tab(self, force: bool = False) -> None:
        key = self._active_tab_key()
        if key == "leaderboard":
            self._load_leaderboard(force=force)
        elif key == "friends":
            self._load_friends(force=force)
        else:
            self._load_guilds(force=force)

    def _load_leaderboard(self, force: bool = False) -> None:
        if not (self.app.online and self.app.online.is_online):
            self._lb_status_lbl.setText("Sign in to view the global board")
            self._lb_table.load([])
            self._lb_footer_lbl.setText("Sign in to submit a score and see your rank.")
            return
        if not force and self._lb_rows and (time.time() - self._lb_last_fetch) < 30.0:
            return
        self._lb_status_lbl.setText("Loading…")
        self.app._push_online_presence()
        self.app._push_leaderboard(done_callback=self._fetch_leaderboard)

    def _fetch_leaderboard(self) -> None:
        if not (self.app.online and self.app.online.is_online):
            return
        def _top_cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._apply_leaderboard(r))
        def _rank_cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._apply_rank(r))
        self.app.online.leaderboard.fetch_top_scores(limit=100, callback=_top_cb)
        self.app.online.leaderboard.fetch_my_rank(callback=_rank_cb)

    def _apply_leaderboard(self, res: Any) -> None:
        if not getattr(res, "success", False):
            self._lb_status_lbl.setText(getattr(res, "error", "Leaderboard unavailable"))
            return
        raw_rows = res.data if isinstance(res.data, list) else []
        self._lb_last_fetch = time.time()
        self._lb_status_lbl.setText(f"Top {len(raw_rows)} merchants")
        my_uid = self.app.online.auth.user_id if self.app.online else ""
        rows: List[Dict[str, Any]] = []
        for idx, row in enumerate(raw_rows, start=1):
            title_raw = str(row.get("title", "") or "")
            title_def = TITLES_BY_ID.get(title_raw)
            title_text = title_def["name"] if title_def else (title_raw or "—")
            is_me = row.get("user_id", "") == my_uid
            tag = "gold" if idx <= 3 else ("cyan" if is_me else "dim")
            rows.append({
                "rank": ("🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"#{idx}"),
                "merchant": row.get("player_name") or row.get("username") or "Unknown",
                "title": title_text,
                "guild": self._guild_cell_text(row),
                "net_worth": f"{float(row.get('net_worth', 0) or 0):,.0f}g",
                "area": row.get("area") or "—",
                "_tag": tag,
            })
        self._lb_rows = rows
        self._lb_table.load(rows)
        self._render_lb_footer()

    def _apply_rank(self, res: Any) -> None:
        self._my_rank = int(res.data.get("rank", 0) or 0) if (getattr(res, "success", False) and isinstance(res.data, dict)) else 0
        self._render_lb_footer()

    def _render_lb_footer(self) -> None:
        g = self.game
        if self._my_rank <= 0:
            self._lb_footer_lbl.setText("Submit a score to appear on the leaderboard.")
            return
        title_def = TITLES_BY_ID.get(getattr(g, "active_title", "") or "")
        title_text = f"  •  {title_def['name']}" if title_def else ""
        guild_text = f"  •  {self.app._cached_guild_name}" if getattr(self.app, "_cached_guild_name", "") else ""
        role_text = f" ({self.app._cached_guild_role})" if getattr(self.app, "_cached_guild_role", "") else ""
        self._lb_footer_lbl.setText(
            f"Your rank: #{self._my_rank:,}  •  {g.player_name or 'Merchant'}{title_text}{guild_text}{role_text}  •  {g._net_worth():,.0f}g net worth"
        )

    def _load_friends(self, force: bool = False) -> None:
        del force
        if not (self.app.online and self.app.online.is_online):
            self._friends_status_lbl.setText("Sign in to manage friends")
            self._pending_table.load([])
            self._friends_table.load([])
            return
        self._friends_status_lbl.setText("Loading…")
        def _pending_cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._apply_pending(r))
        def _friends_cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._apply_friends(r))
        self.app.online.friends.list_pending_requests(callback=_pending_cb)
        self.app.online.friends.list_friends_with_profiles(callback=_friends_cb)

    def _apply_pending(self, res: Any) -> None:
        raw = res.data if (getattr(res, "success", False) and isinstance(res.data, list)) else []
        rows: List[Dict[str, Any]] = []
        for item in raw:
            profile = item.get("profiles") or {}
            rows.append({
                "merchant": self._player_label(profile),
                "net_worth": f"{float(profile.get('last_networth', 0) or 0):,.0f}g",
                "requester_id": item.get("requester_id", ""),
                "_tag": "yellow",
            })
        self._pending_rows = rows
        self._pending_table.load(rows)
        self._update_friend_status()

    def _apply_friends(self, res: Any) -> None:
        raw = res.data if (getattr(res, "success", False) and isinstance(res.data, list)) else []
        rows: List[Dict[str, Any]] = []
        for item in raw:
            profile = item.get("profile") or {}
            status_text, last_seen_text, tag = self._friend_presence(profile.get("last_seen", ""))
            net_worth = float(profile.get("last_networth", 0) or 0)
            rows.append({
                "status": status_text,
                "merchant": self._player_label(profile),
                "net_worth": f"{net_worth:,.0f}g" if net_worth > 0 else "—",
                "seen": last_seen_text,
                "friend_id": item.get("friend_id", ""),
                "_tag": tag,
            })
        self._friends_rows = rows
        self._friends_table.load(rows)
        self._update_friend_status()

    def _update_friend_status(self) -> None:
        self._friends_status_lbl.setText(f"{len(self._friends_rows)} friends  •  {len(self._pending_rows)} pending")

    def _send_friend_request(self) -> None:
        query = self._friend_query.text().strip()
        if not query:
            self.msg.warn("Enter a merchant name or UUID to search.")
            return
        if not (self.app.online and self.app.online.is_online):
            self.msg.warn("Sign in to send friend requests.")
            return
        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res, q=query: self._handle_friend_search(r, q))
        self.app.online.profile.search_players(query, callback=_cb)

    def _handle_friend_search(self, res: Any, query: str) -> None:
        if not getattr(res, "success", False):
            self.msg.err(getattr(res, "error", "Search failed."))
            return
        players = res.data if isinstance(res.data, list) else []
        if not players:
            self.msg.warn(f"No merchant found matching {query}.")
            return
        player = players[0]
        if len(players) > 1:
            label_map: Dict[str, Dict[str, Any]] = {}
            items: List[str] = []
            for item in players:
                label = f"{self._player_label(item)}  •  {float(item.get('last_networth', 0) or 0):,.0f}g NW"
                if label in label_map:
                    suffix = str(item.get("id", ""))[:8]
                    label = f"{label}  •  {suffix}"
                label_map[label] = item
                items.append(label)
            choice, ok = ChoiceListDialog(
                self,
                "Choose Merchant",
                "Multiple merchants matched your search. Choose one.",
                items,
                confirm_text="Send Request",
            ).choose()
            if not ok:
                return
            player = label_map[choice]
        player_id = str(player.get("id") or player.get("user_id") or "")
        if not player_id:
            self.msg.err("Could not resolve that merchant's ID.")
            return
        if player_id == (self.app.online.auth.user_id if self.app.online else ""):
            self.msg.warn("That is your own account.")
            return
        label = self._player_label(player)
        def _send_cb(send_res: Any) -> None:
            _queue_ui(self, lambda r=send_res, name=label: self._after_send_request(r, name))
        self.app.online.friends.send_request(player_id, callback=_send_cb)

    def _after_send_request(self, res: Any, name: str) -> None:
        if getattr(res, "success", False):
            self.msg.ok(f"Friend request sent to {name}.")
            self._friend_query.clear()
            return
        error = str(getattr(res, "error", "Failed to send request.") or "Failed to send request.")
        if "duplicate" in error.lower() or "unique" in error.lower():
            error = f"A pending request with {name} already exists."
        self.msg.err(error)

    def _respond_to_request(self, accept: bool) -> None:
        row = self._pending_table.selected()
        if not row:
            self.msg.warn("Select a pending request first.")
            return
        requester_id = str(row.get("requester_id", "") or "")
        if not requester_id:
            self.msg.err("That request is missing its requester ID.")
            return
        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res, accepted=accept: self._after_respond(r, row, accepted))
        self.app.online.friends.respond_to_request(requester_id, accept, callback=_cb)

    def _after_respond(self, res: Any, row: Dict[str, Any], accept: bool) -> None:
        if getattr(res, "success", False):
            self.msg.ok(f"Accepted {row.get('merchant', 'request')}." if accept else "Request declined.")
            self._load_friends(force=True)
            return
        self.msg.err(getattr(res, "error", "Failed to respond to request."))

    def _remove_friend(self) -> None:
        row = self._friends_table.selected()
        if not row:
            self.msg.warn("Select a friend first.")
            return
        friend_id = str(row.get("friend_id", "") or "")
        name = str(row.get("merchant", "that friend") or "that friend")
        if not friend_id:
            self.msg.err("That friend entry is missing its player ID.")
            return
        if not ConfirmDialog(
            self,
            "Remove Friend",
            f"Remove {name} from your friends list?",
            confirm_text="Remove",
            confirm_role="danger",
        ).ask():
            return
        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res, friend_name=name: self._after_remove_friend(r, friend_name))
        self.app.online.friends.remove_friend(friend_id, callback=_cb)

    def _after_remove_friend(self, res: Any, name: str) -> None:
        if getattr(res, "success", False):
            self.msg.ok(f"Removed {name} from your friends list.")
            self._load_friends(force=True)
            return
        self.msg.err(getattr(res, "error", "Failed to remove friend."))

    def _load_guilds(self, force: bool = False) -> None:
        del force
        if not (self.app.online and self.app.online.is_online):
            self._guilds_status_lbl.setText("Sign in to access guilds")
            self._guild_rows = []
            self._guild_invite_rows = []
            self._guilds_table.load([])
            self._guild_invites_table.load([])
            self._my_guild = None
            self.app._cached_guild_id = ""
            self.app._cached_guild_name = ""
            self.app._cached_guild_role = ""
            self._render_guild_summary()
            return
        self._guilds_status_lbl.setText("Loading…")
        def _mine_cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._apply_my_guild(r))
        def _list_cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._apply_guild_list(r))
        def _invite_cb(res: Any) -> None:
            _queue_ui(self, lambda r=res: self._apply_guild_invites(r))
        self.app.online.guilds.get_my_guild(callback=_mine_cb)
        self.app.online.guilds.list_guilds(limit=25, callback=_list_cb)
        self.app.online.guilds.list_my_invites(callback=_invite_cb)

    def _apply_my_guild(self, res: Any) -> None:
        self._my_guild = res.data if (getattr(res, "success", False) and isinstance(res.data, dict)) else None
        if self._my_guild:
            self.app._cached_guild_id = str(self._my_guild.get("id", "") or "")
            self.app._cached_guild_name = str(self._my_guild.get("name", "") or "")
            self.app._cached_guild_role = str(self._my_guild.get("my_role_label", self._my_guild.get("my_role", "")) or "")
        else:
            self.app._cached_guild_id = ""
            self.app._cached_guild_name = ""
            self.app._cached_guild_role = ""
        self._render_guild_summary()

    def _apply_guild_list(self, res: Any) -> None:
        raw = res.data if (getattr(res, "success", False) and isinstance(res.data, list)) else []
        my_id = self._my_guild.get("id") if self._my_guild else ""
        rows: List[Dict[str, Any]] = []
        for guild in raw:
            desc = str(guild.get("description", "") or "")
            policy = guild.get("guild_policies")
            if isinstance(policy, list):
                policy = policy[0] if policy else {}
            if not isinstance(policy, dict):
                policy = {}
            focus = str(policy.get("event_focus", "balanced") or "balanced").replace("_", " ").title()
            recruitment = str(policy.get("recruitment_mode", "open") or "open").replace("_", " ").title()
            rows.append({
                "name": guild.get("name") or "Unknown",
                "members": str(int(guild.get("member_count", 0) or 0)),
                "focus": focus,
                "description": f"[{recruitment}] {desc if len(desc) <= 70 else desc[:69] + '…'}",
                "guild_id": guild.get("id", ""),
                "recruitment_mode": str(policy.get("recruitment_mode", "open") or "open"),
                "minimum_reputation": int(policy.get("minimum_reputation", 0) or 0),
                "minimum_net_worth": float(policy.get("minimum_net_worth", 0) or 0.0),
                "_tag": "cyan" if guild.get("id", "") == my_id else "dim",
            })
        self._guild_rows = rows
        self._guilds_table.load(rows)
        self._guilds_status_lbl.setText(f"{len(rows)} guilds available")
        self._render_guild_summary()

    def _apply_guild_invites(self, res: Any) -> None:
        raw = res.data if (getattr(res, "success", False) and isinstance(res.data, list)) else []
        rows: List[Dict[str, Any]] = []
        for item in raw:
            sent = str(item.get("created_at", "") or "")
            if "T" in sent:
                sent = sent.split("T", 1)[0]
            guild_info = item.get("guilds") or {}
            rows.append({
                "guild": str(guild_info.get("name", "Unknown Guild") if isinstance(guild_info, dict) else "Unknown Guild"),
                "from": str(item.get("from_user", "Unknown") or "Unknown"),
                "sent": sent or "—",
                "invite_id": str(item.get("id", "") or ""),
                "guild_id": str(item.get("guild_id", "") or ""),
                "_tag": "yellow",
            })
        self._guild_invite_rows = rows
        self._guild_invites_table.load(rows)

    def _render_guild_summary(self) -> None:
        if self._my_guild:
            name = self._my_guild.get("name", "Unknown Guild")
            desc = self._my_guild.get("description") or "No description."
            count = int(self._my_guild.get("member_count", 0) or 0)
            role_label = str(self._my_guild.get("my_role_label", self._my_guild.get("my_role", "")) or "")
            policy = self._my_guild.get("policy") if isinstance(self._my_guild.get("policy"), dict) else {}
            focus = str(policy.get("event_focus", "balanced") or "balanced").replace("_", " ").title()
            self._guild_name_lbl.setText(str(name))
            self._guild_desc_lbl.setText(str(desc))
            role_text = f"  •  {role_label}" if role_label else ""
            self._guild_meta_lbl.setText(f"{count} member{'s' if count != 1 else ''}{role_text}  •  {focus}")
            self._join_btn.setEnabled(False)
            self._manage_guild_btn.setEnabled(True)
        else:
            self._guild_name_lbl.setText("No guild membership")
            self._guild_desc_lbl.setText("Found your own guild or join one from the directory below.")
            self._guild_meta_lbl.setText("")
            self._join_btn.setEnabled(True)
            self._manage_guild_btn.setEnabled(False)

    def _open_guild_management(self) -> None:
        if not self._my_guild:
            self.msg.warn("Join or found a guild first.")
            return
        guild_id = str(self._my_guild.get("id", "") or "")
        if not guild_id:
            self.msg.err("Your guild is missing its ID.")
            return
        GuildManagementDialog(self.app, guild_id, self, on_change=lambda: self._load_guilds(force=True)).exec()

    def _create_guild(self) -> None:
        if not (self.app.online and self.app.online.is_online):
            self.msg.warn("Sign in to create a guild.")
            return
        if self._my_guild:
            self.msg.warn("Leave your current guild before founding a new one.")
            return
        name = TextPromptDialog(
            self,
            "Found a Guild",
            "Choose a guild name.",
            placeholder="Guild name",
            confirm_text="Continue",
        ).get_value()
        if name is None:
            return
        name = name.strip()
        if len(name) < 3:
            self.msg.warn("Guild name must be at least 3 characters.")
            return
        desc = TextPromptDialog(
            self,
            "Guild Description",
            "Add a short description for your guild.",
            placeholder="Optional description",
            confirm_text="Found Guild",
        ).get_value()
        description = (desc or "").strip()
        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res, guild_name=name: self._after_create_guild(r, guild_name))
        self.app.online.guilds.create_guild(name, description, callback=_cb)

    def _after_create_guild(self, res: Any, name: str) -> None:
        if getattr(res, "success", False):
            self._cache_guild_from_result(res.data)
            self.msg.ok(f"Founded {name}.")
            self.app._push_online_presence()
            self.app._push_leaderboard()
            self._load_guilds(force=True)
            return
        self.msg.err(getattr(res, "error", "Failed to create guild."))

    def _join_selected_guild(self) -> None:
        if self._my_guild:
            self.msg.warn("Leave your current guild before joining another.")
            return
        row = self._guilds_table.selected()
        if not row:
            self.msg.warn("Select a guild to join.")
            return
        guild_id = str(row.get("guild_id", "") or "")
        name = str(row.get("name", "that guild") or "that guild")
        if not guild_id:
            self.msg.err("That guild entry is missing its ID.")
            return
        recruitment_mode = str(row.get("recruitment_mode", "open") or "open").lower()
        if recruitment_mode != "open":
            self.msg.warn("That guild is not open for direct joining right now.")
            return
        min_rep = int(row.get("minimum_reputation", 0) or 0)
        if int(getattr(self.game, "reputation", 0) or 0) < min_rep:
            self.msg.warn(f"You need at least {min_rep} reputation to join {name}.")
            return
        min_net_worth = float(row.get("minimum_net_worth", 0) or 0.0)
        if float(self.game._net_worth() or 0.0) < min_net_worth:
            self.msg.warn(f"You need at least {min_net_worth:,.0f}g net worth to join {name}.")
            return
        if not ConfirmDialog(
            self,
            "Join Guild",
            f"Join {name}?",
            confirm_text="Join Guild",
        ).ask():
            return
        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res, guild_name=name: self._after_join_guild(r, guild_name))
        self.app.online.guilds.join_guild(guild_id, callback=_cb)

    def _after_join_guild(self, res: Any, name: str) -> None:
        if getattr(res, "success", False):
            self._cache_guild_from_result(res.data)
            self.msg.ok(f"Joined {name}.")
            self.app._push_online_presence()
            self.app._push_leaderboard()
            self._load_guilds(force=True)
            return
        self.msg.err(getattr(res, "error", "Failed to join guild."))

    def _leave_guild(self) -> None:
        if not self._my_guild:
            self.msg.warn("You are not currently in a guild.")
            return
        guild_id = str(self._my_guild.get("id", "") or "")
        name = str(self._my_guild.get("name", "your guild") or "your guild")
        if not ConfirmDialog(
            self,
            "Leave Guild",
            f"Leave {name}?",
            confirm_text="Leave Guild",
            confirm_role="danger",
        ).ask():
            return
        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res, guild_name=name: self._after_leave_guild(r, guild_name))
        self.app.online.guilds.leave_guild(guild_id, callback=_cb)

    def _after_leave_guild(self, res: Any, name: str) -> None:
        if getattr(res, "success", False):
            self.msg.ok(f"Left {name}.")
            self.app._cached_guild_id = ""
            self.app._cached_guild_name = ""
            self.app._cached_guild_role = ""
            self.app._push_online_presence()
            self.app._push_leaderboard()
            self._load_guilds(force=True)
            return
        self.msg.err(getattr(res, "error", "Failed to leave guild."))

    def _respond_to_selected_guild_invite(self, accept: bool) -> None:
        row = self._guild_invites_table.selected()
        if not row:
            self.msg.warn("Select a guild invite first.")
            return
        invite_id = str(row.get("invite_id", "") or "")
        if not invite_id:
            self.msg.err("That invite is missing its ID.")
            return

        def _cb(res: Any) -> None:
            _queue_ui(self, lambda r=res, accepted=accept, guild_name=str(row.get('guild', 'guild') or 'guild'): self._after_respond_guild_invite(r, accepted, guild_name))

        self.app.online.guilds.respond_to_invite(invite_id, accept, callback=_cb)

    def _after_respond_guild_invite(self, res: Any, accept: bool, guild_name: str) -> None:
        if getattr(res, "success", False):
            self.msg.ok(f"Joined {guild_name}." if accept else f"Declined invite from {guild_name}.")
            self._load_guilds(force=True)
            return
        self.msg.err(getattr(res, "error", "Failed to respond to guild invite."))

    def _cache_guild_from_result(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        guild = payload.get("guild") if isinstance(payload.get("guild"), dict) else payload
        membership = payload.get("membership") if isinstance(payload.get("membership"), dict) else {}
        if not isinstance(guild, dict):
            return
        self.app._cached_guild_id = str(guild.get("id", guild.get("guild_id", "")) or "")
        self.app._cached_guild_name = str(guild.get("name", guild.get("guild_name", "")) or "")
        role_label = str(
            membership.get("role_label", "")
            or payload.get("my_role_label", "")
            or guild.get("my_role_label", "")
            or payload.get("my_role", "")
            or guild.get("my_role", "")
            or ""
        )
        self.app._cached_guild_role = role_label

    @staticmethod
    def _guild_cell_text(row: Dict[str, Any]) -> str:
        guild_name = str(row.get("guild_name", "") or "")
        guild_role = str(row.get("guild_role", "") or "")
        if not guild_name:
            return "—"
        return f"{guild_name} • {guild_role}" if guild_role else guild_name

    @staticmethod
    def _player_label(profile: Dict[str, Any]) -> str:
        name = str(profile.get("username", "Unknown") or "Unknown")
        disc = profile.get("discriminator", 0)
        if isinstance(disc, int) and disc:
            return f"{name} #{disc:04d}"
        if disc:
            return f"{name} #{disc}"
        return name

    @staticmethod
    def _friend_presence(last_seen: str) -> Tuple[str, str, str]:
        if not last_seen:
            return ("Offline", "Offline", "dim")
        try:
            stamp = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
            now = datetime.now(stamp.tzinfo) if stamp.tzinfo else datetime.utcnow()
            age = (now - stamp).total_seconds()
            if age < 300:
                return ("● Online", "Now", "green")
            if age < 1800:
                mins = max(1, int(age // 60))
                return ("◑ Away", f"{mins}m ago", "yellow")
            hours = max(1, int(age // 3600))
            return ("○ Offline", f"{hours}h ago", "dim")
        except Exception:
            return ("○ Offline", "Unknown", "dim")


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS SCREEN  —  full settings & preferences panel
# ══════════════════════════════════════════════════════════════════════════════

class _SettingsScreen(Screen):
    """
    Full settings screen: Game, Display, Gameplay, Audio, Keybindings.
    Changes are committed immediately to game.settings and persisted.
    """

    def build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            UIScale.px(16), UIScale.px(14),
            UIScale.px(16), UIScale.px(12),
        )
        outer.setSpacing(UIScale.px(10))

        # ── Page header ──────────────────────────────────────────────────
        phrow = QHBoxLayout()
        title_lbl = QLabel(f"{Sym.SETTINGS}  Settings",  self)
        title_lbl.setFont(Fonts.title)
        title_lbl.setStyleSheet(f"color:{P.gold}; background:transparent;")
        phrow.addWidget(title_lbl)
        phrow.addStretch()
        back = self.back_button()
        back.setFixedWidth(UIScale.px(100))
        phrow.addWidget(back)
        outer.addLayout(phrow)

        sep0 = QFrame(self)
        sep0.setFrameShape(QFrame.Shape.HLine)
        sep0.setFixedHeight(1)
        sep0.setStyleSheet(f"background:{P.border_light}; border:none;")
        outer.addWidget(sep0)

        # ── Scroll area ──────────────────────────────────────────────────
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background:transparent; border:none;")

        content = QWidget()
        content.setStyleSheet("background:transparent;")
        vlay = QVBoxLayout(content)
        vlay.setSpacing(UIScale.px(14))
        vlay.setContentsMargins(
            UIScale.px(2), UIScale.px(4),
            UIScale.px(10), UIScale.px(8),
        )

        # Build sections
        self._pending_hotkey: Optional[Tuple[str, QPushButton]] = None
        self._hotkey_btns: Dict[str, QPushButton] = {}
        self._hotkey_value_labels: Dict[str, QLabel] = {}
        self._build_game_section(vlay)
        self._build_display_section(vlay)
        self._build_animation_section(vlay)
        self._build_gameplay_section(vlay)
        self._build_audio_section(vlay)
        self._build_keybinds_section(vlay)
        self._build_info_section(vlay)
        vlay.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # ── Footer buttons ─────────────────────────────────────────────
        frow = QHBoxLayout()
        frow.setSpacing(UIScale.px(8))
        bankruptcy_btn = MtButton(f"{Sym.WARNING}  File Bankruptcy", self, role="danger")
        bankruptcy_btn.setFixedHeight(UIScale.px(34))
        bankruptcy_btn.clicked.connect(self._file_bankruptcy)
        save_btn = MtButton(f"{Sym.SAVE}  Save Settings", self)
        save_btn.setFixedHeight(UIScale.px(34))
        save_btn.clicked.connect(self._save_all)
        frow.addWidget(bankruptcy_btn)
        frow.addStretch()
        frow.addWidget(save_btn)
        outer.addLayout(frow)

        self._time_timer = QTimer(self)
        self._time_timer.timeout.connect(self.refresh)
        self._time_timer.start(1000)

    # ── Section helpers ────────────────────────────────────────────────────

    def _section_frame(self, title: str) -> Tuple[QFrame, QVBoxLayout]:
        frame = QFrame(self)
        frame.setObjectName("dashPanel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(UIScale.px(12), UIScale.px(8),
                               UIScale.px(12), UIScale.px(10))
        lay.setSpacing(UIScale.px(6))
        hdr = QLabel(title, frame)
        hdr.setFont(Fonts.mixed_bold)
        hdr.setStyleSheet(f"color:{P.amber}; background:transparent;")
        lay.addWidget(hdr)
        sep = QFrame(frame)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{P.border}; border:none;")
        lay.addWidget(sep)
        return frame, lay

    def _row(self, parent: QWidget, label: str,
             widget: QWidget, note: str = "") -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(UIScale.px(8))
        lbl = QLabel(label, parent)
        lbl.setFont(Fonts.mixed_small)
        lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        lbl.setFixedWidth(UIScale.px(170))
        row.addWidget(lbl)
        row.addWidget(widget, 1)
        if note:
            n = QLabel(note, parent)
            n.setFont(Fonts.tiny)
            n.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
            row.addWidget(n)
        return row

    def _toggle(self, parent: QWidget,
                attr: str, label: str, note: str = "") -> QHBoxLayout:
        s = self.game.settings
        cb = QCheckBox(label, parent)
        cb.setFont(Fonts.mixed_small_bold)
        cb.setChecked(bool(getattr(s, attr, False)))
        cb.setStyleSheet(f"color:{P.fg_header}; background:transparent;")
        cb.stateChanged.connect(
            lambda v, a=attr: (setattr(self.game.settings, a,
                                       v == Qt.CheckState.Checked.value),
                               self.game.settings.save(),
                               self.refresh()))
        return self._row(parent, "", cb, note)

    # ── Game section ───────────────────────────────────────────────────────

    def _build_game_section(self, vlay: QVBoxLayout) -> None:
        s = self.game.settings
        frame, lay = self._section_frame(f"{Sym.SETTINGS}  Game")

        # Difficulty
        diff_combo = QComboBox(frame)
        diff_combo.setFont(Fonts.mixed_small)
        diff_combo.setFixedHeight(UIScale.px(26))
        for d in ("easy", "normal", "hard", "brutal"):
            diff_combo.addItem(d.title(), d)
        diff_combo.setCurrentText(getattr(s, "difficulty", "normal").title())
        _DIFF_DESCS: Dict[str, str] = {
            "easy":   "Costs \u00d70.70  \u00b7  Sell \u00d71.10  \u00b7  Events \u00d70.60  \u00b7  Attacks \u00d70.50",
            "normal": "Costs \u00d71.00  \u00b7  Sell \u00d71.00  \u00b7  Events \u00d71.00  \u00b7  Attacks \u00d71.00",
            "hard":   "Costs \u00d71.35  \u00b7  Sell \u00d70.90  \u00b7  Events \u00d71.40  \u00b7  Attacks \u00d71.50",
            "brutal": "Costs \u00d71.80  \u00b7  Sell \u00d70.80  \u00b7  Events \u00d72.00  \u00b7  Attacks \u00d72.50",
        }
        self._diff_descs = _DIFF_DESCS
        cur_diff = getattr(s, "difficulty", "normal")
        self._diff_desc_lbl = QLabel(f"  {_DIFF_DESCS.get(cur_diff, '')}", frame)
        self._diff_desc_lbl.setFont(Fonts.mono_small)
        self._diff_desc_lbl.setStyleSheet(
            f"color:{P.fg_dim}; background:transparent;")
        self._diff_desc_lbl.setWordWrap(True)
        diff_combo.currentIndexChanged.connect(
            lambda _: (
                self._set_difficulty(diff_combo.currentData()),
                self._diff_desc_lbl.setText(
                    f"  {self._diff_descs.get(diff_combo.currentData(), '')}"),
            ))
        lay.addLayout(self._row(frame, "Difficulty:", diff_combo))
        lay.addWidget(self._diff_desc_lbl)

        # Autosave
        lay.addLayout(self._toggle(frame, "autosave",
                                   "Autosave at end of every day"))

        vlay.addWidget(frame)

    def _set_difficulty(self, val: str) -> None:
        self.game.settings.difficulty = val
        self.game.settings.save()

    # ── Display section ────────────────────────────────────────────────────

    def _build_display_section(self, vlay: QVBoxLayout) -> None:
        s = self.game.settings
        frame, lay = self._section_frame(
            f"{Sym.INTELLIGENCE}  Display  (Ctrl+Scroll to adjust)")

        # UI Scale
        self._scale_lbl = QLabel(
            f"{int(getattr(s, 'ui_scale', 1.0) * 100)}%", frame)
        self._scale_lbl.setFont(Fonts.mixed_small)
        self._scale_lbl.setStyleSheet(
            f"color:{P.amber}; background:transparent;")
        self._scale_lbl.setFixedWidth(UIScale.px(36))

        scale_sl = QSlider(Qt.Orientation.Horizontal, frame)
        scale_sl.setMinimum(75)
        scale_sl.setMaximum(200)
        scale_sl.setValue(int(getattr(s, "ui_scale", 1.0) * 100))
        scale_sl.setTickPosition(QSlider.TickPosition.TicksBelow)
        scale_sl.setTickInterval(25)
        scale_sl.setStyleSheet(self._slider_style())
        self._scale_slider = scale_sl
        scale_sl.valueChanged.connect(self._on_scale_slide)
        scale_sl.sliderReleased.connect(
            lambda: self._apply_scale(scale_sl.value() / 100))

        reset_btn = MtButton("Reset", frame, role="secondary")
        reset_btn.setFont(Fonts.tiny)
        reset_btn.setFixedHeight(UIScale.px(24))
        reset_btn.clicked.connect(self._reset_scale)

        scale_row = QHBoxLayout()
        scale_row.addWidget(self._row_lbl(frame, "UI Scale:"))
        scale_row.addWidget(scale_sl, 1)
        scale_row.addWidget(self._scale_lbl)
        scale_row.addWidget(reset_btn)
        lay.addLayout(scale_row)

        ticks_lbl = self._sub_note(
            frame,
            "75%          100%               150%          200%",
        )
        ticks_lbl.setFont(Fonts.small)
        lay.addWidget(ticks_lbl)

        vlay.addWidget(frame)

    def _build_animation_section(self, vlay: QVBoxLayout) -> None:
        frame, lay = self._section_frame(f"{Sym.PROGRESS}  Animations")
        lay.addLayout(self._toggle(
            frame,
            "profit_flash",
            "Profit flash animations  (golden glow on large earnings)",
        ))
        lay.addWidget(self._sub_note(
            frame,
            ">=100g shimmer  ·  >=500g flash  ·  >=1000g wash  ·  >=5000g jackpot",
        ))
        vlay.addWidget(frame)

    def _slider_style(self) -> str:
        return (
            f"QSlider::groove:horizontal{{height:{UIScale.px(4)}px;"
            f"background:{P.border};border-radius:{UIScale.px(2)}px;}}"
            f"QSlider::handle:horizontal{{background:{P.gold};border:none;"
            f"width:{UIScale.px(14)}px;height:{UIScale.px(14)}px;"
            f"margin:{UIScale.px(-5)}px 0;border-radius:{UIScale.px(7)}px;}}"
            f"QSlider::sub-page:horizontal{{background:{P.amber};"
            f"border-radius:{UIScale.px(2)}px;}}"
        )

    def _row_lbl(self, parent: QWidget, text: str) -> QLabel:
        lbl = QLabel(text, parent)
        lbl.setFont(Fonts.mixed_small)
        lbl.setStyleSheet(f"color:{P.fg}; background:transparent;")
        lbl.setFixedWidth(UIScale.px(170))
        return lbl

    def _sub_note(self, parent: QWidget, text: str) -> QLabel:
        lbl = QLabel(f"   {text}", parent)
        lbl.setFont(Fonts.tiny)
        lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        lbl.setWordWrap(True)
        return lbl

    def _on_scale_slide(self, v: int) -> None:
        self._scale_lbl.setText(f"{v}%")

    def _apply_scale(self, scale: float) -> None:
        UIScale.set(round(scale, 2))
        self.game.settings.ui_scale = round(scale, 2)
        self.game.settings.save()

    def _reset_scale(self) -> None:
        if hasattr(self, "_scale_slider"):
            self._scale_slider.setValue(100)
        self._apply_scale(1.0)

    def _format_hotkey_display(self, binding: str) -> str:
        if not binding:
            return "—"
        names = {
            "Control": "Ctrl",
            "Alt": "Alt",
            "Shift": "Shift",
            "Tab": "Tab",
            "Return": "Enter",
            "Escape": "Esc",
            "BackSpace": "Backspace",
            "Delete": "Del",
            "space": "Space",
        }
        parts = [part for part in binding.split("-") if part]
        display = [
            names.get(part, part.upper() if len(part) == 1 else part)
            for part in parts
        ]
        return "+".join(display) if display else "—"

    def _refresh_audio_status(self) -> None:
        if not hasattr(self, "_audio_status_lbl"):
            return
        s = self.game.settings
        music_state = "Music ON" if getattr(s, "music_enabled", True) else "Music OFF"
        self._audio_status_lbl.setText(
            f"  {music_state}  ·  Music {int(getattr(s, 'music_volume', 0.5) * 100)}%"
            f"  ·  SFX {int(getattr(s, 'sfx_volume', 0.7) * 100)}%"
        )

    # ── Gameplay section ───────────────────────────────────────────────────

    def _build_gameplay_section(self, vlay: QVBoxLayout) -> None:
        frame, lay = self._section_frame("\U0001f5b1  Interactions")
        lay.addLayout(self._toggle(
            frame, "double_click_action",
            "Double-click table rows to perform primary action"))
        lay.addWidget(self._sub_note(
            frame,
            "Trade: buy or sell  \u00b7  Contracts: accept/fulfill  \u00b7"
            "  Travel: depart  \u00b7  Listings: buy  \u00b7  Smuggling: buy/sell"))
        lay.addLayout(self._toggle(
            frame, "right_click_haggle",
            "Right-click an item in the Trade Buy table to haggle"))
        lay.addWidget(self._sub_note(
            frame,
            "Selects the item and triggers an instant haggle attempt for a price discount"))
        lay.addLayout(self._toggle(
            frame, "enable_signatures",
            "Show signing document for licenses, loans, contracts, and real estate"))
        lay.addWidget(self._sub_note(
            frame,
            "Parchment popup with quill cursor \u2014 draw your signature or click Sign & Accept"))
        vlay.addWidget(frame)

    # ── Audio section ──────────────────────────────────────────────────────

    def _build_audio_section(self, vlay: QVBoxLayout) -> None:
        s = self.game.settings
        frame, lay = self._section_frame(f"{Sym.PROGRESS}  Audio")

        self._audio_status_lbl = QLabel(frame)
        self._audio_status_lbl.setFont(Fonts.mono_small)
        self._audio_status_lbl.setStyleSheet(
            f"color:{P.fg_dim}; background:transparent;")
        lay.addWidget(self._audio_status_lbl)
        self._refresh_audio_status()

        # Music enable
        lay.addLayout(self._toggle(frame, "music_enabled",
                                   "Enable background music"))

        # Music volume
        self._mvol_lbl = QLabel(
            f"{int(getattr(s, 'music_volume', 0.5) * 100)}%", frame)
        self._mvol_lbl.setFont(Fonts.mixed_small)
        self._mvol_lbl.setStyleSheet(
            f"color:{P.amber}; background:transparent;")
        self._mvol_lbl.setFixedWidth(UIScale.px(36))
        mvol_sl = QSlider(Qt.Orientation.Horizontal, frame)
        mvol_sl.setMinimum(0)
        mvol_sl.setMaximum(100)
        mvol_sl.setValue(int(getattr(s, "music_volume", 0.5) * 100))
        mvol_sl.setStyleSheet(self._slider_style())
        mvol_sl.valueChanged.connect(self._on_music_volume_changed)
        mvol_sl.sliderReleased.connect(self.game.settings.save)
        mvol_row = QHBoxLayout()
        mvol_row.addWidget(self._row_lbl(frame, "Music Volume:"))
        mvol_row.addWidget(mvol_sl, 1)
        mvol_row.addWidget(self._mvol_lbl)
        lay.addLayout(mvol_row)

        # SFX volume
        self._svol_lbl = QLabel(
            f"{int(getattr(s, 'sfx_volume', 0.7) * 100)}%", frame)
        self._svol_lbl.setFont(Fonts.mixed_small)
        self._svol_lbl.setStyleSheet(
            f"color:{P.amber}; background:transparent;")
        self._svol_lbl.setFixedWidth(UIScale.px(36))
        svol_sl = QSlider(Qt.Orientation.Horizontal, frame)
        svol_sl.setMinimum(0)
        svol_sl.setMaximum(100)
        svol_sl.setValue(int(getattr(s, "sfx_volume", 0.7) * 100))
        svol_sl.setStyleSheet(self._slider_style())
        svol_sl.valueChanged.connect(self._on_sfx_volume_changed)
        svol_sl.sliderReleased.connect(self.game.settings.save)
        svol_row = QHBoxLayout()
        svol_row.addWidget(self._row_lbl(frame, "Sound FX Volume:"))
        svol_row.addWidget(svol_sl, 1)
        svol_row.addWidget(self._svol_lbl)
        lay.addLayout(svol_row)

        vlay.addWidget(frame)

    def _on_music_volume_changed(self, value: int) -> None:
        self._mvol_lbl.setText(f"{value}%")
        self.game.settings.music_volume = value / 100
        self._refresh_audio_status()

    def _on_sfx_volume_changed(self, value: int) -> None:
        self._svol_lbl.setText(f"{value}%")
        self.game.settings.sfx_volume = value / 100
        self._refresh_audio_status()

    # ── Keybindings section ────────────────────────────────────────────────

    _HOTKEY_LABELS: List[Tuple[str, str]] = [
        ("trade",      "Trade"),
        ("travel",     "Travel"),
        ("inventory",  "Inventory"),
        ("wait",       "Rest / Wait"),
        ("businesses", "Businesses"),
        ("finance",    "Finance"),
        ("contracts",  "Contracts"),
        ("market",     "Market Info"),
        ("news",       "News & Events"),
        ("progress",   "Progress"),
        ("skills",     "Skills"),
        ("help",       "Help"),
        ("settings",   "Settings"),
        ("save",       "Quick Save"),
        ("voyage",     "Voyages"),
    ]

    def _build_keybinds_section(self, vlay: QVBoxLayout) -> None:
        s = self.game.settings
        frame, lay = self._section_frame(f"{Sym.CONTRACT}  Keybindings")

        note = QLabel(
            "Click Set then press any key or key combination. "
            "Escape cancels capture. Multi-key hotkeys like Ctrl+T are supported.",
            frame)
        note.setFont(Fonts.tiny)
        note.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        note.setWordWrap(True)
        lay.addWidget(note)

        grid = QGridLayout()
        grid.setSpacing(UIScale.px(4))
        grid.setHorizontalSpacing(UIScale.px(8))
        grid.setContentsMargins(UIScale.px(2), UIScale.px(4), UIScale.px(2), 0)
        grid.setColumnMinimumWidth(0, UIScale.px(180))
        grid.setColumnMinimumWidth(1, UIScale.px(104))
        grid.setColumnMinimumWidth(2, UIScale.px(88))
        grid.setColumnStretch(3, 1)

        for row_idx, (action, label) in enumerate(self._HOTKEY_LABELS):
            cur = getattr(s, "hotkeys", {}).get(action, DEFAULT_HOTKEYS.get(action, ""))
            name_lbl = QLabel(label, frame)
            name_lbl.setFont(Fonts.mixed_small_bold)
            name_lbl.setStyleSheet(f"color:{P.fg_header}; background:transparent;")
            name_lbl.setMinimumWidth(UIScale.px(152))

            cur_lbl = QLabel(self._format_hotkey_display(cur), frame)
            cur_lbl.setFont(Fonts.mono_small)
            cur_lbl.setStyleSheet(
                f"color:{P.gold}; background:{P.bg_input};"
                f" border:1px solid {P.border_light};"
                f" border-radius:{UIScale.px(3)}px;"
                f" padding:1px {UIScale.px(6)}px;")
            cur_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cur_lbl.setMinimumWidth(UIScale.px(104))
            self._hotkey_value_labels[action] = cur_lbl

            set_btn = MtButton("Set", frame, role="secondary")
            set_btn.setFont(Fonts.tiny)
            set_btn.setMinimumWidth(UIScale.px(88))
            set_btn.setFixedHeight(UIScale.px(24))
            set_btn.clicked.connect(
                lambda _, a=action, bl=cur_lbl, bb=set_btn:
                    self._start_capture(a, bl, bb))
            self._hotkey_btns[action] = set_btn

            grid.addWidget(name_lbl, row_idx, 0)
            grid.addWidget(cur_lbl,  row_idx, 1)
            grid.addWidget(set_btn,  row_idx, 2)
            grid.setColumnStretch(3, 1)

        lay.addLayout(grid)

        reset_btn = MtButton(f"{Sym.SYNC}  Reset All to Defaults", frame, role="danger")
        reset_btn.setFont(Fonts.mixed_small)
        reset_btn.setFixedHeight(UIScale.px(26))
        reset_btn.clicked.connect(self._reset_hotkeys)
        lay.addWidget(reset_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        vlay.addWidget(frame)

    def _start_capture(self, action: str,
                       lbl: QLabel, btn: QPushButton) -> None:
        """Begin listening for the next key press."""
        # Cancel any in-progress capture first
        if self._pending_hotkey:
            old_action, old_btn = self._pending_hotkey
            old_btn.setText("Set")
            old_btn.setRole("secondary") if isinstance(old_btn, MtButton) else None

        self._pending_hotkey = (action, btn)
        btn.setText("Press key")
        btn.setRole("primary") if isinstance(btn, MtButton) else None
        self._capture_lbl = lbl
        # Install a one-shot key filter by grabbing keyboard
        self.grabKeyboard()

    def keyPressEvent(self, event: Any) -> None:
        """Capture a key press for hotkey rebinding."""
        if not self._pending_hotkey:
            super().keyPressEvent(event)
            return
        action, btn = self._pending_hotkey
        # Escape cancels
        if event.key() == Qt.Key.Key_Escape:
            btn.setText("Set")
            btn.setRole("secondary") if isinstance(btn, MtButton) else None
            self._pending_hotkey = None
            self.releaseKeyboard()
            return
        # Build key string
        mods  = event.modifiers()
        key   = event.key()
        parts = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("Control")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt")
        # Ignore bare modifiers
        mod_only = {Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
                    Qt.Key.Key_Meta}
        if key in mod_only:
            return
        key_name = QKeySequence(key).toString()
        if key_name:
            parts.append(key_name)
        binding = "-".join(parts)  # Tkinter-style "Control-s"
        if not binding:
            return

        # Apply
        self.game.settings.hotkeys[action] = binding
        self.game.settings.save()
        if hasattr(self.app, "hotkeys"):
            self.app.hotkeys.reload(self.game.settings.hotkeys)

        self._capture_lbl.setText(self._format_hotkey_display(binding))
        btn.setText("Set")
        btn.setRole("secondary") if isinstance(btn, MtButton) else None
        self._pending_hotkey = None
        self.releaseKeyboard()
        self.msg.ok(
            f"Hotkey '{action}' → {self._format_hotkey_display(binding)}")

    def _reset_hotkeys(self) -> None:
        self.game.settings.hotkeys = dict(DEFAULT_HOTKEYS)
        self.game.settings.save()
        if hasattr(self.app, "hotkeys"):
            self.app.hotkeys.reload(self.game.settings.hotkeys)
        for action, lbl in self._hotkey_value_labels.items():
            lbl.setText(self._format_hotkey_display(
                self.game.settings.hotkeys.get(action, "") or ""))
        self.msg.ok("Keybindings reset to defaults.")

    # ── Info section (save file path & session time) ───────────────────────

    def _build_info_section(self, vlay: QVBoxLayout) -> None:
        frame, lay = self._section_frame(f"{Sym.INFO}  Save & Info")

        save_path = getattr(self.game, "SAVE_FILE",
                            "Unknown — see AppData/MerchantTycoon/")
        path_lbl = QLabel(save_path, frame)
        path_lbl.setFont(Fonts.mono_small)
        path_lbl.setStyleSheet(f"color:{P.fg_dim}; background:transparent;")
        path_lbl.setWordWrap(True)
        lay.addLayout(self._row(frame, "Save file:", path_lbl))

        secs = self.app.total_play_time_seconds() if hasattr(self.app, "total_play_time_seconds") else int(
            getattr(self.game, "time_played_seconds",
                getattr(getattr(self.game, "settings", None), "time_played", 0))
        )
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        self._time_played_lbl = QLabel(f"{h}h {m:02d}m {s:02d}s", frame)
        self._time_played_lbl.setFont(Fonts.mixed_small)
        self._time_played_lbl.setStyleSheet(f"color:{P.cream}; background:transparent;")
        lay.addLayout(self._row(frame, "Time played:", self._time_played_lbl))

        vlay.addWidget(frame)

    # ── Save all ───────────────────────────────────────────────────────────

    def _save_all(self) -> None:
        self.game.settings.save()
        self.msg.ok("Settings saved.")

    def _file_bankruptcy(self) -> None:
        if not _popup_confirm(
            self,
            "File Bankruptcy",
            "This will erase all progress, wipe the local save, and start a brand-new profile. This cannot be undone.",
            confirm_text="Erase Save",
            confirm_role="danger",
        ):
            return
        if hasattr(self.app, "_do_bankruptcy_restart"):
            self.app._do_bankruptcy_restart()

    def refresh(self) -> None:
        if hasattr(self, "_diff_desc_lbl"):
            current_diff = getattr(self.game.settings, "difficulty", "normal")
            self._diff_desc_lbl.setText(
                f"  {self._diff_descs.get(current_diff, '')}")
        if hasattr(self, "_scale_lbl"):
            self._scale_lbl.setText(
                f"{int(getattr(self.game.settings, 'ui_scale', 1.0) * 100)}%")
        self._refresh_audio_status()
        if hasattr(self, "_time_played_lbl"):
            secs = self.app.total_play_time_seconds() if hasattr(self.app, "total_play_time_seconds") else int(
                getattr(self.game, "time_played_seconds",
                        getattr(getattr(self.game, "settings", None), "time_played", 0))
            )
            h = secs // 3600
            m = (secs % 3600) // 60
            s = secs % 60
            self._time_played_lbl.setText(f"{h}h {m:02d}m {s:02d}s")


# ── Remaining placeholder screen classes (not yet ported) ───────────────────
InventoryScreen    = _make_stub("Inventory")
WaitScreen         = _make_stub("Wait / Rest")
MarketInfoScreen   = _make_stub("Market Info")
HelpScreen         = _make_stub("Help")
SettingsScreen     = _SettingsScreen
GambleScreen       = _make_stub("Gambling")


# ── Register screens in GameApp._SCREEN_MAP ──────────────────────────────────
GameApp._SCREEN_MAP = {
    # \u2500\u2500 Hub screens (domain entry points)
    "dashboard":        DashboardScreen,
    "trade_hub":        TradeHubScreen,
    "operations_hub":   OperationsHubScreen,
    "finance_hub":      FinanceHubScreen,
    "intelligence_hub": IntelligenceHubScreen,
    "social_hub":       SocialHubScreen,
    "profile_hub":      ProfileHubScreen,
    # \u2500\u2500 Individual screens
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
