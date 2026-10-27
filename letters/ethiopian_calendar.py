"""
Ethiopian Calendar (ዓውደ አውራኅ / Ge'ez Calendar) Conversion and Formatting Utilities.

Provides 100% mathematically exact bidirectional conversion between the Proleptic
Gregorian Calendar and the Ethiopian Calendar with zero external dependencies.

Calendar Structure:
- 12 months of 30 days each (Meskerem through Nehase)
- 1 intercalary month: Pagume (5 days in common years, 6 days in leap years)
- Ethiopian Leap Year Rule: An Ethiopian year Y is a leap year if Y % 4 == 3.
- Era: Incarnation Era (ዓመተ ምሕረት / A.M. / E.C.), ~7-8 years behind Gregorian (G.C.).
"""

import re
from datetime import date, datetime
from typing import Optional, Tuple, Union


# ---------------------------------------------------------------------------
# Month Constants & Names
# ---------------------------------------------------------------------------
ETHIOPIAN_MONTHS_EN = [
    "Meskerem",
    "Tikimt",
    "Hidar",
    "Tahsas",
    "Tir",
    "Yakatit",
    "Magabit",
    "Miyazya",
    "Ginbot",
    "Sene",
    "Hamle",
    "Nehase",
    "Pagume",
]

ETHIOPIAN_MONTHS_AM = [
    "መስከረም",
    "ጥቅምት",
    "ኅዳር",
    "ታኅሣሥ",
    "ጥር",
    "የካቲት",
    "መጋቢት",
    "ሚያዝያ",
    "ግንቦት",
    "ሰኔ",
    "ሐምሌ",
    "ነሐሴ",
    "ጳጉሜ",
]

# Mapping dictionary for fuzzy/alias parsing
ETHIOPIAN_MONTH_MAP = {}
for idx, name in enumerate(ETHIOPIAN_MONTHS_EN, 1):
    ETHIOPIAN_MONTH_MAP[name.lower()] = idx
    ETHIOPIAN_MONTH_MAP[name[:3].lower()] = idx
for idx, name in enumerate(ETHIOPIAN_MONTHS_AM, 1):
    ETHIOPIAN_MONTH_MAP[name] = idx

# Common English transliteration variations
ETHIOPIAN_MONTH_MAP.update({
    "maskaram": 1, "meskerem": 1, "mesk": 1,
    "teqemt": 2, "tikimt": 2, "tik": 2, "tekemt": 2,
    "hedar": 3, "hidar": 3, "hid": 3, "hed": 3,
    "tahasas": 4, "tahsas": 4, "tah": 4,
    "ter": 5, "tir": 5,
    "yekatit": 6, "yakatit": 6, "yek": 6, "yak": 6,
    "megabit": 7, "magabit": 7, "meg": 7, "mag": 7,
    "miyazya": 8, "miazia": 8, "miy": 8, "mia": 8,
    "genbot": 9, "ginbot": 9, "gen": 9, "gin": 9,
    "sene": 10, "sen": 10,
    "hamle": 11, "ham": 11,
    "nehase": 12, "nahase": 12, "neh": 12, "nah": 12,
    "pagume": 13, "pagumen": 13, "pagumē": 13, "pag": 13, "puagme": 13,
})

# Offset constant: Julian day ordinal difference to Epoch (Meskerem 1, 1 EC)
_ETHIOPIC_EPOCH_ORDINAL = 2796


# ---------------------------------------------------------------------------
# Core Conversion Functions
# ---------------------------------------------------------------------------
def is_ethiopian_leap_year(year: int) -> bool:
    """Return True if Ethiopian year is a leap year (Pagume has 6 days)."""
    return (year % 4) == 3


def days_in_ethiopian_month(year: int, month: int) -> int:
    """Return the number of days in a given Ethiopian year and month."""
    if 1 <= month <= 12:
        return 30
    elif month == 13:
        return 6 if is_ethiopian_leap_year(year) else 5
    raise ValueError(f"Invalid Ethiopian month: {month}. Must be between 1 and 13.")


def gregorian_to_ethiopian(greg_date: Union[date, datetime]) -> Tuple[int, int, int]:
    """
    Convert a Gregorian date (G.C.) to Ethiopian date (E.C.).
    Returns (year, month, day).
    """
    if isinstance(greg_date, datetime):
        greg_date = greg_date.date()
    elif not isinstance(greg_date, date):
        raise TypeError(f"Expected date or datetime object, got {type(greg_date)}")

    days = greg_date.toordinal() - _ETHIOPIC_EPOCH_ORDINAL
    if days < 0:
        raise ValueError("Dates prior to Ethiopian Era Epoch (0008-08-27 GC) are not supported.")

    cycle = days // 1461
    rem = days % 1461

    if rem < 365:
        year_in_cycle = 1
        day_in_year = rem
    elif rem < 730:
        year_in_cycle = 2
        day_in_year = rem - 365
    elif rem < 1096:
        year_in_cycle = 3
        day_in_year = rem - 730
    else:
        year_in_cycle = 4
        day_in_year = rem - 1096

    eth_year = 4 * cycle + year_in_cycle
    eth_month = (day_in_year // 30) + 1
    eth_day = (day_in_year % 30) + 1

    return eth_year, eth_month, eth_day


def ethiopian_to_gregorian(eth_year: int, eth_month: int, eth_day: int) -> date:
    """
    Convert an Ethiopian date (E.C.) to a Gregorian date (G.C.).
    Validates month and day bounds.
    """
    if eth_year < 1:
        raise ValueError("Ethiopian year must be >= 1.")
    if not (1 <= eth_month <= 13):
        raise ValueError(f"Invalid Ethiopian month: {eth_month}. Must be 1-13.")
    
    max_days = days_in_ethiopian_month(eth_year, eth_month)
    if not (1 <= eth_day <= max_days):
        raise ValueError(f"Invalid day {eth_day} for Ethiopian month {eth_month} in year {eth_year} (max is {max_days}).")

    days = (
        _ETHIOPIC_EPOCH_ORDINAL
        + (eth_year - 1) * 365
        + (eth_year // 4)
        + (eth_month - 1) * 30
        + (eth_day - 1)
    )
    return date.fromordinal(days)


# ---------------------------------------------------------------------------
# Formatting Functions
# ---------------------------------------------------------------------------
def format_ethiopian_date(
    greg_date: Optional[Union[date, datetime]],
    fmt: str = "full",
    amharic: bool = False
) -> str:
    """
    Format a Gregorian date into an Ethiopian date string.
    
    Format options:
    - 'full': '15 Nehase 2018 E.C.' or 'ነሐሴ 15, 2018 ዓ.ም.'
    - 'short': '15/12/2018 E.C.'
    - 'iso': '2018-12-15'
    - 'month_year': 'Nehase 2018'
    - 'dual': '21 Aug 2026 (15 Nehase 2018 E.C.)'
    """
    if not greg_date:
        return ""

    if isinstance(greg_date, datetime):
        greg_date = greg_date.date()

    ey, em, ed = gregorian_to_ethiopian(greg_date)
    month_name_en = ETHIOPIAN_MONTHS_EN[em - 1]
    month_name_am = ETHIOPIAN_MONTHS_AM[em - 1]

    if fmt == "iso":
        return f"{ey:04d}-{em:02d}-{ed:02d}"
    elif fmt == "short":
        return f"{ed:02d}/{em:02d}/{ey:04d} E.C."
    elif fmt == "month_year":
        return f"{month_name_am} {ey}" if amharic else f"{month_name_en} {ey}"
    elif fmt == "dual":
        greg_str = greg_date.strftime("%d %b %Y")
        if amharic:
            return f"{greg_str} ({month_name_am} {ed}, {ey} ዓ.ም.)"
        return f"{greg_str} ({ed} {month_name_en} {ey} E.C.)"
    else:  # full
        if amharic:
            return f"{month_name_am} {ed}, {ey} ዓ.ም."
        return f"{ed} {month_name_en} {ey} E.C."


# ---------------------------------------------------------------------------
# Parsing Function (Flexible input to Gregorian date)
# ---------------------------------------------------------------------------
def parse_ethiopian_date(date_str: str) -> Optional[date]:
    """
    Parse a user-entered Ethiopian date string into a Gregorian `date` object.
    
    Supported formats:
    - ISO format: '2018-12-15', '2018/12/15', '2018.12.15'
    - Slash/dash/dot DD/MM/YYYY: '15/12/2018', '15-12-2018'
    - Word format: '15 Nehase 2018', '15 Nehase 2018 E.C.', 'Nehase 15, 2018'
    - Amharic format: 'ነሐሴ 15, 2018', 'ነሐሴ 15 2018 ዓ.ም.'
    """
    if not date_str:
        return None

    clean_str = date_str.strip().replace("E.C.", "").replace("EC", "").replace("ዓ.ም.", "").replace("ዓ/ም", "").replace("ዓም", "").strip()

    # 1. Check YYYY-MM-DD or YYYY/MM/DD
    iso_match = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", clean_str)
    if iso_match:
        y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        return ethiopian_to_gregorian(y, m, d)

    # 2. Check DD/MM/YYYY or DD-MM-YYYY
    dmy_match = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", clean_str)
    if dmy_match:
        d, m, y = int(dmy_match.group(1)), int(dmy_match.group(2)), int(dmy_match.group(3))
        return ethiopian_to_gregorian(y, m, d)

    # 3. Check text format: '15 Nehase 2018' or '15/Nehase/2018' or 'ነሐሴ 15 2018'
    # Match: Day Month Year or Month Day Year
    tokens = re.split(r"[\s,/-]+", clean_str)
    tokens = [t for t in tokens if t]

    if len(tokens) == 3:
        # Check if Month Day Year (e.g. ['Nehase', '15', '2018'] or ['ነሐሴ', '15', '2018'])
        if tokens[0].lower() in ETHIOPIAN_MONTH_MAP:
            m = ETHIOPIAN_MONTH_MAP[tokens[0].lower()]
            d = int(tokens[1])
            y = int(tokens[2])
            return ethiopian_to_gregorian(y, m, d)
        elif tokens[0] in ETHIOPIAN_MONTH_MAP:
            m = ETHIOPIAN_MONTH_MAP[tokens[0]]
            d = int(tokens[1])
            y = int(tokens[2])
            return ethiopian_to_gregorian(y, m, d)

        # Check if Day Month Year (e.g. ['15', 'Nehase', '2018'] or ['15', 'ነሐሴ', '2018'])
        if tokens[1].lower() in ETHIOPIAN_MONTH_MAP:
            d = int(tokens[0])
            m = ETHIOPIAN_MONTH_MAP[tokens[1].lower()]
            y = int(tokens[2])
            return ethiopian_to_gregorian(y, m, d)
        elif tokens[1] in ETHIOPIAN_MONTH_MAP:
            d = int(tokens[0])
            m = ETHIOPIAN_MONTH_MAP[tokens[1]]
            y = int(tokens[2])
            return ethiopian_to_gregorian(y, m, d)

    return None


# ---------------------------------------------------------------------------
# Range Queries Helper (For filtering & reports)
# ---------------------------------------------------------------------------
def ethiopian_month_gregorian_range(year: int, month: int) -> Tuple[date, date]:
    """Return the (start_greg_date, end_greg_date) spanning an Ethiopian month."""
    start_date = ethiopian_to_gregorian(year, month, 1)
    end_day = days_in_ethiopian_month(year, month)
    end_date = ethiopian_to_gregorian(year, month, end_day)
    return start_date, end_date


def ethiopian_year_gregorian_range(year: int) -> Tuple[date, date]:
    """Return the (start_greg_date, end_greg_date) spanning an Ethiopian year."""
    start_date = ethiopian_to_gregorian(year, 1, 1)
    end_day = 6 if is_ethiopian_leap_year(year) else 5
    end_date = ethiopian_to_gregorian(year, 13, end_day)
    return start_date, end_date
