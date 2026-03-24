"""
merchant_tycoon_gui.py  —  Tkinter GUI Framework for Merchant Tycoon
══════════════════════════════════════════════════════════════════════

Architecture:
    GameApp (tk.Tk)
      ├── StatusBar         — persistent top strip; refreshes after every action
      ├── MessageBar        — bottom feedback bar  (ok / warn / err)
      └── ContentArea       — middle area; swaps Screen instances in/out
            └── Screen      — base class; each CLI menu becomes a Screen subclass

Navigation:
    app.show(screen_name)   — activate a named screen (pushes to nav stack)
    app.go_back()           — pop stack and return to previous screen
    app.refresh()           — re-render status bar + current screen

Talking to game logic:
    Every Screen holds  self.app.game  (the Game instance).
    GUI handlers call purely-logical Game methods (_advance_day, save_game,
    etc.) then call  self.app.refresh()  to update the UI.

    Blocking CLI methods  (trade_menu, travel_menu, …) are NOT called here —
    they will be replaced one screen at a time as the conversion progresses.

Conversion workflow:
    1. Replace a stub Screen class below with a real implementation.
    2. Wire its buttons/actions to Game logic methods.
    3. Call self.app.refresh() after every state change.
    4. Remove the corresponding entry from the CLI game once verified.
"""

import tkinter as tk
from tkinter import ttk
import sys
import os
from typing import Dict, List, Optional, Tuple

# ── Import game model ─────────────────────────────────────────────────────────
# The CLI entry point (game.play()) is never invoked here.
# We only use the Game class, its dataclasses, and the static data tables.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from merchant_tycoon import (
    Game, Area, Season, LicenseType, SkillType, ItemCategory, PropertyType,
    ALL_ITEMS, AREA_INFO, BUSINESS_CATALOGUE, LICENSE_INFO, ACHIEVEMENTS,
    PROPERTY_CATALOGUE, LAND_PLOT_SIZES, PROPERTY_UPGRADES, AREA_PROPERTY_MULT,
    _PROP_NAMES, condition_label, DEFAULT_HOTKEYS,
    Item, LoanRecord, CDRecord, make_business, Contract,
    CitizenLoan, FundClient, StockHolding, Property, LandPlot,
)

# ══════════════════════════════════════════════════════════════════════════════
# THEME  —  warm fantasy / medieval merchant palette
# ══════════════════════════════════════════════════════════════════════════════

T: Dict[str, str] = {
    # ── Backgrounds (warm dark parchment & aged wood) ──────────────────────
    "bg":            "#241a0d",   # deep warm dark — charred oak
    "bg_panel":      "#2e2110",   # worn leather panel
    "bg_row_alt":    "#281d0b",   # table row alternation — darker grain
    "bg_hover":      "#503818",   # hover / selected rows — firelight glow
    "bg_button":     "#3a2814",   # default button — dark mahogany
    "bg_button_act": "#64401a",   # active button — ember glow
    # ── Text ──────────────────────────────────────────────────────────────
    "fg":            "#f5e8c8",   # warm parchment text
    "fg_dim":        "#b89870",   # aged ink / dim text
    "fg_header":     "#ffffff",   # pure white for prominence
    # ── Accents (fantasy merchant palette) ────────────────────────────────
    "cyan":          "#ffd060",   # bright gold — key values, net worth
    "yellow":        "#ffad3a",   # vivid amber — prices, warmth
    "green":         "#7dd444",   # vibrant forest green — positive, growth
    "red":           "#e04848",   # blood red — danger, losses
    "white":         "#f5ead0",   # cream — neutral labels
    "grey":          "#a89878",   # lighter parchment grey
    # ── Borders (brass, bronze, carved wood) ──────────────────────────────
    "border":        "#6b4a22",   # warm wood border
    "border_light":  "#c89444",   # polished bright brass
    # ── Season aura tints ─────────────────────────────────────────────────
    "spring":        "#7ecb5a",   # fresh meadow
    "summer":        "#f0c040",   # blazing sun (gold)
    "autumn":        "#e07b39",   # harvest flame
    "winter":        "#8ab4d4",   # frost blue
}

# ── Dialog theme constants — dramatically darker so dialogs pop off the BG ───
_DIALOG_BG       = "#0d0a05"   # near-black warm dark — strong contrast vs game bg
_DIALOG_TITLE_BG = "#1c1410"   # dialog title bar — mid-dark warm
_SHADOW_BG       = "#030201"   # drop-shadow Toplevel bg

# ── Animation / UI helpers ────────────────────────────────────────────────────
def _safe_config(widget: tk.Widget, **kw) -> None:
    """Apply widget.config(**kw) ignoring destroyed-widget errors."""
    try:
        widget.config(**kw)
    except tk.TclError:
        pass

def _flash_label(widget: tk.Widget, flash_fg: str,
                 restore_fg: str, ms: int = 550) -> None:
    """Briefly flash a label's fg to flash_fg, then restore."""
    _safe_config(widget, fg=flash_fg)
    widget.after(ms, lambda: _safe_config(widget, fg=restore_fg))

def _pulse_bg(widget: tk.Widget, flash_bg: str,
              restore_bg: str, ms: int = 400) -> None:
    """Briefly flash a widget's bg, then restore."""
    _safe_config(widget, bg=flash_bg)
    widget.after(ms, lambda: _safe_config(widget, bg=restore_bg))


def _format_hotkey(binding: str) -> str:
    """Convert an internal keybinding string to human-readable display text.

    Examples::  "t"          →  "T"
                "Control-t"  →  "Ctrl+T"
                "Tab"        →  "Tab"
                "F10"        →  "F10"
    """
    if not binding:
        return "(none)"
    _names: Dict[str, str] = {
        "Control": "Ctrl", "Alt": "Alt", "Shift": "Shift",
        "Tab": "Tab", "Return": "Enter", "Escape": "Esc",
        "BackSpace": "Backspace", "Delete": "Del", "space": "Space",
        "F1": "F1",  "F2": "F2",  "F3": "F3",  "F4": "F4",
        "F5": "F5",  "F6": "F6",  "F7": "F7",  "F8": "F8",
        "F9": "F9",  "F10": "F10", "F11": "F11", "F12": "F12",
        "Up": "↑", "Down": "↓", "Left": "←", "Right": "→",
        "Home": "Home", "End": "End", "Prior": "PgUp", "Next": "PgDn",
    }
    parts = binding.split("-")
    display = [_names.get(p, p.upper() if len(p) == 1 else p) for p in parts]
    return "+".join(display)


# ── Fonts ─────────────────────────────────────────────────────────────────────
# Palatino Linotype gives a medieval manuscript feel; Consolas for data tables
FONT_FANTASY       = ("Palatino Linotype", 11)
FONT_FANTASY_S     = ("Palatino Linotype", 10)
FONT_FANTASY_L     = ("Palatino Linotype", 14)
FONT_FANTASY_BOLD  = ("Palatino Linotype", 11, "bold")
FONT_FANTASY_TITLE = ("Palatino Linotype", 16, "bold")

FONT_MONO   = ("Consolas", 10)      # for numbers/data in tables
FONT_MONO_S = ("Consolas",  9)
FONT_MONO_L = ("Consolas", 12)
FONT_BOLD   = FONT_FANTASY_BOLD     # most labels/buttons use fantasy font
FONT_TITLE  = FONT_FANTASY_TITLE
FONT_SMALL  = ("Palatino Linotype",  8)

# ── Font / UI scaling ─────────────────────────────────────────────────────────
_UI_SCALE: float = 1.0

def _rescale_fonts(scale: float) -> None:
    """Recompute all module-level font tuples and record the current scale."""
    global FONT_FANTASY, FONT_FANTASY_S, FONT_FANTASY_L, FONT_FANTASY_BOLD
    global FONT_FANTASY_TITLE, FONT_MONO, FONT_MONO_S, FONT_MONO_L
    global FONT_BOLD, FONT_TITLE, FONT_SMALL, _UI_SCALE
    _UI_SCALE = scale
    def _s(base: int) -> int:
        return max(7, round(base * scale))
    FONT_FANTASY       = ("Palatino Linotype", _s(11))
    FONT_FANTASY_S     = ("Palatino Linotype", _s(10))
    FONT_FANTASY_L     = ("Palatino Linotype", _s(14))
    FONT_FANTASY_BOLD  = ("Palatino Linotype", _s(11), "bold")
    FONT_FANTASY_TITLE = ("Palatino Linotype", _s(16), "bold")
    FONT_MONO          = ("Consolas", _s(10))
    FONT_MONO_S        = ("Consolas",  _s(9))
    FONT_MONO_L        = ("Consolas",  _s(12))
    FONT_BOLD          = FONT_FANTASY_BOLD
    FONT_TITLE         = FONT_FANTASY_TITLE
    FONT_SMALL         = ("Palatino Linotype", _s(8))

# ══════════════════════════════════════════════════════════════════════════════
# TTK STYLE SETUP
# ══════════════════════════════════════════════════════════════════════════════

def apply_dark_theme(style: ttk.Style) -> None:
    """Configure ttk widgets to use the warm fantasy Merchant Tycoon theme."""
    style.theme_use("clam")

    style.configure(".",
        background=T["bg"],
        foreground=T["fg"],
        fieldbackground=T["bg_panel"],
        troughcolor=T["bg_panel"],
        bordercolor=T["border"],
        darkcolor=T["bg"],
        lightcolor=T["bg_panel"],
        font=FONT_FANTASY,
    )

    # ── Buttons ───────────────────────────────────────────────────────────────
    style.configure("MT.TButton",
        background=T["bg_button"],
        foreground=T["cyan"],
        bordercolor=T["border_light"],
        focuscolor=T["bg_hover"],
        relief="groove",
        padding=(14, 8),
        font=FONT_FANTASY_BOLD,
    )
    style.map("MT.TButton",
        background=[("active", T["bg_button_act"]), ("pressed", "#5a3a15")],
        foreground=[("active", T["fg_header"])],
        bordercolor=[("active", T["border_light"])],
    )

    style.configure("Nav.TButton",
        background=T["bg_button"],
        foreground=T["grey"],
        bordercolor=T["border"],
        relief="flat",
        padding=(10, 6),
        font=FONT_FANTASY_S,
    )
    style.map("Nav.TButton",
        background=[("active", T["bg_button_act"])],
        foreground=[("active", T["cyan"])],
    )

    style.configure("Danger.TButton",
        background="#2e1008",
        foreground=T["red"],
        bordercolor="#6a2010",
        relief="groove",
        padding=(14, 8),
        font=FONT_FANTASY_BOLD,
    )
    style.map("Danger.TButton",
        background=[("active", "#3e1810"), ("pressed", "#5a1010")],
        foreground=[("active", "#ff7070")],
    )

    style.configure("OK.TButton",
        background="#0e2010",
        foreground=T["green"],
        bordercolor="#285c1a",
        relief="groove",
        padding=(14, 8),
        font=FONT_FANTASY_BOLD,
    )
    style.map("OK.TButton",
        background=[("active", "#183018"), ("pressed", "#204020")],
        foreground=[("active", "#90ff60")],
    )

    # ── Frames ────────────────────────────────────────────────────────────────
    style.configure("MT.TFrame",    background=T["bg"])
    style.configure("Panel.TFrame", background=T["bg_panel"])

    # ── Labels ────────────────────────────────────────────────────────────────
    style.configure("MT.TLabel",
        background=T["bg"],
        foreground=T["fg"],
        font=FONT_FANTASY,
    )
    style.configure("Header.TLabel",
        background=T["bg"],
        foreground=T["cyan"],
        font=FONT_FANTASY_TITLE,
    )
    style.configure("Panel.TLabel",
        background=T["bg_panel"],
        foreground=T["fg"],
        font=FONT_FANTASY,
    )
    style.configure("Dim.TLabel",
        background=T["bg"],
        foreground=T["grey"],
        font=FONT_FANTASY_S,
    )

    # ── Treeview (tables) ─────────────────────────────────────────────────────
    style.configure("MT.Treeview",
        background=T["bg_panel"],
        fieldbackground=T["bg_panel"],
        foreground=T["fg"],
        rowheight=26,
        font=FONT_MONO_S,
        bordercolor=T["border"],
        relief="flat",
    )
    style.configure("MT.Treeview.Heading",
        background=T["bg"],
        foreground=T["cyan"],
        font=FONT_FANTASY_BOLD,
        relief="flat",
        bordercolor=T["border"],
    )
    style.map("MT.Treeview",
        background=[("selected", T["bg_hover"])],
        foreground=[("selected", T["fg_header"])],
    )
    style.map("MT.Treeview.Heading",
        background=[("active", T["bg_panel"])],
    )

    # ── Scrollbar ─────────────────────────────────────────────────────────────
    style.configure("MT.Vertical.TScrollbar",
        background=T["bg_panel"],
        troughcolor=T["bg"],
        arrowcolor=T["border_light"],
        bordercolor=T["border"],
    )
    style.map("MT.Vertical.TScrollbar",
        background=[("active", T["bg_hover"])],
    )

    # ── Notebook (tabs) ───────────────────────────────────────────────────────
    style.configure("MT.TNotebook",
        background=T["bg"],
        bordercolor=T["border"],
        tabmargins=0,
    )
    style.configure("MT.TNotebook.Tab",
        background=T["bg"],
        foreground=T["fg_dim"],
        font=FONT_FANTASY_S,
        padding=(14, 5),
    )
    style.map("MT.TNotebook.Tab",
        background=[("selected", T["bg_button_act"]), ("active", T["bg_button"])],
        foreground=[("selected", T["fg_header"]), ("active", T["fg"])],
        font=[("selected", FONT_FANTASY_BOLD)],
        padding=[("selected", (14, 8))],
    )

    # ── Misc ──────────────────────────────────────────────────────────────────
    style.configure("MT.TSeparator",  background=T["border"])
    style.configure("MT.TEntry",
        fieldbackground=T["bg_panel"],
        foreground=T["fg"],
        insertcolor=T["cyan"],
        bordercolor=T["border_light"],
        font=FONT_FANTASY,
    )
    style.configure("MT.TCombobox",
        fieldbackground=T["bg_panel"],
        background=T["bg_button"],
        foreground=T["fg"],
        arrowcolor=T["cyan"],
        font=FONT_FANTASY,
    )
    # Progressbar — use the base style name to avoid layout-clone issues
    style.configure("Horizontal.TProgressbar",
        background=T["yellow"],
        troughcolor=T["bg_panel"],
        bordercolor=T["border"],
    )

# ══════════════════════════════════════════════════════════════════════════════
# BASE SCREEN
# ══════════════════════════════════════════════════════════════════════════════

class Screen(ttk.Frame):
    """
    Base class for every game screen.

    Subclasses should override:
        build()    — create all widgets (called once on first show)
        refresh()  — pull current game state into widgets (called on every show)
        on_show()  — hook: called each time this screen becomes visible
        on_hide()  — hook: called each time this screen is hidden

    Convenience helpers:
        self.app               → GameApp root window
        self.game              → Game model instance
        self.msg               → MessageBar  (ok / warn / err)
        self.section_label()   → cyan section divider label
        self.action_button()   → standard MT.TButton
        self.back_button()     → back-navigation Nav.TButton
    """

    def __init__(self, parent: tk.Widget, app: "GameApp") -> None:
        super().__init__(parent, style="MT.TFrame")
        self.app   = app
        self.game  = app.game
        self.msg   = app.message_bar
        self._built = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def show(self) -> None:
        """Pack into the content area; build on first call, then refresh."""
        if not self._built:
            self.build()
            self._built = True
        self.pack(fill="both", expand=True)
        self.refresh()
        self.on_show()
        self._fade_in()

    def _fade_in(self) -> None:
        """Fade-in: an opaque overlay dissolves away to reveal the new screen."""
        self.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty()
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10:
            return   # not yet laid out — skip animation
        overlay = tk.Toplevel(self)
        overlay.overrideredirect(True)
        overlay.configure(bg=T["bg"])
        overlay.geometry(f"{w}x{h}+{x}+{y}")
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 1.0)
        self._fade_overlay(overlay, 0, 14)

    def _fade_overlay(self, overlay: tk.Toplevel, step: int, total: int) -> None:
        step += 1
        alpha = max(0.0, 1.0 - step / total)
        try:
            overlay.attributes("-alpha", alpha)
            if alpha > 0:
                self.after(18, lambda: self._fade_overlay(overlay, step, total))
            else:
                overlay.destroy()
        except tk.TclError:
            pass

    def hide(self) -> None:
        """Remove from layout."""
        self.pack_forget()
        self.on_hide()

    # ── Override these ────────────────────────────────────────────────────────

    def build(self) -> None:
        """Create all widgets. Called exactly once, on first show."""
        pass

    def refresh(self) -> None:
        """Update widget values from game state. Called on every show."""
        pass

    def on_show(self) -> None:
        """Hook: runs each time this screen becomes active."""
        pass

    def on_hide(self) -> None:
        """Hook: runs each time this screen is concealed."""
        pass

    # ── Widget helpers ────────────────────────────────────────────────────────

    def section_label(self, parent: tk.Widget, text: str) -> tk.Label:
        """A gold fantasy divider label with decorative flourishes."""
        decorated = f"  ✦  {text.upper()}  ✦"
        return tk.Label(parent, text=decorated,
                        bg=T["bg"], fg=T["cyan"], font=FONT_FANTASY_BOLD,
                        anchor="w")

    def action_button(self, parent: tk.Widget, text: str,
                      command, style: str = "MT.TButton") -> ttk.Button:
        return ttk.Button(parent, text=text, command=command, style=style)

    def back_button(self, parent: tk.Widget,
                    text: str = "◄  Back") -> ttk.Button:
        return ttk.Button(parent, text=text,
                          command=self.app.go_back, style="Nav.TButton")

    def colored_label(self, parent: tk.Widget, text: str,
                      color: str, font=FONT_FANTASY, bg: str = None) -> tk.Label:
        """A plain tk.Label with an explicit foreground colour."""
        return tk.Label(parent, text=text, fg=color,
                        bg=bg or T["bg"], font=font)

# ══════════════════════════════════════════════════════════════════════════════
# REUSABLE WIDGETS
# ══════════════════════════════════════════════════════════════════════════════

class StatusBar(ttk.Frame):
    """
    Persistent top strip — always visible, refreshed after every action.
    Mirrors  Game.display_status()  from the CLI.
    """

    _SEASON_COL = {
        Season.SPRING: T["spring"],
        Season.SUMMER: T["summer"],
        Season.AUTUMN: T["autumn"],
        Season.WINTER: T["winter"],
    }
    _REP_LABELS = [
        (20, "Outlaw",    T["red"]),
        (40, "Suspect",   T["yellow"]),
        (60, "Neutral",   T["white"]),
        (80, "Trusted",   T["green"]),
        (101,"Legendary", T["cyan"]),
    ]

    def __init__(self, parent: tk.Widget, game: Game) -> None:
        super().__init__(parent, style="Panel.TFrame", height=100)
        self.game = game
        self.pack_propagate(False)
        self._prev_gold: float = -1.0
        self._build()

    def _mk_label(self, parent: tk.Widget, font=FONT_FANTASY, **kw) -> tk.Label:
        return tk.Label(parent, bg=T["bg_panel"], font=font, anchor="w", **kw)

    def _build(self) -> None:
        # Decorative top border
        tk.Frame(self, bg=T["border_light"], height=2).pack(fill="x")

        # Row 1: year/day/season · player name · rep
        r1 = tk.Frame(self, bg=T["bg_panel"])
        r1.pack(fill="x", padx=10, pady=(4, 0))

        self._player = tk.Label(r1, text="", bg=T["bg_panel"],
                                fg=T["fg_dim"], font=FONT_FANTASY_BOLD, anchor="w")
        self._player.pack(side="left")

        self._date = self._mk_label(r1, font=FONT_FANTASY_S, fg=T["fg_dim"], text="")
        self._date.pack(side="left", padx=(14, 0))

        self._rep = self._mk_label(r1, font=FONT_FANTASY_S, fg=T["green"], text="")
        self._rep.pack(side="right")

        # Row 2: gold / bank / location / net worth
        r2 = tk.Frame(self, bg=T["bg_panel"])
        r2.pack(fill="x", padx=10, pady=(1, 0))

        self._gold     = self._mk_label(r2, font=FONT_FANTASY_BOLD, fg=T["yellow"], text="")
        self._location = self._mk_label(r2, font=FONT_FANTASY, fg=T["cyan"],   text="")
        self._nw       = self._mk_label(r2, font=FONT_FANTASY_S, fg=T["fg_dim"],   text="")
        self._gold.pack(side="left")
        self._location.pack(side="left", padx=(18, 0))
        self._nw.pack(side="right")

        # Row 3: slot bar · heat · active events
        r3 = tk.Frame(self, bg=T["bg_panel"])
        r3.pack(fill="x", padx=10, pady=(1, 4))

        self._slots  = self._mk_label(r3, font=FONT_FANTASY_S, fg=T["cyan"],   text="")
        self._heat   = self._mk_label(r3, font=FONT_FANTASY_S, fg=T["red"],    text="")
        self._events = self._mk_label(r3, font=FONT_FANTASY_S, fg=T["yellow"], text="")
        self._slots.pack(side="left")
        self._heat.pack(side="left", padx=(18, 0))
        self._events.pack(side="left", padx=(18, 0))

        ttk.Separator(self, orient="horizontal",
                      style="MT.TSeparator").pack(fill="x", side="bottom")

    def _rep_str(self, rep: int) -> Tuple[str, str]:
        for threshold, label, colour in self._REP_LABELS:
            if rep < threshold:
                return label, colour
        return "Legendary", T["cyan"]

    def refresh(self) -> None:
        """Pull current game state and update every label."""
        g = self.game

        if hasattr(self, "_player"):
            self._player.config(text=f"⚘  {g.player_name}" if g.player_name else "⚘  Merchant")

        season_col = self._SEASON_COL.get(g.season, T["fg"])
        self._date.config(
            text=f"Year {g.year}  ·  Day {g.day}  ·  {g.season.value}",
            fg=season_col,
        )

        rep_lbl, rep_col = self._rep_str(g.reputation)
        self._rep.config(
            text=f"Rep: {g.reputation}  ({rep_lbl})",
            fg=rep_col,
        )

        new_gold = g.inventory.gold
        self._gold.config(
            text=f"◆ {new_gold:,.0f}g   Bank: {g.bank_balance:,.0f}g"
        )
        if self._prev_gold >= 0 and new_gold != self._prev_gold:
            flash_fg = T["green"] if new_gold > self._prev_gold else T["red"]
            _flash_label(self._gold, flash_fg, T["yellow"], ms=600)
        self._prev_gold = new_gold
        self._location.config(text=f"📍  {g.current_area.value}")
        self._nw.config(text=f"Net Worth: {g._net_worth():,.2f}g")

        used = g.daily_time_units
        left = g.DAILY_TIME_UNITS - used
        bar  = "●" * used + "○" * left
        slot_col = T["red"] if left == 0 else T["yellow"] if left <= 2 else T["cyan"]
        self._slots.config(
            text=f"⌛ {bar}  ({left} actions left)",
            fg=slot_col,
        )

        if g.heat > 0:
            heat_col = T["red"] if g.heat > 50 else T["yellow"]
            self._heat.config(text=f"🔥 Heat: {g.heat}/100", fg=heat_col)
        else:
            self._heat.config(text="")

        events: List[str] = []
        for mkt in g.markets.values():
            events.extend(mkt.active_events)
        if events:
            unique = list(dict.fromkeys(events))[:3]
            self._events.config(text="Events: " + "  ·  ".join(unique))
        else:
            self._events.config(text="")


class MessageBar(ttk.Frame):
    """
    Bottom strip for feedback — replaces CLI  ok() / warn() / err().
    Messages slide in (animate height) and auto-clear after _CLEAR_MS.
    """

    _CLEAR_MS   = 6_000
    _TARGET_H   = 30
    _ANIM_STEPS = 8
    _ANIM_MS    = 14

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, style="Panel.TFrame", height=0)
        self.pack_propagate(False)
        self._after_id: Optional[str] = None
        self._anim_id:  Optional[str] = None
        self._current_h = 0
        self._toast_fn  = None   # set by GameApp to spawn GameToast windows

        ttk.Separator(self, orient="horizontal",
                      style="MT.TSeparator").pack(fill="x", side="top")
        self._lbl = tk.Label(self, text="", font=FONT_FANTASY_S,
                             bg=T["bg_panel"], anchor="w", padx=12)
        self._lbl.pack(fill="both", expand=True)

    def _show(self, text: str, colour: str) -> None:
        if self._after_id:
            self.after_cancel(self._after_id)
        if self._anim_id:
            self.after_cancel(self._anim_id)
        self._lbl.config(text=text, fg=colour)
        self._animate_open(self._ANIM_STEPS)
        self._after_id = self.after(self._CLEAR_MS, self._clear)
        # Also fire a floating toast
        if self._toast_fn:
            try:
                self._toast_fn(text.strip().lstrip("✔⚠✘› "), colour)
            except Exception:
                pass

    def _animate_open(self, steps: int) -> None:
        target = self._TARGET_H
        if steps <= 0 or self._current_h >= target:
            self.configure(height=target)
            self._current_h = target
            return
        h = int(target * (1 - steps / self._ANIM_STEPS) + 1)
        self.configure(height=h)
        self._current_h = h
        self._anim_id = self.after(self._ANIM_MS,
                                   lambda: self._animate_open(steps - 1))

    def _clear(self) -> None:
        self._lbl.config(text="")
        self._after_id = None
        self._current_h = 0
        self.configure(height=0)

    def ok(self,   text: str) -> None: self._show(f"  ✔  {text}", T["green"])
    def warn(self, text: str) -> None: self._show(f"  ⚠  {text}", T["yellow"])
    def err(self,  text: str) -> None: self._show(f"  ✘  {text}", T["red"])
    def info(self, text: str) -> None: self._show(f"  ›  {text}", T["fg"])


class DataTable(ttk.Frame):
    """
    Scrollable Treeview wrapper for tabular game data.

    columns — list of (key, heading, pixel_width)
    tag_key — optional dict key whose value is a colour tag name

    Usage:
        cols = [("name","Item",180), ("price","Price",80), ("stock","Stock",60)]
        table = DataTable(parent, cols)
        table.load([{"name":"Fish", "price":"12g", "stock":"45", "tag":"green"}, …],
                   tag_key="tag")
        row_dict = table.selected()   # → dict or None
    """

    _TAGS = ["green", "yellow", "red", "cyan", "dim"]

    def __init__(self, parent: tk.Widget,
                 columns: List[Tuple[str, str, int]],
                 height: int = 15,
                 selectmode: str = "browse") -> None:
        super().__init__(parent, style="MT.TFrame")
        self._col_keys = [c[0] for c in columns]

        self.tree = ttk.Treeview(
            self,
            columns=self._col_keys,
            show="headings",
            style="MT.Treeview",
            height=height,
            selectmode=selectmode,
        )
        vsb = ttk.Scrollbar(self, orient="vertical",
                            command=self.tree.yview,
                            style="MT.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set)

        for key, heading, width in columns:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, minwidth=40, anchor="w")

        # Built-in colour tags
        self.tree.tag_configure("green",  foreground=T["green"])
        self.tree.tag_configure("yellow", foreground=T["yellow"])
        self.tree.tag_configure("red",    foreground=T["red"])
        self.tree.tag_configure("cyan",   foreground=T["cyan"])
        self.tree.tag_configure("dim",    foreground=T["fg_dim"])
        self.tree.tag_configure("alt",    background="#201808")
        self.tree.tag_configure("_hover", background="#2e1e0a")

        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Row hover highlight
        self._hover_iid: str = ""
        self.tree.bind("<Motion>", self._on_hover)
        self.tree.bind("<Leave>",  self._on_leave)

    def load(self, rows: List[Dict], tag_key: str = "") -> None:
        """Replace all rows. Optional tag_key selects a colour tag per row."""
        self._rows = list(rows)  # keep originals so selected() returns metadata too
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(rows):
            values = [row.get(k, "") for k in self._col_keys]
            tags: List[str] = []
            if tag_key and tag_key in row:
                tags.append(row[tag_key])
            if i % 2 == 1:
                tags.append("alt")
            self.tree.insert("", "end", values=values, tags=tags)

    def selected(self) -> Optional[Dict]:
        """Return the original row dict (including hidden keys) for the selected row."""
        sel = self.tree.selection()
        if not sel:
            return None
        idx = self.tree.index(sel[0])
        rows = getattr(self, "_rows", [])
        if 0 <= idx < len(rows):
            return rows[idx]
        return dict(zip(self._col_keys, self.tree.item(sel[0])["values"]))

    def bind_double(self, callback) -> None:
        self.tree.bind("<Double-1>", lambda _: callback(self.selected()))

    def bind_select(self, callback) -> None:
        self.tree.bind("<<TreeviewSelect>>", lambda _: callback(self.selected()))

    def _on_hover(self, event) -> None:
        """Highlight row under the mouse cursor."""
        iid = self.tree.identify_row(event.y)
        if iid == self._hover_iid:
            return
        if self._hover_iid:
            try:
                old = [t for t in self.tree.item(self._hover_iid, "tags") if t != "_hover"]
                self.tree.item(self._hover_iid, tags=old)
            except tk.TclError:
                pass
        self._hover_iid = iid
        if iid:
            try:
                new = list(self.tree.item(iid, "tags"))
                if "_hover" not in new:
                    new.append("_hover")
                self.tree.item(iid, tags=new)
            except tk.TclError:
                pass

    def _on_leave(self, event) -> None:
        """Clear hover highlight when cursor leaves the widget."""
        if self._hover_iid:
            try:
                old = [t for t in self.tree.item(self._hover_iid, "tags") if t != "_hover"]
                self.tree.item(self._hover_iid, tags=old)
            except tk.TclError:
                pass
            self._hover_iid = ""


class ScrollableFrame(ttk.Frame):
    """
    A vertically scrollable ttk.Frame container.
    Pack widgets into  self.inner  as if it were a normal Frame.
    """

    def __init__(self, parent: tk.Widget, **kw) -> None:
        super().__init__(parent, style="MT.TFrame", **kw)
        canvas = tk.Canvas(self, bg=T["bg"], highlightthickness=0)
        vsb    = ttk.Scrollbar(self, orient="vertical",
                               command=canvas.yview,
                               style="MT.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self.inner = ttk.Frame(canvas, style="MT.TFrame")
        _win = canvas.create_window((0, 0), window=self.inner, anchor="nw")

        def _on_resize(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(_win, width=e.width)

        self.inner.bind("<Configure>", _on_resize)
        canvas.bind("<Configure>",    _on_resize)

        # Mouse-wheel scrolling
        self.inner.bind_all("<MouseWheel>",
                            lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

# ══════════════════════════════════════════════════════════════════════════════
# DIALOG HELPERS  —  replace CLI  prompt() / pause() / print-block + pause
# ══════════════════════════════════════════════════════════════════════════════

class _BaseDialog(tk.Toplevel):
    """Shared dark-themed modal dialog base — high-contrast against game window."""

    _SHADOW_OFF = 6   # drop-shadow offset in pixels

    def __init__(self, parent: tk.Widget, title: str) -> None:
        super().__init__(parent)
        self.overrideredirect(True)
        # Outer border: bright brass shows through as a thin gold frame
        self.configure(bg=T["border_light"])
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.update_idletasks()
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.result   = None
        self._drag_x  = 0
        self._drag_y  = 0
        self._shadow  = None

        # Clean up shadow automatically on any destroy path
        self.bind("<Destroy>", self._kill_shadow, add="+")

        # ── Title bar (brighter accent + distinct bg) ─────────────────────
        # 5-px gold accent at top (more prominent than old 3px)
        tk.Frame(self, bg=T["border_light"], height=5).pack(fill="x", side="top")
        # Thin mid-tone strip to create a gradient feel
        tk.Frame(self, bg="#8a6430", height=1).pack(fill="x", side="top")

        _title_bar = tk.Frame(self, bg=_DIALOG_TITLE_BG, height=32)
        _title_bar.pack(fill="x", side="top")
        _title_bar.pack_propagate(False)

        tk.Label(_title_bar, text=f"  \u2698  {title}",
                 bg=_DIALOG_TITLE_BG, fg=T["cyan"],
                 font=FONT_FANTASY_BOLD, anchor="w").pack(side="left", fill="x",
                                                          expand=True, padx=(4, 0))

        _close = tk.Label(_title_bar, text="  \u2715  ",
                          bg=_DIALOG_TITLE_BG, fg=T["grey"],
                          font=FONT_FANTASY_BOLD, cursor="hand2")
        _close.pack(side="right", padx=4)
        _close.bind("<Button-1>", lambda _: self._on_cancel())
        _close.bind("<Enter>",    lambda e: e.widget.config(bg="#5a1010", fg=T["fg_header"]))
        _close.bind("<Leave>",    lambda e: e.widget.config(bg=_DIALOG_TITLE_BG, fg=T["grey"]))

        # Bright gold separator below title bar (replaces old dim border)
        tk.Frame(self, bg=T["border_light"], height=2).pack(fill="x", side="top")

        # Drag on the title bar
        for _w in (_title_bar, self):
            _w.bind("<ButtonPress-1>", self._on_drag_start)
            _w.bind("<B1-Motion>",     self._on_drag_move)

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _on_drag_move(self, event: tk.Event) -> None:
        nx = event.x_root - self._drag_x
        ny = event.y_root - self._drag_y
        self.geometry(f"+{nx}+{ny}")
        # Keep shadow in sync while dragging
        if self._shadow:
            try:
                sw = self.winfo_width()  + self._SHADOW_OFF * 2
                sh = self.winfo_height() + self._SHADOW_OFF
                self._shadow.geometry(f"{sw}x{sh}+{nx + self._SHADOW_OFF}+{ny + self._SHADOW_OFF}")
            except tk.TclError:
                pass

    def _center(self) -> None:
        self.update_idletasks()
        pw = self.master.winfo_rootx() + self.master.winfo_width()  // 2
        ph = self.master.winfo_rooty() + self.master.winfo_height() // 2
        w  = self.winfo_width()
        h  = self.winfo_height()
        x  = pw - w // 2
        y  = ph - h // 2

        # Place dialog off-screen slightly above final position for slide-in
        self.geometry(f"+{x}+{y - 14}")

        # ── Fake drop shadow ──────────────────────────────────────────────
        try:
            self._shadow = tk.Toplevel(self.master)
            self._shadow.overrideredirect(True)
            self._shadow.configure(bg=_SHADOW_BG)
            self._shadow.attributes("-alpha", 0.55)
            self._shadow.attributes("-topmost", False)
            sw = w  + self._SHADOW_OFF * 2
            sh = h  + self._SHADOW_OFF
            self._shadow.geometry(f"{sw}x{sh}+{x + self._SHADOW_OFF}+{y + self._SHADOW_OFF}")
            self._shadow.lower()
            self.lift()
        except Exception:
            self._shadow = None

        # Win32 DWM shadow (supplementary — works where alpha is restricted)
        if sys.platform == "win32":
            try:
                import ctypes
                DWMWA_NCRENDERING_POLICY = 2
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    self.winfo_id(), DWMWA_NCRENDERING_POLICY,
                    ctypes.byref(ctypes.c_int(2)), ctypes.sizeof(ctypes.c_int))
            except Exception:
                pass

        # ── Entrance slide-in animation (ease-out, 10 frames × 14 ms) ────
        self._slide_in(x, y - 14, y, 0, 10)

    def _slide_in(self, x: int, y_cur: int, y_end: int, step: int, total: int) -> None:
        """Cubic ease-out vertical slide-in for dialog entrance."""
        step += 1
        t    = step / total
        ease = 1.0 - (1.0 - t) ** 3
        y    = round(y_cur + (y_end - y_cur) * ease)
        try:
            self.geometry(f"+{x}+{y}")
            if self._shadow:
                sw = self.winfo_width()  + self._SHADOW_OFF * 2
                sh = self.winfo_height() + self._SHADOW_OFF
                self._shadow.geometry(
                    f"{sw}x{sh}+{x + self._SHADOW_OFF}+{y + self._SHADOW_OFF}")
            if step < total:
                self.after(14, lambda: self._slide_in(x, y, y_end, step, total))
        except tk.TclError:
            pass

    def _kill_shadow(self, event=None) -> None:
        """Destroy the drop-shadow Toplevel if it exists."""
        try:
            if self._shadow:
                self._shadow.destroy()
                self._shadow = None
        except Exception:
            pass

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()

    def wait(self):
        """Block until the dialog closes, then return result."""
        self.wait_window(self)
        return self.result


class ConfirmDialog(_BaseDialog):
    """
    Yes / No dialog — replaces  prompt("…? [yes/no]")  patterns.

        if ConfirmDialog(root, "Save game before quitting?").wait():
            game.save_game()
    """

    def __init__(self, parent: tk.Widget, question: str,
                 title: str = "Confirm") -> None:
        super().__init__(parent, title)
        f = tk.Frame(self, bg=_DIALOG_BG, padx=24, pady=18)
        f.pack()
        tk.Label(f, text=question, bg=_DIALOG_BG, fg=T["fg"],
                 font=FONT_FANTASY, wraplength=420,
                 justify="center").pack(pady=(0, 16))
        row = tk.Frame(f, bg=_DIALOG_BG)
        row.pack()
        ttk.Button(row, text="  ✓  Yes", style="OK.TButton",
                   command=self._yes).pack(side="left", padx=8)
        ttk.Button(row, text="  ✗  No",  style="Danger.TButton",
                   command=self._on_cancel).pack(side="left", padx=8)
        self._center()

    def _yes(self) -> None:
        self.result = True
        self.destroy()


class InputDialog(_BaseDialog):
    """
    Single text-field input dialog — replaces  prompt("Enter name: ").

        name = InputDialog(root, "Enter your merchant name:").wait()
    """

    def __init__(self, parent: tk.Widget, label: str,
                 title: str = "Input", default: str = "") -> None:
        super().__init__(parent, title)
        f = tk.Frame(self, bg=_DIALOG_BG, padx=24, pady=18)
        f.pack()
        tk.Label(f, text=label, bg=_DIALOG_BG, fg=T["fg"],
                 font=FONT_FANTASY, wraplength=380).pack(pady=(0, 8))
        self._var = tk.StringVar(value=default)
        entry = ttk.Entry(f, textvariable=self._var,
                          style="MT.TEntry", width=34)
        entry.pack(pady=(0, 14))
        entry.focus_set()
        entry.bind("<Return>", lambda _: self._ok())
        row = tk.Frame(f, bg=_DIALOG_BG)
        row.pack()
        ttk.Button(row, text="OK",     style="OK.TButton",
                   command=self._ok).pack(side="left", padx=8)
        ttk.Button(row, text="Cancel", style="Nav.TButton",
                   command=self._on_cancel).pack(side="left", padx=8)
        self._center()

    def _ok(self) -> None:
        self.result = self._var.get().strip()
        self.destroy()


class ChoiceDialog(_BaseDialog):
    """
    Numbered choice dialog — replaces menus that prompt for a number.

        idx = ChoiceDialog(root, "Choose an area:", ["City", "Coast", "Forest"]).wait()
        if idx is not None:
            dest = areas[idx]
    """

    def __init__(self, parent: tk.Widget, label: str,
                 choices: List[str], title: str = "Choose") -> None:
        super().__init__(parent, title)
        f = tk.Frame(self, bg=_DIALOG_BG, padx=28, pady=20)
        f.pack(fill="both", expand=True)
        tk.Label(f, text=label, bg=_DIALOG_BG, fg=T["cyan"],
                 font=FONT_FANTASY_BOLD, wraplength=560).pack(pady=(0, 12))
        lb_frame = tk.Frame(f, bg=_DIALOG_BG)
        lb_frame.pack(fill="both", expand=True)
        vsb = ttk.Scrollbar(lb_frame, orient="vertical",
                            style="MT.Vertical.TScrollbar")
        self._lb = tk.Listbox(
            lb_frame,
            font=FONT_FANTASY,
            bg="#1a1208",           # slightly lighter than _DIALOG_BG for the list
            fg=T["fg"],
            selectbackground=T["bg_hover"],
            selectforeground=T["fg_header"],
            activestyle="none",
            relief="flat",
            highlightthickness=1,
            highlightbackground=T["border"],
            highlightcolor=T["border_light"],
            yscrollcommand=vsb.set,
            height=min(len(choices), 10),
            width=72,
        )
        vsb.configure(command=self._lb.yview)
        for ch in choices:
            self._lb.insert("end", f"  {ch}")
        self._lb.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._lb.bind("<Double-1>", lambda _: self._ok())
        row = tk.Frame(f, bg=_DIALOG_BG)
        row.pack(pady=(14, 0))
        ttk.Button(row, text="Select", style="OK.TButton",
                   command=self._ok).pack(side="left", padx=8)
        ttk.Button(row, text="Cancel", style="Nav.TButton",
                   command=self._on_cancel).pack(side="left", padx=8)
        self._center()

    def _ok(self) -> None:
        sel = self._lb.curselection()
        if sel:
            self.result = sel[0]
            self.destroy()


class InfoDialog(_BaseDialog):
    """
    Read-only scrollable text dialog — replaces  print(…) + pause()  blocks.

        InfoDialog(root, "Battle Report", "You defeated the bandits!\n…").wait()
    """

    def __init__(self, parent: tk.Widget, title: str, body: str,
                 width: int = 64, height: int = 18) -> None:
        super().__init__(parent, title)
        f = tk.Frame(self, bg=_DIALOG_BG, padx=14, pady=12)
        f.pack(fill="both", expand=True)
        txt = tk.Text(f, bg="#1a1208", fg=T["fg"],
                      font=FONT_FANTASY_S, width=width, height=height,
                      relief="flat", state="normal", wrap="word",
                      insertbackground=T["cyan"],
                      highlightthickness=1,
                      highlightbackground=T["border"],
                      highlightcolor=T["border_light"])
        vsb = ttk.Scrollbar(f, orient="vertical", command=txt.yview,
                            style="MT.Vertical.TScrollbar")
        txt.configure(yscrollcommand=vsb.set)
        txt.insert("1.0", body)
        txt.config(state="disabled")
        txt.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        ttk.Button(self, text="Continue", style="MT.TButton",
                   command=self._ok).pack(pady=(0, 10))
        self.bind("<Return>", lambda _: self._ok())
        self._center()

    def _ok(self) -> None:
        self.result = True
        self.destroy()

# ══════════════════════════════════════════════════════════════════════════════
# TUTORIAL DIALOG  —  step-by-step new-player walkthrough
# ══════════════════════════════════════════════════════════════════════════════

_TUTORIAL_STEPS: List[Dict] = [
    {
        "title": "Welcome, Merchant!",
        "icon":  "⚜",
        "body": (
            "Welcome to Merchant Tycoon — a world of trade, cunning, and fortune!\n\n"
            "You begin as a humble merchant with nothing but a purse of gold and a "
            "dream of wealth. What you do with it is entirely up to you.\n\n"
            "The roads are open, the markets are waiting — let's get you started."
        ),
    },
    {
        "title": "Actions & Days",
        "icon":  "⌛",
        "body": (
            "Each day you have a limited number of Action Slots — shown as circles "
            "at the top of the screen  (● = used,  ○ = remaining).\n\n"
            "Almost everything costs at least one action: trading, travelling, "
            "resting, taking contracts, and more.\n\n"
            "When your slots run out the day ends automatically — so plan carefully. "
            "Every day counts!"
        ),
    },
    {
        "title": "⚖  Trading — Your Bread & Butter",
        "icon":  "⚖",
        "body": (
            "Press Trade to visit the local market. Buy goods cheap, sell them high.\n\n"
            "Prices shift by area, season, and world events. The same wheat that "
            "sells for 8g in Farmland might fetch 22g in the Desert.\n\n"
            "Tip: Check Market Info (📊) before buying to scout the best sell "
            "destinations and spot trending prices before other merchants do."
        ),
    },
    {
        "title": "🗺  Travelling the World",
        "icon":  "🗺",
        "body": (
            "There are eight distinct areas to explore: City, Coast, Mountain, "
            "Farmland, Forest, Desert, Swamp, and Tundra.\n\n"
            "Each area produces and demands different goods — distance creates "
            "profit. Use Travel to move between them.\n\n"
            "Travelling costs action slots, so plan your route and make the most "
            "of each journey."
        ),
    },
    {
        "title": "💰  Growing Your Empire",
        "icon":  "💰",
        "body": (
            "Basic trading is just the beginning. As your gold and reputation grow, "
            "unlock new income streams:\n\n"
            "  🏭  Businesses  — hire workers, earn passive production income\n"
            "  📜  Contracts   — timed delivery jobs with lucrative bonuses\n"
            "  🏦  Finance     — bank deposits, loans, and certificates\n"
            "  🏠  Real Estate — buy land, build properties, collect rent\n"
            "  📈  Stocks      — invest in companies for dividends & growth\n\n"
            "And much much more.\n\n"
            "Visit Licenses (📋) to unlock these as you level up."
        ),
    },
    {
        "title": "⚡  Quick Tips",
        "icon":  "⚡",
        "body": (
            "A few things to keep in mind as you start out:\n\n"
            "  •  Carry weight affects travel speed — travel lighter to move faster.\n"
            "  •  Reputation matters — higher rep means better prices & opportunities.\n"
            "  •  Read News & Events (📰) — world events move prices significantly.\n"
            "  •  The game autosaves at the end of every day (toggle in Settings).\n"
            "  •  Stuck? Press ❓ Help at any time for detailed guidance on any topic."
        ),
    },
    {
        "title": "Ready to Trade!",
        "icon":  "🏆",
        "body": (
            "That's everything you need to get started!\n\n"
            "The markets are alive, the roads are open, and fortune favours "
            "the bold merchant.\n\n"
            "Good luck out there — may your coffers overflow and your "
            "reputation shine across every land.\n\n"
            "                    ✦  Happy Trading!  ✦"
        ),
    },
]


class TutorialDialog(_BaseDialog):
    """
    Multi-step tutorial walkthrough for new players.
    Paginated with Back / Next / Skip navigation and progress dots.
    """

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, "Merchant Tycoon — Tutorial")
        self._step  = 0
        self._total = len(_TUTORIAL_STEPS)

        outer = tk.Frame(self, bg=_DIALOG_BG, padx=32, pady=18)
        outer.pack(fill="both", expand=True)

        # ── Progress dots ─────────────────────────────────────────────────
        dot_row = tk.Frame(outer, bg=_DIALOG_BG)
        dot_row.pack(pady=(0, 8))
        self._dots: List[tk.Label] = []
        for _ in range(self._total):
            d = tk.Label(dot_row, text="●", bg=_DIALOG_BG,
                         fg=T["fg_dim"], font=("Palatino Linotype", 8))
            d.pack(side="left", padx=3)
            self._dots.append(d)

        # ── Large icon ────────────────────────────────────────────────────
        self._lbl_icon = tk.Label(outer, text="", bg=_DIALOG_BG,
                                   fg=T["yellow"],
                                   font=("Palatino Linotype", 36))
        self._lbl_icon.pack(pady=(2, 0))

        # ── Step title ────────────────────────────────────────────────────
        self._lbl_title = tk.Label(outer, text="", bg=_DIALOG_BG,
                                    fg=T["cyan"], font=FONT_FANTASY_TITLE,
                                    wraplength=520)
        self._lbl_title.pack(pady=(6, 14))

        # Separator
        tk.Frame(outer, bg=T["border"], height=1).pack(fill="x", padx=8)

        # ── Body text ─────────────────────────────────────────────────────
        self._lbl_body = tk.Label(outer, text="", bg=_DIALOG_BG,
                                   fg=T["fg"], font=FONT_FANTASY,
                                   wraplength=520, justify="left",
                                   anchor="nw")
        self._lbl_body.pack(fill="x", padx=8, pady=(14, 0))

        # ── Navigation row ────────────────────────────────────────────────
        tk.Frame(outer, bg=T["border"], height=1).pack(fill="x", padx=8, pady=(20, 0))
        nav = tk.Frame(outer, bg=_DIALOG_BG)
        nav.pack(pady=(10, 0), fill="x")

        self._btn_skip = ttk.Button(nav, text="Skip Tutorial",
                                     style="Nav.TButton",
                                     command=self._skip)
        self._btn_skip.pack(side="left")

        self._btn_next = ttk.Button(nav, text="Next →",
                                     style="MT.TButton",
                                     command=self._next)
        self._btn_next.pack(side="right")

        self._btn_back = ttk.Button(nav, text="← Back",
                                     style="Nav.TButton",
                                     command=self._back)
        self._btn_back.pack(side="right", padx=(0, 6))

        # Step counter label (e.g. "3 / 7")
        self._lbl_counter = tk.Label(nav, text="", bg=_DIALOG_BG,
                                      fg=T["fg_dim"], font=FONT_FANTASY_S)
        self._lbl_counter.pack(side="right", padx=12)

        self._render()
        self._center()

    def _render(self) -> None:
        step = _TUTORIAL_STEPS[self._step]
        self._lbl_icon.config(text=step["icon"])
        self._lbl_title.config(text=step["title"])
        self._lbl_body.config(text=step["body"])
        self._lbl_counter.config(text=f"{self._step + 1} / {self._total}")

        # Progress dots
        for i, d in enumerate(self._dots):
            d.config(fg=T["cyan"] if i == self._step else T["fg_dim"],
                     font=("Palatino Linotype", 10 if i == self._step else 8))

        # Button states
        is_last = self._step == self._total - 1
        self._btn_next.config(
            text="✓  Let's Go!" if is_last else "Next →",
            style="OK.TButton"  if is_last else "MT.TButton",
        )
        self._btn_back.config(
            state="normal" if self._step > 0 else "disabled"
        )
        self._btn_skip.config(
            state="disabled" if is_last else "normal"
        )

    def _next(self) -> None:
        if self._step < self._total - 1:
            self._step += 1
            self._render()
        else:
            self._finish()

    def _back(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._render()

    def _skip(self) -> None:
        self.result = False
        self.destroy()

    def _finish(self) -> None:
        self.result = True
        self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
# HOTKEY CAPTURE DIALOG  —  captures a key combination for hotkey remapping
# ══════════════════════════════════════════════════════════════════════════════

class HotkeyDialog(_BaseDialog):
    """Captures a key + optional modifiers to use as a hotkey binding.

    Returns the canonical binding string (e.g. ``"t"``, ``"Control-t"``,
    ``"Tab"``) or ``None`` if the user cancels (bare Escape or close button).
    """

    _PURE_MODS = frozenset((
        "Control_L", "Control_R", "Alt_L", "Alt_R",
        "Shift_L",   "Shift_R",   "Super_L", "Super_R",
        "Caps_Lock", "Num_Lock",  "Scroll_Lock",
    ))

    def __init__(self, parent: tk.Widget, action_label: str) -> None:
        super().__init__(parent, "Set Hotkey")
        self.result: Optional[str] = None
        # Track which modifier keys are currently held — avoids unreliable
        # event.state bit parsing which behaves differently across platforms.
        self._mods: set = set()

        body = tk.Frame(self, bg=_DIALOG_BG)
        body.pack(fill="both", expand=True, padx=22, pady=16)

        tk.Label(body, text=action_label, font=FONT_FANTASY_BOLD,
                 bg=_DIALOG_BG, fg=T["cyan"]).pack(pady=(0, 8))

        tk.Label(
            body,
            text="Press a key combination \u2026\n(bare \u241b  Escape  =  cancel)",
            font=FONT_FANTASY_S, bg=_DIALOG_BG, fg=T["fg"],
            justify="center",
        ).pack(pady=(0, 10))

        self._key_lbl = tk.Label(
            body, text="\u2014 waiting \u2014",
            font=("Consolas", 14, "bold"),
            bg=T["bg_panel"], fg=T["yellow"],
            relief="flat", bd=0,
            padx=14, pady=6, width=18,
        )
        self._key_lbl.pack(pady=(0, 16))

        ttk.Button(body, text="\u2715  Cancel", style="Danger.TButton",
                   command=self._on_cancel).pack()

        self._center()
        self.bind("<KeyPress>",   self._on_key)
        self.bind("<KeyRelease>", self._on_key_release)
        self.focus_force()

    def _on_key_release(self, event: tk.Event) -> None:
        """Clear modifier from the tracked set when its key is released."""
        ks = event.keysym
        if ks.startswith("Control"): self._mods.discard("Control")
        elif ks.startswith("Alt"):   self._mods.discard("Alt")
        elif ks.startswith("Shift"): self._mods.discard("Shift")

    def _on_key(self, event: tk.Event) -> None:
        ks = event.keysym

        # Modifier keys just update the tracked set; don't bind them alone
        if ks.startswith("Control"): self._mods.add("Control"); return
        if ks.startswith("Alt"):     self._mods.add("Alt");     return
        if ks.startswith("Shift"):   self._mods.add("Shift");   return
        if ks in self._PURE_MODS:                              return

        # Bare Escape (no modifiers) = cancel
        if ks == "Escape" and not self._mods:
            self._on_cancel()
            return

        # Tab is reserved by Tkinter's focus-traversal system and cannot
        # be reliably intercepted as a hotkey — reject it here.
        if ks == "Tab" and not self._mods:
            self._key_lbl.config(
                text="Tab is reserved",
                fg=T["red"],
            )
            self.after(900, lambda: self._key_lbl.config(
                text="\u2014 waiting \u2014", fg=T["yellow"]))
            return

        # Build canonical binding string
        parts: List[str] = []
        if "Control" in self._mods: parts.append("Control")
        if "Alt"     in self._mods: parts.append("Alt")
        # Skip Shift for plain letters (we store lowercase); keep it for others
        if "Shift" in self._mods and not (len(ks) == 1 and ks.isalpha()):
            parts.append("Shift")

        key = ks.lower() if (len(ks) == 1 and ks.isalpha()) else ks
        parts.append(key)
        binding = "-".join(parts)

        self.result = binding
        self._key_lbl.config(text=_format_hotkey(binding))
        self.after(350, self.destroy)


# ── Applicant helpers (used by ApplicantDialog / BusinessesScreen._do_hire) ───

_AP_FIRST = [
    "Aldric","Bram","Cora","Dag","Elra","Finn","Greta","Holt","Isa","Jorin",
    "Kev","Lena","Mira","Ned","Ora","Pip","Quinn","Rolf","Sable","Tilda",
    "Ulf","Vera","Wren","Xan","Baxter","Cedric","Delia","Edwyn","Faye",
    "Gareth","Hilda","Ingrid","Jasper","Kira","Lorcan","Mabel","Niles","Oona",
    "Percival","Rhea","Sigrid","Torben","Ursula","Vance","Wendell","Yara","Zane",
    "Alvar","Brunhild","Calder","Draven","Esme","Ferris","Gwenna","Hugo","Ilsa",
    "Jovan","Ketil","Liora","Magnus","Nora","Oswin","Phoebe","Rand","Selwyn",
    "Theron","Una","Viggo","Wulfric","Xenia","Ysolde","Zarko",
]
_AP_LAST = [
    "Miller","Cooper","Smith","Tanner","Fisher","Brewer","Thatcher","Mason",
    "Wright","Fletcher","Barrow","Cotter","Dyer","Eastman","Forges","Galloway",
    "Hayward","Ironsides","Jenks","Kettler","Larder","Moorfield","Nettles",
    "Oldham","Pickwick","Quarry","Rushton","Saltmarsh","Trudge","Underhill",
    "Vickers","Weatherby","Yarrow",
]


def _generate_applicants(count: int = 4) -> List[Dict]:
    """Generate a pool of job applicants matching the CLI mechanic."""
    import random
    applicants: List[Dict] = []
    for _ in range(count):
        prod   = round(random.uniform(0.70, 1.40), 2)
        wage   = round(random.uniform(5.0, 14.0), 1)
        traits: List[str] = []
        if prod >= 1.25:   traits.append("Skilled")
        elif prod <= 0.82: traits.append("Lazy")
        if wage <= 6.5:    traits.append("Cheap")
        elif wage >= 12.0: traits.append("Expensive")
        applicants.append({
            "name":         f"{random.choice(_AP_FIRST)} {random.choice(_AP_LAST)}",
            "wage":         wage,
            "productivity": prod,
            "trait":        ", ".join(traits) if traits else "Average",
        })
    return applicants


class ApplicantDialog(_BaseDialog):
    """
    Shows 4 randomly-generated job applicants in a table.
    Resolves to the chosen applicant dict, or None if cancelled.
    """

    def __init__(self, parent: tk.Widget, business_name: str) -> None:
        super().__init__(parent, f"Hire — {business_name}")
        self._applicants = _generate_applicants(4)

        f = tk.Frame(self, bg=_DIALOG_BG, padx=24, pady=18)
        f.pack(fill="both", expand=True)

        tk.Label(f, text="Review applicants and select one to hire.",
                 font=FONT_FANTASY, bg=_DIALOG_BG,
                 fg=T["fg_dim"]).pack(anchor="w", pady=(0, 10))

        self._tbl = DataTable(f, [
            ("num",   "#",             36),
            ("name",  "Name",         175),
            ("wage",  "Wage/day",      82),
            ("prod",  "Productivity",  100),
            ("trait", "Trait",         130),
        ], height=4)
        self._tbl.pack(fill="x")

        self._reload_table()

        tk.Label(f, font=FONT_MONO_S, bg=_DIALOG_BG, fg=T["grey"],
                 text="Productivity multiplies daily output.  Wage is deducted each day."
                 ).pack(anchor="w", pady=(8, 12))

        row = tk.Frame(f, bg=_DIALOG_BG)
        row.pack()
        ttk.Button(row, text="Hire Selected", style="OK.TButton",
                   command=self._ok).pack(side="left", padx=8)
        ttk.Button(row, text="↻ New Applicants", style="MT.TButton",
                   command=self._refresh_applicants).pack(side="left", padx=8)
        ttk.Button(row, text="Cancel", style="Nav.TButton",
                   command=self._on_cancel).pack(side="left", padx=8)
        self._tbl.bind_double(lambda _: self._ok())
        self._center()

    def _reload_table(self) -> None:
        rows = []
        for i, ap in enumerate(self._applicants, 1):
            prod  = ap["productivity"]
            trait = ap.get("trait", "Average")
            tag   = ("green"  if prod >= 1.25 or "Cheap" in trait
                     else ("red" if prod <= 0.82 or "Expensive" in trait
                           else "dim"))
            rows.append({
                "num":   str(i),
                "name":  ap["name"],
                "wage":  f"{ap['wage']:.1f}g",
                "prod":  f"{ap['productivity']:.2f}\u00d7",
                "trait": trait,
                "tag":   tag,
            })
        self._tbl.load(rows, tag_key="tag")

    def _refresh_applicants(self) -> None:
        self._applicants = _generate_applicants(4)
        self._reload_table()

    def _ok(self) -> None:
        sel = self._tbl.selected()
        if not sel:
            return
        try:
            idx = int(sel.get("num", "0")) - 1
        except (ValueError, TypeError):
            return
        if 0 <= idx < len(self._applicants):
            self.result = self._applicants[idx]
            self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
# LEASE APPLICANT DIALOG
# ══════════════════════════════════════════════════════════════════════════════

_TENANT_RELIABILITY: List[Tuple[str, str, str]] = [
    ("Excellent",   "Reliable payer, keeps the property well.",          T["green"]),
    ("Good",        "Generally dependable, occasional minor delay.",     T["cyan"]),
    ("Average",     "Pays on time most months.",                         T["fg"]),
    ("Risky",       "May be late with payments some months.",            T["yellow"]),
    ("Troublesome", "History of payment issues — caveat emptor.",        T["red"]),
]


def _generate_lease_applicants(daily_rate: float, count: int = 3) -> List[Dict]:
    """Generate prospective tenants with variable offered rates and reliability."""
    import random
    applicants: List[Dict] = []
    for _ in range(count):
        rel_idx   = random.choices(range(5), weights=[1, 3, 5, 2, 1])[0]
        rel_label, rel_desc, rel_col = _TENANT_RELIABILITY[rel_idx]
        # Risky / troublesome tenants may offer above-market rates to sweeten deal
        if rel_idx >= 3:
            rate_mult = round(random.uniform(0.90, 1.35), 2)
        elif rel_idx == 0:
            rate_mult = round(random.uniform(0.85, 1.10), 2)
        else:
            rate_mult = round(random.uniform(0.75, 1.20), 2)
        applicants.append({
            "name":          f"{random.choice(_AP_FIRST)} {random.choice(_AP_LAST)}",
            "rate_mult":     rate_mult,
            "offered_daily": round(daily_rate * rate_mult, 2),
            "reliability":   rel_label,
            "rel_desc":      rel_desc,
            "rel_color":     rel_col,
        })
    return applicants


class LeaseApplicantDialog(_BaseDialog):
    """
    Review 3 prospective tenants for a property lease at variable rates.
    Returns: {"name": str, "rate_mult": float, "reliability": str} or None.
    """

    def __init__(self, parent: tk.Widget, prop_name: str, std_daily: float) -> None:
        super().__init__(parent, f"Lease Applicants \u2014 {prop_name}")
        self._std_daily  = std_daily
        self._applicants = _generate_lease_applicants(std_daily, count=3)

        f = tk.Frame(self, bg=_DIALOG_BG, padx=24, pady=18)
        f.pack(fill="both", expand=True)

        # Info header
        info = tk.Frame(f, bg="#1a1208", padx=10, pady=6)
        info.pack(fill="x", pady=(0, 10))
        tk.Label(info,
                 text=f"Standard lease rate:  {std_daily:.2f}g / day   "
                      f"(~{std_daily * 28:.0f}g / month)",
                 bg="#1a1208", fg=T["cyan"],
                 font=FONT_FANTASY_BOLD).pack(anchor="w")
        tk.Label(info,
                 text="Select a tenant and their negotiated rate becomes your passive income.",
                 bg="#1a1208", fg=T["fg_dim"],
                 font=FONT_FANTASY_S).pack(anchor="w")

        self._tbl = DataTable(f, [
            ("num",         "#",            36),
            ("name",        "Applicant",   175),
            ("rate",        "Daily Rate",   80),
            ("diff",        "vs. Standard", 90),
            ("monthly",     "Monthly Est.", 92),
            ("reliability", "Reliability", 110),
        ], height=4)
        self._tbl.pack(fill="x")
        self._reload_table()

        tk.Label(f,
                 text="Risky / Troublesome tenants may offer higher rates but can miss payments.",
                 bg=_DIALOG_BG, fg=T["grey"], font=FONT_MONO_S
                 ).pack(anchor="w", pady=(8, 12))

        row = tk.Frame(f, bg=_DIALOG_BG)
        row.pack()
        ttk.Button(row, text="Lease to Selected",    style="OK.TButton",
                   command=self._ok).pack(side="left", padx=6)
        ttk.Button(row, text="\u21bb New Applicants", style="MT.TButton",
                   command=self._refresh_applicants).pack(side="left", padx=6)
        ttk.Button(row, text="Post Standard Rate",   style="MT.TButton",
                   command=self._standard_lease).pack(side="left", padx=6)
        ttk.Button(row, text="Cancel",               style="Nav.TButton",
                   command=self._on_cancel).pack(side="left", padx=6)

        self._tbl.bind_double(lambda _: self._ok())
        self._center()

    def _reload_table(self) -> None:
        rows = []
        for i, ap in enumerate(self._applicants, 1):
            diff_pct = (ap["rate_mult"] - 1.0) * 100
            if ap["rate_mult"] >= 1.10:
                tag = "green"
            elif ap["rate_mult"] < 0.85:
                tag = "dim"
            else:
                tag = "cyan"
            rows.append({
                "num":         str(i),
                "name":        ap["name"],
                "rate":        f"{ap['offered_daily']:.2f}g/day",
                "diff":        f"{diff_pct:+.0f}%",
                "monthly":     f"~{ap['offered_daily'] * 28:.0f}g",
                "reliability": ap["reliability"],
                "tag":         tag,
            })
        self._tbl.load(rows, tag_key="tag")

    def _refresh_applicants(self) -> None:
        self._applicants = _generate_lease_applicants(self._std_daily, count=3)
        self._reload_table()

    def _standard_lease(self) -> None:
        self.result = {"name": "Standard Lease", "rate_mult": 1.0, "reliability": "Average"}
        self.destroy()

    def _ok(self) -> None:
        sel = self._tbl.selected()
        if not sel:
            return
        try:
            idx = int(sel.get("num", "0")) - 1
        except (ValueError, TypeError):
            return
        if 0 <= idx < len(self._applicants):
            self.result = self._applicants[idx]
            self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
# BUILD CARD DIALOG — visual card grid for selecting construction project
# ══════════════════════════════════════════════════════════════════════════════

_BUILD_ICONS = {
    "cottage":   "🏡",
    "townhouse": "🏘",
    "shop":      "🏪",
    "warehouse": "🏭",
    "inn":       "🍺",
    "workshop":  "🔨",
    "manor":     "🏰",
    "dockyard":  "⚓",
    "estate":    "🌟",
}


class BuildCardDialog(_BaseDialog):
    """
    Grid of property cards for selecting what to build — much more readable
    than a plain listbox.  Double-click a card or select + click Build.
    Returns the integer index into the `buildable` list, or None.
    """

    _CARD_BG      = "#1a1208"
    _CARD_SEL_BG  = "#3a2612"
    _CARD_COLS    = 3

    def __init__(self, parent: tk.Widget, title: str,
                 buildable: List[str], area_mult: float) -> None:
        super().__init__(parent, title)
        self._selected_idx = tk.IntVar(value=-1)
        self._card_frames: List[tk.Frame] = []

        outer = tk.Frame(self, bg=_DIALOG_BG, padx=18, pady=14)
        outer.pack(fill="both", expand=True)

        tk.Label(outer,
                 text="Select a project — click to highlight, double-click to confirm.",
                 bg=_DIALOG_BG, fg=T["fg_dim"],
                 font=FONT_FANTASY_S).pack(anchor="w", pady=(0, 10))

        grid_f = tk.Frame(outer, bg=_DIALOG_BG)
        grid_f.pack(fill="both", expand=True)

        COLS = self._CARD_COLS

        for i, key in enumerate(buildable):
            cat   = PROPERTY_CATALOGUE[key]
            cost  = round(cat["build_cost"] * area_mult, 0)
            val   = round(cat["base_value"]  * area_mult, 0)
            lease = round(cat.get("base_lease", 0) * area_mult, 1)
            icon  = _BUILD_ICONS.get(key, "🏗")
            row_i = i // COLS
            col_i = i % COLS

            card = tk.Frame(grid_f, bg=self._CARD_BG,
                            highlightthickness=1,
                            highlightbackground=T["border"],
                            highlightcolor=T["border_light"],
                            padx=12, pady=10, cursor="hand2")
            card.grid(row=row_i, column=col_i, padx=8, pady=8, sticky="nsew")
            grid_f.columnconfigure(col_i, weight=1)

            # Card header: icon + name
            hdr = tk.Frame(card, bg=self._CARD_BG)
            hdr.pack(fill="x", anchor="w")
            tk.Label(hdr, text=icon, bg=self._CARD_BG, font=("Segoe UI Emoji", 18)
                     ).pack(side="left")
            tk.Label(hdr, text=f"  {cat.get('name', key).upper()}",
                     bg=self._CARD_BG, fg=T["cyan"],
                     font=FONT_FANTASY_BOLD).pack(side="left", anchor="sw")
            tk.Frame(card, bg=T["border_light"], height=1).pack(fill="x", pady=(4, 6))

            # Stats grid
            stats = [
                ("Cost:",     f"{cost:,.0f}g",      T["yellow"]),
                ("Duration:", f"{cat['build_days']} days", T["fg"]),
                ("Value:",    f"~{val:,.0f}g",       T["green"]),
                ("Lease/day:",f"~{lease:.1f}g",      T["cyan"]),
            ]
            for lbl_text, val_text, val_col in stats:
                sr = tk.Frame(card, bg=self._CARD_BG)
                sr.pack(fill="x", pady=1)
                tk.Label(sr, text=lbl_text, bg=self._CARD_BG, fg=T["fg_dim"],
                         font=FONT_MONO_S, width=10, anchor="w").pack(side="left")
                tk.Label(sr, text=val_text, bg=self._CARD_BG, fg=val_col,
                         font=FONT_MONO_S, anchor="w").pack(side="left")

            # Bind click & double-click for the card and all its children
            card_idx = i

            def _make_handlers(idx: int, frm: tk.Frame):
                def _select(e=None):
                    self._selected_idx.set(idx)
                    for cf in self._card_frames:
                        cf.config(bg=self._CARD_BG,
                                  highlightbackground=T["border"])
                        for child in cf.winfo_children():
                            _deep_bg(child, self._CARD_BG)
                    frm.config(bg=self._CARD_SEL_BG,
                               highlightbackground=T["border_light"])
                    for child in frm.winfo_children():
                        _deep_bg(child, self._CARD_SEL_BG)

                def _confirm(e=None):
                    _select()
                    self._ok()

                return _select, _confirm

            sel_fn, confirm_fn = _make_handlers(i, card)
            card.bind("<Button-1>", sel_fn)
            card.bind("<Double-Button-1>", confirm_fn)
            for w in card.winfo_children():
                w.bind("<Button-1>", sel_fn)
                w.bind("<Double-Button-1>", confirm_fn)
                for ww in w.winfo_children():
                    ww.bind("<Button-1>", sel_fn)
                    ww.bind("<Double-Button-1>", confirm_fn)

            self._card_frames.append(card)

        # Bottom row: buttons
        hint_row = (len(buildable) - 1) // COLS + 1
        btn_row_f = tk.Frame(outer, bg=_DIALOG_BG)
        btn_row_f.pack(pady=(10, 0))
        ttk.Button(btn_row_f, text="  \u2713  Build This", style="OK.TButton",
                   command=self._ok).pack(side="left", padx=8)
        ttk.Button(btn_row_f, text="Cancel", style="Nav.TButton",
                   command=self._on_cancel).pack(side="left", padx=8)

        self._center()

    def _ok(self) -> None:
        idx = self._selected_idx.get()
        if idx >= 0:
            self.result = idx
            self.destroy()


def _deep_bg(widget: tk.Widget, color: str) -> None:
    """Recursively update bg of a widget and its direct children."""
    try:
        widget.config(bg=color)
        for child in widget.winfo_children():
            try:
                child.config(bg=color)
            except tk.TclError:
                pass
    except tk.TclError:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# ACHIEVEMENT TOAST
# ══════════════════════════════════════════════════════════════════════════════

class AchievementToast(tk.Toplevel):
    """
    Non-modal achievement popup — replaces CLI achievement banner.
    Slides in from bottom-right, auto-dismisses after AUTO_CLOSE_MS, or on click.
    Multiple simultaneous toasts stack vertically without overlapping.

        AchievementToast(root, ach_dict)   # fire-and-forget
    """

    AUTO_CLOSE_MS = 5_000
    _SLIDE_STEPS  = 12
    _SLIDE_MS     = 16

    # Class-level stack — tracks all live toasts for position calculation
    _active: List["AchievementToast"] = []

    _TIER_COL = {
        "bronze":   T["yellow"],
        "silver":   T["white"],
        "gold":     T["cyan"],
        "platinum": T["cyan"],
        "":         T["green"],
    }

    def __init__(self, parent: tk.Widget, ach: Dict) -> None:
        super().__init__(parent)
        self.overrideredirect(True)
        self.configure(bg=T["border_light"])
        self.attributes("-topmost", True)

        tier_col = self._TIER_COL.get(ach.get("tier", ""), T["green"])
        inner = tk.Frame(self, bg=T["bg_panel"], padx=16, pady=12)
        inner.pack(padx=2, pady=2)

        icon = ach.get("icon", "★")
        tk.Label(inner, text=f"  {icon}  ACHIEVEMENT UNLOCKED!",
                 bg=T["bg_panel"], fg=T["yellow"],
                 font=FONT_FANTASY_BOLD).pack(anchor="w")
        ttk.Separator(inner, style="MT.TSeparator").pack(fill="x", pady=(4, 2))

        tk.Label(inner, text=ach.get("name", ""),
                 bg=T["bg_panel"], fg=tier_col,
                 font=FONT_FANTASY_BOLD).pack(anchor="w")

        desc = ach.get("desc", "")
        if desc:
            tk.Label(inner, text=desc, bg=T["bg_panel"], fg=T["fg"],
                     font=FONT_FANTASY_S, wraplength=300,
                     justify="left").pack(anchor="w", pady=(3, 0))

        hint = ach.get("hint", "")
        if hint and hint != "???":
            tk.Label(inner, text=hint, bg=T["bg_panel"], fg=T["grey"],
                     font=FONT_FANTASY_S, wraplength=300,
                     justify="left").pack(anchor="w", pady=(2, 0))

        # Compute stacked final position (bottom-right, stacks upward)
        self.update_idletasks()
        slot    = len(AchievementToast._active)
        h       = self.winfo_height()
        self._px      = parent.winfo_rootx() + parent.winfo_width() - self.winfo_width() - 20
        py_final      = parent.winfo_rooty() + parent.winfo_height() - (slot + 1) * (h + 8) - 20
        py_start      = py_final + h + 20
        self._py_final = py_final
        AchievementToast._active.append(self)
        self.geometry(f"+{self._px}+{py_start}")

        for widget in self.winfo_children() + [self, inner]:
            try:
                widget.bind("<Button-1>", lambda _: self._safe_destroy())
            except tk.TclError:
                pass

        # slide up into view
        self._slide_in(py_start, 0, self._SLIDE_STEPS)
        self.after(self.AUTO_CLOSE_MS, self._safe_destroy)

    def _slide_in(self, py_start: int, step: int, total: int) -> None:
        if step >= total:
            try:
                self.geometry(f"+{self._px}+{self._py_final}")
            except tk.TclError:
                pass
            return
        t = step / total
        # ease-out quad: fast start, gentle landing
        t_eased = 1 - (1 - t) ** 2
        py = int(py_start + (self._py_final - py_start) * t_eased)
        try:
            self.geometry(f"+{self._px}+{py}")
            self.after(self._SLIDE_MS,
                       lambda: self._slide_in(py_start, step + 1, total))
        except tk.TclError:
            pass

    def _safe_destroy(self) -> None:
        try:
            AchievementToast._active.remove(self)
        except ValueError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass

# ══════════════════════════════════════════════════════════════════════════════
# GAME TOAST  —  Lightweight action-feedback notification
# ══════════════════════════════════════════════════════════════════════════════

class GameToast(tk.Toplevel):
    """
    Short-lived, stacking action-feedback popup.
    Slides in from the right edge; auto-dismisses after 2.5 s.
    Multiple toasts stack vertically without overlapping.

        GameToast(root, "Sold 10 Wheat for 120g", T["green"])
    """

    _active: List["GameToast"] = []   # class-level stack
    _SLIDE_STEPS = 10
    _SLIDE_MS    = 14
    _DURATION_MS = 2_500

    def __init__(self, parent: tk.Widget, text: str,
                 colour: str = None) -> None:
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        colour = colour or T["fg"]

        outer = tk.Frame(self, bg=T["border"], padx=1, pady=1)
        outer.pack()
        inner = tk.Frame(outer, bg=T["bg_panel"], padx=10, pady=7)
        inner.pack()
        # Coloured left accent bar
        tk.Frame(inner, bg=colour, width=3).pack(side="left", fill="y", padx=(0, 8))
        tk.Label(inner, text=text, bg=T["bg_panel"], fg=T["fg"],
                 font=FONT_FANTASY_S, wraplength=260,
                 justify="left").pack(side="left")

        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()

        slot     = len(GameToast._active)
        GameToast._active.append(self)

        px_final = parent.winfo_rootx() + parent.winfo_width() - w - 14
        py       = parent.winfo_rooty() + 52 + slot * (h + 5)
        px_start = px_final + w + 30

        self._px_final = px_final
        self._py       = py
        self.geometry(f"+{px_start}+{py}")

        self._slide_in(px_start, 0, self._SLIDE_STEPS)
        self.after(self._DURATION_MS, self._dismiss)
        for w_bind in (self, inner, outer):
            try:
                w_bind.bind("<Button-1>", lambda _: self._dismiss())
            except tk.TclError:
                pass

    def _slide_in(self, px_start: int, step: int, total: int) -> None:
        if step >= total:
            try:
                self.geometry(f"+{self._px_final}+{self._py}")
            except tk.TclError:
                pass
            return
        t = step / total
        t_eased = 1 - (1 - t) ** 2   # ease-out quad
        px = int(px_start + (self._px_final - px_start) * t_eased)
        try:
            self.geometry(f"+{px}+{self._py}")
            self.after(self._SLIDE_MS,
                       lambda: self._slide_in(px_start, step + 1, total))
        except tk.TclError:
            pass

    def _dismiss(self) -> None:
        try:
            GameToast._active.remove(self)
        except ValueError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass

# ══════════════════════════════════════════════════════════════════════════════
# PROFIT FLASH ANIMATION
# ══════════════════════════════════════════════════════════════════════════════

class ProfitFlash:
    """
    Semi-transparent gold overlay animation for profit milestones.

    Tiers (configurable in Settings):
        >=  100 g  brief shimmer   (alpha 0.16, ~0.5 s)
        >=  500 g  element flash   (alpha 0.32, ~0.8 s)
        >= 1000 g  background wash (alpha 0.52, ~1.3 s)
        >= 5000 g  casino jackpot  (alpha 0.82, ~2.2 s)
    """

    _COLOR = "#FFD700"   # classic metallic gold

    @staticmethod
    def trigger(app: "GameApp", amount: float) -> None:
        if not getattr(app, "profit_animations", True):
            return
        if amount >= 5000:
            ProfitFlash._jackpot(app)
        elif amount >= 1000:
            ProfitFlash._fade(app, peak=0.52, in_ms=120, hold_ms=700, out_ms=500)
        elif amount >= 500:
            ProfitFlash._fade(app, peak=0.32, in_ms=80,  hold_ms=400, out_ms=380)
        else:
            ProfitFlash._fade(app, peak=0.16, in_ms=60,  hold_ms=200, out_ms=280)

    @staticmethod
    def _overlay(app: "GameApp") -> tk.Toplevel:
        app.update_idletasks()
        ov = tk.Toplevel(app)
        ov.overrideredirect(True)
        ov.configure(bg=ProfitFlash._COLOR)
        ov.attributes("-alpha", 0.0)
        ov.attributes("-topmost", True)
        ov.geometry(
            f"{app.winfo_width()}x{app.winfo_height()}"
            f"+{app.winfo_x()}+{app.winfo_y()}"
        )
        return ov

    @staticmethod
    def _fade(app: "GameApp", peak: float,
              in_ms: int, hold_ms: int, out_ms: int) -> None:
        try:
            ov        = ProfitFlash._overlay(app)
            IN_STEPS  = max(4, in_ms  // 16)
            OUT_STEPS = max(4, out_ms // 16)
            i_ms      = max(1, in_ms  // IN_STEPS)
            o_ms      = max(1, out_ms // OUT_STEPS)

            def fade_in(i: int) -> None:
                if not ov.winfo_exists():
                    return
                ov.attributes("-alpha", peak * i / IN_STEPS)
                if i < IN_STEPS:
                    ov.after(i_ms, lambda: fade_in(i + 1))
                else:
                    ov.after(hold_ms, lambda: fade_out(OUT_STEPS))

            def fade_out(i: int) -> None:
                if not ov.winfo_exists():
                    return
                ov.attributes("-alpha", peak * i / OUT_STEPS)
                if i > 0:
                    ov.after(o_ms, lambda: fade_out(i - 1))
                else:
                    try:
                        ov.destroy()
                    except Exception:
                        pass

            fade_in(1)
        except Exception:
            pass

    @staticmethod
    def _jackpot(app: "GameApp") -> None:
        """Casino slot-machine: 5 rapid burst flashes -> sustained glow -> smooth fade."""
        try:
            ov = ProfitFlash._overlay(app)
            # Each entry: (alpha, hold_ms)
            schedule = [
                (0.60, 90),  (0.04, 55),
                (0.68, 95),  (0.04, 55),
                (0.74, 100), (0.04, 55),
                (0.78, 110), (0.04, 45),
                (0.82, 120), (0.04, 40),
                (0.62, 1500),                              # sustained bright glow
                (0.54, 80), (0.46, 80), (0.38, 80),       # smooth fade-out
                (0.30, 80), (0.22, 80), (0.14, 80),
                (0.07, 80), (0.00, 80),
            ]

            def run(idx: int) -> None:
                if not ov.winfo_exists():
                    return
                if idx >= len(schedule):
                    try:
                        ov.destroy()
                    except Exception:
                        pass
                    return
                alpha, delay = schedule[idx]
                ov.attributes("-alpha", alpha)
                ov.after(delay, lambda: run(idx + 1))

            run(0)
        except Exception:
            pass

# ══════════════════════════════════════════════════════════════════════════════
# SOUND MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class SoundManager:
    """
    Lightweight audio manager for Merchant Tycoon.

    Sound effects live in  <script_dir>/sounds/<name>.{wav,ogg,mp3}
    Music tracks live in   <script_dir>/music/<name>.{ogg,mp3,wav}

    pygame.mixer is used when available; every call silently no-ops if
    pygame is not installed so the game launches fine without audio too.

    Quick-start:
        app.sound.play_sfx("buy")          # one-shot sound effect
        app.sound.play_music("tavern")     # loop background music
        app.sound.fade_music()             # fade out current track
        app.sound.stop_music()
        app.sound.sfx_volume   = 0.8       # 0.0 – 1.0
        app.sound.music_volume = 0.5
        app.sound.muted        = True      # silence everything
    """

    _SFX_EXTS   = (".wav", ".ogg", ".mp3")
    _MUSIC_EXTS = (".ogg", ".mp3", ".wav")

    def __init__(self, base_dir: str) -> None:
        self._base_dir      = base_dir
        self._sounds_dir    = os.path.join(base_dir, "sounds")
        self._music_dir     = os.path.join(base_dir, "music")
        self._cache: Dict[str, object] = {}   # name → pygame.Sound
        self._current_track: Optional[str] = None
        self._sfx_volume    = 0.7
        self._music_volume  = 0.5
        self._muted         = False
        self._enabled       = False
        self._pygame        = None
        try:
            import pygame
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            self._pygame = pygame
            self._enabled = True
        except Exception:
            pass   # audio is optional — game works silently without pygame

    # ── Volume properties ────────────────────────────────────────────────────

    @property
    def sfx_volume(self) -> float:
        return self._sfx_volume

    @sfx_volume.setter
    def sfx_volume(self, v: float) -> None:
        self._sfx_volume = max(0.0, min(1.0, float(v)))

    @property
    def music_volume(self) -> float:
        return self._music_volume

    @music_volume.setter
    def music_volume(self, v: float) -> None:
        self._music_volume = max(0.0, min(1.0, float(v)))
        if self._enabled and not self._muted:
            try:
                self._pygame.mixer.music.set_volume(self._music_volume)
            except Exception:
                pass

    @property
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, v: bool) -> None:
        self._muted = bool(v)
        if self._enabled:
            try:
                self._pygame.mixer.music.set_volume(
                    0.0 if self._muted else self._music_volume)
            except Exception:
                pass

    @property
    def enabled(self) -> bool:
        """True if pygame.mixer initialised successfully."""
        return self._enabled

    # ── Sound effects ────────────────────────────────────────────────────────

    def play_sfx(self, name: str) -> None:
        """Play a one-shot sound effect by name (no extension needed)."""
        if not self._enabled or self._muted:
            return
        sound = self._load_sfx(name)
        if sound:
            try:
                sound.set_volume(self._sfx_volume)
                sound.play()
            except Exception:
                pass

    def _load_sfx(self, name: str) -> Optional[object]:
        """Return a cached pygame.Sound, loading it on first use."""
        if name in self._cache:
            return self._cache[name]
        for ext in self._SFX_EXTS:
            path = os.path.join(self._sounds_dir, f"{name}{ext}")
            if os.path.isfile(path):
                try:
                    sound = self._pygame.mixer.Sound(path)
                    self._cache[name] = sound
                    return sound
                except Exception:
                    pass
        return None

    def _load_sfx_direct(self, name: str) -> Optional[object]:
        """Load a sound file from base_dir (script directory) by name."""
        if name in self._cache:
            return self._cache[name]
        for ext in self._SFX_EXTS:
            path = os.path.join(self._base_dir, f"{name}{ext}")
            if os.path.isfile(path):
                try:
                    sound = self._pygame.mixer.Sound(path)
                    self._cache[name] = sound
                    return sound
                except Exception:
                    pass
        return None

    def play_coin_sfx(self) -> None:
        """Play a random coin purse sound on purchase or sale."""
        import random
        if not self._enabled or self._muted:
            return
        name = random.choice(("coinPurse1", "coinPurse2", "coinPurse3"))
        sound = self._load_sfx_direct(name)
        if sound:
            try:
                sound.set_volume(self._sfx_volume)
                sound.play()
            except Exception:
                pass

    # ── Music ────────────────────────────────────────────────────────────────

    def play_music(self, track: str, loop: bool = True,
                   fade_ms: int = 1500) -> None:
        """Start (or cross-fade to) a named music track. Ignores repeats."""
        if not self._enabled or track == self._current_track:
            return
        for ext in self._MUSIC_EXTS:
            path = os.path.join(self._music_dir, f"{track}{ext}")
            if os.path.isfile(path):
                try:
                    self._pygame.mixer.music.fadeout(max(fade_ms // 2, 1))
                    self._pygame.mixer.music.load(path)
                    self._pygame.mixer.music.set_volume(
                        0.0 if self._muted else self._music_volume)
                    self._pygame.mixer.music.play(-1 if loop else 0,
                                                   fade_ms=fade_ms)
                    self._current_track = track
                except Exception:
                    pass
                return

    def stop_music(self) -> None:
        """Immediately stop background music."""
        if self._enabled:
            try:
                self._pygame.mixer.music.stop()
            except Exception:
                pass
        self._current_track = None

    def fade_music(self, ms: int = 1500) -> None:
        """Fade out background music over *ms* milliseconds."""
        if self._enabled:
            try:
                self._pygame.mixer.music.fadeout(ms)
            except Exception:
                pass
        self._current_track = None

    # ── Settings persistence ─────────────────────────────────────────────────

    def apply_settings(self, sfx_vol: float, music_vol: float,
                        muted: bool) -> None:
        """Restore saved audio settings (called by SettingsScreen on load)."""
        self.sfx_volume   = sfx_vol
        self.music_volume = music_vol
        self.muted        = muted

    def status_string(self) -> str:
        """Return a human-readable audio status line for the Settings screen."""
        if not self._enabled:
            return "Audio unavailable (pygame not installed)"
        state = "Muted" if self._muted else "On"
        return (f"{state}  ·  SFX {int(self._sfx_volume * 100)}%  ·  "
                f"Music {int(self._music_volume * 100)}%")


# ══════════════════════════════════════════════════════════════════════════════
# STUB SCREEN FACTORY
# Each screen below is a placeholder until the corresponding CLI menu is
# converted. Replace the stub with a real Screen subclass when ready.
# ══════════════════════════════════════════════════════════════════════════════

class _ResizeGrip(tk.Frame):
    """Transparent resize strips placed at all 8 window edges/corners."""

    _E = 6   # grab-zone thickness in pixels
    _CURSORS = {
        "n":  "top_side",            "s":  "bottom_side",
        "e":  "right_side",          "w":  "left_side",
        "ne": "top_right_corner",    "nw": "top_left_corner",
        "se": "bottom_right_corner", "sw": "bottom_left_corner",
    }

    def __init__(self, app: "GameApp", side: str) -> None:
        super().__init__(app, bg=T["bg"], cursor=self._CURSORS[side],
                         highlightthickness=0)
        self._app  = app
        self._side = side
        self._sx = self._sy = self._sw = self._sh = self._wx = self._wy = 0
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>",     self._drag)

    def _press(self, e: tk.Event) -> None:
        self._sx = e.x_root;  self._sy = e.y_root
        self._sw = self._app.winfo_width()
        self._sh = self._app.winfo_height()
        self._wx = self._app.winfo_x()
        self._wy = self._app.winfo_y()

    def _drag(self, e: tk.Event) -> None:
        dx = e.x_root - self._sx;  dy = e.y_root - self._sy
        w, h, x, y = self._sw, self._sh, self._wx, self._wy
        mw, mh = self._app.MIN_W, self._app.MIN_H
        s = self._side
        if "e" in s:
            w = max(mw, self._sw + dx)
        if "w" in s:
            w = max(mw, self._sw - dx)
            x = self._wx + self._sw - w
        if "s" in s:
            h = max(mh, self._sh + dy)
        if "n" in s:
            h = max(mh, self._sh - dy)
            y = self._wy + self._sh - h
        self._app.geometry(f"{w}x{h}+{x}+{y}")


class CustomTitleBar(tk.Frame):
    """
    Draggable custom title bar that replaces the native OS window chrome.
    Provides: drag-to-move, minimize, maximize, and close.
    """

    def __init__(self, parent: tk.Widget, app: "GameApp") -> None:
        super().__init__(parent, bg=T["bg_panel"], height=36)
        self.app = app
        self.pack_propagate(False)
        self._drag_x = 0
        self._drag_y = 0

        # Decorative top accent line
        tk.Frame(self, bg=T["border_light"], height=2).pack(fill="x", side="top")

        inner = tk.Frame(self, bg=T["bg_panel"])
        inner.pack(fill="both", expand=True, padx=4)

        # App title (left)
        tk.Label(inner, text="⚘  MERCHANT TYCOON",
                 bg=T["bg_panel"], fg=T["cyan"],
                 font=FONT_FANTASY_BOLD).pack(side="left", padx=8)

        # Window controls (right to left: close, maximize, minimize)
        close_btn = tk.Label(inner, text="  ✕  ", bg=T["bg_panel"],
                             fg=T["grey"], font=FONT_FANTASY_BOLD, cursor="hand2")
        close_btn.pack(side="right", padx=(2, 6))
        close_btn.bind("<Button-1>", lambda _: app.quit_game())
        close_btn.bind("<Enter>",    lambda e: e.widget.config(bg="#5a1010", fg=T["fg_header"]))
        close_btn.bind("<Leave>",    lambda e: e.widget.config(bg=T["bg_panel"], fg=T["grey"]))

        max_btn = tk.Label(inner, text="  □  ", bg=T["bg_panel"],
                           fg=T["grey"], font=FONT_FANTASY_BOLD, cursor="hand2")
        max_btn.pack(side="right", padx=2)
        max_btn.bind("<Button-1>", lambda _: app._toggle_maximize(max_btn))
        max_btn.bind("<Enter>",    lambda e: e.widget.config(bg=T["bg_button_act"], fg=T["fg"]))
        max_btn.bind("<Leave>",    lambda e: e.widget.config(bg=T["bg_panel"],      fg=T["grey"]))

        min_btn = tk.Label(inner, text="  —  ", bg=T["bg_panel"],
                           fg=T["grey"], font=FONT_FANTASY_BOLD, cursor="hand2")
        min_btn.pack(side="right", padx=2)
        min_btn.bind("<Button-1>", lambda _: app._minimize_window())
        min_btn.bind("<Enter>",    lambda e: e.widget.config(bg=T["bg_button_act"], fg=T["fg"]))
        min_btn.bind("<Leave>",    lambda e: e.widget.config(bg=T["bg_panel"],      fg=T["grey"]))

        # Bottom separator
        tk.Frame(self, bg=T["border"], height=1).pack(fill="x", side="bottom")

        # Drag bindings on the bar and inner frame
        for widget in (self, inner):
            widget.bind("<ButtonPress-1>",  self._on_drag_start)
            widget.bind("<B1-Motion>",      self._on_drag_move)

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_x = event.x_root - self.app.winfo_x()
        self._drag_y = event.y_root - self.app.winfo_y()

    def _on_drag_move(self, event: tk.Event) -> None:
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.app.geometry(f"+{x}+{y}")


def _make_stub(display_name: str) -> type:
    """Return a placeholder Screen class for a not-yet-converted menu."""

    class _StubScreen(Screen):
        _display_name = display_name

        def build(self) -> None:
            sf = ScrollableFrame(self)
            sf.pack(fill="both", expand=True)
            inner = sf.inner

            self.section_label(inner, self._display_name).pack(
                anchor="w", padx=20, pady=(16, 8))
            ttk.Separator(inner, style="MT.TSeparator").pack(
                fill="x", padx=20, pady=4)
            ttk.Label(inner,
                      text=f"[ {self._display_name} — conversion in progress ]",
                      style="Dim.TLabel").pack(anchor="w", padx=20, pady=6)
            ttk.Separator(inner, style="MT.TSeparator").pack(
                fill="x", padx=20, pady=4)
            self.back_button(inner).pack(anchor="w", padx=20, pady=(8, 0))

        def refresh(self) -> None:
            pass

    _StubScreen.__name__ = f"{display_name.replace(' ', '').replace('/', '')}Screen"
    return _StubScreen


# ── Screen stubs — replace one at a time as the conversion progresses ─────────
class TradeScreen(Screen):
    """
    Trade screen — Buy, Sell, and Arbitrage tabs.
    Mirrors trade_menu(), _buy_items(), _sell_items(), _haggle(),
    and arbitrage_menu() from the CLI.
    """

    _BUY_COLS = [
        ("num",    "#",          36),
        ("item",   "Item",      178),
        ("cat",    "Category",  108),
        ("price",  "Price",      78),
        ("stock",  "Stock",      58),
        ("trend",  "Trend",      52),
        ("rarity", "Rarity",     80),
    ]
    _SELL_COLS = [
        ("num",    "#",          36),
        ("item",   "Item",      178),
        ("have",   "Have",       52),
        ("sell_p", "Sell @",     78),
        ("paid",   "Paid @",     78),
        ("ret",    "Return",     72),
        ("profit", "Est.Profit", 88),
        ("local",  "Local?",     58),
    ]
    _ARB_COLS = [
        ("item",   "Item",      158),
        ("buy",    "Buy",        68),
        ("sell",   "Sell",       68),
        ("dest",   "To",        120),
        ("profit", "Profit%",    68),
        ("days",   "Days",       48),
        ("gpd",    "g/day",      62),
        ("stock",  "Stock",      52),
    ]

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=8, pady=6)

        # Header row
        hdr = ttk.Frame(main, style="MT.TFrame")
        hdr.pack(fill="x", padx=8, pady=(0, 4))
        self.section_label(hdr, "TRADE").pack(side="left")
        self._status_lbl = tk.Label(hdr, text="", font=FONT_MONO,
                                    bg=T["bg"], fg=T["yellow"], anchor="e")
        self._status_lbl.pack(side="right")

        # Notebook
        self._nb = ttk.Notebook(main, style="MT.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=8, pady=2)

        # ── Buy tab ───────────────────────────────────────────────────────────
        buy_tab = ttk.Frame(self._nb, style="MT.TFrame")
        self._nb.add(buy_tab, text="  Buy  ")

        self._buy_table = DataTable(buy_tab, self._BUY_COLS, height=13)
        self._buy_table.pack(fill="both", expand=True, padx=6, pady=4)
        self._buy_table.bind_select(self._on_buy_select)

        buy_act = ttk.Frame(buy_tab, style="MT.TFrame")
        buy_act.pack(fill="x", padx=6, pady=(2, 4))
        ttk.Button(buy_act, text="Buy Item", style="OK.TButton",
                   command=self._do_buy).pack(side="left", padx=(0, 6))
        ttk.Button(buy_act, text="Haggle", style="MT.TButton",
                   command=self._do_haggle).pack(side="left", padx=(0, 6))
        self._haggle_lbl = tk.Label(buy_act, text="", font=FONT_MONO_S,
                                    bg=T["bg"], fg=T["green"])
        self._haggle_lbl.pack(side="left", padx=(8, 0))
        self._buy_info = tk.Label(buy_act, text="Select an item, then click Buy.",
                                  font=FONT_MONO_S, bg=T["bg"], fg=T["grey"])
        self._buy_info.pack(side="right")

        # ── Sell tab ──────────────────────────────────────────────────────────
        sell_tab = ttk.Frame(self._nb, style="MT.TFrame")
        self._nb.add(sell_tab, text="  Sell  ")

        self._sell_table = DataTable(sell_tab, self._SELL_COLS, height=13)
        self._sell_table.pack(fill="both", expand=True, padx=6, pady=4)

        sell_act = ttk.Frame(sell_tab, style="MT.TFrame")
        sell_act.pack(fill="x", padx=6, pady=(2, 4))
        ttk.Button(sell_act, text="Sell Item", style="Danger.TButton",
                   command=self._do_sell).pack(side="left", padx=(0, 6))
        ttk.Button(sell_act, text="Sell All", style="Danger.TButton",
                   command=self._do_sell_all).pack(side="left", padx=(0, 6))
        self._sell_info = tk.Label(sell_act, text="Select an item, then click Sell.",
                                   font=FONT_MONO_S, bg=T["bg"], fg=T["grey"])
        self._sell_info.pack(side="right")

        # ── Arbitrage tab ─────────────────────────────────────────────────────
        arb_tab = ttk.Frame(self._nb, style="MT.TFrame")
        self._nb.add(arb_tab, text="  Arbitrage  ")

        self._arb_table = DataTable(arb_tab, self._ARB_COLS, height=15)
        self._arb_table.pack(fill="both", expand=True, padx=6, pady=4)
        tk.Label(arb_tab, text="Top 15 routes ranked by gold/day. "
                               "Buy here, travel, sell at destination.",
                 font=FONT_MONO_S, bg=T["bg"], fg=T["grey"]).pack(
            anchor="w", padx=6, pady=(0, 4))

        # Bottom bar
        ttk.Separator(main, style="MT.TSeparator").pack(fill="x", padx=8, pady=(4, 2))
        bot = ttk.Frame(main, style="MT.TFrame")
        bot.pack(fill="x", padx=8, pady=(0, 4))
        self.back_button(bot).pack(side="left")

        # Haggle state: (item_key, discount_fraction)
        self._haggle_item:     Optional[str]   = None
        self._haggle_discount: float           = 0.0

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        if not hasattr(self, "_buy_table"):
            return
        g      = self.game
        market = g.markets[g.current_area]
        season = g.season
        skill  = g.skills.trading

        self._status_lbl.config(
            text=(f"Gold: {g.inventory.gold:,.0f}g  ·  "
                  f"Weight: {g._current_weight():.1f}/{g._max_carry_weight():.0f}  ·  "
                  f"{g.current_area.value}")
        )

        # Buy table
        buy_rows = []
        for idx, k in enumerate(sorted(market.item_keys), 1):
            item = ALL_ITEMS.get(k)
            if not item:
                continue
            price = market.get_buy_price(k, season, skill)
            stock = market.stock.get(k, 0)
            hist  = list(market.history.get(k, []))
            if len(hist) >= 2:
                diff  = hist[-1].price - hist[-2].price
                trend = "▲" if diff > 0.001 else ("▼" if diff < -0.001 else "─")
                tcol  = "green" if diff > 0.001 else ("red" if diff < -0.001 else "dim")
            else:
                trend, tcol = "─", "dim"
            tag = "red" if item.illegal else tcol
            # Highlight if this item has an active haggle discount
            if item.illegal:
                tag = "red"
            buy_rows.append({
                "num":    str(idx),
                "item":   f"{item.name} [!]" if item.illegal else item.name,
                "cat":    item.category.value,
                "price":  f"{price:.1f}g",
                "stock":  str(stock),
                "trend":  trend,
                "rarity": item.rarity if isinstance(item.rarity, str) else item.rarity.value,
                "tag":    tag,
            })
        self._buy_table.load(buy_rows, tag_key="tag")

        # Update haggle label
        if self._haggle_item and self._haggle_discount > 0:
            hname = ALL_ITEMS[self._haggle_item].name if self._haggle_item in ALL_ITEMS else "?"
            self._haggle_lbl.config(
                text=f"Haggle active: {int(self._haggle_discount * 100)}% off {hname}"
            )
        else:
            self._haggle_lbl.config(text="")

        self._buy_info.config(
            text="Select an item, then click Buy.",
            fg=T["grey"],
        )

        # Sell table
        sell_rows = []
        for idx, (k, qty) in enumerate(sorted(g.inventory.items.items()), 1):
            item = ALL_ITEMS.get(k)
            if not item:
                continue
            is_local = k in market.item_keys
            sell_p   = market.get_sell_price(k, season, skill)
            if sell_p <= 0 or not is_local:
                sell_p = item.base_price * 0.65
            avg_cost = g.inventory.cost_basis.get(k)
            if avg_cost:
                ret_pct  = (sell_p - avg_cost) / max(avg_cost, 0.01) * 100
                ret_str  = f"{ret_pct:+.0f}%"
                ret_tag  = "green" if ret_pct >= 0 else "red"
                prof_g   = (sell_p - avg_cost) * qty
                prof_str = f"{prof_g:+.0f}g"
                paid_str = f"{avg_cost:.1f}g"
            else:
                ret_str, ret_tag, prof_str, paid_str = "—", "dim", "—", "—"
            tag = "red" if item.illegal else ret_tag
            sell_rows.append({
                "num":    str(idx),
                "item":   f"{item.name} [!]" if item.illegal else item.name,
                "have":   str(qty),
                "sell_p": f"{sell_p:.1f}g",
                "paid":   paid_str,
                "ret":    ret_str,
                "profit": prof_str,
                "local":  "yes" if is_local else "pawn",
                "tag":    tag,
            })
        self._sell_table.load(sell_rows, tag_key="tag")
        self._sell_info.config(
            text="Select an item, then click Sell.",
            fg=T["grey"],
        )

        self._refresh_arb()

    def _refresh_arb(self) -> None:
        g      = self.game
        market = g.markets[g.current_area]
        season = g.season
        skill  = g.skills.trading
        arb_rows = []
        for k in market.item_keys:
            item = ALL_ITEMS.get(k)
            if not item:
                continue
            buy_p = market.get_buy_price(k, season, skill)
            if buy_p <= 0:
                continue
            for dest in Area:
                if dest == g.current_area:
                    continue
                dest_mkt = g.markets[dest]
                if k not in dest_mkt.item_keys:
                    continue
                sell_p = dest_mkt.get_sell_price(k, season, skill)
                if sell_p <= buy_p:
                    continue
                days = AREA_INFO[g.current_area]["travel_days"].get(dest, 3)
                pct  = (sell_p - buy_p) / buy_p * 100
                gpd  = (sell_p - buy_p) / max(days, 1)
                stk  = market.stock.get(k, 0)
                arb_rows.append({
                    "item":   item.name,
                    "buy":    f"{buy_p:.1f}g",
                    "sell":   f"{sell_p:.1f}g",
                    "dest":   dest.value,
                    "profit": f"{pct:.0f}%",
                    "days":   str(days),
                    "gpd":    f"{gpd:.1f}",
                    "stock":  str(stk),
                    "_gpd":   gpd,
                })
        arb_rows.sort(key=lambda r: r["_gpd"], reverse=True)
        for r in arb_rows[:15]:
            del r["_gpd"]
        self._arb_table.load(arb_rows[:15])

    # ── Selection helpers ─────────────────────────────────────────────────────

    def _on_buy_select(self, row: Optional[Dict]) -> None:
        if not row:
            return
        g      = self.game
        market = g.markets[g.current_area]
        k      = self._key_from_buy_num(row.get("num", ""), market)
        if not k:
            return
        item  = ALL_ITEMS.get(k)
        price = market.get_buy_price(k, g.season, g.skills.trading)
        if self._haggle_item == k and self._haggle_discount > 0:
            price = round(price * (1.0 - self._haggle_discount), 2)
        stock = market.stock.get(k, 0)
        cap   = g._max_carry_weight()
        cur_w = g._current_weight()
        free  = max(0.0, cap - cur_w)
        mw    = int(free / item.weight) if item and item.weight > 0 else stock
        mg    = int(g.inventory.gold / price) if price > 0 else stock
        mx    = min(stock, mw, mg)
        txt   = (f"{item.name if item else k}  @{price:.1f}g  "
                 f"stock:{stock}  max:{mx}")
        if self._haggle_item == k and self._haggle_discount > 0:
            txt += f"  [haggled {int(self._haggle_discount * 100)}% off]"
        self._buy_info.config(text=txt, fg=T["yellow"])

    def _key_from_buy_num(self, num_str: str, market) -> Optional[str]:
        """Recover item key from '#' index (1-based) in the buy table."""
        try:
            idx = int(num_str) - 1
            keys = sorted(market.item_keys)
            if 0 <= idx < len(keys):
                return keys[idx]
        except (ValueError, TypeError):
            pass
        return None

    def _key_from_sell_num(self, num_str: str) -> Optional[str]:
        """Recover item key from '#' index (1-based) in the sell table."""
        try:
            idx = int(num_str) - 1
            keys = sorted(self.game.inventory.items.keys())
            if 0 <= idx < len(keys):
                return keys[idx]
        except (ValueError, TypeError):
            pass
        return None

    # ── Buy ───────────────────────────────────────────────────────────────────

    def _do_buy(self) -> None:
        row = self._buy_table.selected()
        if not row:
            self.msg.warn("Select an item first.")
            return
        g      = self.game
        market = g.markets[g.current_area]
        k      = self._key_from_buy_num(row.get("num", ""), market)
        if not k:
            self.msg.err("Could not identify item.")
            return
        item  = ALL_ITEMS.get(k)
        if not item:
            return

        season = g.season
        skill  = g.skills.trading
        price  = market.get_buy_price(k, season, skill)

        # Apply haggle discount if active on this item
        haggled    = self._haggle_item == k and self._haggle_discount > 0
        unit_price = round(price * (1.0 - self._haggle_discount), 2) if haggled else price

        stock      = market.stock.get(k, 0)
        cap        = g._max_carry_weight()
        cur_w      = g._current_weight()
        free_space = max(0.0, cap - cur_w)
        mw         = int(free_space / item.weight) if item.weight > 0 else stock
        mg         = int(g.inventory.gold / unit_price) if unit_price > 0 else stock
        max_qty    = min(stock, mw, mg)

        if max_qty <= 0:
            self.msg.err("Cannot buy: no stock, insufficient gold, or over weight limit.")
            return

        label = (f"Buy {item.name}  @{unit_price:.1f}g each"
                 + (f"  [{int(self._haggle_discount*100)}% haggle discount]" if haggled else "")
                 + f"\nMax quantity: {max_qty}\nQuantity:")
        raw = InputDialog(self, label, "Buy Item", default=str(max_qty)).wait()
        if raw is None:
            return
        try:
            qty = int(raw)
        except ValueError:
            self.msg.err("Invalid quantity.")
            return
        if not (1 <= qty <= max_qty):
            self.msg.err(f"Quantity must be 1–{max_qty}.")
            return

        # buy_from_market updates stock/pressure and returns un-discounted total
        result = market.buy_from_market(k, qty, season, skill)
        if result < 0:
            self.msg.err("Transaction failed — market rejected the purchase.")
            return

        actual_total = round(unit_price * qty, 2)
        g.inventory.gold -= actual_total
        g.inventory.record_purchase(k, qty, unit_price)
        g.inventory.add(k, qty)
        g._gain_skill_xp(SkillType.TRADING, 5)
        g._use_time(1)

        if haggled:
            self._haggle_item     = None
            self._haggle_discount = 0.0

        g.lifetime_trades += 1
        self.msg.ok(
            f"Bought {qty}× {item.name} for {actual_total:.0f}g "
            f"({unit_price:.1f}g/ea)."
        )
        self.app.sound.play_coin_sfx()
        self.app.refresh()
        self.app._flush_achievements()

    # ── Haggle ────────────────────────────────────────────────────────────────

    def _do_haggle(self) -> None:
        import random
        row = self._buy_table.selected()
        if not row:
            self.msg.warn("Select an item to haggle on first.")
            return
        g      = self.game
        market = g.markets[g.current_area]
        k      = self._key_from_buy_num(row.get("num", ""), market)
        if not k:
            self.msg.err("Could not identify item.")
            return
        item  = ALL_ITEMS.get(k)
        if not item:
            return

        skill   = g.skills.haggling
        chance  = 0.10 + skill * 0.08
        g._use_time(1)
        g._gain_skill_xp(SkillType.HAGGLING, 10)

        if random.random() < chance:
            discount = random.uniform(0.05, 0.15 + skill * 0.02)
            self._haggle_item     = k
            self._haggle_discount = discount
            self.msg.ok(
                f"Haggled! {int(discount * 100)}% discount on {item.name}. "
                f"Select the item and click Buy to use it."
            )
        else:
            self._haggle_item     = None
            self._haggle_discount = 0.0
            self.msg.warn("Haggling failed — merchant won't budge.")

        self.app.refresh()

    # ── Sell ──────────────────────────────────────────────────────────────────

    def _do_sell(self) -> None:
        row = self._sell_table.selected()
        if not row:
            self.msg.warn("Select an item to sell.")
            return
        k = self._key_from_sell_num(row.get("num", ""))
        if not k:
            self.msg.err("Could not identify item.")
            return
        self._execute_sell(k)

    def _do_sell_all(self) -> None:
        g      = self.game
        market = g.markets[g.current_area]
        if not g.inventory.items:
            self.msg.err("Inventory is empty.")
            return
        if not ConfirmDialog(self, "Sell ALL items in your inventory?",
                             "Sell All").wait():
            return
        total_earned = 0.0
        for k, qty in list(g.inventory.items.items()):
            item = ALL_ITEMS.get(k)
            if not item:
                continue
            is_local = k in market.item_keys
            sell_p   = market.get_sell_price(k, g.season, g.skills.trading)
            if sell_p <= 0 or not is_local:
                sell_p = round(item.base_price * 0.65, 2)
            earnings = market.sell_to_market(k, qty, g.season, g.skills.trading)
            if earnings < 0:
                earnings = round(sell_p * qty, 2)
            earnings       = round(earnings * g._sell_mult(), 2)
            g.inventory.remove(k, qty)
            g.inventory.gold  += earnings
            g.total_profit    += earnings
            total_earned      += earnings
            g.lifetime_trades += 1
            g._gain_skill_xp(SkillType.TRADING, 5)
        g._use_time(1)
        g.ach_stats["wait_streak"] = 0
        g._check_achievements()
        self.msg.ok(f"Sold all items — received {total_earned:.0f}g total.")
        self.app.sound.play_coin_sfx()
        self.app.profit_flash(total_earned)
        self.app.refresh()
        self.app._flush_achievements()

    def _execute_sell(self, k: str) -> None:
        import random
        g      = self.game
        market = g.markets[g.current_area]
        item   = ALL_ITEMS.get(k)
        if not item:
            return
        max_q = g.inventory.items.get(k, 0)
        if max_q == 0:
            self.msg.err("You don't have that item.")
            return

        is_local = k in market.item_keys
        sell_p   = market.get_sell_price(k, g.season, g.skills.trading)
        if sell_p <= 0 or not is_local:
            sell_p = round(item.base_price * 0.65, 2)

        raw = InputDialog(self,
                          f"Sell {item.name}  @{sell_p:.1f}g each"
                          + ("  [pawn price]" if not is_local else "")
                          + f"\nYou have: {max_q}\nQuantity:",
                          "Sell Item", default=str(max_q)).wait()
        if raw is None:
            return
        try:
            qty = int(raw)
        except ValueError:
            self.msg.err("Invalid quantity.")
            return
        if not (1 <= qty <= max_q):
            self.msg.err(f"Quantity must be 1–{max_q}.")
            return

        # Illegal item guard check
        if item.illegal and g.current_area != Area.SWAMP:
            guard = AREA_INFO[g.current_area].get("guard_strength", 0.0)
            if random.random() < guard * 0.10:
                fine = round(item.base_price * qty * 0.6, 2)
                g.inventory.remove(k, qty)
                g.inventory.gold = max(0.0, g.inventory.gold - fine)
                g.reputation     = max(0, g.reputation - 12)
                g.heat           = min(100, g.heat + 22)
                self.msg.err(
                    f"Guards caught you! {qty}× {item.name} seized + fine {fine:.0f}g."
                )
                self.app.refresh()
                return

        earnings = market.sell_to_market(k, qty, g.season, g.skills.trading)
        if earnings < 0:
            earnings = round(item.base_price * 0.65 * qty, 2)
        earnings = round(earnings * g._sell_mult(), 2)

        avg_cost = g.inventory.cost_basis.get(k)
        g.inventory.remove(k, qty)
        g.inventory.gold  += earnings
        g.total_profit    += earnings
        g.lifetime_trades += 1
        g._gain_skill_xp(SkillType.TRADING, 5)
        g._use_time(1)
        g.ach_stats["wait_streak"] = 0
        g._check_achievements()

        if avg_cost:
            profit = earnings - avg_cost * qty
            pct    = (earnings / qty - avg_cost) / max(avg_cost, 0.01) * 100
            pl_str = f"  P/L: {profit:+.0f}g ({pct:+.0f}%)"
        else:
            pl_str = ""
        self.msg.ok(
            f"Sold {qty}× {item.name} for {earnings:.0f}g "
            f"({earnings / qty:.1f}g/ea).{pl_str}"
        )
        self.app.sound.play_coin_sfx()
        self.app.profit_flash(earnings)
        self.app.refresh()
        self.app._flush_achievements()
class TravelScreen(Screen):
    """Travel screen — mirrors travel_menu() and _travel_incident() from the CLI."""

    _COLS = [
        ("area",  "Destination",  145),
        ("days",  "Days",          55),
        ("risk",  "Risk",          60),
        ("cost",  "Est. Cost",     80),
        ("items", "Local Goods",  230),
        ("desc",  "Description",  260),
    ]

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        # Header + overload notice
        hdr_row = ttk.Frame(main, style="MT.TFrame")
        hdr_row.pack(fill="x", padx=10, pady=(0, 4))
        self.section_label(hdr_row, "TRAVEL").pack(side="left")
        self._overload_lbl = tk.Label(hdr_row, text="", font=FONT_MONO_S,
                                      bg=T["bg"], fg=T["red"], anchor="e")
        self._overload_lbl.pack(side="right")

        self._info_lbl = tk.Label(main, text="", font=FONT_MONO,
                                  bg=T["bg"], fg=T["fg"], anchor="w", padx=10)
        self._info_lbl.pack(fill="x", pady=(0, 4))

        # Destinations table
        self._table = DataTable(main, self._COLS, height=10)
        self._table.pack(fill="both", expand=True, padx=10, pady=4)
        self._table.bind_select(self._on_select)

        # Detail strip
        self._detail_lbl = tk.Label(
            main, text="Select a destination to see details.",
            font=FONT_MONO_S, bg=T["bg_panel"], fg=T["grey"],
            anchor="w", padx=12, pady=6, wraplength=940,
        )
        self._detail_lbl.pack(fill="x", padx=10, pady=(0, 4))

        # Action row
        act = ttk.Frame(main, style="MT.TFrame")
        act.pack(fill="x", padx=10, pady=4)
        self._travel_btn = ttk.Button(act, text="  Travel  ►  ", style="OK.TButton",
                                      command=self._do_travel, state="disabled")
        self._travel_btn.pack(side="left", padx=(0, 8))
        self.back_button(act).pack(side="left")

        self._selected_area: Optional[Area] = None

    def refresh(self) -> None:
        if not hasattr(self, "_table"):
            return
        g         = self.game
        cur_w     = g._current_weight()
        cap       = g._max_carry_weight()
        excess    = max(0.0, cur_w - cap)
        cost_mult = g.settings.cost_mult

        self._info_lbl.config(
            text=f"From: {g.current_area.value}   ·   Gold: {g.inventory.gold:,.0f}g"
        )
        if excess > 0:
            extra = int(excess / 15)
            self._overload_lbl.config(
                text=f"⚠ Overloaded +{excess:.1f}wt  →  +{extra} day(s) per journey"
            )
        else:
            self._overload_lbl.config(text="")

        extra_days = int(excess / 15)
        rows = []
        for area in Area:
            if area == g.current_area:
                continue
            days_base = AREA_INFO[g.current_area]["travel_days"].get(area, 3)
            days      = days_base + extra_days
            risk      = AREA_INFO[area]["travel_risk"]
            cost      = days * 3.0 * cost_mult
            items_4   = list(g.markets[area].item_keys)[:4]
            items_str = ", ".join(
                ALL_ITEMS[k].name for k in items_4 if k in ALL_ITEMS
            )
            desc = AREA_INFO[area].get("description", "")
            rows.append({
                "area":  area.value,
                "days":  str(days),
                "risk":  f"{risk * 100:.0f}%",
                "cost":  f"{cost:.0f}g",
                "items": items_str,
                "desc":  desc,
            })
        self._table.load(rows)
        self._selected_area = None
        self._travel_btn.config(state="disabled")
        self._detail_lbl.config(text="Select a destination to see details.",
                                fg=T["grey"])

    def _on_select(self, row: Optional[Dict]) -> None:
        if not row:
            self._selected_area = None
            self._travel_btn.config(state="disabled")
            return
        area_val = row.get("area", "")
        for a in Area:
            if a.value == area_val:
                self._selected_area = a
                break
        else:
            self._selected_area = None
        if self._selected_area:
            self._travel_btn.config(state="normal")
            self._detail_lbl.config(
                text=(f"{row['area']}  ·  {row['days']} days  ·  risk {row['risk']}"
                      f"  ·  cost ~{row['cost']}  ·  {row['desc']}"),
                fg=T["fg"],
            )

    def _do_travel(self) -> None:
        if not self._selected_area:
            return
        import random

        g         = self.game
        dest      = self._selected_area
        cur       = g.current_area
        cost_mult = g.settings.cost_mult
        cur_w     = g._current_weight()
        cap       = g._max_carry_weight()
        excess    = max(0.0, cur_w - cap)
        extra_d   = int(excess / 15)
        days_base = AREA_INFO[cur]["travel_days"].get(dest, 3)
        days_travel = days_base + extra_d
        travel_cost = days_travel * 3.0 * cost_mult
        risk        = AREA_INFO[dest]["travel_risk"]

        if g.inventory.gold < travel_cost:
            self.msg.err(f"Not enough gold — need {travel_cost:.0f}g.")
            return

        confirm_msg = (
            f"Travel to {dest.value}?\n\n"
            f"Journey:  {days_travel} day(s)\n"
            f"Cost:     {travel_cost:.0f}g\n"
            f"Risk:     {risk * 100:.0f}%"
        )
        if not ConfirmDialog(self, confirm_msg, "Confirm Travel").wait():
            return

        # Bodyguard offer
        effective_risk = risk * (1.5 if extra_d > 0 else 1.0)
        hired_guard    = False
        if risk > 0:
            guard_cost = max(10, round(risk * 120 * cost_mult))
            guard_msg  = (
                f"Hire a bodyguard for {guard_cost}g?\n"
                f"Reduces the chance of an armed attack by 60%."
            )
            if ConfirmDialog(self, guard_msg, "Bodyguard").wait():
                if g.inventory.gold >= travel_cost + guard_cost:
                    g.inventory.gold -= guard_cost
                    hired_guard = True
                    self.msg.info("Bodyguard hired.")
                else:
                    self.msg.warn("Not enough gold for a bodyguard.")

        # Execute travel
        g.inventory.gold -= travel_cost
        attack_mult      = 0.4 if hired_guard else 1.0
        for _ in range(days_travel):
            g._advance_day()

        g.current_area = dest
        g._track_stat("areas_visited", dest.value)
        g._track_stat("journeys")
        g._track_stat("travel_days", days_travel)
        g.heat = max(0, g.heat - days_travel * 3)

        incident_msg = ""
        if random.random() < effective_risk:
            incident_msg = self._run_incident(dest, attack_mult)

        g._check_achievements()
        self.app.refresh()
        self.app._flush_achievements()

        result = (
            f"Arrived in {dest.value}!\n\n"
            f"Journey: {days_travel} day(s)    Cost: {travel_cost:.0f}g"
        )
        if incident_msg:
            result += f"\n\n── Travel Event ──\n{incident_msg}"
        InfoDialog(self, "Travel Complete", result).wait()

    def _run_incident(self, dest: Area, attack_mult: float) -> str:
        import random
        g    = self.game
        roll = random.random()

        # Armed attack
        if roll < 0.25 * attack_mult:
            if random.random() < 0.5:
                return "Armed attackers were repelled by your bodyguard."
            loss_g = round(g.inventory.gold * random.uniform(0.10, 0.30), 2)
            g.inventory.gold = max(0.0, g.inventory.gold - loss_g)
            g.reputation     = max(0, g.reputation - 3)
            keys = list(g.inventory.items.keys())
            if keys:
                k = random.choice(keys)
                g.inventory.remove(k, 1)
                name = ALL_ITEMS[k].name if k in ALL_ITEMS else k
                return (f"Armed attack! Lost {loss_g:.0f}g and "
                        f"1× {name}.  Rep −3.")
            return f"Armed attack! Lost {loss_g:.0f}g.  Rep −3."

        # Bandits — gold theft
        if roll < 0.30:
            pct   = random.uniform(0.05, 0.18)
            loss_g = round(g.inventory.gold * pct, 2)
            g.inventory.gold = max(0.0, g.inventory.gold - loss_g)
            g.reputation     = max(0, g.reputation - 2)
            return f"Bandits stole {loss_g:.0f}g ({pct * 100:.0f}% of your gold).  Rep −2."

        # Bandits — item theft
        if roll < 0.50:
            keys = list(g.inventory.items.keys())
            if keys:
                k   = random.choice(keys)
                qty = max(1, g.inventory.items[k] // 3)
                g.inventory.remove(k, qty)
                name = ALL_ITEMS[k].name if k in ALL_ITEMS else k
                return f"Bandits stole {qty}× {name}."
            return "Bandits found nothing to steal."

        # Border inspection (only if illegal goods present)
        guard = AREA_INFO[dest].get("guard_strength", 0.0)
        illegal = {k: q for k, q in g.inventory.items.items()
                   if ALL_ITEMS.get(k) and ALL_ITEMS[k].illegal}
        if roll < 0.62 and illegal and guard > 0:
            fine = 0.0
            seized = []
            for k, qty in list(illegal.items()):
                fine += ALL_ITEMS[k].base_price * qty * 0.8
                g.inventory.remove(k, qty)
                seized.append(f"{qty}× {ALL_ITEMS[k].name}")
            fine = round(fine, 2)
            g.inventory.gold = max(0.0, g.inventory.gold - fine)
            g.reputation     = max(0, g.reputation - 15)
            g.heat           = min(100, g.heat + 30)
            return (f"Border inspection! Seized: {', '.join(seized)}.\n"
                    f"Fine: {fine:.0f}g.  Rep −15.  Heat +30.")

        # Lucky find
        if roll < 0.78:
            lucky = [k for k in ("herbs", "gold_dust", "gem", "spice", "fur")
                     if k in ALL_ITEMS]
            if lucky:
                k   = random.choice(lucky)
                qty = random.randint(1, 5)
                g.inventory.add(k, qty)
                return f"Lucky! Found {qty}× {ALL_ITEMS[k].name} on the road."

        # Weather damage
        keys = list(g.inventory.items.keys())
        if keys:
            k   = random.choice(keys)
            qty = max(1, g.inventory.items.get(k, 0) // 4)
            g.inventory.remove(k, qty)
            name = ALL_ITEMS[k].name if k in ALL_ITEMS else k
            return f"Bad weather damaged your cargo — lost {qty}× {name}."
        return "Bad weather delayed your journey, but no goods were lost."
class InventoryScreen(Screen):
    """Inventory view — mirrors Inventory.display() from the CLI."""

    _COLS = [
        ("item",  "Item",         200),
        ("qty",   "Qty",           50),
        ("paid",  "Paid/ea",       85),
        ("total", "Total Cost",    90),
        ("wt",    "Wt/ea",         60),
        ("twt",   "Total Wt",      65),
        ("cat",   "Category",     120),
    ]

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        # Header row — title only (back button moved to bottom)
        hdr = ttk.Frame(main, style="MT.TFrame")
        hdr.pack(fill="x", padx=10, pady=(0, 4))
        self.section_label(hdr, "INVENTORY").pack(side="left")

        # Stats row
        stats_row = ttk.Frame(main, style="MT.TFrame")
        stats_row.pack(fill="x", padx=10, pady=(0, 6))
        self._gold_lbl = tk.Label(stats_row, text="", font=FONT_MONO,
                                  bg=T["bg"], fg=T["yellow"], anchor="w")
        self._gold_lbl.pack(side="left")
        self._wt_lbl = tk.Label(stats_row, text="", font=FONT_MONO,
                                bg=T["bg"], fg=T["cyan"], anchor="w")
        self._wt_lbl.pack(side="left", padx=(20, 0))
        self._slots_lbl = tk.Label(stats_row, text="", font=FONT_MONO,
                                   bg=T["bg"], fg=T["fg_dim"], anchor="w")
        self._slots_lbl.pack(side="right")

        # Item table
        self._table = DataTable(main, self._COLS, height=12)
        self._table.pack(fill="both", expand=True, padx=10, pady=4)
        self._empty_lbl = tk.Label(
            main, text="",
            font=FONT_MONO, bg=T["bg"], fg=T["grey"], anchor="center",
        )
        self._empty_lbl.pack(fill="x", pady=4)

        # Weight bar
        wt_frame = ttk.Frame(main, style="MT.TFrame")
        wt_frame.pack(fill="x", padx=10, pady=(2, 4))
        tk.Label(wt_frame, text="Carry Weight: ", font=FONT_MONO_S,
                 bg=T["bg"], fg=T["grey"]).pack(side="left")
        self._wt_bar = ttk.Progressbar(wt_frame, length=320, maximum=100,
                                       style="Horizontal.TProgressbar")
        self._wt_bar.pack(side="left")
        self._wt_pct_lbl = tk.Label(wt_frame, text="", font=FONT_MONO_S,
                                    bg=T["bg"], fg=T["grey"])
        self._wt_pct_lbl.pack(side="left", padx=(8, 0))

        # Back button at bottom left
        self.back_button(main).pack(anchor="w", padx=10, pady=(4, 4))

    def refresh(self) -> None:
        if not hasattr(self, "_table"):
            return
        g    = self.game
        inv  = g.inventory
        cur_w = g._current_weight()
        cap   = g._max_carry_weight()

        self._gold_lbl.config(text=f"Gold: {inv.gold:,.2f}g")
        self._wt_lbl.config(
            text=f"Weight: {cur_w:.1f} / {cap:.0f} wt"
                 + ("  ⚠ OVERLOADED" if cur_w > cap else ""),
            fg=T["red"] if cur_w > cap else T["cyan"],
        )
        used = g.daily_time_units
        left = g.DAILY_TIME_UNITS - used
        self._slots_lbl.config(
            text=f"Slots: {'●' * used}{'○' * left}  ({left}/{g.DAILY_TIME_UNITS} left)"
        )

        # Build rows sorted by category then name
        def _sort_key(pair):
            k, _ = pair
            item = ALL_ITEMS.get(k)
            cat  = item.category.value if item else "ZZZ"
            name = item.name           if item else k
            return (cat, name)

        rows = []
        for k, qty in sorted(inv.items.items(), key=_sort_key):
            item = ALL_ITEMS.get(k)
            if not item:
                continue
            avg_cost  = inv.cost_basis.get(k)
            paid_str  = f"{avg_cost:.1f}g"  if avg_cost else "—"
            total_str = f"{avg_cost * qty:.0f}g" if avg_cost else "—"
            name_str  = f"{item.name} [!]" if item.illegal else item.name
            rows.append({
                "item":  name_str,
                "qty":   str(qty),
                "paid":  paid_str,
                "total": total_str,
                "wt":    f"{item.weight:.1f}",
                "twt":   f"{item.weight * qty:.1f}",
                "cat":   item.category.value,
                "tag":   "red" if item.illegal else "",
            })
        self._table.load(rows, tag_key="tag")
        self._empty_lbl.config(
            text="" if rows
                 else "  — Your cargo hold is empty —"
        )

        # Weight progress bar (yellow > 80%, red > 100%)
        pct = (cur_w / cap * 100) if cap > 0 else 0
        self._wt_bar["value"] = min(pct, 100)
        bar_col = T["red"] if pct >= 100 else T["yellow"] if pct >= 80 else T["cyan"]
        ttk.Style().configure("Horizontal.TProgressbar", background=bar_col)
        self._wt_pct_lbl.config(
            text=f"{pct:.0f}%  ({cur_w:.1f}/{cap:.0f} wt)",
            fg=bar_col,
        )
class WaitScreen(Screen):
    """Wait / Rest screen — mirrors _wait_days_menu() from the CLI."""

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=32, pady=20)

        self.section_label(main, "REST & WAIT").pack(anchor="w", pady=(0, 6))
        ttk.Separator(main, style="MT.TSeparator").pack(fill="x", pady=(0, 16))

        # ── Current time context ──────────────────────────────────────────
        ctx = tk.Frame(main, bg=T["bg_panel"], padx=18, pady=14)
        ctx.pack(fill="x", pady=(0, 16))
        tk.Frame(ctx, bg=T["border_light"], height=2).pack(fill="x", side="top")

        row1 = tk.Frame(ctx, bg=T["bg_panel"])
        row1.pack(fill="x", pady=(8, 0))
        self._info_lbl = tk.Label(row1, text="", font=FONT_FANTASY_BOLD,
                                  bg=T["bg_panel"], fg=T["cyan"], anchor="w")
        self._info_lbl.pack(side="left")
        self._until_lbl = tk.Label(row1, text="", font=FONT_FANTASY_S,
                                   bg=T["bg_panel"], fg=T["fg_dim"], anchor="e")
        self._until_lbl.pack(side="right")

        row2 = tk.Frame(ctx, bg=T["bg_panel"])
        row2.pack(fill="x", pady=(6, 0))
        tk.Label(row2, text="Season progress:", font=FONT_FANTASY_S,
                 bg=T["bg_panel"], fg=T["grey"], anchor="w").pack(side="left")
        self._season_bar = ttk.Progressbar(row2, length=260, maximum=100,
                                           style="Horizontal.TProgressbar")
        self._season_bar.pack(side="left", padx=(10, 8))
        self._season_pct = tk.Label(row2, text="", font=FONT_MONO_S,
                                    bg=T["bg_panel"], fg=T["grey"])
        self._season_pct.pack(side="left")

        row3 = tk.Frame(ctx, bg=T["bg_panel"])
        row3.pack(fill="x", pady=(6, 4))
        self._wait_hint = tk.Label(row3, text="", font=FONT_FANTASY_S,
                                   bg=T["bg_panel"], fg=T["fg_dim"], anchor="w",
                                   justify="left")
        self._wait_hint.pack(anchor="w")

        # ── Action buttons ────────────────────────────────────────────────
        btns = ttk.Frame(main, style="MT.TFrame")
        btns.pack(anchor="w", pady=4)

        ttk.Button(btns, text="⌛  Wait 1 Day", style="MT.TButton",
                   command=self._wait_1).pack(side="left", padx=(0, 8))
        self._season_btn = ttk.Button(btns, text="Wait to Next Season",
                                      style="MT.TButton",
                                      command=self._wait_season)
        self._season_btn.pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Wait N Days…", style="MT.TButton",
                   command=self._wait_n).pack(side="left", padx=(0, 8))

        ttk.Separator(main, style="MT.TSeparator").pack(fill="x", pady=(20, 10))
        self.back_button(main).pack(anchor="w")

    def refresh(self) -> None:
        if not hasattr(self, "_info_lbl"):
            return
        g         = self.game
        days_done = (g.day - 1) % g.DAYS_PER_SEASON
        days_till = g.DAYS_PER_SEASON - days_done
        seasons   = list(Season)
        next_s    = seasons[(seasons.index(g.season) + 1) % 4]

        self._info_lbl.config(
            text=f"{g.season.value}   ·   Year {g.year}   ·   Day {g.day}"
        )
        self._until_lbl.config(
            text=f"Next season in {days_till} day{'s' if days_till != 1 else ''}   →   {next_s.value}"
        )

        pct = int(days_done / g.DAYS_PER_SEASON * 100)
        self._season_bar["value"] = pct
        self._season_pct.config(text=f"{days_done} / {g.DAYS_PER_SEASON} days")

        self._season_btn.config(
            text=f"⏭  Wait to Next Season  ({days_till} day{'s' if days_till != 1 else ''})"
        )

        # Hint text — what will happen while waiting
        hints = []
        if g.businesses:
            running = sum(1 for b in g.businesses if b.workers > 0 and not b.broken_down)
            if running:
                hints.append(f"🏭  {running} business{'es' if running > 1 else ''} will produce goods each day.")
        if g.heat > 0:
            hints.append(f"❄  Heat cools by 3/travel day  (currently {g.heat}/100).")
        if g.cds:
            hints.append(f"🏦  {len(g.cds)} certificate(s) of deposit accumulating interest.")
        self._wait_hint.config(text="\n".join(hints) if hints else "Nothing notable will happen while you wait.")

    def _do_wait(self, days: int) -> None:
        g = self.game
        for _ in range(days):
            g._advance_day()
            g.ach_stats["wait_streak"] = g.ach_stats.get("wait_streak", 0) + 1
        g._check_achievements()
        self.app.refresh()
        self.msg.ok(f"Waited {days} day{'s' if days != 1 else ''}.")
        self.app._flush_achievements()

    def _wait_1(self) -> None:
        self._do_wait(1)

    def _wait_season(self) -> None:
        g         = self.game
        days_till = g.DAYS_PER_SEASON - ((g.day - 1) % g.DAYS_PER_SEASON)
        if ConfirmDialog(self,
                         f"Wait {days_till} day{'s' if days_till != 1 else ''} "
                         f"until the next season?",
                         "Wait to Season").wait():
            self._do_wait(days_till)

    def _wait_n(self) -> None:
        raw = InputDialog(self, "How many days to wait? (1–30):",
                          "Wait N Days").wait()
        if raw is None:
            return
        try:
            n = int(raw)
        except ValueError:
            self.msg.err("Enter a whole number.")
            return
        if not (1 <= n <= 30):
            self.msg.err("Must be between 1 and 30.")
            return
        self._do_wait(n)
class BusinessesScreen(Screen):
    """Businesses screen — mirrors businesses_menu() from the CLI."""

    _COLS = [
        ("num",     "#",          36),
        ("name",    "Name",      190),
        ("item",    "Produces",  115),
        ("level",   "Level",      55),
        ("workers", "Workers",    70),
        ("prod",    "Prod/day",   68),
        ("cost",    "Cost/day",   68),
        ("status",  "Status",     80),
    ]

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        hdr = ttk.Frame(main, style="MT.TFrame")
        hdr.pack(fill="x", padx=10, pady=(0, 4))
        self.section_label(hdr, "BUSINESSES").pack(side="left")
        self._lic_lbl = tk.Label(hdr, text="", font=FONT_MONO_S, bg=T["bg"], fg=T["red"])
        self._lic_lbl.pack(side="right")

        self._table = DataTable(main, self._COLS, height=9)
        self._table.pack(fill="both", expand=True, padx=10, pady=4)
        self._table.bind_select(self._on_select)

        # ── Detail card (updated on row selection) ────────────────────────
        detail_card = tk.Frame(main, bg=T["bg_panel"], padx=14, pady=10)
        detail_card.pack(fill="x", padx=10, pady=(0, 4))
        tk.Frame(detail_card, bg=T["border_light"], height=2).pack(fill="x", side="top")
        detail_inner = tk.Frame(detail_card, bg=T["bg_panel"])
        detail_inner.pack(fill="x", pady=(6, 0))

        # Row 1: name + status
        r1 = tk.Frame(detail_inner, bg=T["bg_panel"])
        r1.pack(fill="x")
        self._det_name   = tk.Label(r1, text="Select a business to see details.",
                                    font=FONT_FANTASY_BOLD, bg=T["bg_panel"], fg=T["cyan"], anchor="w")
        self._det_name.pack(side="left")
        self._det_status = tk.Label(r1, text="",
                                    font=FONT_FANTASY_BOLD, bg=T["bg_panel"], fg=T["grey"], anchor="e")
        self._det_status.pack(side="right")

        # Row 2: key metrics
        r2 = tk.Frame(detail_inner, bg=T["bg_panel"])
        r2.pack(fill="x", pady=(3, 0))
        self._det_metrics = tk.Label(r2, text="",
                                     font=FONT_MONO_S, bg=T["bg_panel"], fg=T["fg"], anchor="w")
        self._det_metrics.pack(side="left")
        self._det_cost = tk.Label(r2, text="",
                                  font=FONT_MONO_S, bg=T["bg_panel"], fg=T["yellow"], anchor="e")
        self._det_cost.pack(side="right")

        act = ttk.Frame(main, style="MT.TFrame")
        act.pack(fill="x", padx=10, pady=4)
        ttk.Button(act, text="Buy Business",   style="OK.TButton",
                   command=self._do_purchase).pack(side="left", padx=(0, 6))
        ttk.Button(act, text="Upgrade",        style="MT.TButton",
                   command=self._do_upgrade).pack(side="left", padx=(0, 6))
        ttk.Button(act, text="Hire Worker",    style="MT.TButton",
                   command=self._do_hire).pack(side="left", padx=(0, 6))
        ttk.Button(act, text="Fire Worker",    style="MT.TButton",
                   command=self._do_fire).pack(side="left", padx=(0, 6))
        ttk.Button(act, text="Repair",         style="MT.TButton",
                   command=self._do_repair).pack(side="left", padx=(0, 6))
        ttk.Button(act, text="Sell Business",  style="Danger.TButton",
                   command=self._do_sell).pack(side="left", padx=(0, 6))

        ttk.Separator(main, style="MT.TSeparator").pack(fill="x", padx=10, pady=(8, 4))
        self.back_button(main).pack(anchor="w", padx=10)

    def refresh(self) -> None:
        if not hasattr(self, "_table"):
            return
        g = self.game
        has_lic = LicenseType.BUSINESS in g.licenses
        self._lic_lbl.config(
            text="" if has_lic else "⚠ No Business Permit — buy from Licenses"
        )
        rows = []
        for i, b in enumerate(g.businesses, 1):
            item   = ALL_ITEMS.get(b.item_produced)
            status = "BROKEN" if b.broken_down else ("Running" if b.workers > 0 else "No workers")
            tag    = "red" if b.broken_down else ("green" if b.workers > 0 else "yellow")
            rows.append({
                "num":     str(i),
                "name":    b.name,
                "item":    item.name if item else b.item_produced,
                "level":   f"Lv{b.level}",
                "workers": f"{b.workers}/{b.max_workers}",
                "prod":    str(b.daily_production()),
                "cost":    f"{b.daily_cost:.0f}g",
                "status":  status,
                "tag":     tag,
            })
        self._table.load(rows, tag_key="tag")

    def _idx(self, row: Optional[Dict]) -> int:
        try:
            return int((row or {}).get("num", "0")) - 1
        except (ValueError, TypeError):
            return -1

    def _on_select(self, row: Optional[Dict]) -> None:
        if not row:
            return
        g   = self.game
        idx = self._idx(row)
        if not (0 <= idx < len(g.businesses)):
            return
        b        = g.businesses[idx]
        upgrade  = round(b.level * 200 + b.purchase_cost * 0.3)
        wage     = b.worker_daily_wage()
        item     = ALL_ITEMS.get(b.item_produced)
        item_name = item.name if item else b.item_produced
        status_str = ("⚠ BROKEN" if b.broken_down
                      else ("✓ Running" if b.workers > 0 else "⚡ No workers"))
        status_col = (T["red"]    if b.broken_down
                      else (T["green"] if b.workers > 0 else T["yellow"]))
        self._det_name.config(text=f"{b.name}   Lv{b.level}   {b.location.value}")
        self._det_status.config(text=status_str, fg=status_col)
        self._det_metrics.config(
            text=(f"Produces: {b.daily_production()}/day {item_name}   ·   "
                  f"Workers: {b.workers}/{b.max_workers}   ·   "
                  f"Daily wages: {wage:.0f}g   ·   Daily cost: {b.daily_cost:.0f}g")
        )
        cost_parts = [f"Upgrade: {upgrade}g"]
        if b.broken_down:
            cost_parts.append(f"Repair: {b.repair_cost:.0f}g")
        sale_val = round(b.purchase_cost * 0.5 + b.level * 80)
        cost_parts.append(f"Sale value: ~{sale_val}g")
        self._det_cost.config(text="   ·   ".join(cost_parts))

    def _do_purchase(self) -> None:
        g = self.game
        if LicenseType.BUSINESS not in g.licenses:
            self.msg.err("You need a Business Permit license to buy businesses.")
            return
        entries  = list(BUSINESS_CATALOGUE.items())
        choices  = []
        for key, data in entries:
            item     = ALL_ITEMS.get(data["item"])
            iname    = item.name if item else data["item"]
            bp       = item.base_price if item else 0
            net      = bp * data["rate"] - data["cost"]
            net_s    = f"{'+' if net >= 0 else ''}{net:.0f}g"
            choices.append(
                f"{data['name']}  [{data['area'].value}]  "
                f"{data['buy']:.0f}g  ·  {data['rate']}/day {iname}  net~{net_s}/day"
            )
        idx = ChoiceDialog(self, "Choose a business to purchase:", choices,
                           "Purchase Business").wait()
        if idx is None:
            return
        key, data = entries[idx]
        cost = data["buy"]
        if g.inventory.gold < cost:
            self.msg.err(f"Need {cost:.0f}g, have {g.inventory.gold:.0f}g.")
            return
        g.inventory.gold -= cost
        b = make_business(key, data["area"])
        g.businesses.append(b)
        g._gain_skill_xp(SkillType.INDUSTRY, 20)
        self.msg.ok(f"Purchased {b.name} for {cost:.0f}g in {b.area.value}.")
        self.app.refresh()

    def _do_upgrade(self) -> None:
        row = self._table.selected()
        if not row:
            self.msg.warn("Select a business to upgrade.")
            return
        g    = self.game
        idx  = self._idx(row)
        if not (0 <= idx < len(g.businesses)):
            return
        b    = g.businesses[idx]
        cost = round(b.level * 200 + b.purchase_cost * 0.3)
        if not ConfirmDialog(self, f"Upgrade {b.name} to Lv{b.level + 1} for {cost}g?",
                             "Upgrade").wait():
            return
        if g.inventory.gold < cost:
            self.msg.err(f"Need {cost}g.")
            return
        g.inventory.gold -= cost
        b.level += 1
        g._gain_skill_xp(SkillType.INDUSTRY, 10)
        self.msg.ok(f"{b.name} upgraded to Lv{b.level}.")
        self.app.refresh()

    def _do_hire(self) -> None:
        row = self._table.selected()
        if not row:
            self.msg.warn("Select a business to hire for.")
            return
        g   = self.game
        idx = self._idx(row)
        if not (0 <= idx < len(g.businesses)):
            return
        b = g.businesses[idx]
        if b.workers >= b.max_workers:
            self.msg.err(f"{b.name} is fully staffed ({b.max_workers} workers).")
            return
        chosen = ApplicantDialog(self, b.name).wait()
        if chosen is None:
            return
        b.hired_workers.append(chosen)
        b.workers = len(b.hired_workers)
        self.app.refresh()
        self.msg.ok(
            f"Hired {chosen['name']} at {chosen['wage']:.1f}g/day  "
            f"(productivity {chosen['productivity']:.2f}×  ·  {chosen['trait']})."
        )

    def _do_fire(self) -> None:
        row = self._table.selected()
        if not row:
            self.msg.warn("Select a business to fire from.")
            return
        g   = self.game
        idx = self._idx(row)
        if not (0 <= idx < len(g.businesses)):
            return
        b = g.businesses[idx]
        if b.workers <= 0:
            self.msg.err(f"{b.name} has no workers.")
            return
        if not ConfirmDialog(self, f"Fire a worker from {b.name}?", "Fire Worker").wait():
            return
        if b.hired_workers:
            b.hired_workers.pop()
        b.workers -= 1
        self.msg.ok(f"Fired a worker from {b.name}.")
        self.app.refresh()

    def _do_repair(self) -> None:
        row = self._table.selected()
        if not row:
            self.msg.warn("Select a broken business to repair.")
            return
        g   = self.game
        idx = self._idx(row)
        if not (0 <= idx < len(g.businesses)):
            return
        b = g.businesses[idx]
        if not b.broken_down:
            self.msg.info(f"{b.name} is not broken.")
            return
        cost = b.repair_cost
        if not ConfirmDialog(self, f"Repair {b.name} for {cost:.0f}g?", "Repair").wait():
            return
        if g.inventory.gold < cost:
            self.msg.err(f"Need {cost:.0f}g.")
            return
        g.inventory.gold -= cost
        b.broken_down = False
        b.repair_cost = 0.0
        self.msg.ok(f"{b.name} repaired!")
        self.app.refresh()

    def _do_sell(self) -> None:
        row = self._table.selected()
        if not row:
            self.msg.warn("Select a business to sell.")
            return
        g   = self.game
        idx = self._idx(row)
        if not (0 <= idx < len(g.businesses)):
            return
        b          = g.businesses[idx]
        sell_price = round(b.purchase_cost * 0.5 * (1 + (b.level - 1) * 0.2))
        if not ConfirmDialog(
            self,
            f"Sell {b.name} for {sell_price}g?\n(50% resale + level bonus)",
            "Sell Business",
        ).wait():
            return
        g.businesses.pop(idx)
        g.inventory.gold += sell_price
        self.msg.ok(f"Sold {b.name} for {sell_price}g.")
        self.app.refresh()


class FinanceScreen(Screen):
    """Banking & Finance screen — mirrors banking_menu() from the CLI."""

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        self.section_label(main, "BANKING & FINANCE").pack(anchor="w", padx=10, pady=(0, 4))

        nb = ttk.Notebook(main, style="MT.TNotebook")
        nb.pack(fill="both", expand=True, padx=10, pady=4)

        # ── Overview ──────────────────────────────────────────────────────────
        ov_tab = ttk.Frame(nb, style="MT.TFrame")
        nb.add(ov_tab, text="  Overview  ")

        self._overview_txt = tk.Text(
            ov_tab, bg=T["bg"], fg=T["fg"], font=FONT_MONO,
            relief="flat", height=8, state="disabled", padx=12, pady=8,
        )
        self._overview_txt.pack(fill="x", padx=6, pady=4)

        ov_act = ttk.Frame(ov_tab, style="MT.TFrame")
        ov_act.pack(fill="x", padx=6, pady=4)
        ttk.Button(ov_act, text="Deposit",    style="OK.TButton",
                   command=self._do_deposit).pack(side="left", padx=(0, 6))
        ttk.Button(ov_act, text="Withdraw",   style="MT.TButton",
                   command=self._do_withdraw).pack(side="left", padx=(0, 6))
        ttk.Button(ov_act, text="Take Loan",  style="MT.TButton",
                   command=self._do_loan).pack(side="left", padx=(0, 6))
        ttk.Button(ov_act, text="Open CD",    style="MT.TButton",
                   command=self._do_cd).pack(side="left", padx=(0, 6))

        # ── CDs ───────────────────────────────────────────────────────────────
        cd_tab = ttk.Frame(nb, style="MT.TFrame")
        nb.add(cd_tab, text="  Certificates  ")
        self._cd_table = DataTable(cd_tab, [
            ("principal", "Principal", 110),
            ("rate",      "Rate",       80),
            ("payout",    "Payout",    110),
            ("profit",    "Profit",     90),
            ("days_left", "Days Left",  90),
            ("term",      "Term",       70),
        ], height=10)
        self._cd_table.pack(fill="both", expand=True, padx=6, pady=4)

        # ── Loans ─────────────────────────────────────────────────────────────
        loan_tab = ttk.Frame(nb, style="MT.TFrame")
        nb.add(loan_tab, text="  Loans  ")
        self._loan_table = DataTable(loan_tab, [
            ("principal", "Principal",   110),
            ("rate",      "Rate/mo",      90),
            ("monthly",   "Monthly",      90),
            ("months",    "Months Left",  95),
            ("total",     "Total Left",  100),
        ], height=9)
        self._loan_table.pack(fill="both", expand=True, padx=6, pady=4)
        ln_act = ttk.Frame(loan_tab, style="MT.TFrame")
        ln_act.pack(fill="x", padx=6, pady=4)
        ttk.Button(ln_act, text="Repay Selected Loan (Lump Sum)",
                   style="Danger.TButton", command=self._do_repay).pack(side="left")

        ttk.Separator(main, style="MT.TSeparator").pack(fill="x", padx=10, pady=(4, 2))
        self.back_button(main).pack(anchor="w", padx=10, pady=4)

    def refresh(self) -> None:
        if not hasattr(self, "_overview_txt"):
            return
        g  = self.game
        mr = 0.015 + g.skills.banking * 0.002
        ad = g._absolute_day()
        text = (
            f"  Wallet:        {g.inventory.gold:>12.2f}g\n"
            f"  Bank Balance:  {g.bank_balance:>12.2f}g\n"
            f"  Net Worth:     {g._net_worth():>12.2f}g\n\n"
            f"  Savings Rate:  {mr * 100:.1f}%/month  (paid every 30 days)\n"
            f"  Banking Skill: Lv{g.skills.banking}  "
            f"(+{g.skills.banking * 0.002 * 100:.1f}%/mo bonus)\n"
            f"  Active CDs:    {len(g.cds)}\n"
            f"  Active Loans:  {len(g.loans)}\n"
        )
        self._overview_txt.config(state="normal")
        self._overview_txt.delete("1.0", "end")
        self._overview_txt.insert("1.0", text)
        self._overview_txt.config(state="disabled")

        cd_rows = []
        for cd in g.cds:
            dl   = cd.maturity_day - ad
            pay  = round(cd.principal * (1 + cd.rate), 2)
            prof = round(pay - cd.principal, 2)
            cd_rows.append({
                "principal": f"{cd.principal:.0f}g",
                "rate":      f"{cd.rate * 100:.0f}%",
                "payout":    f"{pay:.0f}g",
                "profit":    f"+{prof:.0f}g",
                "days_left": str(max(0, dl)),
                "term":      f"{cd.term_days}d",
                "tag": "red" if dl <= 5 else ("yellow" if dl <= 15 else "green"),
            })
        self._cd_table.load(cd_rows, tag_key="tag")

        loan_rows = []
        for loan in g.loans:
            total_left = round(loan.monthly_payment * loan.months_remaining, 2)
            loan_rows.append({
                "principal": f"{loan.principal:.0f}g",
                "rate":      f"{loan.interest_rate * 100:.2f}%",
                "monthly":   f"{loan.monthly_payment:.2f}g",
                "months":    str(loan.months_remaining),
                "total":     f"{total_left:.0f}g",
            })
        self._loan_table.load(loan_rows)

    def _do_deposit(self) -> None:
        g   = self.game
        raw = InputDialog(
            self, f"Deposit into savings.\nWallet: {g.inventory.gold:.0f}g\nAmount:", "Deposit"
        ).wait()
        if raw is None:
            return
        try:
            amt = float(raw)
        except ValueError:
            self.msg.err("Invalid amount.")
            return
        if amt <= 0 or amt > g.inventory.gold:
            self.msg.err("Invalid amount.")
            return
        g.inventory.gold -= amt
        g.bank_balance   += amt
        self.msg.ok(f"Deposited {amt:.2f}g.")
        self.app.refresh()

    def _do_withdraw(self) -> None:
        g   = self.game
        raw = InputDialog(
            self, f"Withdraw from savings.\nBank: {g.bank_balance:.0f}g\nAmount:", "Withdraw"
        ).wait()
        if raw is None:
            return
        try:
            amt = float(raw)
        except ValueError:
            self.msg.err("Invalid amount.")
            return
        if amt <= 0 or amt > g.bank_balance:
            self.msg.err("Invalid amount.")
            return
        g.bank_balance   -= amt
        g.inventory.gold += amt
        self.msg.ok(f"Withdrew {amt:.2f}g.")
        self.app.refresh()

    def _do_loan(self) -> None:
        g = self.game
        # Rate: 1.8%/mo base + credit-risk penalty - banking bonus, clamped 0.6%-4.0%/mo
        credit_pen = max(0.0, (50 - g.reputation) / 100)
        rate       = round(max(0.006, min(0.040,
                           0.018 + credit_pen * 0.008 - g.skills.banking * 0.001)), 4)
        max_loan   = max(500.0, g._net_worth() * 0.4)
        term_choice = ChoiceDialog(
            self,
            f"Select a loan term:\n\n"
            f"  Rate: {rate * 100:.2f}%/month  (rep & banking skill adjustable)\n"
            f"  Max available: {max_loan:.0f}g",
            ["6 months", "12 months"],
            title="Loan Term",
        ).wait()
        if term_choice is None:
            return
        months = 6 if term_choice == 0 else 12
        raw = InputDialog(
            self,
            f"Loan amount (1–{max_loan:.0f}g):\n"
            f"Rate: {rate * 100:.2f}%/mo  ·  Term: {months} months",
            "Take Loan",
        ).wait()
        if raw is None:
            return
        try:
            amt = float(raw)
        except ValueError:
            self.msg.err("Invalid amount.")
            return
        if not (1 <= amt <= max_loan):
            self.msg.err(f"Amount must be 1–{max_loan:.0f}g.")
            return
        monthly = round(
            amt * (rate * (1 + rate) ** months) / ((1 + rate) ** months - 1), 2
        )
        g.loans.append(LoanRecord(
            principal=amt, interest_rate=rate,
            months_remaining=months, monthly_payment=monthly,
        ))
        g.inventory.gold += amt
        self.msg.ok(
            f"Loan of {amt:.0f}g approved.  Monthly: {monthly:.2f}g × {months} months."
        )
        self.app.refresh()

    # CD tier definitions: (days, display_label, base_rate)
    _CD_TIERS = [
        (30,  "Short-Term   (30 days) ",  0.08),
        (90,  "Standard     (90 days) ",  0.26),
        (180, "Extended    (180 days) ",  0.55),
        (360, "Long-Term   (360 days) ",  1.20),
    ]

    def _do_cd(self) -> None:
        g     = self.game
        bonus = g.skills.banking * 0.02   # +2% per Banking level on all tiers
        if g.bank_balance <= 0:
            self.msg.err("No bank balance to invest.")
            return
        tier_labels = [
            f"{label.strip()}   →   {(rate + bonus) * 100:.0f}% return"
            for _, label, rate in self._CD_TIERS
        ]
        tier_idx = ChoiceDialog(
            self,
            f"Choose a CD term:\n\nBank Balance: {g.bank_balance:.0f}g"
            f"   ·   Banking skill bonus: +{bonus * 100:.0f}%",
            tier_labels,
            title="Open CD",
        ).wait()
        if tier_idx is None:
            return
        term_days, label, base_rate = self._CD_TIERS[tier_idx]
        rate = round(base_rate + bonus, 4)
        raw = InputDialog(
            self,
            f"{label.strip()}   →   {rate * 100:.0f}% return\n"
            f"Bank Balance: {g.bank_balance:.0f}g\nAmount to invest:",
            "Open CD",
        ).wait()
        if raw is None:
            return
        try:
            amt = float(raw)
        except ValueError:
            self.msg.err("Invalid amount.")
            return
        if amt <= 0 or amt > g.bank_balance:
            self.msg.err(f"Need {amt:.0f}g in bank (have {g.bank_balance:.0f}g).")
            return
        g.bank_balance -= amt
        g.cds.append(CDRecord(
            principal=amt, rate=rate,
            maturity_day=g._absolute_day() + term_days, term_days=term_days,
        ))
        payout = round(amt * (1 + rate), 2)
        self.msg.ok(
            f"CD opened: {amt:.0f}g → {payout:.0f}g in {term_days} days "
            f"(+{payout - amt:.0f}g, {rate * 100:.0f}% return)."
        )
        self.app.refresh()

    def _do_repay(self) -> None:
        row = self._loan_table.selected()
        if not row:
            self.msg.warn("Select a loan to repay.")
            return
        g = self.game
        if not g.loans:
            self.msg.err("No active loans.")
            return
        try:
            principal = float(row.get("principal", "0").rstrip("g"))
        except ValueError:
            self.msg.err("Could not identify loan.")
            return
        loan = next((l for l in g.loans if abs(l.principal - principal) < 0.01), None)
        if not loan:
            self.msg.err("Could not match loan.")
            return
        total_left = round(loan.monthly_payment * loan.months_remaining, 2)
        if not ConfirmDialog(
            self, f"Repay entire loan early?\nTotal due: {total_left:.2f}g", "Repay Loan"
        ).wait():
            return
        if g.inventory.gold < total_left:
            self.msg.err(f"Need {total_left:.2f}g.  Have {g.inventory.gold:.2f}g.")
            return
        g.inventory.gold -= total_left
        g.loans.remove(loan)
        self.msg.ok(f"Loan fully repaid ({total_left:.0f}g).")
        self.app.refresh()


class ContractsScreen(Screen):
    """
    Contracts — mirrors the CLI contracts_menu() two-phase workflow:
      1. Generate 3 contract OFFERS (not yet committed).
      2. Player reviews terms and accepts the ones they want.
      3. Accepted contracts sit in Active list until fulfilled.
    """

    _OFFER_COLS = [
        ("item",    "Item",        152),
        ("qty",     "Qty",          48),
        ("dest",    "Deliver To",  135),
        ("ppu",     "Contract/ea",  80),
        ("mkt",     "Market@",      72),
        ("vs",      "Vs.Mkt",       60),
        ("bonus",   "Bonus",         66),
        ("penalty", "Penalty",       66),
        ("days",    "Deadline",      60),
    ]
    _ACTIVE_COLS = [
        ("item",    "Item",        155),
        ("qty",     "Qty",          48),
        ("dest",    "Deliver To",  138),
        ("ppu",     "Contract/ea",  80),
        ("bonus",   "Bonus",         66),
        ("penalty", "Penalty",       66),
        ("days",    "Days Left",     68),
        ("status",  "Status",        90),
    ]

    def __init__(self, parent: tk.Widget, app: "GameApp") -> None:
        super().__init__(parent, app)
        self._pending: List[Contract] = []   # generated but not yet accepted

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        hdr = ttk.Frame(main, style="MT.TFrame")
        hdr.pack(fill="x", padx=10, pady=(0, 2))
        self.section_label(hdr, "CONTRACTS").pack(side="left")
        self._lic_lbl = tk.Label(hdr, text="", font=FONT_MONO_S,
                                 bg=T["bg"], fg=T["red"])
        self._lic_lbl.pack(side="right")

        # ── STEP 1 — Available offers ──────────────────────────────────────
        self.section_label(main, "STEP 1 — CONTRACT OFFERS").pack(
            anchor="w", padx=10, pady=(4, 1))
        tk.Label(
            main,
            text="Generate 3 fresh offers, review the terms, then accept the ones you want.",
            font=FONT_MONO_S, bg=T["bg"], fg=T["grey"], anchor="w", padx=10,
        ).pack(fill="x")

        self._offer_table = DataTable(main, self._OFFER_COLS, height=5)
        self._offer_table.pack(fill="x", padx=10, pady=(4, 2))

        offer_act = ttk.Frame(main, style="MT.TFrame")
        offer_act.pack(fill="x", padx=10, pady=(2, 4))
        ttk.Button(offer_act, text="Generate New Offers",
                   style="MT.TButton",
                   command=self._do_generate).pack(side="left", padx=(0, 6))
        ttk.Button(offer_act, text="Accept Selected Offer",
                   style="OK.TButton",
                   command=self._do_accept).pack(side="left", padx=(0, 6))
        ttk.Button(offer_act, text="Accept All",
                   style="OK.TButton",
                   command=self._do_accept_all).pack(side="left", padx=(0, 6))
        ttk.Button(offer_act, text="Discard All Offers",
                   style="Danger.TButton",
                   command=self._do_discard).pack(side="left")

        ttk.Separator(main, style="MT.TSeparator").pack(
            fill="x", padx=10, pady=(4, 4))

        # ── STEP 2 — Active contracts ──────────────────────────────────────
        self.section_label(main, "STEP 2 — YOUR ACTIVE CONTRACTS").pack(
            anchor="w", padx=10, pady=(2, 1))
        tk.Label(
            main,
            text="Travel to the destination with the goods, then select the contract and Fulfill.",
            font=FONT_MONO_S, bg=T["bg"], fg=T["grey"], anchor="w", padx=10,
        ).pack(fill="x")

        self._table = DataTable(main, self._ACTIVE_COLS, height=7)
        self._table.pack(fill="both", expand=True, padx=10, pady=(4, 2))

        act = ttk.Frame(main, style="MT.TFrame")
        act.pack(fill="x", padx=10, pady=4)
        ttk.Button(act, text="Fulfill Selected Contract",
                   style="OK.TButton",
                   command=self._do_fulfill).pack(side="left", padx=(0, 8))
        ttk.Button(act, text="Fulfill All Eligible",
                   style="MT.TButton",
                   command=self._do_fulfill_all).pack(side="left", padx=(0, 8))
        self.back_button(act).pack(side="left")

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        if not hasattr(self, "_table"):
            return
        g       = self.game
        has_lic = LicenseType.CONTRACTS in g.licenses
        self._lic_lbl.config(
            text="" if has_lic
            else "⚠ No Contract Seal — buy from Licenses"
        )

        # Offer / pending table
        offer_rows: List[Dict] = []
        for con in self._pending:
            item = ALL_ITEMS.get(con.item_key)
            if not item:
                continue
            dest_mkt = g.markets[con.destination]
            mref = (dest_mkt.get_sell_price(con.item_key, g.season, g.skills.trading)
                    if con.item_key in dest_mkt.item_keys
                    else item.base_price)
            vs   = (con.price_per_unit - mref) / max(mref, 0.01) * 100
            days = con.deadline_day - g._absolute_day()
            offer_rows.append({
                "item":    item.name,
                "qty":     str(con.quantity),
                "dest":    con.destination.value,
                "ppu":     f"{con.price_per_unit:.1f}g",
                "mkt":     f"{mref:.1f}g",
                "vs":      f"{vs:+.0f}%",
                "bonus":   f"+{con.reward_bonus:.0f}g",
                "penalty": f"-{con.penalty:.0f}g",
                "days":    f"{days}d",
                "tag":     "green" if vs >= 3 else ("red" if vs < -10 else "yellow"),
                "_cid":    con.id,
            })
        if not offer_rows:
            offer_rows = [{
                "item": "— No offers yet.  Click 'Generate New Offers' to request 3 contracts. —",
                "qty": "", "dest": "", "ppu": "", "mkt": "", "vs": "",
                "bonus": "", "penalty": "", "days": "", "tag": "dim", "_cid": -1,
            }]
        self._offer_table.load(offer_rows, tag_key="tag")

        # Active contracts table
        rows: List[Dict] = []
        for con in g.contracts:
            if con.fulfilled:
                continue
            item   = ALL_ITEMS.get(con.item_key)
            name   = item.name if item else con.item_key
            dl     = con.deadline_day - g._absolute_day()
            ready  = (
                g.current_area == con.destination
                and g.inventory.items.get(con.item_key, 0) >= con.quantity
            )
            status = "✓ READY" if ready else ("EXPIRED" if dl <= 0 else "Pending")
            tag    = "green" if ready else ("red" if dl <= 0 else
                     "red" if dl < 5 else "yellow" if dl < 15 else "")
            rows.append({
                "item":    name,
                "qty":     str(con.quantity),
                "dest":    con.destination.value,
                "ppu":     f"{con.price_per_unit:.2f}g",
                "bonus":   f"+{con.reward_bonus:.0f}g",
                "penalty": f"-{con.penalty:.0f}g",
                "days":    str(max(0, dl)),
                "status":  status,
                "tag":     tag,
                "_cid":    con.id,
            })
        self._table.load(rows, tag_key="tag")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _do_generate(self) -> None:
        import random
        g = self.game
        if LicenseType.CONTRACTS not in g.licenses:
            self.msg.err("You need a Trade Contract Seal (Licenses screen).")
            return
        available   = [k for k in ALL_ITEMS if not ALL_ITEMS[k].illegal]
        other_areas = [a for a in Area if a != g.current_area]
        if not other_areas:
            self.msg.err("No other areas to send contracts to.")
            return
        self._pending.clear()
        for _ in range(3):
            item_key = random.choice(available)
            item     = ALL_ITEMS[item_key]
            dest     = random.choice(other_areas)
            dest_mkt = g.markets[dest]
            mref     = (dest_mkt.get_sell_price(item_key, g.season, g.skills.trading)
                        if item_key in dest_mkt.item_keys
                        else item.base_price)
            modifier = random.choices(
                [random.uniform(0.80, 0.92),
                 random.uniform(0.92, 1.05),
                 random.uniform(1.05, 1.15)],
                weights=[30, 50, 20],
            )[0]
            price     = round(mref * modifier, 2)
            qty       = (random.randint(8, 50) if item.base_price < 40
                         else random.randint(3, 20))
            deadline  = g._absolute_day() + random.randint(12, 45)
            bonus     = round(qty * item.base_price * random.uniform(0.10, 0.25), 2)
            penalty   = round(qty * item.base_price * random.uniform(0.15, 0.35), 2)
            self._pending.append(Contract(
                id=g.next_contract_id,
                item_key=item_key, quantity=qty, price_per_unit=price,
                destination=dest, deadline_day=deadline,
                reward_bonus=bonus, penalty=penalty,
            ))
            g.next_contract_id += 1
        self.app.refresh()
        self.msg.ok("3 contract offers generated — review the terms and accept what you want.")

    def _do_accept(self) -> None:
        row = self._offer_table.selected()
        if not row or row.get("_cid", -1) < 0:
            self.msg.warn("Select an offer from the table above to accept it.")
            return
        con = next((c for c in self._pending if c.id == row["_cid"]), None)
        if not con:
            self.msg.warn("Could not find the selected offer.")
            return
        self._pending.remove(con)
        self.game.contracts.append(con)
        item = ALL_ITEMS.get(con.item_key)
        name = item.name if item else con.item_key
        self.app.refresh()
        self.msg.ok(
            f"Accepted: {con.quantity}× {name}  @{con.price_per_unit:.1f}g/ea"
            f"  →  {con.destination.value}  (+{con.reward_bonus:.0f}g bonus)"
        )

    def _do_accept_all(self) -> None:
        if not self._pending:
            self.msg.warn("No pending offers to accept.")
            return
        n = len(self._pending)
        self.game.contracts.extend(self._pending)
        self._pending.clear()
        self.app.refresh()
        self.msg.ok(f"Accepted all {n} contract offer(s) — check Active Contracts below.")

    def _do_discard(self) -> None:
        if not self._pending:
            self.msg.warn("No pending offers to discard.")
            return
        n = len(self._pending)
        self._pending.clear()
        self.app.refresh()
        self.msg.ok(f"Discarded {n} pending offer(s).")

    def _do_fulfill(self) -> None:
        row = self._table.selected()
        if not row:
            self.msg.warn("Select a contract from the Active list to fulfill.")
            return
        g   = self.game
        cid = row.get("_cid", -1)
        con = next((c for c in g.contracts
                    if not c.fulfilled and c.id == cid), None)
        if not con:
            # legacy fallback: match by item name + destination
            con = next(
                (c for c in g.contracts
                 if not c.fulfilled
                 and ALL_ITEMS.get(c.item_key)
                 and ALL_ITEMS[c.item_key].name == row.get("item", "")
                 and c.destination.value == row.get("dest", "")),
                None,
            )
        if not con:
            self.msg.err("Could not match the selected contract.")
            return
        if g.current_area != con.destination:
            self.msg.err(f"You must be in {con.destination.value} to fulfill this.")
            return
        have = g.inventory.items.get(con.item_key, 0)
        item = ALL_ITEMS.get(con.item_key)
        name = item.name if item else con.item_key
        if have < con.quantity:
            self.msg.err(f"Need {con.quantity}× {name}, you only have {have}.")
            return
        dl      = con.deadline_day - g._absolute_day()
        on_time = dl >= 0
        pay     = con.price_per_unit * con.quantity
        adjust  = con.reward_bonus if on_time else -con.penalty
        total   = pay + adjust
        g.inventory.remove(con.item_key, con.quantity)
        g.inventory.gold = max(0.0, g.inventory.gold + total)
        con.fulfilled = True
        g._gain_skill_xp(SkillType.TRADING, 25)
        g._track_stat("contracts_completed")
        if on_time:
            g.reputation = min(100, g.reputation + 3)
            g._track_stat("contracts_ontime")
            g.ach_stats["contracts_streak"] = g.ach_stats.get("contracts_streak", 0) + 1
            if con.reward_bonus > g.ach_stats.get("max_contract_bonus", 0):
                g.ach_stats["max_contract_bonus"] = con.reward_bonus
            if dl == 0:
                g._track_stat("contract_close_call", True)
            self.msg.ok(
                f"Contract fulfilled on time!  +{pay:.0f}g + {con.reward_bonus:.0f}g bonus"
                f" = {total:.0f}g total."
            )
        else:
            g.reputation = max(0, g.reputation - 5)
            g.ach_stats["contracts_streak"] = 0
            self.msg.warn(
                f"Contract fulfilled LATE!  +{pay:.0f}g − {con.penalty:.0f}g penalty"
                f" = {total:.0f}g total."
            )
        g._check_achievements()
        self.app.profit_flash(total)
        self.app.refresh()
        self.app._flush_achievements()

    def _do_fulfill_all(self) -> None:
        """Fulfill every eligible contract at the current destination in one click."""
        g = self.game
        eligible = [
            c for c in g.contracts
            if not c.fulfilled
            and c.destination == g.current_area
            and g.inventory.items.get(c.item_key, 0) >= c.quantity
        ]
        if not eligible:
            self.msg.warn("No eligible contracts to fulfill here.")
            return
        total_gold = 0.0
        fulfilled_n = 0
        for con in eligible:
            have = g.inventory.items.get(con.item_key, 0)
            if have < con.quantity:
                continue  # inventory may have shrunk during loop
            dl      = con.deadline_day - g._absolute_day()
            on_time = dl >= 0
            pay     = con.price_per_unit * con.quantity
            adjust  = con.reward_bonus if on_time else -con.penalty
            total   = pay + adjust
            g.inventory.remove(con.item_key, con.quantity)
            g.inventory.gold = max(0.0, g.inventory.gold + total)
            con.fulfilled = True
            g._gain_skill_xp(SkillType.TRADING, 25)
            g._track_stat("contracts_completed")
            if on_time:
                g.reputation = min(100, g.reputation + 3)
                g._track_stat("contracts_ontime")
                g.ach_stats["contracts_streak"] = g.ach_stats.get("contracts_streak", 0) + 1
                if con.reward_bonus > g.ach_stats.get("max_contract_bonus", 0):
                    g.ach_stats["max_contract_bonus"] = con.reward_bonus
            else:
                g.reputation = max(0, g.reputation - 5)
                g.ach_stats["contracts_streak"] = 0
            total_gold  += total
            fulfilled_n += 1
        if fulfilled_n == 0:
            self.msg.warn("Could not fulfill any contracts (insufficient goods?).")
            return
        g._check_achievements()
        self.app.profit_flash(total_gold)
        self.app.refresh()
        self.app._flush_achievements()
        self.msg.ok(
            f"Fulfilled {fulfilled_n} contract{'s' if fulfilled_n != 1 else ''}  →  "
            f"+{total_gold:.0f}g total."
        )


class SkillsScreen(Screen):
    """Skills & Upgrades screen — mirrors skills_menu() from the CLI."""

    _DESCS = {
        SkillType.TRADING:   "Improves buy/sell price margins",
        SkillType.HAGGLING:  "Chance and size of purchase discounts",
        SkillType.LOGISTICS: "Carry weight capacity (+20 wt per level)",
        SkillType.INDUSTRY:  "Business daily production multiplier",
        SkillType.ESPIONAGE: "Reveals competitor prices & market info",
        SkillType.BANKING:   "Better interest rates and loan terms",
    }

    _COLS = [
        ("skill", "Skill",        120),
        ("level", "Level",         60),
        ("xp",    "XP",            70),
        ("cost",  "Upgrade Cost", 110),
        ("desc",  "Description",  400),
    ]

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        hdr = ttk.Frame(main, style="MT.TFrame")
        hdr.pack(fill="x", padx=10, pady=(0, 4))
        self.section_label(hdr, "SKILLS & UPGRADES").pack(side="left")
        self._gold_lbl = tk.Label(hdr, text="", font=FONT_MONO, bg=T["bg"], fg=T["yellow"])
        self._gold_lbl.pack(side="right")

        self._table = DataTable(main, self._COLS, height=8)
        self._table.pack(fill="x", padx=10, pady=4)
        self._table.bind_select(self._on_select)

        self._detail_lbl = tk.Label(
            main, text="Select a skill to see details.",
            font=FONT_MONO_S, bg=T["bg_panel"], fg=T["grey"], anchor="w", padx=12, pady=5,
        )
        self._detail_lbl.pack(fill="x", padx=10, pady=(0, 4))

        act = ttk.Frame(main, style="MT.TFrame")
        act.pack(fill="x", padx=10, pady=4)
        ttk.Button(act, text="Upgrade Selected Skill", style="OK.TButton",
                   command=self._do_upgrade).pack(side="left")

        ttk.Separator(main, style="MT.TSeparator").pack(fill="x", padx=10, pady=(8, 4))
        self.back_button(main).pack(anchor="w", padx=10)

    def refresh(self) -> None:
        if not hasattr(self, "_table"):
            return
        g = self.game
        self._gold_lbl.config(text=f"Gold: {g.inventory.gold:,.0f}g")
        rows = []
        for skill in SkillType:
            level = getattr(g.skills, skill.value.lower())
            xp    = g.skills.xp.get(skill.value, 0)
            cost  = g.skills.level_up_cost(skill)
            rows.append({
                "skill": skill.value,
                "level": f"Lv{level}",
                "xp":    str(xp),
                "cost":  f"{cost}g",
                "desc":  self._DESCS.get(skill, ""),
                "tag":   "green" if g.inventory.gold >= cost else "dim",
            })
        self._table.load(rows, tag_key="tag")

    def _on_select(self, row: Optional[Dict]) -> None:
        if not row:
            return
        g          = self.game
        skill_name = row.get("skill", "")
        try:
            skill = next(s for s in SkillType if s.value == skill_name)
        except StopIteration:
            return
        level  = getattr(g.skills, skill.value.lower())
        cost   = g.skills.level_up_cost(skill)
        xp     = g.skills.xp.get(skill.value, 0)
        afford = ("  ✓ can afford" if g.inventory.gold >= cost
                  else f"  ✗ need {cost - g.inventory.gold:.0f}g more")
        self._detail_lbl.config(
            text=(f"{skill_name}  Lv{level}  ·  XP: {xp}"
                  f"  ·  Next level: {cost}g{afford}"
                  f"  ·  {self._DESCS.get(skill, '')}"),
            fg=T["fg"],
        )

    def _do_upgrade(self) -> None:
        row = self._table.selected()
        if not row:
            self.msg.warn("Select a skill to upgrade.")
            return
        g          = self.game
        skill_name = row.get("skill", "")
        try:
            skill = next(s for s in SkillType if s.value == skill_name)
        except StopIteration:
            self.msg.err("Unknown skill.")
            return
        cost   = g.skills.level_up_cost(skill)
        cur_lv = getattr(g.skills, skill.value.lower())
        if not ConfirmDialog(
            self,
            f"Upgrade {skill_name}  Lv{cur_lv} → Lv{cur_lv + 1}\nCost: {cost}g",
            "Upgrade Skill",
        ).wait():
            return
        success, new_gold = g.skills.try_level_up(skill, g.inventory.gold)
        if success:
            g.inventory.gold = new_gold
            new_lv = getattr(g.skills, skill.value.lower())
            self.msg.ok(f"{skill_name} upgraded to Lv{new_lv}!")
            g._check_achievements()
            self.app.refresh()
            self.app._flush_achievements()
        else:
            self.msg.err(f"Not enough gold. Need {cost}g, have {g.inventory.gold:.0f}g.")


class SmugglingScreen(Screen):
    """Smuggling Den — split-pane layout: Buy table (left) / Sell table (right)."""

    _BUY_COLS  = [
        ("item",  "Contraband",    168),
        ("price", "Informant",      78),
        ("wt",    "Wt/ea",          50),
        ("catch", "CatchChance",    88),
    ]
    _SELL_COLS = [
        ("item",  "Contraband",    155),
        ("qty",   "Have",           48),
        ("value", "Fence Value",    86),
        ("base",  "Base Price",     78),
    ]

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        self.section_label(main, "SMUGGLING DEN").pack(anchor="w", padx=10, pady=(0, 4))

        # ── Status strip ──────────────────────────────────────────────────────
        self._heat_lbl = tk.Label(main, text="", font=FONT_MONO,
                                  bg=T["bg"], fg=T["red"], anchor="w", padx=10)
        self._heat_lbl.pack(fill="x")
        self._detail_lbl = tk.Label(main, text="", font=FONT_MONO_S,
                                    bg=T["bg"], fg=T["grey"], anchor="w", padx=10)
        self._detail_lbl.pack(fill="x", pady=(0, 6))

        # ── Split pane ────────────────────────────────────────────────────────
        split = ttk.Frame(main, style="MT.TFrame")
        split.pack(fill="both", expand=True, padx=10)

        # Left — Buy from Informant
        left = ttk.Frame(split, style="MT.TFrame")
        left.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.section_label(left, "BUY FROM INFORMANT").pack(anchor="w", pady=(0, 2))
        tk.Label(left, text="1.25× base price · +8 heat per deal",
                 font=FONT_MONO_S, bg=T["bg"], fg=T["grey"], anchor="w",
                 ).pack(fill="x", pady=(0, 3))
        self._buy_table = DataTable(left, self._BUY_COLS, height=8)
        self._buy_table.pack(fill="both", expand=True)
        buy_act = ttk.Frame(left, style="MT.TFrame")
        buy_act.pack(fill="x", pady=(5, 0))
        tk.Label(buy_act, text="Qty:", font=FONT_MONO_S,
                 bg=T["bg"], fg=T["grey"]).pack(side="left")
        self._buy_qty = tk.StringVar(value="1")
        ttk.Entry(buy_act, textvariable=self._buy_qty,
                  style="MT.TEntry", width=7).pack(side="left", padx=(3, 6))
        ttk.Button(buy_act, text="Buy Selected",
                   style="MT.TButton", command=self._do_buy).pack(side="left")

        # Right — Sell to Fence
        right = ttk.Frame(split, style="MT.TFrame")
        right.pack(side="left", fill="both", expand=True, padx=(5, 0))
        self.section_label(right, "SELL TO FENCE").pack(anchor="w", pady=(0, 2))
        tk.Label(right, text="Fence% × base · +10 heat · catch check applies",
                 font=FONT_MONO_S, bg=T["bg"], fg=T["grey"], anchor="w",
                 ).pack(fill="x", pady=(0, 3))
        self._sell_table = DataTable(right, self._SELL_COLS, height=8)
        self._sell_table.pack(fill="both", expand=True)
        sell_act = ttk.Frame(right, style="MT.TFrame")
        sell_act.pack(fill="x", pady=(5, 0))
        tk.Label(sell_act, text="Qty:", font=FONT_MONO_S,
                 bg=T["bg"], fg=T["grey"]).pack(side="left")
        self._sell_qty = tk.StringVar(value="1")
        ttk.Entry(sell_act, textvariable=self._sell_qty,
                  style="MT.TEntry", width=7).pack(side="left", padx=(3, 6))
        ttk.Button(sell_act, text="Sell Selected",
                   style="Danger.TButton", command=self._do_sell).pack(side="left", padx=(0, 5))
        ttk.Button(sell_act, text="Sell All",
                   style="Danger.TButton", command=self._do_sell_all).pack(side="left")

        ttk.Separator(main, style="MT.TSeparator").pack(fill="x", padx=10, pady=(8, 4))
        bot = ttk.Frame(main, style="MT.TFrame")
        bot.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Button(bot, text="Bribe Guards  (−heat)",
                   style="MT.TButton", command=self._do_bribe).pack(side="left", padx=(0, 12))
        self.back_button(bot).pack(side="left")

    def refresh(self) -> None:
        if not hasattr(self, "_heat_lbl"):
            return
        g     = self.game
        esp   = g.skills.espionage
        guard = AREA_INFO[g.current_area].get("guard_strength", 0)
        cb    = max(0.04, min(0.65, 0.20 + g.heat / 200 - esp * 0.025))
        heat_col = T["red"] if g.heat > 60 else (T["yellow"] if g.heat > 30 else T["green"])
        try:
            fence_mult  = g._fence_multiplier()
            fence_label = g._fence_area_label()
        except Exception:
            fence_mult, fence_label = 0.85, g.current_area.value

        if g.heat >= 80:
            self._heat_lbl.config(
                text="⚠ HEAT TOO HIGH — travel to cool down before using Den.", fg=T["red"])
        else:
            self._heat_lbl.config(
                text=(f"Heat: {g.heat}/100   ·   Espionage Lv{esp}"
                      f"   ·   Guard: {guard}/3   ·   {g.current_area.value}"),
                fg=heat_col)
        self._detail_lbl.config(
            text=(f"Catch chance: {cb * 100:.0f}%   ·   "
                  f"Fence ({fence_label}): {fence_mult * 100:.0f}% of base   ·   "
                  f"Gold: {g.inventory.gold:.0f}g"))

        contraband = sorted(
            [(k, v) for k, v in ALL_ITEMS.items() if v.illegal],
            key=lambda x: x[1].name,
        )

        # Buy table — all illegal items
        buy_rows = []
        for k, item in contraband:
            inf_price = round(item.base_price * 1.25, 2)
            buy_rows.append({
                "item":  item.name,
                "price": f"{inf_price:.1f}g",
                "wt":    f"{item.weight:.1f}",
                "catch": f"{cb * 100:.0f}%",
                "tag":   "yellow",
            })
        self._buy_table.load(buy_rows, tag_key="tag")

        # Sell table — only items in your inventory
        sell_rows = []
        for k, item in contraband:
            qty = g.inventory.items.get(k, 0)
            if qty > 0:
                fv = round(item.base_price * fence_mult * qty, 1)
                sell_rows.append({
                    "item":  item.name,
                    "qty":   str(qty),
                    "value": f"{fv:.0f}g",
                    "base":  f"{item.base_price:.1f}g",
                    "tag":   "yellow",
                })
        if not sell_rows:
            sell_rows = [{"item": "— none held —", "qty": "", "value": "", "base": "", "tag": "dim"}]
        self._sell_table.load(sell_rows, tag_key="tag")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _key_from_name(self, name: str) -> Optional[str]:
        """Return the item key for a contraband item by its display name."""
        return next(
            (k for k, v in ALL_ITEMS.items() if v.illegal and v.name == name),
            None,
        )

    # ── Actions ───────────────────────────────────────────────────────────────

    def _do_buy(self) -> None:
        import random
        g   = self.game
        row = self._buy_table.selected()
        if not row:
            self.msg.warn("Select a contraband item in the left table.")
            return
        if g.heat >= 80:
            self.msg.err("Heat too high — travel to cool down first.")
            return
        k = self._key_from_name(row.get("item", ""))
        if not k:
            self.msg.err("Could not identify item.")
            return
        try:
            qty = int(self._buy_qty.get())
        except ValueError:
            self.msg.err("Invalid quantity.")
            return
        if qty <= 0:
            self.msg.err("Quantity must be ≥ 1.")
            return
        item  = ALL_ITEMS[k]
        price = round(item.base_price * 1.25, 2)
        total = round(price * qty, 2)
        if total > g.inventory.gold:
            self.msg.err(f"Need {total:.0f}g, have {g.inventory.gold:.0f}g.")
            return
        esp        = g.skills.espionage
        catch_base = max(0.04, min(0.65, 0.20 + g.heat / 200 - esp * 0.025))
        if random.random() < catch_base:
            # Sting — informant was a plant
            fine = round(total * 0.60, 2)
            g.inventory.gold = max(0.0, g.inventory.gold - fine)
            g.heat           = min(100, g.heat + 35)
            g.reputation     = max(0, g.reputation - 20)
            g._track_stat("smuggle_busts")
            g._check_achievements()
            self.msg.err(
                f"Sting! Informant was a plant.  Fine: {fine:.0f}g  Heat +35  Rep −20.")
            self.app.refresh()
            return
        g.inventory.gold -= total
        g.inventory.record_purchase(k, qty, price)
        g.inventory.add(k, qty)
        g.heat = min(100, g.heat + 8)
        g._gain_skill_xp(SkillType.ESPIONAGE, 10)
        g._use_time(1)
        self.msg.ok(f"Acquired {qty}× {item.name} for {total:.0f}g.  Heat +8 → {g.heat}.")
        self.app.sound.play_coin_sfx()
        self.app.refresh()

    def _do_sell(self) -> None:
        import random
        g   = self.game
        row = self._sell_table.selected()
        if not row:
            self.msg.warn("Select contraband in the right table to sell.")
            return
        if g.heat >= 80:
            self.msg.err("Heat too high — travel to cool down first.")
            return
        k = self._key_from_name(row.get("item", ""))
        if not k:
            self.msg.err("Could not identify item.")
            return
        item  = ALL_ITEMS[k]
        max_q = g.inventory.items.get(k, 0)
        if max_q <= 0:
            self.msg.err(f"You don't hold any {item.name}.")
            return
        try:
            qty = int(self._sell_qty.get())
        except ValueError:
            self.msg.err("Invalid quantity.")
            return
        if not (1 <= qty <= max_q):
            self.msg.err(f"Quantity must be 1–{max_q}.")
            return
        self._execute_sell(k, item, qty)

    def _do_sell_all(self) -> None:
        g   = self.game
        if g.heat >= 80:
            self.msg.err("Heat too high — travel to cool down first.")
            return
        row = self._sell_table.selected()
        if row:
            # Sell all of the selected item
            k = self._key_from_name(row.get("item", ""))
            if not k:
                self.msg.err("Could not identify item.")
                return
            item  = ALL_ITEMS[k]
            max_q = g.inventory.items.get(k, 0)
            if max_q <= 0:
                self.msg.err(f"You don't hold any {item.name}.")
                return
            self._execute_sell(k, item, max_q)
        else:
            # No selection → sell ALL illegal items in inventory
            illegal_keys = [
                k for k, qty in g.inventory.items.items()
                if ALL_ITEMS.get(k) and ALL_ITEMS[k].illegal and qty > 0
            ]
            if not illegal_keys:
                self.msg.warn("No contraband in inventory.")
                return
            for k in illegal_keys:
                if g.heat >= 80:
                    break  # stop if heat maxes out mid-sell
                qty = g.inventory.items.get(k, 0)
                if qty > 0:
                    self._execute_sell(k, ALL_ITEMS[k], qty)

    def _execute_sell(self, k: str, item, qty: int) -> None:
        import random
        g = self.game
        try:
            fence_mult = g._fence_multiplier()
        except Exception:
            fence_mult = 0.85
        catch_base = max(0.04, min(0.65, 0.20 + g.heat / 200 - g.skills.espionage * 0.025))
        sell_catch = min(0.70, catch_base + 0.05)   # slightly higher risk when selling
        fence_total = round(item.base_price * fence_mult * qty, 2)
        if random.random() < sell_catch:
            # Busted — items seized + fine
            fine = round(fence_total * 0.50, 2)
            g.inventory.remove(k, qty)
            g.inventory.gold = max(0.0, g.inventory.gold - fine)
            g.reputation     = max(0, g.reputation - 25)
            g.heat           = min(100, g.heat + 35)
            g._track_stat("smuggle_busts")
            g._check_achievements()
            self.msg.err(
                f"BUSTED! {qty}× {item.name} seized.  "
                f"Fine: {fine:.0f}g  Heat +35  Rep −25.")
            self.app.refresh()
            return
        g.inventory.remove(k, qty)
        g.inventory.gold += fence_total
        g.total_profit   += fence_total
        g.heat = min(100, g.heat + 10)
        g._gain_skill_xp(SkillType.ESPIONAGE, 15)
        g._track_stat("smuggle_success")
        g._track_stat("smuggle_gold", fence_total)
        g._use_time(1)
        g._check_achievements()
        self.msg.ok(
            f"Sold {qty}× {item.name} for {fence_total:.0f}g.  "
            f"Heat +10 → {g.heat}.")
        self.app.sound.play_coin_sfx()
        self.app.profit_flash(fence_total)
        self.app.refresh()

    def _do_bribe(self) -> None:
        import random
        g     = self.game
        guard = AREA_INFO[g.current_area].get("guard_strength", 0)
        if g.heat <= 0:
            self.msg.ok("No heat right now — nothing to bribe away.")
            return
        if guard == 0:
            self.msg.ok(
                f"No guards in {g.current_area.value} — "
                "heat fades naturally as you travel and rest.")
            return
        # CLI formula: cost scales with heat × guard tier
        bribe_cost = round(g.heat * (3 + guard * 4))
        reduction  = random.randint(20, 38)
        backfire   = max(0.03, min(0.40, 0.10 + g.heat / 200
                                   - g.skills.espionage * 0.012))
        if not ConfirmDialog(
            self,
            (f"Bribe guards to reduce heat.\n\n"
             f"  Heat now  : {g.heat}/100\n"
             f"  Cost      : {bribe_cost}g\n"
             f"  Reduction : ~{reduction} points  →  {max(0, g.heat - reduction)}\n"
             f"  Backfire  : {backfire * 100:.0f}%  (guard keeps gold & files report)"),
            "Bribe Guards",
        ).wait():
            return
        if g.inventory.gold < bribe_cost:
            self.msg.err(f"Not enough gold. Need {bribe_cost}g.")
            return
        g.inventory.gold -= bribe_cost
        if random.random() < backfire:
            g.heat       = min(100, g.heat + 15)
            g.reputation = max(0, g.reputation - 10)
            self.msg.warn(
                f"Guard pocketed {bribe_cost}g and filed a report anyway!  "
                f"Heat +15  Rep −10.")
        else:
            g.heat = max(0, g.heat - reduction)
            g._gain_skill_xp(SkillType.ESPIONAGE, 8)
            g._track_stat("bribes")
            g._check_achievements()
            self.msg.ok(
                f"Guard convinced.  Heat −{reduction} → {g.heat}/100.  "
                f"Cost: {bribe_cost}g.")
        self.app.refresh()
        self.app._flush_achievements()


class MarketInfoScreen(Screen):
    """
    Market Info — two tabs matching the CLI market_info_menu():
      Tab 1 "Local Market"   : price/stock/pressure/trend for current area.
      Tab 2 "Price Compare"  : full cross-area buy-price grid + best route.
    """

    # ── Local market columns ──────────────────────────────────────────────────
    _COLS = [
        ("item",     "Item",      185),
        ("price",    "Price",      78),
        ("stock",    "Stock",      62),
        ("pressure", "Pressure",   82),
        ("natural",  "Natural",    72),
        ("trend",    "Trend",      78),
    ]

    # ── Cross-area price grid columns ─────────────────────────────────────────
    # Area abbreviations (6 chars, matching the CLI _abbrev dict)
    _AREA_ABBREV = {
        Area.CITY:     "CapCty",
        Area.FARMLAND: "Farmld",
        Area.MOUNTAIN: "MtnPks",
        Area.COAST:    "Coast.",
        Area.FOREST:   "Forest",
        Area.DESERT:   "Desert",
        Area.SWAMP:    "Swamp.",
        Area.TUNDRA:   "Tundra",
    }
    _GRID_COLS = [
        ("item",     "Item",      160),
        ("cat",      "Category",   78),
        ("city",     "CapCty",     50),
        ("farmland", "Farmld",     50),
        ("mountain", "MtnPks",     50),
        ("coast",    "Coast.",     50),
        ("forest",   "Forest",     50),
        ("desert",   "Desert",     50),
        ("swamp",    "Swamp.",     50),
        ("tundra",   "Tundra",     50),
        ("route",    "Best Route",148),
        ("margin",   "Margin%",    60),
        ("profit",   "+Profit",    55),
    ]

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        hdr = ttk.Frame(main, style="MT.TFrame")
        hdr.pack(fill="x", padx=10, pady=(0, 4))
        self.section_label(hdr, "MARKET INFO").pack(side="left")
        self._area_lbl = tk.Label(hdr, text="", font=FONT_MONO,
                                  bg=T["bg"], fg=T["cyan"])
        self._area_lbl.pack(side="right")

        self._nb = ttk.Notebook(main, style="MT.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=10, pady=4)

        # ── Tab 1: Local Market ───────────────────────────────────────────────
        tab1 = ttk.Frame(self._nb, style="MT.TFrame")
        self._nb.add(tab1, text="  Local Market  ")

        self._events_lbl = tk.Label(
            tab1, text="", font=FONT_MONO_S,
            bg=T["bg"], fg=T["yellow"], anchor="w",
        )
        self._events_lbl.pack(fill="x", pady=(4, 4))

        self._table = DataTable(tab1, self._COLS, height=12)
        self._table.pack(fill="both", expand=True, pady=4)
        self._table.bind_double(self._show_history)

        for note in (
            "Double-click an item to see full price history.",
            "Pressure > natural = item is expensive (demand spike / active event).  "
            "Self-corrects ~20%/day.",
        ):
            tk.Label(tab1, text=note, font=FONT_MONO_S, bg=T["bg"],
                     fg=T["fg_dim"], anchor="w").pack(fill="x")

        # ── Tab 2: Price Compare ──────────────────────────────────────────────
        tab2 = ttk.Frame(self._nb, style="MT.TFrame")
        self._nb.add(tab2, text="  Price Compare  ")

        grid_hdr = ttk.Frame(tab2, style="MT.TFrame")
        grid_hdr.pack(fill="x", pady=(4, 2))
        ttk.Button(grid_hdr, text="↻  Refresh",
                   style="MT.TButton",
                   command=self._refresh_grid).pack(side="left")
        tk.Label(
            grid_hdr,
            text="  Buy prices across all areas.  Green ≥30% margin · Yellow ≥10%.",
            font=FONT_MONO_S, bg=T["bg"], fg=T["fg_dim"],
        ).pack(side="left")
        self._cur_area_note = tk.Label(
            grid_hdr, text="", font=FONT_MONO_S, bg=T["bg"], fg=T["cyan"],
        )
        self._cur_area_note.pack(side="right", padx=4)

        self._grid_table = DataTable(tab2, self._GRID_COLS, height=13)
        self._grid_table.pack(fill="both", expand=True, pady=4)

        # Activate grid refresh whenever the tab is switched to
        self._nb.bind("<<NotebookTabChanged>>", self._on_tab_change)

        ttk.Separator(main, style="MT.TSeparator").pack(
            fill="x", padx=10, pady=(4, 2))
        self.back_button(main).pack(anchor="w", padx=10, pady=4)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        if not hasattr(self, "_table"):
            return
        g      = self.game
        market = g.markets[g.current_area]
        self._area_lbl.config(text=f"📍  {g.current_area.value}")
        self._events_lbl.config(
            text=("Active events: " + "  ·  ".join(market.active_events))
            if market.active_events
            else "No active events in this area."
        )
        rows: List[Dict] = []
        for k in sorted(market.item_keys):
            item = ALL_ITEMS.get(k)
            if not item:
                continue
            # Use mid price (no buy markup, no noise) — matches CLI market_info_menu
            price    = market.get_price(k, g.season, noise=False)
            stock    = market.stock.get(k, 0)
            pressure = market.pressure.get(k, 1.0)
            natural  = market.natural_pressure.get(k, 1.0)
            hist     = list(market.history.get(k, []))
            if len(hist) >= 2:
                delta = (hist[-1].price - hist[-2].price) / max(hist[-2].price, 0.01) * 100
                trend = f"{'▲' if delta >= 0 else '▼'}{abs(delta):.1f}%"
                t_tag = "green" if delta > 0 else ("red" if delta < 0 else "dim")
            else:
                trend, t_tag = "─", "dim"
            p_ratio = pressure / max(natural, 0.01)
            p_tag   = "red"    if p_ratio > 1.2  else \
                      "green"  if p_ratio < 0.85 else ""
            s_tag   = "red"    if stock < 15 else \
                      "yellow" if stock < 40 else ""
            rows.append({
                "item":     item.name,
                "price":    f"{price:.2f}g",
                "stock":    str(stock),
                "pressure": f"{pressure:.3f}",
                "natural":  f"{natural:.3f}",
                "trend":    trend,
                "tag":      p_tag or s_tag or t_tag,
            })
        self._table.load(rows, tag_key="tag")

        # Refresh price grid only if that tab is visible
        if hasattr(self, "_nb") and self._nb.index("current") == 1:
            self._refresh_grid()

    def _on_tab_change(self, _ev) -> None:
        if hasattr(self, "_nb") and self._nb.index("current") == 1:
            self._refresh_grid()

    def _refresh_grid(self) -> None:
        """Rebuild the full cross-area buy-price comparison grid."""
        if not hasattr(self, "_grid_table"):
            return
        g     = self.game
        areas = list(Area)

        # Note which column represents the player's current area
        cur_abbrev = self._AREA_ABBREV.get(g.current_area, "")
        self._cur_area_note.config(
            text=f"Your location: {g.current_area.value} ({cur_abbrev})"
        )

        # Collect all tradeable keys, grouped by category
        all_keys: set = set()
        for mkt in g.markets.values():
            all_keys.update(mkt.item_keys)

        def _sort_key(k: str):
            item = ALL_ITEMS.get(k)
            return (item.category.value if item else "ZZZ",
                    item.name if item else k)

        rows: List[Dict] = []
        for k in sorted(all_keys, key=_sort_key):
            item = ALL_ITEMS.get(k)
            if not item:
                continue

            # Buy prices for every area that stocks this item
            buy_prices: Dict[Area, float] = {}
            sell_prices: Dict[Area, float] = {}
            for area in areas:
                mkt = g.markets.get(area)
                if mkt and k in mkt.item_keys:
                    buy_prices[area]  = mkt.get_buy_price(k, g.season, g.skills.trading)
                    sell_prices[area] = mkt.get_sell_price(k, g.season, g.skills.trading)

            if not buy_prices:
                continue

            min_buy_price  = min(buy_prices.values())
            max_sell_price = max(sell_prices.values()) if sell_prices else 0.0
            best_buy_area  = min(buy_prices, key=buy_prices.__getitem__)
            best_sell_area = max(sell_prices, key=sell_prices.__getitem__) if sell_prices else best_buy_area

            profit = max_sell_price - min_buy_price
            margin = profit / min_buy_price * 100 if min_buy_price > 0 else 0.0

            try:
                route_days = AREA_INFO[best_buy_area]["travel_days"].get(best_sell_area, 1)
            except (KeyError, TypeError):
                route_days = 1
            buy_ab  = self._AREA_ABBREV.get(best_buy_area,  best_buy_area.value[:6])
            sell_ab = self._AREA_ABBREV.get(best_sell_area, best_sell_area.value[:6])
            route   = f"{buy_ab} → {sell_ab} ({route_days}d)"

            row: Dict = {
                "item":   item.name,
                "cat":    item.category.value,
                "route":  route,
                "margin": f"{margin:.1f}%",
                "profit": f"{profit:+.1f}g",
                "tag":    "green" if margin >= 30 else ("yellow" if margin >= 10 else ""),
            }
            # Fill price cells for each area
            for area in areas:
                col_key = area.name.lower()
                row[col_key] = (f"{buy_prices[area]:.0f}g"
                                if area in buy_prices else "—")
            rows.append(row)

        if not rows:
            rows = [{
                "item": "No market data available.", "cat": "",
                "city": "", "farmland": "", "mountain": "", "coast": "",
                "forest": "", "desert": "", "swamp": "", "tundra": "",
                "route": "", "margin": "", "profit": "", "tag": "dim",
            }]

        self._grid_table.load(rows, tag_key="tag")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _show_history(self, row: Optional[Dict]) -> None:
        if not row:
            return
        g      = self.game
        market = g.markets[g.current_area]
        name   = row.get("item", "")
        k      = next(
            (k for k in market.item_keys
             if ALL_ITEMS.get(k) and ALL_ITEMS[k].name == name),
            None,
        )
        if not k:
            return
        hist = list(market.history.get(k, []))
        if not hist:
            InfoDialog(self, "Price History",
                       f"No price history for {name} yet.").wait()
            return
        lines = [f"Price history — {name}", "─" * 36]
        for pp in reversed(hist[-20:]):
            lines.append(f"  Day {pp.day:<5}  {pp.price:>8.2f}g")
        InfoDialog(self, f"Price History: {name}", "\n".join(lines)).wait()


class NewsScreen(Screen):
    """News & Events screen — mirrors info_menu() from the CLI."""

    _HINTS = {
        "Drought":        "Grain/fibre scarce — prices elevated.",
        "Flood":          "Farm & coastal goods disrupted.",
        "Bumper Harvest": "Crop prices lower than usual.",
        "Mine Collapse":  "Ore, coal & gems in short supply.",
        "Piracy Surge":   "Coastal goods hard to come by.",
        "Trade Boom":     "All goods in higher demand.",
        "Plague":         "Medicine & herbs extremely scarce.",
        "Border War":     "Steel & ore demand surging.",
        "Gold Rush":      "Gold dust prices softening.",
        "Grand Festival": "Luxury goods in peak demand.",
    }

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        self.section_label(main, "NEWS & EVENTS").pack(anchor="w", padx=10, pady=(0, 4))

        nb = ttk.Notebook(main, style="MT.TNotebook")
        nb.pack(fill="both", expand=True, padx=10, pady=4)

        ev_tab = ttk.Frame(nb, style="MT.TFrame")
        nb.add(ev_tab, text="  Active Events  ")
        self._ev_table = DataTable(ev_tab, [
            ("area",   "Area",    160),
            ("event",  "Event",   170),
            ("effect", "Effect",  490),
        ], height=10)
        self._ev_table.pack(fill="both", expand=True, padx=6, pady=4)

        feed_tab = ttk.Frame(nb, style="MT.TFrame")
        nb.add(feed_tab, text="  Headlines  ")
        self._feed_table = DataTable(feed_tab, [
            ("date",     "Date",      80),
            ("area",     "Area",     140),
            ("event",    "Event",    165),
            ("headline", "Headline", 480),
        ], height=12)
        self._feed_table.pack(fill="both", expand=True, padx=6, pady=4)

        log_tab = ttk.Frame(nb, style="MT.TFrame")
        nb.add(log_tab, text="  Event Log  ")
        self._log_table = DataTable(log_tab, [("entry", "Entry", 900)], height=14)
        self._log_table.pack(fill="both", expand=True, padx=6, pady=4)

        trade_tab = ttk.Frame(nb, style="MT.TFrame")
        nb.add(trade_tab, text="  Trade Log  ")
        self._trade_table = DataTable(trade_tab, [("entry", "Entry", 900)], height=14)
        self._trade_table.pack(fill="both", expand=True, padx=6, pady=4)

        ttk.Separator(main, style="MT.TSeparator").pack(fill="x", padx=10, pady=(4, 2))
        self.back_button(main).pack(anchor="w", padx=10, pady=4)

    def refresh(self) -> None:
        if not hasattr(self, "_ev_table"):
            return
        g    = self.game
        seen: set = set()
        ev_rows = []
        for area, market in g.markets.items():
            for ev in market.active_events:
                key = (area.value, ev)
                if key not in seen:
                    seen.add(key)
                    ev_rows.append({
                        "area":   area.value,
                        "event":  ev,
                        "effect": self._HINTS.get(ev, "Market effects in play."),
                        "tag":    "yellow",
                    })
        self._ev_table.load(ev_rows, tag_key="tag")

        feed_rows = []
        for entry in list(g.news_feed):
            abs_day, area_name, ev_label, headline = entry
            yr  = (abs_day - 1) // 360 + 1
            day = (abs_day - 1) % 360 + 1
            feed_rows.append({
                "date":     f"Y{yr}D{day}",
                "area":     area_name,
                "event":    ev_label,
                "headline": headline,
            })
        self._feed_table.load(feed_rows)
        self._log_table.load(
            [{"entry": str(e)} for e in list(g.event_log)[:40]]
        )
        self._trade_table.load(
            [{"entry": str(e)} for e in list(g.trade_log)[:40]]
        )


class ProgressScreen(Screen):
    """Progress screen — mirrors progress_menu() / statistics / achievements from the CLI."""

    _STAT_COLS = [("stat", "Statistic", 260), ("value", "Value", 220)]
    _ACH_COLS  = [
        ("status", "Status",           60),
        ("tier",   "Tier",             70),
        ("icon",   "Icon",             40),
        ("name",   "Name",            200),
        ("desc",   "Description / Hint", 440),
    ]

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        self.section_label(main, "PROGRESS").pack(anchor="w", padx=10, pady=(0, 4))

        nb = ttk.Notebook(main, style="MT.TNotebook")
        nb.pack(fill="both", expand=True, padx=10, pady=4)

        stats_tab = ttk.Frame(nb, style="MT.TFrame")
        nb.add(stats_tab, text="  Statistics  ")
        self._stats_table = DataTable(stats_tab, self._STAT_COLS, height=15)
        self._stats_table.pack(fill="both", expand=True, padx=6, pady=4)

        ach_tab = ttk.Frame(nb, style="MT.TFrame")
        nb.add(ach_tab, text="  Achievements  ")
        self._ach_lbl = tk.Label(ach_tab, text="", font=FONT_MONO,
                                  bg=T["bg"], fg=T["cyan"], anchor="w", padx=6, pady=4)
        self._ach_lbl.pack(fill="x")
        self._ach_table = DataTable(ach_tab, self._ACH_COLS, height=14)
        self._ach_table.pack(fill="both", expand=True, padx=6, pady=4)

        ttk.Separator(main, style="MT.TSeparator").pack(fill="x", padx=10, pady=(4, 2))
        self.back_button(main).pack(anchor="w", padx=10, pady=4)

    def refresh(self) -> None:
        if not hasattr(self, "_stats_table"):
            return
        g  = self.game
        ad = g._absolute_day()
        yr = (ad - 1) // 360 + 1
        pv = g._portfolio_value() if hasattr(g, '_portfolio_value') else 0.0
        active_cl  = sum(1 for cl in g.citizen_loans if not cl.defaulted and cl.weeks_remaining > 0)
        active_fc  = sum(1 for fc in g.fund_clients  if not fc.withdrawn)
        wk_income  = sum(cl.weekly_payment for cl in g.citizen_loans
                         if not cl.defaulted and cl.weeks_remaining > 0)
        stats_rows = [
            {"stat": "Player",                "value": g.player_name},
            {"stat": "Days Played",            "value": f"{ad}  (Year {yr})"},
            {"stat": "Current Area",           "value": g.current_area.value},
            {"stat": "", "value": ""},
            {"stat": "Gold in Wallet",         "value": f"{g.inventory.gold:,.2f}g"},
            {"stat": "Bank Balance",           "value": f"{g.bank_balance:,.2f}g"},
            {"stat": "Net Worth",              "value": f"{g._net_worth():,.2f}g"},
            {"stat": "Total Profit",           "value": f"{g.total_profit:,.0f}g"},
            {"stat": "", "value": ""},
            {"stat": "Reputation",             "value": str(g.reputation)},
            {"stat": "Heat",                   "value": str(g.heat)},
            {"stat": "Licenses Held",          "value": f"{len(g.licenses)} / {len(LicenseType)}"},
            {"stat": "", "value": ""},
            {"stat": "Lifetime Trades",        "value": str(g.lifetime_trades)},
            {"stat": "Contracts Completed",    "value": str(g.ach_stats.get("contracts_completed", 0))},
            {"stat": "Smuggling Busts",        "value": str(g.ach_stats.get("smuggle_busts", 0))},
            {"stat": "Journeys Made",          "value": str(g.ach_stats.get("journeys", 0))},
            {"stat": "Travel Days",            "value": str(g.ach_stats.get("travel_days", 0))},
            {"stat": "Max Single Sale",        "value": f"{g.ach_stats.get('max_single_sale', 0):,.0f}g"},
            {"stat": "", "value": ""},
            {"stat": "Businesses Owned",       "value": str(len(g.businesses))},
            {"stat": "Active Contracts",       "value": str(sum(1 for c in g.contracts if not c.fulfilled))},
            {"stat": "Citizen Loans Active",   "value": f"{active_cl}  (weekly income: {wk_income:.1f}g)"},
            {"stat": "Fund Clients Active",    "value": str(active_fc)},
            {"stat": "Stock Portfolio",        "value": f"{pv:,.0f}g" if pv > 0 else "No holdings"},
            {"stat": "", "value": ""},
            {"stat": "Skills  Trading",        "value": f"Lv {g.skills.trading}"},
            {"stat": "Skills  Haggling",       "value": f"Lv {g.skills.haggling}"},
            {"stat": "Skills  Logistics",      "value": f"Lv {g.skills.logistics}"},
            {"stat": "Skills  Industry",       "value": f"Lv {g.skills.industry}"},
            {"stat": "Skills  Espionage",      "value": f"Lv {g.skills.espionage}"},
            {"stat": "Skills  Banking",        "value": f"Lv {g.skills.banking}"},
        ]
        self._stats_table.load(stats_rows)

        unlocked = set(g.achievements)
        total    = len(ACHIEVEMENTS)
        count    = len(unlocked)
        self._ach_lbl.config(
            text=f"Unlocked: {count} / {total}  ({count * 100 // max(total, 1)}%)"
        )
        unlocked_rows: List[Dict] = []
        locked_rows:   List[Dict] = []
        for ach in ACHIEVEMENTS:
            is_un  = ach["id"] in unlocked
            hidden = ach.get("hidden", False)
            entry  = {
                "status": "✓" if is_un else "○",
                "tier":   ach.get("tier", "").title(),
                "icon":   ach.get("icon", "★"),
                "name":   ach.get("name", "") if (is_un or not hidden) else "???",
                "desc":   (ach.get("desc", "") if is_un
                           else (ach.get("hint", "") if not hidden else "Hidden achievement")),
                "tag":    "green" if is_un else "dim",
            }
            (unlocked_rows if is_un else locked_rows).append(entry)
        self._ach_table.load(unlocked_rows + locked_rows, tag_key="tag")


class InfluenceScreen(Screen):
    """Influence & Reputation — campaign/slander market prices, donate for rep."""

    _REP_LABELS = [
        (20,  "Outlaw",    T["red"]),
        (40,  "Suspect",   T["yellow"]),
        (60,  "Neutral",   T["white"]),
        (80,  "Trusted",   T["green"]),
        (101, "Legendary", T["cyan"]),
    ]

    # Columns for the market campaign table
    _MKT_COLS = [
        ("item",     "Item",      160),
        ("price",    "Price",      80),
        ("pressure", "Pressure",   80),
        ("trend",    "Trend",       80),
        ("rarity",   "Rarity",     90),
        ("camp_cost","Camp Cost",   80),
    ]

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        self.section_label(main, "INFLUENCE & REPUTATION").pack(
            anchor="w", padx=10, pady=(0, 4))

        nb = ttk.Notebook(main, style="MT.TNotebook")
        nb.pack(fill="both", expand=True, padx=10, pady=4)

        # ── Overview tab ─────────────────────────────────────────────────────
        ov_tab = ttk.Frame(nb, style="MT.TFrame")
        nb.add(ov_tab, text="  Overview  ")

        self._rep_txt = tk.Text(
            ov_tab, bg=T["bg"], fg=T["fg"], font=FONT_MONO,
            relief="flat", height=7, state="disabled", padx=12, pady=8,
        )
        self._rep_txt.pack(fill="x", padx=6, pady=4)

        # ── Social Actions tab ───────────────────────────────────────────────
        soc_tab = ttk.Frame(nb, style="MT.TFrame")
        nb.add(soc_tab, text="  Social Actions  ")

        info_lbl = tk.Label(
            soc_tab,
            text=(
                "Donate to charity to gain reputation.\n"
                "15g = +1 rep  (diminishing returns above 80 rep).\n"
                "Donation presets: 20g / 50g / 120g / 300g  or enter a custom amount."
            ),
            font=FONT_MONO_S, bg=T["bg"], fg=T["grey"], anchor="w",
            justify="left", padx=8, pady=6,
        )
        info_lbl.pack(fill="x", padx=6, pady=(6, 2))

        btn_row = ttk.Frame(soc_tab, style="MT.TFrame")
        btn_row.pack(fill="x", padx=6, pady=4)
        for amt in (20, 50, 120, 300):
            ttk.Button(
                btn_row, text=f"Donate {amt}g",
                style="MT.TButton",
                command=lambda a=amt: self._do_donate(a),
            ).pack(side="left", padx=(0, 6))
        ttk.Button(
            btn_row, text="Donate Custom…",
            style="OK.TButton",
            command=lambda: self._do_donate(None),
        ).pack(side="left", padx=(0, 6))

        # ── Market Campaign tab ──────────────────────────────────────────────
        mkt_tab = ttk.Frame(nb, style="MT.TFrame")
        nb.add(mkt_tab, text="  Market Campaign  ")

        mkt_info = tk.Label(
            mkt_tab,
            text=(
                "Campaign ↑  —  Spend gold to drive up demand for an item   (+25% pressure).\n"
                "Slander ↓   —  Spread negative rumours to suppress demand  (−20% pressure, costs −5 to −10 rep)."
            ),
            font=FONT_MONO_S, bg=T["bg"], fg=T["grey"], anchor="w",
            justify="left", padx=8, pady=6,
        )
        mkt_info.pack(fill="x", padx=6, pady=(6, 2))

        self._mkt_table = DataTable(mkt_tab, self._MKT_COLS, height=8)
        self._mkt_table.pack(fill="both", expand=True, padx=6, pady=4)

        mkt_act = ttk.Frame(mkt_tab, style="MT.TFrame")
        mkt_act.pack(fill="x", padx=6, pady=4)
        ttk.Button(mkt_act, text="Campaign ↑  (raise price)",
                   style="OK.TButton",
                   command=self._do_market_campaign).pack(side="left", padx=(0, 8))
        ttk.Button(mkt_act, text="Slander ↓  (lower price)",
                   style="MT.TButton",
                   command=self._do_slander).pack(side="left", padx=(0, 8))

        ttk.Separator(main, style="MT.TSeparator").pack(fill="x", padx=10, pady=(4, 2))
        self.back_button(main).pack(anchor="w", padx=10, pady=4)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _rep_lbl(self, rep: int) -> Tuple[str, str]:
        for threshold, label, colour in self._REP_LABELS:
            if rep < threshold:
                return label, colour
        return "Legendary", T["cyan"]

    def _campaign_cost(self, item) -> int:
        return {"common": 60, "uncommon": 100, "rare": 150, "legendary": 200}.get(
            getattr(item, "rarity", "common"), 80
        )

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        if not hasattr(self, "_rep_txt"):
            return
        g              = self.game
        rep_lbl, _     = self._rep_lbl(g.reputation)
        heat_col       = T["red"] if g.heat > 60 else (T["yellow"] if g.heat > 30 else T["green"])
        donate_gain_20  = max(1, int(20  / 15) - max(0, (g.reputation - 80) // 10))
        donate_gain_50  = max(1, int(50  / 15) - max(0, (g.reputation - 80) // 10))
        donate_gain_120 = max(1, int(120 / 15) - max(0, (g.reputation - 80) // 10))
        info = (
            f"  Reputation:  {g.reputation:>4}   ({rep_lbl})\n"
            f"  Heat:        {g.heat:>4} / 100\n"
            f"  Licenses:    {len(g.licenses)} / {len(LicenseType)}\n\n"
            f"  Donate 20g → +{donate_gain_20} rep\n"
            f"  Donate 50g → +{donate_gain_50} rep\n"
            f"  Donate 120g → +{donate_gain_120} rep\n"
            f"  (Diminishing returns above 80 rep)"
        )
        self._rep_txt.config(state="normal")
        self._rep_txt.delete("1.0", "end")
        self._rep_txt.insert("1.0", info)
        self._rep_txt.config(state="disabled")

        # Market campaign table
        if hasattr(self, "_mkt_table"):
            market = g.markets[g.current_area]
            rows   = []
            for k in market.item_keys:
                item = ALL_ITEMS.get(k)
                if item is None:
                    continue
                price    = market.get_price(k, g.season, noise=False)
                pressure = market.pressure.get(k, 1.0)
                natural  = market.natural_pressure.get(k, 1.0)
                hist     = list(market.history.get(k, []))
                if len(hist) >= 2:
                    delta  = (hist[-1].price - hist[-2].price) / max(hist[-2].price, 0.01) * 100
                    trend  = f"{'▲' if delta >= 0 else '▼'}{abs(delta):.1f}%"
                    t_tag  = "green" if delta > 0 else ("red" if delta < 0 else "dim")
                else:
                    trend, t_tag = "─", "dim"
                p_ratio = pressure / max(natural, 0.01)
                p_tag   = "red" if p_ratio > 1.2 else ("green" if p_ratio < 0.85 else "")
                rows.append({
                    "item":      item.name,
                    "price":     f"{price:.2f}g",
                    "pressure":  f"{pressure:.3f}",
                    "trend":     trend,
                    "rarity":    getattr(item, "rarity", "common").title(),
                    "camp_cost": f"{self._campaign_cost(item)}g",
                    "tag":       p_tag or t_tag,
                })
            self._mkt_table.load(rows, tag_key="tag")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _do_donate(self, preset_amt) -> None:
        g = self.game
        if preset_amt is None:
            raw = InputDialog(
                self,
                f"Donate to charity.\nGold: {g.inventory.gold:.0f}g\n"
                "Amount (15g = +1 rep, diminishing returns above 80 rep):",
                "Donate Custom",
            ).wait()
            if raw is None:
                return
            try:
                amt = float(raw)
            except ValueError:
                self.msg.err("Invalid amount.")
                return
        else:
            amt = float(preset_amt)
        if amt < 15:
            self.msg.err("Minimum donation is 15g.")
            return
        if amt > g.inventory.gold:
            self.msg.err(f"Not enough gold.  Have {g.inventory.gold:.0f}g.")
            return
        rep_gain = max(1, int(amt / 15) - max(0, (g.reputation - 80) // 10))
        rep_gain = min(rep_gain, 100 - g.reputation)
        if rep_gain <= 0:
            self.msg.warn("Your reputation is already at maximum.")
            return
        g.inventory.gold -= amt
        g.reputation = min(100, g.reputation + rep_gain)
        g._check_achievements()
        self.msg.ok(f"Donated {amt:.0f}g.  Rep +{rep_gain} → {g.reputation}.")
        self.app.refresh()
        self.app._flush_achievements()

    def _do_market_campaign(self) -> None:
        g   = self.game
        row = self._mkt_table.selected()
        if not row:
            self.msg.warn("Select an item from the Market Campaign table first.")
            return
        item_name = row.get("item", "")
        k = next((ik for ik, it in ALL_ITEMS.items() if it.name == item_name), None)
        if not k:
            self.msg.err("Could not identify item.")
            return
        item   = ALL_ITEMS[k]
        cost   = self._campaign_cost(item)
        market = g.markets[g.current_area]
        if k not in market.item_keys:
            self.msg.err("That item is not traded in this area.")
            return
        if g.inventory.gold < cost:
            self.msg.err(f"Need {cost}g for a campaign on {item.name}.")
            return
        cooldown_key = f"{g.current_area.name}:{k}:campaign"
        expires = g.influence_cooldowns.get(cooldown_key, 0)
        if expires > g._absolute_day():
            days_left = expires - g._absolute_day()
            self.msg.err(
                f"You already ran a campaign for {item.name} here.  "
                f"Cooldown: {days_left} day{'s' if days_left != 1 else ''} remaining."
            )
            return
        if not ConfirmDialog(
            self,
            f"Run a demand campaign for {item.name}?\n"
            f"Cost: {cost}g  →  Pressure +25%  (mean-reverts over ~15-25 days).",
            "Market Campaign",
        ).wait():
            return
        g.inventory.gold -= cost
        old_p = market.pressure.get(k, 1.0)
        try:
            max_p = market.MAX_PRESSURE
        except AttributeError:
            max_p = 2.0
        market.pressure[k] = min(max_p, old_p * 1.25)
        g.heat = min(100, g.heat + 5)
        g.influence_cooldowns[cooldown_key] = g._absolute_day() + 30
        g._check_achievements()
        self.msg.ok(
            f"Campaign launched for {item.name}!  "
            f"Pressure {old_p:.3f} → {market.pressure[k]:.3f}   Heat +5."
        )
        self.app.refresh()

    def _do_slander(self) -> None:
        g   = self.game
        row = self._mkt_table.selected()
        if not row:
            self.msg.warn("Select an item from the Market Campaign table first.")
            return
        item_name = row.get("item", "")
        k = next((ik for ik, it in ALL_ITEMS.items() if it.name == item_name), None)
        if not k:
            self.msg.err("Could not identify item.")
            return
        item   = ALL_ITEMS[k]
        market = g.markets[g.current_area]
        if k not in market.item_keys:
            self.msg.err("That item is not traded in this area.")
            return
        import math
        rep_cost = max(5, min(10, int(math.ceil((100 - g.reputation) * 0.1)) + 5))
        if g.reputation - rep_cost < 0:
            self.msg.err(
                f"Reputation too low.  Slander costs {rep_cost} rep  "
                f"(you have {g.reputation})."
            )
            return
        slander_key = f"{g.current_area.name}:{k}:slander"
        slander_expires = g.influence_cooldowns.get(slander_key, 0)
        if slander_expires > g._absolute_day():
            days_left = slander_expires - g._absolute_day()
            self.msg.err(
                f"You already slandered {item.name} here.  "
                f"Cooldown: {days_left} day{'s' if days_left != 1 else ''} remaining."
            )
            return
        if not ConfirmDialog(
            self,
            f"Spread slander about {item.name} in {g.current_area.value}?\n"
            f"Pressure −20%  (mean-reverts over ~10-20 days).\n"
            f"Cost: −{rep_cost} reputation.",
            "Slander",
        ).wait():
            return
        old_p = market.pressure.get(k, 1.0)
        try:
            min_p = market.MIN_PRESSURE
        except AttributeError:
            min_p = 0.3
        market.pressure[k] = max(min_p, old_p * 0.80)
        g.reputation = max(0, g.reputation - rep_cost)
        g.influence_cooldowns[slander_key] = g._absolute_day() + 20
        g._check_achievements()
        self.msg.ok(
            f"Slander spread on {item.name}!  "
            f"Pressure {old_p:.3f} → {market.pressure[k]:.3f}   Rep −{rep_cost}."
        )
        self.app.refresh()


class LicensesScreen(Screen):
    """Licenses & Permits — purchase and view all licenses."""

    _LIC_COLS = [
        ("status",  "Have",       50),
        ("name",    "License",   200),
        ("cost",    "Cost",       70),
        ("rep_req", "Rep Req",    70),
        ("tier",    "Tier",       80),
        ("desc",    "Description", 380),
    ]

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        self.section_label(main, "LICENSES & PERMITS").pack(
            anchor="w", padx=10, pady=(0, 4))

        info = tk.Label(
            main,
            text="Purchase licenses to unlock new gameplay options.  Higher reputation unlocks more.",
            font=FONT_MONO_S, bg=T["bg"], fg=T["grey"], anchor="w", padx=10,
        )
        info.pack(fill="x", padx=10, pady=(0, 4))

        self._lic_table = DataTable(main, self._LIC_COLS, height=10)
        self._lic_table.pack(fill="both", expand=True, padx=10, pady=4)

        act = ttk.Frame(main, style="MT.TFrame")
        act.pack(fill="x", padx=10, pady=4)
        ttk.Button(act, text="Purchase Selected License",
                   style="OK.TButton",
                   command=self._do_buy_license).pack(side="left", padx=(0, 8))
        self.back_button(act).pack(side="left")

    def refresh(self) -> None:
        if not hasattr(self, "_lic_table"):
            return
        g        = self.game
        lic_rows = []
        for lt in LicenseType:
            info_d  = LICENSE_INFO.get(lt, {})
            have    = lt in g.licenses
            cost    = info_d.get("cost", 0)
            rep_req = info_d.get("rep",  0)
            can_buy = not have and g.reputation >= rep_req and g.inventory.gold >= cost
            lic_rows.append({
                "status":  "✓" if have else "",
                "name":    lt.value,
                "cost":    f"{cost}g" if cost > 0 else "Free",
                "rep_req": str(rep_req),
                "tier":    info_d.get("tier", "").title(),
                "desc":    info_d.get("desc", ""),
                "tag":     "green" if have else ("cyan" if can_buy else "dim"),
            })
        self._lic_table.load(lic_rows, tag_key="tag")

    def _do_buy_license(self) -> None:
        row = self._lic_table.selected()
        if not row:
            self.msg.warn("Select a license to purchase.")
            return
        g        = self.game
        name_val = row.get("name", "")
        lt       = next((l for l in LicenseType if l.value == name_val), None)
        if lt is None:
            self.msg.err("Could not identify license.")
            return
        if lt in g.licenses:
            self.msg.info("You already hold this license.")
            return
        info_d  = LICENSE_INFO.get(lt, {})
        cost    = info_d.get("cost", 0)
        rep_req = info_d.get("rep",  0)
        if g.reputation < rep_req:
            self.msg.err(f"Reputation too low ({g.reputation} / {rep_req} required).")
            return
        if g.inventory.gold < cost:
            self.msg.err(f"Need {cost}g.  Have {g.inventory.gold:.0f}g.")
            return
        if not ConfirmDialog(self, f"Purchase {lt.value} for {cost}g?",
                             "Buy License").wait():
            return
        g.inventory.gold -= cost
        g.licenses.add(lt)
        self.msg.ok(f"Licensed: {lt.value}.")
        self.app.refresh()


        g.licenses.add(lt)
        self.msg.ok(f"Licensed: {lt.value}.")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# CITIZEN LENDING SCREEN
# ══════════════════════════════════════════════════════════════════════════════

class CitizenLendingScreen(Screen):
    """Citizen Lending — issue personal loans and collect weekly interest."""

    _LOAN_COLS = [
        ("borrower", "Borrower",     160),
        ("principal","Principal",     80),
        ("rate",     "Rate/wk",       70),
        ("weeks",    "Wks Left",      68),
        ("payment",  "Wk Payment",    90),
        ("received", "Received",      80),
        ("status",   "Status",        80),
    ]
    _APPL_COLS = [
        ("name",     "Applicant",    155),
        ("amount",   "Amount",        75),
        ("purpose",  "Purpose",      140),
        ("weeks",    "Weeks",         55),
        ("max_rate", "Max Rate",      70),
        ("risk",     "Default Risk",  90),
        ("cw",       "Creditworth.",  95),
    ]

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        # Header + summary
        hdr = ttk.Frame(main, style="MT.TFrame")
        hdr.pack(fill="x", padx=10, pady=(0, 4))
        self.section_label(hdr, "CITIZEN LENDING").pack(side="left")
        self._summary_lbl = tk.Label(hdr, text="", font=FONT_MONO_S,
                                     bg=T["bg"], fg=T["cyan"])
        self._summary_lbl.pack(side="right")

        self._nb = ttk.Notebook(main, style="MT.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=10, pady=4)

        # ── Tab 1: Active Loans ───────────────────────────────────────────
        tab1 = ttk.Frame(self._nb, style="MT.TFrame")
        self._nb.add(tab1, text="  Active Loans  ")

        self._loan_table = DataTable(tab1, self._LOAN_COLS, height=10)
        self._loan_table.pack(fill="both", expand=True, pady=4)

        act1 = ttk.Frame(tab1, style="MT.TFrame")
        act1.pack(fill="x", pady=(2, 0))
        ttk.Button(act1, text="Recall Loan Early  (−20%)", style="Danger.TButton",
                   command=self._recall_loan).pack(side="left", padx=(0, 8))

        # ── Tab 2: New Applicants ─────────────────────────────────────────
        tab2 = ttk.Frame(self._nb, style="MT.TFrame")
        self._nb.add(tab2, text="  New Applicants  ")

        appl_hdr = ttk.Frame(tab2, style="MT.TFrame")
        appl_hdr.pack(fill="x", pady=(4, 2))
        ttk.Button(appl_hdr, text="↻  New Pool", style="MT.TButton",
                   command=self._refresh_pool).pack(side="left")
        tk.Label(appl_hdr,
                 text="  Offer an interest rate ≤ applicant's max rate to proceed.",
                 font=FONT_MONO_S, bg=T["bg"], fg=T["fg_dim"]).pack(side="left")

        self._appl_table = DataTable(tab2, self._APPL_COLS, height=8)
        self._appl_table.pack(fill="both", expand=True, pady=4)

        act2 = ttk.Frame(tab2, style="MT.TFrame")
        act2.pack(fill="x", pady=(2, 0))
        ttk.Button(act2, text="Issue Loan to Selected", style="OK.TButton",
                   command=self._issue_loan).pack(side="left", padx=(0, 8))

        ttk.Separator(main, style="MT.TSeparator").pack(fill="x", padx=10, pady=(6, 2))
        self.back_button(main).pack(anchor="w", padx=10, pady=4)

        self._applicants: List[Dict] = []

    def refresh(self) -> None:
        if not hasattr(self, "_loan_table"):
            return
        g = self.game
        if LicenseType.LENDER not in g.licenses:
            self._summary_lbl.config(text="🔒  Lending Charter required", fg=T["red"])
            self._loan_table.load([])
            self._appl_table.load([])
            return

        active_cl = [cl for cl in g.citizen_loans
                     if not cl.defaulted and cl.weeks_remaining > 0]
        outstanding = sum(cl.principal for cl in active_cl)
        wk_income   = sum(cl.weekly_payment for cl in active_cl)
        self._summary_lbl.config(
            text=f"Active: {len(active_cl)}  ·  Capital out: {outstanding:.0f}g"
                 f"  ·  Weekly income: {wk_income:.1f}g",
            fg=T["cyan"])

        rows: List[Dict] = []
        for cl in g.citizen_loans:
            if cl.defaulted:
                status, tag = "Defaulted", "red"
            elif cl.weeks_remaining <= 0:
                status, tag = "Repaid", "dim"
            elif cl.weeks_remaining <= 2:
                status, tag = f"{cl.weeks_remaining}wk left", "yellow"
            else:
                status, tag = f"{cl.weeks_remaining}wk left", "green"
            rows.append({
                "borrower":  cl.borrower_name,
                "principal": f"{cl.principal:.0f}g",
                "rate":      f"{cl.interest_rate*100:.1f}%",
                "weeks":     str(cl.weeks_remaining),
                "payment":   f"{cl.weekly_payment:.1f}g",
                "received":  f"{cl.total_received:.0f}g",
                "status":    status,
                "tag":       tag,
            })
        self._loan_table.load(rows, tag_key="tag")

        if not self._applicants:
            self._applicants = g._gen_loan_applicants(6)
        self._load_appl_table()

    def _load_appl_table(self) -> None:
        rows: List[Dict] = []
        for ap in self._applicants:
            cw = ap["creditworthiness"]
            tag = "red" if cw < 0.85 else ("yellow" if cw < 1.15 else "green")
            rows.append({
                "name":     ap["name"],
                "amount":   f"{ap['amount']:.0f}g",
                "purpose":  ap["purpose"],
                "weeks":    str(ap["weeks"]),
                "max_rate": f"{ap['max_rate']*100:.1f}%",
                "risk":     f"{ap['default_risk']*100:.1f}%",
                "cw":       f"{cw:.2f}",
                "tag":      tag,
            })
        self._appl_table.load(rows, tag_key="tag")

    def _refresh_pool(self) -> None:
        self._applicants = self.game._gen_loan_applicants(6)
        self._load_appl_table()

    def _issue_loan(self) -> None:
        g = self.game
        if LicenseType.LENDER not in g.licenses:
            self.msg.err("Lending Charter required.")
            return
        row = self._appl_table.selected()
        if not row:
            self.msg.warn("Select an applicant first.")
            return
        name = row.get("name", "")
        ap   = next((a for a in self._applicants if a["name"] == name), None)
        if ap is None:
            self.msg.err("Could not find applicant data.")
            return
        if g.inventory.gold < ap["amount"]:
            self.msg.err(f"Need {ap['amount']:.0f}g.  Have {g.inventory.gold:.0f}g.")
            return

        rate_str = InputDialog(
            self,
            f"Loan to {ap['name']}:  {ap['amount']:.0f}g  /  {ap['weeks']} weeks\n"
            f"Purpose: {ap['purpose']}\n"
            f"Max rate they'll accept: {ap['max_rate']*100:.1f}%/wk\n\n"
            f"Enter your interest rate (e.g. 0.04 for 4%/wk):",
            title="Issue Loan",
        ).wait()
        if not rate_str:
            return
        try:
            rate = float(rate_str)
        except ValueError:
            self.msg.err("Invalid rate — enter a decimal (e.g. 0.05).")
            return
        if rate > ap["max_rate"]:
            self.msg.err(f"Rate {rate*100:.1f}% exceeds max {ap['max_rate']*100:.1f}%.  Applicant refused.")
            return
        if rate <= 0:
            self.msg.err("Rate must be positive.")
            return

        weeks     = ap["weeks"]
        principal = ap["amount"]
        wk_pmt    = round(principal * (rate + 1.0 / weeks), 2)
        total_ret = round(wk_pmt * weeks, 2)
        profit    = round(total_ret - principal, 2)

        if not ConfirmDialog(
            self,
            f"Lend {principal:.0f}g to {ap['name']}\n"
            f"@ {rate*100:.1f}%/wk  ·  {weeks} weeks\n"
            f"Weekly payment: {wk_pmt:.2f}g  ·  Total return: {total_ret:.2f}g\n"
            f"Expected profit: +{profit:.2f}g",
            "Confirm Loan",
        ).wait():
            return

        g.inventory.gold -= principal
        cl = CitizenLoan(
            id=g.next_citizen_loan_id,
            borrower_name=ap["name"],
            principal=principal,
            interest_rate=rate,
            weeks_remaining=weeks,
            weekly_payment=wk_pmt,
            creditworthiness=ap["creditworthiness"],
        )
        g.citizen_loans.append(cl)
        g.next_citizen_loan_id += 1
        # Remove from pool so same applicant isn't shown twice
        self._applicants = [a for a in self._applicants if a["name"] != name]
        g._log_event(f"Citizen loan: {principal:.0f}g to {ap['name']}")
        self.msg.ok(f"Loaned {principal:.0f}g to {ap['name']} @ {rate*100:.1f}%/wk.  "
                    f"Expected profit: +{profit:.2f}g.")
        self.app.refresh()

    def _recall_loan(self) -> None:
        g   = self.game
        row = self._loan_table.selected()
        if not row:
            self.msg.warn("Select an active loan to recall.")
            return
        name = row.get("borrower", "")
        cl   = next(
            (c for c in g.citizen_loans
             if c.borrower_name == name and not c.defaulted and c.weeks_remaining > 0),
            None,
        )
        if cl is None:
            self.msg.warn("Loan not found or already closed.")
            return
        remainder = round(cl.weeks_remaining * cl.weekly_payment, 2)
        recall    = round(remainder * 0.80, 2)
        if not ConfirmDialog(
            self,
            f"Recall loan to {cl.borrower_name}?\n"
            f"Remaining value: {remainder:.2f}g\n"
            f"You receive: {recall:.2f}g  (−20% early-recall fee)",
            "Confirm Recall",
        ).wait():
            return
        g.inventory.gold  += recall
        cl.defaulted       = True
        cl.weeks_remaining = 0
        g._log_event(f"Recalled citizen loan from {cl.borrower_name}: +{recall:.0f}g")
        self.msg.ok(f"Loan recalled.  +{recall:.2f}g deposited.")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# STOCK MARKET SCREEN
# ══════════════════════════════════════════════════════════════════════════════

class StockMarketScreen(Screen):
    """Stock Exchange — buy and sell shares in 10 in-game companies."""

    _COLS = [
        ("sym",      "Sym",       52),
        ("name",     "Company",  210),
        ("sector",   "Sector",    95),
        ("price",    "Price",     72),
        ("chg",      "Today%",    68),
        ("week7",    "7d%",       65),
        ("holdings", "Holdings", 180),
    ]

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        hdr = ttk.Frame(main, style="MT.TFrame")
        hdr.pack(fill="x", padx=10, pady=(0, 4))
        self.section_label(hdr, "STOCK EXCHANGE").pack(side="left")
        self._port_lbl = tk.Label(hdr, text="", font=FONT_MONO_S,
                                  bg=T["bg"], fg=T["cyan"])
        self._port_lbl.pack(side="right")

        self._table = DataTable(main, self._COLS, height=12)
        self._table.pack(fill="both", expand=True, padx=10, pady=4)

        note = tk.Label(
            main,
            text="Green = price rose today · Red = price fell · Gold = you hold shares",
            font=FONT_MONO_S, bg=T["bg"], fg=T["fg_dim"], anchor="w", padx=10,
        )
        note.pack(fill="x", padx=10)

        act = ttk.Frame(main, style="MT.TFrame")
        act.pack(fill="x", padx=10, pady=(6, 2))
        ttk.Button(act, text="Buy Shares",  style="OK.TButton",
                   command=self._buy).pack(side="left", padx=(0, 8))
        ttk.Button(act, text="Sell Shares", style="Danger.TButton",
                   command=self._sell).pack(side="left", padx=(0, 8))
        ttk.Button(act, text="↻  Refresh",  style="MT.TButton",
                   command=self.refresh).pack(side="left")

        ttk.Separator(main, style="MT.TSeparator").pack(fill="x", padx=10, pady=(6, 2))
        self.back_button(main).pack(anchor="w", padx=10, pady=4)

    def refresh(self) -> None:
        if not hasattr(self, "_table"):
            return
        g = self.game
        if LicenseType.FUND_MGR not in g.licenses:
            self._port_lbl.config(text="🔒  Fund Manager License required", fg=T["red"])
            self._table.load([])
            return

        pv = g._portfolio_value()
        self._port_lbl.config(
            text=f"Portfolio: {pv:,.0f}g  ·  Wallet: {g.inventory.gold:,.0f}g",
            fg=T["cyan"])

        rows: List[Dict] = []
        for sym, sd in g.stock_market.stocks.items():
            price = sd["price"]
            hist  = list(sd["history"])
            prev  = hist[-2] if len(hist) >= 2 else price
            chg   = (price - prev) / max(prev, 0.01) * 100
            w7    = hist[-7:] if len(hist) >= 7 else hist
            t7    = ((w7[-1] - w7[0]) / max(w7[0], 0.01) * 100) if len(w7) > 1 else 0.0
            hold  = g.stock_holdings.get(sym)
            if hold:
                val  = round(hold.shares * price, 1)
                gain = round(val - hold.shares * hold.avg_cost, 1)
                hold_str = (f"{hold.shares}sh  val:{val:.0f}g  "
                            f"{'+'if gain>=0 else ''}{gain:.0f}g")
                h_tag = "green" if gain >= 0 else "red"
            else:
                hold_str, h_tag = "—", ""
            # Row tag: gold if holding, else by daily change
            if hold:
                tag = "yellow"
            else:
                tag = "green" if chg > 0 else ("red" if chg < 0 else "dim")
            rows.append({
                "sym":      sym,
                "name":     sd["name"],
                "sector":   sd["sector"],
                "price":    f"{price:.2f}g",
                "chg":      f"{'+'if chg>=0 else ''}{chg:.2f}%",
                "week7":    f"{'+'if t7>=0 else ''}{t7:.1f}%",
                "holdings": hold_str,
                "tag":      tag,
            })
        self._table.load(rows, tag_key="tag")

    def _buy(self) -> None:
        g   = self.game
        if LicenseType.FUND_MGR not in g.licenses:
            self.msg.err("Fund Manager License required.")
            return
        row = self._table.selected()
        if not row:
            self.msg.warn("Select a company to buy shares in.")
            return
        sym = row.get("sym", "").strip()
        if sym not in g.stock_market.stocks:
            self.msg.err("Unknown symbol.")
            return
        sd    = g.stock_market.stocks[sym]
        price = sd["price"]
        max_sh = int(g.inventory.gold / price) if price > 0 else 0
        if max_sh <= 0:
            self.msg.err(f"Not enough gold.  Need at least {price:.2f}g.")
            return
        qty_str = InputDialog(
            self,
            f"Buy shares of {sd['name']}  ({sym})\n"
            f"Current price: {price:.2f}g/share\n"
            f"Max you can afford: {max_sh} shares\n\n"
            f"How many shares to buy?",
            title="Buy Shares",
        ).wait()
        if not qty_str:
            return
        try:
            qty = int(qty_str)
        except ValueError:
            self.msg.err("Enter a whole number of shares.")
            return
        if qty <= 0:
            return
        cost = round(qty * price, 2)
        if cost > g.inventory.gold:
            self.msg.err(f"Need {cost:.2f}g.  Have {g.inventory.gold:.2f}g.")
            return
        if not ConfirmDialog(
            self, f"Buy {qty}× {sym} @ {price:.2f}g = {cost:.2f}g total?",
            "Confirm Purchase"
        ).wait():
            return
        g.inventory.gold -= cost
        if sym in g.stock_holdings:
            hold     = g.stock_holdings[sym]
            new_avg  = (hold.shares * hold.avg_cost + cost) / (hold.shares + qty)
            hold.shares   += qty
            hold.avg_cost  = round(new_avg, 2)
        else:
            g.stock_holdings[sym] = StockHolding(sym, qty, round(price, 2))
        g._log_event(f"Bought {qty}× {sym} @ {price:.2f}g")
        self.msg.ok(f"Bought {qty}× {sym} @ {price:.2f}g  (−{cost:.2f}g)")
        self.app.refresh()

    def _sell(self) -> None:
        g   = self.game
        if LicenseType.FUND_MGR not in g.licenses:
            self.msg.err("Fund Manager License required.")
            return
        row = self._table.selected()
        if not row:
            self.msg.warn("Select a company to sell shares in.")
            return
        sym  = row.get("sym", "").strip()
        hold = g.stock_holdings.get(sym)
        if not hold or hold.shares <= 0:
            self.msg.err(f"No shares held in {sym}.")
            return
        sd    = g.stock_market.stocks[sym]
        price = sd["price"]
        gain_ea = price - hold.avg_cost
        qty_str = InputDialog(
            self,
            f"Sell shares of {sd['name']}  ({sym})\n"
            f"You hold: {hold.shares} shares  (avg cost: {hold.avg_cost:.2f}g)\n"
            f"Current price: {price:.2f}g  ·  "
            f"Unrealised: {'+'if gain_ea>=0 else ''}{gain_ea:.2f}g/sh\n\n"
            f"How many shares to sell?",
            title="Sell Shares",
        ).wait()
        if not qty_str:
            return
        try:
            qty = int(qty_str)
        except ValueError:
            self.msg.err("Enter a whole number of shares.")
            return
        if qty <= 0 or qty > hold.shares:
            self.msg.err(f"Invalid quantity (have {hold.shares}).")
            return
        proceeds = round(qty * price, 2)
        profit   = round((price - hold.avg_cost) * qty, 2)
        if not ConfirmDialog(
            self,
            f"Sell {qty}× {sym} @ {price:.2f}g = {proceeds:.2f}g\n"
            f"P/L: {'+'if profit>=0 else ''}{profit:.2f}g",
            "Confirm Sale",
        ).wait():
            return
        g.inventory.gold += proceeds
        g.total_profit   += profit
        hold.shares -= qty
        if hold.shares <= 0:
            del g.stock_holdings[sym]
        g._log_event(f"Sold {qty}× {sym} @ {price:.2f}g  P/L:{profit:+.0f}g")
        if profit > 0:
            g._track_stat("stock_profit", profit)
        g._check_achievements()
        self.msg.ok(f"Sold {qty}× {sym} @ {price:.2f}g  +{proceeds:.2f}g  "
                    f"(P/L: {'+'if profit>=0 else ''}{profit:.2f}g)")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# FUND MANAGEMENT SCREEN
# ══════════════════════════════════════════════════════════════════════════════

class FundManagementScreen(Screen):
    """Fund Management — accept client capital and return with promised yield."""

    _CLIENT_COLS = [
        ("name",    "Client",      180),
        ("capital", "Capital",      82),
        ("rate",    "Promised%",    82),
        ("fee",     "Fee/mo",       70),
        ("days",    "Days Left",    80),
        ("fees_pd", "Fees Paid",    80),
        ("owed",    "Owed at Mat.", 90),
    ]
    _POOL_COLS = [
        ("name",   "Prospective Client", 195),
        ("cap",    "Capital",             82),
        ("dur",    "Duration",            70),
        ("rate",   "Promised%",           82),
        ("fee",    "Mgmt Fee/mo",         90),
    ]

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        hdr = ttk.Frame(main, style="MT.TFrame")
        hdr.pack(fill="x", padx=10, pady=(0, 4))
        self.section_label(hdr, "FUND MANAGEMENT").pack(side="left")
        self._aum_lbl = tk.Label(hdr, text="", font=FONT_MONO_S,
                                 bg=T["bg"], fg=T["cyan"])
        self._aum_lbl.pack(side="right")

        self._nb = ttk.Notebook(main, style="MT.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=10, pady=4)

        # ── Tab 1: Active Clients ─────────────────────────────────────────
        tab1 = ttk.Frame(self._nb, style="MT.TFrame")
        self._nb.add(tab1, text="  Active Clients  ")

        self._client_table = DataTable(tab1, self._CLIENT_COLS, height=9)
        self._client_table.pack(fill="both", expand=True, pady=4)

        act1 = ttk.Frame(tab1, style="MT.TFrame")
        act1.pack(fill="x", pady=(2, 0))
        ttk.Button(act1, text="Return Funds Early  (−15%)", style="Danger.TButton",
                   command=self._early_return).pack(side="left", padx=(0, 8))

        # ── Tab 2: Accept Client ──────────────────────────────────────────
        tab2 = ttk.Frame(self._nb, style="MT.TFrame")
        self._nb.add(tab2, text="  Accept New Client  ")

        pool_hdr = ttk.Frame(tab2, style="MT.TFrame")
        pool_hdr.pack(fill="x", pady=(4, 2))
        ttk.Button(pool_hdr, text="↻  New Pool", style="MT.TButton",
                   command=self._refresh_pool).pack(side="left")
        tk.Label(pool_hdr,
                 text="  You receive capital NOW to invest freely.  Return it + promised % at maturity.",
                 font=FONT_MONO_S, bg=T["bg"], fg=T["fg_dim"]).pack(side="left")

        self._pool_table = DataTable(tab2, self._POOL_COLS, height=7)
        self._pool_table.pack(fill="both", expand=True, pady=4)

        act2 = ttk.Frame(tab2, style="MT.TFrame")
        act2.pack(fill="x", pady=(2, 0))
        ttk.Button(act2, text="Accept Selected Client", style="OK.TButton",
                   command=self._accept_client).pack(side="left", padx=(0, 8))

        ttk.Separator(main, style="MT.TSeparator").pack(fill="x", padx=10, pady=(6, 2))
        self.back_button(main).pack(anchor="w", padx=10, pady=4)

        self._pool: List[Dict] = []

    def refresh(self) -> None:
        if not hasattr(self, "_client_table"):
            return
        g = self.game
        locked = LicenseType.FUND_MGR not in g.licenses
        low_rep = g.reputation < 55
        if locked or low_rep:
            msg = ("🔒  Fund Manager License required." if locked
                   else f"🔒  Reputation {g.reputation}/100 — need 55+.")
            self._aum_lbl.config(text=msg, fg=T["red"])
            self._client_table.load([])
            self._pool_table.load([])
            return

        active_fc  = [fc for fc in g.fund_clients if not fc.withdrawn]
        aum        = sum(fc.capital for fc in active_fc)
        self._aum_lbl.config(
            text=f"Clients: {len(active_fc)}  ·  AUM: {aum:,.0f}g  ·  Wallet: {g.inventory.gold:,.0f}g",
            fg=T["cyan"])

        today = g._absolute_day()
        rows: List[Dict] = []
        for fc in active_fc:
            dl   = fc.maturity_day - today
            owed = round(fc.capital * (1 + fc.promised_rate), 2)
            tag  = "red" if dl <= 5 else ("yellow" if dl <= 15 else "green")
            rows.append({
                "name":    fc.name,
                "capital": f"{fc.capital:.0f}g",
                "rate":    f"{fc.promised_rate*100:.1f}%",
                "fee":     f"{fc.fee_rate*100:.1f}%",
                "days":    f"{dl}d",
                "fees_pd": f"{fc.fees_collected:.0f}g",
                "owed":    f"{owed:.0f}g",
                "tag":     tag,
            })
        self._client_table.load(rows, tag_key="tag")

        if not self._pool:
            self._pool = g._gen_fund_client_pool(4)
        self._load_pool_table()

    def _load_pool_table(self) -> None:
        rows: List[Dict] = []
        for p in self._pool:
            rows.append({
                "name": p["name"],
                "cap":  f"{p['capital']:.0f}g",
                "dur":  f"{p['duration']}d",
                "rate": f"{p['promised_rate']*100:.1f}%",
                "fee":  f"{p['fee_rate']*100:.1f}%",
                "tag":  "",
            })
        self._pool_table.load(rows, tag_key="tag")

    def _refresh_pool(self) -> None:
        self._pool = self.game._gen_fund_client_pool(4)
        self._load_pool_table()

    def _accept_client(self) -> None:
        g = self.game
        if LicenseType.FUND_MGR not in g.licenses:
            self.msg.err("Fund Manager License required.")
            return
        if g.reputation < 55:
            self.msg.err(f"Reputation {g.reputation}/100 — need 55+.")
            return
        row = self._pool_table.selected()
        if not row:
            self.msg.warn("Select a prospective client.")
            return
        name = row.get("name", "")
        p = next((x for x in self._pool if x["name"] == name), None)
        if p is None:
            self.msg.err("Client not found.")
            return

        today = g._absolute_day()
        owed  = round(p["capital"] * (1 + p["promised_rate"]), 2)
        if not ConfirmDialog(
            self,
            f"Accept {p['name']}\n"
            f"Capital: {p['capital']:.0f}g  ·  Duration: {p['duration']}d\n"
            f"You receive {p['capital']:.0f}g NOW to invest freely.\n"
            f"At maturity you must pay back: {owed:.0f}g\n"
            f"Management fee: {p['fee_rate']*100:.1f}%/mo (auto-collected)",
            "Accept Client",
        ).wait():
            return

        g.inventory.gold += p["capital"]
        fc = FundClient(
            id=g.next_fund_client_id,
            name=p["name"],
            capital=p["capital"],
            promised_rate=p["promised_rate"],
            start_day=today,
            duration_days=p["duration"],
            maturity_day=today + p["duration"],
            fee_rate=p["fee_rate"],
        )
        g.fund_clients.append(fc)
        g.next_fund_client_id += 1
        self._pool = [x for x in self._pool if x["name"] != name]
        g._log_event(f"Fund client {p['name']}: {p['capital']:.0f}g / {p['duration']}d")
        self.msg.ok(f"Accepted {p['name']}.  +{p['capital']:.0f}g received.  "
                    f"Repay {owed:.0f}g in {p['duration']}d.")
        self.app.refresh()

    def _early_return(self) -> None:
        g   = self.game
        row = self._client_table.selected()
        if not row:
            self.msg.warn("Select a client to return funds to.")
            return
        name = row.get("name", "")
        active_fc = [fc for fc in g.fund_clients if not fc.withdrawn]
        fc = next((c for c in active_fc if c.name == name), None)
        if fc is None:
            self.msg.warn("Client not found or already closed.")
            return
        owed = round(fc.capital * (1 + fc.promised_rate) * 0.85, 2)
        if g.inventory.gold < owed:
            self.msg.err(f"Need {owed:.0f}g.  Have {g.inventory.gold:.0f}g.")
            return
        if not ConfirmDialog(
            self,
            f"Return funds early to {fc.name}?\n"
            f"You pay: {owed:.0f}g  (principal + return × 85%)\n"
            f"Reputation −3 for early termination.",
            "Confirm Early Return",
        ).wait():
            return
        g.inventory.gold -= owed
        fc.withdrawn      = True
        g.reputation      = max(0, g.reputation - 3)
        g._log_event(f"Early fund return to {fc.name}: −{owed:.0f}g")
        self.msg.ok(f"Funds returned to {fc.name}.  −{owed:.0f}g.  Rep −3.")
        self.app.refresh()


        fc.withdrawn      = True
        g.reputation      = max(0, g.reputation - 3)
        g._log_event(f"Early fund return to {fc.name}: −{owed:.0f}g")
        self.msg.ok(f"Funds returned to {fc.name}.  −{owed:.0f}g.  Rep −3.")
        self.app.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# REAL ESTATE SCREEN
# ══════════════════════════════════════════════════════════════════════════════

class RealEstateScreen(Screen):
    """
    Real Estate — buy land, construct buildings, purchase/flip/lease properties.

    Tabs:
      My Portfolio  — view owned properties: lease, upgrade, repair, sell
      Browse Listings — procedurally generated market listings; haggle or buy
      Build on Land — buy a land plot and launch a construction project
    """

    # ── Table column definitions ──────────────────────────────────────────────
    _PORT_COLS = [
        ("name",     "Property",    200),
        ("area",     "Area",        108),
        ("type",     "Type",         90),
        ("cond",     "Condition",    80),
        ("value",    "Value",        78),
        ("lease",    "Lease/day",    74),
        ("status",   "Status",       90),
        ("days",     "Days Owned",   74),
    ]
    _LIST_COLS = [
        ("name",     "Property",    200),
        ("type",     "Type",         90),
        ("cond",     "Condition",    80),
        ("asking",   "Asking",       80),
        ("repair",   "Est. Repair",  80),
        ("lease",    "Lease/day",    72),
        ("haggle",   "Negotiable",   74),
        ("flavour",  "Notes",        200),
    ]
    _LAND_COLS = [
        ("area",     "Area",        120),
        ("size",     "Size",         80),
        ("cost",     "Cost",         68),
        ("status",   "Status",      120),
        ("progress", "Progress",    100),
    ]

    def build(self) -> None:
        outer = ttk.Frame(self, style="MT.TFrame")
        outer.pack(fill="both", expand=True)

        # ── Header row ────────────────────────────────────────────────────
        hdr = tk.Frame(outer, bg=T["bg"])
        hdr.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(hdr, text="🏠  Real Estate & Land Development",
                 font=FONT_FANTASY_TITLE, bg=T["bg"], fg=T["cyan"],
                 anchor="w").pack(side="left")
        self._lbl_stats = tk.Label(hdr, text="", font=FONT_FANTASY_S,
                                   bg=T["bg"], fg=T["fg_dim"], anchor="e")
        self._lbl_stats.pack(side="right", padx=8)

        # Require license notice
        self._lbl_locked = tk.Label(outer,
            text="⚠  Real Estate Charter required.  Purchase the license to unlock this feature.",
            font=FONT_FANTASY_BOLD, bg=T["bg"], fg=T["yellow"], anchor="center")

        # ── Notebook tabs ─────────────────────────────────────────────────
        self._nb = ttk.Notebook(outer, style="MT.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=10, pady=4)

        # Tab 1: My Portfolio
        tab1 = ttk.Frame(self._nb, style="MT.TFrame")
        self._nb.add(tab1, text="  🏠 My Portfolio  ")
        self._build_portfolio_tab(tab1)

        # Tab 2: Browse Listings
        tab2 = ttk.Frame(self._nb, style="MT.TFrame")
        self._nb.add(tab2, text="  📋 Browse Listings  ")
        self._build_listings_tab(tab2)

        # Tab 3: Build on Land
        tab3 = ttk.Frame(self._nb, style="MT.TFrame")
        self._nb.add(tab3, text="  🏗 Build on Land  ")
        self._build_land_tab(tab3)

        # Back row
        bot = ttk.Frame(outer, style="MT.TFrame")
        bot.pack(fill="x", padx=10, pady=(2, 6))
        self.back_button(bot).pack(side="left")

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 1: My Portfolio
    # ─────────────────────────────────────────────────────────────────────────

    def _build_portfolio_tab(self, parent: ttk.Frame) -> None:
        self._port_table = DataTable(parent, self._PORT_COLS, height=10)
        self._port_table.pack(fill="both", expand=True, padx=8, pady=(6, 4))

        # Summary labels
        sf = ttk.Frame(parent, style="MT.TFrame")
        sf.pack(fill="x", padx=8)
        self._port_summary = tk.Label(sf, text="", font=FONT_MONO_S,
                                      bg=T["bg"], fg=T["fg_dim"], anchor="w")
        self._port_summary.pack(side="left")

        # Action buttons
        act = ttk.Frame(parent, style="MT.TFrame")
        act.pack(fill="x", padx=8, pady=4)
        ttk.Button(act, text="Toggle Lease",     style="MT.TButton",
                   command=self._do_toggle_lease).pack(side="left", padx=(0, 4))
        ttk.Button(act, text="Repair Property",  style="OK.TButton",
                   command=self._do_repair).pack(side="left", padx=(0, 4))
        ttk.Button(act, text="Add Upgrade",      style="MT.TButton",
                   command=self._do_upgrade).pack(side="left", padx=(0, 4))
        ttk.Button(act, text="Sell Property",    style="Danger.TButton",
                   command=self._do_sell_property).pack(side="left", padx=(0, 4))

    def _refresh_portfolio(self) -> None:
        g    = self.game
        rows = []
        total_value  = 0.0
        total_lease  = 0.0
        for prop in g.real_estate:
            cond_label_str, _ = condition_label(prop.condition)
            if prop.under_construction:
                status = f"🏗 Building ({prop.construction_days_left}d)"
                tag    = "dim"
            elif prop.is_leased:
                tenant_str = prop.tenant_name or "Leased"
                status = f"📋 {tenant_str[:16]}"
                tag    = "green"
            else:
                status = "Available"
                tag    = "cyan"
            if not prop.under_construction:
                total_value += prop.current_value
                if prop.is_leased:
                    total_lease += prop.daily_lease
            rows.append({
                "name":   prop.name,
                "area":   prop.area.value,
                "type":   PROPERTY_CATALOGUE.get(prop.prop_type, {}).get("name", prop.prop_type).title(),
                "cond":   f"{cond_label_str} ({prop.condition:.0%})",
                "value":  f"{prop.current_value:,.0f}g",
                "lease":  f"{prop.daily_lease:.1f}g" if not prop.under_construction else "—",
                "status": status,
                "days":   str(prop.days_owned),
                "tag":    tag,
                "_prop":  prop,
            })
        # Land plots
        for plot in g.land_plots:
            if plot.build_project:
                cat   = PROPERTY_CATALOGUE.get(plot.build_project, {})
                label = f"🏗 {cat.get('name','Building')} ({plot.build_days_left}d left)"
                tag   = "yellow"
            else:
                label = "Undeveloped"
                tag   = "dim"
            rows.append({
                "name":   f"Land Plot ({plot.size.title()}) — {plot.area.value}",
                "area":   plot.area.value,
                "type":   "Land Plot",
                "cond":   "N/A",
                "value":  f"{round(plot.purchase_price * 1.05):,}g",
                "lease":  "—",
                "status": label,
                "days":   "—",
                "tag":    tag,
                "_prop":  None,
            })
        self._port_table.load(rows, tag_key="tag")
        self._port_summary.config(
            text=(f"Properties: {len(g.real_estate)}     "
                  f"Total value: {total_value:,.0f}g     "
                  f"Lease income: {total_lease:.1f}g/day     "
                  f"Lifetime lease: {g.ach_stats.get('re_lease_income', 0):,.0f}g")
        )

    def _selected_property(self) -> "Property | None":
        row = self._port_table.selected()
        if not row:
            return None
        return row.get("_prop")

    def _do_toggle_lease(self) -> None:
        prop = self._selected_property()
        if prop is None:
            self.msg.warn("Select a property first.")
            return
        if prop.under_construction:
            self.msg.warn("Cannot lease a property still under construction.")
            return
        if prop.condition < 0.25:
            self.msg.warn("Property is too derelict to lease \u2014 repair it first.")
            return
        if prop.is_leased:
            tenant_str = prop.tenant_name or "current tenant"
            if not ConfirmDialog(self,
                    f"End lease with '{tenant_str}' for '{prop.name}'?",
                    "End Lease").wait():
                return
            prop.is_leased       = False
            prop.tenant_name     = ""
            prop.lease_rate_mult = 1.0
            self.msg.ok("Lease ended.")
        else:
            # Open tenant applicant review dialog
            std_rate = prop.daily_lease  # computed at rate_mult=1.0
            applicant = LeaseApplicantDialog(self, prop.name, std_rate).wait()
            if applicant is None:
                return   # player cancelled
            prop.is_leased       = True
            prop.tenant_name     = applicant["name"]
            prop.lease_rate_mult = applicant["rate_mult"]
            actual_rate = round(std_rate * applicant["rate_mult"], 2)
            self.msg.ok(
                f"'{prop.name}' leased to {applicant['name']}  \u2014  "
                f"{actual_rate:.2f}g/day  ({applicant['rate_mult']:.0%} of standard)."
            )
            self.game.ach_stats["re_leases_active"] = sum(
                1 for p in self.game.real_estate if p.is_leased and not p.under_construction)
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
        rc    = prop.repair_cost
        g     = self.game
        if g.inventory.gold < rc:
            self.msg.err(f"Need {rc:,.0f}g for repairs.  You have {g.inventory.gold:,.0f}g.")
            return
        old_cond = prop.condition
        if not ConfirmDialog(self,
                f"Repair '{prop.name}' for {rc:,.0f}g?\n"
                f"Condition {old_cond:.0%} → Pristine (100%)",
                "Confirm Repair").wait():
            return
        g.inventory.gold -= rc
        prop.condition    = 1.0
        self.msg.ok(f"'{prop.name}' fully repaired — now worth {prop.current_value:,.0f}g.")
        g._log_event(f"Repaired {prop.name} for {rc:.0f}g → pristine.")
        g._check_achievements()
        self.app.refresh()

    def _do_upgrade(self) -> None:
        prop = self._selected_property()
        if prop is None:
            self.msg.warn("Select a property first.")
            return
        if prop.under_construction:
            self.msg.warn("Cannot upgrade a property under construction.")
            return
        g = self.game
        # Build list of upgrades not yet applied
        available = [(k, v) for k, v in PROPERTY_UPGRADES.items()
                     if k not in prop.upgrades]
        if not available:
            self.msg.info("All upgrades have already been applied to this property.")
            return
        choices = [
            f"{v['desc']}  (cost: {round(prop.current_value * v['cost_frac']):,}g  "
            f"+{v['value_frac']:.0%} value  +{v['lease_frac']:.0%} lease)"
            for k, v in available
        ]
        idx = ChoiceDialog(self, f"Choose an upgrade for '{prop.name}':", choices,
                           title="Add Upgrade").wait()
        if idx is None:
            return
        ukey, udata = available[idx]
        cost = round(prop.current_value * udata["cost_frac"], 2)
        if g.inventory.gold < cost:
            self.msg.err(f"Need {cost:,.0f}g for this upgrade.  Have {g.inventory.gold:,.0f}g.")
            return
        if not ConfirmDialog(self, f"Apply '{ukey.replace('_',' ').title()}' to '{prop.name}' for {cost:,.0f}g?",
                             "Confirm Upgrade").wait():
            return
        g.inventory.gold -= cost
        prop.upgrades.append(ukey)
        g.ach_stats["re_upgrades_applied"] = g.ach_stats.get("re_upgrades_applied", 0) + 1
        self.msg.ok(f"Upgrade applied!  New value: {prop.current_value:,.0f}g  "
                    f"Lease: {prop.daily_lease:.1f}g/day")
        g._log_event(f"Upgraded {prop.name}: {ukey}")
        g._check_achievements()
        self.app.refresh()

    def _do_sell_property(self) -> None:
        prop = self._selected_property()
        if prop is None:
            row  = self._port_table.selected()
            # Could be a land plot row
            if row and row.get("type") == "Land Plot":
                self._do_sell_plot(row)
            else:
                self.msg.warn("Select a property to sell.")
            return
        g          = self.game
        sell_price = round(prop.current_value * 0.88, 2)   # 12% selling agent fee
        if not ConfirmDialog(self,
                f"Sell '{prop.name}' for {sell_price:,.0f}g?\n"
                f"(Agent fee applied — appraised: {prop.current_value:,.0f}g)",
                "Confirm Sale").wait():
            return
        profit = round(sell_price - prop.purchase_price_paid, 2)
        g.inventory.gold += sell_price
        g.real_estate.remove(prop)
        g.ach_stats["re_properties_sold"]  = g.ach_stats.get("re_properties_sold", 0) + 1
        g.ach_stats["re_flip_profit"]      = g.ach_stats.get("re_flip_profit", 0.0) + max(0, profit)
        if profit > g.ach_stats.get("re_max_flip_profit", 0.0):
            g.ach_stats["re_max_flip_profit"] = profit
        if g.ach_stats.get("re_derelict_flip") is not True:
            if prop.condition >= 0.99 and prop.purchase_price_paid > 0:
                # Check if original listing was derelict (condition < 0.25 at original buy)
                # We approximate by checking if repair cost was large vs buy price
                orig_cond_approx = prop.purchase_price_paid / (prop.base_value * prop.area_mult)
                if orig_cond_approx <= 0.35:
                    if profit > 0:
                        g.ach_stats["re_derelict_flip"] = True
        g.total_profit += max(0, profit)
        g._log_event(f"Sold {prop.name} for {sell_price:.0f}g (profit: {profit:+.0f}g)")
        profit_str = f"{profit:+,.0f}g"
        self.msg.ok(f"Sold '{prop.name}' for {sell_price:,.0f}g  (profit {profit_str}).")
        if profit > 100:
            self.app.profit_flash(profit)
        g._check_achievements()
        self.app.refresh()

    def _do_sell_plot(self, row: dict) -> None:
        g    = self.game
        # Find plot from row text
        area_str  = row.get("area", "")
        size_str  = row.get("name", "")
        plot = next((p for p in g.land_plots
                     if p.area.value == area_str), None)
        if plot is None:
            self.msg.warn("Could not identify plot.")
            return
        sell_price = round(plot.purchase_price * 0.85, 2)
        if not ConfirmDialog(self, f"Sell {plot.size.title()} land plot in {plot.area.value} for {sell_price:,.0f}g?",
                             "Sell Land").wait():
            return
        g.inventory.gold += sell_price
        g.land_plots.remove(plot)
        self.msg.ok(f"Land plot sold for {sell_price:,.0f}g.")
        self.app.refresh()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 2: Browse Listings
    # ─────────────────────────────────────────────────────────────────────────

    def _build_listings_tab(self, parent: ttk.Frame) -> None:
        ctrl = ttk.Frame(parent, style="MT.TFrame")
        ctrl.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(ctrl, text="Area:", font=FONT_FANTASY_S,
                 bg=T["bg"], fg=T["fg_dim"]).pack(side="left")
        self._list_area_var = tk.StringVar()
        area_names = [a.value for a in Area]
        self._list_area_var.set(area_names[0])
        self._list_area_combo = ttk.Combobox(
            ctrl, textvariable=self._list_area_var,
            values=area_names, width=20, state="readonly",
            style="MT.TCombobox",
        )
        self._list_area_combo.pack(side="left", padx=(4, 8))
        ttk.Button(ctrl, text="🔄 Refresh Listings", style="MT.TButton",
                   command=self._do_refresh_listings).pack(side="left", padx=(0, 8))
        self._lbl_list_info = tk.Label(ctrl, text="", font=FONT_MONO_S,
                                       bg=T["bg"], fg=T["fg_dim"])
        self._lbl_list_info.pack(side="right")

        self._list_table = DataTable(parent, self._LIST_COLS, height=10)
        self._list_table.pack(fill="both", expand=True, padx=8, pady=4)
        self._listings_data: list = []   # raw listing dicts

        act = ttk.Frame(parent, style="MT.TFrame")
        act.pack(fill="x", padx=8, pady=4)
        ttk.Button(act, text="Buy at Asking Price", style="OK.TButton",
                   command=lambda: self._do_buy_listing(haggle=False)).pack(side="left", padx=(0, 4))
        ttk.Button(act, text="Haggle", style="MT.TButton",
                   command=lambda: self._do_buy_listing(haggle=True)).pack(side="left", padx=(0, 4))

    def _refresh_listings(self, force: bool = False) -> None:
        g    = self.game
        area_val  = self._list_area_var.get() if hasattr(self, "_list_area_var") else g.current_area.value
        area_enum = next((a for a in Area if a.value == area_val), g.current_area)
        if force or not self._listings_data or getattr(self, "_listings_area_cache", "") != area_val:
            self._listings_data       = g._generate_property_listings(area_enum, count=10)
            self._listings_area_cache = area_val
        rows = []
        for lst in self._listings_data:
            rows.append({
                "name":    lst["name"],
                "type":    PROPERTY_CATALOGUE.get(lst["prop_type"], {}).get("name", lst["prop_type"]).title(),
                "cond":    f"{lst['cond_label']} ({lst['condition']:.0%})",
                "asking":  f"{lst['asking_price']:,.0f}g",
                "repair":  f"~{lst['repair_cost']:,.0f}g",
                "lease":   f"{lst['daily_lease']:.1f}g/day",
                "haggle":  "Yes" if lst["is_negotiable"] else "No",
                "flavour": lst["flavour"],
                "tag":     ("dim" if lst["condition"] <= 0.22
                             else "green" if lst["condition"] >= 0.80 else "cyan"),
                "_listing": lst,
            })
        self._list_table.load(rows, tag_key="tag")
        self._lbl_list_info.config(
            text=f"Showing {len(self._listings_data)} listings in {area_val}")

    def _do_refresh_listings(self) -> None:
        self._refresh_listings(force=True)

    def _do_buy_listing(self, haggle: bool) -> None:
        import random as _rng
        row = self._list_table.selected()
        if not row:
            self.msg.warn("Select a listing first.")
            return
        lst = row.get("_listing")
        if lst is None:
            return
        g         = self.game
        area_enum = lst["area"]
        asking    = lst["asking_price"]

        # ── Haggling flow ────────────────────────────────────────
        if haggle:
            if not lst["is_negotiable"]:
                self.msg.warn("This seller is firm on their price — haggling refused.")
                return
            hag_lvl = g.skills.haggling
            # Chance: 20% base + 10% per haggling skill level
            success_chance = 0.20 + hag_lvl * 0.10
            if _rng.random() > success_chance:
                # Failed — seller annoyed; offer to buy at full price
                if not ConfirmDialog(self,
                        f"Your haggling attempt failed!\n"
                        f"The seller won't budge from {asking:,.0f}g.\n\n"
                        f"Buy at full asking price instead?",
                        "❌ Haggle Failed").wait():
                    return
                final_price = asking
            else:
                # Succeeded — discount scales with skill
                discount    = min(0.28, hag_lvl * _rng.uniform(0.025, 0.07))
                final_price = round(asking * (1.0 - discount), 2)
                if not ConfirmDialog(self,
                        f"✓ Haggling succeeded!  (Haggling Lv.{hag_lvl})\n\n"
                        f"Original asking:  {asking:,.0f}g\n"
                        f"Discount:            {discount:.1%} off\n"
                        f"Your price:          {final_price:,.0f}g",
                        "✓ Haggle Success!").wait():
                    return
                try:
                    from merchant_tycoon import SkillType
                    g._gain_skill_xp(SkillType.HAGGLING, 8)
                except Exception:
                    pass
        else:
            final_price = asking
            if not ConfirmDialog(self,
                    f"Buy '{lst['name']}' ({lst['cond_label']}) for {final_price:,.0f}g?\n\n"
                    f"Est. repair to pristine:  ~{lst['repair_cost']:,.0f}g\n"
                    f"Lease income (cur. cond.):  {lst['daily_lease']:.1f}g/day",
                    "Confirm Purchase").wait():
                return

        if g.inventory.gold < final_price:
            self.msg.err(f"Need {final_price:,.0f}g.  Have {g.inventory.gold:,.0f}g.")
            return
        if LicenseType.REAL_ESTATE not in g.licenses:
            self.msg.err("Real Estate Charter required.")
            return

        g.inventory.gold -= final_price
        new_prop = Property(
            id=g.next_property_id,
            prop_type=lst["prop_type"],
            name=lst["name"],
            area=area_enum,
            condition=lst["condition"],
            base_value=lst["pristine_value"] / lst["area_mult"],
            area_mult=lst["area_mult"],
            purchase_price_paid=final_price,
        )
        g.next_property_id += 1
        g.real_estate.append(new_prop)
        g.ach_stats["re_properties_owned"] = g.ach_stats.get("re_properties_owned", 0) + 1
        areas_list = g.ach_stats.setdefault("re_properties_areas", [])
        if new_prop.area.name not in areas_list:
            areas_list.append(new_prop.area.name)
        self._listings_data.remove(lst)
        g._log_event(f"Purchased {new_prop.name} in {area_enum.value} for {final_price:.0f}g")
        self.msg.ok(f"'{new_prop.name}' purchased for {final_price:,.0f}g!")
        g._check_achievements()
        self.app.refresh()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 3: Build on Land
    # ─────────────────────────────────────────────────────────────────────────

    def _build_land_tab(self, parent: ttk.Frame) -> None:
        # Land Plots I Own
        self.section_label(parent, "YOUR LAND PLOTS").pack(anchor="w", padx=10, pady=(6, 2))
        self._land_table = DataTable(parent, self._LAND_COLS, height=5)
        self._land_table.pack(fill="x", padx=8, pady=(0, 4))
        land_act = ttk.Frame(parent, style="MT.TFrame")
        land_act.pack(fill="x", padx=8)
        ttk.Button(land_act, text="Start Construction", style="OK.TButton",
                   command=self._do_start_build).pack(side="left", padx=(0, 4))

        ttk.Separator(parent, style="MT.TSeparator").pack(fill="x", padx=10, pady=8)

        # Buy New Plot
        self.section_label(parent, "BUY A LAND PLOT").pack(anchor="w", padx=10, pady=(0, 2))
        buy_f = ttk.Frame(parent, style="MT.TFrame")
        buy_f.pack(fill="x", padx=10)
        tk.Label(buy_f, text="Size:", font=FONT_FANTASY_S,
                 bg=T["bg"], fg=T["fg_dim"]).grid(row=0, column=0, sticky="w", padx=4)
        self._plot_size_var = tk.StringVar(value="medium")
        for i, sz in enumerate(["small", "medium", "large"]):
            tk.Radiobutton(buy_f, text=sz.title(), variable=self._plot_size_var,
                           value=sz, bg=T["bg"], fg=T["fg"],
                           selectcolor=T["bg_hover"],
                           activebackground=T["bg"],
                           font=FONT_FANTASY_S).grid(row=0, column=i+1, padx=8, sticky="w")
        tk.Label(buy_f, text="Area:", font=FONT_FANTASY_S,
                 bg=T["bg"], fg=T["fg_dim"]).grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self._plot_area_var = tk.StringVar()
        area_names = [a.value for a in Area]
        self._plot_area_combo = ttk.Combobox(
            buy_f, textvariable=self._plot_area_var,
            values=area_names, width=22, state="readonly",
            style="MT.TCombobox",
        )
        self._plot_area_var.set(area_names[0])
        self._plot_area_combo.grid(row=1, column=1, columnspan=3, sticky="w", padx=4)
        self._lbl_plot_cost = tk.Label(buy_f, text="", font=FONT_MONO_S,
                                       bg=T["bg"], fg=T["yellow"])
        self._lbl_plot_cost.grid(row=2, column=0, columnspan=4, sticky="w", padx=4, pady=2)
        ttk.Button(buy_f, text="Buy Plot", style="OK.TButton",
                   command=self._do_buy_plot).grid(row=3, column=0, columnspan=2,
                                                   sticky="w", padx=4, pady=4)
        # Update cost label when controls change
        self._plot_size_var.trace_add("write", lambda *_: self._update_plot_cost())
        self._plot_area_var.trace_add("write", lambda *_: self._update_plot_cost())

    def _update_plot_cost(self) -> None:
        if not hasattr(self, "_lbl_plot_cost"):
            return
        import math as _math
        sz        = self._plot_size_var.get()
        area_val  = self._plot_area_var.get()
        area_enum = next((a for a in Area if a.value == area_val), None)
        if area_enum is None:
            return
        amult     = AREA_PROPERTY_MULT.get(area_enum.name, 1.0)
        base_cost = LAND_PLOT_SIZES[sz]["base_cost"]
        cost      = round(base_cost * amult, 0)
        self._lbl_plot_cost.config(
            text=f"Plot cost: {cost:,.0f}g  ·  "
                 f"Buildable: {', '.join(LAND_PLOT_SIZES[sz]['max_build'])}")

    def _refresh_land(self) -> None:
        g    = self.game
        rows = []
        for plot in g.land_plots:
            if plot.build_project:
                cat  = PROPERTY_CATALOGUE.get(plot.build_project, {})
                prog = f"{cat.get('build_days', 1) - plot.build_days_left}/{cat.get('build_days', 1)}d"
                stat = f"Building: {cat.get('name', plot.build_project)}"
            else:
                stat = "Undeveloped — ready to build"
                prog = "—"
            rows.append({
                "area":     plot.area.value,
                "size":     plot.size.title(),
                "cost":     f"{plot.purchase_price:,.0f}g",
                "status":   stat,
                "progress": prog,
                "tag":      "yellow" if plot.build_project else "cyan",
                "_plot":    plot,
            })
        self._land_table.load(rows, tag_key="tag")

    def _do_buy_plot(self) -> None:
        g        = self.game
        if LicenseType.REAL_ESTATE not in g.licenses:
            self.msg.err("Real Estate Charter required.")
            return
        sz        = self._plot_size_var.get()
        area_val  = self._plot_area_var.get()
        area_enum = next((a for a in Area if a.value == area_val), None)
        if area_enum is None:
            self.msg.err("Select a valid area.")
            return
        amult = AREA_PROPERTY_MULT.get(area_enum.name, 1.0)
        cost  = round(LAND_PLOT_SIZES[sz]["base_cost"] * amult, 0)
        if g.inventory.gold < cost:
            self.msg.err(f"Need {cost:,.0f}g.  Have {g.inventory.gold:,.0f}g.")
            return
        if not ConfirmDialog(self, f"Buy {sz.title()} land plot in {area_enum.value} for {cost:,.0f}g?",
                             "Buy Land Plot").wait():
            return
        g.inventory.gold -= cost
        new_plot = LandPlot(
            id=g.next_plot_id, area=area_enum, size=sz,
            purchase_price=cost,
        )
        g.next_plot_id += 1
        g.land_plots.append(new_plot)
        g._log_event(f"Bought {sz} land plot in {area_enum.value} for {cost:.0f}g")
        self.msg.ok(f"{sz.title()} land plot purchased in {area_enum.value} for {cost:,.0f}g.")
        self.app.refresh()

    def _do_start_build(self) -> None:
        row = self._land_table.selected()
        if not row:
            self.msg.warn("Select a land plot first.")
            return
        plot = row.get("_plot")
        if plot is None:
            return
        g = self.game
        if plot.build_project:
            self.msg.warn(f"Construction already underway: {plot.build_project}.")
            return
        sz_info   = LAND_PLOT_SIZES[plot.size]
        max_build = sz_info["max_build"]
        # Filter by area restrictions in catalogue
        buildable = [k for k in max_build
                     if (cat := PROPERTY_CATALOGUE.get(k)) and
                     (cat.get("areas") is None or plot.area.name in cat["areas"])]
        if not buildable:
            self.msg.warn("No buildable property types for this plot in this area.")
            return
        amult = AREA_PROPERTY_MULT.get(plot.area.name, 1.0)

        # Card grid dialog — much more readable than a plain listbox
        dlg_title = f"Build on {plot.size.title()} Plot — {plot.area.value}"
        idx = BuildCardDialog(self, dlg_title, buildable, amult).wait()
        if idx is None:
            return
        key  = buildable[idx]
        cat  = PROPERTY_CATALOGUE[key]
        cost = round(cat["build_cost"] * amult, 0)
        if g.inventory.gold < cost:
            self.msg.err(f"Need {cost:,.0f}g to start construction.  Have {g.inventory.gold:,.0f}g.")
            return
        if not ConfirmDialog(self,
                f"Build {cat['name']} on {plot.size.title()} plot in {plot.area.value}?\n"
                f"Cost: {cost:,.0f}g  |  Duration: {cat['build_days']} days\n"
                f"Finished value: ~{round(cat['base_value'] * amult):,}g",
                "Confirm Build").wait():
            return
        g.inventory.gold     -= cost
        plot.build_project    = key
        plot.build_days_left  = cat["build_days"]
        plot.build_cost_paid  = cost
        g._log_event(f"Started building {cat['name']} in {plot.area.value}: {cost:.0f}g, {cat['build_days']}d")
        self.msg.ok(f"Construction started!  {cat['name']} will be ready in {cat['build_days']} days.")
        self.app.refresh()

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        if not hasattr(self, "_nb"):
            return
        g       = self.game
        locked  = LicenseType.REAL_ESTATE not in g.licenses

        if locked:
            self._nb.pack_forget()
            self._lbl_locked.pack(fill="both", expand=True)
        else:
            self._lbl_locked.pack_forget()
            self._nb.pack(fill="both", expand=True, padx=10, pady=4)

        # Stats header
        prop_count  = sum(1 for p in g.real_estate if not p.under_construction)
        lease_count = sum(1 for p in g.real_estate if p.is_leased and not p.under_construction)
        total_daily = sum(p.daily_lease for p in g.real_estate if p.is_leased and not p.under_construction)
        if hasattr(self, "_lbl_stats"):
            self._lbl_stats.config(
                text=(f"Properties: {prop_count}   Leased: {lease_count}   "
                      f"Income: {total_daily:.1f}g/day   "
                      f"Under construction: {sum(1 for p in g.real_estate if p.under_construction) + len([p for p in g.land_plots if p.build_project])}")
            )

        if not locked:
            self._refresh_portfolio()
            self._refresh_listings()
            self._refresh_land()
            self._update_plot_cost()
            # Sync area combos to current area
            if hasattr(self, "_list_area_var"):
                self._list_area_var.set(g.current_area.value)
            if hasattr(self, "_plot_area_var"):
                self._plot_area_var.set(g.current_area.value)


class HelpScreen(Screen):
    """Help & Guide — all 11 topics as a left-list / right-content pane."""

    _CONTENT: List[Tuple[str, str]] = [
        ("Trading Basics", """\
Buy goods in one area and sell them in another for profit.
Each buy or sell action costs 1 time slot (max 6 per day).

Buy: Trade → Buy tab → select item → Enter quantity.
Sell: Trade → Sell tab → select item → Enter quantity.
Pawn price: If an area doesn't normally stock an item, you still
  sell it at 65% of base price (shown as [pawn]).

Profit tip: check the Trend column (▲/▼) — rising prices mean
  you can sell higher, falling means buy discounts ahead.
"""),
        ("Prices & Seasons", """\
Each item has a base price that shifts with supply, demand, and events.

Seasons: Spring / Summer / Autumn / Winter.
  Each area produces goods that peak in a specific season.
  Off-season supply drops and buy prices rise.
  Tip: buy in-season, sell out-of-season.

Pressure: internal score (shown in Market Info).
  pressure > natural  →  item is expensive (overcrowded buying).
  pressure < natural  →  item is cheap (lots of supply).
  Pressure reverts ~20% per day toward natural.

Price history: double-click any item in Market Info to see the
  last 20 price snapshots for that item.
"""),
        ("Business Management", """\
Businesses produce goods every day, even while you travel.

Requirements: Business Permit license (buy from Licenses tab).

Purchase: Businesses → Buy Business → pick from catalogue.
  Each business is tied to an area; produce it there.
  Cost: 1200–3800g depending on type and output.

Workers: each hired worker improves daily output by +15%.
  No workers = 0 production.  5 workers max per business.

Levels: upgrade to increase production multiplier.
  Lv1=1.0×, Lv2=1.6×, Lv3=2.2×, Lv4=2.8×, …

Breakdowns: random chance to break; repair to resume output.
Sell: recoup ~50% of purchase cost (+ upgrade bonus).
"""),
        ("Skills Guide", """\
Six skills improve passively via trade actions:

Trading   — upgrades give better buy/sell price margins.
Haggling  — boosts chance and size of purchase discounts.
Logistics — +20 carry weight per level (more cargo per trip).
Industry  — multiplies business daily production output.
Espionage — improves smuggling success and reveals market info.
Banking   — better savings rate, cheaper loans, higher CD returns.

Upgrade cost: Lv × Lv × 150g  (Lv1→2 = 150g, Lv5→6 = 3750g).
XP gained: +5 XP per trade/haggle/wait action.
No XP threshold — upgrade costs gold only.
"""),
        ("Contracts & Reputation", """\
Contracts: formal delivery orders for bonus gold.

Requirements: Trade Contract Seal license.
Generate: Contracts → Generate New Contracts.
Fulfill: Travel to the destination area with the listed goods,
  then use Contracts → Fulfill Selected.

Reward = price_per_unit × quantity + bonus.
Missing deadline incurs a gold penalty.
Contracts boost reputation when fulfilled on time.

Reputation (0–100):
  0–19: Outlaw   (sell prices heavily penalised)
  20–39: Suspect
  40–59: Neutral
  60–79: Trusted
  80–100: Legendary (best prices, special events)
"""),
        ("Smuggling & Heat", """\
Contraband: items marked [!] are illegal in most areas.
You can buy and sell them at the Smuggling Den.

Buy from informant: 1.25× base price, +8 heat per deal.
Sell to fence: ~85–95% of base price, +10 heat.
Bribe guards: spend gold to reduce heat (guard level × 30g).

Heat (0–100): risk of getting caught.
  High heat = higher catch chance when smuggling.
  Heat cools by 3 per travel day.
  Heat ≥ 80: Den is locked until you cool down.

Catch consequences: goods seized + fine + rep −15 + heat +25.

Swamp is the safest area for selling contraband openly.
Espionage skill reduces catch chance: −2.5% per level.
"""),
        ("World Events & News", """\
Random events affect market prices for several days.

Event effects:
  Drought      — grain & fibre scarce, prices elevated.
  Flood        — farm & coastal goods disrupted.
  Bumper Harvest — crop prices fall.      
  Mine Collapse — ore, coal & gems in short supply.
  Piracy Surge  — coastal trade disrupted.
  Trade Boom    — all goods in higher demand.
  Plague        — medicine & herbs extremely scarce.
  Border War    — steel & ore demand surging.
  Gold Rush     — gold dust prices soften.
  Grand Festival — luxury goods in peak demand.

Check News & Events → Active Events for current conditions.
Events are area-specific — travel to exploit price differences.
"""),
        ("Areas & Travel", """\
8 tradeable areas, each with unique goods and risks:

Capital City    — all goods; tannery, glassworks, smithy, apothecary.
Farmlands       — wheat, wine, ale; low risk; 1 day from City.
Mountain Peaks  — ore, gem, coal; moderate risk; 2 days from City.
Coastal Harbor  — fish, salt; low/mod risk; 1 day from City.
Deep Forest     — timber, herbs; moderate risk; 2 days from City.
Sand Desert     — spice, glass (pawn); high risk; 3 days from City.
Misty Swamp     — contraband safe zone; moderate risk.
Frozen Tundra   — fur, blubber; very high risk; 4 days from City.

Travel cost: 3g × days × cost multiplier.
Overloaded (over max carry weight): +1 day per 15wt excess.
Bodyguard offer: available when route risk ≥ 5%.
"""),
        ("Tips & Strategies", """\
Early game (Days 1–60):
  • Buy wheat/ale at Farmlands, sell at City for steady profit.
  • Haggle on every buy to stretch your gold.
  • Get a Contracts license early — bonus gold per delivery.

Mid game (Days 61–200):
  • Purchase a Farm or Fishery; assign workers immediately.
  • Trade spice/gems for large per-trip margins.
  • Monitor seasonal bonuses — sell in the correct area.

Late game:
  • Upgrade skills to Lv5+ for significant production/price gains.
  • Open CDs for passive income while traveling.
  • Use the Arbitrage tab to find the best current trade route.

General:
  • Sell price is reduced if your reputation is below 40.
  • Waiting increases wait_streak; some achievements need it.
  • Markets self-correct — don't buy everything at once.
"""),
        ("Social & Influence", """\
Reputation affects your sell prices and license access.
  rep < 40: sell prices are penalised (up to −22%).
  rep ≥ 80: access to Legendary pricing and rare events.

Raise reputation:
  • Fulfill contracts on time.
  • Donate to charity (25g = +1 rep).
  • Political campaign (200g = +5 rep, +10 heat).

Lower reputation:
  • Getting caught smuggling (−12 to −15 rep).
  • Travel attacks/incidents (−2 to −3 rep).

Licenses require minimum reputation:
  Business Permit    — Rep 10+
  Contract Seal      — Rep 15+
  Lending Charter    — Rep 40+
  Fund Manager       — Rep 60+
"""),
        ("Schedule & Time", """\
Each in-game day has 6 time slots.
  Each trade (buy or sell) uses 1 slot.
  Haggling, waiting, and certain actions also use 1 slot.
  When all 6 slots are used the day advances automatically.

Day structure:
  Day 1–30:  Season 1 (e.g. Spring)
  Day 31–60: Season 2, etc.  Each year = 4 seasons = 120 days.

Waiting:
  Use Wait / Rest to skip days deliberately.
    • Lets businesses accumulate produced goods.
    • Heat cools 3 per travel day (passively).
    • Markets restock and prices normalise.

Living cost: deducted each day automatically.
  Cost = base + difficulty multiplier.
"""),
    ]

    def build(self) -> None:
        main = ttk.Frame(self, style="MT.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        self.section_label(main, "HELP & GUIDE").pack(anchor="w", padx=10, pady=(0, 4))

        pane = ttk.Frame(main, style="MT.TFrame")
        pane.pack(fill="both", expand=True, padx=10, pady=4)

        # Left: topic list
        lf = tk.Frame(pane, bg=T["bg_panel"], width=190)
        lf.pack(side="left", fill="y", padx=(0, 6))
        lf.pack_propagate(False)
        tk.Label(lf, text="Topics", bg=T["bg_panel"],
                 fg=T["cyan"], font=FONT_BOLD).pack(pady=(8, 4))
        self._lb = tk.Listbox(
            lf, font=FONT_MONO_S,
            bg=T["bg_panel"], fg=T["fg"],
            selectbackground=T["bg_hover"], selectforeground=T["fg_header"],
            activestyle="none", relief="flat", borderwidth=0,
        )
        for i, (title, _) in enumerate(self._CONTENT):
            self._lb.insert("end", f"  {i + 1}. {title}")
        self._lb.pack(fill="both", expand=True, padx=4, pady=(0, 8))
        self._lb.bind("<<ListboxSelect>>", self._on_select)

        # Right: content text
        rf = tk.Frame(pane, bg=T["bg"])
        rf.pack(side="left", fill="both", expand=True)
        self._txt = tk.Text(
            rf, bg=T["bg"], fg=T["fg"], font=FONT_MONO,
            relief="flat", wrap="word", state="disabled",
            padx=12, pady=8,
        )
        vsb = ttk.Scrollbar(rf, orient="vertical", command=self._txt.yview,
                            style="MT.Vertical.TScrollbar")
        self._txt.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._txt.pack(side="left", fill="both", expand=True)

        # Select first topic by default
        self._lb.selection_set(0)
        self._on_select(None)

        ttk.Separator(main, style="MT.TSeparator").pack(fill="x", padx=10, pady=(4, 2))
        self.back_button(main).pack(anchor="w", padx=10, pady=4)

    def _on_select(self, _event) -> None:
        sel = self._lb.curselection()
        if not sel:
            return
        _, body = self._CONTENT[sel[0]]
        self._txt.config(state="normal")
        self._txt.delete("1.0", "end")
        self._txt.insert("1.0", body)
        self._txt.config(state="disabled")
        self._txt.yview_moveto(0.0)

    def refresh(self) -> None:
        pass  # static content; no game state needed


class SettingsScreen(Screen):
    """Comprehensive options screen — game, audio, display, and save info."""

    _DIFF: List[Tuple[str, str, str, str]] = [
        ("easy",   "Easy",   T["green"],  "Costs \u00d70.70  \u00b7  Sell \u00d71.10  \u00b7  Events \u00d70.60  \u00b7  Attacks \u00d70.50"),
        ("normal", "Normal", T["cyan"],   "Costs \u00d71.00  \u00b7  Sell \u00d71.00  \u00b7  Events \u00d71.00  \u00b7  Attacks \u00d71.00"),
        ("hard",   "Hard",   T["yellow"], "Costs \u00d71.35  \u00b7  Sell \u00d70.90  \u00b7  Events \u00d71.40  \u00b7  Attacks \u00d71.50"),
        ("brutal", "Brutal", T["red"],    "Costs \u00d71.80  \u00b7  Sell \u00d70.80  \u00b7  Events \u00d72.00  \u00b7  Attacks \u00d72.50"),
    ]

    def build(self) -> None:
        # Outer scrollable container
        sf = ScrollableFrame(self)
        sf.pack(fill="both", expand=True)
        main = sf.inner

        def _sep():
            ttk.Separator(main, style="MT.TSeparator").pack(fill="x", padx=4, pady=8)

        def _head(text: str):
            tk.Label(main, text=text, font=FONT_BOLD,
                     bg=T["bg"], fg=T["cyan"]).pack(anchor="w", pady=(8, 3), padx=4)

        # ── Title ─────────────────────────────────────────────────────────
        self.section_label(main, "SETTINGS").pack(anchor="w", pady=(4, 8), padx=4)
        _sep()

        # ── GAME section ──────────────────────────────────────────────────
        _head("\u2699  Game")

        # Difficulty
        tk.Label(main, text="Difficulty:", font=FONT_FANTASY_S,
                 bg=T["bg"], fg=T["fg_dim"]).pack(anchor="w", padx=12, pady=(4, 2))
        self._diff_var = tk.StringVar()
        rb_row = ttk.Frame(main, style="MT.TFrame")
        rb_row.pack(anchor="w", padx=12, pady=(0, 2))
        for key, label, color, _ in self._DIFF:
            tk.Radiobutton(
                rb_row, text=label, variable=self._diff_var, value=key,
                bg=T["bg"], fg=color, selectcolor=T["bg_panel"],
                activebackground=T["bg_hover"], activeforeground=color,
                font=FONT_BOLD, command=self._on_diff_change,
            ).pack(side="left", padx=6)
        self._diff_desc = tk.Label(main, text="", font=FONT_MONO_S,
                                   bg=T["bg"], fg=T["grey"], anchor="w")
        self._diff_desc.pack(anchor="w", padx=16, pady=(0, 6))

        # Autosave
        self._autosave_var = tk.BooleanVar()
        tk.Checkbutton(
            main, text="Autosave at end of every in-game day",
            variable=self._autosave_var, command=self._on_autosave_change,
            bg=T["bg"], fg=T["fg_header"], selectcolor=T["bg_panel"],
            activebackground=T["bg_hover"], font=FONT_BOLD,
        ).pack(anchor="w", padx=12, pady=3)

        _sep()
        # ── DISPLAY section ───────────────────────────────────────────────
        _head("\ud83d\udda5  Display  (Ctrl+Scroll to adjust)")

        tk.Label(main, text="UI Scale:", font=FONT_FANTASY_S,
                 bg=T["bg"], fg=T["fg_dim"]).pack(anchor="w", padx=12, pady=(4, 0))

        scale_row = ttk.Frame(main, style="MT.TFrame")
        scale_row.pack(fill="x", padx=12, pady=(2, 0))
        self._scale_var = tk.DoubleVar(value=_UI_SCALE)
        self._scale_lbl = tk.Label(scale_row, text=f"{int(_UI_SCALE * 100)}%",
                                   fg=T["yellow"], bg=T["bg"], font=FONT_MONO,
                                   width=5)
        self._scale_lbl.pack(side="left", padx=(0, 6))
        scale_sl = ttk.Scale(scale_row, from_=0.75, to=2.0,
                             orient="horizontal", variable=self._scale_var,
                             command=self._on_scale_move)
        scale_sl.pack(side="left", fill="x", expand=True)
        ttk.Button(scale_row, text="Reset", style="Nav.TButton",
                   command=self._on_scale_reset).pack(side="left", padx=(8, 0))
        tk.Label(main, text="  75%          100%               150%          200%",
                 font=FONT_SMALL, bg=T["bg"], fg=T["fg_dim"]).pack(anchor="w", padx=12)

        # Profit animations toggle
        _sep()
        _head("\u2728  Animations")
        self._anim_var = tk.BooleanVar()
        tk.Checkbutton(
            main, text="Profit flash animations  (golden glow on large earnings)",
            variable=self._anim_var, command=self._on_anim_change,
            bg=T["bg"], fg=T["fg_header"], selectcolor=T["bg_panel"],
            activebackground=T["bg_hover"], font=FONT_BOLD,
        ).pack(anchor="w", padx=12, pady=3)
        tk.Label(main,
                 text="  \u2265100g shimmer  \u00b7  \u2265500g flash  \u00b7  \u22651000g wash  \u00b7  \u22655000g jackpot",
                 font=FONT_MONO_S, bg=T["bg"], fg=T["grey"]).pack(anchor="w", padx=20, pady=(0, 4))

        _sep()
        # ── AUDIO section ─────────────────────────────────────────────────
        _head("\U0001f50a  Audio")
        self._audio_status = tk.Label(main, text="", font=FONT_MONO_S,
                                      bg=T["bg"], fg=T["fg_dim"])
        self._audio_status.pack(anchor="w", padx=12, pady=(0, 6))

        # Music toggle
        self._music_enabled_var = tk.BooleanVar()
        tk.Checkbutton(
            main, text="Enable music",
            variable=self._music_enabled_var, command=self._on_music_toggle,
            bg=T["bg"], fg=T["fg_header"], selectcolor=T["bg_panel"],
            activebackground=T["bg_hover"], font=FONT_BOLD,
        ).pack(anchor="w", padx=12, pady=2)

        # Music volume
        mv_row = ttk.Frame(main, style="MT.TFrame")
        mv_row.pack(fill="x", padx=12, pady=(4, 2))
        tk.Label(mv_row, text="Music volume:", font=FONT_FANTASY_S,
                 bg=T["bg"], fg=T["fg_dim"], width=16, anchor="w").pack(side="left")
        self._music_vol_var = tk.DoubleVar()
        self._music_vol_lbl = tk.Label(mv_row, text="50%", fg=T["yellow"],
                                       bg=T["bg"], font=FONT_MONO, width=5)
        self._music_vol_lbl.pack(side="left", padx=(0, 4))
        ttk.Scale(mv_row, from_=0.0, to=1.0, orient="horizontal",
                  variable=self._music_vol_var,
                  command=self._on_music_vol).pack(side="left", fill="x", expand=True)

        # SFX volume
        sfx_row = ttk.Frame(main, style="MT.TFrame")
        sfx_row.pack(fill="x", padx=12, pady=(2, 6))
        tk.Label(sfx_row, text="Sound FX volume:", font=FONT_FANTASY_S,
                 bg=T["bg"], fg=T["fg_dim"], width=16, anchor="w").pack(side="left")
        self._sfx_vol_var = tk.DoubleVar()
        self._sfx_vol_lbl = tk.Label(sfx_row, text="70%", fg=T["yellow"],
                                     bg=T["bg"], font=FONT_MONO, width=5)
        self._sfx_vol_lbl.pack(side="left", padx=(0, 4))
        ttk.Scale(sfx_row, from_=0.0, to=1.0, orient="horizontal",
                  variable=self._sfx_vol_var,
                  command=self._on_sfx_vol).pack(side="left", fill="x", expand=True)

        _sep()
        # ── SAVE FILE INFO section ────────────────────────────────────────
        _head("\U0001f4be  Save File Location")
        try:
            from merchant_tycoon import Game as _G
            save_path = _G.SAVE_FILE
        except Exception:
            save_path = "(unknown)"
        tk.Label(main, text=save_path, font=FONT_MONO_S,
                 bg=T["bg"], fg=T["fg_dim"], anchor="w",
                 wraplength=700).pack(anchor="w", padx=16, pady=(2, 8))

        _sep()
        # ── KEYBINDINGS section ─────────────────────────────────────────
        _head("⌨  Keybindings")
        tk.Label(
            main,
            text=(
                "  Click ‘Set’ then press any key or key combination.  "
                "Bare Escape cancels capture.  Multi-key hotkeys (e.g. Ctrl+T) are supported."
            ),
            font=FONT_SMALL, bg=T["bg"], fg=T["grey"],
            wraplength=640, justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 8))

        _HK_ROWS: List[Tuple[str, str]] = [
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
        ]

        hk_outer = ttk.Frame(main, style="MT.TFrame")
        hk_outer.pack(anchor="w", padx=12, pady=(0, 4))
        self._hk_labels: Dict[str, tk.Label] = {}
        hk = self.game.settings.hotkeys
        for action, display in _HK_ROWS:
            row_fr = ttk.Frame(hk_outer, style="MT.TFrame")
            row_fr.pack(fill="x", pady=2)
            tk.Label(row_fr, text=display, font=FONT_FANTASY_S,
                     bg=T["bg"], fg=T["fg_dim"],
                     width=16, anchor="w").pack(side="left", padx=(0, 6))
            self._hk_labels[action] = tk.Label(
                row_fr,
                text=_format_hotkey(hk.get(action, "")),
                font=FONT_MONO, fg=T["yellow"], bg=T["bg_panel"],
                relief="flat", padx=6, pady=2, width=12, anchor="center",
            )
            self._hk_labels[action].pack(side="left", padx=(0, 6))
            ttk.Button(
                row_fr, text="Set", style="Nav.TButton", width=6,
                command=lambda a=action: self._on_set_hotkey(a),
            ).pack(side="left")

        ttk.Button(
            main, text="⟳  Reset All to Defaults",
            style="Nav.TButton",
            command=self._on_reset_hotkeys,
        ).pack(anchor="w", padx=12, pady=(6, 10))

        _sep()
        self.back_button(main).pack(anchor="w", padx=4, pady=4)

    # ── Refresh: sync all controls from live state ─────────────────────────

    def refresh(self) -> None:
        if not hasattr(self, "_diff_var"):
            return
        s = self.game.settings
        self._diff_var.set(s.difficulty)
        self._autosave_var.set(s.autosave)
        self._scale_var.set(_UI_SCALE)
        self._scale_lbl.config(text=f"{int(_UI_SCALE * 100)}%")
        if hasattr(self, "_anim_var"):
            self._anim_var.set(s.profit_flash)
        snd = self.app.sound
        self._audio_status.config(text=f"  {snd.status_string()}")
        self._music_enabled_var.set(s.music_enabled)
        self._music_vol_var.set(s.music_volume)
        self._music_vol_lbl.config(text=f"{int(s.music_volume * 100)}%")
        self._sfx_vol_var.set(s.sfx_volume)
        self._sfx_vol_lbl.config(text=f"{int(s.sfx_volume * 100)}%")
        self._update_diff_desc()
        # Hotkey labels
        if hasattr(self, "_hk_labels"):
            hk = s.hotkeys
            for action, lbl in self._hk_labels.items():
                lbl.config(text=_format_hotkey(hk.get(action, "")))

    # ── Handlers ──────────────────────────────────────────────────────────

    def _update_diff_desc(self) -> None:
        key = self._diff_var.get()
        for k, _, _, desc in self._DIFF:
            if k == key:
                self._diff_desc.config(text=f"  {desc}")
                return

    def _on_diff_change(self) -> None:
        self.game.settings.difficulty = self._diff_var.get()
        self.game.settings.save()
        self._update_diff_desc()
        self.msg.ok(f"Difficulty set to {self._diff_var.get().title()}.")

    def _on_autosave_change(self) -> None:
        self.game.settings.autosave = bool(self._autosave_var.get())
        self.game.settings.save()
        self.msg.ok(f"Autosave {'ON' if self.game.settings.autosave else 'OFF'}.")

    def _on_anim_change(self) -> None:
        self.game.settings.profit_flash = bool(self._anim_var.get())
        self.app.profit_animations = self.game.settings.profit_flash
        self.game.settings.save()
        self.msg.ok(f"Profit animations {'ON' if self.app.profit_animations else 'OFF'}.")

    def _on_scale_move(self, val: str) -> None:
        v = round(float(val) * 4) / 4   # snap to 0.25 steps
        self._scale_lbl.config(text=f"{int(v * 100)}%")
        self.after_idle(lambda: self.app.apply_scale(v))

    def _on_scale_reset(self) -> None:
        self._scale_var.set(1.0)
        self._scale_lbl.config(text="100%")
        self.app.apply_scale(1.0)

    def _on_music_toggle(self) -> None:
        enabled = bool(self._music_enabled_var.get())
        self.game.settings.music_enabled = enabled
        self.app.sound.muted = not enabled
        self.game.settings.save()
        self.msg.ok(f"Music {'enabled' if enabled else 'disabled'}.")
        self._audio_status.config(text=f"  {self.app.sound.status_string()}")

    def _on_music_vol(self, val: str) -> None:
        v = round(float(val), 2)
        self.game.settings.music_volume = v
        self.app.sound.music_volume = v
        self._music_vol_lbl.config(text=f"{int(v * 100)}%")
        self._audio_status.config(text=f"  {self.app.sound.status_string()}")
        self.game.settings.save()

    def _on_sfx_vol(self, val: str) -> None:
        v = round(float(val), 2)
        self.game.settings.sfx_volume = v
        self.app.sound.sfx_volume = v
        self._sfx_vol_lbl.config(text=f"{int(v * 100)}%")
        self._audio_status.config(text=f"  {self.app.sound.status_string()}")
        self.game.settings.save()

    # ── Hotkey handlers ────────────────────────────────────────────────────

    _HK_LABELS_MAP: Dict[str, str] = {
        "trade": "Trade", "travel": "Travel", "inventory": "Inventory",
        "wait": "Rest / Wait", "businesses": "Businesses",
        "finance": "Finance", "contracts": "Contracts",
        "market": "Market Info", "news": "News & Events",
        "progress": "Progress", "skills": "Skills",
        "help": "Help", "settings": "Settings", "save": "Quick Save",
    }

    def _on_set_hotkey(self, action: str) -> None:
        label = self._HK_LABELS_MAP.get(action, action.title())
        new_binding = HotkeyDialog(
            self.app, f"Set hotkey for: {label}"
        ).wait()
        if new_binding is None:
            return   # user cancelled
        self.game.settings.hotkeys[action] = new_binding
        self.game.settings.save()
        self.app._setup_hotkeys()   # re-register with updated bindings
        if action in self._hk_labels:
            self._hk_labels[action].config(text=_format_hotkey(new_binding))
        self.msg.ok(f"'{label}' hotkey → {_format_hotkey(new_binding)}.")

    def _on_reset_hotkeys(self) -> None:
        self.game.settings.hotkeys = dict(DEFAULT_HOTKEYS)
        self.game.settings.save()
        self.app._setup_hotkeys()   # re-register with defaults
        for action, lbl in self._hk_labels.items():
            lbl.config(text=_format_hotkey(
                self.game.settings.hotkeys.get(action, "")))
        self.msg.ok("All keybindings reset to defaults.")

# ══════════════════════════════════════════════════════════════════════════════
# MAIN MENU SCREEN  —  first fully implemented screen
# ══════════════════════════════════════════════════════════════════════════════

class MainMenuScreen(Screen):
    """
    Hub screen — full-screen card grid with a live dashboard strip at the
    top.  Each navigation option is a hoverable card with icon + label +
    one-line description.  Alert badges surface urgent info without the
    player having to hunt for it.
    """

    # (label, key, section, icon, short description)
    _BUTTONS: List[Tuple[str, str, str, str, str]] = [
        ("Trade",         "trade",      "ACTIONS",      "⚖",  "Buy and sell goods"),
        ("Travel",        "travel",     "ACTIONS",      "🗺", "Journey to new areas"),
        ("Inventory",     "inventory",  "ACTIONS",      "🎒", "Manage your cargo"),
        ("Rest & Wait",   "wait",       "ACTIONS",      "⌛", "Pass time & recover"),
        ("Businesses",    "businesses", "OPERATIONS",   "🏭", "Manage production"),
        ("Finance",       "finance",    "OPERATIONS",   "🏦", "Banking & loans"),
        ("Contracts",     "contracts",  "OPERATIONS",   "📜", "Delivery orders"),
        ("Lending",       "lending",    "OPERATIONS",   "⊛",  "Issue citizen loans"),
        ("Stock Market",  "stocks",     "OPERATIONS",   "📈", "Buy & sell shares"),
        ("Fund Mgmt",     "funds",      "OPERATIONS",   "💰", "Manage client capital"),
        ("Real Estate",   "real_estate","OPERATIONS",   "🏠", "Buy, build & lease property"),
        ("Skills",        "skills",     "OPERATIONS",   "⚡", "Improve your character"),
        ("Smuggling Den", "smuggling",  "OPERATIONS",   "🦝", "Black market deals"),
        ("Market Info",   "market",     "INTELLIGENCE", "📊", "Prices & trade routes"),
        ("News & Events", "news",       "INTELLIGENCE", "📰", "World events & impacts"),
        ("Progress",      "progress",   "PLAYER",       "🏆", "Stats & achievements"),
        ("Influence",     "influence",  "PLAYER",       "⭐", "Reputation & market power"),
        ("Licenses",      "licenses",   "PLAYER",       "📋", "Permits & certifications"),
        ("Help",          "help",       "PLAYER",       "❓", "Game guide & tips"),
        ("Settings",      "settings",   "PLAYER",       "⚙", "Options, audio & keybindings"),
    ]

    def build(self) -> None:
        outer = ttk.Frame(self, style="MT.TFrame")
        outer.pack(fill="both", expand=True)

        # ── Dashboard strip ───────────────────────────────────────────────
        dash = tk.Frame(outer, bg=T["bg_panel"])
        dash.pack(fill="x")
        tk.Frame(outer, bg=T["border_light"], height=2).pack(fill="x")

        dl = tk.Frame(dash, bg=T["bg_panel"])
        dl.pack(side="left", fill="y", expand=True)
        dr = tk.Frame(dash, bg=T["bg_panel"])
        dr.pack(side="right")

        self._dash_gold   = tk.Label(dl, text="", font=FONT_FANTASY_BOLD,
                                     bg=T["bg_panel"], fg=T["yellow"],
                                     padx=16, pady=5, anchor="w")
        self._dash_gold.pack(anchor="w")
        self._dash_status = tk.Label(dl, text="", font=FONT_FANTASY_S,
                                     bg=T["bg_panel"], fg=T["fg_dim"],
                                     padx=16, pady=1, anchor="w")
        self._dash_status.pack(anchor="w")

        self._dash_alert = tk.Label(dr, text="", font=FONT_FANTASY_S,
                                    bg=T["bg_panel"], fg=T["yellow"],
                                    padx=16, pady=6, anchor="e", justify="right")
        self._dash_alert.pack(anchor="e", fill="both", expand=True)

        # ── Card grid ─────────────────────────────────────────────────────
        grid_frame = ttk.Frame(outer, style="MT.TFrame")
        grid_frame.pack(fill="both", expand=True, padx=14, pady=(8, 4))

        COL_N = 4
        for c in range(COL_N):
            grid_frame.columnconfigure(c, weight=1, uniform="navcard")

        # Group buttons by section, preserving insertion order
        sections: Dict[str, list] = {}
        order: List[str] = []
        for label, key, section, icon, desc in self._BUTTONS:
            if section not in sections:
                sections[section] = []
                order.append(section)
            sections[section].append((label, key, icon, desc))

        r = 0
        for sec in order:
            # Section header spanning all columns
            tk.Label(grid_frame, text=f"  ✦  {sec}  ✦",
                     bg=T["bg"], fg=T["border_light"],
                     font=FONT_FANTASY_S, anchor="w",
                     ).grid(row=r, column=0, columnspan=COL_N,
                            sticky="w", pady=(10, 2), padx=2)
            r += 1
            items = sections[sec]
            for i, (label, key, icon, desc) in enumerate(items):
                card = self._make_card(grid_frame, icon, label, desc, key)
                card.grid(row=r + i // COL_N, column=i % COL_N,
                          padx=4, pady=4, sticky="nsew")
            r += (len(items) + COL_N - 1) // COL_N

        # ── Bottom system row ─────────────────────────────────────────────
        ttk.Separator(outer, style="MT.TSeparator").pack(fill="x", padx=14, pady=(6, 3))
        sys_row = ttk.Frame(outer, style="MT.TFrame")
        sys_row.pack(fill="x", padx=14, pady=(0, 8))
        ttk.Button(sys_row, text="💾  Save", style="MT.TButton",
                   command=self._save).pack(side="left", padx=4)
        ttk.Button(sys_row, text="📋  Bankruptcy", style="Danger.TButton",
                   command=self._file_bankruptcy).pack(side="left", padx=4)
        ttk.Button(sys_row, text="✕  Quit", style="Danger.TButton",
                   command=self.app.quit_game).pack(side="right", padx=4)

    def _make_card(self, parent: tk.Widget, icon: str, label: str,
                   desc: str, key: str) -> tk.Frame:
        """Create a hoverable navigation card."""
        border = tk.Frame(parent, bg=T["border"], cursor="hand2")
        inner  = tk.Frame(border, bg=T["bg_panel"])
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        # Left accent bar
        tk.Frame(inner, bg=T["border_light"], width=4).pack(side="left", fill="y")

        body = tk.Frame(inner, bg=T["bg_panel"])
        body.pack(side="left", fill="both", expand=True, padx=12, pady=10)

        lbl_title = tk.Label(body, text=f"{icon}  {label}",
                             bg=T["bg_panel"], fg=T["cyan"],
                             font=FONT_FANTASY_BOLD, anchor="w")
        lbl_title.pack(anchor="w")
        lbl_desc = tk.Label(body, text=desc,
                            bg=T["bg_panel"], fg=T["fg_dim"],
                            font=FONT_FANTASY_S, anchor="w")
        lbl_desc.pack(anchor="w", pady=(1, 0))

        hoverable    = [inner, body, lbl_desc]
        _timer: list = [None]

        def _enter(_e):
            if _timer[0]:
                border.after_cancel(_timer[0])
                _timer[0] = None
            for w in hoverable:
                try: w.config(bg=T["bg_hover"])
                except tk.TclError: pass
            lbl_title.config(bg=T["bg_hover"], fg=T["fg_header"])

        def _leave(_e):
            def _restore():
                _timer[0] = None
                for w in hoverable:
                    try: w.config(bg=T["bg_panel"])
                    except tk.TclError: pass
                lbl_title.config(bg=T["bg_panel"], fg=T["cyan"])
            _timer[0] = border.after(40, _restore)

        def _click(_e):
            self.app.show(key)

        for w in [border, inner, body, lbl_title, lbl_desc]:
            w.bind("<Enter>",    _enter)
            w.bind("<Leave>",    _leave)
            w.bind("<Button-1>", _click)

        return border

    def refresh(self) -> None:
        if not hasattr(self, "_dash_gold"):
            return
        g = self.game

        # ── Left dashboard ────────────────────────────────────────────────
        self._dash_gold.config(
            text=f"◆  {g.inventory.gold:,.0f}g    🏦 Bank: {g.bank_balance:,.0f}g"
                 f"    📈 Net Worth: {g._net_worth():,.0f}g"
        )
        left    = g.DAILY_TIME_UNITS - g.daily_time_units
        used    = g.daily_time_units
        slot_col = T["red"] if left == 0 else (T["yellow"] if left <= 2 else T["cyan"])
        wt_str  = f"{g._current_weight():.0f} / {g._max_carry_weight():.0f} wt"
        self._dash_status.config(
            text=(f"{'●' * used}{'○' * left}  ·  {left} action{'s' if left != 1 else ''} left  ·  "
                  f"🎒 {wt_str}  ·  📍 {g.current_area.value}  ·  "
                  f"Year {g.year}, Day {g.day} — {g.season.value}"),
            fg=slot_col,
        )

        # ── Right alert badges ────────────────────────────────────────────
        alerts: List[str] = []
        active_con = [c for c in g.contracts if not c.fulfilled]
        if active_con:
            c  = min(active_con, key=lambda x: x.deadline_day - g._absolute_day())
            dl = c.deadline_day - g._absolute_day()
            nm = ALL_ITEMS.get(c.item_key, type("", (), {"name": "?"})()).name
            col = "🔴" if dl <= 3 else "🟡"
            alerts.append(f"{col}  Contract: {c.quantity}× {nm} → {c.destination.value}  [{dl}d left]")
        broken = [b for b in g.businesses if b.broken_down]
        if broken:
            alerts.append(f"🔴  {len(broken)} business{'es' if len(broken) > 1 else ''} BROKEN — needs repair")
        if g.heat > 60:
            alerts.append(f"🔥  Heat {g.heat}/100 — travel to cool down")
        if g.news_feed:
            _, _, _, hl = g.news_feed[0]
            alerts.append(f"📰  {hl[:70]}")

        self._dash_alert.config(
            text="\n".join(alerts) if alerts else "",
            fg=T["red"] if (broken or g.heat > 60) else T["yellow"],
        )

    def _save(self) -> None:
        self.game.save_game(silent=True)
        self.msg.ok("Game saved.")

    def _file_bankruptcy(self) -> None:
        """Wipe save, reset to a new game — no tutorial on restart."""
        if not ConfirmDialog(
            self.app,
            "⚠  File for Bankruptcy?\n\n"
            "This will erase all progress and start a brand new game.\n"
            "This action cannot be undone!",
            "File Bankruptcy",
        ).wait():
            return
        self.app._do_bankruptcy_restart()

# ══════════════════════════════════════════════════════════════════════════════
# GAME APP  —  root window and navigation controller
# ══════════════════════════════════════════════════════════════════════════════

class GameApp(tk.Tk):
    """
    Root window and screen orchestrator.

    Screen registry:   self.screens  { name → Screen instance }
    Navigation stack:  self._stack   [ name, … ]  (active = last)

    Public API:
        show(name)    — navigate to a named screen
        go_back()     — pop stack; return to previous screen
        refresh()     — update status bar + re-render current screen
        quit_game()   — prompt save then close
    """

    TITLE    = "Merchant Tycoon — Expanded Edition"
    WIN_W    = 1120
    WIN_H    = 760
    MIN_W    = 900
    MIN_H    = 600

    # Registry: logical name → Screen subclass
    _SCREEN_MAP: Dict[str, type] = {
        "main":       MainMenuScreen,
        "trade":      TradeScreen,
        "travel":     TravelScreen,
        "inventory":  InventoryScreen,
        "wait":       WaitScreen,
        "businesses": BusinessesScreen,
        "finance":    FinanceScreen,
        "contracts":  ContractsScreen,
        "skills":     SkillsScreen,
        "smuggling":  SmugglingScreen,
        "market":     MarketInfoScreen,
        "news":       NewsScreen,
        "progress":   ProgressScreen,
        "influence":  InfluenceScreen,
        "licenses":   LicensesScreen,
        "lending":    CitizenLendingScreen,
        "stocks":     StockMarketScreen,
        "funds":      FundManagementScreen,
        "real_estate": RealEstateScreen,
        "reputation": InfluenceScreen,
        "help":       HelpScreen,
        "settings":   SettingsScreen,
    }

    def __init__(self) -> None:
        super().__init__()
        # ── Window setup ──────────────────────────────────────────────────
        self.title("Merchant Tycoon — Expanded Edition")
        self.geometry(f"{self.WIN_W}x{self.WIN_H}")
        self.minsize(self.MIN_W, self.MIN_H)
        self.configure(bg=T["bg"])

        # Remove native OS title bar; custom bar is built below
        self.overrideredirect(True)

        # Hide the console/CMD window that launched this script
        if sys.platform == "win32":
            import ctypes
            hwnd_console = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd_console:
                ctypes.windll.user32.ShowWindow(hwnd_console, 0)  # SW_HIDE

        # Centre on screen — deferred so the window is fully realized first
        self.after(1, self._center_on_screen)

        # Register window in taskbar (deferred so Win32 HWND is ready)
        if sys.platform == "win32":
            self.after(50, self._set_appwindow)

        # Apply theme
        apply_dark_theme(ttk.Style(self))

        # Game model
        self.game = Game()
        self.profit_animations: bool = True   # toggle via Settings

        # Sound manager (pygame optional — silently disabled if not present)
        self.sound = SoundManager(_HERE)

        # Apply saved settings (scale, audio, animations)
        s = self.game.settings
        if s.ui_scale != 1.0:
            _rescale_fonts(s.ui_scale)
            apply_dark_theme(ttk.Style(self))
        self.profit_animations = s.profit_flash
        self.sound.apply_settings(s.sfx_volume, s.music_volume,
                                   muted=not s.music_enabled)

        # ── Layout: CustomTitleBar / StatusBar / content / MessageBar ─────
        self.custom_title = CustomTitleBar(self, self)
        self.custom_title.pack(fill="x", side="top")

        self.status_bar  = StatusBar(self, self.game)
        self.status_bar.pack(fill="x", side="top")

        self.message_bar = MessageBar(self)
        self.message_bar.pack(fill="x", side="bottom")
        # Wire toast callback so MessageBar also fires floating GameToast
        self.message_bar._toast_fn = lambda text, col: GameToast(self, text, col)

        self._content = ttk.Frame(self, style="MT.TFrame")
        self._content.pack(fill="both", expand=True)

        # ── Screen registry and nav stack ─────────────────────────────────
        self.screens: Dict[str, Screen] = {}
        self._stack:  List[str]         = []
        self._register_screens()

        # ── Global key bindings ───────────────────────────────────────────
        self.bind_all("<Escape>", self._on_escape)
        self.bind("<F5>",        lambda _: self.refresh())
        # Ctrl+Scroll — scale the UI up / down
        self.bind_all("<Control-MouseWheel>", self._on_ctrl_scroll)
        # Register one bind_all per hotkey so Tkinter handles modifier detection
        self._registered_hk_seqs: set = set()
        self._setup_hotkeys()

        # ── Window close ──────────────────────────────────────────────────
        self.protocol("WM_DELETE_WINDOW", self.quit_game)
        self._maximized = False
        self._install_resize_grips()

    def _register_screens(self) -> None:
        for name, cls in self._SCREEN_MAP.items():
            self.screens[name] = cls(self._content, self)

    # ── Navigation ────────────────────────────────────────────────────────────

    def show(self, name: str) -> None:
        """Navigate to the named screen, pushing it onto the stack."""
        if name not in self.screens:
            self.message_bar.err(f"Unknown screen: '{name}'")
            return
        if self._stack:
            self.screens[self._stack[-1]].hide()
        if not self._stack or self._stack[-1] != name:
            self._stack.append(name)
        self.screens[name].show()
        self.status_bar.refresh()

    def goto(self, name: str) -> None:
        """
        Flat / hotkey navigation: jump directly to a screen, discarding any
        intermediate nav stack depth.  The resulting stack is always just
        ['main'] or ['main', name] so Back always returns to the main menu.
        This prevents screens from silently stacking up when the user uses
        keyboard shortcuts to jump between sections.
        """
        if name not in self.screens:
            self.message_bar.err(f"Unknown screen: '{name}'")
            return
        # Hide the currently-visible screen
        if self._stack:
            try:
                self.screens[self._stack[-1]].hide()
            except Exception:
                pass
        # Collapse the entire stack
        self._stack = []
        if name != "main":
            self._stack = ["main", name]
        else:
            self._stack = ["main"]
        self.screens[name].show()
        self.status_bar.refresh()

    def go_back(self) -> None:
        """Return to the previous screen."""
        if len(self._stack) <= 1:
            return
        self.screens[self._stack.pop()].hide()
        self.screens[self._stack[-1]].show()
        self.status_bar.refresh()

    def refresh(self) -> None:
        """Refresh status bar and currently visible screen."""
        self.status_bar.refresh()
        if self._stack:
            self.screens[self._stack[-1]].refresh()
        self._flush_achievements()

    def profit_flash(self, amount: float) -> None:
        """Trigger gold overlay animation if profit meets a threshold."""
        if amount >= 100:
            ProfitFlash.trigger(self, amount)

    def _flush_achievements(self) -> None:
        """Pop and display any queued achievement toasts."""
        for aid in list(self.game.ach_queue):
            ach = next((a for a in ACHIEVEMENTS if a["id"] == aid), None)
            if ach:
                AchievementToast(self, ach)
        self.game.ach_queue.clear()

    # ── Save / Quit ───────────────────────────────────────────────────────────

    def _quick_save(self) -> None:
        self.game.save_game(silent=True)
        self.message_bar.ok("Game saved.")

    def _minimize_window(self) -> None:
        """Minimize using Win32 SW_MINIMIZE (works with overrideredirect)."""
        if sys.platform == "win32":
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        else:
            self.iconify()

    def _toggle_maximize(self, btn: tk.Label) -> None:
        """Toggle between maximized (work area) and restored geometry."""
        if self._maximized:
            self.geometry(self._normal_geo)
            self._maximized = False
            btn.config(text="  □  ")
        else:
            self._normal_geo = self.geometry()
            if sys.platform == "win32":
                import ctypes
                class RECT(ctypes.Structure):
                    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                 ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
                rect = RECT()
                ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0)
                w = rect.right  - rect.left
                h = rect.bottom - rect.top
                self.geometry(f"{w}x{h}+{rect.left}+{rect.top}")
            else:
                sw = self.winfo_screenwidth()
                sh = self.winfo_screenheight()
                self.geometry(f"{sw}x{sh}+0+0")
            self._maximized = True
            btn.config(text="  ❐  ")

    def _install_resize_grips(self) -> None:
        """Place transparent resize-grip strips at all 8 window edges/corners."""
        E = _ResizeGrip._E
        C = E * 2
        placements = {
            "n":  dict(relx=0, rely=0, relwidth=1,  height=E,    anchor="nw"),
            "s":  dict(relx=0, rely=1, relwidth=1,  height=E,    anchor="sw"),
            "w":  dict(relx=0, rely=0, width=E,     relheight=1, anchor="nw"),
            "e":  dict(relx=1, rely=0, width=E,     relheight=1, anchor="ne"),
            "nw": dict(relx=0, rely=0, width=C,     height=C,    anchor="nw"),
            "ne": dict(relx=1, rely=0, width=C,     height=C,    anchor="ne"),
            "sw": dict(relx=0, rely=1, width=C,     height=C,    anchor="sw"),
            "se": dict(relx=1, rely=1, width=C,     height=C,    anchor="se"),
        }
        for side, kw in placements.items():
            grip = _ResizeGrip(self, side)
            grip.place(**kw)
            grip.lift()

    def quit_game(self) -> None:
        if ConfirmDialog(self, "Save before quitting?", "Quit").wait():
            self.game.save_game(silent=True)
        self.destroy()

    def _center_on_screen(self) -> None:
        """Centre the main window on the primary monitor (deferred so HWND is ready)."""
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = max(0, (sw - self.WIN_W) // 2)
        y  = max(0, (sh - self.WIN_H) // 2)
        self.geometry(f"{self.WIN_W}x{self.WIN_H}+{x}+{y}")

    def _set_appwindow(self) -> None:
        """
        Apply WS_EX_APPWINDOW extended style so the borderless window
        still shows in the Windows taskbar and can be minimised via it.
        """
        import ctypes
        GWL_EXSTYLE      = -20
        WS_EX_APPWINDOW  = 0x00040000
        WS_EX_TOOLWINDOW = 0x00000080
        hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
        if hwnd:
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            # Refresh style without hiding the window
            SWP_NOMOVE      = 0x0002
            SWP_NOSIZE      = 0x0001
            SWP_NOZORDER    = 0x0004
            SWP_NOACTIVATE  = 0x0010
            SWP_FRAMECHANGED = 0x0020
            ctypes.windll.user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
            )

    # ── Entry point ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Run the startup flow then hand control to the tkinter event loop."""
        # Defer _startup so the window is fully mapped before dialogs grab focus
        self.after(1, self._startup)
        self.mainloop()

    def _startup(self) -> None:
        """
        New game / load game flow — mirrors the CLI play() preamble
        but uses dialog boxes instead of input() / print().
        """
        is_new_game = True

        if os.path.exists(Game.SAVE_FILE):
            if ConfirmDialog(self, "Save file found. Load game?",
                             "Welcome").wait():
                if self.game.load_game():
                    self.message_bar.ok(
                        f"Welcome back, {self.game.player_name}!")
                    is_new_game = False
                else:
                    name = InputDialog(self, "Enter your merchant name:",
                                       "New Game", "Merchant").wait()
                    self.game.player_name = name or "Merchant"
            else:
                name = InputDialog(self, "Enter your merchant name:",
                                   "New Game", "Merchant").wait()
                self.game.player_name = name or "Merchant"
        else:
            name = InputDialog(self, "Enter your merchant name:",
                               "New Game", "Merchant").wait()
            self.game.player_name = name or "Merchant"

        self.show("main")

        if is_new_game:
            # Defer slightly so the main screen finishes rendering first
            self.after(120, self._offer_tutorial)

    def _offer_tutorial(self) -> None:
        """Ask new players if they want the tutorial, then show it."""
        if ConfirmDialog(
            self,
            f"Welcome, {self.game.player_name}!\n\n"
            "Would you like a quick tutorial to get started?",
            "New Merchant",
        ).wait():
            TutorialDialog(self).wait()

    # ── Focus / entry guard ───────────────────────────────────────────────────

    def _is_entry_focused(self) -> bool:
        """Return True if a text-entry widget currently holds keyboard focus."""
        w = self.focus_get()
        if w is None:
            return False
        return isinstance(w, (tk.Entry, tk.Text, ttk.Entry,
                               ttk.Combobox, ttk.Spinbox))

    def _on_escape(self, event: tk.Event) -> None:
        """Global Escape handler — go back unless a dialog or entry has focus."""
        try:
            if event.widget.winfo_toplevel() is not self:
                return   # A Toplevel dialog has focus — let it handle Escape
        except Exception:
            return
        if self._is_entry_focused():
            return
        self.go_back()

    # ── Hotkey system ─────────────────────────────────────────────────────────

    def _dispatch_hotkey(self, event: tk.Event) -> None:
        """Kept for compatibility — actual dispatch is done by bind_all per-sequence."""
        pass

    def _setup_hotkeys(self) -> None:
        """
        Bind each hotkey directly as a named Tkinter event sequence so Tkinter
        handles all modifier logic. Safe to call any time hotkeys change.
        """
        # Unbind only the sequences we previously registered
        for seq in getattr(self, "_registered_hk_seqs", set()):
            try:
                self.unbind_all(f"<{seq}>")
            except Exception:
                pass
        self._registered_hk_seqs = set()

        _NAV = {
            "trade": "trade", "travel": "travel", "inventory": "inventory",
            "wait": "wait", "businesses": "businesses", "finance": "finance",
            "contracts": "contracts", "market": "market", "news": "news",
            "progress": "progress", "skills": "skills", "help": "help",
            "settings": "settings",
        }

        def _guard(action: str):
            """Wrap a hotkey action; bail out if a dialog or entry has focus."""
            _ENTRY_TYPES = (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox, ttk.Spinbox)
            def _handler(event: tk.Event) -> None:
                try:
                    if event.widget.winfo_toplevel() is not self:
                        return
                except Exception:
                    return
                # Check the ORIGINAL focused widget (event.widget), not focus_get().
                # For Tab, the class-level focus-traversal binding has already moved
                # focus to the next widget by the time bind_all fires, so focus_get()
                # would return the wrong widget and could block navigation incorrectly.
                try:
                    if isinstance(event.widget, _ENTRY_TYPES):
                        return
                except Exception:
                    return
                if action in _NAV:
                    # Defer via after_idle so no widget pack/forget happens
                    # while we are still inside the event-handler call stack.
                    self.after_idle(lambda a=action: self.goto(_NAV[a]))
                elif action == "save":
                    self._quick_save()
            return _handler

        for action, binding in self.game.settings.hotkeys.items():
            if not binding:
                continue
            # Tab cannot be reliably overridden — Tkinter's focus traversal
            # class binding always wins regardless of bind_all priority.
            if binding.lower() == "tab":
                continue
            try:
                self.bind_all(f"<{binding}>", _guard(action))
                self._registered_hk_seqs.add(binding)
            except Exception:
                pass

    # ── UI Scale ──────────────────────────────────────────────────────────────

    def apply_scale(self, scale: float) -> None:
        """
        Rescale all fonts, re-apply the TTK theme, then rebuild every
        screen so new font sizes take effect immediately.
        The full navigation stack is preserved so Back still works.
        """
        scale = max(0.75, min(2.0, round(scale * 4) / 4))
        if abs(scale - _UI_SCALE) < 0.01:
            return
        _rescale_fonts(scale)
        apply_dark_theme(ttk.Style(self))
        self.game.settings.ui_scale = scale
        self.game.settings.save()
        # Snapshot the complete nav stack before destroying screens
        saved_stack = list(self._stack) if self._stack else ["main"]
        for sc in list(self.screens.values()):
            try:
                sc.destroy()
            except Exception:
                pass
        self.screens = {}
        self._stack  = []
        self._register_screens()
        # Restore every level of the previous stack (filters stale names)
        for name in saved_stack:
            if name in self.screens:
                self._stack.append(name)
        if not self._stack:
            self._stack = ["main"]
        # Show the top-most screen without pushing it again
        self.screens[self._stack[-1]].show()
        self.status_bar.refresh()

    def _on_ctrl_scroll(self, event: tk.Event) -> None:
        """Ctrl+Scroll — zoom in (up) or out (down) by 0.25 steps."""
        delta = 0.25 if event.delta > 0 else -0.25
        new_scale = max(0.75, min(2.0, round((_UI_SCALE + delta) * 4) / 4))
        self.apply_scale(new_scale)

    # ── Bankruptcy restart ────────────────────────────────────────────────────

    def _do_bankruptcy_restart(self) -> None:
        """Wipe save file, create a fresh Game, prompt for a name, skip tutorial."""
        import os as _os
        try:
            if _os.path.exists(Game.SAVE_FILE):
                _os.remove(Game.SAVE_FILE)
        except Exception:
            pass
        # Rebuild game model
        self.game = Game()
        self.status_bar.game = self.game
        self.status_bar.refresh()
        # Re-wire each existing screen to the new game instance
        for sc in self.screens.values():
            sc.game = self.game
        # Ask for a name then go straight to main (no tutorial)
        name = InputDialog(self, "Enter your merchant name:",
                           "Fresh Start", "Merchant").wait()
        self.game.player_name = name or "Merchant"
        # Clear nav stack and show main menu
        self._stack = []
        self.show("main")
        self.message_bar.ok(
            f"Starting fresh, {self.game.player_name}. Good luck!")


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    app = GameApp()
    app.start()
