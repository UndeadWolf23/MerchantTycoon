"""
╔══════════════════════════════════════════════════════════╗
║            MERCHANT TYCOON  ─  EXPANDED EDITION          ║
╚══════════════════════════════════════════════════════════╝
A deep trading / business-management simulation.

Controls  ─ navigate every menu by typing the number shown.
Goal      ─ accumulate wealth through trade, business, and cunning.
"""

import random
import json
import os
import sys
import time
import base64
import zlib

# Ensure Unicode output works on Windows terminals
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import math
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
from enum import Enum
from copy import deepcopy
from collections import deque

# ─────────────────────────────────────────────────────────────────────────────
# USER DATA DIRECTORY  —  AppData/Roaming on Windows, ~/.config elsewhere
# ─────────────────────────────────────────────────────────────────────────────

def _get_user_data_dir() -> str:
    """Return (and create if needed) the persistent data folder for this game."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.join(os.path.expanduser("~"), ".config")
    folder = os.path.join(base, "MerchantTycoon")
    os.makedirs(folder, exist_ok=True)
    return folder

_USER_DATA_DIR: str = _get_user_data_dir()

# ─────────────────────────────────────────────────────────────────────────────
# COLOUR HELPERS (works on Windows 10+ with ANSI enabled, graceful fallback)
# ─────────────────────────────────────────────────────────────────────────────
try:
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
except Exception:
    pass

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"
GREY   = "\033[90m"

def c(text: str, colour: str) -> str:
    return f"{colour}{text}{RESET}"

def header(text: str) -> str:
    line = "─" * 60
    return f"\n{BOLD}{CYAN}{line}\n  {text}\n{line}{RESET}"

def warn(text: str):
    print(c(f"  ⚠  {text}", YELLOW))

def err(text: str):
    print(c(f"  ✗  {text}", RED))

def ok(text: str):
    print(c(f"  ✓  {text}", GREEN))

def prompt(text: str) -> str:
    return input(f"{BOLD}{WHITE}  › {text}{RESET}").strip()

def pause():
    input(c("  [Press Enter to continue]", GREY))

# ─────────────────────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────────────────────

class Season(Enum):
    SPRING = "Spring"
    SUMMER = "Summer"
    AUTUMN = "Autumn"
    WINTER = "Winter"

class Area(Enum):
    CITY        = "Capital City"
    FARMLAND    = "Farmlands"
    MOUNTAIN    = "Mountain Peaks"
    COAST       = "Coastal Harbor"
    FOREST      = "Deep Forest"
    DESERT      = "Sand Desert"
    SWAMP       = "Misty Swamp"
    TUNDRA      = "Frozen Tundra"

class ItemCategory(Enum):
    RAW_MATERIAL = "Raw Material"
    FOOD         = "Food & Drink"
    PROCESSED    = "Processed Goods"
    LUXURY       = "Luxury Goods"
    CONTRABAND   = "Contraband"
    EQUIPMENT    = "Equipment"

class EventType(Enum):
    DROUGHT        = "Drought"
    FLOOD          = "Flood"
    BUMPER_HARVEST = "Bumper Harvest"
    MINE_COLLAPSE  = "Mine Collapse"
    PIRACY         = "Piracy Surge"
    TRADE_BOOM     = "Trade Boom"
    PLAGUE         = "Plague"
    WAR            = "Border War"
    GOLD_RUSH      = "Gold Rush"
    FESTIVAL       = "Grand Festival"

class SkillType(Enum):
    TRADING     = "Trading"
    HAGGLING    = "Haggling"
    LOGISTICS   = "Logistics"
    INDUSTRY    = "Industry"
    ESPIONAGE   = "Espionage"
    BANKING     = "Banking"

# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Item:
    key: str
    name: str
    base_price: float
    category: ItemCategory
    rarity: str = "common"          # common / uncommon / rare / legendary
    weight: float = 1.0             # affects caravan capacity
    illegal: bool = False           # contraband items
    seasonal_bonus: Optional[Season] = None   # season where demand spikes
    area_produced: Optional[List[str]] = None # areas that naturally produce this
    description: str = ""

@dataclass
class PricePoint:
    day: int
    price: float

@dataclass
class Contract:
    id: int
    item_key: str
    quantity: int
    price_per_unit: float
    destination: Area
    deadline_day: int
    reward_bonus: float = 0.0
    penalty: float = 0.0
    fulfilled: bool = False

@dataclass
class LoanRecord:
    principal: float
    interest_rate: float    # per month
    months_remaining: int
    monthly_payment: float

@dataclass
class CDRecord:
    principal: float
    rate: float         # total flat return applied at maturity (e.g. 0.16 = 16%)
    maturity_day: int   # _absolute_day() value when this matures
    term_days: int      # for display only

# ─────────────────────────────────────────────────────────────────────────────
# DEFAULT HOTKEYS  —  canonical keybinding map; stored / merged in settings.json
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_HOTKEYS: Dict[str, str] = {
    "trade":      "t",
    "travel":     "v",
    "inventory":  "i",
    "wait":       "w",
    "businesses": "b",
    "finance":    "f",
    "contracts":  "c",
    "market":     "m",
    "news":       "n",
    "progress":   "p",
    "skills":     "k",
    "help":       "h",
    "settings":   "F10",
    "save":       "Control-s",
    "voyage":     "g",
}

@dataclass
class GameSettings:
    difficulty:    str   = "normal"  # "easy" / "normal" / "hard" / "brutal"
    autosave:      bool  = True      # autosave every in-game day
    ui_scale:      float = 1.0       # display / font scale (0.75 – 2.0)
    music_volume:  float = 0.5       # 0.0 – 1.0
    sfx_volume:    float = 0.7       # 0.0 – 1.0
    music_enabled: bool  = True
    profit_flash:          bool  = True      # golden flash on large earnings
    double_click_action:   bool  = True      # double-click table rows to perform primary action
    right_click_haggle:    bool  = True      # right-click buy table item to haggle
    enable_signatures:     bool  = True      # show parchment signing dialog for licenses/loans/etc.
    gamble_mercy:          int   = 0           # mercy counter: at 15 the next coffer roll excludes commons
    hotkeys:               Dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_HOTKEYS)
    )

    # Derived difficulty multipliers ──────────────────────────────────────────
    @property
    def cost_mult(self) -> float:
        """Multiplier on all outgoing costs (living, travel, wages, upkeep)."""
        return {"easy": 0.70, "normal": 1.0, "hard": 1.35, "brutal": 1.80}[self.difficulty]

    @property
    def price_sell_mult(self) -> float:
        """Multiplier on sell prices received (harder = less for you)."""
        return {"easy": 1.10, "normal": 1.0, "hard": 0.90, "brutal": 0.80}[self.difficulty]

    @property
    def event_freq_mult(self) -> float:
        """Multiplier on random event frequency."""
        return {"easy": 0.60, "normal": 1.0, "hard": 1.40, "brutal": 2.00}[self.difficulty]

    @property
    def attack_mult(self) -> float:
        """Multiplier on travel attack/incident probability."""
        return {"easy": 0.50, "normal": 1.0, "hard": 1.50, "brutal": 2.50}[self.difficulty]

    SETTINGS_FILE: str = os.path.join(_USER_DATA_DIR, "settings.json")

    def save(self):
        with open(self.SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "difficulty":    self.difficulty,
                "autosave":      self.autosave,
                "ui_scale":      self.ui_scale,
                "music_volume":  self.music_volume,
                "sfx_volume":    self.sfx_volume,
                "music_enabled": self.music_enabled,
                "profit_flash":         self.profit_flash,
                "double_click_action":   self.double_click_action,
                "right_click_haggle":    self.right_click_haggle,
                "enable_signatures":     self.enable_signatures,
                "hotkeys":               self.hotkeys,
            }, f)

    def load(self):
        if os.path.exists(self.SETTINGS_FILE):
            try:
                with open(self.SETTINGS_FILE, encoding="utf-8") as f:
                    d = json.load(f)
                self.difficulty    = d.get("difficulty",    "normal")
                self.autosave      = d.get("autosave",      True)
                self.ui_scale      = float(d.get("ui_scale",      1.0))
                self.music_volume  = float(d.get("music_volume",  0.5))
                self.sfx_volume    = float(d.get("sfx_volume",    0.7))
                self.music_enabled = bool(d.get("music_enabled",  True))
                self.profit_flash         = bool(d.get("profit_flash",         True))
                self.double_click_action  = bool(d.get("double_click_action",   True))
                self.right_click_haggle   = bool(d.get("right_click_haggle",    True))
                self.enable_signatures    = bool(d.get("enable_signatures",     True))
                # Merge saved hotkeys with defaults (new actions get default binding)
                raw_hk = d.get("hotkeys", {})
                if isinstance(raw_hk, dict):
                    merged = {
                        **DEFAULT_HOTKEYS,
                        **{k: v for k, v in raw_hk.items()
                           if isinstance(k, str) and isinstance(v, str)},
                    }
                    # Strip Tab from any action — it cannot be reliably
                    # intercepted due to Tkinter's focus-traversal class binding.
                    self.hotkeys = {
                        k: ("i" if v.lower() == "tab" and k == "inventory" else
                            "" if v.lower() == "tab" else v)
                        for k, v in merged.items()
                    }
            except Exception:
                pass

@dataclass
class Business:
    key: str
    name: str
    item_produced: str
    production_rate: float  # units/day at level 1
    daily_cost: float
    purchase_cost: float
    area: Area
    level: int = 1
    workers: int = 0
    max_workers: int = 5
    broken_down: bool = False
    repair_cost: float = 0.0
    days_owned: int = 0
    total_produced: int = 0
    hired_workers: List = field(default_factory=list)  # list of {name, wage, productivity}

    def daily_production(self) -> int:
        if self.broken_down or self.workers == 0:
            return 0   # no workers → no output
        # Average productivity across hired workers
        avg_prod = (sum(w["productivity"] for w in self.hired_workers) / self.workers
                    if self.hired_workers else 1.0)
        worker_bonus = 1.0 + ((self.workers - 1) * 0.15)  # 1 worker = base rate, each extra +15%
        # Diminishing returns per level: Lv1=1.0x, Lv2=1.6x, Lv3=2.2x, Lv4=2.8x …
        level_mult = 1.0 + (self.level - 1) * 0.6
        return int(self.production_rate * level_mult * worker_bonus * avg_prod)

    def worker_daily_wage(self) -> float:
        return sum(w["wage"] for w in self.hired_workers) if self.hired_workers else 0.0

@dataclass
class PlayerSkills:
    trading: int   = 1   # better buy/sell prices
    haggling: int  = 1   # chance to reduce price at purchase
    logistics: int = 1   # caravan carry weight
    industry: int  = 1   # business production bonus
    espionage: int = 1   # see hidden market info
    banking: int   = 1   # better interest rates, loan terms
    xp: Dict[str, int] = field(default_factory=lambda: {s.value: 0 for s in SkillType})

    def level_up_cost(self, skill: SkillType) -> int:
        current = getattr(self, skill.value.lower())
        return current * current * 150  # quadratic: Lv1→2=150g, Lv3→4=1350g, Lv5→6=3750g

    def try_level_up(self, skill: SkillType, gold: float) -> Tuple[bool, float]:
        cost = self.level_up_cost(skill)
        if gold < cost:
            return False, gold
        setattr(self, skill.value.lower(), getattr(self, skill.value.lower()) + 1)
        return True, gold - cost

# ─────────────────────────────────────────────────────────────────────────────
# PERMITS & LICENSES
# ─────────────────────────────────────────────────────────────────────────────

class LicenseType(Enum):
    MERCHANT    = "Merchant License"      # default — basic buy/sell
    BUSINESS    = "Business Permit"       # own / operate businesses
    LENDER      = "Lending Charter"       # lend money to citizens
    CONTRACTS   = "Trade Contract Seal"   # formal trade contracts
    FUND_MGR    = "Fund Manager License"  # manage private funds; stock market
    REAL_ESTATE = "Real Estate Charter"   # buy/sell/develop land and property
    VOYAGE      = "Voyage Charter"        # buy ships and send international cargo

class PropertyType(Enum):
    PLOT      = "Vacant Land Plot"
    COTTAGE   = "Cottage"
    TOWNHOUSE = "Townhouse"
    SHOP      = "Shop"
    WAREHOUSE = "Warehouse"
    INN       = "Inn"
    WORKSHOP  = "Workshop"
    MANOR     = "Manor House"
    DOCKYARD  = "Dockyard"
    ESTATE    = "Grand Estate"

LICENSE_INFO: Dict = {
    LicenseType.MERCHANT:  {
        "cost": 0,    "rep": 0,  "banking": 0,
        "desc": "Basic trading rights — granted to all new merchants.",
        "unlocks": "Buy and sell goods at any market.",
        "tier": "starter",
    },
    LicenseType.BUSINESS:  {
        "cost": 150,  "rep": 10, "banking": 0,
        "desc": "Grants the right to purchase and operate businesses.",
        "unlocks": "Access the Manage Businesses menu and buy any listed business.",
        "tier": "basic",
    },
    LicenseType.CONTRACTS: {
        "cost": 200,  "rep": 15, "banking": 0,
        "desc": "Official seal for taking on formal delivery contracts.",
        "unlocks": "Accept delivery contracts and earn bonuses for on-time completion.",
        "tier": "basic",
    },
    LicenseType.LENDER:    {
        "cost": 600,  "rep": 40, "banking": 1,
        "desc": "Authorises you to lend money directly to citizens.",
        "unlocks": "Issue citizen loans and collect weekly interest payments.",
        "tier": "advanced",
    },
    LicenseType.FUND_MGR:  {
        "cost": 2000, "rep": 60, "banking": 3,
        "desc": "Qualifies you to manage private investment funds and trade stocks.",
        "unlocks": "Access the Stock Exchange and accept fund management clients.",
        "tier": "elite",
    },
    LicenseType.REAL_ESTATE: {
        "cost": 1500, "rep": 55, "banking": 2,
        "desc": "Grants the right to purchase, develop, and lease real estate and land.",
        "unlocks": "Browse property listings, buy land plots, construct buildings, repair & flip properties, and earn lease income.",
        "tier": "elite",
    },
    LicenseType.VOYAGE: {
        "cost": 3000, "rep": 100, "banking": 0,
        "desc": "A royal charter authorising you to outfit ships for international trade voyages.",
        "unlocks": "Buy ships, hire captains, load cargo, and send voyages to distant ports for massive profits.",
        "tier": "elite",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# REAL ESTATE DATA  —  Property classes, catalogues, and area value tables
# ─────────────────────────────────────────────────────────────────────────────

# Area property value multipliers (how desirable / expensive an area is)
AREA_PROPERTY_MULT: Dict[str, float] = {
    "CITY":     2.5,
    "COAST":    1.8,
    "MOUNTAIN": 1.3,
    "FARMLAND": 1.1,
    "FOREST":   0.9,
    "DESERT":   0.85,
    "SWAMP":    0.65,
    "TUNDRA":   0.70,
}

# Property catalogue: base_value is the fully pristine value at area_mult = 1.0
PROPERTY_CATALOGUE: Dict[str, Dict] = {
    "cottage":   {"name": "Cottage",      "type": PropertyType.COTTAGE,   "base_value":  800, "base_lease":  2, "build_days": 20, "build_cost":  380, "areas": None},
    "townhouse": {"name": "Townhouse",    "type": PropertyType.TOWNHOUSE, "base_value": 2000, "base_lease":  5, "build_days": 35, "build_cost":  900, "areas": None},
    "shop":      {"name": "Shop",         "type": PropertyType.SHOP,      "base_value": 1800, "base_lease":  6, "build_days": 28, "build_cost":  820, "areas": None},
    "warehouse": {"name": "Warehouse",    "type": PropertyType.WAREHOUSE, "base_value": 3000, "base_lease":  9, "build_days": 40, "build_cost": 1200, "areas": None},
    "inn":       {"name": "Inn",          "type": PropertyType.INN,       "base_value": 3500, "base_lease": 11, "build_days": 45, "build_cost": 1400, "areas": None},
    "workshop":  {"name": "Workshop",     "type": PropertyType.WORKSHOP,  "base_value": 2500, "base_lease":  8, "build_days": 35, "build_cost": 1000, "areas": None},
    "manor":     {"name": "Manor House",  "type": PropertyType.MANOR,     "base_value": 6000, "base_lease": 18, "build_days": 55, "build_cost": 2400, "areas": None},
    "dockyard":  {"name": "Dockyard",     "type": PropertyType.DOCKYARD,  "base_value": 5000, "base_lease": 16, "build_days": 50, "build_cost": 2000, "areas": ["COAST"]},
    "estate":    {"name": "Grand Estate", "type": PropertyType.ESTATE,    "base_value":15000, "base_lease": 45, "build_days": 90, "build_cost": 9000, "areas": ["CITY", "COAST", "MOUNTAIN"]},
}

# Land plot sizes — each size restricts what can be built on it
LAND_PLOT_SIZES: Dict[str, Dict] = {
    "small":  {"label": "Small Plot",  "base_cost": 200, "max_build": {"cottage", "shop", "workshop"}},
    "medium": {"label": "Medium Plot", "base_cost": 450, "max_build": {"cottage", "townhouse", "shop", "warehouse", "workshop", "inn"}},
    "large":  {"label": "Large Plot",  "base_cost": 800, "max_build": {"cottage", "townhouse", "shop", "warehouse", "workshop", "inn", "manor", "dockyard", "estate"}},
}

# Property upgrades: fractions are of current_value (base_value × area_mult)
PROPERTY_UPGRADES: Dict[str, Dict] = {
    "fortified_walls":   {"cost_frac": 0.06, "value_frac": 0.10, "lease_frac": 0.00, "desc": "Reinforced stone walls improve structural integrity."},
    "master_carpentry":  {"cost_frac": 0.05, "value_frac": 0.08, "lease_frac": 0.04, "desc": "Quality woodwork throughout raises appeal."},
    "stone_facade":      {"cost_frac": 0.08, "value_frac": 0.12, "lease_frac": 0.05, "desc": "Prestigious stone exterior commands premium rents."},
    "private_garden":    {"cost_frac": 0.04, "value_frac": 0.07, "lease_frac": 0.06, "desc": "An enclosed garden is highly desirable to tenants."},
    "wine_cellar":       {"cost_frac": 0.05, "value_frac": 0.08, "lease_frac": 0.07, "desc": "Underground cellar for storage; tenants pay more."},
    "ornate_gates":      {"cost_frac": 0.06, "value_frac": 0.09, "lease_frac": 0.02, "desc": "Decorative iron-wrought gates signal wealth."},
    "servants_quarters": {"cost_frac": 0.07, "value_frac": 0.09, "lease_frac": 0.10, "desc": "Dedicated staff rooms greatly improve lease value."},
    "trading_hall":      {"cost_frac": 0.10, "value_frac": 0.15, "lease_frac": 0.12, "desc": "A built-in commerce hall; ideal for commercial tenants."},
}

# Property name pools for procedurally generated listings
_PROP_NAMES: Dict[str, List[str]] = {
    "cottage":   ["The Old Stonehouse","Miller's Cottage","The Dove Cottage","Thatcher's Rest",
                  "The Mossy Eaves","Hedgerow Cottage","Fenwick Cottage","The Crofter's Nook"],
    "townhouse": ["Irongate Townhouse","The Merchant's Terrace","Alderholt House","Copperfield Row",
                  "The Guild Quarter Townhouse","Briarwood Townhouse","Saltholm House","The Weaver's Row"],
    "shop":      ["The Corner Shop","The Trading Post","Saltmarsh Shoppe","The Old Exchange",
                  "Pilgrim's Emporium","The Market Stall","Quartermaster's Shop","The Bursar's Counter"],
    "warehouse": ["The River Warehouse","The Stone Vault","Dockside Storage","Merchant's Depot",
                  "The Grain Loft","The Old Counting House","The East Warehouse","The Sealed Vault"],
    "inn":       ["The Rusty Anchor","The Crossed Keys","The Boatswain's Rest","The Golden Plough",
                  "The Wayfarer's Inn","The Howling Wolf","The Toll Road Inn","The Silver Chalice"],
    "workshop":  ["The Old Forge","Ironside's Workshop","The Bellows","Coppercraft Workshop",
                  "The Journeyman's Hall","The Tallow Works","The Artisan's Guild","The Tinker's Den"],
    "manor":     ["Aldermoor Manor","The Grey Towers","Brokenford Hall","Blackthorn Manor",
                  "Westmarch House","The Merchant's Hall","Dunmore Manor","Ashenvale House"],
    "dockyard":  ["The Old Dockyards","Salter's Wharf","The Harbour Works","The Chandler's Dock",
                  "Ironkeel Yard","The Sea Gate Yards","The Mariner's Dock","Northport Quays"],
    "estate":    ["The Grand Estate","Oldstead Hall","Whitmore Estate","Ashgrove Park",
                  "The Duke's Seat","The Merchant Prince's Court","Thornbury Estate","The Citadel House"],
}

# Condition tiers: label, fraction, flavour text
CONDITION_TIERS = [
    (0.20, "Derelict",  "Barely standing — major structural damage throughout."),
    (0.45, "Poor",      "Significant wear; needs substantial repairs before use."),
    (0.65, "Fair",      "Functional but showing age; cosmetic and moderate repairs needed."),
    (0.82, "Good",      "Well-maintained with minor deficiencies."),
    (1.00, "Pristine",  "Excellent condition — move-in ready with no issues."),
]

def condition_label(cond: float) -> Tuple[str, str]:
    """Return (tier_label, flavour_text) for a 0.0–1.0 condition value."""
    for frac, label, text in CONDITION_TIERS:
        if cond <= frac + 0.01:
            return label, text
    return "Pristine", CONDITION_TIERS[-1][2]

# ─────────────────────────────────────────────────────────────────────────────
# REAL ESTATE DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Property:
    id: int
    prop_type: str          # key into PROPERTY_CATALOGUE
    name: str               # procedural name, e.g. "The Rusty Anchor Inn"
    area: Area
    condition: float        # 0.0 (ruined) to 1.0 (pristine)
    base_value: float       # pristine value at area_mult = 1.0
    area_mult: float        # frozen at purchase time
    is_leased: bool = False
    days_owned: int = 0
    upgrades: List[str] = field(default_factory=list)
    under_construction: bool = False
    construction_days_left: int = 0
    total_lease_income: float = 0.0
    purchase_price_paid: float = 0.0  # what the player actually paid
    tenant_name: str = ""             # name of current tenant, or '' if unleased
    lease_rate_mult: float = 1.0      # tenant's negotiated rate vs standard

    @property
    def current_value(self) -> float:
        """Pristine value at current area, adjusted for condition and upgrades."""
        base = self.base_value * self.area_mult
        cond_adj = base * self.condition
        upgrade_add = sum(
            base * PROPERTY_UPGRADES[u]["value_frac"]
            for u in self.upgrades if u in PROPERTY_UPGRADES
        )
        return round(cond_adj + upgrade_add, 2)

    @property
    def daily_lease(self) -> float:
        """Gold per day when leased (scaled by condition + upgrades + tenant rate)."""
        cat = PROPERTY_CATALOGUE.get(self.prop_type, {})
        base_lease = cat.get("base_lease", 0) * self.area_mult * self.condition
        upgrade_bonus = sum(
            (cat.get("base_lease", 0) * self.area_mult) * PROPERTY_UPGRADES[u]["lease_frac"]
            for u in self.upgrades if u in PROPERTY_UPGRADES
        )
        return round((base_lease + upgrade_bonus) * self.lease_rate_mult, 2)

    @property
    def repair_cost(self) -> float:
        """Cost to bring property from current condition to pristine."""
        pristine_val = self.base_value * self.area_mult
        return round(pristine_val * (1.0 - self.condition) * 0.38, 2)

@dataclass
class LandPlot:
    id: int
    area: Area
    size: str               # "small", "medium", "large"
    purchase_price: float
    build_project: str = ""          # catalogue key of active build project
    build_days_left: int = 0
    build_cost_paid: float = 0.0     # gold spent on construction

# ─────────────────────────────────────────────────────────────────────────────
# CITIZEN LENDING
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CitizenLoan:
    id: int
    borrower_name: str
    principal: float
    interest_rate: float        # per week (e.g. 0.04 = 4%/week)
    weeks_remaining: int
    weekly_payment: float
    total_received: float = 0.0
    defaulted: bool = False
    creditworthiness: float = 1.0   # 0.5 = risky, 1.5 = very safe

# ─────────────────────────────────────────────────────────────────────────────
# BUSINESS MANAGER
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BusinessManagerRecord:
    name: str
    wage_per_week: float
    days_employed: int = 0
    total_repairs: int = 0
    total_hires: int = 0
    total_sold_value: float = 0.0
    auto_sell: bool = True
    auto_repair: bool = True
    auto_hire: bool = True

# ─────────────────────────────────────────────────────────────────────────────
# NPC MANAGER SYSTEM
# Each HiredManager automates a domain of the game.  Managers level 1-5;
# higher levels are more efficient, make fewer mistakes, and understand
# economy fluctuations better.  They earn XP from successful actions.
# ─────────────────────────────────────────────────────────────────────────────

class ManagerType(Enum):
    BUSINESS_FOREMAN    = "Business Foreman"      # repairs, hires, manages production
    TRADE_STEWARD       = "Trade Steward"          # scans markets, sells inventory smartly
    PROPERTY_STEWARD    = "Property Steward"       # manages tenants, repairs, leases
    CONTRACT_AGENT      = "Contract Agent"         # accepts & fulfills delivery contracts
    LENDING_ADVISOR     = "Lending Advisor"        # vets & issues citizen loans, manages defaults
    INVESTMENT_BROKER   = "Investment Broker"      # buys / sells stocks intelligently
    FUND_CUSTODIAN      = "Fund Custodian"         # manages investment fund clients
    CAMPAIGN_HANDLER    = "Campaign Handler"       # runs market influence campaigns
    SMUGGLING_HANDLER   = "Smuggling Handler"      # manages contraband operations

# XP thresholds to reach each level (cumulative from L1)
MANAGER_XP_THRESHOLDS: List[int] = [0, 50, 150, 350, 750]   # L1 base, L1→L2, L2→L3, L3→L4, L4→L5

# Per-level efficiency multipliers (affects quality and profit of decisions)
MANAGER_EFFICIENCY: Dict[int, float] = {1: 0.65, 2: 0.76, 3: 0.86, 4: 0.93, 5: 0.98}

# Per manager-type definition: base weekly wage, required license, description, icon
MANAGER_DEFS: Dict[str, Dict] = {
    ManagerType.BUSINESS_FOREMAN: {
        "icon": "🔧", "wage": 25.0, "license": LicenseType.BUSINESS,
        "desc": "Maintains your businesses — repairs breakdowns, hires workers, and handles daily operations.",
        "detail": "At Lv1 makes decent hires and eventually repairs breakdowns. At Lv5 optimally staffs all businesses and prevents most failures.",
    },
    ManagerType.TRADE_STEWARD: {
        "icon": "⚖", "wage": 30.0, "license": LicenseType.MERCHANT,
        "desc": "Sells accumulated inventory at market — finds decent prices and clears excess stock.",
        "detail": "At Lv1 sells at your current area for 70% of best price. At Lv5 identifies optimal routes and achieves 98% of peak value.",
    },
    ManagerType.PROPERTY_STEWARD: {
        "icon": "🏠", "wage": 35.0, "license": LicenseType.REAL_ESTATE,
        "desc": "Manages your real estate — finds tenants, collects rent, and keeps properties maintained.",
        "detail": "At Lv1 may accept risky tenants and misses repair windows. At Lv5 screens tenants carefully and pre-empts condition decay.",
    },
    ManagerType.CONTRACT_AGENT: {
        "icon": "📜", "wage": 40.0, "license": LicenseType.CONTRACTS,
        "desc": "Monitors contracts and fulfills deliveries — accepts good orders and delivers on time.",
        "detail": "At Lv1 may accept contracts with thin margins. At Lv5 only accepts profitable orders and fulfills them efficiently.",
    },
    ManagerType.LENDING_ADVISOR: {
        "icon": "⊛", "wage": 45.0, "license": LicenseType.LENDER,
        "desc": "Manages your citizen lending — vets borrowers, issues loans, and monitors repayments.",
        "detail": "At Lv1 lends to average-risk citizens. At Lv5 only funds highly creditworthy borrowers at optimal rates.",
    },
    ManagerType.INVESTMENT_BROKER: {
        "icon": "📈", "wage": 50.0, "license": LicenseType.FUND_MGR,
        "desc": "Invests in the stock market on your behalf — reads trends and world events.",
        "detail": "At Lv1 follows simple momentum signals. At Lv5 anticipates event impacts and builds an optimal portfolio.",
    },
    ManagerType.FUND_CUSTODIAN: {
        "icon": "💰", "wage": 55.0, "license": LicenseType.FUND_MGR,
        "desc": "Handles your fund management clients — accepts capital and collects management fees.",
        "detail": "At Lv1 accepts any clients with modest rates. At Lv5 curates high-capital clients and maximises fee income.",
    },
    ManagerType.CAMPAIGN_HANDLER: {
        "icon": "⭐", "wage": 35.0, "license": LicenseType.MERCHANT,
        "desc": "Runs market influence campaigns and product promotions on your behalf.",
        "detail": "At Lv1 runs basic campaigns with modest gold returns. At Lv5 times campaigns perfectly around supply events for maximum impact.",
    },
    ManagerType.SMUGGLING_HANDLER: {
        "icon": "🦝", "wage": 60.0, "license": LicenseType.MERCHANT,
        "desc": "Manages contraband operations — buys and sells illegal goods while minimising heat.",
        "detail": "At Lv1 sticks to small conservative ops with average margins. At Lv5 runs sophisticated routes for maximum profit.",
    },
}

@dataclass
class HiredManager:
    manager_type: str       # ManagerType.value string for JSON serialisation
    name: str
    level: int = 1
    xp: int = 0
    days_employed: int = 0
    weekly_wage: float = 25.0
    is_active: bool = True
    # Configurable behaviour (type-specific keys; stored as free dict)
    config: Dict = field(default_factory=dict)
    # Lifetime stats for this manager
    stats: Dict = field(default_factory=lambda: {
        "total_actions":        0,
        "total_gold_generated": 0.0,
        "total_wages_paid":    0.0,   # actual wages deducted
        "total_gold_cost":      0.0,   # operational gold spent (buys, repairs, etc.)
        "mistakes":             0,
        "level_ups":            0,
        "last_action_day":      0,
        "last_action_desc":     "",
    })

    # ── XP / levelling helpers ──────────────────────────────────────────────

    def xp_to_next(self) -> int:
        """XP needed to reach the next level (0 if already Lv5)."""
        if self.level >= 5:
            return 0
        return MANAGER_XP_THRESHOLDS[self.level] - self.xp

    def add_xp(self, amount: int) -> bool:
        """Add XP; returns True if levelled up."""
        if self.level >= 5:
            return False
        self.xp += amount
        if self.xp >= MANAGER_XP_THRESHOLDS[self.level]:
            self.level += 1
            self.stats["level_ups"] += 1
            return True
        return False

    @property
    def efficiency(self) -> float:
        return MANAGER_EFFICIENCY.get(self.level, 0.65)

    def type_enum(self) -> "ManagerType":
        for mt in ManagerType:
            if mt.value == self.manager_type:
                return mt
        raise ValueError(self.manager_type)

# Default configs per manager type (applied when hiring)
_MANAGER_DEFAULT_CONFIGS: Dict[str, Dict] = {
    ManagerType.BUSINESS_FOREMAN.value: {
        "auto_repair":             True,    # repair broken-down businesses
        "auto_hire":               True,    # fill empty worker slots
        "repair_threshold":        500.0,   # skip repairs costing more than this
        "max_wage_per_worker":     8.0,     # don't hire workers asking more than this
        "auto_fire_lazy":          False,   # fire workers below productivity threshold
        "min_worker_productivity": 0.6,     # fire workers below this productivity
    },
    ManagerType.TRADE_STEWARD.value: {
        "sell_min_quantity":    1,      # minimum qty per item before selling
        "keep_quantity":        0,      # always keep at least this many of each item
        "sell_business_output": True,   # sell goods produced by your businesses
        "sell_purchased_goods": True,   # sell goods in inventory (tracked by cost basis)
        "auto_buy_for_resale":  False,  # buy cheap goods to resell later
        "max_buy_gold":         200.0,  # max gold to spend on resale buys per day
        "min_profit_pct":       0.08,   # minimum profit above cost before selling (8%)
        "patience_days":        5,      # days to hold waiting for target price
        "allow_travel":         False,  # steward travels independently to better markets
        "max_travel_days":      2,      # only consider routes up to this many days away
    },
    ManagerType.PROPERTY_STEWARD.value: {
        "auto_lease":                True,   # find and place tenants in empty properties
        "reject_risky_tenants":      False,  # skip low-creditworthiness tenants
        "auto_repair":               True,   # repair properties with low condition
        "min_condition_to_repair":   0.55,   # trigger repair below this condition
        "max_repair_cost":           1000.0, # skip single repairs costing more than this
        "auto_evict_low_condition":  False,  # evict tenant so repairs can proceed
        "evict_condition_threshold": 0.30,   # evict when condition drops below this
    },
    ManagerType.CONTRACT_AGENT.value: {
        "auto_fulfill":         True,   # deliver fulfilled contracts automatically
        "auto_procure":         True,   # buy missing items to fulfil contracts
        "min_profit_per_unit":  0.5,    # only act on contracts at this margin or better
        "max_deadline_days":    30,     # ignore contracts with deadlines beyond this
        "max_procure_gold":     300.0,  # max gold to spend procuring per contract
    },
    ManagerType.LENDING_ADVISOR.value: {
        "auto_issue":           True,
        "min_creditworthiness": 0.7,    # 0.5=risky  1.0=average  1.5=safe
        "max_loan_amount":      300.0,
        "max_active_loans":     5,
        "prefer_short_loans":   False,  # only accept loans ≤8 weeks duration
        "max_total_loaned":     1000.0, # cap on total outstanding principal
        "auto_write_off":       False,  # auto-clear defaulted loans from the ledger
    },
    ManagerType.INVESTMENT_BROKER.value: {
        "auto_buy":                 True,   # buy stocks when signals are positive
        "auto_sell":                True,   # sell stocks when take-profit/stop-loss hit
        "max_investment_per_stock": 200.0,
        "max_portfolio_value":      1000.0,
        "risk_tolerance":           0.5,    # 0=conservative  1=aggressive
        "min_gain_to_sell":         0.15,   # sell when gain % reaches this threshold
        "stop_loss_pct":            0.20,   # sell when loss % reaches this threshold
    },
    ManagerType.FUND_CUSTODIAN.value: {
        "auto_accept":        True,
        "max_clients":        4,
        "min_client_capital": 300.0,
        "min_fee_rate":       0.01,  # reject clients offering less than this fee rate
        "min_duration_days":  30,    # reject very short-term fund contracts
    },
    ManagerType.CAMPAIGN_HANDLER.value: {
        "campaign_frequency_days": 14,
        "preferred_area":          "CITY",
        "max_campaign_cost":       50.0,  # spending cap per campaign run
        "skip_if_last_loss":       False, # pause if the last campaign lost money
    },
    ManagerType.SMUGGLING_HANDLER.value: {
        "max_heat":              60,    # refuse to operate above this heat level
        "ops_frequency_days":    7,
        "max_bust_risk":         0.25,  # skip run if estimated bust chance exceeds this
        "min_net_profit":        0.0,   # skip run if expected net profit is below this
        "heat_pause_after_bust": True,  # rest 3 days after a bust before resuming
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# STOCK MARKET
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StockHolding:
    symbol: str
    shares: int
    avg_cost: float     # per share at purchase time

@dataclass
class FundClient:
    id: int
    name: str
    capital: float           # gold entrusted
    promised_rate: float     # e.g. 0.08 = 8% return promised at maturity
    start_day: int
    duration_days: int       # 30 / 60 / 90 day window
    maturity_day: int
    fee_rate: float          # management fee fraction per 30d (e.g. 0.025)
    withdrawn: bool = False
    fees_collected: float = 0.0

class StockMarket:
    """Live stock exchange — 10 companies whose prices move with the economy."""

    _DEFS = [
        # (sym, name, sector, base_price, volatility, shares_k,
        #  linked_items, linked_events {event_name: impact_fraction})
        ("IRON", "Ironvale Mining Corp",   "Mining",      45.0, 0.055,  800,
         ["ore", "steel", "coal"],
         {"MINE_COLLAPSE": -0.28, "WAR": 0.18, "GOLD_RUSH": 0.14, "TRADE_BOOM": 0.10}),
        ("WAVE", "Seaways Trading Co.",    "Maritime",    28.0, 0.050, 1200,
         ["fish", "salt", "rope", "blubber"],
         {"PIRACY": -0.22, "TRADE_BOOM": 0.16, "FLOOD": -0.09}),
        ("HARV", "Harvest Agricultural",  "Agriculture", 22.0, 0.070, 1500,
         ["wheat", "barley", "cotton", "bread"],
         {"DROUGHT": -0.32, "FLOOD": -0.18, "BUMPER_HARVEST": 0.14, "FESTIVAL": 0.07}),
        ("ALCH", "Alchemia Corp",          "Medicine",    65.0, 0.080,  500,
         ["medicine", "herbs"],
         {"PLAGUE": 0.38, "WAR": 0.14, "DROUGHT": 0.07}),
        ("LUXE", "Luxuria Holdings",       "Luxury",      80.0, 0.100,  400,
         ["silk", "spice", "jewelry", "tapestry", "wine"],
         {"FESTIVAL": 0.24, "PIRACY": -0.13, "WAR": -0.17, "TRADE_BOOM": 0.14}),
        ("TIMB", "Timberco Group",         "Lumber",      35.0, 0.048, 1000,
         ["timber", "wood", "rope"],
         {"FLOOD": -0.13, "DROUGHT": 0.05, "TRADE_BOOM": 0.11}),
        ("GLDV", "Goldvault Bank",         "Finance",    120.0, 0.038,  300,
         ["gold_dust", "gem"],
         {"GOLD_RUSH": 0.28, "WAR": -0.11, "TRADE_BOOM": 0.10, "PLAGUE": -0.08}),
        ("FURS", "Tundra Furs Ltd",        "Furs",        30.0, 0.090, 1100,
         ["fur", "leather", "blubber"],
         {"TRADE_BOOM": 0.10, "WAR": 0.07, "FESTIVAL": 0.08}),
        ("BREW", "Swampbrews & Co.",       "Brewing",     18.0, 0.060, 2000,
         ["ale", "wine", "barley"],
         {"FESTIVAL": 0.28, "DROUGHT": -0.20, "BUMPER_HARVEST": 0.14, "PLAGUE": -0.10}),
        ("GEMS", "Gemstone Exchange",      "Gems",        95.0, 0.090,  250,
         ["gem", "gold_dust", "jewelry"],
         {"MINE_COLLAPSE": -0.34, "GOLD_RUSH": 0.10, "FESTIVAL": 0.18, "WAR": -0.07}),
    ]

    def __init__(self):
        self.stocks: Dict[str, dict] = {}
        for sym, name, sector, bp, vol, shares_k, items, events in self._DEFS:
            noise = random.uniform(0.88, 1.12)
            init_price = round(bp * noise, 2)
            self.stocks[sym] = {
                "symbol": sym, "name": name, "sector": sector,
                "price": init_price, "base_price": bp, "volatility": vol,
                "shares": shares_k * 1000,
                "linked_items": items, "linked_events": events,
                "history": deque([init_price], maxlen=30),
            }
        self.day = 0

    def update(self, markets: dict, season: object):
        """Called once per in-game day to advance all prices."""
        self.day += 1
        for sd in self.stocks.values():
            drift = (sd["base_price"] - sd["price"]) / max(sd["base_price"], 1.0) * 0.025
            shock = random.gauss(0.0, sd["volatility"])
            item_signal = 0.0
            count = 0
            for mkt in markets.values():
                for item_key in sd["linked_items"]:
                    if item_key in mkt.pressure:
                        item_signal += (mkt.pressure[item_key] - 1.0) * 0.012
                        count += 1
            if count > 0:
                item_signal /= count
            new_price = sd["price"] * (1.0 + drift + shock + item_signal)
            sd["price"] = max(1.0, round(new_price, 2))
            sd["history"].append(sd["price"])

    def on_event(self, event: object):
        """Apply immediate event shock (60% of full impact) to linked stocks."""
        for sd in self.stocks.values():
            impact = sd["linked_events"].get(event.name, 0.0)
            if impact != 0.0:
                sd["price"] = max(1.0, round(sd["price"] * (1.0 + impact * 0.60), 2))
                sd["history"].append(sd["price"])

    def to_save(self) -> dict:
        return {sym: {"price": sd["price"], "history": list(sd["history"])}
                for sym, sd in self.stocks.items()}

    def from_save(self, data: dict):
        for sym, d in data.items():
            if sym in self.stocks:
                self.stocks[sym]["price"] = d.get("price", self.stocks[sym]["base_price"])
                self.stocks[sym]["history"] = deque(d.get("history", []), maxlen=30)

# ─────────────────────────────────────────────────────────────────────────────
# ACHIEVEMENTS  (100 total)
# Each dict:  id, name, tier, icon, hidden, hint, desc, check(game)->bool
# Tiers: "bronze" "silver" "gold" "platinum" ""
# ─────────────────────────────────────────────────────────────────────────────

ACHIEVEMENTS = [
    # ══ TRADING ══════════════════════════════════════════════════════════════
    {"id":"first_trade",        "tier":"bronze",   "icon":"⚙",  "hidden":False,
     "name":"First Steps",
     "hint":"Buy or sell anything at a market.",
     "desc":"Took your first step into the grand marketplace.",
     "check": lambda g: g.lifetime_trades >= 1},

    {"id":"trades_10",          "tier":"bronze",   "icon":"⚙",  "hidden":False,
     "name":"Market Regular",
     "hint":"Complete 10 trades (buys or sells).",
     "desc":"The merchants are starting to recognize your face.",
     "check": lambda g: g.lifetime_trades >= 10},

    {"id":"trades_100",         "tier":"silver",   "icon":"★",  "hidden":False,
     "name":"Market Veteran",
     "hint":"Complete 100 trades.",
     "desc":"You've worn a groove in the marketplace floor.",
     "check": lambda g: g.lifetime_trades >= 100},

    {"id":"trades_1000",        "tier":"gold",     "icon":"★",  "hidden":False,
     "name":"Trading Legend",
     "hint":"Complete 1,000 trades.",
     "desc":"Your name is synonymous with commerce.",
     "check": lambda g: g.lifetime_trades >= 1000},

    {"id":"first_profit",       "tier":"",         "icon":"◆",  "hidden":False,
     "name":"In the Black",
     "hint":"Earn your first profit on a sale.",
     "desc":"A penny earned is a penny... multiplied.",
     "check": lambda g: g.total_profit > 0},

    {"id":"profit_1k",          "tier":"bronze",   "icon":"◆",  "hidden":False,
     "name":"Money Talks",
     "hint":"Earn 1,000g total profit.",
     "desc":"Your ledger book is no longer embarrassing.",
     "check": lambda g: g.total_profit >= 1000},

    {"id":"profit_10k",         "tier":"silver",   "icon":"◆",  "hidden":False,
     "name":"Golden Touch",
     "hint":"Earn 10,000g total profit.",
     "desc":"Everything you touch turns to gold. Mostly.",
     "check": lambda g: g.total_profit >= 10000},

    {"id":"profit_100k",        "tier":"gold",     "icon":"◆",  "hidden":False,
     "name":"Midas Incarnate",
     "hint":"Earn 100,000g total profit.",
     "desc":"Entire kingdoms spend less than your monthly profit.",
     "check": lambda g: g.total_profit >= 100000},

    {"id":"profit_1m",          "tier":"platinum", "icon":"◆",  "hidden":True,
     "name":"The Golden Goose",
     "hint":"???",
     "desc":"1,000,000g profit. The realm bows to you.",
     "check": lambda g: g.total_profit >= 1000000},

    {"id":"big_sale",           "tier":"silver",   "icon":"⚡", "hidden":False,
     "name":"The Big Score",
     "hint":"Earn 1,000g in a single sale transaction.",
     "desc":"One deal to rule them all — at least, for now.",
     "check": lambda g: g.ach_stats.get("max_single_sale", 0) >= 1000},

    # ══ WEALTH ═══════════════════════════════════════════════════════════════
    {"id":"worth_1k",           "tier":"bronze",   "icon":"◎",  "hidden":False,
     "name":"A Thousand to My Name",
     "hint":"Reach 1,000g net worth.",
     "desc":"You could buy a small boat. Or a very large hat.",
     "check": lambda g: g._net_worth() >= 1000},

    {"id":"worth_5k",           "tier":"silver",   "icon":"◎",  "hidden":False,
     "name":"Man of Means",
     "hint":"Reach 5,000g net worth.",
     "desc":"You can afford things you don't need. Progress!",
     "check": lambda g: g._net_worth() >= 5000},

    {"id":"worth_25k",          "tier":"gold",     "icon":"◎",  "hidden":False,
     "name":"The Wealthy",
     "hint":"Reach 25,000g net worth.",
     "desc":"You genuinely do not know how many horses you own.",
     "check": lambda g: g._net_worth() >= 25000},

    {"id":"worth_100k",         "tier":"platinum", "icon":"◎",  "hidden":False,
     "name":"Plutocrat",
     "hint":"Reach 100,000g net worth.",
     "desc":"Economic force of nature. Governments write to you.",
     "check": lambda g: g._net_worth() >= 100000},

    {"id":"worth_500k",         "tier":"platinum", "icon":"◎",  "hidden":True,
     "name":"Financial Overlord",
     "hint":"???",
     "desc":"500,000g net worth. You are the economy.",
     "check": lambda g: g._net_worth() >= 500000},

    {"id":"bank_1k",            "tier":"bronze",   "icon":"◎",  "hidden":False,
     "name":"First Deposit",
     "hint":"Keep 1,000g in your bank account.",
     "desc":"The teller smiled when you walked in.",
     "check": lambda g: g.bank_balance >= 1000},

    {"id":"bank_10k",           "tier":"silver",   "icon":"◎",  "hidden":False,
     "name":"Vault Holder",
     "hint":"Keep 10,000g in the bank.",
     "desc":"The bank now offers you your own desk.",
     "check": lambda g: g.bank_balance >= 10000},

    {"id":"bank_50k",           "tier":"gold",     "icon":"◎",  "hidden":False,
     "name":"The Bank IS Me",
     "hint":"Keep 50,000g in the bank.",
     "desc":"You ARE the interest rate.",
     "check": lambda g: g.bank_balance >= 50000},

    # ══ BUSINESS ═════════════════════════════════════════════════════════════
    {"id":"first_business",     "tier":"bronze",   "icon":"⌂",  "hidden":False,
     "name":"Entrepreneur",
     "hint":"Purchase your first business.",
     "desc":"You are now, technically, a capitalist.",
     "check": lambda g: len(g.businesses) >= 1},

    {"id":"biz_3",              "tier":"silver",   "icon":"⌂",  "hidden":False,
     "name":"Business Baron",
     "hint":"Own 3 or more businesses simultaneously.",
     "desc":"Three enterprises — and only one of them is on fire.",
     "check": lambda g: len(g.businesses) >= 3},

    {"id":"biz_6",              "tier":"gold",     "icon":"⌂",  "hidden":False,
     "name":"Industrial Magnate",
     "hint":"Own 6 or more businesses simultaneously.",
     "desc":"You employ more people than some small villages.",
     "check": lambda g: len(g.businesses) >= 6},

    {"id":"biz_10",             "tier":"platinum", "icon":"⌂",  "hidden":True,
     "name":"Empire Builder",
     "hint":"???",
     "desc":"Ten businesses. The realm trembles at your payroll.",
     "check": lambda g: len(g.businesses) >= 10},

    {"id":"biz_upgrade",        "tier":"bronze",   "icon":"⌂",  "hidden":False,
     "name":"Level Up!",
     "hint":"Upgrade any business to level 2 or higher.",
     "desc":"Reinvestment is the soul of enterprise.",
     "check": lambda g: any(b.level >= 2 for b in g.businesses)},

    {"id":"biz_max_level",      "tier":"silver",   "icon":"⌂",  "hidden":False,
     "name":"Peak Performance",
     "hint":"Upgrade any business to maximum level (5).",
     "desc":"This establishment can go no higher. Or can it?",
     "check": lambda g: any(b.level >= 5 for b in g.businesses)},

    {"id":"biz_repair_5",       "tier":"bronze",   "icon":"⌂",  "hidden":False,
     "name":"Handyman",
     "hint":"Repair 5 broken businesses over your career.",
     "desc":"If it ain't broke... well, it was broke.",
     "check": lambda g: g.ach_stats.get("repairs", 0) >= 5},

    {"id":"biz_4areas",         "tier":"silver",   "icon":"⌂",  "hidden":False,
     "name":"Diversified Portfolio",
     "hint":"Own businesses in 4 different regions simultaneously.",
     "desc":"You have interests everywhere — literally.",
     "check": lambda g: len(set(b.area for b in g.businesses)) >= 4},

    {"id":"hire_manager",       "tier":"silver",   "icon":"⌂",  "hidden":False,
     "name":"Management Material",
     "hint":"Hire a business manager.",
     "desc":"Delegating. The true sign of a powerful merchant.",
     "check": lambda g: g.business_manager is not None},

    {"id":"manager_sold_5k",    "tier":"gold",     "icon":"⌂",  "hidden":False,
     "name":"The Manager Special",
     "hint":"Have your business manager auto-sell 5,000g worth of goods.",
     "desc":"Your manager earns their wage. Finally.",
     "check": lambda g: (g.business_manager is not None
                         and g.business_manager.total_sold_value >= 5000)},

    {"id":"full_workers",       "tier":"silver",   "icon":"⌂",  "hidden":False,
     "name":"Best Boss",
     "hint":"Fill all worker slots across all owned businesses.",
     "desc":"A fully staffed operation. Profits should follow. Should.",
     "check": lambda g: (len(g.businesses) > 0
                         and all(b.workers >= b.max_workers for b in g.businesses))},

    {"id":"all_biz_broken",     "tier":"",         "icon":"☠",  "hidden":True,
     "name":"Closed for Renovations",
     "hint":"???",
     "desc":"Three of your businesses broke down at the same time. Talent.",
     "check": lambda g: sum(1 for b in g.businesses if b.broken_down) >= 3},

    # ══ SKILLS ═══════════════════════════════════════════════════════════════
    {"id":"skill_lv2",          "tier":"bronze",   "icon":"▲",  "hidden":False,
     "name":"Apprentice",
     "hint":"Raise any skill to level 2.",
     "desc":"You're learning. It shows.",
     "check": lambda g: any(getattr(g.skills, s.value.lower(), 0) >= 2 for s in __import__('enum').EnumMeta.__subclasscheck__ and [] or [])
     },  # placeholder; real check below via _check_skill

    {"id":"skill_lv5",          "tier":"silver",   "icon":"▲",  "hidden":False,
     "name":"Seasoned Pro",
     "hint":"Raise any skill to level 5.",
     "desc":"Not just book smarts — you've earned those calluses.",
     "check": lambda g: False},  # replaced below

    {"id":"skill_lv10",         "tier":"gold",     "icon":"▲",  "hidden":False,
     "name":"Master of the Craft",
     "hint":"Max out any skill (level 10).",
     "desc":"You have reached the pinnacle of this discipline.",
     "check": lambda g: False},  # replaced below

    {"id":"all_skills_3",       "tier":"silver",   "icon":"▲",  "hidden":False,
     "name":"Renaissance Merchant",
     "hint":"Raise all 6 skills to level 3.",
     "desc":"A well-rounded education in exploitation.",
     "check": lambda g: False},  # replaced below

    {"id":"all_skills_5",       "tier":"gold",     "icon":"▲",  "hidden":False,
     "name":"The Complete Package",
     "hint":"Raise all 6 skills to level 5.",
     "desc":"You are terrifyingly good at commerce.",
     "check": lambda g: False},  # replaced below

    {"id":"max_espionage",      "tier":"gold",     "icon":"▲",  "hidden":True,
     "name":"The Ghost",
     "hint":"???",
     "desc":"Espionage 10. You were never here.",
     "check": lambda g: False},  # replaced below

    {"id":"max_logistics",      "tier":"silver",   "icon":"▲",  "hidden":False,
     "name":"Pack Mule Supreme",
     "hint":"Raise Logistics to level 10.",
     "desc":"You can carry an implausible amount of goods. Don't ask how.",
     "check": lambda g: False},  # replaced below

    {"id":"max_banking",        "tier":"gold",     "icon":"▲",  "hidden":False,
     "name":"The Banker",
     "hint":"Raise Banking to level 10.",
     "desc":"Interest rates whisper your name in awe.",
     "check": lambda g: False},  # replaced below

    # ══ EXPLORATION ══════════════════════════════════════════════════════════
    {"id":"areas_4",            "tier":"bronze",   "icon":"✦",  "hidden":False,
     "name":"Wanderer",
     "hint":"Visit 4 different regions.",
     "desc":"The horizon is your favourite view.",
     "check": lambda g: len(set(g.ach_stats.get("areas_visited", []))) >= 4},

    {"id":"areas_all",          "tier":"silver",   "icon":"✦",  "hidden":False,
     "name":"World Traveler",
     "hint":"Visit all 8 regions.",
     "desc":"You've seen everything. Nothing surprises you.",
     "check": lambda g: len(set(g.ach_stats.get("areas_visited", []))) >= 8},

    {"id":"journey_10",         "tier":"bronze",   "icon":"✦",  "hidden":False,
     "name":"On the Road",
     "hint":"Complete 10 journeys between regions.",
     "desc":"Your boots need resoling.",
     "check": lambda g: g.ach_stats.get("journeys", 0) >= 10},

    {"id":"journey_50",         "tier":"silver",   "icon":"✦",  "hidden":False,
     "name":"Nomad",
     "hint":"Complete 50 journeys.",
     "desc":"Home is wherever you lay your ledger book.",
     "check": lambda g: g.ach_stats.get("journeys", 0) >= 50},

    {"id":"journey_100",        "tier":"gold",     "icon":"✦",  "hidden":True,
     "name":"The Wandering Merchant",
     "hint":"???",
     "desc":"100 journeys. You've spent half your life on the road.",
     "check": lambda g: g.ach_stats.get("journeys", 0) >= 100},

    {"id":"travel_tundra",      "tier":"bronze",   "icon":"✦",  "hidden":False,
     "name":"Into the Frozen Wastes",
     "hint":"Travel to the Tundra region.",
     "desc":"Why would you go there? Profit, apparently.",
     "check": lambda g: "TUNDRA" in g.ach_stats.get("areas_visited", [])},

    {"id":"travel_desert",      "tier":"bronze",   "icon":"✦",  "hidden":False,
     "name":"Desert Walker",
     "hint":"Travel to the Desert region.",
     "desc":"Spice and gold await — and also heat stroke.",
     "check": lambda g: "DESERT" in g.ach_stats.get("areas_visited", [])},

    {"id":"travel_days_365",    "tier":"gold",     "icon":"✦",  "hidden":False,
     "name":"A Year on the Road",
     "hint":"Accumulate 365 total days of travel.",
     "desc":"Your mount has earned a very long vacation.",
     "check": lambda g: g.ach_stats.get("travel_days", 0) >= 365},

    # ══ SMUGGLING ════════════════════════════════════════════════════════════
    {"id":"first_smuggle",      "tier":"bronze",   "icon":"☾",  "hidden":False,
     "name":"Shady Dealings",
     "hint":"Successfully fence your first contraband.",
     "desc":"You told yourself it was just this once.",
     "check": lambda g: g.ach_stats.get("smuggle_success", 0) >= 1},

    {"id":"smuggle_10",         "tier":"silver",   "icon":"☾",  "hidden":False,
     "name":"Career Criminal",
     "hint":"Complete 10 successful smuggling sales.",
     "desc":"You have a brand now. Unfortunately.",
     "check": lambda g: g.ach_stats.get("smuggle_success", 0) >= 10},

    {"id":"smuggle_gold_5k",    "tier":"gold",     "icon":"☾",  "hidden":False,
     "name":"Crime Pays",
     "hint":"Earn 5,000g total from smuggling.",
     "desc":"The illegal trade is very, very legal for your wallet.",
     "check": lambda g: g.ach_stats.get("smuggle_gold", 0) >= 5000},

    {"id":"smuggle_busted",     "tier":"",         "icon":"☾",  "hidden":True,
     "name":"Occupational Hazard",
     "hint":"???",
     "desc":"You got caught. First time happens to everyone. Allegedly.",
     "check": lambda g: g.ach_stats.get("smuggle_busts", 0) >= 1},

    {"id":"smuggle_busted_3",   "tier":"",         "icon":"☾",  "hidden":True,
     "name":"Three Strikes",
     "hint":"???",
     "desc":"Caught three times. At this point the guards know you by name.",
     "check": lambda g: g.ach_stats.get("smuggle_busts", 0) >= 3},

    {"id":"hot_potato",         "tier":"",         "icon":"☾",  "hidden":True,
     "name":"On Fire",
     "hint":"???",
     "desc":"Heat level 90+. Every guard in the realm is looking for you.",
     "check": lambda g: g.heat >= 90},

    {"id":"phantom",            "tier":"gold",     "icon":"☾",  "hidden":True,
     "name":"Phantom",
     "hint":"???",
     "desc":"20 successful smuggling ops without a single bust. You're a ghost.",
     "check": lambda g: (g.ach_stats.get("smuggle_success", 0) >= 20
                         and g.ach_stats.get("smuggle_busts", 0) == 0)},

    {"id":"bribe_5",            "tier":"silver",   "icon":"☾",  "hidden":False,
     "name":"Pocket Full of Favors",
     "hint":"Bribe guards 5 times.",
     "desc":"Corruption is just commerce by another name.",
     "check": lambda g: g.ach_stats.get("bribes", 0) >= 5},

    # ══ CONTRACTS ════════════════════════════════════════════════════════════
    {"id":"first_contract",     "tier":"bronze",   "icon":"📜", "hidden":False,
     "name":"Delivery Person",
     "hint":"Fulfill your first contract on time.",
     "desc":"On time, on target. You could do this professionally.",
     "check": lambda g: g.ach_stats.get("contracts_ontime", 0) >= 1},

    {"id":"contracts_5",        "tier":"silver",   "icon":"📜", "hidden":False,
     "name":"Reliable Courier",
     "hint":"Fulfill 5 contracts on time.",
     "desc":"Five satisfied clients. Seventeen unsatisfied, but we don't mention those.",
     "check": lambda g: g.ach_stats.get("contracts_ontime", 0) >= 5},

    {"id":"contracts_25",       "tier":"gold",     "icon":"📜", "hidden":False,
     "name":"Contract King",
     "hint":"Fulfill 25 contracts (on time or late).",
     "desc":"The contract guild has dedicated an entire shelf to your file.",
     "check": lambda g: g.ach_stats.get("contracts_completed", 0) >= 25},

    {"id":"deadlines_10",       "tier":"gold",     "icon":"📜", "hidden":False,
     "name":"Always on Time",
     "hint":"Fulfill 10 contracts in a row without missing a deadline.",
     "desc":"Are you a merchant or a postal service? Yes.",
     "check": lambda g: g.ach_stats.get("contracts_streak", 0) >= 10},

    {"id":"contract_close_call","tier":"",         "icon":"📜", "hidden":True,
     "name":"Photo Finish",
     "hint":"???",
     "desc":"Fulfilled a contract with exactly 1 day remaining. Dramatic.",
     "check": lambda g: g.ach_stats.get("contract_close_call", False)},

    {"id":"contract_first_fail","tier":"",         "icon":"📜", "hidden":True,
     "name":"Sorry I'm Late",
     "hint":"???",
     "desc":"Your first failed contract. The client is not happy.",
     "check": lambda g: g.ach_stats.get("contracts_failed", 0) >= 1},

    {"id":"contract_bonus_500", "tier":"silver",   "icon":"📜", "hidden":False,
     "name":"Premium Delivery",
     "hint":"Earn a 500g+ bonus on a single contract.",
     "desc":"Over-delivered. Pun intended.",
     "check": lambda g: g.ach_stats.get("max_contract_bonus", 0) >= 500},

    {"id":"contracts_failed_3", "tier":"",         "icon":"📜", "hidden":True,
     "name":"Overdue and Over It",
     "hint":"???",
     "desc":"Three failed contracts. The guild is not returning your letters.",
     "check": lambda g: g.ach_stats.get("contracts_failed", 0) >= 3},

    # ══ BANKING & LENDING ════════════════════════════════════════════════════
    {"id":"first_loan",         "tier":"",         "icon":"⊛",  "hidden":False,
     "name":"In Debt We Trust",
     "hint":"Take out your first bank loan.",
     "desc":"Your future self would like a word.",
     "check": lambda g: g.ach_stats.get("loans_taken", 0) >= 1},

    {"id":"loans_repaid_2",     "tier":"silver",   "icon":"⊛",  "hidden":False,
     "name":"Debt Fighter",
     "hint":"Voluntarily repay 2 bank loans in full.",
     "desc":"Freedom from debt. For now.",
     "check": lambda g: g.ach_stats.get("loans_repaid", 0) >= 2},

    {"id":"cd_3",               "tier":"silver",   "icon":"⊛",  "hidden":False,
     "name":"CD Collector",
     "hint":"Hold 3 active Certificates of Deposit simultaneously.",
     "desc":"Patience is a virtue that compounds at 8% annually.",
     "check": lambda g: len(g.cds) >= 3},

    {"id":"first_citizen_loan", "tier":"bronze",   "icon":"⊛",  "hidden":False,
     "name":"The Moneylender",
     "hint":"Issue your first citizen loan.",
     "desc":"You are now the bank for someone else's problems.",
     "check": lambda g: len(g.citizen_loans) >= 1},

    {"id":"citizen_loans_5",    "tier":"silver",   "icon":"⊛",  "hidden":False,
     "name":"Loan Shark",
     "hint":"Have 5 active citizen loans at once.",
     "desc":"That many debtors. Sleep with one eye open.",
     "check": lambda g: (sum(1 for cl in g.citizen_loans
                              if not cl.defaulted and cl.weeks_remaining > 0)) >= 5},

    {"id":"citizen_loans_col10","tier":"gold",     "icon":"⊛",  "hidden":False,
     "name":"The Collector",
     "hint":"Have 10 citizen loans fully repaid.",
     "desc":"Every last coin, returned with interest. Remarkable.",
     "check": lambda g: (sum(1 for cl in g.citizen_loans
                              if not cl.defaulted and cl.weeks_remaining <= 0)) >= 10},

    {"id":"lender_license",     "tier":"silver",   "icon":"⊛",  "hidden":False,
     "name":"Chartered Lender",
     "hint":"Obtain the Lending Charter license.",
     "desc":"The state has officially sanctioned your avaricious behaviour.",
     "check": lambda g: LicenseType.LENDER in g.licenses},

    {"id":"loan_default",       "tier":"",         "icon":"⊛",  "hidden":True,
     "name":"The Deadbeat Chronicles",
     "hint":"???",
     "desc":"A citizen loan defaulted on you. Welcome to banking.",
     "check": lambda g: any(cl.defaulted for cl in g.citizen_loans)},

    # ══ STOCKS & FUND MANAGEMENT ══════════════════════════════════════════════
    {"id":"first_stock",        "tier":"bronze",   "icon":"↑",  "hidden":False,
     "name":"First of Many",
     "hint":"Buy your first stock on the exchange.",
     "desc":"You now own a tiny fraction of a company that may or may not exist.",
     "check": lambda g: len(g.stock_holdings) >= 1},

    {"id":"stocks_5types",      "tier":"silver",   "icon":"↑",  "hidden":False,
     "name":"Portfolio Manager",
     "hint":"Hold 5 different stocks simultaneously.",
     "desc":"Diversification! Or chaos. Hard to say.",
     "check": lambda g: len(g.stock_holdings) >= 5},

    {"id":"stocks_all_10",      "tier":"gold",     "icon":"↑",  "hidden":True,
     "name":"The Full Exchange",
     "hint":"???",
     "desc":"All 10 stocks in your portfolio simultaneously. You ARE the market.",
     "check": lambda g: len(g.stock_holdings) >= 10},

    {"id":"stock_profit_1k",    "tier":"silver",   "icon":"↑",  "hidden":False,
     "name":"The Bull",
     "hint":"Earn 1,000g in realized stock trading profits.",
     "desc":"Buy low, sell high. It really is that simple (it isn't).",
     "check": lambda g: g.ach_stats.get("stock_profit", 0) >= 1000},

    {"id":"stock_portfolio_10k","tier":"gold",     "icon":"↑",  "hidden":False,
     "name":"High Roller",
     "hint":"Have a stock portfolio value exceeding 10,000g.",
     "desc":"That's a lot of theoretical money.",
     "check": lambda g: g._portfolio_value() >= 10000},

    {"id":"diamond_hands",      "tier":"",         "icon":"↑",  "hidden":True,
     "name":"Diamond Hands",
     "hint":"???",
     "desc":"You're holding a stock at -30% from your average cost. Brave. Possibly foolish.",
     "check": lambda g: any(
         h.shares > 0
         and g.stock_market.stocks.get(sym, {}).get("price", h.avg_cost) <= h.avg_cost * 0.70
         for sym, h in g.stock_holdings.items()
     )},

    {"id":"first_fund_client",  "tier":"bronze",   "icon":"↑",  "hidden":False,
     "name":"Fund Starter",
     "hint":"Accept your first fund management client.",
     "desc":"Someone trusts you with their money. Terrifying.",
     "check": lambda g: len(g.fund_clients) >= 1},

    {"id":"fund_clients_3",     "tier":"silver",   "icon":"↑",  "hidden":False,
     "name":"Trust Fund Manager",
     "hint":"Manage 3 active fund clients simultaneously.",
     "desc":"You manage other people's wealth while acquiring your own.",
     "check": lambda g: sum(1 for fc in g.fund_clients if not fc.withdrawn) >= 3},

    {"id":"fund_fees_1k",       "tier":"gold",     "icon":"↑",  "hidden":False,
     "name":"Fee for Service",
     "hint":"Collect 1,000g in fund management fees.",
     "desc":"This is the way: charge fees regardless of performance.",
     "check": lambda g: g.ach_stats.get("fund_fees", 0) >= 1000},

    {"id":"fund_mgr_license",   "tier":"gold",     "icon":"↑",  "hidden":False,
     "name":"The Fund Manager",
     "hint":"Obtain the Fund Manager License.",
     "desc":"Certified to manage other people's mistakes professionally.",
     "check": lambda g: LicenseType.FUND_MGR in g.licenses},

    # ══ LICENSES ═════════════════════════════════════════════════════════════
    {"id":"first_extra_license","tier":"bronze",   "icon":"⊕",  "hidden":False,
     "name":"Credentialed",
     "hint":"Purchase your first non-default license.",
     "desc":"The bureaucracy acknowledges your existence.",
     "check": lambda g: g.ach_stats.get("licenses_purchased", 0) >= 1},

    {"id":"all_licenses",       "tier":"gold",     "icon":"⊕",  "hidden":False,
     "name":"Licensed to Deal",
     "hint":"Obtain all 6 licenses.",
     "desc":"You are licensed in everything. The realm is yours to exploit.",
     "check": lambda g: len(g.licenses) >= 6},

    {"id":"broke_buying_license","tier":"",        "icon":"⊕",  "hidden":True,
     "name":"Committed to the Bit",
     "hint":"???",
     "desc":"Spent your last 50g or less on a license. Priorities.",
     "check": lambda g: g.ach_stats.get("license_bought_broke", False)},

    # ══ REPUTATION ════════════════════════════════════════════════════════════
    {"id":"rep_70",             "tier":"bronze",   "icon":"♦",  "hidden":False,
     "name":"Respected",
     "hint":"Reach 70 reputation.",
     "desc":"Merchants greet you first. A small but meaningful sign.",
     "check": lambda g: g.reputation >= 70},

    {"id":"rep_90",             "tier":"gold",     "icon":"♦",  "hidden":False,
     "name":"Beloved",
     "hint":"Reach 90 reputation.",
     "desc":"Songs are being written about you. Flattering ones, even.",
     "check": lambda g: g.reputation >= 90},

    {"id":"rep_100",            "tier":"platinum", "icon":"♦",  "hidden":False,
     "name":"Community Pillar",
     "hint":"Reach 100 reputation.",
     "desc":"Perfect reputation. You could probably be elected king.",
     "check": lambda g: g.reputation >= 100},

    {"id":"rep_recovery",       "tier":"silver",   "icon":"♦",  "hidden":True,
     "name":"Redemption Arc",
     "hint":"???",
     "desc":"Clawed back from below 20 reputation to above 60. The people forgive you.",
     "check": lambda g: g.ach_stats.get("rep_recovered", False)},

    {"id":"rep_floor",          "tier":"",         "icon":"♦",  "hidden":True,
     "name":"Persona Non Grata",
     "hint":"???",
     "desc":"Reputation hit 0. Dogs bark at you in the street.",
     "check": lambda g: g.ach_stats.get("rep_hit_zero", False)},

    # ══ WORLD EVENTS ══════════════════════════════════════════════════════════
    {"id":"events_5",           "tier":"bronze",   "icon":"⚑",  "hidden":False,
     "name":"Storm Chaser",
     "hint":"Experience 5 random world events.",
     "desc":"Floods, wars, droughts — you've seen them all. From a safe distance.",
     "check": lambda g: g.ach_stats.get("events_triggered", 0) >= 5},

    {"id":"lucky_find",         "tier":"",         "icon":"⚑",  "hidden":False,
     "name":"Fortune Smiles",
     "hint":"Discover a lucky item abandoned on the road.",
     "desc":"Free stuff! The best kind of stuff.",
     "check": lambda g: g.ach_stats.get("lucky_finds", 0) >= 1},

    {"id":"war_profiteer",      "tier":"silver",   "icon":"⚑",  "hidden":True,
     "name":"War Profiteer",
     "hint":"???",
     "desc":"Sold 50+ ore or steel while a WAR event was active. Tasteless, effective.",
     "check": lambda g: g.ach_stats.get("war_ore_sold", 0) >= 50},

    {"id":"plague_doctor",      "tier":"silver",   "icon":"⚑",  "hidden":True,
     "name":"The Apothecary",
     "hint":"???",
     "desc":"Sold medicine during a PLAGUE event. Hero or profiteer? Both.",
     "check": lambda g: g.ach_stats.get("plague_medicine_sold", 0) >= 1},

    {"id":"survived_attack",    "tier":"",         "icon":"⚑",  "hidden":True,
     "name":"Robbed and Wiser",
     "hint":"???",
     "desc":"Survived a theft or armed attack on the road. You'll hire a better guard.",
     "check": lambda g: g.ach_stats.get("attacks_suffered", 0) >= 1},

    # ══ FUNNY / SPECIAL / HIDDEN ══════════════════════════════════════════════
    {"id":"sell_at_loss",       "tier":"",         "icon":"☺",  "hidden":True,
     "name":"Buy High, Sell Low",
     "hint":"???",
     "desc":"You sold something for less than you paid. A bold strategy.",
     "check": lambda g: g.ach_stats.get("sold_at_loss", False)},

    {"id":"broker_in_debt",     "tier":"",         "icon":"☺",  "hidden":True,
     "name":"Broke and Broker",
     "hint":"???",
     "desc":"Went into negative gold. The irony of being a merchant.",
     "check": lambda g: g.ach_stats.get("went_negative", False)},

    {"id":"help_10",            "tier":"",         "icon":"☺",  "hidden":False,
     "name":"Help Me I'm Lost",
     "hint":"Press ? for help 10 or more times.",
     "desc":"The help guide is good but maybe read it once and remember it?",
     "check": lambda g: g.ach_stats.get("help_presses", 0) >= 10},

    {"id":"wait_10_streak",     "tier":"",         "icon":"☺",  "hidden":True,
     "name":"The Philosopher",
     "hint":"???",
     "desc":"10 consecutive days of waiting and resting without trading. Deep.",
     "check": lambda g: g.ach_stats.get("wait_streak", 0) >= 10},

    {"id":"year_5",             "tier":"silver",   "icon":"⌛", "hidden":False,
     "name":"Seasoned Survivor",
     "hint":"Play for 5 in-game years.",
     "desc":"Half a decade in the markets. You look tired.",
     "check": lambda g: g.year >= 5},

    {"id":"year_10",            "tier":"gold",     "icon":"⌛", "hidden":False,
     "name":"The Long Haul",
     "hint":"Play for 10 in-game years.",
     "desc":"A decade. The markets have changed. You have too.",
     "check": lambda g: g.year >= 10},

    {"id":"year_30",            "tier":"platinum", "icon":"⌛", "hidden":True,
     "name":"What Am I Doing With My Life",
     "hint":"???",
     "desc":"Year 30. The realm has aged around you. Are you... okay?",
     "check": lambda g: g.year >= 30},

    # ══ REAL ESTATE ═══════════════════════════════════════════════════════════
    {"id":"re_first_property",  "tier":"bronze",   "icon":"🏠", "hidden":False,
     "name":"Property Owner",
     "hint":"Purchase or build your first property.",
     "desc":"Land is the only thing they stopped making more of.",
     "check": lambda g: len(g.real_estate) >= 1},

    {"id":"re_3_properties",    "tier":"silver",   "icon":"🏠", "hidden":False,
     "name":"Property Baron",
     "hint":"Own 3 or more properties simultaneously.",
     "desc":"Three rooftops above your name. Progress.",
     "check": lambda g: sum(1 for p in g.real_estate if not p.under_construction) >= 3},

    {"id":"re_5_properties",    "tier":"gold",     "icon":"🏠", "hidden":False,
     "name":"Real Estate Mogul",
     "hint":"Own 5 or more properties simultaneously.",
     "desc":"At five properties, you stop counting rooms and start counting buildings.",
     "check": lambda g: sum(1 for p in g.real_estate if not p.under_construction) >= 5},

    {"id":"re_10_properties",   "tier":"platinum", "icon":"🏠", "hidden":True,
     "name":"The Landlord",
     "hint":"???",
     "desc":"Ten properties. Half the city rents from you. The other half wants to.",
     "check": lambda g: sum(1 for p in g.real_estate if not p.under_construction) >= 10},

    {"id":"re_estate_owner",    "tier":"gold",     "icon":"🏠", "hidden":False,
     "name":"Lord of the Manor",
     "hint":"Own a Grand Estate.",
     "desc":"You've acquired an estate grand enough to embarrass minor nobility.",
     "check": lambda g: any(p.prop_type == "estate" and not p.under_construction
                            for p in g.real_estate)},

    {"id":"re_first_flip",      "tier":"bronze",   "icon":"🔨", "hidden":False,
     "name":"The Flipper",
     "hint":"Repair a property and sell it for more than you paid.",
     "desc":"Buy low, repair well, sell high. The oldest trick in the book.",
     "check": lambda g: g.ach_stats.get("re_flip_profit", 0) > 0},

    {"id":"re_flip_profit_1k",  "tier":"silver",   "icon":"🔨", "hidden":False,
     "name":"Master Renovator",
     "hint":"Earn 1,000g profit from a single property sale.",
     "desc":"Derelict to desirable — you have a talent for this.",
     "check": lambda g: g.ach_stats.get("re_max_flip_profit", 0) >= 1000},

    {"id":"re_flip_profit_5k",  "tier":"gold",     "icon":"🔨", "hidden":True,
     "name":"The Developer",
     "hint":"???",
     "desc":"A single property flip netting 5,000g. That's not luck — that's skill.",
     "check": lambda g: g.ach_stats.get("re_max_flip_profit", 0) >= 5000},

    {"id":"re_first_lease",     "tier":"bronze",   "icon":"📋", "hidden":False,
     "name":"Landlord's Debut",
     "hint":"Put a property up for lease.",
     "desc":"Passive income. The merchant's ultimate ambition.",
     "check": lambda g: g.ach_stats.get("re_leases_active", 0) >= 1},

    {"id":"re_lease_3",         "tier":"silver",   "icon":"📋", "hidden":False,
     "name":"The Portfolio Landlord",
     "hint":"Have 3 properties leased simultaneously.",
     "desc":"Three revenue streams flowing without your daily effort. Elegant.",
     "check": lambda g: sum(1 for p in g.real_estate
                             if p.is_leased and not p.under_construction) >= 3},

    {"id":"re_lease_income_5k", "tier":"gold",     "icon":"📋", "hidden":False,
     "name":"Rent Collector",
     "hint":"Collect 5,000g in total lease income.",
     "desc":"Tenants have contributed more than they probably realize.",
     "check": lambda g: g.ach_stats.get("re_lease_income", 0) >= 5000},

    {"id":"re_lease_income_25k","tier":"platinum", "icon":"📋", "hidden":True,
     "name":"The Passive Empire",
     "hint":"???",
     "desc":"25,000g in lease income. Your properties work harder than you do.",
     "check": lambda g: g.ach_stats.get("re_lease_income", 0) >= 25000},

    {"id":"re_first_build",     "tier":"bronze",   "icon":"🏗",  "hidden":False,
     "name":"Ground Breaking",
     "hint":"Complete your first construction project.",
     "desc":"You watched it go from an empty plot to a real building. Satisfying.",
     "check": lambda g: g.ach_stats.get("re_builds_completed", 0) >= 1},

    {"id":"re_builder_3",       "tier":"silver",   "icon":"🏗",  "hidden":False,
     "name":"Master Builder",
     "hint":"Complete 3 construction projects.",
     "desc":"The architect's guild considers you a valuable patron.",
     "check": lambda g: g.ach_stats.get("re_builds_completed", 0) >= 3},

    {"id":"re_upgrade_5",       "tier":"silver",   "icon":"🏗",  "hidden":False,
     "name":"Property Perfectionist",
     "hint":"Apply 5 upgrades across your properties.",
     "desc":"Details matter. Wine cellars, stone facades, ornate gates — every coin shows.",
     "check": lambda g: g.ach_stats.get("re_upgrades_applied", 0) >= 5},

    {"id":"re_diversified",     "tier":"gold",     "icon":"🏠", "hidden":False,
     "name":"The Property Map",
     "hint":"Own properties in 4 different regions.",
     "desc":"Your real estate portfolio has geographic range. Impressive.",
     "check": lambda g: len(set(g.ach_stats.get("re_properties_areas", []))) >= 4},

    {"id":"re_tycoon",          "tier":"platinum", "icon":"🏠", "hidden":True,
     "name":"The Tycoon",
     "hint":"???",
     "desc":"5+ properties and 5+ businesses at once. You are the economy.",
     "check": lambda g: (sum(1 for p in g.real_estate if not p.under_construction) >= 5
                         and len(g.businesses) >= 5)},

    {"id":"re_license",         "tier":"silver",   "icon":"🏠", "hidden":False,
     "name":"Chartered Developer",
     "hint":"Obtain the Real Estate Charter license.",
     "desc":"Officially licensed to buy, build, and lease. The realm is your domain.",
     "check": lambda g: LicenseType.REAL_ESTATE in g.licenses},

    {"id":"re_derelict_flip",   "tier":"gold",     "icon":"🔨", "hidden":True,
     "name":"From the Ashes",
     "hint":"???",
     "desc":"Bought a Derelict property, fully repaired it, and sold it for profit.",
     "check": lambda g: g.ach_stats.get("re_derelict_flip", False)},

    # ══ INFLUENCE COVERAGE ════════════════════════════════════════════════════
    {"id":"influence_first",    "tier":"bronze",   "icon":"⭐", "hidden":False,
     "name":"The Backchannel",
     "hint":"Execute your first influence operation.",
     "desc":"Whisper campaigns, slander, and quiet coin — tools of the trade.",
     "check": lambda g: g.ach_stats.get("campaigns_run", 0) + g.ach_stats.get("slanders_run", 0) >= 1},

    {"id":"influence_power",    "tier":"silver",   "icon":"⭐", "hidden":False,
     "name":"The Puppeteer",
     "hint":"Execute 10 total influence operations.",
     "desc":"Ten market manipulations in. You've learned that subtlety scales.",
     "check": lambda g: g.ach_stats.get("campaigns_run", 0) + g.ach_stats.get("slanders_run", 0) >= 10},

    {"id":"influence_max_gold", "tier":"gold",     "icon":"⭐", "hidden":True,
     "name":"The Gray Cardinal",
     "hint":"???",
     "desc":"Spent 2,000g on a single influence campaign. You know what you're doing.",
     "check": lambda g: g.ach_stats.get("max_campaign_gold", 0) >= 2000},
]

# Fix lambda checks that needed SkillType inline — replace with real funcs
def _ach_skill_check(level: int):
    def _c(g):
        from_vals = [g.skills.trading, g.skills.haggling, g.skills.logistics,
                     g.skills.industry, g.skills.espionage, g.skills.banking]
        return any(v >= level for v in from_vals)
    return _c

def _ach_all_skills_check(level: int):
    def _c(g):
        from_vals = [g.skills.trading, g.skills.haggling, g.skills.logistics,
                     g.skills.industry, g.skills.espionage, g.skills.banking]
        return all(v >= level for v in from_vals)
    return _c

# Patch the placeholder lambdas with real check functions
_ACH_SKILL_CHECKS = {
    "skill_lv2":    _ach_skill_check(2),
    "skill_lv5":    _ach_skill_check(5),
    "skill_lv10":   _ach_skill_check(10),
    "all_skills_3": _ach_all_skills_check(3),
    "all_skills_5": _ach_all_skills_check(5),
    "max_espionage":  lambda g: g.skills.espionage  >= 10,
    "max_logistics":  lambda g: g.skills.logistics  >= 10,
    "max_banking":    lambda g: g.skills.banking     >= 10,
}
for _ach in ACHIEVEMENTS:
    if _ach["id"] in _ACH_SKILL_CHECKS:
        _ach["check"] = _ACH_SKILL_CHECKS[_ach["id"]]

# Build lookup dict for fast access
ACHIEVEMENTS_BY_ID = {a["id"]: a for a in ACHIEVEMENTS}

# ─────────────────────────────────────────────────────────────────────────────
# ITEM CATALOGUE  (30+ items)
# ─────────────────────────────────────────────────────────────────────────────

ALL_ITEMS: Dict[str, Item] = {
    # ── Raw Materials ──────────────────────────────────────────────────────
    "wheat":        Item("wheat",        "Wheat",          10,   ItemCategory.RAW_MATERIAL,  "common",    1.0, area_produced=["FARMLAND"], description="Staple grain crop."),
    "barley":       Item("barley",       "Barley",         8,    ItemCategory.RAW_MATERIAL,  "common",    1.0, area_produced=["FARMLAND"], description="Used in brewing."),
    "cotton":       Item("cotton",       "Cotton",         14,   ItemCategory.RAW_MATERIAL,  "common",    0.8, area_produced=["FARMLAND"], description="Raw textile fibre."),
    "ore":          Item("ore",          "Iron Ore",       25,   ItemCategory.RAW_MATERIAL,  "uncommon",  2.0, area_produced=["MOUNTAIN"], description="Smelted into metal."),
    "coal":         Item("coal",         "Coal",           18,   ItemCategory.RAW_MATERIAL,  "common",    2.5, area_produced=["MOUNTAIN"], description="Fuels furnaces."),
    "gold_dust":    Item("gold_dust",    "Gold Dust",      120,  ItemCategory.RAW_MATERIAL,  "rare",      0.5, area_produced=["MOUNTAIN", "DESERT"], description="Raw gold flakes."),
    "sulfur":       Item("sulfur",       "Sulfur",         30,   ItemCategory.RAW_MATERIAL,  "uncommon",  1.0, area_produced=["DESERT", "SWAMP"], description="Used in alchemy."),
    "timber":       Item("timber",       "Timber",         20,   ItemCategory.RAW_MATERIAL,  "common",    3.0, area_produced=["FOREST"], description="Raw cut lumber."),
    "herbs":        Item("herbs",        "Wild Herbs",     22,   ItemCategory.RAW_MATERIAL,  "uncommon",  0.5, area_produced=["FOREST", "SWAMP"], description="Medicinal plants."),
    "peat":         Item("peat",         "Peat",           12,   ItemCategory.RAW_MATERIAL,  "common",    2.0, area_produced=["SWAMP"], description="Burnable bog material."),
    "ivory":        Item("ivory",        "Ivory",          80,   ItemCategory.RAW_MATERIAL,  "rare",      1.5, area_produced=["DESERT"], description="Precious animal tusk."),
    "fur":          Item("fur",          "Animal Fur",     45,   ItemCategory.RAW_MATERIAL,  "uncommon",  0.7, area_produced=["TUNDRA", "FOREST"], description="Thick warm pelts."),
    "blubber":      Item("blubber",      "Whale Blubber",  35,   ItemCategory.RAW_MATERIAL,  "uncommon",  2.0, area_produced=["COAST", "TUNDRA"], description="Used for oil and light."),

    # ── Food & Drink ──────────────────────────────────────────────────────
    "fish":         Item("fish",         "Salted Fish",    15,   ItemCategory.FOOD,          "common",    1.0, area_produced=["COAST"], seasonal_bonus=Season.SUMMER, description="Preserves well."),
    "bread":        Item("bread",        "Bread",          18,   ItemCategory.FOOD,          "common",    0.8, description="Baked from wheat."),
    "ale":          Item("ale",          "Ale",            20,   ItemCategory.FOOD,          "common",    1.2, seasonal_bonus=Season.AUTUMN, description="Brewed from barley."),
    "wine":         Item("wine",         "Fine Wine",      55,   ItemCategory.FOOD,          "uncommon",  1.0, area_produced=["FARMLAND"], seasonal_bonus=Season.AUTUMN, description="Aged vintage."),
    "exotic_fruit": Item("exotic_fruit", "Exotic Fruit",   38,   ItemCategory.FOOD,          "uncommon",  0.6, area_produced=["DESERT"], seasonal_bonus=Season.SUMMER, description="Sweet desert fruit."),
    "smoked_meat":  Item("smoked_meat",  "Smoked Meat",    28,   ItemCategory.FOOD,          "common",    1.0, area_produced=["TUNDRA", "FOREST"], description="Long-lasting preserved meat."),
    "honey":        Item("honey",        "Forest Honey",   42,   ItemCategory.FOOD,          "uncommon",  0.7, area_produced=["FOREST"], description="Sweet and medicinal."),
    "spice":        Item("spice",        "Rare Spices",    65,   ItemCategory.FOOD,          "rare",      0.6, area_produced=["DESERT"], seasonal_bonus=Season.WINTER, description="From distant lands."),
    "salt":         Item("salt",         "Salt",           22,   ItemCategory.FOOD,          "common",    1.5, area_produced=["COAST", "DESERT"], description="Essential preservative."),

    # ── Processed Goods ────────────────────────────────────────────────────
    "cloth":        Item("cloth",        "Woven Cloth",    30,   ItemCategory.PROCESSED,     "common",    0.8, description="Woven from cotton."),
    "steel":        Item("steel",        "Steel Ingot",    60,   ItemCategory.PROCESSED,     "uncommon",  2.0, description="Smelted from iron ore."),
    "wood":         Item("wood",         "Planked Wood",   18,   ItemCategory.PROCESSED,     "common",    2.5, description="Cut and dried planks."),
    "rope":         Item("rope",         "Rope & Rigging", 25,   ItemCategory.PROCESSED,     "common",    1.5, area_produced=["COAST"], description="Essential for ships."),
    "leather":      Item("leather",      "Tanned Leather", 40,   ItemCategory.PROCESSED,     "uncommon",  0.9, description="Cured animal hides."),
    "paper":        Item("paper",        "Paper",          20,   ItemCategory.PROCESSED,     "common",    0.8, description="Made from wood pulp."),
    "gunpowder":    Item("gunpowder",    "Gunpowder",      75,   ItemCategory.PROCESSED,     "rare",      1.0, illegal=True, description="Volatile mixture."),
    "medicine":     Item("medicine",     "Medicine",       90,   ItemCategory.PROCESSED,     "rare",      0.7, description="Brewed from herbs and knowledge."),
    "glassware":    Item("glassware",    "Fine Glassware", 50,   ItemCategory.PROCESSED,     "uncommon",  1.0, description="Blown in the capital."),

    # ── Luxury Goods ──────────────────────────────────────────────────────
    "gem":          Item("gem",          "Gemstone",       150,  ItemCategory.LUXURY,        "rare",      0.5, area_produced=["MOUNTAIN"], description="Cut precious stones."),
    "jewelry":      Item("jewelry",      "Fine Jewelry",   200,  ItemCategory.LUXURY,        "rare",      0.6, description="Crafted gold and gems."),
    "silk":         Item("silk",         "Silk Cloth",     110,  ItemCategory.LUXURY,        "rare",      0.6, area_produced=["DESERT"], description="Incredibly fine weave."),
    "perfume":      Item("perfume",      "Exotic Perfume", 130,  ItemCategory.LUXURY,        "rare",      0.4, area_produced=["SWAMP", "DESERT"], description="Distilled from rare flowers."),
    "tapestry":     Item("tapestry",     "Tapestry",       85,   ItemCategory.LUXURY,        "uncommon",  1.5, description="Decorated woven art."),
    "artifact":     Item("artifact",     "Ancient Relic",  300,  ItemCategory.LUXURY,        "legendary", 0.5, area_produced=["DESERT", "SWAMP"], description="Priceless historical piece."),

    # ── Contraband ────────────────────────────────────────────────────────
    "blackpowder":  Item("blackpowder",  "Black Powder",   95,   ItemCategory.CONTRABAND,    "rare",      1.0, illegal=True, description="Restricted explosive compound."),
    "stolen_goods": Item("stolen_goods", "Stolen Goods",   40,   ItemCategory.CONTRABAND,    "uncommon",  1.5, illegal=True, description="Hot merchandise."),
    "toxin":        Item("toxin",        "Alchemical Toxin",180, ItemCategory.CONTRABAND,    "rare",      0.7, illegal=True, description="Dangerous substance."),
}

# ─────────────────────────────────────────────────────────────────────────────
# AREA DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

AREA_INFO = {
    Area.CITY: {
        "description": "The bustling capital — everything is available but nothing is cheap.",
        "travel_days": {Area.FARMLAND: 1, Area.MOUNTAIN: 2, Area.COAST: 1, Area.FOREST: 2, Area.DESERT: 3, Area.SWAMP: 3, Area.TUNDRA: 4},
        "travel_risk": 0.05,
        "base_items": [
            "wheat","barley","ore","fish","timber","cloth","steel","wood","bread","ale",
            "wine","spice","gem","jewelry","silk","glassware","medicine","leather","paper","tapestry",
            "salt","smoked_meat","honey","coal","cotton","herbs","ivory","exotic_fruit",
        ],
        "guard_strength": 3,   # high guard = harder to smuggle
    },
    Area.FARMLAND: {
        "description": "Fertile plains producing food and fibre for the realm.",
        "travel_days": {Area.CITY: 1, Area.MOUNTAIN: 2, Area.COAST: 2, Area.FOREST: 1, Area.DESERT: 3, Area.SWAMP: 2, Area.TUNDRA: 3},
        "travel_risk": 0.04,
        "base_items": ["wheat","barley","cotton","bread","ale","wine","honey","cloth","leather","salt"],
        "guard_strength": 1,
    },
    Area.MOUNTAIN: {
        "description": "Rugged peaks rich in ore, gems, and coal.",
        "travel_days": {Area.CITY: 2, Area.FARMLAND: 2, Area.COAST: 3, Area.FOREST: 2, Area.DESERT: 3, Area.SWAMP: 4, Area.TUNDRA: 2},
        "travel_risk": 0.10,
        "base_items": ["ore","coal","gold_dust","gem","steel","fur","smoked_meat","sulfur"],
        "guard_strength": 1,
    },
    Area.COAST: {
        "description": "A thriving harbor town where ships bring strange cargo.",
        "travel_days": {Area.CITY: 1, Area.FARMLAND: 2, Area.MOUNTAIN: 3, Area.FOREST: 2, Area.DESERT: 4, Area.SWAMP: 2, Area.TUNDRA: 4},
        "travel_risk": 0.08,
        "base_items": ["fish","salt","rope","blubber","cloth","wine","spice","silk","glassware","smoked_meat"],
        "guard_strength": 2,
    },
    Area.FOREST: {
        "description": "Dense woodland teeming with hunters, herbalists, and hidden paths.",
        "travel_days": {Area.CITY: 2, Area.FARMLAND: 1, Area.MOUNTAIN: 2, Area.COAST: 2, Area.DESERT: 4, Area.SWAMP: 1, Area.TUNDRA: 3},
        "travel_risk": 0.12,
        "base_items": ["timber","herbs","fur","honey","wood","peat","leather","smoked_meat","paper"],
        "guard_strength": 0,
    },
    Area.DESERT: {
        "description": "Harsh sands hiding ancient riches — and ruthless bandits.",
        "travel_days": {Area.CITY: 3, Area.FARMLAND: 3, Area.MOUNTAIN: 3, Area.COAST: 4, Area.FOREST: 4, Area.SWAMP: 5, Area.TUNDRA: 6},
        "travel_risk": 0.18,
        "base_items": ["gold_dust","ivory","sulfur","spice","exotic_fruit","silk","salt","artifact","perfume"],
        "guard_strength": 0,
    },
    Area.SWAMP: {
        "description": "Fetid marshes concealing rare plants, smugglers, and ancient secrets.",
        "travel_days": {Area.CITY: 3, Area.FARMLAND: 2, Area.MOUNTAIN: 4, Area.COAST: 2, Area.FOREST: 1, Area.DESERT: 5, Area.TUNDRA: 5},
        "travel_risk": 0.15,
        "base_items": ["herbs","peat","sulfur","perfume","artifact","blubber","stolen_goods","toxin"],
        "guard_strength": 0,
    },
    Area.TUNDRA: {
        "description": "Frozen wilderness where only the hardiest survive — and profit.",
        "travel_days": {Area.CITY: 4, Area.FARMLAND: 3, Area.MOUNTAIN: 2, Area.COAST: 4, Area.FOREST: 3, Area.DESERT: 6, Area.SWAMP: 5},
        "travel_risk": 0.14,
        "base_items": ["fur","blubber","smoked_meat","coal","iron_ore","gold_dust"],
        "guard_strength": 0,
    },
}

# Fix tundra items to valid keys
AREA_INFO[Area.TUNDRA]["base_items"] = ["fur","blubber","smoked_meat","coal","ore","gold_dust"]

# ─────────────────────────────────────────────────────────────────────────────
# SEASONAL MODIFIERS  (demand multiplier for each season)
# ─────────────────────────────────────────────────────────────────────────────

SEASONAL_DEMAND: Dict[str, Dict[Season, float]] = {
    # item_key: {season: multiplier}
    "wheat":        {Season.SPRING: 0.9,  Season.SUMMER: 1.1,  Season.AUTUMN: 1.3, Season.WINTER: 1.4},
    "bread":        {Season.SPRING: 1.0,  Season.SUMMER: 1.0,  Season.AUTUMN: 1.1, Season.WINTER: 1.4},
    "barley":       {Season.SPRING: 0.9,  Season.SUMMER: 0.9,  Season.AUTUMN: 1.4, Season.WINTER: 1.2},
    "ale":          {Season.SPRING: 1.1,  Season.SUMMER: 1.3,  Season.AUTUMN: 1.5, Season.WINTER: 1.2},
    "wine":         {Season.SPRING: 1.1,  Season.SUMMER: 1.2,  Season.AUTUMN: 1.4, Season.WINTER: 1.3},
    "spice":        {Season.SPRING: 1.0,  Season.SUMMER: 0.9,  Season.AUTUMN: 1.0, Season.WINTER: 1.5},
    "fur":          {Season.SPRING: 0.7,  Season.SUMMER: 0.5,  Season.AUTUMN: 1.0, Season.WINTER: 2.0},
    "coal":         {Season.SPRING: 0.7,  Season.SUMMER: 0.6,  Season.AUTUMN: 1.1, Season.WINTER: 2.2},
    "medicine":     {Season.SPRING: 1.0,  Season.SUMMER: 0.9,  Season.AUTUMN: 1.2, Season.WINTER: 1.8},
    "fish":         {Season.SPRING: 1.1,  Season.SUMMER: 1.4,  Season.AUTUMN: 1.1, Season.WINTER: 0.8},
    "exotic_fruit": {Season.SPRING: 1.1,  Season.SUMMER: 1.5,  Season.AUTUMN: 0.8, Season.WINTER: 0.6},
    "honey":        {Season.SPRING: 1.2,  Season.SUMMER: 1.4,  Season.AUTUMN: 1.0, Season.WINTER: 0.9},
    "timber":       {Season.SPRING: 1.2,  Season.SUMMER: 1.0,  Season.AUTUMN: 1.1, Season.WINTER: 1.3},
    "cotton":       {Season.SPRING: 1.3,  Season.SUMMER: 1.0,  Season.AUTUMN: 1.0, Season.WINTER: 0.8},
    "blubber":      {Season.SPRING: 0.8,  Season.SUMMER: 0.6,  Season.AUTUMN: 1.0, Season.WINTER: 1.6},
    "peat":         {Season.SPRING: 0.7,  Season.SUMMER: 0.6,  Season.AUTUMN: 1.0, Season.WINTER: 1.8},
    "smoked_meat":  {Season.SPRING: 1.0,  Season.SUMMER: 0.9,  Season.AUTUMN: 1.3, Season.WINTER: 1.5},
    # Items that previously had no seasonal variation — added for realism
    "salt":    {Season.SPRING: 0.9,  Season.SUMMER: 0.9,  Season.AUTUMN: 1.3, Season.WINTER: 1.2},  # autumn preservation season
    "cloth":   {Season.SPRING: 1.0,  Season.SUMMER: 0.9,  Season.AUTUMN: 1.2, Season.WINTER: 1.4},  # winter clothing demand
    "leather": {Season.SPRING: 1.0,  Season.SUMMER: 0.8,  Season.AUTUMN: 1.2, Season.WINTER: 1.5},  # winter boots/coats
    "rope":    {Season.SPRING: 1.2,  Season.SUMMER: 1.4,  Season.AUTUMN: 1.1, Season.WINTER: 0.8},  # sailing/construction season
    "wood":    {Season.SPRING: 1.2,  Season.SUMMER: 1.0,  Season.AUTUMN: 1.0, Season.WINTER: 1.5},  # firewood in winter, building in spring
    "steel":   {Season.SPRING: 1.2,  Season.SUMMER: 1.1,  Season.AUTUMN: 1.0, Season.WINTER: 0.9},  # construction season
    "silk":    {Season.SPRING: 1.3,  Season.SUMMER: 1.2,  Season.AUTUMN: 1.0, Season.WINTER: 0.9},  # social/fashion season
    "ivory":   {Season.SPRING: 1.0,  Season.SUMMER: 1.1,  Season.AUTUMN: 1.2, Season.WINTER: 0.9},  # gift-giving season
}

# ─────────────────────────────────────────────────────────────────────────────
# AREA PRODUCTION TABLE
# production_factor reflects how naturally abundant/cheap an item is in that area.
#   >= 1.8 → primary producer:   cheap, restocks fast, natural price ~75% of base
#   >= 1.4 → secondary producer: fairly cheap, moderate restock, ~85% of base
#   >= 1.0 → trades regularly:   neutral price, slow restock, ~92% of base
#   missing → importer only:     expensive, very slow restock, ~118% of base
# ─────────────────────────────────────────────────────────────────────────────

AREA_PRODUCTION: Dict[str, Dict[str, float]] = {
    "CITY": {
        "cloth":1.3, "steel":1.3, "glassware":1.4, "leather":1.2,
        "paper":1.3, "medicine":1.2, "jewelry":1.4, "tapestry":1.2,
        "bread":1.2, "ale":1.1, "wine":1.1,
    },
    "FARMLAND": {
        "wheat":2.0, "barley":2.0, "cotton":1.8, "bread":1.8,
        "ale":1.6,   "wine":1.8,   "honey":1.5, "cloth":1.3,
        "leather":1.2,
        # salt is NOT produced at farmland — it is imported from coast/desert
    },
    "MOUNTAIN": {
        "ore":2.0, "coal":2.0, "gold_dust":1.8, "gem":1.8,
        "steel":1.5, "fur":1.5, "smoked_meat":1.2, "sulfur":1.5,
    },
    "COAST": {
        "fish":2.0, "salt":1.8, "rope":1.8, "blubber":1.5,
        "smoked_meat":1.3, "cloth":1.1, "wine":1.1,
        "spice":1.1, "silk":1.1, "glassware":1.1,
    },
    "FOREST": {
        "timber":2.0, "herbs":2.0, "fur":1.8, "honey":1.8,
        "wood":1.5,  "peat":1.5,  "leather":1.5, "smoked_meat":1.5,
        "paper":1.3,
    },
    "DESERT": {
        "ivory":2.0, "spice":2.0, "exotic_fruit":2.0, "silk":1.8,
        "salt":1.5,  "gold_dust":1.5, "sulfur":1.8,
        "artifact":1.8, "perfume":1.8,
    },
    "SWAMP": {
        "herbs":1.8, "peat":2.0, "sulfur":1.5, "perfume":1.8,
        "artifact":1.5, "stolen_goods":2.0, "toxin":2.0,
        # blubber not produced here — swamps have no whales; traded as importer
    },
    "TUNDRA": {
        "fur":2.0, "blubber":2.0, "smoked_meat":1.8,
        "coal":1.5, "ore":1.3, "gold_dust":1.3,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# MARKET CLASS
# ─────────────────────────────────────────────────────────────────────────────

class AreaMarket:
    """
    Price model: price = base_price x pressure x seasonal x scarcity

    pressure  -- single float per item replacing old supply/demand pair.
                 Starts near natural_pressure (based on production) and
                 mean-reverts 20%/day back to it, preventing permanent
                 price lock-in from round-trip trading.

    Anti-exploit properties:
    - sqrt(qty) trade impact is capped so bulk buys can't spike prices 10x.
    - Strong daily mean reversion (20%/day) unwinds player-driven distortions.
    - Home producers restock deterministically every day (farms always produce).
    - Importers restock very slowly (1-5 units/day) making them scarce but stable.
    - Scarcity bonus max +30%, only when stock < 15 units.
    """

    HISTORY_LEN  = 30
    REVERT_RATE  = 0.20   # pressure reverts 20% toward natural each day
    SCARCITY_LOW = 15     # stock below this triggers mild scarcity premium
    BUY_IMPACT   = 0.018  # pressure += sqrt(qty) * BUY_IMPACT  (ceil 0.22)
    SELL_IMPACT  = 0.015  # pressure -= sqrt(qty) * SELL_IMPACT (ceil 0.18)
    MAX_PRESSURE = 2.0
    MIN_PRESSURE = 0.40

    def __init__(self, area: Area):
        self.area      = area
        info           = AREA_INFO[area]
        area_prod      = AREA_PRODUCTION.get(area.name, {})
        self.item_keys: List[str] = [k for k in info["base_items"] if k in ALL_ITEMS]

        self.natural_pressure: Dict[str, float] = {}
        self.natural_stock:    Dict[str, int]   = {}
        self.daily_restock:    Dict[str, int]   = {}

        for k in self.item_keys:
            pf = area_prod.get(k, 0.0)
            if pf >= 1.8:
                self.natural_pressure[k] = 0.75
                self.natural_stock[k]    = 220
                self.daily_restock[k]    = random.randint(18, 28)
            elif pf >= 1.4:
                self.natural_pressure[k] = 0.85
                self.natural_stock[k]    = 160
                self.daily_restock[k]    = random.randint(10, 18)
            elif pf >= 1.0:
                self.natural_pressure[k] = 0.92
                self.natural_stock[k]    = 100
                self.daily_restock[k]    = random.randint(5, 12)
            else:
                # Importer -- goods arrive slowly via trade routes
                self.natural_pressure[k] = 1.18
                self.natural_stock[k]    = 55
                self.daily_restock[k]    = random.randint(1, 5)

        # Initialise state near natural values with small random noise
        self.stock: Dict[str, int] = {
            k: random.randint(int(self.natural_stock[k] * 0.55),
                              self.natural_stock[k])
            for k in self.item_keys
        }
        self.pressure: Dict[str, float] = {
            k: self.natural_pressure[k] * random.uniform(0.93, 1.07)
            for k in self.item_keys
        }
        self.history:       Dict[str, deque] = {k: deque(maxlen=self.HISTORY_LEN) for k in self.item_keys}
        self.active_events: List[str]        = []
        self.days_passed = 0
        self.travel_risk_override: float = 0.0  # extra risk; decays daily

    # ── Price calculation ────────────────────────────────────────────────────

    def _seasonal_mult(self, item_key: str, season: Season) -> float:
        if item_key in SEASONAL_DEMAND:
            return SEASONAL_DEMAND[item_key].get(season, 1.0)
        return 1.0

    def get_price(self, item_key: str, season: Season, noise: bool = True) -> float:
        if item_key not in ALL_ITEMS:
            return 0.0
        base     = ALL_ITEMS[item_key].base_price
        pressure = self.pressure.get(item_key, 1.0)
        seasonal = self._seasonal_mult(item_key, season)
        stock    = self.stock.get(item_key, 50)
        scarcity = (1.0 + (self.SCARCITY_LOW - stock) / self.SCARCITY_LOW * 0.30
                    if stock < self.SCARCITY_LOW else 1.0)
        price = base * pressure * seasonal * scarcity
        if noise:
            price *= random.uniform(0.97, 1.03)
        return round(max(1.0, price), 2)

    def get_buy_price(self, item_key: str, season: Season, trading_skill: int = 1) -> float:
        mid    = self.get_price(item_key, season)
        markup = max(1.01, 1.08 - trading_skill * 0.01)
        return round(mid * markup, 2)

    def get_sell_price(self, item_key: str, season: Season, trading_skill: int = 1) -> float:
        mid      = self.get_price(item_key, season)
        discount = min(0.98, 0.92 + trading_skill * 0.01)
        return round(mid * discount, 2)

    # ── Transactions ─────────────────────────────────────────────────────────

    def buy_from_market(self, item_key: str, qty: int, season: Season, trading_skill: int = 1) -> float:
        if item_key not in self.item_keys:
            return -1.0
        if self.stock.get(item_key, 0) < qty:
            return -2.0
        price = self.get_buy_price(item_key, season, trading_skill)
        self.stock[item_key] -= qty
        impact = min(0.22, math.sqrt(qty) * self.BUY_IMPACT)
        self.pressure[item_key] = min(self.MAX_PRESSURE,
                                      self.pressure[item_key] + impact)
        return round(price * qty, 2)

    def sell_to_market(self, item_key: str, qty: int, season: Season, trading_skill: int = 1) -> float:
        if item_key not in self.item_keys:
            if self.area == Area.CITY:
                item = ALL_ITEMS.get(item_key)
                if not item:
                    return -1.0
                return round(item.base_price * 0.65 * qty, 2)
            return -1.0
        price = self.get_sell_price(item_key, season, trading_skill)
        # Cap stock so the market can't be infinitely flooded
        stock_cap = self.natural_stock[item_key] + 40
        self.stock[item_key] = min(stock_cap, self.stock.get(item_key, 0) + qty)
        impact = min(0.18, math.sqrt(qty) * self.SELL_IMPACT)
        self.pressure[item_key] = max(self.MIN_PRESSURE,
                                      self.pressure[item_key] - impact)
        return round(price * qty, 2)

    # ── Daily update ─────────────────────────────────────────────────────────

    def update(self, season: Season):
        """Called once per in-game day: restock, mean-revert pressure, history."""
        self.days_passed += 1
        for k in self.item_keys:
            # Mean-revert pressure toward natural value (~5 days to half-recover)
            nat = self.natural_pressure[k]
            self.pressure[k] += (nat - self.pressure[k]) * self.REVERT_RATE
            self.pressure[k]  = max(self.MIN_PRESSURE,
                                    min(self.MAX_PRESSURE, self.pressure[k]))

            # Deterministic daily production -- represents the local economy
            curr = self.stock.get(k, 0)
            cap  = self.natural_stock[k]
            if curr < cap:
                self.stock[k] = min(cap, curr + self.daily_restock[k])

            self.history[k].append(PricePoint(self.days_passed,
                                               self.get_price(k, season, noise=False)))

        if self.days_passed % 30 == 0 and self.active_events:
            self.active_events.pop(0)

        # WAR travel-risk bonus decays at 0.01/day
        if self.travel_risk_override > 0:
            self.travel_risk_override = max(0.0, self.travel_risk_override - 0.01)

    # ── Events ───────────────────────────────────────────────────────────────

    def apply_event(self, event: EventType):
        """Shift pressure for relevant items; daily reversion unwinds the effect."""
        self.active_events.append(event.value)
        if event == EventType.DROUGHT:
            for k in ["wheat", "barley", "cotton", "bread"]:
                if k in self.pressure:
                    self.pressure[k] = min(self.MAX_PRESSURE, self.pressure[k] * 1.5)
                    self.stock[k]    = max(0, int(self.stock.get(k, 0) * 0.6))
            # Drought also hits fermented goods (grapes and hops need water)
            for k in ["wine", "ale", "honey"]:
                if k in self.pressure:
                    self.pressure[k] = min(self.MAX_PRESSURE, self.pressure[k] * 1.2)
        elif event == EventType.FLOOD:
            for k in ["wheat", "barley", "cotton", "peat", "herbs"]:
                if k in self.pressure:
                    self.pressure[k] = min(self.MAX_PRESSURE, self.pressure[k] * 1.35)
                    self.stock[k]    = max(0, int(self.stock.get(k, 0) * 0.7))
            # Salt flats can be contaminated; rope hemp fields flood too
            for k in ["salt", "rope"]:
                if k in self.pressure:
                    self.pressure[k] = min(self.MAX_PRESSURE, self.pressure[k] * 1.15)
        elif event == EventType.BUMPER_HARVEST:
            for k in ["wheat", "barley", "cotton"]:
                if k in self.pressure:
                    self.pressure[k] = max(self.MIN_PRESSURE, self.pressure[k] * 0.65)
                    self.stock[k]    = min(self.natural_stock.get(k, 200),
                                          self.stock.get(k, 0) + 80)
            # Cheap grain flows downstream into processed foods
            for k in ["bread", "ale", "wine"]:
                if k in self.pressure:
                    self.pressure[k] = max(self.MIN_PRESSURE, self.pressure[k] * 0.85)
        elif event == EventType.MINE_COLLAPSE:
            for k in ["ore", "coal", "gem", "gold_dust"]:
                if k in self.pressure:
                    self.pressure[k] = min(self.MAX_PRESSURE, self.pressure[k] * 1.8)
                    self.stock[k]    = max(0, int(self.stock.get(k, 0) * 0.4))
        elif event == EventType.PIRACY:
            for k in ["fish", "salt", "rope", "blubber", "spice", "silk"]:
                if k in self.pressure:
                    self.pressure[k] = min(self.MAX_PRESSURE, self.pressure[k] * 1.3)
        elif event == EventType.TRADE_BOOM:
            # Luxury & processed goods benefit most; raw commodities get a milder lift
            _prime = {"gem", "jewelry", "silk", "perfume", "tapestry", "artifact",
                      "cloth", "steel", "glassware", "medicine", "leather", "paper",
                      "wine", "spice", "exotic_fruit", "honey"}
            for k in self.pressure:
                mult = 1.20 if k in _prime else 1.08
                self.pressure[k] = min(self.MAX_PRESSURE, self.pressure[k] * mult)
        elif event == EventType.PLAGUE:
            for k in ["medicine", "herbs"]:
                if k in self.pressure:
                    self.pressure[k] = min(self.MAX_PRESSURE, self.pressure[k] * 2.0)
                    self.stock[k]    = max(0, int(self.stock.get(k, 0) * 0.3))
        elif event == EventType.WAR:
            # "horse" removed — not a valid item key in the catalogue
            war_items = ["steel", "ore", "medicine", "smoked_meat",
                         "rope", "coal", "leather", "bread",
                         "gunpowder", "blackpowder"]
            for k in war_items:
                if k in self.pressure:
                    self.pressure[k] = min(self.MAX_PRESSURE, self.pressure[k] * 2.0)
                    self.stock[k] = max(0, int(self.stock.get(k, 0) * 0.5))
            # WAR raises local travel risk sharply for 10+ days
            self.travel_risk_override = min(0.65, self.travel_risk_override + 0.18)
        elif event == EventType.GOLD_RUSH:
            if "gold_dust" in self.pressure:
                self.pressure["gold_dust"] = max(self.MIN_PRESSURE,
                                                  self.pressure["gold_dust"] * 0.6)
                self.stock["gold_dust"] = min(self.natural_stock.get("gold_dust", 80),
                                              self.stock.get("gold_dust", 0) + 60)
            # Prospectors flood the area — they need food, rope, and ale
            for k in ["smoked_meat", "rope", "ale", "medicine"]:
                if k in self.pressure:
                    self.pressure[k] = min(self.MAX_PRESSURE, self.pressure[k] * 1.15)
        elif event == EventType.FESTIVAL:
            for k in ["ale", "wine", "spice", "jewelry", "tapestry", "silk",
                      "exotic_fruit", "honey", "perfume", "bread"]:
                if k in self.pressure:
                    self.pressure[k] = min(self.MAX_PRESSURE, self.pressure[k] * 1.45)


# ─────────────────────────────────────────────────────────────────────────────
# AVAILABLE BUSINESSES
# ─────────────────────────────────────────────────────────────────────────────

BUSINESS_CATALOGUE = {
    "farm":       {"name": "Wheat Farm",       "item": "wheat",      "rate": 12, "cost": 40,  "buy": 1200,  "area": Area.FARMLAND},
    "vineyard":   {"name": "Vineyard",          "item": "wine",       "rate": 4,  "cost": 60,  "buy": 1800,  "area": Area.FARMLAND},
    "brewery":    {"name": "Brewery",           "item": "ale",        "rate": 8,  "cost": 55,  "buy": 1500,  "area": Area.FARMLAND},
    "mine":       {"name": "Iron Mine",         "item": "ore",        "rate": 6,  "cost": 80,  "buy": 2200,  "area": Area.MOUNTAIN},
    "gem_mine":   {"name": "Gem Mine",          "item": "gem",        "rate": 2,  "cost": 90,  "buy": 3800,  "area": Area.MOUNTAIN},
    "coal_mine":  {"name": "Coal Mine",         "item": "coal",       "rate": 9,  "cost": 70,  "buy": 1800,  "area": Area.MOUNTAIN},
    "fishery":    {"name": "Fishery",           "item": "fish",       "rate": 10, "cost": 50,  "buy": 1400,  "area": Area.COAST},
    "saltworks":  {"name": "Saltworks",         "item": "salt",       "rate": 7,  "cost": 45,  "buy": 1200,  "area": Area.COAST},
    "lumber":     {"name": "Lumber Mill",       "item": "timber",     "rate": 8,  "cost": 55,  "buy": 1500,  "area": Area.FOREST},
    "herbalists": {"name": "Herbalist Garden",  "item": "herbs",      "rate": 5,  "cost": 45,  "buy": 1400,  "area": Area.FOREST},
    "tannery":    {"name": "Tannery",           "item": "leather",    "rate": 5,  "cost": 65,  "buy": 1650,  "area": Area.CITY},
    "glassworks": {"name": "Glassworks",        "item": "glassware",  "rate": 4,  "cost": 70,  "buy": 2100,  "area": Area.CITY},
    "smithy":     {"name": "Smithy",            "item": "steel",      "rate": 4,  "cost": 85,  "buy": 2700,  "area": Area.CITY},
    "apothecary": {"name": "Apothecary",        "item": "medicine",   "rate": 2,  "cost": 75,  "buy": 3000,  "area": Area.CITY},
    "spice_farm": {"name": "Spice Plantation",  "item": "spice",      "rate": 3,  "cost": 80,  "buy": 3300,  "area": Area.DESERT},
    "fur_station":{"name": "Fur Trading Post",  "item": "fur",        "rate": 5,  "cost": 60,  "buy": 1650,  "area": Area.TUNDRA},
}

def make_business(key: str, area: Area) -> Business:
    b = BUSINESS_CATALOGUE[key]
    return Business(
        key=key, name=b["name"], item_produced=b["item"],
        production_rate=b["rate"], daily_cost=b["cost"],
        purchase_cost=b["buy"], area=area
    )

# ─────────────────────────────────────────────────────────────────────────────
# RANDOM EVENTS
# ─────────────────────────────────────────────────────────────────────────────

RANDOM_EVENTS = [
    (EventType.DROUGHT,        ["FARMLAND"],                   0.06),
    (EventType.FLOOD,          ["FARMLAND","SWAMP","COAST"],   0.05),
    (EventType.BUMPER_HARVEST, ["FARMLAND"],                   0.07),
    (EventType.MINE_COLLAPSE,  ["MOUNTAIN"],                   0.04),
    (EventType.PIRACY,         ["COAST"],                      0.06),
    (EventType.TRADE_BOOM,     ["CITY"],                       0.05),
    (EventType.PLAGUE,         ["CITY","FARMLAND"],            0.04),
    (EventType.WAR,            ["MOUNTAIN","DESERT"],          0.04),
    (EventType.GOLD_RUSH,      ["MOUNTAIN","DESERT"],          0.03),
    (EventType.FESTIVAL,       ["CITY","FARMLAND","COAST"],    0.06),
]

# News headlines keyed to event type name (+ "NEUTRAL" filler pool)
NEWS_POOL: Dict[str, List[str]] = {
    "DROUGHT": [
        "Crops withering across the farmlands as wells run dry.",
        "Bakers brace for shortage — grain deliveries down sharply.",
        "A third consecutive dry week has farmers abandoning outlying fields.",
        "Livestock markets quiet; feed prices the talk of every inn.",
    ],
    "FLOOD": [
        "Swollen rivers swamp the low fields — harvest uncertain this season.",
        "Roads to the southern farms are washed out; deliveries badly delayed.",
        "Mill wheel spinning in reverse, they say. Mud everywhere you step.",
        "Flood waters receding, but the cotton crop is all but ruined.",
    ],
    "BUMPER_HARVEST": [
        "Record yields across the farmlands — warehouses already full.",
        "Grain merchants uneasy as prices dip: more wheat than buyers.",
        "A bumper season: barley so cheap farmers can barely cover costs.",
        "Local granaries turning away deliveries. Stack it cheap while it lasts.",
    ],
    "MINE_COLLAPSE": [
        "A section of the main shaft has caved in — ore deliveries halted.",
        "Mining guild posts reward for engineers: deep tunnels in crisis.",
        "Iron ore all but vanished from market shelves overnight.",
        "Smithies idle as the mountain yields nothing but silence and dust.",
    ],
    "PIRACY": [
        "Three merchant vessels seized off the cape — goods never arrived.",
        "Coast road patrols doubled after another ambush near the bay.",
        "Rope and salt scarce; captains refuse to sail without armed escort.",
        "Investors pulling coin from shipping ventures amid rising piracy fears.",
    ],
    "TRADE_BOOM": [
        "Guild quarter alive with activity — buying frenzy since dawn.",
        "Merchants pouring in from every road. Inns booked out for weeks.",
        "Every stall in the market square sold out well before midday.",
        "The coin is flowing! Even the beggars seem better dressed than usual.",
    ],
    "PLAGUE": [
        "City healers overwhelmed — apothecaries sold out of everything useful.",
        "Herb pickers commanded to work round the clock by the council's order.",
        "Worried faces on every street. Medicine selling for extraordinary prices.",
        "Quarantine notices posted at the north gate. Normal trade disrupted.",
    ],
    "WAR": [
        "Skirmishes reported at the border passes — mountain trade moving slowly.",
        "Military requisitions have cleared half the city's steel stocks overnight.",
        "Surgeons needed at the front; medicine supplies quietly vanishing.",
        "Soldiers marching through: they pay well but carry nothing useful back.",
    ],
    "GOLD_RUSH": [
        "Word of a new vein has every prospector heading for the hills.",
        "Gold dust flowing freely — prices softening as sellers abound.",
        "Mountain towns crowded with fortune-seekers. Easy trade for food and tools.",
        "Assay office swamped; gold claims filed by the hundreds this week.",
    ],
    "FESTIVAL": [
        "The Grand Festival fills the city with merrymakers and loose coin.",
        "Silk and wine disappear from shelves before noon. Come early.",
        "Taverns emptied of ale, spice merchants grinning ear to ear.",
        "Luxury vendors can't keep shelves stocked — demand is relentless.",
    ],
    "NEUTRAL": [
        "Council debate over road taxes drags into its third week.",
        "Nothing of note out of the east. Quiet roads, quiet trade.",
        "A merchant from the far south passed through — odd spices, stranger prices.",
        "Weather: mild. Markets: unremarkable. A fine day to plan ahead.",
        "Thieves' guild supposedly disbanded. Three wallets stolen this morning.",
        "Traveling acrobats in town. Commerce can wait until evening.",
        "The river ran brown last night. Nobody knows why. Nobody's asking.",
        "Old Tobias the cartwright finally retired. His sons, less skilled.",
        "Rumours of a new trade route — nothing confirmed, everything speculated.",
        "A shipment of glassware smashed somewhere between here and the coast.",
        "City watch turned away a suspicious caravan at the south gate.",
        "Scholars claim this winter will be harsh. Grain merchants seem pleased.",
        "Two trading posts changed hands this week. Prices unchanged, for now.",
        "A courier arrived from the capital with sealed letters. Sealed tightly.",
        # comedic additions
        "Local fortune-teller predicts 'great commerce.' Charges double for the prediction.",
        "Man found asleep in grain storage. Claims he is 'market research.'",
        "Rat spotted in a merchant's stall. Customer claims it was 'negotiating.'",
        "Tavern brawl blamed on bad ale. Brewer insists the ale was fine. The brawl disagrees.",
        "Dog chased a cart of fish through the square. Most of the fish recaptured.",
        "Printer's apprentice accidentally posted wrong prices on half the market stalls.",
        "A philosopher arrived in town asking what 'true value' means. Nobody bought anything for an hour.",
        "Merchant caught selling 'aged cheese' that was simply left in the sun for a week.",
        "Guild treasurer cannot account for 14 gold. Suspects the bookkeeper. Bookkeeper suspects the treasurer.",
        "Noted town drunk correctly predicted last week's grain shortage. Now considered an oracle.",
        "City watch issued new uniforms. Criminals still easier to spot.",
        "A cart of salt overturned on the east road. Locals declared it 'free seasoning.'",
        "Beekeeper reports record honey yield. Also reports record number of stings.",
        "Shipwright's assistant miscounted boards. New dock wobbles slightly but stands.",
        "Cook at the Gilded Spoon inn won a bet that nobody could finish the 'merchant's platter.' The bet was 2g. The platter cost 3g.",
        "Local alderman demands cleaner streets. Merchants moved their rubbish one street over.",
        "A goat escaped from the livestock pen and briefly held a stall for ransom.",
        "Apprentice healer administered the wrong remedy. Patient felt 'surprisingly good about it.'",
        "Merchant insists his new rope is 'stronger than steel.' Bridge inspector disagrees.",
        "Fisherman claims to have caught a talking fish. He ate it. 'It didn't say much,' he reports.",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# INVENTORY
# ─────────────────────────────────────────────────────────────────────────────

class Inventory:
    def __init__(self, gold: float = 500.0):
        self.items:      Dict[str, int]   = {}
        self.cost_basis: Dict[str, float] = {}  # weighted-average price paid per unit
        self.gold = gold

    def add(self, key: str, qty: int):
        self.items[key] = self.items.get(key, 0) + qty

    def record_purchase(self, key: str, qty: int, price_per_unit: float):
        """Update weighted-average cost basis after a purchase."""
        old_qty  = self.items.get(key, 0)
        old_cost = self.cost_basis.get(key, price_per_unit)
        new_qty  = old_qty + qty
        self.cost_basis[key] = (old_cost * old_qty + price_per_unit * qty) / max(new_qty, 1)

    def remove(self, key: str, qty: int) -> bool:
        if self.items.get(key, 0) >= qty:
            self.items[key] -= qty
            if self.items[key] == 0:
                del self.items[key]
                self.cost_basis.pop(key, None)
            return True
        return False

    def has(self, key: str, qty: int = 1) -> bool:
        return self.items.get(key, 0) >= qty

    def total_weight(self, max_carry: float) -> Tuple[float, float]:
        w = sum(ALL_ITEMS[k].weight * v for k, v in self.items.items() if k in ALL_ITEMS)
        return round(w, 1), max_carry

    def display(self, max_carry: float):
        print(header("INVENTORY"))
        if not self.items:
            print(c("  (empty)", GREY))
        else:
            cats: Dict[str, List] = {}
            for k, qty in sorted(self.items.items()):
                item = ALL_ITEMS.get(k)
                if not item:
                    continue
                cat = item.category.value
                cats.setdefault(cat, []).append((item, qty, k))
            print(f"  {BOLD}{'Item':<25} {'Qty':>5}  {'Paid/ea':>10}  {'Total cost':>12}{RESET}")
            print(f"  {GREY}{'─' * 58}{RESET}")
            for cat, entries in sorted(cats.items()):
                print(f"\n  {BOLD}{YELLOW}{cat}{RESET}")
                for item, qty, k in entries:
                    illegal_tag = c(" [!]", RED) if item.illegal else ""
                    avg_cost    = self.cost_basis.get(k)
                    cost_str    = f"{avg_cost:.1f}g/ea" if avg_cost else "  ─"
                    total_str   = f"{avg_cost * qty:.0f}g" if avg_cost else "  ─"
                    print(f"  {item.name + illegal_tag:<28} {qty:>5}  "
                          f"{c(cost_str, GREY):>18}  {c(total_str, GREY):>20}")
        w, cap = self.total_weight(max_carry)
        bar_fill = int((w / max(cap, 1)) * 20)
        bar = c("█" * bar_fill, YELLOW if w < cap * 0.8 else RED) + c("░" * (20 - bar_fill), GREY)
        print(f"\n  Weight: [{bar}] {w}/{cap}   Gold: {c(f'{self.gold:.2f}', YELLOW)}")

# ─────────────────────────────────────────────────────────────────────────────
# VOYAGE SYSTEM  —  Ships, Captains, and International Trade
# ─────────────────────────────────────────────────────────────────────────────

SHIP_TYPES: Dict[str, Dict] = {
    "sloop":      {"name": "Sloop",      "cargo": 40,  "base_days": (30, 40), "piracy_risk": 0.08, "wreck_risk": 0.05, "cost": 2500},
    "brigantine": {"name": "Brigantine", "cargo": 80,  "base_days": (35, 50), "piracy_risk": 0.07, "wreck_risk": 0.06, "cost": 5000},
    "galleon":    {"name": "Galleon",    "cargo": 160, "base_days": (40, 60), "piracy_risk": 0.06, "wreck_risk": 0.07, "cost": 9000},
    "carrack":    {"name": "Carrack",    "cargo": 120, "base_days": (38, 55), "piracy_risk": 0.05, "wreck_risk": 0.08, "cost": 7000},
}

SHIP_UPGRADES: Dict[str, Dict] = {
    "reinforced_hull": {"name": "Reinforced Hull", "cost": 600, "wreck_mult": 0.55, "desc": "Iron plating reduces shipwreck risk."},
    "cannon_battery":  {"name": "Cannon Battery",  "cost": 800, "piracy_mult": 0.50, "desc": "Mounted guns deter pirates."},
    "speed_rigging":   {"name": "Speed Rigging",   "cost": 500, "days_mult":   0.80, "desc": "Superior sails cut voyage duration by 20%."},
    "merchant_flag":   {"name": "Merchant Flag",   "cost": 300, "piracy_mult": 0.70, "profit_mult": 1.05, "desc": "Guild flag reduces piracy, boosts prices."},
    "expanded_hold":   {"name": "Expanded Hold",   "cost": 700, "cargo_bonus": 40,   "desc": "Extra storage adds 40 cargo capacity."},
}

VOYAGE_PORTS: Dict[str, Dict] = {
    "al_rashid":   {"name": "Port Al-Rashid", "days_mod": 1.0, "profit_mult": {"LUXURY": 1.8, "FOOD": 1.5, "RAW_MATERIAL": 1.2}},
    "veldtholm":   {"name": "Veldtholm",      "days_mod": 0.9, "profit_mult": {"RAW_MATERIAL": 1.9, "PROCESSED": 1.6, "LUXURY": 1.3}},
    "port_aureus": {"name": "Port Aureus",    "days_mod": 1.2, "profit_mult": {"LUXURY": 2.2, "EQUIPMENT": 1.8, "FOOD": 1.4}},
    "ironreach":   {"name": "Ironreach",      "days_mod": 1.1, "profit_mult": {"EQUIPMENT": 2.0, "PROCESSED": 1.7, "RAW_MATERIAL": 1.5}},
    "sundara":     {"name": "Sundara",        "days_mod": 1.3, "profit_mult": {"LUXURY": 2.5, "FOOD": 1.9, "PROCESSED": 1.6}},
    "coldwater":   {"name": "Coldwater",      "days_mod": 0.8, "profit_mult": {"RAW_MATERIAL": 1.7, "FOOD": 1.6, "EQUIPMENT": 1.5}},
}

_CAPTAIN_FIRST  = ["Edmund", "Silas", "Aldric", "Torben", "Margret", "Fenwick",
                    "Caelum", "Drest", "Gilda", "Oric", "Vesper", "Halvard",
                    "Britta", "Cormac", "Theron", "Isolde", "Roric", "Beatrix"]
_CAPTAIN_LAST   = ["Saltmere", "Wavecrest", "Drake", "Hornsby", "Brine",
                    "Fairweather", "Stormwall", "Ironkeel", "Thatcher",
                    "Blackwater", "Coldwind", "Hartley", "Dunmore", "Reefshire"]
_CAPTAIN_TITLES = ["Captain", "Admiral", "Commodore", "Navigator", "Skipper"]

_SHIP_NAME_PREFIXES = ["Swift", "Iron", "Golden", "Sea", "Storm", "Silver", "Brave", "Proud"]
_SHIP_NAME_SUFFIXES = ["Wind", "Wave", "Dawn", "Star", "Crest", "Tide", "Anchor", "Gull"]


@dataclass
class Ship:
    id: int
    ship_type: str
    name: str
    upgrades: List[str] = field(default_factory=list)
    status: str = "docked"           # "docked" | "sailing"
    voyage_id: Optional[int] = None

    @property
    def cargo_capacity(self) -> int:
        return SHIP_TYPES[self.ship_type]["cargo"] + sum(
            SHIP_UPGRADES[u].get("cargo_bonus", 0) for u in self.upgrades
        )

    @property
    def piracy_risk(self) -> float:
        m = 1.0
        for u in self.upgrades:
            m *= SHIP_UPGRADES[u].get("piracy_mult", 1.0)
        return SHIP_TYPES[self.ship_type]["piracy_risk"] * m

    @property
    def wreck_risk(self) -> float:
        m = 1.0
        for u in self.upgrades:
            m *= SHIP_UPGRADES[u].get("wreck_mult", 1.0)
        return SHIP_TYPES[self.ship_type]["wreck_risk"] * m

    @property
    def days_mult(self) -> float:
        m = 1.0
        for u in self.upgrades:
            m *= SHIP_UPGRADES[u].get("days_mult", 1.0)
        return m

    @property
    def profit_mult(self) -> float:
        m = 1.0
        for u in self.upgrades:
            m *= SHIP_UPGRADES[u].get("profit_mult", 1.0)
        return m


@dataclass
class Captain:
    id: int
    name: str
    title: str
    navigation: int    # 1–5
    combat: int        # 1–5
    seamanship: int    # 1–5
    charisma: int      # 1–5
    wage_per_voyage: float
    crew_wage: float
    is_hired: bool = False

    @property
    def day_reduction(self) -> float:
        return (self.navigation - 1) * 0.05

    @property
    def piracy_mult(self) -> float:
        return max(0.40, 1.0 - (self.combat - 1) * 0.12)

    @property
    def wreck_mult(self) -> float:
        return max(0.40, 1.0 - (self.seamanship - 1) * 0.12)

    @property
    def profit_mult(self) -> float:
        return 1.0 + (self.charisma - 1) * 0.08


@dataclass
class Voyage:
    id: int
    ship_id: int
    ship_name: str
    captain_id: int
    captain_name: str
    destination_key: str
    cargo: Dict[str, int]      # item_key → qty
    cargo_cost: float
    days_total: int
    days_remaining: int
    status: str = "sailing"    # "sailing" | "arrived" | "lost_piracy" | "lost_wreck"
    outcome_gold: float = 0.0
    outcome_text: str = ""
    departure_day: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# MAIN GAME CLASS
# ─────────────────────────────────────────────────────────────────────────────

class Game:
    SAVE_FILE            = os.path.join(_USER_DATA_DIR, "savegame.dat")
    DAYS_PER_SEASON      = 30
    SEASONS_PER_YEAR     = 4
    DAILY_TIME_UNITS     = 6     # activity slots per in-game day before night falls
    BASE_LIVING_COST     = 18.0  # base gold/day (was 12; harder baseline)

    def __init__(self):
        self.settings       = GameSettings()
        self.settings.load()
        self.player_name    = "Merchant"
        self.current_area   = Area.CITY
        self.inventory      = Inventory(gold=750.0)
        self.markets        = {area: AreaMarket(area) for area in Area}
        self.businesses: List[Business] = []
        self.skills         = PlayerSkills()
        self.contracts: List[Contract] = []
        self.loans: List[LoanRecord]   = []
        self.cds:   List[CDRecord]     = []
        self.day            = 1
        self.year           = 1
        self.season         = Season.SPRING
        self.bank_balance   = 0.0
        self.bank_interest_rate = 0.05
        self.reputation     = 50        # 0–100; affects contract quality, guard suspicion
        self.heat           = 0         # 0–100; accumulated from smuggling
        self.net_worth_history: List[float] = []
        self.trade_log: deque = deque(maxlen=50)
        self.event_log: deque = deque(maxlen=20)
        self.news_feed: deque = deque(maxlen=15)  # (abs_day, area_name, event, headline)
        self.total_profit   = 0.0
        self.lifetime_trades = 0
        self.next_contract_id  = 1
        self.daily_time_units  = 0   # slots used so far today
        self.bodyguard_hired   = False   # hired for next journey only
        self.running           = True
        self._max_carry        = 100.0  # updated from skills
        # ── New systems ───────────────────────────────────────────────────
        self.licenses: set      = {LicenseType.MERCHANT}  # only basic trading rights by default
        self.citizen_loans: List[CitizenLoan] = []
        self.next_citizen_loan_id: int = 1
        self.stock_holdings: Dict[str, StockHolding] = {}   # symbol → StockHolding
        self.business_manager: Optional[BusinessManagerRecord] = None
        self.stock_market: StockMarket = StockMarket()
        self.fund_clients: List[FundClient] = []
        self.next_fund_client_id: int = 1
        # ── Real Estate ───────────────────────────────────────────────────
        self.real_estate: List[Property] = []
        self.land_plots: List[LandPlot]  = []
        self.next_property_id: int = 1
        self.next_plot_id: int     = 1
        self._re_listings_cache: List[Dict] = []   # cached area listings
        self._re_listings_area:  str        = ""   # area name those listings were for
        # ── NPC Managers ──────────────────────────────────────────────────
        self.hired_managers: List[HiredManager] = []
        self._manager_action_log: deque = deque(maxlen=100)  # detailed action log
        # ── Achievements ──────────────────────────────────────────────────
        self.achievements: set  = set()   # unlocked achievement IDs
        self.ach_queue: list    = []       # IDs pending display
        self.ach_stats: dict    = {
            "areas_visited":       [],    # list of area-name strings seen
            "smuggle_success":     0,
            "smuggle_busts":       0,
            "smuggle_gold":        0.0,
            "contracts_completed": 0,
            "contracts_ontime":    0,
            "contracts_failed":    0,
            "contracts_streak":    0,    # consecutive on-time fulfillments
            "max_contract_bonus":  0.0,
            "contract_close_call": False,
            "journeys":            0,
            "travel_days":         0,
            "loans_taken":         0,
            "loans_repaid":        0,
            "bribes":              0,
            "help_presses":        0,
            "repairs":             0,
            "lucky_finds":         0,
            "attacks_suffered":    0,
            "events_triggered":    0,
            "max_single_sale":     0.0,
            "fund_fees":           0.0,
            "stock_profit":        0.0,
            "sold_at_loss":        False,
            "wait_streak":         0,
            "war_ore_sold":        0,
            "plague_medicine_sold":0,
            "rep_recovered":       False,
            "rep_hit_zero":        False,
            "rep_floor_tracking":  False,  # True once rep has been <20
            "went_negative":       False,
            "licenses_purchased":  0,
            "license_bought_broke": False,
            # ── Real Estate ──────────────────────────────────────────────
            "re_properties_owned": 0,   # lifetime total acquired
            "re_properties_sold":  0,
            "re_flip_profit":      0.0, # total profit from flipping
            "re_max_flip_profit":  0.0, # best single flip
            "re_leases_active":    0,   # snapshot updated daily
            "re_lease_income":     0.0, # lifetime total from leases
            "re_builds_completed": 0,
            "re_upgrades_applied": 0,
            "re_properties_areas": [],  # area names of owned properties (dedup list)
            "re_derelict_flip":    False,
            # ── Influence operations ─────────────────────────────────────
            "campaigns_run":       0,
            "slanders_run":        0,
            "max_campaign_gold":   0.0,
            # ── Voyage ───────────────────────────────────────────────────
            "voyages_completed":   0,
            "voyages_lost":        0,
            "voyage_gold_earned":  0.0,
        }
        self.influence_cooldowns: Dict[str, int] = {}  # "{area}:{item}:{action}" → expiry abs_day
        # ── Voyage system ─────────────────────────────────────────────────
        self.ships: List[Ship]       = []
        self.captains: List[Captain] = []
        self.voyages: List[Voyage]   = []
        self.next_ship_id:    int    = 1
        self.next_captain_id: int    = 1
        self.next_voyage_id:  int    = 1
        self._generate_captains()

    def _generate_captains(self) -> None:
        """Generate a pool of 6 hireable captains at game start."""
        self.captains = []
        self.next_captain_id = 1
        used_names: set = set()
        for _ in range(6):
            for _attempt in range(20):
                first = random.choice(_CAPTAIN_FIRST)
                last  = random.choice(_CAPTAIN_LAST)
                if (first, last) not in used_names:
                    used_names.add((first, last))
                    break
            title = random.choice(_CAPTAIN_TITLES)
            nav   = random.randint(1, 5)
            com   = random.randint(1, 5)
            sea   = random.randint(1, 5)
            cha   = random.randint(1, 5)
            wage  = round(50 + (nav + com + sea + cha) * 8 + random.uniform(-10, 10), 0)
            crew  = round(20 + random.uniform(0, 15), 0)
            self.captains.append(Captain(
                id=self.next_captain_id,
                name=f"{first} {last}",
                title=title,
                navigation=nav, combat=com, seamanship=sea, charisma=cha,
                wage_per_voyage=wage,
                crew_wage=crew,
                is_hired=False,
            ))
            self.next_captain_id += 1

    def _living_cost(self) -> float:
        """Living cost fluctuates daily ±30%, scaled by difficulty."""
        fluctuation = random.uniform(0.70, 1.30)
        return round(self.BASE_LIVING_COST * fluctuation * self.settings.cost_mult, 2)

    def _sell_mult(self) -> float:
        """Effective sell-price multiplier: difficulty × reputation penalty."""
        rep_penalty = 1.0
        if self.reputation < 40:
            # Linear penalty: rep 0→0.78, rep 20→0.87, rep 40→1.0
            rep_penalty = 0.78 + (self.reputation / 40.0) * 0.22
        return round(self.settings.price_sell_mult * rep_penalty, 4)

    # ── Achievement System ───────────────────────────────────────────────────

    def _track_stat(self, key: str, amount=1) -> None:
        """Update an ach_stats counter, bool, or list."""
        if key not in self.ach_stats:
            return
        current = self.ach_stats[key]
        if isinstance(current, bool):
            self.ach_stats[key] = bool(amount)
        elif isinstance(current, list):
            if amount not in current:
                current.append(amount)
        else:
            self.ach_stats[key] = current + amount

    def _check_achievements(self) -> None:
        """Unlock any newly met achievements and push them to the queue."""
        for ach in ACHIEVEMENTS:
            if ach["id"] in self.achievements:
                continue
            try:
                if ach["check"](self):
                    self.achievements.add(ach["id"])
                    self.ach_queue.append(ach["id"])
            except Exception:
                pass

    def _display_achievement_queue(self) -> None:
        """Print the box-art unlock banner for every queued achievement."""
        if not self.ach_queue:
            return
        import textwrap as _tw
        TIER_COL = {
            "bronze":   YELLOW,
            "silver":   WHITE,
            "gold":     YELLOW,
            "platinum": CYAN,
            "":         GREEN,
        }
        for aid in list(self.ach_queue):
            ach = ACHIEVEMENTS_BY_ID.get(aid)
            if not ach:
                continue
            tc     = TIER_COL.get(ach.get("tier", ""), CYAN)
            tier_s = f"  [{ach['tier'].upper()}]" if ach.get("tier") else ""
            name_s = ach["name"]
            desc_s = ach.get("desc", "")
            hint_s = ach.get("hint", "")
            icon_s = ach.get("icon", "★")
            w     = 60
            inner = w - 2          # 58 printable chars per row
            pfx   = "   "          # 3-space indent inside the box
            txt_w = inner - len(pfx)   # usable text width per line

            def _row(text, colour=None):
                # pad to exactly `inner` visible chars (no truncation — caller wraps)
                padded = text.ljust(inner)
                if colour:
                    return f"  {c('║', YELLOW)}{c(padded, colour)}{c('║', YELLOW)}"
                return f"  {c('║', YELLOW)}{padded}{c('║', YELLOW)}"

            def _wrap_rows(text, prefix=pfx, colour=None):
                usable = inner - len(prefix)
                lines  = _tw.wrap(text, width=usable) or [""]
                return [_row(prefix + line, colour) for line in lines]

            print()
            print(f"  {c('╔' + '═' * inner + '╗', YELLOW)}")
            print(_row(f" {icon_s} ACHIEVEMENT UNLOCKED!", BOLD + YELLOW))
            print(f"  {c('╠' + '═' * inner + '╣', YELLOW)}")
            # Name + tier badge
            for row in _wrap_rows(f"{name_s}{tier_s}", prefix=pfx, colour=BOLD + tc):
                print(row)
            # Description (full, word-wrapped)
            for row in _wrap_rows(desc_s):
                print(row)
            # Hint / flavor text (shown dimmed, only when meaningful)
            if hint_s and hint_s != "???":
                print(_row(""))
                for row in _wrap_rows(f'"{hint_s}"', colour=DIM):
                    print(row)
            print(f"  {c('╚' + '═' * inner + '╝', YELLOW)}")
        self.ach_queue.clear()
        pause()

    def achievements_menu(self) -> None:
        """Display all achievements with unlock status."""
        TIER_COL = {"bronze": YELLOW, "silver": WHITE, "gold": YELLOW, "platinum": CYAN, "": GREEN}
        while True:
            header("ACHIEVEMENTS")
            total   = len(ACHIEVEMENTS)
            unlocked = len(self.achievements)
            print(f"  Progress: {c(str(unlocked), CYAN)}/{c(str(total), WHITE)} unlocked\n")

            # Group by a simple category derived from first underscore prefix
            cats = {}
            for ach in ACHIEVEMENTS:
                aid = ach["id"]
                # derive a readable category from the tier/icon or id
                if   aid.startswith(("first_trade","trades_","profit_","big_sale","sell_at_loss")):
                    cat = "Trading"
                elif aid.startswith(("worth_","bank_")):
                    cat = "Wealth"
                elif aid.startswith(("first_business","biz_","hire_","manager_","full_","all_biz")):
                    cat = "Business"
                elif aid.startswith(("skill_","all_skills","max_esp","max_log","max_bank")):
                    cat = "Skills"
                elif aid.startswith(("areas_","journey_","travel_")):
                    cat = "Exploration"
                elif aid.startswith(("first_smuggle","smuggle_","hot_","phantom","bribe_")):
                    cat = "Smuggling"
                elif aid.startswith(("first_contract","contract","deadlines_")):
                    cat = "Contracts"
                elif aid.startswith(("first_loan","loans_","cd_","first_citizen","citizen_","lender_","loan_d")):
                    cat = "Banking"
                elif aid.startswith(("first_stock","stocks_","stock_","diamond_","first_fund","fund_")):
                    cat = "Finance"
                elif aid.startswith(("first_extra","all_licenses","broke_buy")):
                    cat = "Licenses"
                elif aid.startswith(("re_",)):
                    cat = "Real Estate"
                elif aid.startswith(("influence_",)):
                    cat = "Influence"
                elif aid.startswith(("rep_",)):
                    cat = "Reputation"
                else:
                    cat = "Special"
                cats.setdefault(cat, []).append(ach)

            for cat_name, achs in cats.items():
                cat_done  = sum(1 for a in achs if a["id"] in self.achievements)
                print(f"  {c(cat_name, BOLD + WHITE)}  {c(f'{cat_done}/{len(achs)}', GREY)}")
                for ach in achs:
                    aid      = ach["id"]
                    unlck    = aid in self.achievements
                    hidden   = ach.get("hidden", False)
                    tier_s   = f"[{ach['tier'].upper()}] " if ach.get("tier") else ""
                    tier_col = TIER_COL.get(ach.get("tier", ""), GREEN)
                    if unlck:
                        line = f"    {c('✓', GREEN)} {c(tier_s + ach['name'], tier_col)}  — {ach['desc'][:48]}"
                    elif hidden:
                        line = f"    {c('?', GREY)} {c('??? (hidden)', GREY)}"
                    else:
                        line = f"    {c('○', GREY)} {c(tier_s + ach['name'], GREY)}  — {ach['hint'][:48]}"
                    print(line)
                print()

            print(f"  [{c('B', CYAN)}] Back")
            ch = prompt("").strip().upper()
            if ch in ("B", ""):
                break

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _day_of_year(self) -> int:
        return self.day

    def _absolute_day(self) -> int:
        return (self.year - 1) * 360 + self.day

    def _season_from_day(self) -> Season:
        idx = ((self.day - 1) // self.DAYS_PER_SEASON) % self.SEASONS_PER_YEAR
        return list(Season)[idx]

    def _max_carry_weight(self) -> float:
        return 100.0 + self.skills.logistics * 20.0

    def _current_weight(self) -> float:
        return sum(ALL_ITEMS[k].weight * v for k, v in self.inventory.items.items() if k in ALL_ITEMS)

    def _net_worth(self) -> float:
        nw = self.inventory.gold + self.bank_balance + self._portfolio_value()
        for k, qty in self.inventory.items.items():
            item = ALL_ITEMS.get(k)
            if item:
                nw += item.base_price * qty
        for b in self.businesses:
            nw += b.purchase_cost * b.level * 0.7
        for loan in self.loans:
            nw -= loan.principal
        # Citizen loans as assets
        for cl in self.citizen_loans:
            if not cl.defaulted and cl.weeks_remaining > 0:
                nw += cl.weekly_payment * cl.weeks_remaining
        # Fund client obligations as liabilities
        for fc in self.fund_clients:
            if not fc.withdrawn:
                nw -= fc.capital * (1 + fc.promised_rate)
        # Real estate at current appraised value
        for prop in self.real_estate:
            if not prop.under_construction:
                nw += prop.current_value
        # Land plots at cost + modest appreciation
        for plot in self.land_plots:
            nw += plot.purchase_price * 1.05
        return round(nw, 2)

    def _portfolio_value(self) -> float:
        """Current market value of all stock holdings."""
        return round(sum(
            h.shares * self.stock_market.stocks[sym]["price"]
            for sym, h in self.stock_holdings.items()
            if sym in self.stock_market.stocks
        ), 2)

    def _can_buy_license(self, lt: LicenseType) -> bool:
        info = LICENSE_INFO[lt]
        return (self.reputation  >= info["rep"]
                and self.skills.banking >= info["banking"]
                and lt not in self.licenses)

    def _manager_daily_actions(self):
        """Run once per day when a business manager is employed."""
        mgr = self.business_manager
        mgr.days_employed += 1
        # Auto-repair broken businesses
        if mgr.auto_repair:
            for b in self.businesses:
                if b.broken_down and self.inventory.gold >= b.repair_cost:
                    self.inventory.gold -= b.repair_cost
                    b.broken_down = False
                    b.repair_cost = 0.0
                    mgr.total_repairs += 1
                    self._log_event(f"[Mgr] Auto-repaired {b.name}")
        # Auto-hire workers to fill empty slots
        if mgr.auto_hire:
            for b in self.businesses:
                if not b.broken_down:
                    while b.workers < b.max_workers:
                        candidates = self._generate_applicants(3)
                        best = max(candidates,
                                   key=lambda x: x["productivity"] / max(x["wage"], 0.1))
                        b.hired_workers.append(best)
                        b.workers = len(b.hired_workers)
                        mgr.total_hires += 1
        # Auto-sell accumulated production
        if mgr.auto_sell:
            for b in self.businesses:
                key = b.item_produced
                qty = self.inventory.items.get(key, 0)
                if qty >= 10:
                    mkt = self.markets[self.current_area]
                    if key in mkt.item_keys:
                        earnings = mkt.sell_to_market(key, qty, self.season,
                                                       self.skills.trading)
                        if earnings > 0:
                            self.inventory.remove(key, qty)
                            self.inventory.gold += earnings
                            mgr.total_sold_value += earnings
        # Weekly wage
        if mgr.days_employed % 7 == 0:
            if self.inventory.gold >= mgr.wage_per_week:
                self.inventory.gold -= mgr.wage_per_week
            else:
                warn(f"Can't pay manager {mgr.name}'s wages — manager quits!")
                self.business_manager = None

    # ── NPC Manager System ────────────────────────────────────────────────────

    def _mgr_log(self, mgr: "HiredManager", msg: str) -> None:
        """Log a manager action to both the manager action log and trade log."""
        abs_day = self._absolute_day()
        full = f"[Y{self.year} D{self.day}] [{mgr.name} L{mgr.level}] {msg}"
        self._manager_action_log.appendleft(full)
        self._log_trade(f"[{mgr.name}] {msg}")
        mgr.stats["last_action_day"]  = abs_day
        mgr.stats["last_action_desc"] = msg

    def _mgr_award_xp(self, mgr: "HiredManager", amount: int) -> None:
        """Award XP; announce level-ups in the game log."""
        levelled = mgr.add_xp(amount)
        if levelled:
            self._mgr_log(mgr, f"LEVEL UP → Lv{mgr.level}! Efficiency now {mgr.efficiency*100:.0f}%")

    def _run_hired_managers(self) -> None:
        """Called once per day from _advance_day to run all hired managers."""
        fired: List["HiredManager"] = []
        for mgr in self.hired_managers:
            if not mgr.is_active:
                continue
            mgr.days_employed += 1
            # Weekly wage deduction
            if mgr.days_employed % 7 == 0:
                wage = mgr.weekly_wage * self.settings.cost_mult
                if self.inventory.gold >= wage:
                    self.inventory.gold -= wage
                    mgr.stats["total_wages_paid"] += wage
                    mgr.stats["total_gold_cost"]  += wage
                else:
                    self._mgr_log(mgr, "Wages unpaid — manager quits!")
                    self._log_event(f"Manager {mgr.name} quit — wages unpaid")
                    fired.append(mgr)
                    continue
            # Dispatch to the correct action handler
            mt = mgr.manager_type
            if   mt == ManagerType.BUSINESS_FOREMAN.value:  self._mgr_business_foreman(mgr)
            elif mt == ManagerType.TRADE_STEWARD.value:     self._mgr_trade_steward(mgr)
            elif mt == ManagerType.PROPERTY_STEWARD.value:  self._mgr_property_steward(mgr)
            elif mt == ManagerType.CONTRACT_AGENT.value:    self._mgr_contract_agent(mgr)
            elif mt == ManagerType.LENDING_ADVISOR.value:   self._mgr_lending_advisor(mgr)
            elif mt == ManagerType.INVESTMENT_BROKER.value: self._mgr_investment_broker(mgr)
            elif mt == ManagerType.FUND_CUSTODIAN.value:    self._mgr_fund_custodian(mgr)
            elif mt == ManagerType.CAMPAIGN_HANDLER.value:  self._mgr_campaign_handler(mgr)
            elif mt == ManagerType.SMUGGLING_HANDLER.value: self._mgr_smuggling_handler(mgr)
        for mgr in fired:
            self.hired_managers.remove(mgr)

    # ── Per-manager action methods ────────────────────────────────────────────

    def _mgr_business_foreman(self, mgr: "HiredManager") -> None:
        """Repairs breakdowns, optionally fires underperformers, and fills worker slots."""
        cfg = mgr.config
        eff = mgr.efficiency
        # ── Auto-repair broken businesses ────────────────────────────────
        if cfg.get("auto_repair", True):
            threshold = cfg.get("repair_threshold", 500.0)
            for b in self.businesses:
                if not b.broken_down:
                    continue
                if random.random() > eff:   # low-level managers sometimes miss it
                    continue
                cost = b.repair_cost
                if cost > threshold or self.inventory.gold < cost:
                    continue
                self.inventory.gold  -= cost
                b.broken_down         = False
                b.repair_cost         = 0.0
                mgr.stats["total_actions"]   += 1
                mgr.stats["total_gold_cost"] += cost
                self._mgr_log(mgr, f"Repaired {b.name} for {cost:.0f}g")
                self._mgr_award_xp(mgr, 2)
        # ── Auto-fire underperforming / over-priced workers ───────────────
        if cfg.get("auto_fire_lazy", False):
            prod_floor = cfg.get("min_worker_productivity", 0.6)
            max_wage   = cfg.get("max_wage_per_worker", 8.0)
            for b in self.businesses:
                if b.broken_down:
                    continue
                for worker in list(b.hired_workers):
                    prod = worker.get("productivity", 1.0)
                    wage = worker.get("wage", 0.0)
                    if prod < prod_floor or wage > max_wage:
                        b.hired_workers.remove(worker)
                        b.workers = len(b.hired_workers)
                        mgr.stats["total_actions"] += 1
                        self._mgr_log(mgr, f"Replaced {worker['name']} at {b.name} "
                                           f"(prod {prod:.2f}, wage {wage:.1f}g/day)")
                        self._mgr_award_xp(mgr, 1)
        # ── Auto-hire workers to fill empty slots ─────────────────────────
        if cfg.get("auto_hire", True):
            # Pool size = how many applicants the foreman can interview per slot.
            # L1 (0.65): 3 candidates — limited network, less selective.
            # L5 (1.00): 8 candidates — wide network, picks the best of many.
            pool_size = max(3, round(3 + eff * 5))
            max_wage  = cfg.get("max_wage_per_worker", 8.0)
            for b in self.businesses:
                if b.broken_down or b.workers >= b.max_workers:
                    continue
                while b.workers < b.max_workers:
                    candidates = self._generate_applicants(pool_size)
                    candidates = [c for c in candidates if c.get("wage", 99) <= max_wage]
                    if not candidates:
                        break
                    best = max(candidates,
                               key=lambda x: x["productivity"] / max(x["wage"], 0.01))
                    b.hired_workers.append(best)
                    b.workers = len(b.hired_workers)
                    mgr.stats["total_actions"] += 1
                    self._mgr_log(mgr, f"Hired {best['name']} for {b.name} "
                                       f"at {best['wage']:.1f}g/day")
                    self._mgr_award_xp(mgr, 1)

    def _mgr_trade_steward(self, mgr: "HiredManager") -> None:
        """P&L-aware sell agent with optional same-day multi-market routing.

        Design:
          - No position/transit state. Steward always operates from player's area.
          - Tracks cost_basis per item. Player-bought items are registered at the
            current sell price (the "floor" — steward wants a move above that).
          - With allow_travel=True: evaluates nearby markets, pays 3g×days trip cost,
            and sells the entire batch at the best destination that day. One decision,
            one trip. No delayed state, no stuck-in-transit bugs.

        Intelligence (eff = mgr.efficiency):
          L1 (0.65): 35% miss, no trend reads, checks ~2 destinations
          L3 (0.86): 14% miss, 3-day trend exit signal, checks ~4 destinations
          L5 (0.98):  2% miss, full market scan, trend buys
        """
        cfg = mgr.config
        eff = mgr.efficiency

        # Safe bootstrap — survives any save format
        mgr.stats.setdefault("cost_basis",     {})
        mgr.stats.setdefault("hold_since_day", {})

        min_qty       = cfg.get("sell_min_quantity",  1)
        keep_qty      = cfg.get("keep_quantity",      0)
        sell_biz      = cfg.get("sell_business_output", True)
        sell_purch    = cfg.get("sell_purchased_goods", True)
        auto_buy      = cfg.get("auto_buy_for_resale",  False)
        max_spend     = cfg.get("max_buy_gold",       200.0)
        min_profit    = cfg.get("min_profit_pct",      0.05)  # 5% target above basis
        patience      = cfg.get("patience_days",         5)   # days before accepting near-cost
        allow_travel  = cfg.get("allow_travel",        False)
        max_travel_d  = cfg.get("max_travel_days",       2) if allow_travel else 0

        home_area  = self.current_area
        home_mkt   = self.markets[home_area]
        biz_items  = {b.item_produced for b in self.businesses}
        cost_basis = mgr.stats["cost_basis"]
        hold_since = mgr.stats["hold_since_day"]

        # ── Clean stale basis entries for items no longer in inventory ────
        for ik in list(cost_basis.keys()):
            if self.inventory.items.get(ik, 0) == 0:
                cost_basis.pop(ik, None)
                hold_since.pop(ik, None)

        # ── Register estimated floor for manually-held items ──────────────
        # Use current sell price as the cost floor. Steward needs a price ABOVE
        # this before selling (target_margin %). After patience_days it relaxes.
        if sell_purch:
            for item_key in list(self.inventory.items.keys()):
                if (item_key not in biz_items
                        and item_key not in cost_basis
                        and item_key in home_mkt.item_keys):
                    cost_basis[item_key] = home_mkt.get_sell_price(
                        item_key, self.season, self.skills.trading)
                    hold_since.setdefault(item_key, self.day)

        # ── Determine sell market (home or best routed destination) ───────
        # With allow_travel, the steward scouts nearby markets and can pay a
        # trip cost to sell the whole batch there on the same day.
        sell_area     = home_area
        sell_mkt      = home_mkt
        trip_cost_paid = 0.0

        if allow_travel and max_travel_d > 0:
            # Collect items we intend to sell
            route_items = []
            for item_key, qty in self.inventory.items.items():
                is_b = item_key in biz_items
                if is_b and not sell_biz:
                    continue
                if not is_b and not sell_purch:
                    continue
                net = qty - keep_qty
                if net >= min_qty and item_key in home_mkt.item_keys:
                    route_items.append((item_key, net))

            if route_items:
                home_tdtbl  = AREA_INFO[home_area]["travel_days"]
                # Gather route candidates — intelligence limits awareness
                # L1: each destination has only eff chance to be considered
                best_dest   = home_area
                best_bonus  = 0.0  # must be positive to justify the trip

                for dest_area in Area:
                    if dest_area == home_area:
                        continue
                    td = home_tdtbl.get(dest_area, 99)
                    if td > max_travel_d:
                        continue
                    # Low-level stewards miss some routes
                    if random.random() > eff + 0.35:
                        continue
                    tc       = td * 3.0 * self.settings.cost_mult
                    dest_mkt = self.markets[dest_area]
                    bonus    = -tc  # overcome trip cost to be worthwhile

                    for item_key, net in route_items:
                        if item_key in dest_mkt.item_keys:
                            local_sp = home_mkt.get_sell_price(
                                item_key, self.season, self.skills.trading)
                            dest_sp  = dest_mkt.get_sell_price(
                                item_key, self.season, self.skills.trading)
                            bonus += (dest_sp - local_sp) * net

                    if bonus > best_bonus:
                        best_bonus = bonus
                        best_dest  = dest_area

                # Execute the trip if the net gain is worthwhile
                if best_dest != home_area:
                    td = home_tdtbl[best_dest]
                    tc = round(td * 3.0 * self.settings.cost_mult, 1)
                    if self.inventory.gold >= tc:
                        self.inventory.gold          -= tc
                        trip_cost_paid                = tc
                        sell_area                     = best_dest
                        sell_mkt                      = self.markets[best_dest]
                        mgr.stats["total_gold_cost"] += tc
                        # Road risk (higher eff = safer traveller)
                        risk     = (AREA_INFO[best_dest]["travel_risk"]
                                    + self.markets[best_dest].travel_risk_override)
                        eff_risk = risk * (1.2 - eff)
                        if random.random() < eff_risk:
                            loss = max(0, min(
                                int(self.inventory.gold * random.uniform(0.03, 0.12)),
                                int(self.inventory.gold)))
                            self.inventory.gold = max(0, self.inventory.gold - loss)
                            mgr.stats["mistakes"] += 1
                            self._mgr_log(mgr,
                                f"⚠ Trouble on road to {best_dest.value}! "
                                f"Lost {loss:.0f}g")
                        else:
                            self._mgr_log(mgr,
                                f"Routed to {best_dest.value} "
                                f"(+{best_bonus:.0f}g est. vs local, {tc:.0f}g trip)")
                        mgr.stats["total_actions"] += 1
                        self._mgr_award_xp(mgr, 1)

        # ── SELL loop ─────────────────────────────────────────────────────
        for item_key, qty in list(self.inventory.items.items()):
            is_biz = item_key in biz_items
            if is_biz and not sell_biz:
                continue
            if not is_biz and not sell_purch:
                continue

            sellable = qty - keep_qty
            if sellable < min_qty:
                continue
            if item_key not in sell_mkt.item_keys:
                continue

            pressure = sell_mkt.pressure.get(item_key, 1.0)
            nat      = sell_mkt.natural_pressure.get(item_key, 1.0)

            # ── Business goods: sell unless market is severely depressed ──
            if is_biz:
                if pressure < nat * 0.88:
                    continue
                to_sell  = max(1, int(sellable * eff))
                earnings = sell_mkt.sell_to_market(
                    item_key, to_sell, self.season, self.skills.trading)
                if earnings <= 0:
                    continue
                self.inventory.remove(item_key, to_sell)
                self.inventory.gold   += earnings
                self.total_profit     += earnings
                mgr.stats["total_actions"]        += 1
                mgr.stats["total_gold_generated"] += earnings
                loc = f" at {sell_area.value}" if sell_area != home_area else ""
                self._mgr_log(mgr, f"Sold {to_sell}× {item_key} for {earnings:.0f}g "
                                   f"(×{pressure:.2f}{loc})")
                self._mgr_award_xp(mgr, 1)
                if eff >= 0.85:
                    self._mgr_award_xp(mgr, 2)
                continue

            # ── Purchased goods: P&L gate ─────────────────────────────────
            basis     = cost_basis.get(item_key, 0.0)
            day_held  = self.day - hold_since.get(item_key, self.day)
            sell_p    = sell_mkt.get_sell_price(item_key, self.season, self.skills.trading)

            # Scale target slightly with level; L1=5%, L5=6.6%
            target_margin = min_profit + (eff - 0.65) * 0.05
            target_price  = basis * (1.0 + target_margin) if basis > 0 else 0.01

            will_sell   = False
            sell_reason = ""

            if sell_p >= target_price:
                will_sell   = True
                pct = (sell_p / max(basis, 0.01) - 1) * 100
                sell_reason = f"{pct:+.0f}% vs floor"

            if not will_sell and basis >= 0:
                # After patience_days accept within −5% of basis; after max_hold sell anything
                max_hold = patience * (1.0 + (eff - 0.65) * 2.0)
                if day_held >= max_hold:
                    will_sell   = True
                    sell_reason = f"max-hold ({day_held:.0f}d)"
                elif day_held >= patience and sell_p >= basis * 0.95:
                    will_sell   = True
                    sell_reason = f"patience ({day_held:.0f}d)"

            # L3+: cut position on declining trend when still above basis
            if not will_sell and eff >= 0.79:
                hist = list(sell_mkt.history.get(item_key, []))
                if len(hist) >= 3:
                    t3 = (hist[-1].price - hist[-3].price) / max(hist[-3].price, 0.01)
                    if t3 < -0.02 and sell_p >= basis * 1.02:
                        will_sell   = True
                        sell_reason = "trend ↓ exit"

            # Miss rate: simulates imperfect timing (L1: 35%, L5: ~2%)
            if will_sell and random.random() > eff:
                will_sell = False

            if not will_sell:
                continue

            to_sell  = sellable
            earnings = sell_mkt.sell_to_market(
                item_key, to_sell, self.season, self.skills.trading)
            if earnings <= 0:
                continue

            pnl = earnings - (basis * to_sell) if basis > 0 else earnings
            self.inventory.remove(item_key, to_sell)
            self.inventory.gold   += earnings
            self.total_profit     += earnings
            cost_basis.pop(item_key, None)
            hold_since.pop(item_key, None)
            mgr.stats["total_actions"]        += 1
            mgr.stats["total_gold_generated"] += earnings
            loc = f" at {sell_area.value}" if sell_area != home_area else ""
            self._mgr_log(mgr,
                f"Sold {to_sell}× {item_key} for {earnings:.0f}g "
                f"(P&L {pnl:+.0f}g, {sell_reason}{loc})")
            self._mgr_award_xp(mgr, 1)
            if pnl > 0:
                self._mgr_award_xp(mgr, 1)

        # ── AUTO-BUY for resale ───────────────────────────────────────────
        if not auto_buy:
            return
        spent = 0.0
        for item_key in list(home_mkt.item_keys):
            if spent >= max_spend or self.inventory.gold < 5:
                break
            item = ALL_ITEMS.get(item_key)
            if not item or item.illegal:
                continue
            # Skip items already in inventory with a known basis (don't double-dip)
            if item_key in cost_basis and self.inventory.items.get(item_key, 0) > 0:
                continue

            buy_p = home_mkt.get_buy_price(item_key, self.season, self.skills.trading)

            # Best expected sell price (local or best routed destination)
            best_sell_p   = home_mkt.get_sell_price(item_key, self.season, self.skills.trading)
            best_sell_area = home_area
            if allow_travel:
                for dest_area in Area:
                    if dest_area == home_area:
                        continue
                    td = AREA_INFO[home_area]["travel_days"].get(dest_area, 99)
                    if td > max_travel_d:
                        continue
                    dest_mkt = self.markets[dest_area]
                    if item_key not in dest_mkt.item_keys:
                        continue
                    tc       = td * 3.0 * self.settings.cost_mult
                    dest_sp  = dest_mkt.get_sell_price(item_key, self.season, self.skills.trading)
                    # Amortise trip cost over an expected 10-unit lot
                    adj_sp   = dest_sp - tc / 10.0
                    if adj_sp > best_sell_p:
                        best_sell_p    = adj_sp
                        best_sell_area = dest_area

            target_sell = buy_p * (1.0 + min_profit)
            if best_sell_p < target_sell:
                continue

            # L3+: trend signal at best sell destination
            if eff >= 0.79:
                dest_mkt = self.markets[best_sell_area]
                hist = list(dest_mkt.history.get(item_key, []))
                if (len(hist) >= 3 and best_sell_p < target_sell):
                    t3 = (hist[-1].price - hist[-3].price) / max(hist[-3].price, 0.01)
                    if t3 > 0.015:
                        pass  # still need target_sell to pass above

            if random.random() > eff:  # miss rate
                continue

            budget   = min(max_spend - spent, self.inventory.gold * 0.25)
            qty_cap  = max(1, int(budget / max(buy_p, 0.01)))
            qty      = min(qty_cap, home_mkt.stock.get(item_key, 0), 30)
            if qty < 1:
                continue

            cost = home_mkt.buy_from_market(item_key, qty, self.season, self.skills.trading)
            if cost < 0 or self.inventory.gold < cost:
                continue

            self.inventory.gold -= cost
            self.inventory.add(item_key, qty)
            spent += cost

            old_qty = self.inventory.items.get(item_key, qty) - qty
            paid_pu = cost / qty
            if old_qty > 0 and item_key in cost_basis:
                cost_basis[item_key] = (cost_basis[item_key] * old_qty + cost) / (old_qty + qty)
            else:
                cost_basis[item_key] = paid_pu
            hold_since[item_key] = self.day

            dest_note = (f" → {best_sell_area.value}" if best_sell_area != home_area else "")
            mgr.stats["total_actions"]   += 1
            mgr.stats["total_gold_cost"] += cost
            self._mgr_log(mgr,
                f"Bought {qty}× {item_key} @ {paid_pu:.1f}g "
                f"({cost:.0f}g){dest_note}, need >{target_sell:.1f}g to sell")
            self._mgr_award_xp(mgr, 1)

    def _mgr_property_steward(self, mgr: "HiredManager") -> None:
        """Manages real estate: finds tenants, triggers repairs, handles leases."""
        cfg = mgr.config
        eff = mgr.efficiency
        # ── Auto-evict tenants from critically damaged properties ─────────
        if cfg.get("auto_evict_low_condition", False):
            evict_thresh = cfg.get("evict_condition_threshold", 0.30)
            for prop in self.real_estate:
                if not prop.is_leased or prop.condition > evict_thresh:
                    continue
                old_tenant  = prop.tenant_name or "Tenant"
                prop.is_leased   = False
                prop.tenant_name = ""
                self.reputation  = max(0, self.reputation - 1)
                mgr.stats["total_actions"] += 1
                self._mgr_log(mgr, f"Evicted {old_tenant} from {prop.name} "
                                   f"(condition {prop.condition:.0%} < {evict_thresh:.0%})")
        # ── Auto-lease vacant properties ─────────────────────────────────
        if cfg.get("auto_lease", True):
            for prop in self.real_estate:
                if prop.under_construction or prop.is_leased or prop.condition < 0.20:
                    continue
                # Low-level stewards occasionally miss vacancies
                if random.random() > eff:
                    continue
                reject_risky = cfg.get("reject_risky_tenants", False)
                rate_base = max(0.1, eff - random.uniform(0, 0.15))
                cw_floor  = 0.5 if not reject_risky else max(0.5, eff * 0.8)
                cw        = random.uniform(cw_floor, 1.5)
                reliability_labels = ["Troublesome","Risky","Average","Good","Excellent"]
                cw_idx      = min(4, int((cw - 0.5) / 0.25))
                _tf = ["Aldric","Bram","Cora","Dag","Elra","Finn","Greta","Holt","Isa",
                       "Jorin","Kev","Lena","Mira","Ned","Ora","Pip","Quinn","Rolf","Sable","Tilda"]
                _tl = ["Miller","Cooper","Smith","Tanner","Fisher","Brewer","Mason",
                       "Wright","Fletcher","Barrow","Cotter","Dyer","Galloway","Hayward"]
                tenant_name          = f"{random.choice(_tf)} {random.choice(_tl)}"
                prop.is_leased       = True
                prop.tenant_name     = tenant_name
                prop.lease_rate_mult = round(rate_base * 1.1, 2)
                mgr.stats["total_actions"] += 1
                mgr.stats["total_gold_generated"] += prop.daily_lease * 30
                self._mgr_log(mgr, f"Leased {prop.name} to {tenant_name} "
                                   f"({reliability_labels[cw_idx]}) "
                                   f"at {prop.daily_lease:.1f}g/day")
                self._mgr_award_xp(mgr, 3)
        # ── Auto-repair low-condition properties ─────────────────────────
        if not cfg.get("auto_repair", True):
            return
        threshold    = cfg.get("min_condition_to_repair", 0.55)
        max_repair   = cfg.get("max_repair_cost", 1000.0)
        for prop in self.real_estate:
            if prop.under_construction or prop.condition >= threshold:
                continue
            if prop.is_leased:
                continue   # can't repair while occupied; use auto_evict first
            cost = prop.repair_cost
            if cost <= 0 or self.inventory.gold < cost:
                continue
            if cost > max_repair:
                self._mgr_log(mgr, f"Skipped repair of {prop.name}: cost {cost:.0f}g "
                                   f"exceeds limit {max_repair:.0f}g")
                continue
            if random.random() > eff:
                continue
            self.inventory.gold -= cost
            prop.condition       = min(1.0, prop.condition + random.uniform(0.3, 0.5) * eff)
            mgr.stats["total_actions"]   += 1
            mgr.stats["total_gold_cost"] += cost
            self._mgr_log(mgr, f"Repaired {prop.name} (condition now {prop.condition:.0%})")
            self._mgr_award_xp(mgr, 2)

    def _mgr_contract_agent(self, mgr: "HiredManager") -> None:
        """Fulfills accepted contracts by procuring items and marking deliveries."""
        cfg = mgr.config
        eff = mgr.efficiency
        auto_fulfill = cfg.get("auto_fulfill", True)
        auto_procure = cfg.get("auto_procure", True)
        max_deadline = cfg.get("max_deadline_days", 999)
        max_procure  = cfg.get("max_procure_gold", 300.0)
        for con in self.contracts:
            if con.fulfilled:
                continue
            days_left = con.deadline_day - self._absolute_day()
            if days_left > max_deadline:
                continue
            urgency  = 1.0 - (days_left / max(con.deadline_day, 1))
            act_prob = eff + urgency * 0.3
            if random.random() > min(1.0, act_prob):
                continue
            have   = self.inventory.items.get(con.item_key, 0)
            needed = con.quantity
            # ── Fulfill if we have stock at the destination ───────────────
            if auto_fulfill and have >= needed and self.current_area == con.destination:
                value = needed * con.price_per_unit + con.reward_bonus
                self.inventory.remove(con.item_key, needed)
                self.inventory.gold += value
                self.reputation      = min(100, self.reputation + 2)
                self.total_profit   += value
                self._track_stat("contracts_completed")
                if days_left > 0:
                    self._track_stat("contracts_ontime")
                con.fulfilled = True
                mgr.stats["total_actions"] += 1
                mgr.stats["total_gold_generated"] += value
                self._mgr_log(mgr, f"Fulfilled contract: {needed}× {con.item_key} "
                                   f"→ {con.destination.value}  +{value:.0f}g")
                self._mgr_award_xp(mgr, 5)
                self._check_achievements()
            # ── Procure short-fall from market ────────────────────────────
            elif auto_procure and have < needed:
                short = needed - have
                mkt   = self.markets[self.current_area]
                if mkt.stock.get(con.item_key, 0) < short:
                    continue
                buy_price = mkt.get_buy_price(con.item_key, self.season, self.skills.trading)
                total_cost = round(buy_price * short, 2)
                if total_cost > max_procure:
                    self._mgr_log(mgr, f"Skipped procuring {short}× {con.item_key}: "
                                       f"cost {total_cost:.0f}g exceeds limit {max_procure:.0f}g")
                    continue
                if self.inventory.gold < total_cost:
                    continue
                actual_cost = mkt.buy_from_market(con.item_key, short,
                                                   self.season, self.skills.trading)
                if actual_cost < 0:
                    continue
                self.inventory.gold -= actual_cost
                self.inventory.add(con.item_key, short)
                mgr.stats["total_actions"]   += 1
                mgr.stats["total_gold_cost"] += actual_cost
                self._mgr_log(mgr, f"Procured {short}× {con.item_key} "
                                   f"for pending contract ({actual_cost:.0f}g)")
                self._mgr_award_xp(mgr, 2)

    def _mgr_lending_advisor(self, mgr: "HiredManager") -> None:
        """Vets and issues citizen loans periodically."""
        cfg = mgr.config
        eff = mgr.efficiency
        # Only acts every 3-5 days
        if self._absolute_day() % random.randint(3, 5) != 0:
            return
        if not cfg.get("auto_issue", True):
            return
        # ── Auto write-off: clear very old defaulted loans ───────────────
        if cfg.get("auto_write_off", False):
            for cl in list(self.citizen_loans):
                if cl.defaulted and cl.weeks_remaining <= 0:
                    self.citizen_loans.remove(cl)
                    mgr.stats["total_actions"] += 1
                    self._mgr_log(mgr, f"Wrote off defaulted loan from {cl.borrower_name} "
                                       f"({cl.principal:.0f}g principal)")
        max_active = cfg.get("max_active_loans", 5)
        active     = [cl for cl in self.citizen_loans
                      if not cl.defaulted and cl.weeks_remaining > 0]
        if len(active) >= max_active:
            return
        # ── Max total loaned cap ──────────────────────────────────────────
        max_total_loaned = cfg.get("max_total_loaned", 1000.0)
        outstanding = sum(cl.principal for cl in active)
        if outstanding >= max_total_loaned:
            return
        max_gold = cfg.get("max_loan_amount", 300.0)
        min_cw   = cfg.get("min_creditworthiness", 0.7)
        adj_cw   = min_cw + (eff - 0.65) * 0.5
        prefer_short = cfg.get("prefer_short_loans", False)
        candidates   = self._gen_loan_applicants(4)
        for cand in candidates:
            if cand["creditworthiness"] < adj_cw:
                continue
            if cand["amount"] > max_gold:
                continue
            if prefer_short and cand["weeks"] > 8:
                continue
            if outstanding + cand["amount"] > max_total_loaned:
                continue
            if self.inventory.gold < cand["amount"]:
                continue
            rate    = round(cand["max_rate"] * (0.9 + eff * 0.1), 3)
            weeks   = cand["weeks"]
            payment = round(cand["amount"] * (1 + rate * weeks) / weeks, 2)
            cl = CitizenLoan(
                id=self.next_citizen_loan_id,
                borrower_name=cand["name"],
                principal=cand["amount"],
                interest_rate=rate,
                weeks_remaining=weeks,
                weekly_payment=payment,
                creditworthiness=cand["creditworthiness"],
            )
            self.next_citizen_loan_id += 1
            self.citizen_loans.append(cl)
            self.inventory.gold -= cand["amount"]
            outstanding         += cand["amount"]
            mgr.stats["total_actions"] += 1
            mgr.stats["total_gold_generated"] += payment * weeks - cand["amount"]
            self._mgr_log(mgr, f"Issued loan to {cand['name']}: {cand['amount']:.0f}g "
                               f"@ {rate*100:.1f}%/wk × {weeks}wk")
            self._mgr_award_xp(mgr, 3)
            break  # one loan per trigger

    def _mgr_investment_broker(self, mgr: "HiredManager") -> None:
        """Buys and sells stocks based on signals; efficiency controls quality of decisions."""
        cfg  = mgr.config
        eff  = mgr.efficiency
        risk = cfg.get("risk_tolerance", 0.5)
        # Acts every 2-4 days
        if self._absolute_day() % random.randint(2, 4) != 0:
            return
        auto_sell      = cfg.get("auto_sell", True)
        auto_buy       = cfg.get("auto_buy", True)
        min_gain       = cfg.get("min_gain_to_sell", 0.15)
        stop_loss      = cfg.get("stop_loss_pct", 0.20)
        max_per        = cfg.get("max_investment_per_stock", 200.0)
        max_total      = cfg.get("max_portfolio_value", 1000.0)
        port_val       = self._portfolio_value()
        # ── Sell signals (take profit or cut loss) ──────────────────────
        if auto_sell:
            for sym, holding in list(self.stock_holdings.items()):
                sd       = self.stock_market.stocks.get(sym)
                if not sd:
                    continue
                price    = sd["price"]
                avg_cost = holding.avg_cost
                gain_pct = (price - avg_cost) / max(avg_cost, 1.0)
                if eff < 0.80:
                    sell = gain_pct > min_gain or gain_pct < -stop_loss
                else:
                    hist  = list(sd["history"])
                    trend = (hist[-1] - hist[-5]) / max(hist[-5], 1.0) if len(hist) >= 5 else 0
                    sell  = (gain_pct > min_gain + risk * 0.15) or (trend < -0.04 and gain_pct < 0)
                if sell:
                    proceeds = round(holding.shares * price, 2)
                    profit   = proceeds - round(holding.shares * avg_cost, 2)
                    del self.stock_holdings[sym]
                    self.inventory.gold += proceeds
                    self.total_profit   += profit
                    self._track_stat("stock_profit", profit)
                    mgr.stats["total_actions"] += 1
                    mgr.stats["total_gold_generated"] += max(0.0, profit)
                    self._mgr_log(mgr, f"Sold {holding.shares}× {sym} for {proceeds:.0f}g "
                                       f"({'profit' if profit >= 0 else 'loss'} {abs(profit):.0f}g)")
                    self._mgr_award_xp(mgr, 5 if profit > 0 else 1)
        # ── Buy signals ──────────────────────────────────────────────────
        if not auto_buy:
            return
        if port_val >= max_total or self.inventory.gold < 50:
            return
        candidates = []
        for sym, sd in self.stock_market.stocks.items():
            if sym in self.stock_holdings:
                continue
            price = sd["price"]
            hist  = list(sd["history"])
            if len(hist) < 3:
                continue
            trend_3d = (hist[-1] - hist[-3]) / max(hist[-3], 1.0) if len(hist) >= 3 else 0
            event_score = 0.0
            if eff >= 0.85:
                for mkt in self.markets.values():
                    for ev in mkt.active_events:
                        impact = sd["linked_events"].get(ev, 0.0)
                        event_score += impact
            score = trend_3d + event_score * eff * 0.5
            candidates.append((score, sym, price, sd["volatility"]))
        if not candidates:
            return
        candidates.sort(reverse=True)
        top_sym, top_price, top_vol = candidates[0][1], candidates[0][2], candidates[0][3]
        if candidates[0][0] < (0.01 if eff >= 0.80 else 0.02):
            return
        invest = min(max_per * eff, max_total - port_val, self.inventory.gold * 0.3)
        invest = max(10.0, round(invest, 2))
        shares = max(1, int(invest / max(top_price, 0.01)))
        cost   = round(shares * top_price, 2)
        if cost > self.inventory.gold:
            return
        self.inventory.gold -= cost
        if top_sym in self.stock_holdings:
            h            = self.stock_holdings[top_sym]
            total_shares = h.shares + shares
            avg          = round((h.shares * h.avg_cost + cost) / total_shares, 4)
            self.stock_holdings[top_sym] = StockHolding(top_sym, total_shares, avg)
        else:
            self.stock_holdings[top_sym] = StockHolding(top_sym, shares, top_price)
        mgr.stats["total_actions"] += 1
        self._mgr_log(mgr, f"Bought {shares}× {top_sym} @ {top_price:.2f}g ea ({cost:.0f}g)")
        self._mgr_award_xp(mgr, 2)

    def _mgr_fund_custodian(self, mgr: "HiredManager") -> None:
        """Accepts fund management clients automatically based on configuration."""
        cfg = mgr.config
        eff = mgr.efficiency
        # Only acts every 5-8 days
        if self._absolute_day() % random.randint(5, 8) != 0:
            return
        if not cfg.get("auto_accept", True):
            return
        if LicenseType.FUND_MGR not in self.licenses:
            return
        max_clients  = cfg.get("max_clients", 4)
        active_count = sum(1 for fc in self.fund_clients if not fc.withdrawn)
        if active_count >= max_clients:
            return
        min_cap       = cfg.get("min_client_capital", 300.0)
        min_fee_rate  = cfg.get("min_fee_rate", 0.01)
        min_dur_days  = cfg.get("min_duration_days", 30)
        pool          = self._gen_fund_client_pool(3)
        for cand in pool:
            if cand["capital"] < min_cap:
                continue
            if cand["duration"] < min_dur_days:
                self._mgr_log(mgr, f"Skipped {cand['name']}: duration {cand['duration']}d < "
                                   f"minimum {min_dur_days}d")
                continue
            fee_rate = round(cand["fee_rate"] * (0.9 + eff * 0.2), 4)
            if fee_rate < min_fee_rate:
                self._mgr_log(mgr, f"Skipped {cand['name']}: fee {fee_rate*100:.1f}% < "
                                   f"minimum {min_fee_rate*100:.1f}%")
                continue
            start = self._absolute_day()
            dur   = cand["duration"]
            fc = FundClient(
                id=self.next_fund_client_id,
                name=cand["name"],
                capital=cand["capital"],
                promised_rate=cand["promised_rate"],
                start_day=start,
                duration_days=dur,
                maturity_day=start + dur,
                fee_rate=fee_rate,
            )
            self.next_fund_client_id += 1
            self.fund_clients.append(fc)
            mgr.stats["total_actions"] += 1
            self._mgr_log(mgr, f"Accepted fund client {cand['name']}: "
                               f"{cand['capital']:.0f}g, {dur}d, fee {fee_rate*100:.1f}%/mo")
            self._mgr_award_xp(mgr, 5)
            break  # one new client per trigger

    def _mgr_campaign_handler(self, mgr: "HiredManager") -> None:
        """Runs market influence campaigns periodically."""
        cfg  = mgr.config
        eff  = mgr.efficiency
        freq = cfg.get("campaign_frequency_days", 14)
        if self._absolute_day() % freq != 0:
            return
        if LicenseType.MERCHANT not in self.licenses:
            return
        # Skip if the last campaign lost money and the toggle is on
        if cfg.get("skip_if_last_loss", False):
            if mgr.stats.get("last_campaign_net", 1.0) < 0:
                self._mgr_log(mgr, "Skipping campaign — last run was a loss")
                return
        pref_area_name = cfg.get("preferred_area", "CITY")
        try:
            target_area = Area[pref_area_name]
        except KeyError:
            target_area = self.current_area
        mkt          = self.markets[target_area]
        items        = list(mkt.pressure.items())
        if not items:
            return
        items_scored = sorted(items, key=lambda x: x[1], reverse=True)
        if not items_scored:
            return
        # Intelligence-based item selection:
        # L1 picks randomly from the top half of items (limited market reading).
        # L3+ narrows to the top quartile; L5 always picks the single best target.
        visible_count = max(1, round(len(items_scored) * (1.0 - eff * 0.85)))
        top_item = random.choice(items_scored[:visible_count])[0]
        base_campaign_cost = 20.0
        effective_cost     = round(base_campaign_cost * (1 + eff * 0.5), 2)
        max_cost           = cfg.get("max_campaign_cost", 50.0)
        if effective_cost > max_cost:
            self._mgr_log(mgr, f"Campaign cost {effective_cost:.0f}g would exceed "
                               f"limit {max_cost:.0f}g — skipping")
            return
        if self.inventory.gold < effective_cost:
            return
        base_yield           = effective_cost * (0.8 + eff * 0.6)
        actual_yield         = round(base_yield * random.uniform(0.8, 1.2), 2)
        net                  = actual_yield - effective_cost
        self.inventory.gold += net
        self._track_stat("campaigns_run")
        mgr.stats["total_actions"] += 1
        mgr.stats["last_campaign_net"] = net
        mgr.stats["total_gold_generated"] += max(0.0, net)
        if net > self.ach_stats.get("max_campaign_gold", 0.0):
            self.ach_stats["max_campaign_gold"] = net
        self._mgr_log(mgr, f"Ran campaign for {top_item} in {target_area.value}: "
                           f"spent {effective_cost:.0f}g, earned {actual_yield:.0f}g "
                           f"(net {net:+.0f}g)")
        self._mgr_award_xp(mgr, 5)
        self._check_achievements()

    def _mgr_smuggling_handler(self, mgr: "HiredManager") -> None:
        """Manages contraband operations; obeys max_heat and risk limits."""
        cfg  = mgr.config
        eff  = mgr.efficiency
        freq = cfg.get("ops_frequency_days", 7)
        if self._absolute_day() % freq != 0:
            return
        max_heat = cfg.get("max_heat", 60)
        if self.heat >= max_heat:
            return
        # ── Heat cooldown after a bust ────────────────────────────────────
        if cfg.get("heat_pause_after_bust", True):
            last_bust = mgr.stats.get("last_bust_day", -999)
            if mgr.days_employed - last_bust < 3:
                self._mgr_log(mgr, "Pausing ops — too soon after last bust")
                return
        # Find contraband items available at current area market
        mkt        = self.markets[self.current_area]
        contraband = [k for k, item in ALL_ITEMS.items()
                      if item.illegal and mkt.stock.get(k, 0) >= 5]
        if not contraband:
            return
        item_key = random.choice(contraband)
        item     = ALL_ITEMS[item_key]
        qty      = max(1, int(5 + eff * 15))
        cost     = round(item.base_price * mkt.pressure.get(item_key, 1.0) * qty * 0.7, 2)
        if self.inventory.gold < cost:
            return
        # ── Pre-op risk / profit checks ───────────────────────────────────
        bust_chance  = max(0.03, 0.25 - eff * 0.22)
        max_risk     = cfg.get("max_bust_risk", 0.25)
        if bust_chance > max_risk:
            self._mgr_log(mgr, f"Bust risk {bust_chance:.0%} > limit {max_risk:.0%} — standing down")
            return
        premium      = 1.4 + eff * 0.4
        expected_net = round(item.base_price * qty * premium - cost, 2)
        min_profit   = cfg.get("min_net_profit", 0.0)
        if expected_net < min_profit:
            self._mgr_log(mgr, f"Expected net {expected_net:.0f}g < minimum {min_profit:.0f}g — skipping")
            return
        # ── Execute ───────────────────────────────────────────────────────
        if random.random() < bust_chance:
            fine    = round(cost * 1.5, 2)
            penalty = min(fine, self.inventory.gold)
            self.inventory.gold -= penalty
            self.heat            = min(100, self.heat + 20)
            self.reputation      = max(0, self.reputation - 5)
            self._track_stat("smuggle_busts")
            mgr.stats["mistakes"]       += 1
            mgr.stats["last_bust_day"]   = mgr.days_employed
            self._mgr_log(mgr, f"⚠ BUSTED running {qty}× {item_key}! Fine {penalty:.0f}g  Heat +20")
            self._mgr_award_xp(mgr, 0)
            return
        self.inventory.gold  -= cost
        sell_earnings         = round(item.base_price * qty * premium, 2)
        self.inventory.gold  += sell_earnings
        net                   = sell_earnings - cost
        self.total_profit    += net
        heat_gain             = max(2, int(10 - eff * 8))
        self.heat             = min(100, self.heat + heat_gain)
        self._track_stat("smuggle_success")
        self._track_stat("smuggle_gold", net)
        mgr.stats["total_actions"] += 1
        mgr.stats["total_gold_generated"] += net
        self._mgr_log(mgr, f"Smuggled {qty}× {item_key}: spent {cost:.0f}g "
                           f"sold {sell_earnings:.0f}g (net +{net:.0f}g)  Heat +{heat_gain}")
        self._mgr_award_xp(mgr, 3)
        self._check_achievements()

    def _gen_loan_applicants(self, count: int = 5) -> List[Dict]:
        """Generate citizens seeking personal loans."""
        _first = ["Bryn","Cal","Doren","Elva","Fenn","Gwyn","Holt","Isla",
                  "Jord","Kira","Lund","Maris","Nev","Orla","Per","Quin",
                  "Ren","Sona","Tev","Una","Vorn","Wynn","Xan","Yva","Zorn"]
        _last  = ["Baker","Carver","Duggan","Fisher","Greer","Holt","Ivans",
                  "Jenks","Kemp","Lomas","Marsh","Nott","Orton","Pryce",
                  "Rowan","Sable","Trapp","Upham","Vane","Wicks","York"]
        war_on  = any("WAR" in e    for mkt in self.markets.values() for e in mkt.active_events)
        dry_on  = any("DROUGHT" in e for mkt in self.markets.values() for e in mkt.active_events)
        stress  = 1.0 + (0.3 if war_on else 0) + (0.2 if dry_on else 0)
        PURPOSE = ["business startup","home repairs","debt consolidation",
                   "harvest supplies","equipment purchase","medical expenses"]
        result = []
        for _ in range(count):
            name       = f"{random.choice(_first)} {random.choice(_last)}"
            amount     = round(random.choice([50,80,100,150,200,300,500]) * random.uniform(0.8,1.2))
            cw         = round(random.uniform(0.6, 1.5), 2)
            max_rate   = round(random.uniform(0.04, 0.14), 3)
            weeks      = random.choice([4, 6, 8, 12, 16])
            def_risk   = round(min(0.30, (1.5 - cw) * 0.07 * stress), 4)
            cw_lbl     = (c("High risk", RED) if cw < 0.85
                          else c("Average", YELLOW) if cw < 1.15
                          else c("Reliable", GREEN))
            result.append({"name": name, "amount": amount, "max_rate": max_rate,
                            "weeks": weeks, "creditworthiness": cw,
                            "default_risk": def_risk,
                            "purpose": random.choice(PURPOSE), "cw_label": cw_lbl})
        return result

    def _gen_fund_client_pool(self, count: int = 4) -> List[Dict]:
        """Generate wealthy citizens looking for a fund manager."""
        _names = ["Aldric Weston","Vera Colby","Magnus Ironsides","Lady Orla Fenn",
                  "Sir Cedric Pryce","Isabeau Morland","Theron Saltmarsh","Nora Quickley",
                  "Baron Rupert Hale","Countess Ysolde","Hugo Blackwell","Phoebe Croft"]
        result = []
        for _ in range(count):
            result.append({
                "name":         random.choice(_names),
                "capital":      round(random.choice([200,500,800,1000,1500,2000])
                                      * random.uniform(0.9, 1.1)),
                "duration":     random.choice([30, 60, 90]),
                "promised_rate": round(random.uniform(0.05, 0.18), 3),
                "fee_rate":      round(random.uniform(0.015, 0.035), 3),
            })
        return result

    def _generate_property_listings(self, area: Area = None, count: int = 10) -> List[Dict]:
        """
        Generate a list of property listings for the given area.
        Each listing dict has: prop_type, name, condition, cond_label,
        asking_price, repair_cost, daily_lease, is_negotiable, flavour, area_mult
        """
        if area is None:
            area = self.current_area
        area_mult = AREA_PROPERTY_MULT.get(area.name, 1.0)

        # Determine which property types are available in this area
        available = []
        for key, cat in PROPERTY_CATALOGUE.items():
            area_restrict = cat.get("areas")
            if area_restrict is None or area.name in area_restrict:
                available.append(key)

        listings = []
        for _ in range(count):
            ptype = random.choice(available)
            cat   = PROPERTY_CATALOGUE[ptype]
            base  = cat["base_value"]

            # Random condition — weighted toward poor/fair for market interest
            cond_weights = [(0.20, 2), (0.45, 5), (0.65, 7), (0.82, 5), (1.00, 3)]
            cond = random.choices([c[0] for c in cond_weights],
                                  weights=[c[1] for c in cond_weights])[0]
            # Add small jitter
            cond = round(min(1.0, max(0.10, cond + random.uniform(-0.05, 0.05))), 2)

            pristine_val = base * area_mult
            current_val  = round(pristine_val * cond, 2)

            # Seller markup: derelict properties need more convincing markup
            markup = random.uniform(1.05, 1.25)
            asking = round(current_val * markup, 2)

            # Repair cost estimate
            repair = round(pristine_val * (1.0 - cond) * 0.38, 2)

            # Daily lease at listed condition (no upgrades)
            base_lease   = cat.get("base_lease", 0) * area_mult * cond
            daily_lease  = round(base_lease, 2)

            cond_label, flavour = condition_label(cond)
            name = random.choice(_PROP_NAMES.get(ptype, ["Property"]))

            listings.append({
                "prop_type":     ptype,
                "name":          name,
                "condition":     cond,
                "cond_label":    cond_label,
                "asking_price":  asking,
                "repair_cost":   repair,
                "daily_lease":   daily_lease,
                "pristine_value": pristine_val,
                "is_negotiable": random.random() < 0.55,
                "flavour":       flavour,
                "area_mult":     area_mult,
                "area":          area,
            })
        return listings

    def _rep_label(self) -> str:
        r = self.reputation
        if r < 20:   return c("Outlaw",     RED)
        if r < 40:   return c("Suspect",    YELLOW)
        if r < 60:   return c("Neutral",    WHITE)
        if r < 80:   return c("Trusted",    GREEN)
        return               c("Legendary", CYAN)

    def _log_event(self, msg: str):
        self.event_log.appendleft(f"[Y{self.year} D{self.day}] {msg}")

    def _log_trade(self, msg: str):
        self.trade_log.appendleft(f"[Y{self.year} D{self.day}] {msg}")

    def _use_time(self, slots: int = 1):
        """Spend activity slots for the day; auto-advance when daily limit reached."""
        self.daily_time_units += slots
        if self.daily_time_units >= self.DAILY_TIME_UNITS:
            print(f"\n  {c('◑  Night falls — your day is done.', GREY)}")
            self._advance_day()
            print(f"  {c(f'Morning: Year {self.year}, Day {self.day}  ({self.season.value})', CYAN)}\n")

    # ── Display ──────────────────────────────────────────────────────────────

    def display_status(self):
        season_colour = {Season.SPRING: GREEN, Season.SUMMER: YELLOW,
                         Season.AUTUMN: "\033[33m", Season.WINTER: BLUE}[self.season]
        print(f"\n{BOLD}{CYAN}{'═'*62}{RESET}")
        print(f"  {BOLD}MERCHANT TYCOON{RESET}  ·  Year {self.year}, Day {self.day}  ·  {season_colour}{self.season.value}{RESET}")
        print(f"  Location : {BOLD}{self.current_area.value}{RESET}  ·  Reputation: {self._rep_label()}")
        print(f"  Gold     : {c(f'{self.inventory.gold:.2f}', YELLOW)}  ·  Bank: {c(f'{self.bank_balance:.2f}', YELLOW)}")
        w = self._current_weight()
        cap = self._max_carry_weight()
        w_col = RED if w > cap * 0.9 else YELLOW if w > cap * 0.7 else GREEN
        print(f"  Weight   : {c(f'{w:.1f}/{cap:.0f}', w_col)}  ·  Net Worth: {c(f'{self._net_worth():.2f}', CYAN)}")
        used = self.daily_time_units
        left = self.DAILY_TIME_UNITS - used
        slots_bar = c("●", CYAN) * used + c("○", GREY) * left
        print(f"  Schedule : {slots_bar}  "
              f"{c(f'{left}/{self.DAILY_TIME_UNITS} slots left', CYAN if left > 2 else YELLOW if left > 0 else RED)}"
              f"  {c(f'· {self._living_cost():.0f}g/day living cost', GREY)}")
        if self.heat > 0:
            print(f"  {c(f'HEAT: {self.heat}/100 — guards are watching!', RED)}")
        if self.businesses:
            print(f"  Businesses: {len(self.businesses)}  ·  Active Contracts: {len([c for c in self.contracts if not c.fulfilled])}")
        if self.loans:
            total_debt = sum(l.principal for l in self.loans)
            print(f"  {c(f'Outstanding Debt: {total_debt:.2f} gold', RED)}")

        active_events = []
        for market in self.markets.values():
            active_events.extend(market.active_events)
        if active_events:
            unique_events = list(dict.fromkeys(active_events))[:3]
            print(f"  {c('Active Events: ' + ', '.join(unique_events), YELLOW)}")
        print(f"{BOLD}{CYAN}{'═'*62}{RESET}")

    def display_main_menu(self):
        broken       = sum(1 for b in self.businesses if b.broken_down)
        active_cons  = [con for con in self.contracts if not con.fulfilled]
        urgent_cons  = sum(1 for con in active_cons
                           if con.deadline_day - self._absolute_day() <= 5)
        days_till    = self.DAYS_PER_SEASON - ((self.day - 1) % self.DAYS_PER_SEASON)
        seasons_lst  = list(Season)
        next_s       = seasons_lst[(seasons_lst.index(self.season) + 1) % 4]

        def key(k):
            return f"{BOLD}{CYAN}[{k}]{RESET}"

        def sect(name):
            pad = "─" * max(0, 56 - len(name) - 4)
            print(f"  {GREY}── {name} {pad}{RESET}")

        # ── ACTIONS ──────────────────────────────────────────────────────
        sect("ACTIONS")
        travel_hint = c(f"  ({self.season.value}→{next_s.value} in {days_till}d)", GREY)
        print(f"  {key('T')} Trade   "
              f"  {key('V')} Travel{travel_hint}")
        print(f"  {key('I')} Inventory"
              f"  {key('W')} Wait / Rest")

        # ── OPERATIONS ───────────────────────────────────────────────────
        print()
        sect("OPERATIONS")
        biz_txt = "Businesses"
        if broken:
            biz_txt += c(f" ⚠{broken}", RED)
        elif self.businesses:
            biz_txt += c(f" [{len(self.businesses)}]", GREY)

        fin_txt = "Finance"
        if self.bank_balance > 0:
            fin_txt += c(f" ·{self.bank_balance:.0f}g", GREY)

        con_txt = "Contracts"
        if urgent_cons:
            con_txt += c(f" ⚠{urgent_cons}", RED)
        elif active_cons:
            con_txt += c(f" [{len(active_cons)}]", GREY)

        xden_txt = "Smuggling Den"
        if self.heat > 0:
            heat_col = RED if self.heat > 50 else YELLOW
            xden_txt += c(f" [HEAT:{self.heat}]", heat_col)

        print(f"  {key('B')} {biz_txt}   {key('F')} {fin_txt}   {key('C')} {con_txt}")
        print(f"  {key('S')} Skills         {key('X')} {xden_txt}")

        # ── INFORMATION ──────────────────────────────────────────────────
        print()
        sect("INFORMATION")
        news_txt = "News & Events"
        if self.news_feed:
            _, _, ev, _ = self.news_feed[0]
            if ev != "Local Rumour":
                news_txt += c(f" [{ev}]", YELLOW)
        print(f"  {key('M')} Market Info    {key('N')} {news_txt}")

        # ── PLAYER ───────────────────────────────────────────────────────
        print()
        sect("PLAYER")
        prog_txt = f"Progress {c(str(len(self.achievements)), CYAN)}/{len(ACHIEVEMENTS)}"
        rep_txt  = f"Reputation & Community [{len(self.licenses)}/5 lic]"
        print(f"  {key('P')} {prog_txt}   {key('R')} {rep_txt}")

        # ── SYSTEM ───────────────────────────────────────────────────────
        print()
        diff_col = {"easy": GREEN, "normal": CYAN,
                    "hard": YELLOW, "brutal": RED}.get(self.settings.difficulty, CYAN)
        as_txt   = c("[AS]", GREEN) if self.settings.autosave else c("[AS off]", GREY)
        diff_txt = c(self.settings.difficulty.capitalize(), diff_col)
        print(f"  {key('SAVE')} Save   {key('O')} Options·{diff_txt} {as_txt}   {key('Q')} Quit   {key('?')} Help")

    # ── Trading ──────────────────────────────────────────────────────────────

    def trade_menu(self):
        while True:
            market = self.markets[self.current_area]
            print(header(f"TRADE \u2014 {self.current_area.value}"))
            print(f"  {CYAN}1{RESET}. Buy items")
            print(f"  {CYAN}2{RESET}. Sell items")

    # ── Trading ──────────────────────────────────────────────────────────────

    def trade_menu(self):
        while True:
            market = self.markets[self.current_area]
            print(header(f"TRADE \u2014 {self.current_area.value}"))
            print(f"  {CYAN}1{RESET}. Buy items")
            print(f"  {CYAN}2{RESET}. Sell items")
            print(f"  {CYAN}3{RESET}. Price comparison (all regions)")
            print(f"  {CYAN}4{RESET}. Haggle on a purchase")
            print(f"  {CYAN}5{RESET}. Arbitrage advisor  {GREY}(best routes from here){RESET}")
            print(f"  {BOLD}[B]{RESET} Back")
            ch = prompt("Choice: ")
            if   ch == "1": self._buy_items()
            elif ch == "2": self._sell_items()
            elif ch == "3": self._compare_prices()
            elif ch == "4": self._haggle()
            elif ch == "5": self.arbitrage_menu()
            elif ch.upper() in ("6", "B"): break

    def _show_market_table(self, buy: bool = True):
        market = self.markets[self.current_area]
        mode = "BUY (you pay)" if buy else "SELL (you receive)"
        print(f"\n  {BOLD}{mode}{RESET}")
        print(f"  {'#':<4}{'Item':<22}{'Category':<18}{'Price':>8}  {'Stock':>6}  {'Trend':<8}  Rarity")
        print(f"  {GREY}{'─'*80}{RESET}")
        rows = []
        for idx, k in enumerate(sorted(market.item_keys), 1):
            item = ALL_ITEMS[k]
            if buy:
                price = market.get_buy_price(k, self.season, self.skills.trading)
            else:
                price = market.get_sell_price(k, self.season, self.skills.trading)
            stock = market.stock.get(k, 0)
            history = list(market.history.get(k, []))
            if len(history) >= 2:
                trend = "▲" if history[-1].price > history[-2].price else "▼"
                trend_col = GREEN if trend == "▲" else RED
            else:
                trend = "─"
                trend_col = GREY
            rarity_cols = {"common": WHITE, "uncommon": CYAN, "rare": YELLOW, "legendary": "\033[95m"}
            r_col = rarity_cols.get(item.rarity, WHITE)
            illegal = c(" [!]", RED) if item.illegal else ""
            rows.append((idx, k, item, price, stock, trend, trend_col, r_col, illegal))
            print(f"  {GREY}{idx:<4}{RESET}{item.name + illegal:<25}{item.category.value:<18}"
                  f"{c(f'{price:.2f}', YELLOW):>14}  {stock:>6}  "
                  f"{c(trend, trend_col):<8}  {c(item.rarity.capitalize(), r_col)}")
        return rows

    def _buy_items(self):
        rows = self._show_market_table(buy=True)
        if not rows:
            err("Nothing to buy here.")
            return

        cap   = self._max_carry_weight()
        space = round(max(0.0, cap - self._current_weight()), 1)
        print(f"\n  {c(f'Gold: {self.inventory.gold:.0f}g  |  Free carry: {space}/{cap:.0f}wt', GREY)}")
        raw = prompt("Item number(s) to buy (e.g. '2' or '1,3,5' or 'all'), or 'cancel': ")
        if raw.strip().lower() == "cancel":
            return

        targets: List = []
        if raw.strip().lower() == "all":
            targets = [(r[1], r[2]) for r in rows]
        else:
            for part in raw.replace(" ", "").split(","):
                try:
                    idx = int(part) - 1
                    if 0 <= idx < len(rows):
                        targets.append((rows[idx][1], rows[idx][2]))
                except ValueError:
                    pass

        market = self.markets[self.current_area]
        any_purchased = False
        for item_key, item in targets:
            # Calculate limits BEFORE touching the market
            cur_space     = max(0.0, self._max_carry_weight() - self._current_weight())
            max_by_weight = int(cur_space / item.weight) if item.weight > 0 else 9999
            price_est     = market.get_buy_price(item_key, self.season, self.skills.trading)
            max_by_gold   = int(self.inventory.gold / price_est) if price_est > 0 else 0
            max_by_stock  = market.stock.get(item_key, 0)
            max_can_buy   = max(0, min(max_by_weight, max_by_gold, max_by_stock))
            hint = c(f" [max: {max_can_buy}  \u2248 {price_est:.1f}g/ea]", GREY)

            try:
                qty_raw = prompt(f"Qty of {item.name}{hint} (or 'max'/'cancel'): ")
                if qty_raw.strip().lower() == "cancel":
                    continue
                if qty_raw.strip().lower() == "max":
                    qty = max_can_buy
                else:
                    qty = int(qty_raw)
                if qty <= 0:
                    continue
            except ValueError:
                err("Invalid quantity.")
                continue

            # Cap at carry weight
            if qty > max_by_weight:
                warn(f"Weight limit! Reducing from {qty} to {max_by_weight}.")
                qty = max_by_weight
                if qty <= 0:
                    err("No carry capacity!")
                    continue

            # Cap at stock
            available = market.stock.get(item_key, 0)
            if qty > available:
                warn(f"Only {available} in stock. Reducing.")
                qty = available
                if qty <= 0:
                    err("Out of stock!")
                    continue

            # Pre-check gold BEFORE touching market state
            total_cost = round(price_est * qty, 2)
            if total_cost > self.inventory.gold:
                err(f"Not enough gold! Need ~{total_cost:.0f}g, have {self.inventory.gold:.0f}g")
                continue

            result = market.buy_from_market(item_key, qty, self.season, self.skills.trading)
            if result < 0:
                err(f"Transaction error (code {result}). No purchase made.")
                continue

            self.inventory.gold -= result
            self.inventory.record_purchase(item_key, qty, result / qty)
            self.inventory.add(item_key, qty)
            ok(f"Bought {qty}x {item.name} for {c(f'-{result:.2f}g', RED)}")
            self._log_trade(f"BUY {qty}x {item.name} @ {result/qty:.2f}g each = {result:.2f}g total")
            self.lifetime_trades += 1
            self._gain_skill_xp(SkillType.TRADING, 5)
            any_purchased = True
        if any_purchased:
            self._use_time(1)

    def _sell_items(self):
        if not self.inventory.items:
            err("Inventory is empty!")
            return

        market = self.markets[self.current_area]

        def _build_sellable() -> List:
            rows = []
            for k, qty in sorted(self.inventory.items.items()):
                item = ALL_ITEMS.get(k)
                if not item:
                    continue
                sell_p = market.get_sell_price(k, self.season, self.skills.trading)
                is_local = k in market.item_keys
                if sell_p <= 0 or not is_local:
                    sell_p = item.base_price * 0.65
                avg_cost = self.inventory.cost_basis.get(k)
                rows.append((k, item, qty, sell_p, avg_cost))
            return rows

        def _print_sell_table(rows: List):
            print(header(f"SELL ITEMS \u2014 {self.current_area.value}"))
            print(f"  {BOLD}{'#':<4}{'Item':<24} {'Have':>5}  {'Sell@':>8}  {'Paid@':>8}  {'Return':>8}  {'Est. Profit':>12}{RESET}")
            print(f"  {GREY}{'\u2500' * 74}{RESET}")
            for idx, (k, item, qty, sell_p, avg_cost) in enumerate(rows, 1):
                illegal_tag = c(" [!]", RED) if item.illegal else ""
                sell_str    = c(f"{sell_p:.1f}g", YELLOW)
                if avg_cost:
                    ret_pct   = (sell_p - avg_cost) / max(avg_cost, 0.01) * 100
                    ret_col   = GREEN if ret_pct >= 0 else RED
                    ret_str   = c(f"{ret_pct:+.0f}%", ret_col)
                    cost_str  = c(f"{avg_cost:.1f}g", GREY)
                    est_prof  = (sell_p - avg_cost) * qty
                    prof_col  = GREEN if est_prof >= 0 else RED
                    prof_str  = c(f"{est_prof:+.0f}g", prof_col)
                else:
                    ret_str  = c("  n/a", GREY)
                    cost_str = c("  n/a", GREY)
                    prof_str = c("  n/a", GREY)
                if not (k in market.item_keys):
                    sell_str += c(" [pawn]", GREY)
                print(f"  {GREY}{idx:<4}{RESET}{item.name + illegal_tag:<24} "
                      f"{qty:>5}  {sell_str:>16}  {cost_str:>16}  "
                      f"{ret_str:>16}  {prof_str:>20}")
            print(f"  {GREY}[pawn] = not stocked here; selling at 65% of base price{RESET}")
            print(f"  {GREY}Gold: {self.inventory.gold:.0f}g   "
                  f"Weight: {self._current_weight():.1f}/{self._max_carry_weight():.0f}wt{RESET}")

        while True:
            sellable = _build_sellable()
            if not sellable:
                ok("Inventory is now empty.")
                return

            _print_sell_table(sellable)
            raw = prompt("Sell: number(s) / 'all' / 'cancel'  (add ':max' or ':N' e.g. '2:max', '1:50'): ")
            if not raw or raw.strip().lower() == "cancel":
                return

            # Parse targets: 'all' | '1,3' | '2:max' | '1:30,3:max'
            sell_all  = raw.strip().lower() == "all"
            sell_jobs: List[Tuple] = []  # (item_key, item, qty_to_sell, sell_p)

            if sell_all:
                sell_jobs = [(k, item, qty, sell_p)
                             for k, item, qty, sell_p, _ in sellable]
            else:
                for part in raw.replace(" ", "").split(","):
                    qty_override = None
                    if ":" in part:
                        num_s, qty_s = part.split(":", 1)
                        qty_override = qty_s.strip().lower()
                    else:
                        num_s = part
                    try:
                        idx = int(num_s.strip()) - 1
                        if not (0 <= idx < len(sellable)):
                            err(f"No item #{int(num_s.strip())}.")
                            continue
                        k, item, max_q, sell_p, _ = sellable[idx]
                        if qty_override is None:
                            # No qty given — ask
                            try:
                                q_raw = prompt(f"Qty of {item.name} (have {max_q}, or 'max'): ")
                                if q_raw.strip().lower() == "max":
                                    qty2 = max_q
                                else:
                                    qty2 = int(q_raw)
                            except ValueError:
                                err("Invalid quantity.")
                                continue
                        elif qty_override == "max":
                            qty2 = max_q
                        else:
                            try:
                                qty2 = int(qty_override)
                            except ValueError:
                                err(f"Invalid qty '{qty_override}'.")
                                continue
                        if qty2 <= 0 or qty2 > max_q:
                            err(f"Invalid qty {qty2} for {item.name} (have {max_q}).")
                            continue
                        sell_jobs.append((k, item, qty2, sell_p))
                    except ValueError:
                        err(f"Could not parse '{part}'.")

            if not sell_jobs:
                continue

            session_gold = 0.0
            session_profit = 0.0
            any_sold = False
            for item_key, item, qty, _ in sell_jobs:
                # Refresh sell price from live market (may have shifted)
                sell_p = market.get_sell_price(item_key, self.season, self.skills.trading)
                is_local = item_key in market.item_keys
                if sell_p <= 0 or not is_local:
                    sell_p = round(item.base_price * 0.65, 2)

                # Illegal item guard check — selling openly through normal market
                if item.illegal and self.current_area != Area.SWAMP:
                    guard = AREA_INFO[self.current_area]["guard_strength"]
                    if random.random() < guard * 0.10:
                        fine = round(item.base_price * qty * 0.6, 2)
                        self.inventory.remove(item_key, qty)   # goods seized
                        self.inventory.gold = max(0, self.inventory.gold - fine)
                        self.reputation     = max(0, self.reputation - 12)
                        self.heat           = min(100, self.heat + 22)
                        warn(f"Guards caught you selling {item.name}! "
                             f"{qty}x seized + fine {fine:.0f}g  Rep-12  Heat+22")
                        self._log_event(f"CAUGHT openly selling {item.name} — {qty}x seized + {fine:.0f}g fine")
                        continue

                avg_cost = self.inventory.cost_basis.get(item_key)
                earnings = market.sell_to_market(item_key, qty, self.season, self.skills.trading)
                if earnings < 0:
                    earnings = round(item.base_price * 0.65 * qty, 2)
                    warn(f"{item.name}: no local buyer \u2014 pawnbroker price (65% base).")

                # Apply difficulty + reputation multiplier to actual earnings
                sm = self._sell_mult()
                if sm < 1.0:
                    penalty_g = round(earnings * (1.0 - sm), 2)
                    earnings  = round(earnings * sm, 2)
                    rep_note  = "" if self.reputation >= 40 else f"  rep:{self.reputation}"
                    print(f"  {GREY}(Price adjusted ×{sm:.2f}{rep_note} — difficulty/rep penalty: -{penalty_g:.1f}g){RESET}")

                self.inventory.remove(item_key, qty)
                self.inventory.gold += earnings
                self.total_profit   += earnings
                session_gold        += earnings
                any_sold = True

                # P&L line
                ea = earnings / max(qty, 1)
                if avg_cost:
                    profit     = earnings - avg_cost * qty
                    pct        = (ea - avg_cost) / max(avg_cost, 0.01) * 100
                    pct_col    = GREEN if pct >= 0 else RED
                    session_profit += profit
                    pl_str = c(f"{profit:+.0f}g ({pct:+.0f}%)", pct_col)
                else:
                    profit     = 0.0
                    pl_str = c("(no cost data)", GREY)

                ok(f"Sold {qty}x {item.name}  "
                   f"{c(f'+{earnings:.0f}g', GREEN)} @ {ea:.1f}g/ea  "
                   f"P/L: {pl_str}")
                self._log_trade(
                    f"SELL {qty}x {item.name} @ {ea:.2f}g = {earnings:.2f}g"
                    + (f"  (paid {avg_cost:.2f}g, P/L {profit:+.0f}g)" if avg_cost else "")
                )
                self.lifetime_trades += 1
                self._gain_skill_xp(SkillType.TRADING, 5)
                # ── Achievement tracking ──────────────────────────────────
                if earnings > self.ach_stats.get("max_single_sale", 0):
                    self.ach_stats["max_single_sale"] = earnings
                if avg_cost is not None and profit < 0:
                    self._track_stat("sold_at_loss", True)
                # War / Plague event item tracking
                for ev in getattr(self.markets[self.current_area], "active_events", []):
                    ev_name = ev.get("name", "").upper() if isinstance(ev, dict) else str(ev).upper()
                    if "WAR" in ev_name and item_key in ("ore", "steel"):
                        self._track_stat("war_ore_sold", qty)
                    if "PLAGUE" in ev_name and item_key == "medicine":
                        self._track_stat("plague_medicine_sold", qty)

            if any_sold:
                prof_col = GREEN if session_profit >= 0 else RED
                print(f"  {GREY}\u2500\u2500 Session total: "
                      f"{c(f'+{session_gold:.0f}g received', GREEN)},  "
                      f"P/L: {c(f'{session_profit:+.0f}g', prof_col)}  "
                      f"| Gold now: {c(f'{self.inventory.gold:.0f}g', YELLOW)}{RESET}")
                self._use_time(1)
                self.ach_stats["wait_streak"] = 0
                self._check_achievements()

            if sell_all or not self.inventory.items:
                return  # done — no point looping if we sold everything

    def _haggle(self):
        """Attempt to negotiate a lower price at purchase — uses Haggling skill"""
        market = self.markets[self.current_area]
        rows = self._show_market_table(buy=True)
        try:
            idx = int(prompt("Item number to haggle on: ")) - 1
            if idx < 0 or idx >= len(rows):
                err("Invalid choice.")
                return
            item_key, item = rows[idx][1], rows[idx][2]
            qty = int(prompt(f"Quantity of {item.name}: "))
        except ValueError:
            err("Invalid input.")
            return

        # Haggling chance = 10% + 8% per haggling level
        chance = 0.10 + self.skills.haggling * 0.08
        discount = 0.0
        if random.random() < chance:
            discount = random.uniform(0.05, 0.15 + self.skills.haggling * 0.02)
            ok(f"Haggling succeeded! {int(discount*100)}% discount.")
        else:
            warn("Haggling failed — paying full price.")

        original_price = market.get_buy_price(item_key, self.season, self.skills.trading)
        final_price = round(original_price * (1 - discount), 2)
        total = final_price * qty

        cap = self._max_carry_weight()
        cur_w = self._current_weight()
        max_by_weight = int((cap - cur_w) / item.weight) if item.weight > 0 else qty
        if qty > max_by_weight:
            err(f"Over weight limit. Max: {max_by_weight}")
            return

        if total > self.inventory.gold:
            err(f"Not enough gold. Need {total:.2f}g, have {self.inventory.gold:.2f}g")
            return

        result = market.buy_from_market(item_key, qty, self.season, self.skills.trading)
        if result < 0:
            err("Transaction failed.")
            return
        # apply discount retroactively
        actual_total = final_price * qty
        self.inventory.gold -= actual_total
        self.inventory.record_purchase(item_key, qty, final_price)
        self.inventory.add(item_key, qty)
        ok(f"Bought {qty}x {item.name} for {c(f'{actual_total:.2f}g', YELLOW)}")
        self._log_trade(f"HAGGLE {qty}x {item.name} @ {final_price:.2f}g each = {actual_total:.2f}g")
        self._gain_skill_xp(SkillType.HAGGLING, 10)
        self._use_time(1)

    def _compare_prices(self):
        areas = list(Area)

        # 6-char abbreviations — exact width so │ separators always align
        _abbrev = {
            Area.CITY:     "CapCty",
            Area.FARMLAND: "Farmld",
            Area.MOUNTAIN: "MtnPk.",
            Area.COAST:    "Coast.",
            Area.FOREST:   "Forest",
            Area.DESERT:   "Desert",
            Area.SWAMP:    "Swamp.",
            Area.TUNDRA:   "Tundra",
        }
        _short = {a: v.rstrip(".") for a, v in _abbrev.items()}  # for route display

        COL  = 6   # visible chars per area price column (e.g. " 120g " → 6)
        ICOL = 22  # item name + flag column width

        # Collect all tradeable item keys grouped by category
        all_keys: set = set()
        for m in self.markets.values():
            all_keys.update(m.item_keys)
        cats: Dict[str, List[str]] = {}
        for k in sorted(all_keys):
            item = ALL_ITEMS.get(k)
            if item:
                cats.setdefault(item.category.value, []).append(k)

        # Area header cells — pad raw name first, then colour
        def _hcell(a: Area) -> str:
            name   = _abbrev.get(a, a.value[:COL])[:COL]
            padded = f"{name:^{COL}}"
            return c(padded, CYAN) if a == self.current_area else padded

        area_header  = "│".join(_hcell(a) for a in areas)
        spread_header = f"  {'Best Route':<24}  Profit"

        # Separator line — ┼ at every │ position, ─ everywhere else
        sep_line = (
            "─" * ICOL + "┼"
            + "┼".join("─" * COL for _ in areas)
            + "┼" + "─" * 32
        )

        print(header("PRICE COMPARISON  —  BUY prices (what you pay)"))
        print(f"  {c(f'Location: {self.current_area.value}', CYAN)}  "
              f"·  Season: {self.season.value}")
        print(f"  {c('Green = cheapest   Red = most expensive   Cyan = you are here', GREY)}")

        for cat, keys in sorted(cats.items()):
            print(f"\n  {BOLD}{YELLOW}{cat}{RESET}")
            print(f"  {'Item':<{ICOL}}│{area_header}│{spread_header}")
            print(f"  {GREY}{sep_line}{RESET}")

            for k in keys:
                item = ALL_ITEMS[k]

                # Gather current buy prices for every area that stocks this item
                buy_prices: Dict[Area, float] = {}
                for a in areas:
                    mkt = self.markets[a]
                    if k in mkt.item_keys:
                        buy_prices[a] = mkt.get_buy_price(k, self.season, self.skills.trading)

                if not buy_prices:
                    continue

                pvs    = list(buy_prices.values())
                min_p  = min(pvs)
                max_p  = max(pvs)
                unique = len(set(f"{p:.0f}" for p in pvs)) > 1

                # Item name column (flag illegal items)
                illegal_tag = c("!", RED) if item.illegal else " "
                name_cell   = f"{item.name:<{ICOL - 2}} {illegal_tag}"

                # Price cells — pad the raw string first, THEN apply colour,
                # then join with │ so separators are always single characters
                price_cells = []
                for a in areas:
                    if a in buy_prices:
                        p      = buy_prices[a]
                        p_raw  = f"{p:.0f}g"
                        padded = f"{p_raw:>{COL}}"
                        if unique and p == min_p:
                            price_col = GREEN       # cheapest: buy here
                        elif unique and p == max_p:
                            price_col = RED         # priciest: sell here
                        elif a == self.current_area:
                            price_col = CYAN
                        else:
                            price_col = WHITE
                        price_cells.append(c(padded, price_col))
                    else:
                        price_cells.append(c(f"{'─':^{COL}}", GREY))
                cells = "│".join(price_cells)

                # Spread: best buy area → best sell area
                best_sell_prices = {
                    a: self.markets[a].get_sell_price(k, self.season, self.skills.trading)
                    for a in areas if k in self.markets[a].item_keys
                }
                best_sell_p    = max(best_sell_prices.values())
                best_buy_area  = min(buy_prices, key=buy_prices.get)
                best_sell_area = max(best_sell_prices, key=best_sell_prices.get)
                route_profit   = best_sell_p - min_p
                buy_ab         = _short.get(best_buy_area,  best_buy_area.value[:5])
                sell_ab        = _short.get(best_sell_area, best_sell_area.value[:5])
                route_str      = f"{min_p:.0f}g({buy_ab}) → {best_sell_p:.0f}g({sell_ab})"
                profit_col     = GREEN if route_profit > item.base_price * 0.08 else (
                                 YELLOW if route_profit > 0 else RED)
                spread_cell    = f"  {route_str:<24}  {c(f'{route_profit:+.0f}g', profit_col)}"

                print(f"  {name_cell}│{cells}│{spread_cell}")

        print()
        pause()

    # ── Travel ───────────────────────────────────────────────────────────────

    def travel_menu(self):
        days_till   = self.DAYS_PER_SEASON - ((self.day - 1) % self.DAYS_PER_SEASON)
        seasons_lst = list(Season)
        next_s      = seasons_lst[(seasons_lst.index(self.season) + 1) % 4]
        print(header("TRAVEL"))
        print(f"  Season: {c(self.season.value, CYAN)}  \u00b7  "
              f"Next season ({c(next_s.value, YELLOW)}) in {days_till} day(s)")
        excess = self._current_weight() - self._max_carry_weight()
        if excess > 0:
            warn(f"Overloaded by {excess:.1f}wt! Travel takes extra days (+1d per 15wt over limit).")
        else:
            print(f"  {GREY}Carry: {self._current_weight():.1f}/{self._max_carry_weight():.0f}wt \u00b7 overloading adds extra travel days{RESET}")
        print()
        areas = [a for a in Area if a != self.current_area]
        for i, area in enumerate(areas, 1):
            days     = AREA_INFO[self.current_area]["travel_days"].get(area, 3)
            risk     = AREA_INFO[area]["travel_risk"]
            risk_col = RED if risk > 0.12 else YELLOW if risk > 0.07 else GREEN
            # Show top 4 items stocked in that area's market
            mkt_keys  = list(self.markets[area].item_keys)[:4]
            items_str = ", ".join(ALL_ITEMS[k].name for k in mkt_keys if k in ALL_ITEMS)
            print(f"  {CYAN}{i}{RESET}. {area.value:<20}  "
                  f"{days}d travel  Risk: {c(f'{int(risk*100)}%', risk_col)}")
            print(f"     {GREY}{AREA_INFO[area]['description']}{RESET}")
            print(f"     {GREY}Sells: {items_str}...{RESET}")

        raw = prompt("Travel to (number) or 'cancel': ")
        if raw.strip().lower() == "cancel":
            return
        try:
            idx = int(raw.strip()) - 1
            if idx < 0 or idx >= len(areas):
                err("Invalid choice.")
                return
            dest = areas[idx]
        except ValueError:
            err("Invalid input.")
            return

        days_travel = AREA_INFO[self.current_area]["travel_days"].get(dest, 3)
        risk = AREA_INFO[dest]["travel_risk"]

        # Weight penalty: overweight slows travel (extra days)
        excess = self._current_weight() - self._max_carry_weight()
        if excess > 0:
            extra_days = max(1, int(excess / 15))
            warn(f"Overloaded! Journey takes {extra_days} extra day(s).")
            days_travel += extra_days

        # ── Travel expenses ───────────────────────────────────────────────
        travel_cost = round(days_travel * 3.0 * self.settings.cost_mult, 1)
        print(f"\n  {GREY}Travel cost: {c(f'{travel_cost:.1f}g', YELLOW)} "
              f"({days_travel}d × 3g base × {self.settings.cost_mult:.2f} difficulty){RESET}")
        if self.inventory.gold < travel_cost:
            err("Not enough gold to cover travel expenses!")
            return
        self.inventory.gold -= travel_cost
        self._log_event(f"Travel expenses: -{travel_cost:.1f}g to {dest.value}")

        # ── Bodyguard hire ────────────────────────────────────────────────
        effective_risk = min(0.90, risk + self.markets[dest].travel_risk_override)
        self.bodyguard_hired = False
        if effective_risk >= 0.05:
            guard_cost = round(effective_risk * 120 * self.settings.cost_mult)
            guard_cost = max(10, guard_cost)
            guard_ch = prompt(
                f"  Hire a bodyguard for this trip? "
                f"Cost: {c(f'{guard_cost}g', YELLOW)}  "
                f"(reduces attack chance by ~60%)  [yes/no]: "
            )
            if guard_ch.strip().lower() in ("yes", "y"):
                if self.inventory.gold >= guard_cost:
                    self.inventory.gold -= guard_cost
                    self.bodyguard_hired = True
                    ok(f"Bodyguard hired for {guard_cost}g.")
                else:
                    err("Not enough gold to hire bodyguard.")

        print(f"\n  Traveling to {dest.value} ({days_travel} days)...")
        for _ in range(days_travel):
            self._advance_day()

        self.current_area = dest
        ok(f"Arrived at {dest.value}!")
        self._log_event(f"Traveled to {dest.value}")
        # ── Achievement tracking ──────────────────────────────────────────
        self._track_stat("areas_visited", dest.name)
        self._track_stat("journeys")
        self._track_stat("travel_days", days_travel)
        self.ach_stats["wait_streak"] = 0
        self._check_achievements()

        # Travel risk event — use war-boosted risk; bodyguard halves attack odds
        effective_risk = min(0.90, risk + self.markets[dest].travel_risk_override)
        if random.random() < effective_risk:
            self._travel_incident(dest)
        self.bodyguard_hired = False  # bodyguard contract ends on arrival

        # Heat slowly dissipates when traveling
        self.heat = max(0, self.heat - days_travel * 3)

    def _travel_incident(self, dest: Area):
        """Bad things can happen on the road"""
    def _travel_incident(self, dest: Area):
        """Bad things can happen on the road."""
        roll = random.random()
        illegal_items = [k for k in self.inventory.items
                         if ALL_ITEMS.get(k, Item("","",0,ItemCategory.RAW_MATERIAL)).illegal]

        # ── Dedicated armed attack (scales with difficulty + bodyguard) ──
        # Attack base chance = 25%; bodyguard halves it; brutal doubles it
        attack_threshold = 0.25 * self.settings.attack_mult
        if self.bodyguard_hired:
            attack_threshold *= 0.40  # bodyguard cuts attack chance by 60%

        if roll < attack_threshold:
            if self.bodyguard_hired and random.random() < 0.55:
                # Bodyguard repels the attackers
                ok("Armed assailants ambush you — but your bodyguard drives them off!")
                self._log_event("Attack repelled by bodyguard")
            else:
                # Attack succeeds — lose gold AND an item
                stolen_gold = round(self.inventory.gold * random.uniform(0.10, 0.30), 2)
                self.inventory.gold = max(0, self.inventory.gold - stolen_gold)
                msg = f"Armed attack! You lose {stolen_gold:.2f}g"
                if self.inventory.items:
                    k = random.choice(list(self.inventory.items.keys()))
                    qty = max(1, self.inventory.items[k] // 3)
                    self.inventory.remove(k, qty)
                    msg += f" and {qty}x {ALL_ITEMS.get(k,Item('?','?',0,ItemCategory.RAW_MATERIAL)).name}"
                    self._log_event(f"Armed attack — lost {stolen_gold:.2f}g + {qty}x {k}")
                else:
                    self._log_event(f"Armed attack — lost {stolen_gold:.2f}g")
                self.reputation = max(0, self.reputation - 3)
                warn(msg + "!")
                self._track_stat("attacks_suffered")
                self._check_achievements()
            return

        # Adjust roll to redistribute remaining incidents across [0, 1)
        # re-scale so events below fill 1.0 uniformly
        roll_adj = (roll - attack_threshold) / max(0.01, 1.0 - attack_threshold)

        if roll_adj < 0.30:
            # Bandits steal gold
            stolen = round(self.inventory.gold * random.uniform(0.05, 0.18), 2)
            self.inventory.gold = max(0, self.inventory.gold - stolen)
            warn(f"Bandits ambush your caravan! You lose {stolen:.2f} gold.")
            self._log_event(f"Bandit attack — lost {stolen:.2f}g")
            self.reputation = max(0, self.reputation - 2)
            self._track_stat("attacks_suffered")
        elif roll_adj < 0.50:
            # Bandits steal an item
            if self.inventory.items:
                k = random.choice(list(self.inventory.items.keys()))
                qty_stolen = max(1, self.inventory.items[k] // 3)
                self.inventory.remove(k, qty_stolen)
                warn(f"Bandits steal {qty_stolen}x "
                     f"{ALL_ITEMS.get(k,Item('?','?',0,ItemCategory.RAW_MATERIAL)).name}!")
                self._log_event(f"Bandit theft — lost {qty_stolen}x {k}")
        elif roll_adj < 0.62 and illegal_items:
            # Border inspection
            guard = AREA_INFO[dest]["guard_strength"]
            if guard > 0:
                fine_total = 0.0
                for k in illegal_items:
                    qty  = self.inventory.items[k]
                    fine = ALL_ITEMS[k].base_price * qty * 0.8
                    fine_total += fine
                    self.inventory.remove(k, qty)
                self.inventory.gold = max(0, self.inventory.gold - fine_total)
                self.reputation     = max(0, self.reputation - 15)
                self.heat           = min(100, self.heat + 30)
                warn(f"Border inspection! Contraband seized and fined {fine_total:.2f}g. "
                     "Rep -15. Heat +30.")
                self._log_event(f"Border inspection — contraband seized, fined {fine_total:.2f}g")
        elif roll_adj < 0.78:
            # Lucky find
            lucky_items = ["herbs", "gold_dust", "gem", "spice", "fur"]
            k   = random.choice(lucky_items)
            qty = random.randint(1, 5)
            self.inventory.add(k, qty)
            ok(f"Lucky find! You discover {qty}x {ALL_ITEMS[k].name} abandoned on the road.")
            self._log_event(f"Lucky find: {qty}x {k}")
            self._track_stat("lucky_finds")
            self._check_achievements()
        else:
            # Storm / accident damages goods
            if self.inventory.items:
                k   = random.choice(list(self.inventory.items.keys()))
                dmg = max(1, self.inventory.items[k] // 4)
                self.inventory.remove(k, dmg)
                warn(f"Harsh weather! {dmg}x "
                     f"{ALL_ITEMS.get(k,Item('?','?',0,ItemCategory.RAW_MATERIAL)).name} "
                     "spoiled/damaged.")
                self._log_event(f"Weather damage — lost {dmg}x {k}")

    # ── Businesses ───────────────────────────────────────────────────────────

    def businesses_menu(self):
        while True:
            print(header("BUSINESSES"))
            if self.businesses:
                print(f"  {'#':<4}{'Name':<22}{'Produces':<16}{'Level':<7}{'Workers':<9}{'Prod/day':<10}{'Status'}")
                print(f"  {GREY}{'─'*80}{RESET}")
                for i, b in enumerate(self.businesses, 1):
                    prod = b.daily_production()
                    status = c("BROKEN", RED) if b.broken_down else c("Running", GREEN)
                    item = ALL_ITEMS.get(b.item_produced, Item("?","?",0,ItemCategory.RAW_MATERIAL))
                    print(f"  {GREY}{i:<4}{RESET}{b.name:<22}{item.name:<16}{b.level:<7}{b.workers}/{b.max_workers:<7}{prod:<10}{status}")
            else:
                print(c("  You own no businesses.", GREY))

            print(f"\n  {CYAN}1{RESET}. Purchase a business")
            print(f"  {CYAN}2{RESET}. Upgrade a business")
            print(f"  {CYAN}3{RESET}. Hire/Fire workers")
            print(f"  {CYAN}4{RESET}. Repair broken business")
            print(f"  {CYAN}5{RESET}. Sell a business")
            print(f"  {BOLD}[B]{RESET} Back")
            ch = prompt("Choice: ")
            if ch == "1":   self._purchase_business()
            elif ch == "2": self._upgrade_business()
            elif ch == "3": self._manage_workers()
            elif ch == "4": self._repair_business()
            elif ch == "5": self._sell_business()
            elif ch.upper() in ("6", "B"): break

    def _purchase_business(self):
        print(header("PURCHASE A BUSINESS"))
        available = []
        for idx, (key, data) in enumerate(BUSINESS_CATALOGUE.items(), 1):
            item = ALL_ITEMS.get(data["item"], Item("?","?",0,ItemCategory.RAW_MATERIAL))
            daily_rev = item.base_price * data["rate"]
            net = daily_rev - data["cost"]
            area_str = data["area"].value
            cost_str = f"{data['buy']:.0f}g"
            net_str = f"{net:.0f}g/day"
            net_col = GREEN if net > 0 else RED
            print(f"  {CYAN}{idx}{RESET}. {data['name']:<22} Location: {area_str:<15} Cost: {c(cost_str, YELLOW)}")
            print(f"     Produces {data['rate']}/day {item.name}  ·  Running cost: {data['cost']:.0f}g/day  ·  Est. net: {c(net_str, net_col)}")
            available.append(key)

        try:
            idx = int(prompt("Purchase (0 to cancel): ")) - 1
            if idx < 0 or idx >= len(available):
                return
            key = available[idx]
            data = BUSINESS_CATALOGUE[key]
            cost = data["buy"]
            if LicenseType.BUSINESS not in self.licenses:
                err("You need a Business Permit license to own businesses.")
                err("Purchase one from  18. Permits & Licenses  in the main menu.")
                return
            if cost > self.inventory.gold:
                err(f"Need {cost}g, have {self.inventory.gold:.2f}g")
                return
            self.inventory.gold -= cost
            b = make_business(key, data["area"])
            self.businesses.append(b)
            ok(f"Purchased {b.name} for {cost}g! Located in {b.area.value}.")
            self._log_event(f"Purchased {b.name}")
            self._gain_skill_xp(SkillType.INDUSTRY, 20)
        except (ValueError, IndexError):
            err("Invalid choice.")

    def _upgrade_business(self):
        if not self.businesses:
            err("No businesses.")
            return
        print(header("UPGRADE BUSINESS"))
        for i, b in enumerate(self.businesses, 1):
            cost = b.level * 200 + b.purchase_cost * 0.3
            next_level_mult = 1.0 + b.level * 0.6  # level+1 applied
            avg_prod = (sum(w["productivity"] for w in b.hired_workers) / max(b.workers, 1)
                        if b.hired_workers else 1.0)
            worker_bonus = 1.0 + max(0, (b.workers - 1) * 0.15)
            prod_after = int(b.production_rate * next_level_mult * worker_bonus * avg_prod)
            print(f"  {CYAN}{i}{RESET}. {b.name} Lv{b.level} → Lv{b.level+1}  Cost: {c(f'{cost:.0f}g', YELLOW)}  New prod: {prod_after}/day")
        try:
            idx = int(prompt("Upgrade (0 to cancel): ")) - 1
            if idx < 0 or idx >= len(self.businesses):
                return
            b = self.businesses[idx]
            cost = b.level * 200 + b.purchase_cost * 0.3
            if cost > self.inventory.gold:
                err(f"Need {cost:.0f}g")
                return
            self.inventory.gold -= cost
            b.level += 1
            ok(f"Upgraded {b.name} to Level {b.level}!")
            self._gain_skill_xp(SkillType.INDUSTRY, 15)
        except (ValueError, IndexError):
            err("Invalid choice.")

    @staticmethod
    def _generate_applicants(count: int = 4) -> List[Dict]:
        """Generate a pool of job applicants with random stats."""
        _first = [
            "Aldric","Bram","Cora","Dag","Elra","Finn","Greta","Holt",
            "Isa","Jorin","Kev","Lena","Mira","Ned","Ora","Pip",
            "Quinn","Rolf","Sable","Tilda","Ulf","Vera","Wren","Xan",
            # new additions
            "Baxter","Cedric","Delia","Edwyn","Faye","Gareth","Hilda","Ingrid",
            "Jasper","Kira","Lorcan","Mabel","Niles","Oona","Percival","Rhea",
            "Sigrid","Torben","Ursula","Vance","Wendell","Yara","Zane","Alvar",
            "Brunhild","Calder","Draven","Esmé","Ferris","Gwenna","Hugo","Ilsa",
            "Jovan","Ketil","Liora","Magnus","Nora","Oswin","Phoebe","Rand",
            "Selwyn","Theron","Una","Viggo","Wulfric","Xenia","Ysolde","Zarko",
        ]
        _last = [
            "Miller","Cooper","Smith","Tanner","Fisher","Brewer",
            "Thatcher","Mason","Wright","Fletcher",
            # new additions
            "Barrow","Cotter","Dyer","Eastman","Forges","Galloway",
            "Hayward","Ironsides","Jenks","Kettler","Larder","Moorfield",
            "Nettles","Oldham","Pickwick","Quarry","Rushton","Saltmarsh",
            "Trudge","Underhill","Vickers","Weatherby","Yarrow","Zeal",
        ]
        applicants = []
        for _ in range(count):
            prod  = round(random.uniform(0.70, 1.40), 2)  # multiplier vs. standard worker
            wage  = round(random.uniform(5.0, 14.0), 1)   # gold/day
            trait_pool = []
            if prod >= 1.25: trait_pool.append(c("Skilled", GREEN))
            elif prod <= 0.82: trait_pool.append(c("Lazy", RED))
            if wage <= 6.5:  trait_pool.append(c("Cheap", GREEN))
            elif wage >= 12: trait_pool.append(c("Expensive", YELLOW))
            trait = ", ".join(trait_pool) if trait_pool else c("Average", GREY)
            applicants.append({
                "name":        f"{random.choice(_first)} {random.choice(_last)}",
                "wage":        wage,
                "productivity": prod,
                "trait":       trait,
            })
        return applicants

    def _manage_workers(self):
        if not self.businesses:
            err("No businesses.")
            return

        # Ensure hired_workers list is in sync with legacy workers int
        for b in self.businesses:
            if not b.hired_workers and b.workers > 0:
                # Migrate old save: synthesise generic workers
                b.hired_workers = [{"name": f"Worker {i+1}", "wage": 8.0, "productivity": 1.0}
                                   for i in range(b.workers)]

        while True:
            print(header("MANAGE WORKERS"))
            print(f"  {GREY}Workers produce goods. 0 workers = no production.{RESET}")
            print(f"  {GREY}Each worker beyond the first adds +15% to base output.{RESET}")
            print()
            for i, b in enumerate(self.businesses, 1):
                item    = ALL_ITEMS.get(b.item_produced)
                prod    = b.daily_production()
                status  = c("BROKEN", RED) if b.broken_down else (
                          c("Idle",   YELLOW) if b.workers == 0 else
                          c(f"{prod}/day", GREEN))
                daily_w = b.worker_daily_wage()
                print(f"  {CYAN}{i}{RESET}. {b.name:<22}  "
                      f"Workers: {c(str(b.workers), CYAN)}/{b.max_workers}  "
                      f"Output: {status}  "
                      f"Wages: {c(f'{daily_w:.1f}g/day', YELLOW)}")
            print(f"\n  {BOLD}[B]{RESET} Back")
            raw = prompt("Select business to manage (or B): ")
            if raw.strip().upper() in ("B", "0") or not raw.strip():
                return
            try:
                bidx = int(raw.strip()) - 1
                if not (0 <= bidx < len(self.businesses)):
                    err("Invalid business.")
                    continue
            except ValueError:
                err("Invalid input.")
                continue

            b = self.businesses[bidx]

            while True:
                item   = ALL_ITEMS.get(b.item_produced)
                prod   = b.daily_production()
                wages  = b.worker_daily_wage()
                print(f"\n  {BOLD}{b.name}{RESET}  —  Lv{b.level}  "
                      f"Produces: {item.name if item else '?'}")
                if b.workers == 0:
                    print(f"  {c('  ⚠  No workers hired — business produces nothing!', YELLOW)}")
                else:
                    eff = sum(w["productivity"] for w in b.hired_workers) / max(b.workers, 1)
                    print(f"  Output: {c(f'{prod}/day', GREEN)}  "
                          f"Avg productivity: {c(f'{eff:.2f}x', CYAN)}  "
                          f"Total wages: {c(f'{wages:.1f}g/day', YELLOW)}")

                if b.hired_workers:
                    print(f"\n  {BOLD}Current Staff:{RESET}")
                    print(f"  {'#':<4}{'Name':<22}{'Wage/day':>10}{'Productivity':>14}  Trait")
                    print(f"  {GREY}{'─' * 58}{RESET}")
                    for wi, w in enumerate(b.hired_workers, 1):
                        print(f"  {GREY}{wi:<4}{RESET}{w['name']:<22}"
                              f"{c(f"{w['wage']:.1f}g", YELLOW):>18}"
                              f"{c(f"{w['productivity']:.2f}x", CYAN):>22}  {w.get('trait', '')}")

                print(f"\n  {CYAN}1{RESET}. Hire new worker  "
                      f"{GREY}(see applicants)  {b.workers}/{b.max_workers} slots filled{RESET}")
                print(f"  {CYAN}2{RESET}. Fire a worker")
                print(f"  {BOLD}[B]{RESET} Back")
                sub = prompt("Choice: ")

                if sub.upper() in ("B", "3", ""):
                    break

                elif sub == "1":
                    if b.workers >= b.max_workers:
                        err(f"Already at max workers ({b.max_workers})!")
                        continue
                    applicants = self._generate_applicants(4)
                    print(f"\n  {BOLD}Applicants for {b.name}:{RESET}")
                    print(f"  {'#':<4}{'Name':<22}{'Wage/day':>10}{'Productivity':>14}  Trait")
                    print(f"  {GREY}{'─' * 58}{RESET}")
                    for ai, ap in enumerate(applicants, 1):
                        print(f"  {CYAN}{ai:<4}{RESET}{ap['name']:<22}"
                              f"{c(f"{ap['wage']:.1f}g", YELLOW):>18}"
                              f"{c(f"{ap['productivity']:.2f}x", CYAN):>22}  {ap['trait']}")
                    print(f"  {GREY}Productivity multiplies daily output. Wage is daily gold cost.{RESET}")
                    raw2 = prompt("Hire applicant # (or 'cancel'): ")
                    if raw2.strip().lower() == "cancel":
                        continue
                    try:
                        aidx = int(raw2.strip()) - 1
                        if not (0 <= aidx < len(applicants)):
                            err("Invalid choice.")
                            continue
                        chosen = applicants[aidx]
                        b.hired_workers.append(chosen)
                        b.workers = len(b.hired_workers)
                        ok(f"Hired {chosen['name']} at {chosen['wage']:.1f}g/day "
                           f"(productivity {chosen['productivity']:.2f}x).")
                    except ValueError:
                        err("Invalid input.")

                elif sub == "2":
                    if not b.hired_workers:
                        err("No workers to fire.")
                        continue
                    print(f"\n  Fire which worker?")
                    for wi, w in enumerate(b.hired_workers, 1):
                        print(f"  {CYAN}{wi}{RESET}. {w['name']}  "
                              f"{w['wage']:.1f}g/day  "
                              f"productivity {w['productivity']:.2f}x")
                    raw3 = prompt("Fire # (or 'cancel'): ")
                    if raw3.strip().lower() == "cancel":
                        continue
                    try:
                        fidx = int(raw3.strip()) - 1
                        if not (0 <= fidx < len(b.hired_workers)):
                            err("Invalid choice.")
                            continue
                        fired = b.hired_workers.pop(fidx)
                        b.workers = len(b.hired_workers)
                        ok(f"Fired {fired['name']}.")
                    except ValueError:
                        err("Invalid input.")

    def _repair_business(self):
        broken = [b for b in self.businesses if b.broken_down]
        if not broken:
            ok("All businesses are running fine!")
            return
        for i, b in enumerate(broken, 1):
            print(f"  {CYAN}{i}{RESET}. {b.name}  Repair cost: {c(f'{b.repair_cost:.0f}g', YELLOW)}")
        try:
            idx = int(prompt("Repair (0 to cancel): ")) - 1
            if idx < 0 or idx >= len(broken):
                return
            b = broken[idx]
            if b.repair_cost > self.inventory.gold:
                err(f"Need {b.repair_cost:.0f}g to repair.")
                return
            self.inventory.gold -= b.repair_cost
            b.broken_down = False
            b.repair_cost = 0.0
            ok(f"{b.name} repaired and back in operation!")
            self._track_stat("repairs")
            self._check_achievements()
        except (ValueError, IndexError):
            err("Invalid choice.")

    def _sell_business(self):
        if not self.businesses:
            err("No businesses.")
            return
        print(header("SELL A BUSINESS"))
        for i, b in enumerate(self.businesses, 1):
            sale_price = b.purchase_cost * b.level * 0.65
            print(f"  {CYAN}{i}{RESET}. {b.name} Lv{b.level}  Sale price: {c(f'{sale_price:.0f}g', YELLOW)}")
        try:
            idx = int(prompt("Sell (0 to cancel): ")) - 1
            if idx < 0 or idx >= len(self.businesses):
                return
            b = self.businesses[idx]
            sale_price = b.purchase_cost * b.level * 0.65
            confirm = prompt(f"Sell {b.name} for {sale_price:.0f}g? (yes/no): ")
            if confirm.lower() == "yes":
                self.inventory.gold += sale_price
                self.businesses.pop(idx)
                ok(f"Sold {b.name} for {sale_price:.0f}g.")
                self._log_event(f"Sold {b.name} for {sale_price:.0f}g")
        except (ValueError, IndexError):
            err("Invalid choice.")

    # ── Banking & Loans ───────────────────────────────────────────────────────

    def banking_menu(self):
        while True:
            monthly_rate = 0.015 + self.skills.banking * 0.002
            print(header("BANKING & LOANS"))
            print(f"  Wallet: {c(f'{self.inventory.gold:.2f}g', YELLOW)}   "
                  f"Bank (liquid): {c(f'{self.bank_balance:.2f}g', YELLOW)}")
            print(f"  Savings rate: {c(f'{monthly_rate*100:.1f}%/month', GREEN)}  "
                  f"{GREY}(+{self.skills.banking * 0.002 * 100:.1f}%/mo from Banking skill  ·  paid every 30 days){RESET}")

            # Active CDs
            if self.cds:
                print(f"\n  {BOLD}Certificates of Deposit:{RESET}")
                today = self._absolute_day()
                for cd in self.cds:
                    days_left = cd.maturity_day - today
                    payout    = round(cd.principal * (1 + cd.rate), 2)
                    profit    = round(payout - cd.principal, 2)
                    dl_col    = RED if days_left <= 5 else YELLOW if days_left <= 15 else GREEN
                    print(f"  · {cd.principal:.0f}g locked for {cd.term_days}d  "
                          f"→  {c(f'{payout:.0f}g', GREEN)} at maturity  "
                          f"(+{profit:.0f}g, {cd.rate*100:.0f}%)  "
                          f"  {c(f'{days_left}d left', dl_col)}")

            # Outstanding loans
            if self.loans:
                print(f"\n  {BOLD}Outstanding Loans:{RESET}")
                for i, loan in enumerate(self.loans, 1):
                    total_left = round(loan.monthly_payment * loan.months_remaining, 2)
                    print(f"  {i}. {loan.principal:.0f}g principal  "
                          f"Rate: {loan.interest_rate*100:.2f}%/mo  "
                          f"Months left: {loan.months_remaining}  "
                          f"Monthly: {loan.monthly_payment:.2f}g  "
                          f"{GREY}(total left: {total_left:.0f}g){RESET}")

            print(f"\n  {CYAN}1{RESET}. Deposit gold into savings")
            print(f"  {CYAN}2{RESET}. Withdraw from savings")
            print(f"  {CYAN}3{RESET}. Take out a loan")
            print(f"  {CYAN}4{RESET}. Repay a loan early (lump sum)")
            print(f"  {CYAN}5{RESET}. Open a Certificate of Deposit  "
                  f"{GREY}(lock funds, earn significantly more){RESET}")
            _lend_tag = "" if LicenseType.LENDER   in self.licenses else c("  [needs Lending Charter]", GREY)
            _fund_tag = "" if LicenseType.FUND_MGR in self.licenses else c("  [needs Fund Manager License]", GREY)
            print(f"  {CYAN}6{RESET}. Citizen Lending{_lend_tag}")
            print(f"  {CYAN}7{RESET}. Stock Exchange{_fund_tag}")
            print(f"  {CYAN}8{RESET}. Fund Management{_fund_tag}")
            print(f"  {BOLD}[B]{RESET} Back")
            ch = prompt("Choice: ")
            if ch == "1":
                try:
                    amt = float(prompt("Deposit amount: "))
                    if amt <= 0 or amt > self.inventory.gold:
                        err("Invalid amount.")
                    else:
                        self.inventory.gold -= amt
                        self.bank_balance   += amt
                        ok(f"Deposited {amt:.2f}g  (earns {monthly_rate*100:.1f}%/mo)")
                except ValueError:
                    err("Invalid input.")
            elif ch == "2":
                try:
                    amt = float(prompt("Withdraw amount: "))
                    if amt <= 0 or amt > self.bank_balance:
                        err("Invalid amount.")
                    else:
                        self.bank_balance   -= amt
                        self.inventory.gold += amt
                        ok(f"Withdrew {amt:.2f}g")
                except ValueError:
                    err("Invalid input.")
            elif ch == "3":
                self._take_loan()
            elif ch == "4":
                self._repay_loan()
            elif ch == "5":
                self._open_cd()
            elif ch == "6":
                self.citizen_lending_menu()
            elif ch == "7":
                self.stock_market_menu()
            elif ch == "8":
                self.fund_management_menu()
            elif ch.upper() in ("9", "B"):
                break

    def _take_loan(self):
        max_loan = max(500.0, self._net_worth() * 0.4)
        # Rate: ~1.8%/month base; bad rep raises it, banking skill lowers it
        credit_penalty = (50 - self.reputation) / 100  # 0 at neutral, +0.5 at terrible
        rate = 0.018 + max(0.0, credit_penalty) * 0.008 - self.skills.banking * 0.001
        rate = round(max(0.006, min(rate, 0.04)), 4)   # clamp 0.6%–4%/month
        print(f"\n  Max available loan: {c(f'{max_loan:.0f}g', YELLOW)}")
        rate_col = RED if rate > 0.025 else YELLOW if rate > 0.015 else GREEN
        print(f"  Interest rate: {c(f'{rate*100:.2f}%/month', rate_col)}  "
              f"{GREY}({rate * 1200:.1f}%/year equivalent){RESET}")
        print(f"  {GREY}Repayments are auto-deducted every 30 days."
              f"  Defaulting grows debt by 50% and costs reputation.{RESET}")
        try:
            amt = float(prompt("Loan amount (0 to cancel): "))
            if amt <= 0:
                return
            if amt > max_loan:
                err(f"Cannot borrow more than {max_loan:.0f}g")
                return
            term_raw = prompt("Repayment term — enter 6 or 12 months: ").strip()
            months   = 6 if term_raw == "6" else 12
            monthly  = round(amt * (rate * (1 + rate)**months) / ((1 + rate)**months - 1), 2)
            total_repaid   = round(monthly * months, 2)
            total_interest = round(total_repaid - amt, 2)
            print(f"\n  Loan: {c(f'{amt:.0f}g', YELLOW)}  "
                  f"Monthly payment: {c(f'{monthly:.2f}g', YELLOW)}  "
                  f"Term: {months} months  "
                  f"Total interest: {c(f'{total_interest:.0f}g', RED)}")
            confirm = prompt("Confirm loan? (yes/no): ")
            if confirm.lower() == "yes":
                self.inventory.gold += amt
                self.loans.append(LoanRecord(principal=amt, interest_rate=rate,
                                              months_remaining=months, monthly_payment=monthly))
                ok(f"Loan of {amt:.0f}g received!  First payment due in 30 days.")
                self._log_event(f"Took loan of {amt:.0f}g @ {rate*100:.2f}%/mo for {months}mo")
                self._gain_skill_xp(SkillType.BANKING, 10)
                self._track_stat("loans_taken")
                self._check_achievements()
        except ValueError:
            err("Invalid input.")

    def _repay_loan(self):
        if not self.loans:
            ok("No outstanding loans!")
            return
        for i, loan in enumerate(self.loans, 1):
            remaining_principal = loan.monthly_payment * loan.months_remaining
            print(f"  {CYAN}{i}{RESET}. Payoff: {remaining_principal:.2f}g  (saves future interest)")
        try:
            idx = int(prompt("Repay which loan (0 to cancel): ")) - 1
            if idx < 0 or idx >= len(self.loans):
                return
            loan = self.loans[idx]
            payoff = loan.monthly_payment * loan.months_remaining
            if payoff > self.inventory.gold:
                err(f"Need {payoff:.2f}g to pay off loan.")
                return
            confirm = prompt(f"Pay off {payoff:.2f}g in full? (yes/no): ")
            if confirm.lower() == "yes":
                self.inventory.gold -= payoff
                self.loans.pop(idx)
                ok("Loan fully repaid!")
                self.reputation = min(100, self.reputation + 5)
                self._gain_skill_xp(SkillType.BANKING, 15)
                self._track_stat("loans_repaid")
                self._check_achievements()
        except (ValueError, IndexError):
            err("Invalid choice.")

    def _open_cd(self):
        """Open a Certificate of Deposit — lock gold for a fixed term, earn a flat return."""
        CD_TIERS = [
            {"days": 30,  "label": "Short-Term   (30 days) ", "base_rate": 0.08},
            {"days": 90,  "label": "Standard     (90 days) ", "base_rate": 0.26},
            {"days": 180, "label": "Extended    (180 days) ", "base_rate": 0.55},
            {"days": 360, "label": "Long-Term   (360 days) ", "base_rate": 1.20},
        ]
        skill_bonus = self.skills.banking * 0.02  # +2% per banking level
        print(f"\n  {BOLD}Certificates of Deposit{RESET}  "
              f"{GREY}— funds are locked until maturity, no early withdrawal{RESET}")
        print(f"  Banking skill bonus: {c(f'+{skill_bonus*100:.1f}%', GREEN)} added to all rates")
        print()
        print(f"  {'#':<4}{'Term':<26}{'Return':>8}  {'Example (500g → )':>18}")
        print(f"  {GREY}{'─'*60}{RESET}")
        for i, tier in enumerate(CD_TIERS, 1):
            rate    = tier["base_rate"] + skill_bonus
            example = round(500 * (1 + rate))
            r_col   = GREEN if rate >= 0.35 else CYAN if rate >= 0.16 else WHITE
            print(f"  {CYAN}{i}{RESET}   {tier['label']}  "
                  f"{c(f'{rate*100:.1f}%', r_col):>16}  {GREY}{example}g{RESET}")
        print()
        try:
            ch  = prompt("Choose tier (0 to cancel): ").strip()
            idx = int(ch) - 1
            if idx < 0 or idx >= len(CD_TIERS):
                return
            tier = CD_TIERS[idx]
            rate = round(tier["base_rate"] + skill_bonus, 4)

            avail = self.inventory.gold
            print(f"  Available gold: {c(f'{avail:.0f}g', YELLOW)}  "
                  f"(CDs invest from your wallet, not from savings)")
            raw = prompt(f"Amount to invest (max {avail:.0f}g): ").strip()
            amt = float(raw)
            if amt <= 0:
                return
            if amt > self.inventory.gold:
                err("Not enough gold in wallet.")
                return

            maturity = self._absolute_day() + tier["days"]
            payout   = round(amt * (1 + rate), 2)
            profit   = round(payout - amt, 2)
            print(f"\n  Invest: {c(f'{amt:.0f}g', YELLOW)}  "
                  f"→  receive {c(f'{payout:.0f}g', GREEN)} in {tier['days']} days  "
                  f"(+{c(f'{profit:.0f}g', GREEN)}, {rate*100:.1f}% return)")
            confirm = prompt("Confirm? (yes/no): ")
            if confirm.lower() == "yes":
                self.inventory.gold -= amt
                self.cds.append(CDRecord(principal=amt, rate=rate,
                                         maturity_day=maturity, term_days=tier["days"]))
                ok(f"CD opened!  {amt:.0f}g locked for {tier['days']} days.")
                self._log_event(f"Opened CD: {amt:.0f}g for {tier['days']}d @ {rate*100:.1f}%")
                self._gain_skill_xp(SkillType.BANKING, 8)
        except (ValueError, IndexError):
            err("Invalid input.")

    # ── Contracts ─────────────────────────────────────────────────────────────

    def contracts_menu(self):
        if LicenseType.CONTRACTS not in self.licenses:
            err("You need a Trade Contract Seal to access formal contracts.")
            err("Purchase one from  18. Permits & Licenses  in the main menu.")
            pause()
            return
        while True:
            print(header("MERCHANT CONTRACTS"))
            active = [c for c in self.contracts if not c.fulfilled]
            if active:
                print(f"  {BOLD}Active Contracts:{RESET}")
                for i, con in enumerate(active, 1):
                    item = ALL_ITEMS.get(con.item_key, Item("?","?",0,ItemCategory.RAW_MATERIAL))
                    days_left = con.deadline_day - self._absolute_day()
                    dl_col = RED if days_left < 5 else YELLOW if days_left < 15 else GREEN
                    print(f"  {CYAN}{i}{RESET}. Deliver {con.quantity}x {item.name} to {con.destination.value}")
                    print(f"     Pay: {c(f'{con.price_per_unit:.2f}g/ea', YELLOW)}  Bonus: {c(f'+{con.reward_bonus:.0f}g', GREEN)}  "
                          f"Penalty: {c(f'-{con.penalty:.0f}g', RED)}  Days left: {c(str(days_left), dl_col)}")
            else:
                print(c("  No active contracts.", GREY))

            print(f"\n  {CYAN}1{RESET}. Generate new contracts")
            print(f"  {CYAN}2{RESET}. Fulfill a contract")
            print(f"  {BOLD}[B]{RESET} Back")
            ch = prompt("Choice: ")
            if ch == "1":   self._generate_contracts()
            elif ch == "2": self._fulfill_contract()
            elif ch.upper() in ("3", "B"): break

    def _generate_contracts(self):
        """Generate 3 random contracts with prices anchored to live market prices."""
        available_items = [k for k in ALL_ITEMS if not ALL_ITEMS[k].illegal]
        new_contracts   = []

        for _ in range(3):
            item_key = random.choice(available_items)
            item     = ALL_ITEMS[item_key]
            dest     = random.choice([a for a in Area if a != self.current_area])

            # Anchor to current market sell price at destination (what buyer would pay)
            dest_market = self.markets[dest]
            if item_key in dest_market.item_keys:
                market_ref = dest_market.get_sell_price(item_key, self.season, self.skills.trading)
            else:
                market_ref = item.base_price  # fallback if dest doesn't trade it

            # Contract price = market_ref × modifier
            # Ranges: very cheap deal (-20%) to slightly premium (+12%)
            # Weighted toward slightly below market (0.85–1.05 most common)
            modifier   = random.choices(
                [random.uniform(0.80, 0.92),   # below market — risky/less reward
                 random.uniform(0.92, 1.05),   # near market  — fair deal
                 random.uniform(1.05, 1.15)],  # small premium — good contract
                weights=[30, 50, 20]
            )[0]
            price = round(market_ref * modifier, 2)

            # Quantity scales loosely with how cheap the item is
            qty = random.randint(8, 50) if item.base_price < 40 else random.randint(3, 20)

            days_to_deliver = random.randint(12, 45)
            deadline        = self._absolute_day() + days_to_deliver

            # Bonus only on on-time delivery; penalty for missing deadline
            bonus   = round(qty * item.base_price * random.uniform(0.10, 0.25), 2)
            penalty = round(qty * item.base_price * random.uniform(0.15, 0.35), 2)

            con = Contract(
                id=self.next_contract_id,
                item_key=item_key, quantity=qty, price_per_unit=price,
                destination=dest, deadline_day=deadline,
                reward_bonus=bonus, penalty=penalty
            )
            self.next_contract_id += 1
            new_contracts.append((con, market_ref))

        print(f"\n  {BOLD}New Contracts Available:{RESET}")
        print(f"  {GREY}(Market@ = current sell price at destination for reference){RESET}")
        print(f"  {'#':<4}{'Item':<20}{'Qty':>5}  {'Deliver To':<16}  {'Pay/ea':>8}  {'Market@':>9}  "
              f"{'Vs.Mkt':>7}  {'Bonus':>7}  {'Penalty':>8}  Deadline")
        print(f"  {GREY}{'─' * 102}{RESET}")
        for i, (con, mref) in enumerate(new_contracts, 1):
            item    = ALL_ITEMS[con.item_key]
            vs_mkt  = (con.price_per_unit - mref) / max(mref, 0.01) * 100
            vs_col  = GREEN if vs_mkt >= 3 else (RED if vs_mkt < -10 else YELLOW)
            days_left = con.deadline_day - self._absolute_day()
            print(f"  {CYAN}{i:<4}{RESET}{item.name:<20}{con.quantity:>5}  "
                  f"{c(con.destination.value, CYAN):<24}  "
                  f"{c(f'{con.price_per_unit:.1f}g', YELLOW):>16}  "
                  f"{c(f'{mref:.1f}g', GREY):>17}  "
                  f"{c(f'{vs_mkt:+.0f}%', vs_col):>15}  "
                  f"{c(f'+{con.reward_bonus:.0f}g', GREEN):>15}  "
                  f"{c(f'-{con.penalty:.0f}g', RED):>16}  "
                  f"{days_left}d")

        raw = prompt("Accept which contracts? (e.g. '1,3' or 'none'): ")
        if raw.lower() == "none":
            return
        for part in raw.replace(" ", "").split(","):
            try:
                idx = int(part) - 1
                if 0 <= idx < len(new_contracts):
                    con, _ = new_contracts[idx]
                    self.contracts.append(con)
                    ok(f"Contract accepted: {con.quantity}x {ALL_ITEMS[con.item_key].name} "
                       f"@ {con.price_per_unit:.1f}g/ea")
            except ValueError:
                pass

    def _fulfill_contract(self):
        active = [c for c in self.contracts if not c.fulfilled]
        if not active:
            err("No active contracts.")
            return
        for i, con in enumerate(active, 1):
            item = ALL_ITEMS.get(con.item_key, Item("?","?",0,ItemCategory.RAW_MATERIAL))
            have = self.inventory.items.get(con.item_key, 0)
            print(f"  {CYAN}{i}{RESET}. {con.quantity}x {item.name}  Have: {have}  Dest: {con.destination.value}")
        try:
            idx = int(prompt("Fulfill contract (0 to cancel): ")) - 1
            if idx < 0 or idx >= len(active):
                return
            con = active[idx]
            item = ALL_ITEMS.get(con.item_key, Item("?","?",0,ItemCategory.RAW_MATERIAL))
            if self.current_area != con.destination:
                err(f"You must be in {con.destination.value} to fulfill this!")
                return
            if not self.inventory.has(con.item_key, con.quantity):
                err(f"Need {con.quantity}x {item.name}, only have {self.inventory.items.get(con.item_key,0)}")
                return
            days_left = con.deadline_day - self._absolute_day()
            self.inventory.remove(con.item_key, con.quantity)
            earnings = con.price_per_unit * con.quantity
            if days_left >= 0:
                earnings += con.reward_bonus
                ok(f"Contract fulfilled on time! Earned {c(f'+{earnings:.2f}g', GREEN)}")
                self.reputation = min(100, self.reputation + 3)
                # ── Achievement tracking ──────────────────────────────────
                self._track_stat("contracts_completed")
                self._track_stat("contracts_ontime")
                self.ach_stats["contracts_streak"] = self.ach_stats.get("contracts_streak", 0) + 1
                if con.reward_bonus > self.ach_stats.get("max_contract_bonus", 0):
                    self.ach_stats["max_contract_bonus"] = con.reward_bonus
                if days_left == 0:
                    self._track_stat("contract_close_call", True)
            else:
                earnings -= con.penalty
                warn(f"Contract fulfilled LATE. Penalty applied. Earned {earnings:.2f}g")
                self.reputation = max(0, self.reputation - 5)
                # ── Achievement tracking ──────────────────────────────────
                self._track_stat("contracts_completed")
                self.ach_stats["contracts_streak"] = 0
            self.inventory.gold += max(0, earnings)
            con.fulfilled = True
            self._log_event(f"Fulfilled contract: {con.quantity}x {item.name}")
            self._gain_skill_xp(SkillType.TRADING, 25)
            self._check_achievements()
        except (ValueError, IndexError):
            err("Invalid choice.")

    # ── Skills ───────────────────────────────────────────────────────────────

    def skills_menu(self):
        print(header("SKILLS & UPGRADES"))
        skill_descriptions = {
            SkillType.TRADING:    "Improves buy/sell price margins",
            SkillType.HAGGLING:   "Chance and size of purchase discounts",
            SkillType.LOGISTICS:  "Carry weight capacity (+20/level)",
            SkillType.INDUSTRY:   "Business production multiplier",
            SkillType.ESPIONAGE:  "Reveals competitor prices & future events",
            SkillType.BANKING:    "Better interest rates and loan terms",
        }
        for skill in SkillType:
            attr = skill.value.lower()
            level = getattr(self.skills, attr)
            xp = self.skills.xp.get(skill.value, 0)
            upgrade_cost = self.skills.level_up_cost(skill)
            print(f"  {BOLD}{CYAN}{skill.value:<14}{RESET} Lv{level}  XP: {xp}  "
                  f"Upgrade cost: {c(f'{upgrade_cost}g', YELLOW)}")
            print(f"    {GREY}{skill_descriptions[skill]}{RESET}")

        print(f"\n  Gold available: {c(f'{self.inventory.gold:.2f}g', YELLOW)}")
        print(f"\n  {CYAN}1{RESET}. Upgrade a skill")
        print(f"  {BOLD}[B]{RESET} Back")
        ch = prompt("Choice: ")
        if ch == "1":
            skill_list = list(SkillType)
            for i, s in enumerate(skill_list, 1):
                print(f"  {CYAN}{i}{RESET}. {s.value}")
            try:
                idx = int(prompt("Upgrade (0 to cancel): ")) - 1
                if idx < 0 or idx >= len(skill_list):
                    return
                skill = skill_list[idx]
                success, new_gold = self.skills.try_level_up(skill, self.inventory.gold)
                if success:
                    self.inventory.gold = new_gold
                    ok(f"{skill.value} upgraded to level {getattr(self.skills, skill.value.lower())}!")
                else:
                    err(f"Not enough gold! Need {self.skills.level_up_cost(skill)}g")
            except (ValueError, IndexError):
                err("Invalid choice.")

    def _gain_skill_xp(self, skill: SkillType, amount: int):
        key = skill.value
        self.skills.xp[key] = self.skills.xp.get(key, 0) + amount

    # ── Smuggling ─────────────────────────────────────────────────────────────

    def smuggling_menu(self):
        while True:
            if self.heat >= 80:
                err("You are too HOT — guards are on high alert everywhere. Lie low and travel to cool down.")
                pause()
                return

            guard      = AREA_INFO[self.current_area]["guard_strength"]
            esp        = self.skills.espionage
            catch_base = max(0.04, min(0.65, 0.20 + self.heat / 200 - esp * 0.025))
            contraband = {k: v for k, v in ALL_ITEMS.items() if v.illegal}
            have_ctr   = {k: self.inventory.items.get(k, 0) for k in contraband
                          if self.inventory.items.get(k, 0) > 0}
            fence_mult = self._fence_multiplier()

            print(header("SMUGGLING DEN"))
            heat_col = RED if self.heat > 60 else YELLOW if self.heat > 30 else GREEN
            print(f"  Heat: {c(f'{self.heat}/100', heat_col)}  "
                  f"\u00b7  Espionage: Lv{esp}  "
                  f"\u00b7  Guard strength: {guard}/3  "
                  f"\u00b7  {self.current_area.value}")
            print(f"  Catch chance: {c(f'{catch_base*100:.0f}%', RED if catch_base > 0.35 else YELLOW if catch_base > 0.15 else GREEN)}"
                  f"  {GREY}(base 20% + heat bonus \u2212 espionage bonus){RESET}")
            if have_ctr:
                fence_val = sum(ALL_ITEMS[k].base_price * fence_mult * q for k, q in have_ctr.items())
                pocket_str = ", ".join(f"{q}x {ALL_ITEMS[k].name}" for k, q in have_ctr.items())
                print(f"  {BOLD}Contraband held: {pocket_str}  "
                      f"{c(f'(fence value ~{fence_val:.0f}g)', GREEN)}{RESET}")

            print(f"\n  {CYAN}1{RESET}. Buy from informant   "
                  f"{GREY}1.25\u00d7 base price, +8 heat per deal{RESET}")
            print(f"  {CYAN}2{RESET}. Sell to fence         "
                  f"{GREY}{fence_mult*100:.0f}% of base  ({self._fence_area_label()})  +10 heat{RESET}")
            print(f"  {CYAN}3{RESET}. Bribe guards          "
                  f"{GREY}spend gold to reduce heat  (guard={guard}){RESET}")
            print(f"  {BOLD}[B]{RESET} Back")
            ch = prompt("Choice: ")
            if   ch == "1": self._smug_buy(contraband, catch_base)
            elif ch == "2": self._smug_sell(contraband, have_ctr, catch_base)
            elif ch == "3": self._smug_bribe(guard)
            elif ch.upper() in ("4", "B"): break

    def _fence_multiplier(self) -> float:
        """Fence payout as a multiple of base_price — scales with area guard level."""
        guard = AREA_INFO[self.current_area]["guard_strength"]
        # guard 0 (Swamp/Forest/Desert/Tundra) = best prices; City = lowest but still profitable
        base  = {0: 2.6, 1: 2.2, 2: 1.85, 3: 1.55}[guard]
        base += self.skills.espionage * 0.04   # +4% per espionage level
        return round(base, 3)

    def _fence_area_label(self) -> str:
        guard = AREA_INFO[self.current_area]["guard_strength"]
        return {0: "best — no guards", 1: "good", 2: "fair", 3: "low — high risk"}.get(guard, "")

    def _smug_buy(self, contraband: dict, catch_base: float):
        """Buy contraband from underground informant at 1.25× base."""
        fence_mult = self._fence_multiplier()
        rows = []
        print(f"\n  {BOLD}Informant Stock  —  buy at 1.25\u00d7 base{RESET}")
        print(f"  {'#':<4}{'Item':<24}{'You Pay':>9}  {'Fence ~':>9}  {'Est. Margin/ea':>16}  Owned")
        print(f"  {GREY}{'\u2500' * 70}{RESET}")
        for idx, (k, item) in enumerate(contraband.items(), 1):
            buy_p   = round(item.base_price * 1.25, 2)
            fence_p = round(item.base_price * fence_mult, 2)
            margin  = round(fence_p - buy_p, 2)
            m_col   = GREEN if margin > 0 else RED
            have    = self.inventory.items.get(k, 0)
            rows.append((k, item, buy_p))
            print(f"  {CYAN}{idx}{RESET}   {item.name:<24}{buy_p:>7.0f}g  "
                  f"{fence_p:>7.0f}g  {c(f'{margin:+.0f}g', m_col):>24}  {have}")
        try:
            idx = int(prompt("Item (0=cancel): ")) - 1
            if idx < 0 or idx >= len(rows):
                return
            k, item, buy_p = rows[idx]

            cap      = self._max_carry_weight()
            cur_w    = self._current_weight()
            max_wt   = int((cap - cur_w) / item.weight) if item.weight > 0 else 9999
            max_gold = int(self.inventory.gold / buy_p) if buy_p > 0 else 0
            max_can  = max(0, min(max_wt, max_gold))
            qty = int(prompt(f"Qty of {item.name}  [max {max_can}]  (0=cancel): "))
            if qty <= 0:
                return
            total = round(buy_p * qty, 2)
            if total > self.inventory.gold:
                err(f"Need {total:.0f}g, have {self.inventory.gold:.0f}g")
                return
            if qty > max_wt:
                err(f"Weight limit — max {max_wt} units.")
                return

            if random.random() < catch_base:
                fine = round(total * 0.60, 2)
                self.inventory.gold = max(0, self.inventory.gold - fine)
                self.heat           = min(100, self.heat + 35)
                self.reputation     = max(0, self.reputation - 20)
                warn(f"Sting! Informant was a plant. Fine: {fine:.0f}g  Heat+35  Rep-20")
                self._log_event(f"Smuggling sting when buying — fined {fine:.0f}g")
                self._track_stat("smuggle_busts")
                self._check_achievements()
            else:
                self.inventory.gold -= total
                self.inventory.record_purchase(k, qty, buy_p)
                self.inventory.add(k, qty)
                self.heat = min(100, self.heat + 8)
                ok(f"Acquired {qty}x {item.name} for {total:.0f}g.  Heat +8.")
                self._gain_skill_xp(SkillType.ESPIONAGE, 10)
                self._use_time(1)
        except ValueError:
            err("Invalid input.")

    def _smug_sell(self, contraband: dict, have_ctr: dict, catch_base: float):
        """Sell contraband to the fence at 2.0–2.8× base depending on area."""
        if not have_ctr:
            warn("You have no contraband to sell.")
            return

        fence_mult  = self._fence_multiplier()
        sell_catch  = min(0.70, catch_base + 0.05)  # slightly higher risk when selling
        rows = []
        print(f"\n  {BOLD}Fence Buy Prices  —  {self.current_area.value}  "
              f"({fence_mult*100:.0f}% of base){RESET}")
        print(f"  {'#':<4}{'Item':<24}{'Have':>6}  {'Per unit':>9}  {'Total':>9}")
        print(f"  {GREY}{'\u2500' * 58}{RESET}")
        for idx, (k, qty) in enumerate(have_ctr.items(), 1):
            item    = ALL_ITEMS[k]
            fence_p = round(item.base_price * fence_mult, 2)
            total   = round(fence_p * qty, 2)
            rows.append((k, item, qty, fence_p, total))
            print(f"  {CYAN}{idx}{RESET}   {item.name:<24}{qty:>6}  "
                  f"{c(f'{fence_p:.0f}g', YELLOW):>17}  {c(f'{total:.0f}g', GREEN):>17}")
        print(f"  {GREY}Catch chance on sell: {sell_catch*100:.0f}%  "
              f"(caught = item confiscated + fine + Heat+35 + Rep-25){RESET}")

        raw = prompt("Sell which (number / 'all', 0=cancel): ").strip()
        if raw == "0":
            return
        if raw.lower() == "all":
            sell_list = rows
        else:
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(rows):
                    sell_list = [rows[idx]]
                else:
                    err("Invalid choice.")
                    return
            except ValueError:
                err("Invalid input.")
                return

        any_sold = False
        for k, item, qty, fence_p, total in sell_list:
            if random.random() < sell_catch:
                # Caught: item seized, fine on top
                fine = round(total * 0.50, 2)
                self.inventory.remove(k, qty)
                self.inventory.gold = max(0, self.inventory.gold - fine)
                self.heat           = min(100, self.heat + 35)
                self.reputation     = max(0, self.reputation - 25)
                warn(f"BUSTED! {qty}x {item.name} seized.  Fine: {fine:.0f}g  Heat+35  Rep-25")
                self._log_event(f"Busted at fence — {qty}x {item.name} seized, fined {fine:.0f}g")
                self._track_stat("smuggle_busts")
                self._check_achievements()
            else:
                self.inventory.remove(k, qty)
                self.inventory.gold += total
                self.total_profit   += total
                self.heat            = min(100, self.heat + 10)
                ok(f"Fence bought {qty}x {item.name}  "
                   f"{c(f'+{total:.0f}g', GREEN)}  @ {fence_p:.0f}g/ea.  Heat +10.")
                self._log_trade(f"FENCE {qty}x {item.name} @ {fence_p:.0f}g = {total:.0f}g")
                self._gain_skill_xp(SkillType.ESPIONAGE, 15)
                any_sold = True
                self._track_stat("smuggle_success")
                self._track_stat("smuggle_gold", total)
        if any_sold:
            self._use_time(1)
            self._check_achievements()

    def _smug_bribe(self, guard: int):
        """Pay guards to look the other way — reduces heat."""
        if self.heat <= 0:
            ok("No heat right now, nothing to bribe away.")
            return
        if guard == 0:
            ok(f"No guards in {self.current_area.value} — heat fades naturally as you travel and rest.")
            return

        # Cost scales with heat × guard tier
        bribe_cost  = round(self.heat * (3 + guard * 4))
        reduction   = random.randint(20, 38)
        backfire    = max(0.03, min(0.40, 0.10 + self.heat / 200 - self.skills.espionage * 0.012))

        print(f"\n  Current heat : {c(f'{self.heat}/100', RED)}")
        print(f"  Bribe cost   : {c(f'{bribe_cost}g', YELLOW)}")
        print(f"  Heat reduced : ~{reduction} points  (heat → {max(0, self.heat - reduction)})")
        print(f"  Backfire risk: {backfire*100:.0f}%  {GREY}(guard takes gold and files report anyway){RESET}")

        if self.inventory.gold < bribe_cost:
            err(f"Not enough gold in wallet. Need {bribe_cost}g.")
            return

        confirm = prompt("Attempt bribe? (yes/no): ")
        if confirm.lower() != "yes":
            return

        self.inventory.gold -= bribe_cost
        if random.random() < backfire:
            self.heat       = min(100, self.heat + 15)
            self.reputation = max(0, self.reputation - 10)
            warn(f"Guard pocketed {bribe_cost}g and filed a report anyway.  Heat+15  Rep-10")
            self._log_event(f"Bribe backfired — lost {bribe_cost}g, heat rose to {self.heat}")
        else:
            self.heat = max(0, self.heat - reduction)
            ok(f"Guard convinced.  Heat -{reduction}  ({c(f'{self.heat}/100', YELLOW)} remaining)  "
               f"-{bribe_cost}g")
            self._log_event(f"Bribed guards — heat -{reduction}, paid {bribe_cost}g")
            self._gain_skill_xp(SkillType.ESPIONAGE, 8)
            self._track_stat("bribes")
            self._check_achievements()

    # ── Price History ─────────────────────────────────────────────────────────

    def market_info_menu(self):
        while True:
            print(header(f"MARKET INFO — {self.current_area.value}"))
            market = self.markets[self.current_area]
            print(f"  {BOLD}{'Item':<22} {'Price':>8}  {'Stock':>7}  {'Pressure':>10}  {'Natural':>8}  Trend{RESET}")
            print(f"  {GREY}{'─'*72}{RESET}")
            items_list = sorted(market.item_keys)
            for k in items_list:
                item = ALL_ITEMS[k]
                price    = market.get_price(k, self.season, noise=False)
                stock    = market.stock.get(k, 0)
                pressure = market.pressure.get(k, 1.0)
                natural  = market.natural_pressure.get(k, 1.0)
                hist     = list(market.history.get(k, []))
                if len(hist) >= 2:
                    delta = ((hist[-1].price - hist[-2].price) / max(hist[-2].price, 0.01)) * 100
                    trend = f"{'▲' if delta >= 0 else '▼'}{abs(delta):.1f}%"
                    trend_col = GREEN if delta >= 0 else RED
                else:
                    trend = "  ─"
                    trend_col = GREY
                # Pressure relative to natural: heated = above, cooled = below
                p_ratio = pressure / max(natural, 0.01)
                p_col   = RED if p_ratio > 1.2 else GREEN if p_ratio < 0.85 else WHITE
                p_str   = f"{pressure:.2f}"
                n_str   = f"{natural:.2f}"
                p_str_p = f"{p_str:>8}"
                n_str_p = f"{n_str:>8}"
                s_col   = RED if stock < 15 else YELLOW if stock < 40 else GREEN
                print(f"  {item.name:<22} {price:>8.2f}  {c(f'{stock:>5}', s_col)}    "
                      f"{c(p_str_p, p_col)}  {GREY}{n_str_p}{RESET}  "
                      f"{c(trend, trend_col)}")

            if market.active_events:
                print(f"\n  {BOLD}Active Events in {self.current_area.value}:{RESET}")
                for ev in market.active_events:
                    print(f"    {c('▸ ' + ev, YELLOW)}")
            print(f"\n  {GREY}Pressure > natural = item is expensive (player bought a lot or event)."
                  f"\n  Pressure reverts ~20%/day toward natural — markets self-correct.{RESET}")

            print(f"\n  {CYAN}1{RESET}. Price history for an item")
            print(f"  {CYAN}2{RESET}. Show price comparison")
            print(f"  {BOLD}[B]{RESET} Back")
            ch = prompt("Choice: ")
            if ch == "1":
                self._show_price_history(items_list, market)
            elif ch == "2":
                self._compare_prices()
            elif ch.upper() in ("3", "B"):
                break

    def _show_price_history(self, items_list: List[str], market: AreaMarket):
        for i, k in enumerate(items_list, 1):
            print(f"  {CYAN}{i}{RESET}. {ALL_ITEMS[k].name}")
        try:
            idx = int(prompt("Item: ")) - 1
            k = items_list[idx]
            hist = list(market.history.get(k, []))
            item = ALL_ITEMS[k]
            print(f"\n  {BOLD}Price History: {item.name}{RESET}")
            if not hist:
                print(c("  No history yet.", GREY))
                return
            max_price = max(p.price for p in hist)
            min_price = min(p.price for p in hist)
            print(f"  Min: {c(f'{min_price:.2f}', GREEN)}  Max: {c(f'{max_price:.2f}', RED)}  Latest: {c(f'{hist[-1].price:.2f}', YELLOW)}")
            # ASCII chart
            chart_width = 40
            chart_height = 8
            if len(hist) > 1:
                prices = [p.price for p in hist[-chart_width:]]
                p_range = max(0.01, max_price - min_price)
                print()
                for row in range(chart_height, 0, -1):
                    threshold = min_price + (row / chart_height) * p_range
                    line = ""
                    for p in prices:
                        if p >= threshold:
                            line += c("█", CYAN)
                        else:
                            line += c("░", GREY)
                    label = f"{threshold:>7.1f} │"
                    print(f"  {GREY}{label}{RESET}{line}")
                print(f"  {'':>8}└" + "─" * len(prices))
        except (ValueError, IndexError):
            err("Invalid choice.")
        pause()

    # ── Social / Influence ────────────────────────────────────────────────────

    def social_menu(self):
        """Donate, campaign to inflate prices, or slander to dent a competitor's goods."""
        while True:
            market = self.markets[self.current_area]
            rep_col = RED if self.reputation < 40 else YELLOW if self.reputation < 70 else GREEN
            print(header(f"SOCIAL & INFLUENCE  —  {self.current_area.value}"))
            print(f"  Reputation: {c(f'{self.reputation}/100', rep_col)}  ({self._rep_label()})")
            print(f"  Gold (wallet): {c(f'{self.inventory.gold:.0f}g', YELLOW)}")
            print(f"\n  {CYAN}1{RESET}. Donate to local causes     "
                  f"{GREY}· spend gold, raise rep{RESET}")
            print(f"  {CYAN}2{RESET}. Campaign for an item        "
                  f"{GREY}· spend gold, raise its price here{RESET}")
            print(f"  {CYAN}3{RESET}. Slander an item             "
                  f"{GREY}· free, lower its price here, costs rep{RESET}")
            print(f"  {BOLD}[B]{RESET} Back")
            ch = prompt("Choice: ")

            if ch.upper() in ("4", "B", ""):
                break

            elif ch == "1":
                # ── DONATE ────────────────────────────────────────────────
                print(header("DONATE TO LOCAL CAUSES"))
                rep_col2 = RED if self.reputation < 40 else YELLOW if self.reputation < 70 else GREEN
                print(f"  Current rep: {c(f'{self.reputation}/100', rep_col2)}")
                print(f"  Donating gold to local guilds, temples and orphanages raises your standing.")
                print(f"  {GREY}Rep gain = roughly 1 point per 15g donated.{RESET}")
                print(f"  {GREY}Diminishing returns kick in toward rep 90+.{RESET}")
                print(f"\n  Presets:")
                presets = [
                    (20,  "A modest gesture."),
                    (50,  "A visible contribution."),
                    (120, "A memorable donation."),
                    (300, "A legendary act of generosity."),
                ]
                for i, (amt, note) in enumerate(presets, 1):
                    rep_gain = max(1, int(amt / 15) - max(0, (self.reputation - 80) // 10))
                    print(f"  {CYAN}{i}{RESET}. Donate {c(f'{amt}g', YELLOW)}  "
                          f"→  +{rep_gain} rep  {GREY}({note}){RESET}")
                print(f"  {CYAN}5{RESET}. Custom amount")
                sub = prompt("Choice (0 to cancel): ")
                try:
                    if sub == "0":
                        continue
                    if sub == "5":
                        raw = prompt(f"  Amount to donate (wallet: {self.inventory.gold:.0f}g): ")
                        donate_amt = float(raw)
                    else:
                        donate_amt = presets[int(sub) - 1][0]
                    donate_amt = round(donate_amt, 2)
                    if donate_amt <= 0:
                        err("Nothing donated.")
                        continue
                    if donate_amt > self.inventory.gold:
                        err(f"Not enough gold. Have {self.inventory.gold:.0f}g.")
                        continue
                    rep_gain = max(1, int(donate_amt / 15) - max(0, (self.reputation - 80) // 10))
                    rep_gain = min(rep_gain, 100 - self.reputation)  # can't exceed 100
                    self.inventory.gold -= donate_amt
                    self.reputation = min(100, self.reputation + rep_gain)
                    ok(f"Donated {donate_amt:.0f}g to {self.current_area.value}. "
                       f"Reputation +{rep_gain}  →  {self.reputation}/100")
                    self._log_event(f"Donated {donate_amt:.0f}g in {self.current_area.value}  (+{rep_gain} rep)")
                    headline = random.choice([
                        f"Wealthy merchant makes generous donation in {self.current_area.value}.",
                        f"Coin flows freely — local causes benefit from traveler's purse.",
                        f"Guild hall accepts large donation amid raucous applause.",
                        f"Unnamed donor leaves {self.current_area.value} in noticeably better spirits.",
                    ])
                    self.news_feed.appendleft(
                        (self._absolute_day(), self.current_area.value, "Local Donation", headline))
                    self._use_time(1)
                except (ValueError, IndexError):
                    err("Invalid input.")

            elif ch == "2":
                # ── CAMPAIGN ──────────────────────────────────────────────
                print(header("CAMPAIGN FOR AN ITEM"))
                print(f"  Hire criers and post bills to stoke demand for a specific item.")
                print(f"  {GREY}Effect: raises market demand pressure here (prices go up) for ~15–25 days.{RESET}")
                print(f"  {GREY}Cost: 60–200g depending on item rarity.{RESET}")

                local_keys = sorted(market.item_keys)
                for i, k in enumerate(local_keys, 1):
                    item = ALL_ITEMS[k]
                    cur_p   = market.get_buy_price(k, self.season, self.skills.trading)
                    pres    = market.pressure.get(k, 1.0)
                    rarity_costs = {"common": 60, "uncommon": 100, "rare": 150, "legendary": 200}
                    cost    = rarity_costs.get(item.rarity, 80)
                    est_up  = round(pres * 1.25 * cur_p - cur_p, 1)
                    print(f"  {CYAN}{i:>2}{RESET}. {item.name:<22} "
                          f"Now: {c(f'{cur_p:.1f}g', YELLOW):>14}  "
                          f"Cost: {c(f'{cost}g', YELLOW):>12}  "
                          f"Est. +{c(f'{est_up:.0f}g', GREEN)}")
                print()
                try:
                    idx = int(prompt("Item number (0 to cancel): ")) - 1
                    if idx < 0 or idx >= len(local_keys):
                        continue
                    k    = local_keys[idx]
                    item = ALL_ITEMS[k]
                    rarity_costs = {"common": 60, "uncommon": 100, "rare": 150, "legendary": 200}
                    cost = rarity_costs.get(item.rarity, 80)
                    if self.inventory.gold < cost:
                        err(f"Need {cost}g to run campaign. Have {self.inventory.gold:.0f}g.")
                        continue
                    self.inventory.gold -= cost
                    # Boost pressure by 25% — mean reversion will unwind it in ~15-25 days
                    old_p = market.pressure.get(k, 1.0)
                    new_p = min(market.MAX_PRESSURE, old_p * 1.25)
                    market.pressure[k] = new_p
                    ok(f"Campaign underway for {item.name}! Demand rising in {self.current_area.value}.")
                    self._log_event(f"Campaigned {item.name} in {self.current_area.value}  (-{cost}g)")
                    headline = random.choice([
                        f"Town criers trumpet virtues of {item.name}. Shoppers take notice.",
                        f"Colourful posters appear overnight — {item.name} seemingly everywhere.",
                        f"Demand for {item.name} up noticeably after aggressive postering campaign.",
                        f"Merchants selling {item.name} report a brisker morning than usual.",
                    ])
                    self.news_feed.appendleft(
                        (self._absolute_day(), self.current_area.value, "Market Campaign", headline))
                    self._use_time(1)
                except (ValueError, IndexError):
                    err("Invalid input.")

            elif ch == "3":
                # ── SLANDER ───────────────────────────────────────────────
                print(header("SLANDER AN ITEM"))
                print(f"  Spread whispers, bribe critics, start rumours — undercut demand for a good.")
                print(f"  {GREY}Effect: lowers market demand pressure (prices fall) for ~10–20 days.{RESET}")
                print(f"  {c('Costs: -5 to -10 reputation. Free to execute.', RED)}")

                local_keys = sorted(market.item_keys)
                for i, k in enumerate(local_keys, 1):
                    item = ALL_ITEMS[k]
                    cur_p = market.get_sell_price(k, self.season, self.skills.trading)
                    pres  = market.pressure.get(k, 1.0)
                    est_dn = round(cur_p - pres * 0.80 * cur_p / max(pres, 0.01), 1)
                    print(f"  {CYAN}{i:>2}{RESET}. {item.name:<22} "
                          f"Now: {c(f'{cur_p:.1f}g', YELLOW):>14}  "
                          f"Rep cost: {c('-5 to -10', RED):>18}  "
                          f"Est. {c(f'-{abs(est_dn):.0f}g', RED)}")
                print()
                try:
                    idx = int(prompt("Item number (0 to cancel): ")) - 1
                    if idx < 0 or idx >= len(local_keys):
                        continue
                    k    = local_keys[idx]
                    item = ALL_ITEMS[k]
                    rep_cost = random.randint(5, 10)
                    if self.reputation - rep_cost < 0:
                        err("Your reputation is too low to risk further scandal.")
                        continue
                    # Reduce pressure by 20%
                    old_p = market.pressure.get(k, 1.0)
                    new_p = max(market.MIN_PRESSURE, old_p * 0.80)
                    market.pressure[k] = new_p
                    self.reputation = max(0, self.reputation - rep_cost)
                    warn(f"Slander spread about {item.name} in {self.current_area.value}. "
                         f"Rep -{rep_cost}  →  {self.reputation}/100")
                    self._log_event(
                        f"Slandered {item.name} in {self.current_area.value}  (-{rep_cost} rep)")
                    headline = random.choice([
                        f"Unsavoury claims about {item.name} circulate in the market quarter.",
                        f"Shoppers avoiding {item.name} after rumours of dubious quality spread.",
                        f"Something unpleasant is being said about {item.name}. Nobody's buying.",
                        f"A mysterious pamphlet warns buyers off {item.name}. Demand has cooled.",
                        f"Street gossip turns against {item.name}. Sellers are not amused.",
                    ])
                    self.news_feed.appendleft(
                        (self._absolute_day(), self.current_area.value, "Slander", headline))
                    self._use_time(1)
                except (ValueError, IndexError):
                    err("Invalid input.")
            else:
                err("Invalid choice.")

    # ── Event Log & Stats ─────────────────────────────────────────────────────

    def news_menu(self):
        """World News — recent events with narrative headlines and active event summary."""
        print(header("WORLD NEWS"))

        # Show active market events across all areas
        all_active: List[Tuple[str, str]] = []
        for area, market in self.markets.items():
            for ev in market.active_events:
                all_active.append((area.value, ev))

        if all_active:
            print(f"\n  {BOLD}⚑  Currently Active Events:{RESET}")
            seen = set()
            for area_name, ev_label in all_active:
                key = (area_name, ev_label)
                if key not in seen:
                    seen.add(key)
                    # Map label back to effect hints
                    _hints = {
                        "Drought":       c("Grain/fibre scarce — prices elevated.", YELLOW),
                        "Flood":         c("Farm & coastal goods disrupted.", YELLOW),
                        "Bumper Harvest":c("Crop prices lower than usual.",         GREEN),
                        "Mine Collapse": c("Ore, coal & gems in short supply.",     YELLOW),
                        "Piracy Surge":  c("Coastal goods hard to come by.",        YELLOW),
                        "Trade Boom":    c("All goods in higher demand.",            GREEN),
                        "Plague":        c("Medicine & herbs extremely scarce.",    RED),
                        "Border War":    c("Steel & ore demand surging.",           YELLOW),
                        "Gold Rush":     c("Gold dust prices softening.",           CYAN),
                        "Grand Festival":c("Luxury goods in peak demand.",          GREEN),
                    }
                    hint = _hints.get(ev_label, c("Market effects in play.", GREY))
                    print(f"  {c('●', RED)} {c(ev_label, BOLD)} in {c(area_name, CYAN)}  —  {hint}")
        else:
            print(f"\n  {GREY}No major events currently active.{RESET}")

        # Show news feed
        print(f"\n  {BOLD}Recent Headlines:{RESET}")
        if not self.news_feed:
            print(f"  {GREY}No dispatches yet — check back after a few days of travel.{RESET}")
        else:
            print(f"  {GREY}{'─' * 64}{RESET}")
            for entry in self.news_feed:
                abs_day, area_name, ev_label, headline = entry
                yr  = (abs_day - 1) // 360 + 1
                day = (abs_day - 1) % 360 + 1
                date_str = f"Y{yr}·D{day:<3}"
                tag_col  = YELLOW if ev_label != "Local Rumour" else GREY
                print(f"  {GREY}{date_str}{RESET}  {c(f'[{ev_label}]', tag_col):<28}  {headline}")
        print(f"  {GREY}{'─' * 64}{RESET}")
        pause()

    def event_log_menu(self):
        print(header("EVENT LOG"))

        # Active world events summary
        all_active: List[Tuple[str, str]] = []
        for area, market in self.markets.items():
            for ev in market.active_events:
                all_active.append((area.value, ev))
        if all_active:
            print(f"\n  {BOLD}Active Market Conditions:{RESET}")
            seen = set()
            for area_name, ev_label in all_active:
                key = (area_name, ev_label)
                if key not in seen:
                    seen.add(key)
                    print(f"  {c('►', YELLOW)} {c(ev_label, BOLD)} — {area_name}")
        else:
            print(f"\n  {GREY}No active events right now.{RESET}")

        print(f"\n  {BOLD}World Event History:{RESET}")
        if not self.event_log:
            print(c("  No events recorded.", GREY))
        for entry in self.event_log:
            print(f"  {GREY}{entry}{RESET}")

        print(f"\n  {BOLD}Recent Trades:{RESET}")
        trades = list(self.trade_log)[:15]
        if not trades:
            print(f"  {GREY}No trades recorded yet.{RESET}")
        for entry in trades:
            print(f"  {GREY}{entry}{RESET}")
        pause()

    def statistics_menu(self):
        print(header("STATISTICS & CHARTS"))
        nw            = self._net_worth()
        total_workers = sum(b.workers for b in self.businesses)
        total_debt    = sum(l.principal for l in self.loans)
        col_w = 32

        print(f"\n  {BOLD}FINANCIALS{RESET}")
        print(f"  {'Net Worth':.<{col_w}} {c(f'{nw:,.2f}g', CYAN)}")
        print(f"  {'Cash on Hand':.<{col_w}} {c(f'{self.inventory.gold:,.2f}g', YELLOW)}")
        print(f"  {'Bank Balance':.<{col_w}} {c(f'{self.bank_balance:,.2f}g', YELLOW)}")
        monthly_rate = 0.015 + self.skills.banking * 0.002
        if self.bank_balance > 0:
            proj_interest = round(self.bank_balance * monthly_rate, 2)
            print(f"  {'  → Interest next 30d':.<{col_w}} {c(f'+{proj_interest:.2f}g', GREEN)}  "
                  f"{GREY}({monthly_rate*100:.1f}%/mo){RESET}")
        print(f"  {'Lifetime Sales Revenue':.<{col_w}} {c(f'{self.total_profit:,.2f}g', GREEN)}")
        debt_col = RED if total_debt > 0 else GREY
        print(f"  {'Outstanding Debt':.<{col_w}} {c(f'{total_debt:,.2f}g', debt_col)}")
        if self.loans:
            total_monthly = sum(l.monthly_payment for l in self.loans)
            months_max    = max(l.months_remaining for l in self.loans)
            print(f"  {'  → Monthly payments':.<{col_w}} {c(f'{total_monthly:.2f}g/mo', RED)}  "
                  f"{GREY}(longest: {months_max} months remaining){RESET}")

        # CDs summary
        if self.cds:
            locked  = sum(cd.principal for cd in self.cds)
            payouts = sum(round(cd.principal * (1 + cd.rate), 2) for cd in self.cds)
            profits = round(payouts - locked, 2)
            today   = self._absolute_day()
            soonest = min(cd.maturity_day - today for cd in self.cds)
            print(f"  {'Locked in CDs':.<{col_w}} {c(f'{locked:.0f}g', CYAN)}  "
                  f"{GREY}→ {payouts:.0f}g at maturity  (+{profits:.0f}g){RESET}")
            print(f"  {'  → Soonest maturity':.<{col_w}} {c(f'in {soonest}d', YELLOW if soonest <= 10 else GREEN)}")

        print(f"\n  {BOLD}DAILY CASHFLOW ESTIMATE{RESET}")
        liv = self._living_cost()
        print(f"  {'Living Costs':.<{col_w}} {c(f'-{liv:.0f}g/day', RED)}")
        _dummy = Item("?", "?", 0, ItemCategory.RAW_MATERIAL)
        if self.businesses:
            gross_inc  = sum(b.daily_production() * ALL_ITEMS.get(b.item_produced, _dummy).base_price
                             for b in self.businesses)
            total_opex = sum(b.daily_cost + b.worker_daily_wage() for b in self.businesses)
            net_biz    = gross_inc - total_opex - liv
            print(f"  {'Gross Business Income':.<{col_w}} {c(f'+{gross_inc:.0f}g/day', GREEN)}")
            print(f"  {'Business Operating Costs':.<{col_w}} {c(f'-{total_opex:.0f}g/day', RED)}")
            net_col = GREEN if net_biz >= 0 else RED
            print(f"  {'Est. Net Daily P/L':.<{col_w}} {c(f'{net_biz:+.0f}g/day', net_col)}")
        else:
            print(f"  {GREY}No businesses — trading profit only.{RESET}")

        print(f"\n  {BOLD}PLAYER STATUS{RESET}")
        print(f"  {'Reputation':.<{col_w}} {self._rep_label()}  ({self.reputation}/100)")
        heat_col = RED if self.heat > 50 else YELLOW if self.heat > 0 else GREY
        print(f"  {'Heat Level':.<{col_w}} {c(f'{self.heat}/100', heat_col)}")
        print(f"  {'Lifetime Trades':.<{col_w}} {self.lifetime_trades}")
        print(f"  {'Current Date':.<{col_w}} Year {self.year}, Day {self.day}  ({self.season.value})")

        print(f"\n  {BOLD}BUSINESSES  ({len(self.businesses)} owned){RESET}")
        if self.businesses:
            print(f"  {GREY}{'Name':<22}{'Lv':>4}{'Workers':>9}{'Avg Prod':>10}{'Output/d':>10}{'Net/d':>10}{RESET}")
            print(f"  {GREY}{'─'*66}{RESET}")
            for b in self.businesses:
                item     = ALL_ITEMS.get(b.item_produced, _dummy)
                prod     = b.daily_production()
                gross    = prod * item.base_price
                net_b    = gross - b.daily_cost - b.worker_daily_wage()
                net_col  = GREEN if net_b >= 0 else RED
                avg_p    = (sum(w["productivity"] for w in b.hired_workers) / max(b.workers, 1)
                            if b.hired_workers else 0.0)
                eff_str  = f"{avg_p:.2f}x" if b.workers else c("idle", GREY)
                status   = c("BROKEN", RED) if b.broken_down else ""
                print(f"  {b.name:<22}{b.level:>4}{b.workers:>9}{c(f'{eff_str}', CYAN):>20}"
                      f"{c(f'{prod}u', GREEN):>18}{c(f'{net_b:+.0f}g', net_col):>18}  {status}")
        else:
            print(f"  {GREY}No businesses owned yet.{RESET}")

        print(f"\n  {BOLD}SKILLS{RESET}")
        skill_desc = {
            "Trading":   f"Buy/sell prices ~{self.skills.trading * 2}% better",
            "Haggling":  f"{self.skills.haggling * 8}% haggle success chance",
            "Logistics": f"{100 + self.skills.logistics * 20}kg carry weight",
            "Industry":  f"+{(self.skills.industry-1)*8}% production bonus/business",
            "Espionage": f"Unlocks {min(self.skills.espionage, 3)} levels of market info",
            "Banking":   f"{(0.015 + self.skills.banking * 0.002)*100:.1f}%/mo savings, +{self.skills.banking*2}% CD rates",
        }
        for s in SkillType:
            level  = getattr(self.skills, s.value.lower())
            xp     = self.skills.xp.get(s.value, 0)
            bar    = c("\u2588" * level, YELLOW) + c("\u2591" * max(0, 10 - level), GREY)
            xp_to  = self.skills.level_up_cost(s)
            desc   = skill_desc.get(s.value, "")
            print(f"  {s.value:<14} [{bar}] Lv{level:<3}  XP: {xp:<6} \u2192 {xp_to}g  {GREY}{desc}{RESET}")

        # Business income bar chart
        print(self._business_bar_chart())

        # Net worth line graph
        if len(self.net_worth_history) >= 2:
            peak  = max(self.net_worth_history)
            title = f"Net Worth Over Time  (peak: {peak:,.0f}g)"
            print(self._ascii_line_graph(self.net_worth_history, title=title))
        else:
            print(f"\n  {GREY}Net worth graph available after a few days of play.{RESET}")

        pause()

    # ── ASCII Charts ──────────────────────────────────────────────────────────

    def _ascii_line_graph(self, values: List[float], title: str,
                          width: int = 48, height: int = 8) -> str:
        """Render a filled area chart. Returns a printable multi-line string."""
        if len(values) < 2:
            return c("  (not enough data \u2014 keep playing!)", GREY)
        if len(values) > width:
            step = (len(values) - 1) / max(width - 1, 1)
            data = [values[int(round(i * step))] for i in range(width)]
        else:
            data = list(values)
            width = len(data)
        min_v   = min(data)
        max_v   = max(data)
        v_range = max(1.0, max_v - min_v)

        def scaled(v: float) -> int:
            return int((v - min_v) / v_range * (height - 1))

        lines: List[str] = [c(f"  {title}", BOLD)]
        for row in range(height - 1, -1, -1):
            threshold_v = min_v + (row / max(height - 1, 1)) * v_range
            raw_label   = f"{threshold_v:>10,.0f} \u2524"
            bar = ""
            for _, v in enumerate(data):
                h = scaled(v)
                if h == row:
                    bar += c("\u25b2", GREEN)
                elif h > row:
                    bar += c("\u2588", BLUE)
                else:
                    bar += c("\u00b7", GREY)
            lines.append(f"  {GREY}{raw_label}{RESET}{bar}")
        lines.append(f"  {'':>12}\u2514" + c("\u2500" * width, GREY))
        abs_day   = self._absolute_day()
        n         = len(values)
        start_lbl = f"Day {max(1, abs_day - n * 10)}"
        end_lbl   = f"Day {abs_day}"
        pad       = max(0, width - len(start_lbl) - len(end_lbl) - 2)
        lines.append(f"  {'':>13}{c(start_lbl, GREY)}{' ' * pad}{c(end_lbl, GREY)}")
        return "\n".join(lines)

    def _business_bar_chart(self) -> str:
        """Horizontal bar chart of business daily net income."""
        if not self.businesses:
            return c("  No businesses owned yet.", GREY)
        BAR_W  = 28
        _dummy = Item("?", "?", 0, ItemCategory.RAW_MATERIAL)
        entries = []
        for b in self.businesses:
            item  = ALL_ITEMS.get(b.item_produced, _dummy)
            gross = b.daily_production() * item.base_price
            net   = gross - b.daily_cost - b.worker_daily_wage()
            entries.append((b, net))
        max_abs = max((abs(e[1]) for e in entries), default=1) or 1
        lines = [f"\n  {c('Business Daily Net Income (est.):', BOLD)}"]
        for b, net in entries:
            bar_len = int(abs(net) / max_abs * BAR_W)
            col     = GREEN if net >= 0 else RED
            bar     = c("\u2588" * bar_len, col) + c("\u2591" * (BAR_W - bar_len), GREY)
            status  = c(" [BROKEN]", RED) if b.broken_down else ""
            net_s   = f"{net:+.0f}g/day"
            lines.append(f"  {b.name:<22} \u2502{bar}\u2502 {c(net_s, col)}{status}")
        return "\n".join(lines)

    # ── Arbitrage Advisor ────────────────────────────────────────────────────

    def arbitrage_menu(self):
        print(header(f"TRADE ROUTES FROM {self.current_area.value.upper()}"))
        print(c("  Items available here and sellable for profit elsewhere.", GREY))
        print(c("  Sorted by gold-per-travel-day (efficiency). Prices are estimates.", GREY))
        local = self.markets[self.current_area]
        opps: List = []
        _dummy = Item("?", "?", 0, ItemCategory.RAW_MATERIAL)
        for item_key in local.item_keys:
            item = ALL_ITEMS[item_key]
            if item.illegal:
                continue
            buy_p = local.get_buy_price(item_key, self.season, self.skills.trading)
            for dest, dest_mkt in self.markets.items():
                if dest == self.current_area:
                    continue
                if item_key in dest_mkt.item_keys:
                    sell_p = dest_mkt.get_sell_price(item_key, self.season, self.skills.trading)
                    pct    = (sell_p - buy_p) / max(buy_p, 0.01) * 100
                    if pct <= 5:
                        continue
                    tdays = AREA_INFO[self.current_area]["travel_days"].get(dest, 3)
                    gpd   = (sell_p - buy_p) / max(1, tdays)
                    stock = local.stock.get(item_key, 0)
                    opps.append((item, buy_p, sell_p, pct, dest, tdays, gpd, stock))
        opps.sort(key=lambda x: x[6], reverse=True)

        if not opps:
            warn("No profitable routes found from here right now.")
            print(c("  Try: travel elsewhere, wait for price changes, or use the price comparison.", GREY))
            pause()
            return

        print(f"\n  {'Item':<22} {'Buy':>7}  {'Sell':>7}  {'Destination':<20} {'Profit':>8}  {'Days':>5}  {'g/day':>6}  {'Stock':>6}")
        print(c(f"  {'-'*92}", GREY))
        for item, buy_p, sell_p, pct, dest, tdays, gpd, stock in opps[:15]:
            pct_col   = GREEN if pct > 30 else YELLOW if pct > 15 else WHITE
            stock_col = RED if stock < 10 else YELLOW if stock < 30 else GREEN
            bp = f"{buy_p:>6.0f}g"
            sp = f"{sell_p:>6.0f}g"
            pp = f"+{pct:>5.0f}%"
            gd = f"{gpd:>5.0f}"
            st = f"{stock:>5}"
            print(f"  {item.name:<22} {c(bp, RED)}  {c(sp, GREEN)}  "
                  f"{dest.value:<20} {c(pp, pct_col)}  "
                  f"{tdays:>5}d  {c(gd, CYAN)}g/d  {c(st, stock_col)}")
        print(f"\n  {GREY}Stock in red (<10) may run out mid-purchase. Plan qty accordingly.{RESET}")
        print(f"  {GREY}g/day ranks efficiency \u2014 higher means more profit per unit of time.{RESET}")
        pause()

    # ── Help & Guide ─────────────────────────────────────────────────────────

    def help_menu(self):
        while True:
            print(header("HELP & GUIDE"))
            print(f"  {CYAN}1{RESET}. Trading Basics         {CYAN}6{RESET}. Smuggling & Heat")
            print(f"  {CYAN}2{RESET}. Prices & Seasons       {CYAN}7{RESET}. World Events & News")
            print(f"  {CYAN}3{RESET}. Business Management    {CYAN}8{RESET}. Areas & Travel")
            print(f"  {CYAN}4{RESET}. Skills Guide           {CYAN}9{RESET}. Tips & Strategies")
            print(f"  {CYAN}5{RESET}. Contracts & Reputation {CYAN}10{RESET}. Social & Influence")
            print(f"  {CYAN}11{RESET}. Schedule & Time")
            print(f"\n  {BOLD}[B]{RESET} Back  {GREY}(or Enter){RESET}")
            ch = prompt("Topic: ").strip().upper()
            if ch in ("0", "B", ""):
                break
            elif ch == "1":
                self._help_section("TRADING BASICS", [
                    ("How prices work",
                     "base_price x (demand / supply) x seasonal modifier x scarcity bonus.\n"
                     "Low stock (<30) adds up to +50% scarcity premium. Markets rebalance daily."),
                    ("Buy/Sell spread",
                     "You pay slightly above mid-price when buying; receive slightly below mid\n"
                     "when selling. Trading skill narrows this gap (minimum ~3% each side)."),
                    ("Haggling",
                     "Use Haggle in the Trade menu to roll for a discount on a purchase.\n"
                     "Haggling Lv1: ~18% chance of 5-17% off.  Lv5: ~50% chance of 5-25% off."),
                    ("Selling elsewhere",
                     "Any item can be sold anywhere. Items not listed locally sell at 65% of\n"
                     "base price (pawnbroker rate). Capital City always pays fair prices."),
                    ("Multi-buy / sell",
                     "Type multiple item numbers (e.g. '1,3,5') to buy/sell several at once.\n"
                     "Type 'all' to process everything listed. Type 'max' for auto-max quantity."),
                ])
            elif ch == "2":
                self._help_section("PRICES & SEASONS", [
                    ("The 4 seasons",
                     "Spring (Day 1-30), Summer (31-60), Autumn (61-90), Winter (91-120),\n"
                     "then repeats. Seasonal effects are global and affect all areas equally."),
                    ("Winter hotlist",
                     "Fur (x2.0), Coal (x2.2), Peat (x1.8), Medicine (x1.8), Spice (x1.5),\n"
                     "Wheat (x1.4), Bread (x1.4). Stock up in Autumn before prices spike."),
                    ("Summer hotlist",
                     "Fish (x1.4), Exotic Fruit (x1.5), Honey (x1.4), Ale (x1.3).\n"
                     "Buy these cheap in Winter/Spring and sell at peak through Summer."),
                    ("Autumn hotlist",
                     "Barley (x1.4), Ale (x1.5), Wine (x1.4), Smoked Meat (x1.3).\n"
                     "Breweries and Vineyards are most profitable in Autumn."),
                    ("Supply & demand",
                     "Buying reduces supply (item price rises). Selling increases supply (falls).\n"
                     "Large bulk purchases can visibly move prices for that item."),
                ])
            elif ch == "3":
                self._help_section("BUSINESS MANAGEMENT", [
                    ("Buying a business",
                     "One-time purchase fee + daily operating cost. Goods produced each day\n"
                     "automatically go into your inventory while you play."),
                    ("Workers",
                     "Each worker adds +15% daily production and costs wages per day.\n"
                     "Worker productivity (0.70–1.40×) directly multiplies output.\n"
                     "Max 5 workers/business. Hire skilled workers when item prices justify it."),
                    ("Upkeep & breakdowns",
                     "If you can't pay daily costs, workers quit first (reducing wages).\n"
                     "If still unaffordable, the business shuts down needing paid repair.\n"
                     "Maintain a gold reserve of at least 5x your total daily operating cost."),
                    ("Upgrades",
                     "Each level multiplies production (diminishing returns: +60% per level).\n"
                     "Lv1=1.0×, Lv2=1.6×, Lv3=2.2×. Upgrade costs scale with level.\n"
                     "A Lv3 Gem Mine with 3 skilled workers produces very strong passive income."),
                    ("Industry skill",
                     "Industry Lv2+: +8% bonus production per skill level above 1, every day.\n"
                     "Industry Lv3+: ~25% chance of additional windfall production.\n"
                     "Always prioritize Industry once you own 2+ businesses."),
                ])
            elif ch == "4":
                self._help_section("SKILLS GUIDE", [
                    ("Trading",
                     "Reduces buy markup, increases sell return. Lv1: ~7% spread each side.\n"
                     "At Lv6: ~3% spread. Gain XP from every buy/sell and fulfilled contract."),
                    ("Haggling",
                     "Increases success chance and discount size with the Haggle option.\n"
                     "Lv1: 18% chance.  Lv5: 50% chance, up to 25% discount."),
                    ("Logistics",
                     "+20 carry weight per level. Base: 100 weight. Heavy items (Coal 2.5,\n"
                     "Timber 3.0) need Logistics Lv3+ to carry in meaningful bulk."),
                    ("Industry",
                     "Lv2+: +8% bonus production per level above 1 on every business, daily.\n"
                     "Lv3+: ~25%/day windfall bonus. Best skill for 3+ business owners."),
                    ("Espionage",
                     "Each level reduces contraband detection chance by -5%.\n"
                     "Lv4+ makes smuggling runs fairly safe with low heat."),
                    ("Banking",
                     "Lv1 base: 1.5%/mo savings. +0.2%/mo per level. Better CD rates (+2%/lv).\n"
                     "Lv4+ makes the bank a meaningful passive income source."),
                    ("Skill cost scaling",
                     "Costs are quadratic: Lv1->2 costs 150g, Lv2->3: 600g, Lv3->4: 1350g,\n"
                     "Lv4->5: 2400g, Lv5->6: 3750g. Plan your investment path carefully."),
                ])
            elif ch == "5":
                self._help_section("CONTRACTS & REPUTATION", [
                    ("Taking contracts",
                     "Generate up to 3 random delivery contracts. Each specifies: item,\n"
                     "quantity, destination, deadline, pay/unit, early bonus, late penalty."),
                    ("Fulfilling",
                     "Travel to the destination with the goods before the deadline.\n"
                     "On-time: full pay + bonus.  Late: forfeits bonus AND deducts penalty."),
                    ("Reputation (0-100)",
                     "Starts at 50. Fulfilling on time: +3. Late/missed: -5.\n"
                     "Fines for illegal goods: -10 to -15. Loan payoff: +5."),
                    ("Rep effects",
                     "Rep >75 (Trusted/Legendary): better contract pay, lower loan rates.\n"
                     "Rep <30 (Suspect/Outlaw): guards more aggressive, loans cost more."),
                    ("Strategy",
                     "Only accept contracts for items near production areas on your route.\n"
                     "Stack multiple contracts toward the same destination for efficiency."),
                ])
            elif ch == "6":
                self._help_section("SMUGGLING & HEAT", [
                    ("Contraband overview",
                     "4 illegal items: Stolen Goods (base 40g), Gunpowder (75g),\n"
                     "Black Powder (95g), Alchemical Toxin (180g).\n"
                     "Buy from informant at 1.25x base; sell to fence at 1.55\u20132.6x base."),
                    ("Fence pricing by area",
                     "Swamp/Forest/Desert/Tundra (guard 0): 2.6x base (+4%/Esp.lv)\n"
                     "Farmland/Mountain (guard 1): 2.2x base\n"
                     "Coast (guard 2): 1.85x base\n"
                     "Capital City (guard 3): 1.55x base  (risky but accessible)"),
                    ("Catch chance formula",
                     "Buy & sell: max(4%, 20% + heat/200 \u2212 Espionage\u00d72.5%).\n"
                     "Sell adds +5%.  Espionage Lv5 = \u221212.5% off catch chance.\n"
                     "Caught: item seized + 50\u201360% fine + Heat+35 + Rep-20/25."),
                    ("Bribing guards",
                     "Cost = heat \u00d7 (3 + guard\u00d74).  Reduces heat by 20\u201338 points.\n"
                     "Backfire risk: 10% + heat/200 \u2212 Espionage\u00d71.2%.\n"
                     "Only works where guards exist (guard \u2265 1)."),
                    ("Heat & cooling",
                     "Buy success: +8 heat.  Sell success: +10.  Getting caught: +35.\n"
                     "Heat drops \u22122/day naturally, \u22123\u00d7travel_days when moving.\n"
                     "Den inaccessible at heat \u226580.  Bribe guards to speed cooldown."),
                    ("Strategy",
                     "Best route: buy Toxin at Swamp (cheap), sell fence at Swamp (2.6x).\n"
                     "Riskier: buy anywhere, haul to Forest/Desert fence for 2.2\u20132.6x.\n"
                     "Keep Espionage \u22653 to cut catch chance below 10% at low heat."),
                ])
            elif ch == "7":
                self._help_section("WORLD EVENTS & NEWS", [
                    ("Frequency & decay",
                     "Events fire at ~4% per day. Effects last up to 30 in-game days,\n"
                     "then auto-decay as markets normalize."),
                    ("Key events",
                     "Drought:        Food/grain prices spike. Buy before, sell during.\n"
                     "Mine Collapse:  Ore/Gem/Coal supply collapses. Profit if you hold.\n"
                     "Plague:         Medicine x2, Herbs x2 demand. Hoard before it hits.\n"
                     "Border War:     Steel, Ore, Medicine spike. Transit risks increase.\n"
                     "Festival:       Ale, Wine, Silk, Jewelry all spike. Sell luxury goods.\n"
                     "Gold Rush:      Gold Dust floods market - buy cheap, sell elsewhere.\n"
                     "Bumper Harvest: Wheat/Barley/Cotton flood market, prices crash."),
                    ("Monitoring events",
                     "Press [N] News & Events for headlines, active conditions, and trade log.\n"
                     "Press [M] Market Info to see active events for a specific area.\n"
                     "The status bar at the top always shows current active events."),
                    ("News headlines",
                     "Headlines appear in World News as events unfold.\n"
                     "Event headlines hint at which goods are affected and in which region.\n"
                     "Neutral rumours appear daily — mostly flavour, occasionally prophetic."),
                ])
            elif ch == "8":
                self._help_section("AREAS & TRAVEL", [
                    ("Area specializations",
                     "Farmlands : Wheat, Barley, Cotton, Wine, Bread, Ale\n"
                     "Mountain  : Ore, Coal, Gold Dust, Gems, Fur, Steel\n"
                     "Coast     : Fish, Salt, Rope, Silk, Blubber, Spice\n"
                     "Forest    : Timber, Herbs, Fur, Honey, Leather, Paper\n"
                     "Desert    : Spice, Ivory, Gold Dust, Silk, Exotic Fruit, Relics\n"
                     "Swamp     : Herbs, Peat, Perfume, Relics, Contraband\n"
                     "Tundra    : Fur, Blubber, Smoked Meat, Coal, Ore\n"
                     "Capital   : Everything, but all at high prices"),
                    ("Travel risk",
                     "Each route has a 4-18% incident chance: bandit gold/item theft,\n"
                     "border inspection (seizes contraband), lucky find, or weather damage."),
                    ("Overloading",
                     "Exceeding carry weight adds 1 extra travel day per 15 excess weight.\n"
                     "Keep weight under limit for fastest routes and fewest incidents."),
                    ("Guard strength",
                     "City: 3  |  Coast: 2  |  Farmland/Mountain: 1  |  Others: 0.\n"
                     "High guard = higher risk selling contraband or traveling with illegal goods."),
                ])
            elif ch == "9":
                self._help_section("TIPS & STRATEGIES", [
                    ("Early game (Days 1-60)",
                     "Buy Wheat in Farmlands (~10g), sell in Capital City (~15-18g).\n"
                     "Buy Ore in Mountains (~25g), sell in City (~35-40g).\n"
                     "Use Arbitrage Advisor (Trade menu) for current best routes."),
                    ("First business",
                     "Save ~2,000g then buy a Coal Mine (1,200g) or Fishery (900g).\n"
                     "Always maintain 5 days of operating costs as a gold reserve."),
                    ("Seasonal play",
                     "Buy Fur in Summer (demand 0.5x = cheapest), sell in Winter (demand 2.0x).\n"
                     "Buy Coal in Spring/Summer, sell in Winter for 2.2x demand premium."),
                    ("Passive income",
                     "Gem Mine Lv2 + 2 workers: ~6 gems/day at 150g base = ~900g gross/day.\n"
                     "Net after costs: ~700g/day. ROI in under a week."),
                    ("Contract stacking",
                     "Accept contracts whose destination matches your planned trade route.\n"
                     "Stack 2-3 contracts toward the same city for maximum trip value."),
                    ("Banking & loans",
                     "Keep 50%+ of idle gold in the bank earning interest.\n"
                     "Use loans for business purchases - repay early once ROI kicks in."),
                    ("Heat management",
                     "Do smuggling runs near the Swamp. Sell contraband there (0 guards).\n"
                     "Long journeys (Desert, Tundra) cool heat effectively."),
                ])
            elif ch == "10":
                self._help_section("SOCIAL & INFLUENCE", [
                    ("Donate to local causes",
                     "Spend wallet gold to raise reputation in the current area.\n"
                     "Roughly +1 rep per 15g donated. Presets or custom amounts.\n"
                     "Diminishing returns above rep 80. Safe, legal, effective."),
                    ("Campaign for an item",
                     "Hire town criers and post bills to inflate demand for one item locally.\n"
                     "Raises market pressure by ~25%, lifting buy and sell prices.\n"
                     "Cost: 60g (common) to 200g (legendary). Fades in 15–25 days via natural reversion."),
                    ("Slander an item",
                     "Whisper rumours to cool demand for a specific item here.\n"
                     "Reduces market pressure by ~20%, lowering prices for buyers and sellers alike.\n"
                     "No gold cost, but costs -5 to -10 reputation. Use with care."),
                    ("Strategic uses",
                     "Buy at slandered (low) prices, then travel away and sell at full price.\n"
                     "Campaign an item you already hold stock of — sell into the spike.\n"
                     "Donate before taking loans or filing contracts to get better rates.\n"
                     "Don't slander in areas with high guard — rep losses stack with fines."),
                    ("Banking — updated rates",
                     "Savings: 1.5%/mo base (+0.2%/mo per Banking level, paid every 30 days).\n"
                     "CDs: 8%/30d, 26%/90d, 55%/180d, 120%/360d — locked, no early withdrawal.\n"
                     "Skill bonus: +2% return per Banking level on all CD tiers."),
                ])
            elif ch == "11":
                self._help_section("SCHEDULE & TIME", [
                    ("Activity slots (the Schedule bar)",
                     "Each in-game day has 6 activity slots, shown as ●/○ dots in the status bar.\n"
                     "Every substantial action (visiting Businesses, Finance, Contracts,\n"
                     "Skills, Smuggling, or Reputation menus) costs 1 slot.\n"
                     "Trading and Traveling manage their own time internally."),
                    ("When slots run out",
                     "Once all 6 slots are used, the day ends automatically:\n"
                     "  '◑ Night falls — your day is done.'\n"
                     "The game then advances to the next morning before you return to the\n"
                     "main menu. Businesses produce, markets restock, and heat cools."),
                    ("How a day advances",
                     "A day passes when: (a) all 6 slots are spent, (b) you use [W] Wait/Rest,\n"
                     "or (c) you travel (travel adds 1–5 days depending on distance).\n"
                     "Each day: living costs are deducted, businesses produce goods,\n"
                     "market prices drift, heat drops by 2, and events may fire."),
                    ("The calendar",
                     "1 year = 360 days. Seasons cycle every 30 days, repeating 3 times\n"
                     "per year: Spring → Summer → Autumn → Winter → Spring → ... and so on.\n"
                     "The season counter on the status bar shows how many days remain\n"
                     "until the next seasonal price shift."),
                    ("Waiting strategically",
                     "Use [W] Wait/Rest to skip ahead without spending action slots.\n"
                     "Waiting costs no slots but does advance the calendar, paying\n"
                     "living costs each day and triggering all daily events normally.\n"
                     "Wait until next season to time a big sell into a price spike."),
                    ("Slots vs. travel time",
                     "Traveling from Farmlands to the Capital takes 2 days (2 real calendar\n"
                     "days pass), consuming all remaining slots for that day plus travel days.\n"
                     "Heat drops 3× per travel day — long routes cool you fast.\n"
                     "Overloading (+15 excess weight per tier) adds 1 extra travel day."),
                ])
            else:
                err("Invalid choice — enter a number 1-11.")

    def _help_section(self, title: str, entries: List[Tuple[str, str]]):
        print(header(title))
        for heading, body in entries:
            print(f"\n  {BOLD}{YELLOW}{heading}{RESET}")
            for line in body.split("\n"):
                print(f"  {GREY}  {line.strip()}{RESET}")
        pause()

    # ── Tutorial ──────────────────────────────────────────────────────────────

    def _run_tutorial(self) -> None:
        """Paginated new-player tutorial covering core game mechanics."""
        import textwrap as _tw
        W = 56  # usable text width per line

        def tip(label: str, body: str) -> None:
            print(f"\n  {BOLD}{YELLOW}{label}{RESET}")
            for line in _tw.wrap(body, width=W):
                print(f"  {GREY}  {line}{RESET}")

        def bullet(text: str) -> None:
            for i, line in enumerate(_tw.wrap(text, width=W - 4)):
                prefix = "• " if i == 0 else "  "
                print(f"  {GREY}  {prefix}{line}{RESET}")

        def kh(key: str, desc: str) -> None:
            print(f"    {BOLD}{CYAN}[{key}]{RESET}  {GREY}{desc}{RESET}")

        # ── Screen 1: Navigation ──────────────────────────────────────────────
        print(header(f"TUTORIAL  1/4  ·  NAVIGATION"))
        tip("Getting Around",
            "Use letter keys to navigate the main menu; in sub-menus use number keys. "
            "[B] goes back from any sub-menu. [?] opens the full help guide.")
        print()
        kh("T", "Trade")
        kh("V", "Travel")
        kh("B", "Businesses")
        kh("C", "Contracts")
        kh("F", "Finance")
        kh("R", "Licenses & Reputation")
        kh("N / M", "News · Market Info")
        kh("W", "Wait / Rest")
        kh("SAVE", "Save game")
        pause()

        # ── Screen 2: Time & the Economy ─────────────────────────────────────
        print(header(f"TUTORIAL  2/4  ·  TIME & THE ECONOMY"))
        tip("Schedule",
            "You have 6 activity slots per day. Slots refill each morning. "
            "Buying and selling never costs slots — trade freely. "
            "Use [W] to rest and skip time when needed.")
        tip("Seasons & Events",
            "Seasons shift every 30 days, moving demand for goods "
            "dramatically. Random world events — fires, plagues, "
            "embargoes — can swing prices overnight. "
            "Check [N] News and [M] Market Info to stay ahead.")
        tip("Reputation",
            "Your rep affects prices, contract quality, and what licenses "
            "you can buy. Keep it healthy — it opens a lot of doors.")
        pause()

        # ── Screen 3: Making Money ────────────────────────────────────────────
        print(header(f"TUTORIAL  3/4  ·  MAKING MONEY"))
        tip("Trading  (Early Game)",
            "Buy goods cheap where they're produced; sell where demand "
            "is high. Each area has its own specialty:")
        print()
        bullet("Farmland — grain, ale, honey")
        bullet("Mountain — ore, coal, gems")
        bullet("Coast    — fish, salt, spice")
        bullet("Forest   — timber, herbs, fur")
        bullet("Swamp    — rare herbs, curiosities  (risky)")
        bullet("Desert   — spice, ivory, silk  (very risky)")
        bullet("City     — high demand for almost everything")
        print(f"\n  {GREY}  Tip: [T] → option 5 opens the Arbitrage Advisor for best routes.{RESET}")
        tip("Contracts  (Early–Mid Game)",
            "Unlock via Trade Contract Seal from [R]. "
            "Contracts lock in a price before you start — "
            "reliable income when the market feels uncertain.")
        pause()

        # ── Screen 4: Growth Path ─────────────────────────────────────────────
        print(header(f"TUTORIAL  4/4  ·  GROWTH PATH"))
        tip("Businesses  (Mid Game)",
            "A Business License from [R] lets you buy production "
            "sites — farms, mines, fisheries. They generate goods "
            "daily while you focus on other things.")
        tip("Lending & Funds  (Late Game)",
            "High reputation and Banking skill unlock Lending Charter "
            "and Fund Manager License. These shift your income from "
            "hauling goods to managing capital — a different game entirely.")
        tip("Skills  [S]",
            "Invest early in Trading to narrow your buy/sell spread. "
            "The rest you'll feel out as you grow.")
        print(f"\n  {BOLD}{GREEN}Good luck, {self.player_name}. "
              f"Press [?] any time for the full in-game guide.{RESET}\n")
        pause()

    # ── Wait / Rest ───────────────────────────────────────────────────────────

    def _wait_days_menu(self):
        """Pass time to let businesses accumulate goods and markets restock."""
        days_till   = self.DAYS_PER_SEASON - ((self.day - 1) % self.DAYS_PER_SEASON)
        seasons_lst = list(Season)
        next_s      = seasons_lst[(seasons_lst.index(self.season) + 1) % 4]
        print(header("WAIT / REST"))
        print(f"  Waiting advances time: businesses produce, markets restock, heat cools.")
        print(f"  Current season: {c(self.season.value, CYAN)}  ·  Days until {c(next_s.value, CYAN)}: {days_till}")
        print(f"\n  {CYAN}1{RESET}. Wait 1 day")
        print(f"  {CYAN}2{RESET}. Wait until next season  ({days_till} day(s))")
        print(f"  {CYAN}3{RESET}. Wait N days (max 30)")
        print(f"  {BOLD}[B]{RESET} Back")
        ch = prompt("Choice: ")
        if ch == "1":
            self._advance_day()
            self.ach_stats["wait_streak"] = self.ach_stats.get("wait_streak", 0) + 1
            self._check_achievements()
            ok(f"1 day passed. Now: {self.season.value}, Day {self.day}")
        elif ch == "2":
            print(f"  Waiting {days_till} days...")
            for _ in range(days_till):
                self._advance_day()
                self.ach_stats["wait_streak"] = self.ach_stats.get("wait_streak", 0) + 1
            self._check_achievements()
            ok(f"Season changed! Now: {c(self.season.value, CYAN)}, Day {self.day}")
        elif ch == "3":
            try:
                n = int(prompt("Days to wait (1\u201330): "))
                n = max(1, min(30, n))
                for _ in range(n):
                    self._advance_day()
                    self.ach_stats["wait_streak"] = self.ach_stats.get("wait_streak", 0) + 1
                self._check_achievements()
                ok(f"{n} day(s) passed. Now: {self.season.value}, Day {self.day}")
            except ValueError:
                err("Invalid input.")

    # ── Day Advance ───────────────────────────────────────────────────────────

    def _advance_day(self):
        self.daily_time_units = 0  # reset schedule for the new day

        # ── Autosave (every in-game day when enabled) ─────────────────────
        if self.settings.autosave:
            self.save_game(silent=True)

        # ── Daily cost of living (fluctuates ±30%, scaled by difficulty) ─
        living_cost = self._living_cost()
        self.inventory.gold -= living_cost
        if self.inventory.gold < -200:
            warn(f"Severe debt! Creditors press you. Rep -2  ({self.inventory.gold:.0f}g)")
            self.reputation = max(0, self.reputation - 2)
            # Businesses suffer: one random employee quits each deep-debt day
            biz_with_workers = [b for b in self.businesses if b.hired_workers]
            if biz_with_workers and random.random() < 0.40:
                b = random.choice(biz_with_workers)
                b.hired_workers.pop()
                b.workers = len(b.hired_workers)
                warn(f"Worker quits {b.name} — can't guarantee wages!")
        elif self.inventory.gold < 0:
            warn(f"Living expenses put you in the red! ({self.inventory.gold:.1f}g  ·  "
                 f"daily cost: {living_cost:.1f}g)")
            self._log_event(f"Living expenses: -{living_cost:.1f}g (in debt)")

        # ── Overweight penalty ────────────────────────────────────────────
        excess = self._current_weight() - self._max_carry_weight()
        if excess > 20:
            self.reputation = max(0, self.reputation - 1)
            warn(f"Overloaded by {excess:.0f}wt — exhaustion hurts your reputation!")

        # ── Low-reputation warning ────────────────────────────────────────
        if self.reputation < 20:
            warn(f"Your reputation is dangerously low ({self.reputation})! "
                 "Traders demand higher prices and merchants shun you.")
        self.day += 1
        if self.day > 360:
            self.day = 1
            self.year += 1
            ok(f"New Year!  Year {self.year} begins.")

        self.season = self._season_from_day()

        # Business production
        for b in self.businesses:
            if b.broken_down:
                continue
            b.days_owned += 1
            prod = b.daily_production()
            self.inventory.add(b.item_produced, prod)
            b.total_produced += prod
            # Deduct running costs
            daily_wages = b.worker_daily_wage()
            total_daily = b.daily_cost + daily_wages
            if self.inventory.gold >= total_daily:
                self.inventory.gold -= total_daily
            else:
                warn(f"Can't pay {b.name} costs! A worker quits.")
                if b.hired_workers:
                    b.hired_workers.pop()
                b.workers = len(b.hired_workers)
                if self.inventory.gold >= b.daily_cost:
                    self.inventory.gold -= b.daily_cost
                else:
                    warn(f"{b.name} is shutting down temporarily!")
                    b.broken_down = True
                    b.repair_cost = b.daily_cost * 5

            # Random breakdown
            breakdown_chance = 0.001 / max(1, b.level * 0.5)
            if random.random() < breakdown_chance:
                b.broken_down = True
                b.repair_cost = round(b.purchase_cost * 0.15, 2)
                warn(f"⚠ {b.name} has broken down! Repair cost: {b.repair_cost:.0f}g")
                self._log_event(f"{b.name} broke down — repair: {b.repair_cost:.0f}g")

            # Industry skill: +8% bonus production per skill level (all levels)
            if self.skills.industry > 1:
                industry_bonus = round(prod * (self.skills.industry - 1) * 0.08)
                if industry_bonus > 0:
                    self.inventory.add(b.item_produced, industry_bonus)
            # At high levels: occasional extra windfall (~25% chance)
            if self.skills.industry >= 3 and random.random() < 0.25:
                bonus = max(1, prod // 4)
                self.inventory.add(b.item_produced, bonus)

        # Market updates
        for market in self.markets.values():
            market.update(self.season)

        # Monthly loan payments + savings interest (every 30 days)
        if self.day % 30 == 0:
            for loan in self.loans[:]:
                if self.inventory.gold >= loan.monthly_payment:
                    self.inventory.gold -= loan.monthly_payment
                    loan.months_remaining -= 1
                    if loan.months_remaining <= 0:
                        self.loans.remove(loan)
                        ok("Loan fully repaid!")
                        self.reputation = min(100, self.reputation + 5)
                else:
                    # Default
                    warn(f"Loan payment missed! Debt increases. Rep -10.")
                    loan.principal *= 1.5
                    loan.monthly_payment = round(loan.principal / max(1, loan.months_remaining), 2)
                    self.reputation = max(0, self.reputation - 10)
                    self._log_event("Loan payment missed — debt grew 50%")

            # Monthly savings interest on liquid bank balance
            if self.bank_balance > 0:
                monthly_rate = 0.015 + self.skills.banking * 0.002
                interest     = round(self.bank_balance * monthly_rate, 2)
                self.bank_balance += interest
                ok(f"Bank interest: +{interest:.2f}g  ({monthly_rate*100:.1f}%/mo  ·  balance: {self.bank_balance:.0f}g)")

        # Daily CD maturity check
        for cd in self.cds[:]:
            if self._absolute_day() >= cd.maturity_day:
                payout = round(cd.principal * (1 + cd.rate), 2)
                profit = round(payout - cd.principal, 2)
                self.inventory.gold += payout
                self.cds.remove(cd)
                ok(f"💰 CD matured!  Received {payout:.0f}g  "
                   f"(principal {cd.principal:.0f}g + {c(f'{profit:.0f}g interest', GREEN)})")
                self._log_event(f"CD matured: +{profit:.0f}g on {cd.principal:.0f}g ({cd.term_days}d term)")

        # Random world event (frequency scales with difficulty)
        if random.random() < 0.04 * self.settings.event_freq_mult:
            self._trigger_random_event()

        # Contract expiry check
        for con in self.contracts:
            if not con.fulfilled and con.deadline_day < self._absolute_day():
                if con.penalty > 0:
                    self.inventory.gold = max(0, self.inventory.gold - con.penalty)
                    self.reputation = max(0, self.reputation - 5)
                    warn(f"Contract expired! Penalty deducted: {con.penalty:.0f}g")
                    self._log_event(f"Contract expired — penalty: {con.penalty:.0f}g")
                    self._track_stat("contracts_failed")
                    self.ach_stats["contracts_streak"] = 0
                con.fulfilled = True  # mark as done (failed)

        # Heat naturally cools
        if self.heat > 0:
            self.heat = max(0, self.heat - 2)

        # ── Stock market daily advance ─────────────────────────────────────
        self.stock_market.update(self.markets, self.season)

        # ── Business manager daily actions ─────────────────────────────────
        if self.business_manager:
            self._manager_daily_actions()

        # ── NPC hired managers daily actions ──────────────────────────────
        if self.hired_managers:
            self._run_hired_managers()

        # ── Voyage daily progress ─────────────────────────────────────────
        for _voy in [v for v in self.voyages if v.status == "sailing"]:
            _voy.days_remaining -= 1
            _ship    = next((s for s in self.ships    if s.id == _voy.ship_id),    None)
            _captain = next((c for c in self.captains if c.id == _voy.captain_id), None)
            _piracy_r = (_ship.piracy_risk if _ship else 0.10) * (_captain.piracy_mult if _captain else 1.0)
            _wreck_r  = (_ship.wreck_risk  if _ship else 0.06) * (_captain.wreck_mult  if _captain else 1.0)
            _daily_piracy = _piracy_r / max(1, _voy.days_total)
            _daily_wreck  = _wreck_r  / max(1, _voy.days_total)
            _roll = random.random()
            if _roll < _daily_wreck:
                _voy.status       = "lost_wreck"
                _voy.outcome_text = f"The {_voy.ship_name} was lost in a violent storm."
                if _ship:
                    self.ships.remove(_ship)
                self.ach_stats["voyages_lost"] = self.ach_stats.get("voyages_lost", 0) + 1
                self.news_feed.appendleft((self._absolute_day(), "Sea", "Shipwreck",
                                           f"The {_voy.ship_name} was lost at sea!"))
                self.event_log.appendleft(_voy.outcome_text)
            elif _roll < _daily_wreck + _daily_piracy:
                _voy.status       = "lost_piracy"
                _voy.outcome_text = f"Pirates seized the {_voy.ship_name}. Crew ransomed for 200g."
                self.inventory.gold = max(0.0, self.inventory.gold - 200)
                if _ship:
                    _ship.status    = "docked"
                    _ship.voyage_id = None
                self.ach_stats["voyages_lost"] = self.ach_stats.get("voyages_lost", 0) + 1
                self.news_feed.appendleft((self._absolute_day(), "Sea", "Piracy",
                                           f"The {_voy.ship_name} was seized by pirates!"))
                self.event_log.appendleft(_voy.outcome_text)
            elif _voy.days_remaining <= 0:
                _port  = VOYAGE_PORTS.get(_voy.destination_key, {})
                _pmult = _port.get("profit_mult", {})
                _profit = 0.0
                for _ikey, _qty in _voy.cargo.items():
                    _item = ALL_ITEMS.get(_ikey)
                    if _item:
                        _cat_mult = _pmult.get(_item.category.name, 1.1)
                        _profit  += _item.base_price * _qty * _cat_mult
                if _captain:
                    _profit *= _captain.profit_mult
                if _ship:
                    _profit *= _ship.profit_mult
                _profit *= self.settings.price_sell_mult
                _voy.status        = "arrived"
                _voy.outcome_gold  = _profit
                _voy.outcome_text  = (f"The {_voy.ship_name} returned from "
                                      f"{_port.get('name', '?')} with {_profit:,.0f}g.")
                self.inventory.gold += _profit
                self.total_profit   += max(0.0, _profit - _voy.cargo_cost)
                if _ship:
                    _ship.status    = "docked"
                    _ship.voyage_id = None
                self.ach_stats["voyages_completed"] = self.ach_stats.get("voyages_completed", 0) + 1
                self.ach_stats["voyage_gold_earned"] = self.ach_stats.get("voyage_gold_earned", 0.0) + _profit
                self.news_feed.appendleft((self._absolute_day(), "Sea", "Voyage Return",
                                           _voy.outcome_text))
                self.event_log.appendleft(_voy.outcome_text)

        # ── Citizen loan weekly payments (every 7 days) ───────────────────
        if self.day % 7 == 0:
            for cl in self.citizen_loans[:]:
                if cl.defaulted or cl.weeks_remaining <= 0:
                    continue
                econ_stress = 1.0 + sum(
                    0.15 for mkt in self.markets.values()
                    for e in mkt.active_events
                    if "WAR" in e or "DROUGHT" in e
                )
                if random.random() < (1.5 - cl.creditworthiness) * 0.06 * econ_stress:
                    cl.defaulted = True
                    warn(f"Citizen loan DEFAULTED: {cl.borrower_name} can't pay!  Rep -2")
                    self.reputation = max(0, self.reputation - 2)
                    self._log_event(f"Citizen loan default: {cl.borrower_name}")
                    continue
                self.inventory.gold += cl.weekly_payment
                cl.total_received   += cl.weekly_payment
                cl.weeks_remaining  -= 1
                if cl.weeks_remaining <= 0:
                    ok(f"Citizen loan fully repaid: {cl.borrower_name}  "
                       f"(total: +{cl.total_received:.0f}g)")
                    self.reputation = min(100, self.reputation + 1)
                    self._log_event(f"Citizen loan repaid by {cl.borrower_name}: +{cl.total_received:.0f}g")

        # ── Real estate — daily lease income & construction progress ──────────
        daily_lease_total = 0.0
        for prop in self.real_estate:
            prop.days_owned += 1
            if prop.under_construction:
                prop.construction_days_left = max(0, prop.construction_days_left - 1)
                if prop.construction_days_left == 0:
                    prop.under_construction = False
                    prop.condition = 1.0
                    self._track_stat("re_builds_completed")
                    ok(f"🏗 Construction complete: {c(prop.name, CYAN)} in {prop.area.value}!")
                    self._log_event(f"Construction complete: {prop.name} ({prop.area.value})")
                    self._check_achievements()
            elif prop.is_leased and prop.condition >= 0.20:
                income = prop.daily_lease
                if income > 0:
                    self.inventory.gold += income
                    prop.total_lease_income += income
                    daily_lease_total += income
        # Construction progress for land plots
        completed_plots = []
        for plot in self.land_plots:
            if plot.build_project and plot.build_days_left > 0:
                plot.build_days_left -= 1
                if plot.build_days_left == 0:
                    # Convert land plot into a finished property
                    cat = PROPERTY_CATALOGUE.get(plot.build_project, {})
                    area_mult = AREA_PROPERTY_MULT.get(plot.area.name, 1.0)
                    names = _PROP_NAMES.get(plot.build_project, ["New Property"])
                    prop_name = random.choice(names)
                    new_prop = Property(
                        id=self.next_property_id, prop_type=plot.build_project,
                        name=prop_name, area=plot.area, condition=1.0,
                        base_value=cat.get("base_value", 1000), area_mult=area_mult,
                        purchase_price_paid=plot.purchase_price + plot.build_cost_paid,
                    )
                    self.next_property_id += 1
                    self.real_estate.append(new_prop)
                    self._track_stat("re_builds_completed")
                    self._track_stat("re_properties_owned")
                    if new_prop.area.name not in self.ach_stats.get("re_properties_areas", []):
                        self.ach_stats.setdefault("re_properties_areas", []).append(new_prop.area.name)
                    completed_plots.append(plot)
                    ok(f"🏗 Construction complete: {c(prop_name, CYAN)} in {plot.area.value}!")
                    self._log_event(f"Built: {prop_name} ({plot.area.value})")
                    self._check_achievements()
        for p in completed_plots:
            self.land_plots.remove(p)
        if daily_lease_total > 0:
            self.ach_stats["re_lease_income"] = self.ach_stats.get("re_lease_income", 0.0) + daily_lease_total
            self.ach_stats["re_leases_active"] = sum(1 for p in self.real_estate if p.is_leased and not p.under_construction)
        # ── Fund client fees (every 30 days) + maturity checks (daily) ────
        if self.day % 30 == 0:
            for fc in self.fund_clients:
                if not fc.withdrawn:
                    fee = round(fc.capital * fc.fee_rate, 2)
                    self.inventory.gold += fee
                    fc.fees_collected   += fee
                    self._track_stat("fund_fees", fee)
        today_abs = self._absolute_day()
        for fc in self.fund_clients[:]:
            if fc.withdrawn or today_abs < fc.maturity_day:
                continue
            owed = round(fc.capital * (1 + fc.promised_rate), 2)
            if self.inventory.gold >= owed:
                self.inventory.gold -= owed
                fc.withdrawn = True
                ok(f"Fund matured — paid {fc.name} {c(f'{owed:.0f}g', YELLOW)}. "
                   f"Fees earned: {c(f'+{fc.fees_collected:.0f}g', GREEN)}")
                self.reputation = min(100, self.reputation + 2)
                self._log_event(f"Fund matured for {fc.name}: paid {owed:.0f}g")
            else:
                warn(f"Can't pay fund client {fc.name}! Need {owed:.0f}g.  Rep -5")
                self.reputation   = max(0, self.reputation - 5)
                fc.capital        = round(fc.capital * 1.20, 2)
                fc.maturity_day   = today_abs + 14
                self._log_event(f"Fund default for {fc.name} — penalty applied")

        # Occasional neutral-flavour filler news (~25% chance per day)
        if random.random() < 0.25:
            headline = random.choice(NEWS_POOL["NEUTRAL"])
            self.news_feed.appendleft((self._absolute_day(), "—", "Local Rumour", headline))

        # Track net worth
        if self.day % 10 == 0:
            self.net_worth_history.append(self._net_worth())

        # ── Achievement stat tracking (daily) ─────────────────────────────
        if self.inventory.gold < 0 and not self.ach_stats.get("went_negative", False):
            self._track_stat("went_negative", True)
        if self.reputation <= 0 and not self.ach_stats.get("rep_hit_zero", False):
            self._track_stat("rep_hit_zero", True)
        if self.reputation < 20:
            self._track_stat("rep_floor_tracking", True)
        if (self.ach_stats.get("rep_floor_tracking", False)
                and self.reputation >= 60
                and not self.ach_stats.get("rep_recovered", False)):
            self._track_stat("rep_recovered", True)

        # Check achievements every day so time-based ones fire promptly
        self._check_achievements()

    def _trigger_random_event(self):
        event, affected_regions, _ = random.choice(RANDOM_EVENTS)
        region_enum = None
        for area, info in AREA_INFO.items():
            if any(r in area.name for r in affected_regions):
                region_enum = area
                break
        if not region_enum:
            region_enum = random.choice(list(Area))

        self.markets[region_enum].apply_event(event)
        self.stock_market.on_event(event)   # propagate to stock prices
        if self.current_area == region_enum:
            warn(f"WORLD EVENT: {event.value} in {region_enum.value}!")
        else:
            print(c(f"  [News] {event.value} reported in {region_enum.value}...", GREY))
        self._log_event(f"World event: {event.value} in {region_enum.value}")
        self._track_stat("events_triggered")

        # Store a narrative headline in the news feed
        pool = NEWS_POOL.get(event.name, NEWS_POOL["NEUTRAL"])
        headline = random.choice(pool)
        self.news_feed.appendleft((self._absolute_day(), region_enum.value, event.value, headline))

    # ── Save / Load ───────────────────────────────────────────────────────────

    def save_game(self, silent: bool = False):
        businesses_data = []
        for b in self.businesses:
            businesses_data.append({
                "key": b.key, "name": b.name, "item_produced": b.item_produced,
                "production_rate": b.production_rate, "daily_cost": b.daily_cost,
                "purchase_cost": b.purchase_cost, "area": b.area.name,
                "level": b.level, "workers": b.workers, "max_workers": b.max_workers,
                "broken_down": b.broken_down, "repair_cost": b.repair_cost,
                "days_owned": b.days_owned, "total_produced": b.total_produced,
                "hired_workers": b.hired_workers,
            })

        contracts_data = []
        for con in self.contracts:
            contracts_data.append({
                "id": con.id, "item_key": con.item_key, "quantity": con.quantity,
                "price_per_unit": con.price_per_unit, "destination": con.destination.name,
                "deadline_day": con.deadline_day, "reward_bonus": con.reward_bonus,
                "penalty": con.penalty, "fulfilled": con.fulfilled,
            })

        loans_data = [{"principal": l.principal, "interest_rate": l.interest_rate,
                       "months_remaining": l.months_remaining, "monthly_payment": l.monthly_payment}
                      for l in self.loans]

        cds_data = [{"principal": cd.principal, "rate": cd.rate,
                     "maturity_day": cd.maturity_day, "term_days": cd.term_days}
                    for cd in self.cds]

        skills_data = {
            "trading": self.skills.trading, "haggling": self.skills.haggling,
            "logistics": self.skills.logistics, "industry": self.skills.industry,
            "espionage": self.skills.espionage, "banking": self.skills.banking,
            "xp": self.skills.xp,
        }

        data = {
            "version": 2,
            "player_name": self.player_name,
            "day": self.day, "year": self.year, "season": self.season.name,
            "current_area": self.current_area.name,
            "gold": self.inventory.gold,
            "inventory_items": self.inventory.items,
            "cost_basis": self.inventory.cost_basis,
            "bank_balance": self.bank_balance,
            "reputation": self.reputation,
            "heat": self.heat,
            "total_profit": self.total_profit,
            "lifetime_trades": self.lifetime_trades,
            "next_contract_id": self.next_contract_id,
            "businesses": businesses_data,
            "contracts": contracts_data,
            "loans": loans_data,
            "cds": cds_data,
            "skills": skills_data,
            "net_worth_history": self.net_worth_history[-100:],
            "licenses": [lt.name for lt in self.licenses],
            "citizen_loans": [
                {"id": cl.id, "borrower_name": cl.borrower_name,
                 "principal": cl.principal, "interest_rate": cl.interest_rate,
                 "weeks_remaining": cl.weeks_remaining, "weekly_payment": cl.weekly_payment,
                 "total_received": cl.total_received, "defaulted": cl.defaulted,
                 "creditworthiness": cl.creditworthiness}
                for cl in self.citizen_loans
            ],
            "next_citizen_loan_id": self.next_citizen_loan_id,
            "stock_holdings": {
                sym: {"shares": h.shares, "avg_cost": h.avg_cost}
                for sym, h in self.stock_holdings.items()
            },
            "business_manager": (
                {"name": m.name, "wage_per_week": m.wage_per_week,
                 "days_employed": m.days_employed, "total_repairs": m.total_repairs,
                 "total_hires": m.total_hires, "total_sold_value": m.total_sold_value,
                 "auto_sell": m.auto_sell, "auto_repair": m.auto_repair,
                 "auto_hire": m.auto_hire}
                if (m := self.business_manager) else None
            ),
            "fund_clients": [
                {"id": fc.id, "name": fc.name, "capital": fc.capital,
                 "promised_rate": fc.promised_rate, "start_day": fc.start_day,
                 "duration_days": fc.duration_days, "maturity_day": fc.maturity_day,
                 "fee_rate": fc.fee_rate, "withdrawn": fc.withdrawn,
                 "fees_collected": fc.fees_collected}
                for fc in self.fund_clients
            ],
            "next_fund_client_id": self.next_fund_client_id,
            "stock_prices": self.stock_market.to_save(),
            "achievements": list(self.achievements),
            "ach_stats": {
                k: (list(v) if isinstance(v, list) else v)
                for k, v in self.ach_stats.items()
            },
            "gamble_mercy":       self.settings.gamble_mercy,
            "influence_cooldowns": dict(self.influence_cooldowns),
            # ── Real Estate ──────────────────────────────────────────────────────────
            "real_estate": [
                {"id": p.id, "prop_type": p.prop_type, "name": p.name,
                 "area": p.area.name, "condition": p.condition,
                 "base_value": p.base_value, "area_mult": p.area_mult,
                 "is_leased": p.is_leased, "days_owned": p.days_owned,
                 "upgrades": p.upgrades,
                 "under_construction": p.under_construction,
                 "construction_days_left": p.construction_days_left,
                 "total_lease_income": p.total_lease_income,
                 "purchase_price_paid": p.purchase_price_paid,
                 "tenant_name": p.tenant_name,
                 "lease_rate_mult": p.lease_rate_mult}
                for p in self.real_estate
            ],
            "land_plots": [
                {"id": pl.id, "area": pl.area.name, "size": pl.size,
                 "purchase_price": pl.purchase_price,
                 "build_project": pl.build_project,
                 "build_days_left": pl.build_days_left,
                 "build_cost_paid": pl.build_cost_paid}
                for pl in self.land_plots
            ],
            "next_property_id": self.next_property_id,
            "next_plot_id": self.next_plot_id,
            # ── NPC Managers ─────────────────────────────────────────────────────────────
            "hired_managers": [
                {
                    "manager_type":  m.manager_type,
                    "name":          m.name,
                    "level":         m.level,
                    "xp":            m.xp,
                    "days_employed": m.days_employed,
                    "weekly_wage":   m.weekly_wage,
                    "is_active":     m.is_active,
                    "config":        m.config,
                    "stats":         m.stats,
                }
                for m in self.hired_managers
            ],
            "manager_action_log": list(self._manager_action_log),
            # ── Voyage system ────────────────────────────────────────────────────────────
            "ships": [
                {"id": s.id, "ship_type": s.ship_type, "name": s.name,
                 "upgrades": s.upgrades, "status": s.status, "voyage_id": s.voyage_id}
                for s in self.ships
            ],
            "captains": [
                {"id": c.id, "name": c.name, "title": c.title,
                 "navigation": c.navigation, "combat": c.combat,
                 "seamanship": c.seamanship, "charisma": c.charisma,
                 "wage_per_voyage": c.wage_per_voyage, "crew_wage": c.crew_wage,
                 "is_hired": c.is_hired}
                for c in self.captains
            ],
            "voyages": [
                {"id": v.id, "ship_id": v.ship_id, "ship_name": v.ship_name,
                 "captain_id": v.captain_id, "captain_name": v.captain_name,
                 "destination_key": v.destination_key, "cargo": v.cargo,
                 "cargo_cost": v.cargo_cost, "days_total": v.days_total,
                 "days_remaining": v.days_remaining, "status": v.status,
                 "outcome_gold": v.outcome_gold, "outcome_text": v.outcome_text,
                 "departure_day": v.departure_day}
                for v in self.voyages
            ],
            "next_ship_id":    self.next_ship_id,
            "next_captain_id": self.next_captain_id,
            "next_voyage_id":  self.next_voyage_id,
            # ── Activity logs (saved so they survive a reload) ────────────────────────────
            "news_feed":  [list(entry) for entry in self.news_feed],
            "event_log":  list(self.event_log),
            "trade_log":  list(self.trade_log),
        }

        try:
            raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
            payload = base64.b64encode(zlib.compress(raw, level=6))
            with open(self.SAVE_FILE, "wb") as f:
                f.write(payload)
        except Exception as exc:
            if not silent:
                err(f"Save failed: {exc}")
            return
        if not silent:
            ok(f"Game saved.")

    def load_game(self) -> bool:
        if not os.path.exists(self.SAVE_FILE):
            # Legacy plain-JSON path fallback
            legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "merchant_savegame.json")
            if not os.path.exists(legacy):
                return False
            try:
                with open(legacy, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                return False
        else:
            try:
                with open(self.SAVE_FILE, "rb") as f:
                    payload = f.read()
                # Try new obfuscated format first, fall back to plain JSON
                try:
                    raw = zlib.decompress(base64.b64decode(payload))
                    data = json.loads(raw.decode("utf-8"))
                except Exception:
                    data = json.loads(payload.decode("utf-8"))
            except Exception:
                return False
        try:

            self.player_name  = data.get("player_name", "Merchant")
            self.day          = data.get("day", 1)
            self.year         = data.get("year", 1)
            self.season       = Season[data.get("season", "SPRING")]
            self.current_area = Area[data.get("current_area", "CITY")]
            self.inventory    = Inventory(data.get("gold", 500.0))
            self.inventory.items      = data.get("inventory_items", {})
            self.inventory.cost_basis = data.get("cost_basis", {})
            self.bank_balance = data.get("bank_balance", 0.0)
            self.reputation   = data.get("reputation", 50)
            self.heat         = data.get("heat", 0)
            self.total_profit = data.get("total_profit", 0.0)
            self.lifetime_trades = data.get("lifetime_trades", 0)
            self.next_contract_id = data.get("next_contract_id", 1)
            self.net_worth_history = data.get("net_worth_history", [])

            self.businesses = []
            for bd in data.get("businesses", []):
                b = Business(
                    key=bd["key"], name=bd["name"], item_produced=bd["item_produced"],
                    production_rate=bd["production_rate"], daily_cost=bd["daily_cost"],
                    purchase_cost=bd["purchase_cost"], area=Area[bd["area"]],
                    level=bd.get("level", 1), workers=bd.get("workers", 0),
                    max_workers=bd.get("max_workers", 5),
                    broken_down=bd.get("broken_down", False),
                    repair_cost=bd.get("repair_cost", 0.0),
                    days_owned=bd.get("days_owned", 0),
                    total_produced=bd.get("total_produced", 0),
                    hired_workers=bd.get("hired_workers", []),
                )
                # Migrate legacy saves: rebuild hired_workers from workers count
                if not b.hired_workers and b.workers > 0:
                    b.hired_workers = [{"name": f"Worker {i+1}", "wage": 8.0,
                                        "productivity": 1.0, "trait": ""}
                                       for i in range(b.workers)]
                b.workers = len(b.hired_workers)
                self.businesses.append(b)

            self.contracts = []
            for cd in data.get("contracts", []):
                con = Contract(
                    id=cd["id"], item_key=cd["item_key"], quantity=cd["quantity"],
                    price_per_unit=cd["price_per_unit"], destination=Area[cd["destination"]],
                    deadline_day=cd["deadline_day"], reward_bonus=cd.get("reward_bonus", 0),
                    penalty=cd.get("penalty", 0), fulfilled=cd.get("fulfilled", False),
                )
                self.contracts.append(con)

            self.loans = []
            for ld in data.get("loans", []):
                self.loans.append(LoanRecord(
                    principal=ld["principal"], interest_rate=ld["interest_rate"],
                    months_remaining=ld["months_remaining"], monthly_payment=ld["monthly_payment"],
                ))

            self.cds = []
            for cdd in data.get("cds", []):
                self.cds.append(CDRecord(
                    principal=cdd["principal"], rate=cdd["rate"],
                    maturity_day=cdd["maturity_day"], term_days=cdd["term_days"],
                ))

            sd = data.get("skills", {})
            self.skills = PlayerSkills(
                trading=sd.get("trading", 1), haggling=sd.get("haggling", 1),
                logistics=sd.get("logistics", 1), industry=sd.get("industry", 1),
                espionage=sd.get("espionage", 1), banking=sd.get("banking", 1),
                xp=sd.get("xp", {s.value: 0 for s in SkillType}),
            )

            # ── New feature fields (backward compatible) ────────────────────
            raw_lic = data.get("licenses")
            if raw_lic is None:
                # Legacy save: grant the three always-available licenses
                self.licenses = {LicenseType.MERCHANT}
            else:
                self.licenses = set()
                for name in raw_lic:
                    try:
                        self.licenses.add(LicenseType[name])
                    except KeyError:
                        pass

            self.citizen_loans = []
            for cld in data.get("citizen_loans", []):
                self.citizen_loans.append(CitizenLoan(
                    id=cld["id"], borrower_name=cld["borrower_name"],
                    principal=cld["principal"], interest_rate=cld["interest_rate"],
                    weeks_remaining=cld["weeks_remaining"], weekly_payment=cld["weekly_payment"],
                    total_received=cld.get("total_received", 0.0),
                    defaulted=cld.get("defaulted", False),
                    creditworthiness=cld.get("creditworthiness", 0.8),
                ))
            self.next_citizen_loan_id = data.get("next_citizen_loan_id", 1)

            self.stock_holdings = {}
            for sym, hd in data.get("stock_holdings", {}).items():
                self.stock_holdings[sym] = StockHolding(
                    symbol=sym, shares=hd["shares"], avg_cost=hd["avg_cost"])

            mgd = data.get("business_manager")
            if mgd:
                self.business_manager = BusinessManagerRecord(
                    name=mgd["name"], wage_per_week=mgd["wage_per_week"],
                    days_employed=mgd.get("days_employed", 0),
                    total_repairs=mgd.get("total_repairs", 0),
                    total_hires=mgd.get("total_hires", 0),
                    total_sold_value=mgd.get("total_sold_value", 0.0),
                    auto_sell=mgd.get("auto_sell", True),
                    auto_repair=mgd.get("auto_repair", True),
                    auto_hire=mgd.get("auto_hire", True),
                )
            else:
                self.business_manager = None

            self.fund_clients = []
            for fcd in data.get("fund_clients", []):
                self.fund_clients.append(FundClient(
                    id=fcd["id"], name=fcd["name"], capital=fcd["capital"],
                    promised_rate=fcd["promised_rate"], start_day=fcd["start_day"],
                    duration_days=fcd["duration_days"], maturity_day=fcd["maturity_day"],
                    fee_rate=fcd["fee_rate"], withdrawn=fcd.get("withdrawn", False),
                    fees_collected=fcd.get("fees_collected", 0.0),
                ))
            self.next_fund_client_id = data.get("next_fund_client_id", 1)

            sp = data.get("stock_prices")
            if sp:
                self.stock_market.from_save(sp)

            # ── Achievement data (backward-compatible) ──────────────────
            self.achievements = set(data.get("achievements", []))
            saved_stats = data.get("ach_stats", {})
            for k, default_v in self.ach_stats.items():
                if k in saved_stats:
                    sv = saved_stats[k]
                    if isinstance(default_v, list):
                        self.ach_stats[k] = list(sv) if isinstance(sv, list) else default_v
                    else:
                        self.ach_stats[k] = sv
            self.influence_cooldowns = {k: int(v) for k, v in data.get("influence_cooldowns", {}).items()}
            self.settings.gamble_mercy = int(data.get("gamble_mercy", 0))

            # ── Real Estate (backward-compatible) ───────────────────────────────────
            self.real_estate = []
            for pd in data.get("real_estate", []):
                try:
                    self.real_estate.append(Property(
                        id=pd["id"], prop_type=pd["prop_type"], name=pd["name"],
                        area=Area[pd["area"]], condition=float(pd["condition"]),
                        base_value=float(pd["base_value"]), area_mult=float(pd["area_mult"]),
                        is_leased=pd.get("is_leased", False),
                        days_owned=pd.get("days_owned", 0),
                        upgrades=pd.get("upgrades", []),
                        under_construction=pd.get("under_construction", False),
                        construction_days_left=pd.get("construction_days_left", 0),
                        total_lease_income=pd.get("total_lease_income", 0.0),
                        purchase_price_paid=pd.get("purchase_price_paid", 0.0),
                        tenant_name=pd.get("tenant_name", ""),
                        lease_rate_mult=float(pd.get("lease_rate_mult", 1.0)),
                    ))
                except Exception:
                    pass
            self.land_plots = []
            for pld in data.get("land_plots", []):
                try:
                    self.land_plots.append(LandPlot(
                        id=pld["id"], area=Area[pld["area"]], size=pld["size"],
                        purchase_price=float(pld["purchase_price"]),
                        build_project=pld.get("build_project", ""),
                        build_days_left=pld.get("build_days_left", 0),
                        build_cost_paid=float(pld.get("build_cost_paid", 0.0)),
                    ))
                except Exception:
                    pass
            self.next_property_id = data.get("next_property_id", 1)
            self.next_plot_id     = data.get("next_plot_id",     1)

            # ── NPC Managers (backward-compatible) ──────────────────────────────────────────
            self.hired_managers = []
            for md in data.get("hired_managers", []):
                try:
                    default_stats = {
                        "total_actions": 0, "total_gold_generated": 0.0,
                        "total_wages_paid": 0.0, "total_gold_cost": 0.0,
                        "mistakes": 0, "level_ups": 0,
                        "last_action_day": 0, "last_action_desc": "",
                        # Trade Steward travel/tracking state (ignored by other types)
                        "mgr_area": None, "travel_dest": None,
                        "travel_days_left": 0,
                        "cost_basis": {}, "hold_since_day": {},
                    }
                    saved_stats = md.get("stats", {})
                    merged_stats = {**default_stats, **saved_stats}
                    mgr = HiredManager(
                        manager_type  = md["manager_type"],
                        name          = md["name"],
                        level         = md.get("level", 1),
                        xp            = md.get("xp", 0),
                        days_employed = md.get("days_employed", 0),
                        weekly_wage   = md.get("weekly_wage", 25.0),
                        is_active     = md.get("is_active", True),
                        config        = md.get("config", {}),
                        stats         = merged_stats,
                    )
                    self.hired_managers.append(mgr)
                except Exception:
                    pass
            for entry in reversed(data.get("manager_action_log", [])):
                self._manager_action_log.appendleft(str(entry))

            # ── Voyage system (backward-compatible) ────────────────────────────────────────
            self.ships = []
            for sd in data.get("ships", []):
                try:
                    self.ships.append(Ship(
                        id=sd["id"], ship_type=sd["ship_type"], name=sd["name"],
                        upgrades=sd.get("upgrades", []),
                        status=sd.get("status", "docked"),
                        voyage_id=sd.get("voyage_id"),
                    ))
                except Exception:
                    pass
            self.captains = []
            for cd in data.get("captains", []):
                try:
                    self.captains.append(Captain(
                        id=cd["id"], name=cd["name"], title=cd["title"],
                        navigation=cd["navigation"], combat=cd["combat"],
                        seamanship=cd["seamanship"], charisma=cd["charisma"],
                        wage_per_voyage=cd["wage_per_voyage"], crew_wage=cd["crew_wage"],
                        is_hired=cd.get("is_hired", False),
                    ))
                except Exception:
                    pass
            # Re-generate captains pool if none were saved (legacy saves)
            if not self.captains:
                self._generate_captains()
            self.voyages = []
            for vd in data.get("voyages", []):
                try:
                    self.voyages.append(Voyage(
                        id=vd["id"], ship_id=vd["ship_id"], ship_name=vd["ship_name"],
                        captain_id=vd["captain_id"], captain_name=vd["captain_name"],
                        destination_key=vd["destination_key"],
                        cargo=vd.get("cargo", {}),
                        cargo_cost=vd.get("cargo_cost", 0.0),
                        days_total=vd["days_total"], days_remaining=vd["days_remaining"],
                        status=vd.get("status", "sailing"),
                        outcome_gold=vd.get("outcome_gold", 0.0),
                        outcome_text=vd.get("outcome_text", ""),
                        departure_day=vd.get("departure_day", 0),
                    ))
                except Exception:
                    pass
            self.next_ship_id    = data.get("next_ship_id",    1)
            self.next_captain_id = data.get("next_captain_id", len(self.captains) + 1)
            self.next_voyage_id  = data.get("next_voyage_id",  1)

            # ── Restore activity logs ───────────────────────────────────────────────────────
            for entry in reversed(data.get("news_feed", [])):
                try:
                    self.news_feed.appendleft(tuple(entry))
                except Exception:
                    pass
            for entry in reversed(data.get("event_log", [])):
                self.event_log.appendleft(str(entry))
            for entry in reversed(data.get("trade_log", [])):
                self.trade_log.appendleft(str(entry))

            return True
        except Exception as e:
            warn(f"Failed to load save: {e}")
            return False

    # ── Permits & Licenses ────────────────────────────────────────────────────

    def licenses_menu(self):
        """Buy permits and licenses that unlock game features."""
        TIER_LABEL = {
            "starter":  c("◆ STARTER",  GREEN),
            "basic":    c("◈ BASIC",     CYAN),
            "advanced": c("★ ADVANCED",  YELLOW),
            "elite":    c("✦ ELITE",     RED),
        }
        while True:
            print(header("PERMITS & LICENSES"))
            owned_count = len(self.licenses)
            print(f"  {GREY}Licenses unlock core game features. Purchase them to expand your merchant empire.{RESET}")
            print(f"  {GREY}Your wallet: {c(f'{self.inventory.gold:.0f}g', YELLOW)}   "
                  f"Reputation: {c(str(self.reputation), CYAN)}   "
                  f"Banking skill: {c(str(self.skills.banking), CYAN)}   "
                  f"Owned: {c(str(owned_count), GREEN)}/{c('5', WHITE)}{RESET}")
            print(f"  {GREY}{'─' * 70}{RESET}\n")

            all_types = list(LicenseType)
            for i, lt in enumerate(all_types, 1):
                info  = LICENSE_INFO[lt]
                owned = lt in self.licenses
                met   = self._can_buy_license(lt)
                tier  = TIER_LABEL.get(info.get("tier", ""), "")

                # ── Status badge ──────────────────────────────────────────
                if owned:
                    badge     = c(" ✓ OWNED ", GREEN)
                    name_col  = GREEN
                    avail_str = ""
                elif met:
                    badge     = c(" ✦ BUY   ", CYAN)
                    name_col  = CYAN
                    avail_str = c(f"  → {info['cost']}g", YELLOW)
                else:
                    badge     = c(" ✗ LOCKED", GREY)
                    name_col  = GREY
                    avail_str = ""

                # ── Requirement string ────────────────────────────────────
                req_parts = []
                if info["rep"]     > 0:
                    r_met = self.reputation  >= info["rep"]
                    req_parts.append(
                        c(f"Rep {self.reputation}/{info['rep']}", GREEN if r_met else RED))
                if info["banking"] > 0:
                    b_met = self.skills.banking >= info["banking"]
                    req_parts.append(
                        c(f"Banking {self.skills.banking}/{info['banking']}", GREEN if b_met else RED))
                if info["cost"]    > 0 and not owned:
                    g_met = self.inventory.gold >= info["cost"]
                    req_parts.append(
                        c(f"{info['cost']}g", GREEN if g_met else RED))
                req_str = ("  Requires: " + "  ".join(req_parts)) if req_parts else ""

                print(f"  {CYAN}{i}{RESET}. [{badge}] {c(lt.value, name_col)}{avail_str}  {tier}")
                print(f"     {GREY}{info['desc']}{RESET}")
                print(f"     {c('Unlocks:', WHITE)} {GREY}{info['unlocks']}{RESET}")
                if req_str:
                    print(f"    {req_str}")
                print()

            print(f"  {BOLD}[B]{RESET} Back")
            ch = prompt("Enter license # to purchase, or B to go back: ")
            if ch.strip().upper() in ("0", "B"):
                return
            try:
                idx = int(ch.strip()) - 1
                if idx < 0 or idx >= len(all_types):
                    err("Invalid choice.")
                    continue
                lt   = all_types[idx]
                info = LICENSE_INFO[lt]
                if lt in self.licenses:
                    warn(f"You already hold the {lt.value}.")
                    continue
                if not self._can_buy_license(lt):
                    missing = []
                    if info["rep"]     > self.reputation:     missing.append(f"Reputation {self.reputation}/{info['rep']}")
                    if info["banking"] > self.skills.banking:  missing.append(f"Banking skill {self.skills.banking}/{info['banking']}")
                    err(f"Requirements not met — {',  '.join(missing)}")
                    continue
                if info["cost"] > self.inventory.gold:
                    err(f"Not enough gold — need {info['cost']}g, you have {self.inventory.gold:.0f}g")
                    continue
                print(f"\n  {BOLD}{lt.value}{RESET}")
                print(f"  {GREY}{info['desc']}{RESET}")
                print(f"  {c('Unlocks:', WHITE)} {GREY}{info['unlocks']}{RESET}")
                confirm = prompt(f"  Purchase for {c(f"{info['cost']}g", YELLOW)}? (yes/no): ")
                if confirm.lower() in ("yes", "y"):
                    self.inventory.gold -= info["cost"]
                    self.licenses.add(lt)
                    ok(f"{lt.value} obtained!  Gold: {self.inventory.gold:.0f}g remaining.")
                    self._log_event(f"Purchased {lt.value}")
                    self._track_stat("licenses_purchased")
                    if self.inventory.gold <= 50:
                        self._track_stat("license_bought_broke", True)
                    self._check_achievements()
            except (ValueError, IndexError):
                err("Invalid choice.")

    # ── Business Portfolio ────────────────────────────────────────────────────

    def business_portfolio_menu(self):
        """Summary view of all owned businesses with revenue estimates and ROI."""
        print(header("BUSINESS PORTFOLIO"))
        if not self.businesses:
            print(c("  You own no businesses.", GREY))
            pause()
            return
        mgr_tag = (c(f"  Manager: {self.business_manager.name}", GREEN)
                   if self.business_manager else c("  No manager", GREY))
        print(f"  {len(self.businesses)} business(es) owned{mgr_tag}\n")
        total_invest, total_rev, total_cost = 0.0, 0.0, 0.0
        print(f"  {BOLD}{'Business':<22}{'Lv':>3}{'Wkrs':>6}{'Prod/d':>7}{'Rev/d':>9}{'Cost/d':>9}{'Net/d':>9}  Status{RESET}")
        print(f"  {GREY}{'─'*82}{RESET}")
        for b in self.businesses:
            prod  = b.daily_production()
            item  = ALL_ITEMS.get(b.item_produced)
            mkt   = self.markets[b.area]
            sp    = (mkt.get_sell_price(b.item_produced, self.season)
                     if b.item_produced in mkt.item_keys
                     else (item.base_price * 0.65 if item else 0))
            drev  = round(prod * sp, 1)
            dcost = round(b.daily_cost + b.worker_daily_wage(), 1)
            net   = drev - dcost
            nc    = GREEN if net > 0 else RED
            total_invest += b.purchase_cost * b.level
            total_rev    += drev
            total_cost   += dcost
            status = c("BROKEN", RED) if b.broken_down else c("OK", GREEN)
            print(f"  {b.name:<22}{b.level:>3}{b.workers}/{b.max_workers:<4}"
                  f"{prod:>7}{c(f'{drev:.0f}g', YELLOW):>17}"
                  f"{c(f'{dcost:.0f}g', GREY):>17}{c(f'{net:+.0f}g', nc):>17}  {status}")
        total_net = total_rev - total_cost
        nc        = GREEN if total_net > 0 else RED
        ann_net   = total_net * 360
        roi       = (ann_net / max(total_invest, 1)) * 100
        print(f"  {GREY}{'─'*82}{RESET}")
        print(f"  {'TOTAL':<22}{'':>9}{total_rev:>17.0f}g"
              f"{total_cost:>17.0f}g{c(f'{total_net:+.0f}g', nc):>17}")
        print(f"\n  Total invested : {c(f'{total_invest:.0f}g', CYAN)}")
        print(f"  Annual net est.: {c(f'{ann_net:.0f}g', nc)}")
        print(f"  Est. ROI       : {c(f'{roi:.1f}%/year', nc)}")
        # Stocked production goods
        biz_keys = {b.item_produced for b in self.businesses}
        held     = {k: v for k, v in self.inventory.items.items() if k in biz_keys and v > 0}
        if held:
            print(f"\n  {BOLD}Produced goods in your inventory:{RESET}")
            for k, qty in held.items():
                item = ALL_ITEMS.get(k)
                if item:
                    mkt = self.markets[self.current_area]
                    sp  = (mkt.get_sell_price(k, self.season) if k in mkt.item_keys
                           else item.base_price * 0.65)
                    print(f"  · {item.name}: {c(str(qty), CYAN)} units  "
                          f"{GREY}(~{sp:.1f}g ea ≈ {qty*sp:.0f}g){RESET}")
        pause()

    # ── Business Manager ──────────────────────────────────────────────────────

    def business_manager_menu(self):
        """Hire/manage an NPC who auto-runs all your businesses."""
        while True:
            print(header("BUSINESS MANAGER"))
            if self.business_manager:
                mgr = self.business_manager
                print(f"  {BOLD}Manager:{RESET} {c(mgr.name, CYAN)}")
                print(f"  Wage: {c(f'{mgr.wage_per_week:.0f}g/week', YELLOW)}  "
                      f"Days employed: {mgr.days_employed}")
                print(f"  Repairs done: {mgr.total_repairs}  "
                      f"Workers hired: {mgr.total_hires}  "
                      f"Auto-sold: {c(f'{mgr.total_sold_value:.0f}g', GREEN)}")
                print(f"\n  Services:")
                print(f"    Auto-repair : {c('ON', GREEN) if mgr.auto_repair else c('OFF', GREY)}")
                print(f"    Auto-hire   : {c('ON', GREEN) if mgr.auto_hire   else c('OFF', GREY)}")
                print(f"    Auto-sell   : {c('ON', GREEN) if mgr.auto_sell   else c('OFF', GREY)}")
                print(f"\n  {CYAN}1{RESET}. Toggle auto-repair")
                print(f"  {CYAN}2{RESET}. Toggle auto-hire")
                print(f"  {CYAN}3{RESET}. Toggle auto-sell")
                print(f"  {CYAN}4{RESET}. Dismiss manager")
                print(f"  {BOLD}[B]{RESET} Back")
                ch = prompt("Choice: ")
                if ch == "1":
                    mgr.auto_repair = not mgr.auto_repair
                    ok(f"Auto-repair {'enabled' if mgr.auto_repair else 'disabled'}.")
                elif ch == "2":
                    mgr.auto_hire = not mgr.auto_hire
                    ok(f"Auto-hire {'enabled' if mgr.auto_hire else 'disabled'}.")
                elif ch == "3":
                    mgr.auto_sell = not mgr.auto_sell
                    ok(f"Auto-sell {'enabled' if mgr.auto_sell else 'disabled'}.")
                elif ch == "4":
                    confirm = prompt(f"Dismiss {mgr.name}? (yes/no): ")
                    if confirm.lower() in ("yes", "y"):
                        ok(f"{mgr.name} dismissed.")
                        self.business_manager = None
                    break
                elif ch.upper() in ("5", "B"):
                    break
            else:
                print(f"  {GREY}No manager hired.{RESET}")
                print(f"\n  A business manager automatically:")
                print(f"  {GREY}· Repairs broken businesses (if funds available){RESET}")
                print(f"  {GREY}· Hires best-value workers to fill all empty slots{RESET}")
                print(f"  {GREY}· Sells accumulated production when ≥10 units stockpiled{RESET}")
                print(f"  {GREY}· Does NOT upgrade businesses — that remains your call{RESET}")
                num_biz = max(1, len(self.businesses))
                weekly  = round(80 + num_biz * 20)
                print(f"\n  Upfront cost: {c('200g', YELLOW)}  +  weekly wage: {c(f'{weekly}g/week', YELLOW)}")
                print(f"  {GREY}Can only be hired while in the Capital City.{RESET}")
                print(f"\n  {CYAN}1{RESET}. Hire a manager")
                print(f"  {BOLD}[B]{RESET} Back")
                ch = prompt("Choice: ")
                if ch == "1":
                    if self.current_area != Area.CITY:
                        err("Managers are only available in the Capital City.")
                        break
                    if self.inventory.gold < 200:
                        err("Need 200g upfront deposit.")
                        break
                    confirm = prompt(f"Hire a manager? 200g + {weekly}g/week (yes/no): ")
                    if confirm.lower() in ("yes", "y"):
                        _mgr_names = ["Aldric Cooper","Vera Thatcher","Magnus Yarrow",
                                      "Sable Wright","Oswin Barrow","Phoebe Fletcher",
                                      "Hugo Ironsides","Ilsa Moorfield","Rand Pickwick",
                                      "Theron Saltmarsh"]
                        name = random.choice(_mgr_names)
                        self.inventory.gold -= 200
                        self.business_manager = BusinessManagerRecord(
                            name=name, wage_per_week=weekly)
                        ok(f"Hired {name} as business manager ({weekly}g/week).")
                        self._log_event(f"Hired business manager {name}")
                    break
                elif ch.upper() in ("2", "B"):
                    break

    # ── Citizen Lending ───────────────────────────────────────────────────────

    def citizen_lending_menu(self):
        """Lend money to citizens at negotiable weekly interest rates."""
        if LicenseType.LENDER not in self.licenses:
            err("Requires a Lending Charter license.")
            err("Buy one from  18. Permits & Licenses.")
            pause()
            return
        while True:
            print(header("CITIZEN LENDING"))
            outstanding = sum(cl.principal for cl in self.citizen_loans if not cl.defaulted)
            wk_income   = sum(cl.weekly_payment for cl in self.citizen_loans
                              if not cl.defaulted and cl.weeks_remaining > 0)
            print(f"  Active loans: {c(str(len(self.citizen_loans)), CYAN)}"
                  f"  ·  Outstanding capital: {c(f'{outstanding:.0f}g', YELLOW)}"
                  f"  ·  Expected weekly income: {c(f'{wk_income:.1f}g', GREEN)}\n")
            if self.citizen_loans:
                print(f"  {BOLD}{'#':<4}{'Borrower':<22}{'Principal':>10}{'Rate/wk':>9}"
                      f"{'Weeks left':>11}{'Wk payment':>12}  {'Status'}{RESET}")
                print(f"  {GREY}{'─'*76}{RESET}")
                for i, cl in enumerate(self.citizen_loans, 1):
                    st = c("DEFAULTED", RED) if cl.defaulted else (
                         c("Paid off", GREY) if cl.weeks_remaining <= 0 else c("Active", GREEN))
                    print(f"  {GREY}{i:<4}{RESET}{cl.borrower_name:<22}"
                          f"{c(f'{cl.principal:.0f}g', YELLOW):>18}"
                          f"{c(f'{cl.interest_rate*100:.1f}%', CYAN):>17}"
                          f"{cl.weeks_remaining:>11}"
                          f"{c(f'{cl.weekly_payment:.1f}g', GREEN):>20}  {st}")
            print(f"\n  {CYAN}1{RESET}. Extend a new loan")
            print(f"  {CYAN}2{RESET}. Call in a loan early (penalty applies)")
            print(f"  {BOLD}[B]{RESET} Back")
            ch = prompt("Choice: ")
            if ch == "1":
                applicants = self._gen_loan_applicants(5)
                print(f"\n  {BOLD}{'#':<4}{'Name':<22}{'Wants':>8}  {'Purpose':<24}"
                      f"{'Max rate/wk':>13}{'Weeks':>7}  Risk{RESET}")
                print(f"  {GREY}{'─'*84}{RESET}")
                for ai, ap in enumerate(applicants, 1):
                    _amt = f"{ap['amount']:.0f}g"
                    _mr  = f"{ap['max_rate']*100:.1f}%"
                    print(f"  {CYAN}{ai:<4}{RESET}{ap['name']:<22}"
                          f"{c(_amt, YELLOW):>16}  "
                          f"{ap['purpose']:<24}"
                          f"{c(_mr, CYAN):>13}"
                          f"{ap['weeks']:>7}  {ap['cw_label']}")
                print(f"  {GREY}Set your own rate; if ≤ their max the loan is accepted.{RESET}")
                try:
                    aidx = int(prompt("Select applicant (0 to cancel): ")) - 1
                    if aidx < 0 or aidx >= len(applicants):
                        continue
                    ap = applicants[aidx]
                    if ap["amount"] > self.inventory.gold:
                        err(f"Need {ap['amount']:.0f}g in wallet.")
                        continue
                    rate_s = prompt(f"Your weekly rate offer (their max {ap['max_rate']*100:.1f}%, e.g. 0.05): ")
                    rate   = float(rate_s)
                    if rate <= 0:
                        err("Rate must be positive.")
                        continue
                    if rate > ap["max_rate"]:
                        err(f"{ap['name']} refuses — rate too high.")
                        continue
                    weeks       = ap["weeks"]
                    weekly_pmt  = round(ap["amount"] * (rate + 1.0 / weeks), 2)
                    total_back  = weekly_pmt * weeks
                    profit      = total_back - ap["amount"]
                    _ap_amt = f"{ap['amount']:.0f}g"
                    print(f"\n  Lending {c(_ap_amt, YELLOW)} to {ap['name']}")
                    print(f"  Rate: {c(f'{rate*100:.1f}%/wk', CYAN)}  ·  {weeks} weeks")
                    print(f"  Weekly payment: {c(f'{weekly_pmt:.1f}g', GREEN)}")
                    print(f"  Total return: {c(f'{total_back:.0f}g', GREEN)}  "
                          f"({c(f'+{profit:.0f}g profit', GREEN)})")
                    confirm = prompt("Confirm? (yes/no): ")
                    if confirm.lower() in ("yes", "y"):
                        self.inventory.gold -= ap["amount"]
                        cl = CitizenLoan(
                            id=self.next_citizen_loan_id,
                            borrower_name=ap["name"],
                            principal=ap["amount"],
                            interest_rate=rate,
                            weeks_remaining=weeks,
                            weekly_payment=weekly_pmt,
                            creditworthiness=ap["creditworthiness"],
                        )
                        self.citizen_loans.append(cl)
                        self.next_citizen_loan_id += 1
                        ok(f"Loaned {ap['amount']:.0f}g to {ap['name']} @ {rate*100:.1f}%/wk.")
                        self._log_event(f"Citizen loan: {ap['amount']:.0f}g to {ap['name']}")
                except ValueError:
                    err("Invalid input.")
            elif ch == "2":
                active = [cl for cl in self.citizen_loans
                          if not cl.defaulted and cl.weeks_remaining > 0]
                if not active:
                    err("No active loans to recall.")
                    continue
                for i, cl in enumerate(active, 1):
                    remainder = round(cl.weeks_remaining * cl.weekly_payment, 2)
                    recall    = round(remainder * 0.80, 2)
                    print(f"  {CYAN}{i}{RESET}. {cl.borrower_name}  "
                          f"Remaining: {remainder:.0f}g  "
                          f"Recall now (−20% fee): {c(f'{recall:.0f}g', YELLOW)}")
                try:
                    ridx = int(prompt("Recall # (0 to cancel): ")) - 1
                    if ridx < 0 or ridx >= len(active):
                        continue
                    cl       = active[ridx]
                    recall   = round(cl.weeks_remaining * cl.weekly_payment * 0.80, 2)
                    self.inventory.gold += recall
                    cl.defaulted = True
                    cl.weeks_remaining = 0
                    ok(f"Recalled loan from {cl.borrower_name}: +{recall:.0f}g "
                       f"(after 20% early-recall fee).")
                    self._log_event(f"Recalled citizen loan from {cl.borrower_name}: +{recall:.0f}g")
                except (ValueError, IndexError):
                    err("Invalid input.")
            elif ch.upper() in ("3", "B"):
                break

    # ── Stock Exchange ────────────────────────────────────────────────────────

    def stock_market_menu(self):
        """Live stock exchange — buy and sell shares in 10 companies."""
        if LicenseType.FUND_MGR not in self.licenses:
            err("Requires a Fund Manager License.")
            err("Buy one from  18. Permits & Licenses.")
            pause()
            return
        while True:
            print(header("STOCK EXCHANGE"))
            pv = self._portfolio_value()
            print(f"  {GREY}Market Day {self.stock_market.day}  ·  "
                  f"Portfolio: {c(f'{pv:.0f}g', CYAN)}  ·  "
                  f"Wallet: {c(f'{self.inventory.gold:.0f}g', YELLOW)}{RESET}\n")
            print(f"  {BOLD}{'Sym':<6}{'Company':<26}{'Sector':<14}{'Price':>8}"
                  f"{'Chg%':>8}{'7d%':>8}  Holdings{RESET}")
            print(f"  {GREY}{'─'*84}{RESET}")
            for sym, sd in self.stock_market.stocks.items():
                price = sd["price"]
                hist  = list(sd["history"])
                prev  = hist[-2] if len(hist) >= 2 else price
                chg   = (price - prev) / max(prev, 0.01) * 100
                cc    = GREEN if chg >= 0 else RED
                w7    = hist[-7:] if len(hist) >= 7 else hist
                t7    = ((w7[-1] - w7[0]) / max(w7[0], 0.01) * 100) if len(w7) > 1 else 0.0
                tc    = GREEN if t7 >= 0 else RED
                h     = self.stock_holdings.get(sym)
                hold_str = ""
                if h:
                    val  = round(h.shares * price, 1)
                    gain = round(val - h.shares * h.avg_cost, 1)
                    hold_str = (c(f"{h.shares}sh  val:{val:.0f}g  "
                                  f"{gain:+.0f}g", GREEN if gain >= 0 else RED))
                print(f"  {c(sym, CYAN):<14}{sd['name']:<26}{sd['sector']:<14}"
                      f"{c(f'{price:.2f}g', YELLOW):>16}"
                      f"{c(f'{chg:+.2f}%', cc):>16}"
                      f"{c(f'{t7:+.1f}%', tc):>16}  {hold_str}")
            print(f"\n  {CYAN}1{RESET}. Buy shares")
            print(f"  {CYAN}2{RESET}. Sell shares")
            print(f"  {CYAN}3{RESET}. Company details & price chart")
            print(f"  {BOLD}[B]{RESET} Back")
            ch = prompt("Choice: ")
            if ch == "1":
                sym_in = prompt("Symbol to buy (e.g. IRON): ").strip().upper()
                if sym_in not in self.stock_market.stocks:
                    err(f"Unknown symbol '{sym_in}'.")
                    continue
                sd    = self.stock_market.stocks[sym_in]
                price = sd["price"]
                try:
                    shares = int(prompt(f"{sd['name']} @ {price:.2f}g — how many shares? "))
                    if shares <= 0:
                        continue
                    cost = round(shares * price, 2)
                    if cost > self.inventory.gold:
                        err(f"Need {cost:.0f}g, have {self.inventory.gold:.0f}g")
                        continue
                    self.inventory.gold -= cost
                    if sym_in in self.stock_holdings:
                        hold = self.stock_holdings[sym_in]
                        new_avg = (hold.shares * hold.avg_cost + cost) / (hold.shares + shares)
                        hold.shares   += shares
                        hold.avg_cost  = round(new_avg, 2)
                    else:
                        self.stock_holdings[sym_in] = StockHolding(sym_in, shares, round(price, 2))
                    ok(f"Bought {shares}× {sym_in} @ {price:.2f}g  (−{cost:.0f}g)")
                    self._log_event(f"Bought {shares}× {sym_in} @ {price:.2f}g")
                except ValueError:
                    err("Invalid input.")
            elif ch == "2":
                sym_in = prompt("Symbol to sell: ").strip().upper()
                if sym_in not in self.stock_holdings:
                    err("No holding for that symbol.")
                    continue
                hold  = self.stock_holdings[sym_in]
                sd    = self.stock_market.stocks[sym_in]
                price = sd["price"]
                gain_ea = price - hold.avg_cost
                print(f"  {hold.shares} shares @ avg {hold.avg_cost:.2f}g  "
                      f"→ {c(f'{price:.2f}g', YELLOW)} each  "
                      f"| unrealised: {c(f'{gain_ea:+.2f}g/sh', GREEN if gain_ea>=0 else RED)}")
                try:
                    qty = int(prompt(f"Shares to sell (max {hold.shares}): "))
                    if qty <= 0 or qty > hold.shares:
                        err("Invalid quantity.")
                        continue
                    proceeds = round(qty * price, 2)
                    profit   = round((price - hold.avg_cost) * qty, 2)
                    self.inventory.gold += proceeds
                    self.total_profit   += profit
                    hold.shares -= qty
                    if hold.shares <= 0:
                        del self.stock_holdings[sym_in]
                    ok(f"Sold {qty}× {sym_in} @ {price:.2f}g = {c(f'+{proceeds:.0f}g', GREEN)}  "
                       f"P/L: {c(f'{profit:+.0f}g', GREEN if profit >= 0 else RED)}")
                    self._log_event(f"Sold {qty}× {sym_in} @ {price:.2f}g  P/L:{profit:+.0f}g")
                    if profit > 0:
                        self._track_stat("stock_profit", profit)
                    self._check_achievements()
                except ValueError:
                    err("Invalid input.")
            elif ch == "3":
                sym_in = prompt("Symbol (e.g. GLDV): ").strip().upper()
                if sym_in not in self.stock_market.stocks:
                    err(f"Unknown symbol '{sym_in}'.")
                    continue
                sd   = self.stock_market.stocks[sym_in]
                hist = list(sd["history"])
                print(f"\n  {BOLD}{sd['name']}  ({sym_in}){RESET}  —  {sd['sector']}")
                _sd_price = f"{sd['price']:.2f}g"
                print(f"  Price: {c(_sd_price, YELLOW)}  "
                      f"Base: {sd['base_price']:.2f}g  "
                      f"Volatility: {sd['volatility']*100:.1f}%/day")
                print(f"  Linked items: {', '.join(sd['linked_items'])}")
                print(f"  Event impacts: "
                      + "  ".join(f"{k}:{v:+.0%}" for k, v in sd["linked_events"].items()))
                if hist:
                    hi  = max(hist)
                    lo  = min(hist)
                    avg = sum(hist) / len(hist)
                    print(f"  30d  High: {c(f'{hi:.2f}g', GREEN)}  "
                          f"Low: {c(f'{lo:.2f}g', RED)}  "
                          f"Avg: {avg:.2f}g")
                    span = max(hi - lo, 0.01)
                    H    = 5
                    print()
                    for row in range(H, 0, -1):
                        bar = "".join(
                            "█" if int((p - lo) / span * (H - 1)) >= row else " "
                            for p in list(hist)[-40:]
                        )
                        print(f"  {lo + (row-1)/H*span:6.1f}g │{bar}")
                    print(f"         └{'─'*min(40, len(hist))}")
                if sym_in in self.stock_holdings:
                    h = self.stock_holdings[sym_in]
                    _hval = f"{h.shares*sd['price']:.0f}g"
                    print(f"\n  Your holding: {c(str(h.shares)+' shares', CYAN)}"
                          f"  avg cost: {h.avg_cost:.2f}g  "
                          f"current value: {c(_hval, YELLOW)}")
                pause()
            elif ch.upper() in ("4", "B"):
                break

    # ── Fund Management ───────────────────────────────────────────────────────

    def fund_management_menu(self):
        """Accept client capital, invest it, return promised yield at maturity."""
        if LicenseType.FUND_MGR not in self.licenses:
            err("Requires a Fund Manager License.")
            pause()
            return
        if self.reputation < 55:
            err(f"Reputation {self.reputation}/100 — need 55+ for fund management clients.")
            pause()
            return
        while True:
            print(header("FUND MANAGEMENT"))
            active_fc = [fc for fc in self.fund_clients if not fc.withdrawn]
            aum       = sum(fc.capital for fc in active_fc)
            print(f"  AUM: {c(f'{aum:.0f}g', CYAN)}  "
                  f"·  Clients: {c(str(len(active_fc)), CYAN)}  "
                  f"·  Wallet: {c(f'{self.inventory.gold:.0f}g', YELLOW)}\n")
            print(f"  {GREY}You receive client capital now (invest freely)."
                  f"  At maturity you must return capital + promised return.{RESET}")
            print(f"  {GREY}Monthly management fee is auto-collected.{RESET}\n")
            if active_fc:
                print(f"  {BOLD}{'#':<4}{'Client':<22}{'Capital':>9}{'Promised':>10}"
                      f"{'Fee/mo':>8}{'Days Left':>10}{'Fees Paid':>11}{RESET}")
                print(f"  {GREY}{'─'*76}{RESET}")
                today = self._absolute_day()
                for i, fc in enumerate(active_fc, 1):
                    dl     = fc.maturity_day - today
                    dlc    = RED if dl <= 5 else YELLOW if dl <= 15 else GREEN
                    print(f"  {GREY}{i:<4}{RESET}{fc.name:<22}"
                          f"{c(f'{fc.capital:.0f}g', YELLOW):>17}"
                          f"{c(f'{fc.promised_rate*100:.1f}%', CYAN):>18}"
                          f"{c(f'{fc.fee_rate*100:.1f}%', GREY):>16}"
                          f"{c(str(dl)+'d', dlc):>18}"
                          f"{c(f'{fc.fees_collected:.0f}g', GREEN):>19}")
            print(f"\n  {CYAN}1{RESET}. Accept new client")
            print(f"  {CYAN}2{RESET}. Return funds early (15% penalty)")
            print(f"  {BOLD}[B]{RESET} Back")
            ch = prompt("Choice: ")
            if ch == "1":
                pool = self._gen_fund_client_pool(4)
                print(f"\n  {BOLD}{'#':<4}{'Client':<22}{'Capital':>9}"
                      f"{'Duration':>10}{'Promised Return':>17}{'Mgmt Fee/mo':>13}{RESET}")
                print(f"  {GREY}{'─'*77}{RESET}")
                for pi, p in enumerate(pool, 1):
                    _pcap  = f"{p['capital']:.0f}g"
                    _prate = f"{p['promised_rate']*100:.1f}%"
                    _pfee  = f"{p['fee_rate']*100:.1f}%/mo"
                    print(f"  {CYAN}{pi:<4}{RESET}{p['name']:<22}"
                          f"{c(_pcap, YELLOW):>17}"
                          f"{p['duration']:>10}d"
                          f"{c(_prate, CYAN):>17}"
                          f"{c(_pfee, GREEN):>21}")
                try:
                    pidx = int(prompt("Accept client # (0 to cancel): ")) - 1
                    if pidx < 0 or pidx >= len(pool):
                        continue
                    p     = pool[pidx]
                    today = self._absolute_day()
                    owed  = round(p["capital"] * (1 + p["promised_rate"]), 2)
                    print(f"\n  {p['name']} entrusts {p['capital']:.0f}g for {p['duration']}d.")
                    print(f"  You receive the funds now to invest as you see fit.")
                    print(f"  At maturity you must pay: {c(f'{owed:.0f}g', YELLOW)}"
                          f"  (principal + {p['promised_rate']*100:.1f}%)")
                    _pfee2 = f"{p['fee_rate']*100:.1f}%"
                    print(f"  Monthly fee auto-collected: "
                          f"{c(_pfee2, GREEN)} of {p['capital']:.0f}g")
                    confirm = prompt("Accept? (yes/no): ")
                    if confirm.lower() in ("yes", "y"):
                        self.inventory.gold += p["capital"]
                        fc = FundClient(
                            id=self.next_fund_client_id,
                            name=p["name"], capital=p["capital"],
                            promised_rate=p["promised_rate"],
                            start_day=today, duration_days=p["duration"],
                            maturity_day=today + p["duration"],
                            fee_rate=p["fee_rate"],
                        )
                        self.fund_clients.append(fc)
                        self.next_fund_client_id += 1
                        ok(f"Accepted {p['name']}: +{p['capital']:.0f}g received. "
                           f"Maturity in {p['duration']}d.")
                        self._log_event(f"Fund client {p['name']}: {p['capital']:.0f}g / {p['duration']}d")
                except ValueError:
                    err("Invalid input.")
            elif ch == "2":
                if not active_fc:
                    err("No active clients.")
                    continue
                for i, fc in enumerate(active_fc, 1):
                    owed  = round(fc.capital * (1 + fc.promised_rate) * 0.85, 2)
                    print(f"  {CYAN}{i}{RESET}. {fc.name}  "
                          f"Early return: {c(f'{owed:.0f}g', YELLOW)} (−15% penalty)")
                try:
                    ridx = int(prompt("Return to client # (0 to cancel): ")) - 1
                    if ridx < 0 or ridx >= len(active_fc):
                        continue
                    fc   = active_fc[ridx]
                    owed = round(fc.capital * (1 + fc.promised_rate) * 0.85, 2)
                    if self.inventory.gold < owed:
                        err(f"Need {owed:.0f}g.  Have {self.inventory.gold:.0f}g")
                        continue
                    self.inventory.gold -= owed
                    fc.withdrawn = True
                    self.reputation = max(0, self.reputation - 3)
                    ok(f"Early return to {fc.name}: −{owed:.0f}g.  Rep −3.")
                    self._log_event(f"Early fund return to {fc.name}: −{owed:.0f}g")
                except (ValueError, IndexError):
                    err("Invalid input.")
            elif ch.upper() in ("3", "B"):
                break

    # ── Settings ──────────────────────────────────────────────────────────────

    def settings_menu(self):
        """Game settings: difficulty and autosave."""
        DIFF_LABELS = {
            "easy":   ("Easy",   GREEN,  "Costs ×0.70  ·  Sell ×1.10  ·  Events ×0.60  ·  Attacks ×0.50"),
            "normal": ("Normal", CYAN,   "Costs ×1.00  ·  Sell ×1.00  ·  Events ×1.00  ·  Attacks ×1.00"),
            "hard":   ("Hard",   YELLOW, "Costs ×1.35  ·  Sell ×0.90  ·  Events ×1.40  ·  Attacks ×1.50"),
            "brutal": ("Brutal", RED,    "Costs ×1.80  ·  Sell ×0.80  ·  Events ×2.00  ·  Attacks ×2.50"),
        }
        while True:
            s = self.settings
            dlabel, dcol, ddesc = DIFF_LABELS[s.difficulty]
            print(header("SETTINGS"))
            print(f"  Current difficulty : {c(dlabel, dcol)}")
            print(f"  {GREY}{ddesc}{RESET}")
            print(f"  Autosave           : {c('ON  (every 3 days)', GREEN) if s.autosave else c('OFF', GREY)}")
            print()
            print(f"  {CYAN}1{RESET}. Change difficulty")
            print(f"  {CYAN}2{RESET}. Toggle autosave")
            print(f"  {BOLD}[B]{RESET} Back")
            ch = prompt("Choice: ")
            if ch == "1":
                print(f"\n  Difficulties:")
                options = list(DIFF_LABELS.keys())
                for i, key in enumerate(options, 1):
                    lbl, col, desc = DIFF_LABELS[key]
                    marker = c(" ◄", CYAN) if key == s.difficulty else ""
                    print(f"    {CYAN}{i}{RESET}. {c(lbl, col)}{marker}  {GREY}{desc}{RESET}")
                dc = prompt("Choose difficulty (1-4) or cancel: ")
                if dc.strip().lower() == "cancel":
                    continue
                try:
                    di = int(dc.strip()) - 1
                    if 0 <= di < len(options):
                        s.difficulty = options[di]
                        lbl, col, _ = DIFF_LABELS[s.difficulty]
                        s.save()
                        ok(f"Difficulty set to {c(lbl, col)}.")
                    else:
                        err("Invalid choice.")
                except ValueError:
                    err("Invalid input.")
            elif ch == "2":
                s.autosave = not s.autosave
                state = c("ON", GREEN) if s.autosave else c("OFF", GREY)
                s.save()
                ok(f"Autosave turned {state}.")
            elif ch.upper() in ("3", "B"):
                return
            else:
                err("Invalid choice.")

    # ── Combined / Hub Menus ──────────────────────────────────────────────────

    def info_menu(self):
        """Combined News & Events viewer — headlines + active conditions + trade log."""
        # Active events across all markets
        all_active: List[Tuple[str, str]] = []
        for area, market in self.markets.items():
            for ev in market.active_events:
                all_active.append((area.value, ev))

        print(header("NEWS & EVENTS"))

        if all_active:
            print(f"\n  {BOLD}⚑  Active Conditions:{RESET}")
            seen: set = set()
            _hints = {
                "Drought":        c("Grain/fibre scarce — prices elevated.",    YELLOW),
                "Flood":          c("Farm & coastal goods disrupted.",           YELLOW),
                "Bumper Harvest": c("Crop prices lower than usual.",             GREEN),
                "Mine Collapse":  c("Ore, coal & gems in short supply.",         YELLOW),
                "Piracy Surge":   c("Coastal goods hard to come by.",            YELLOW),
                "Trade Boom":     c("All goods in higher demand.",               GREEN),
                "Plague":         c("Medicine & herbs extremely scarce.",        RED),
                "Border War":     c("Steel & ore demand surging.",               YELLOW),
                "Gold Rush":      c("Gold dust prices softening.",               CYAN),
                "Grand Festival": c("Luxury goods in peak demand.",              GREEN),
            }
            for area_name, ev_label in all_active:
                key = (area_name, ev_label)
                if key not in seen:
                    seen.add(key)
                    hint = _hints.get(ev_label, c("Market effects in play.", GREY))
                    print(f"  {c('●', RED)} {c(ev_label, BOLD)} in {c(area_name, CYAN)}  —  {hint}")
        else:
            print(f"\n  {GREY}No major events currently active.{RESET}")

        # Recent headlines
        print(f"\n  {BOLD}Recent Headlines:{RESET}")
        if not self.news_feed:
            print(f"  {GREY}No dispatches yet — travel to generate news.{RESET}")
        else:
            print(f"  {GREY}{'─' * 64}{RESET}")
            for entry in self.news_feed:
                abs_day, area_name, ev_label, headline = entry
                yr  = (abs_day - 1) // 360 + 1
                day = (abs_day - 1) % 360 + 1
                date_str = f"Y{yr}·D{day:<3}"
                tag_col  = YELLOW if ev_label != "Local Rumour" else GREY
                print(f"  {GREY}{date_str}{RESET}  {c(f'[{ev_label}]', tag_col):<28}  {headline}")

        # Recent event & trade log
        print(f"\n  {BOLD}Event History:{RESET}")
        if not self.event_log:
            print(f"  {GREY}No events recorded.{RESET}")
        for entry in list(self.event_log)[:8]:
            print(f"  {GREY}{entry}{RESET}")

        print(f"\n  {BOLD}Recent Trades:{RESET}")
        trades = list(self.trade_log)[:10]
        if not trades:
            print(f"  {GREY}No trades recorded yet.{RESET}")
        for entry in trades:
            print(f"  {GREY}{entry}{RESET}")
        pause()

    def progress_menu(self):
        """Combined Statistics & Achievements hub."""
        while True:
            print(header("PROGRESS"))
            ach_count = len(self.achievements)
            print(f"\n  {BOLD}[1]{RESET} Statistics & Charts")
            print(f"  {BOLD}[2]{RESET} Achievements  "
                  f"{c(f'{ach_count}/{len(ACHIEVEMENTS)} unlocked', CYAN)}")
            print(f"\n  {BOLD}[B]{RESET} Back  {GREY}(or Enter){RESET}")
            ch = prompt("").strip().upper()
            if ch == "1":
                self.statistics_menu()
            elif ch == "2":
                self.achievements_menu()
            elif ch in ("B", ""):
                break

    def reputation_menu(self):
        """Combined Social & Community hub — social influence + licenses."""
        while True:
            print(header("REPUTATION & COMMUNITY"))
            print(f"\n  Rep: {self._rep_label()}  "
                  f"{GREY}·{RESET}  Heat: {c(str(self.heat), RED if self.heat > 50 else YELLOW) if self.heat > 0 else c('0', GREY)}"
                  f"  {GREY}·{RESET}  Licenses: {c(f'{len(self.licenses)}/5', CYAN)}")
            print(f"\n  {BOLD}[1]{RESET} Social & Influence   "
                  f"{GREY}· Donate · Campaign · Slander{RESET}")
            print(f"  {BOLD}[2]{RESET} Permits & Licenses   "
                  f"{GREY}[{len(self.licenses)}/5 held]{RESET}")
            print(f"\n  {BOLD}[B]{RESET} Back  {GREY}(or Enter){RESET}")
            ch = prompt("").strip().upper()
            if ch == "1":
                self.social_menu()
            elif ch == "2":
                self.licenses_menu()
            elif ch in ("B", ""):
                break

    # ── Main Loop ─────────────────────────────────────────────────────────────

    def play(self):
        print(f"""{BOLD}{CYAN}
╔══════════════════════════════════════════════════════════╗
║          MERCHANT TYCOON  ─  EXPANDED EDITION            ║
║  Trade · Build · Scheme · Profit                         ║
╚══════════════════════════════════════════════════════════╝{RESET}""")

        _new_game = False
        if os.path.exists(self.SAVE_FILE):
            ch = prompt("Save file found. Load game? (yes/no): ")
            if ch.lower() in ("yes", "y"):
                if self.load_game():
                    ok(f"Welcome back, {self.player_name}!")
                else:
                    self.player_name = prompt("Enter your merchant name: ") or "Merchant"
                    _new_game = True
            else:
                self.player_name = prompt("Enter your merchant name: ") or "Merchant"
                _new_game = True
        else:
            self.player_name = prompt("Enter your merchant name: ") or "Merchant"
            _new_game = True

        if _new_game:
            print(f"\n  {BOLD}Welcome, {self.player_name}!{RESET}  You start with "
                  f"{c('750 gold', CYAN)} at {c('Capital City', CYAN)}.")
            tut_ch = prompt("  Would you like a quick tutorial? (yes/no): ").strip().lower()
            if tut_ch in ("yes", "y"):
                self._run_tutorial()
            else:
                print(f"""
  {BOLD}QUICK START:{RESET}
  {GREY}• [T] Trade — buy low in producing areas, sell high at the City.{RESET}
  {GREY}• [V] Travel — move between areas to find better prices.{RESET}
  {GREY}• [C] Contracts — reliable income; needs Trade Contract Seal (rep 15+).{RESET}
  {GREY}• [N] News · [M] Market Info — track world events & prices.{RESET}
  {GREY}• [?] Help — full guides available any time in-game.{RESET}
""")
                pause()

        while self.running:
            self._display_achievement_queue()
            self.display_status()
            self.display_main_menu()

            ch = prompt("").strip().upper()

            if   ch == "T":  self.trade_menu()
            elif ch == "V":  self.travel_menu()
            elif ch == "I":  self.inventory.display(self._max_carry_weight())
            elif ch == "W":  self._wait_days_menu()
            elif ch == "B":  self.businesses_menu()
            elif ch == "F":  self.banking_menu()
            elif ch == "C":  self.contracts_menu()
            elif ch == "S":  self.skills_menu()
            elif ch == "X":  self.smuggling_menu()
            elif ch == "M":  self.market_info_menu()
            elif ch == "N":  self.info_menu()
            elif ch == "P":  self.progress_menu()
            elif ch == "R":  self.reputation_menu()
            elif ch == "SAVE":
                self.save_game()
            elif ch == "O":
                self.settings_menu()
            elif ch == "Q":
                ch2 = prompt("Save before quitting? (yes/no): ")
                if ch2.lower() in ("yes", "y"):
                    self.save_game()
                print(f"\n  {BOLD}Thanks for playing, {self.player_name}!{RESET}")
                print(f"  Final Net Worth: {c(f'{self._net_worth():.2f}g', CYAN)}")
                self.running = False
            elif ch in ("?", "HELP"):
                self.help_menu()
                self._track_stat("help_presses")
                self._check_achievements()
            else:
                err("Invalid — use a letter key shown above, or ? for help.")
                continue

            # Spend 1 activity slot after substantial non-trade actions
            # (trade/travel/wait handle their own time internally via _use_time)
            if ch in ("B", "F", "C", "S", "X", "R"):
                self._use_time(1)



# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    game = Game()
    game.play()