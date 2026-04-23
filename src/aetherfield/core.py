import math
from dataclasses import dataclass
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple, List
from pathlib import Path
import os
try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*_args, **_kwargs):
        return False
from functools import lru_cache
# --- aetherfield: is_up utilities -------------------------------------------
try:
    from .iplocal import get_ip_data  # type: ignore
except Exception:
    def get_ip_data():
        return '0,0', 'UTC', 0


# Mean obliquity (degrees). You can make this tunable from your calibration file if you want.
OBLIQUITY_DEG = 23.43928

bodies = ['sun','moon','mercury','venus','mars','jupiter','saturn']

# Mean regression of lunar nodes (~18.6 year cycle)
DRACONIC_RATE_DEG_PER_DAY = -360.0 / (18.612958 * 365.2422)

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo",
    "Virgo", "Libra", "Scorpio", "Sagittarius",
    "Capricorn", "Aquarius", "Pisces"
]
data = None

AGE_LENGTH = 2147.67

ANCHOR_YEAR = 1
ANCHOR_SIGN = "Pisces"

CACHE_PATH = os.path.join(os.path.expanduser("~"), ".cache", "aetherfield", "aetherfield_calibration.json")
REMOTE_URL = "https://pythoness.duckdns.org/v1/aether/calibration/file"

load_dotenv()

def _wrap_deg(x: float) -> float:
    return x % 360.0

def _angdiff_deg(a: float, b: float) -> float:
    """Signed smallest difference a-b in (-180, +180]."""
    return ((a - b + 180.0) % 360.0) - 180.0


def _canonical_body(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    key = name.strip().lower()
    return DRACONIC_ALIASES.get(key, key)


def _import_skyfieldcomm():
    """Best-effort import for pythoness.skyfieldcomm without hard dependency."""
    for mod_name in (
        "pythoness.skyfieldcomm",
        "Pythoness.skyfieldcomm",
        "skyfieldcomm",
    ):
        try:
            return __import__(mod_name, fromlist=("dummy",))
        except Exception:
            continue
    return None


def _draconic_base_longitudes(dt: datetime) -> Tuple[float, float]:
    """Compute ascending/descending node longitudes at dt."""
    if SKYFIELD_OK:
        module = _import_skyfieldcomm()
        if module is not None:
            find_node_crossing = getattr(module, "find_node_crossing", None)
            adjust_node_position = getattr(module, "adjust_node_position", None)
            if callable(find_node_crossing) and callable(adjust_node_position):
                try:
                    anchor_time, anchor_lon = find_node_crossing(initial_time=dt, direction='backward')
                    asc = float(adjust_node_position(anchor_time, anchor_lon, dt))
                    asc %= 360.0
                    desc = (asc + 180.0) % 360.0
                    return asc, desc
                except Exception:
                    pass
    delta_days = (dt - DRACONIC_ANCHOR_EPOCH).total_seconds() / 86400.0
    asc = (DRACONIC_ANCHOR_ASC_LON + DRACONIC_RATE_DEG_PER_DAY * delta_days) % 360.0
    desc = (asc + 180.0) % 360.0
    return asc, desc


def _draconic_cache_key(dt: datetime) -> Tuple[int, int, int]:
    dt_utc = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    dt_utc = dt_utc.astimezone(UTC)
    base = dt_utc.replace(minute=0, second=0, microsecond=0)
    return base.year, base.timetuple().tm_yday, base.hour


@lru_cache(maxsize=128)
def _draconic_longitudes_cached(year: int, yearday: int, hour: int) -> Tuple[float, float]:
    base = datetime(year, 1, 1, tzinfo=UTC) + timedelta(days=yearday - 1, hours=hour)
    return _draconic_base_longitudes(base)


def _get_draconic_longitudes(dt: Any) -> Dict[str, float]:
    dt_utc = _ensure_utc_datetime(_as_datetime(dt))
    floor_dt = dt_utc.replace(minute=0, second=0, microsecond=0)
    cache_key = _draconic_cache_key(dt_utc)
    asc_base, desc_base = _draconic_longitudes_cached(*cache_key)
    delta_days = (dt_utc - floor_dt).total_seconds() / 86400.0
    drift = DRACONIC_RATE_DEG_PER_DAY * delta_days
    asc = (asc_base + drift) % 360.0
    desc = (desc_base + drift) % 360.0
    return {
        'ascending_node': asc,
        'descending_node': desc,
    }

def ecliptic_to_equatorial(lon_deg: float, lat_deg: float = 0.0, eps_deg: float = OBLIQUITY_DEG):
    """
    Convert ecliptic (λ, β) -> equatorial (RA, Dec), all degrees.
    Using β≈0 for planets gives a good first pass; Moon will be rough but serviceable.
    """
    lam = math.radians(_wrap_deg(lon_deg))
    beta = math.radians(lat_deg)
    eps  = math.radians(eps_deg)

    sin_dec = math.sin(beta)*math.cos(eps) + math.cos(beta)*math.sin(eps)*math.sin(lam)
    dec = math.degrees(math.asin(sin_dec))

    y = math.sin(lam)*math.cos(eps) - math.tan(beta)*math.sin(eps)
    x = math.cos(lam)
    ra = math.degrees(math.atan2(y, x)) % 360.0
    return ra, dec

def _julian_date(dt):
    d = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    d = d.astimezone(timezone.utc)
    y, m = d.year, d.month
    day = d.day + (d.hour + (d.minute + d.second/60.0)/60.0)/24.0
    if m <= 2:
        y -= 1; m += 12
    A = y // 100
    B = 2 - A + (A // 5)
    return int(365.25*(y + 4716)) + int(30.6001*(m + 1)) + day + B - 1524.5

def _gmst_deg(dt):
    jd = _julian_date(dt)
    T = (jd - 2451545.0)/36525.0
    gmst = 280.46061837 + 360.98564736629*(jd-2451545.0) + 0.000387933*T*T - (T*T*T)/38710000.0
    return gmst % 360.0

def _lst_deg(dt, lon_deg):
    return (_gmst_deg(dt) + lon_deg) % 360.0



try:
    import pytz
except Exception:
    pytz = None  # type: ignore[assignment]
    UTC = timezone.utc
else:
    UTC = pytz.utc
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

try:
    from skyfield.api import load
    from skyfield.framelib import ecliptic_frame
    SKYFIELD_OK = True
except Exception:
    SKYFIELD_OK = False



def get_age_sign(year: int) -> str:


    offset_years = year - ANCHOR_YEAR
    age_index_offset = offset_years // AGE_LENGTH

    anchor_index = SIGNS.index(ANCHOR_SIGN)
    sign_index = (anchor_index + age_index_offset) % 12

    return SIGNS[int(sign_index)]

def rotated_zodiac(start_sign: str) -> list[str]:
    i = SIGNS.index(start_sign)
    return SIGNS[i:] + SIGNS[:i]

def get_zodiac_by_longitude_dt(longitude: float, dt: datetime) -> str:
    dt = _as_datetime(dt)
    year = dt.year
    age_sign = get_age_sign(year)
    signs = rotated_zodiac(age_sign)

    i = int(longitude // 30) % 12
    return signs[i]

try:
    # Reuse existing helper for sign segmentation if present
    from skyfieldcomm import get_zodiac_by_longitude
except Exception:
    def get_zodiac_by_longitude(longitude: float) -> str:
        signs = [
            "Aries", "Taurus", "Gemini", "Cancer", "Leo",
            "Virgo", "Libra", "Scorpio", "Sagittarius",
            "Capricorn", "Aquarius", "Pisces"
        ]
        i = int(longitude // 30) % 12
        return signs[i]


DE421_START = datetime(1951, 1, 2, tzinfo=UTC)
DE421_END = datetime(2049, 12, 30, 23, 59, 58, tzinfo=UTC)
DE440_START = datetime(1551, 1, 2, tzinfo=UTC)
DE440_END = datetime(2649, 12, 30, 23, 59, 58, tzinfo=UTC)
# DE441 spans beyond Python's datetime range; clamp to supported bounds.
DE441_START = datetime(1, 1, 2, tzinfo=UTC)
DE441_END = datetime(9999, 12, 30, 23, 59, 58, tzinfo=UTC)


@dataclass(frozen=True)
class EphemerisSpec:
    name: str
    filename: str
    start: datetime
    end: datetime
    true_start_year: int
    true_end_year: int

EPHEMERIS_SPECS: Dict[str, EphemerisSpec] = {
    "de421": EphemerisSpec(
        name="de421",
        filename="de421.bsp",
        start=DE421_START,
        end=DE421_END,
        true_start_year=1951,
        true_end_year=2049,
    ),
    "de440": EphemerisSpec(
        name="de440",
        filename="de440.bsp",
        start=DE440_START,
        end=DE440_END,
        true_start_year=1551,
        true_end_year=2649,
    ),
    "de441": EphemerisSpec(
        name="de441",
        filename="de441.bsp",
        start=DE441_START,
        end=DE441_END,
        true_start_year=-13201,
        true_end_year=17189,
    ),
}
EPHEMERIS_PREFERENCE = ("de441", "de440", "de421")


def _ephemeris_search_paths() -> List[Path]:
    here = Path(__file__).resolve()
    paths = [Path.cwd(), here.parent]
    paths.extend(here.parents)
    seen = set()
    ordered: List[Path] = []
    for p in paths:
        try:
            resolved = p.resolve()
        except Exception:
            resolved = p
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(resolved)
    return ordered


def _resolve_ephemeris_path(name_or_path: str) -> Optional[Path]:
    if not name_or_path:
        return None
    candidate = Path(name_or_path)
    if candidate.is_file():
        return candidate.resolve()
    filename = name_or_path if name_or_path.lower().endswith(".bsp") else f"{name_or_path}.bsp"
    for base in _ephemeris_search_paths():
        path = base / filename
        if path.is_file():
            return path.resolve()
    return None


def _select_calibration_ephemeris() -> Tuple[EphemerisSpec, Optional[Path]]:
    requested = os.getenv("AETHER_CAL_EPHEMERIS", "").strip().lower()
    if requested:
        spec = EPHEMERIS_SPECS.get(requested)
        if spec:
            return spec, _resolve_ephemeris_path(spec.filename) or _resolve_ephemeris_path(requested)
        path = _resolve_ephemeris_path(requested)
        if path:
            name = path.stem.lower()
            return EPHEMERIS_SPECS.get(name, EPHEMERIS_SPECS["de421"]), path
        return EPHEMERIS_SPECS.get(requested, EPHEMERIS_SPECS["de421"]), None
    for key in EPHEMERIS_PREFERENCE:
        spec = EPHEMERIS_SPECS[key]
        path = _resolve_ephemeris_path(spec.filename)
        if path:
            return spec, path
    return EPHEMERIS_SPECS["de421"], _resolve_ephemeris_path("de421.bsp")

def resolve_ephemeris(year: int):
    if 1951 <= year <= 2049:
        return "de421"
    elif 1551 <= year <= 2649:
        return "de440"
    else:
        return "de441"

_CAL_EPHEMERIS_SPEC, _CAL_EPHEMERIS_PATH = _select_calibration_ephemeris()
EPHEMERIS_NAME = _CAL_EPHEMERIS_SPEC.name
EPHEMERIS_PATH = str(_CAL_EPHEMERIS_PATH) if _CAL_EPHEMERIS_PATH else _CAL_EPHEMERIS_SPEC.filename
EPHEMERIS_START = _CAL_EPHEMERIS_SPEC.start
EPHEMERIS_END = _CAL_EPHEMERIS_SPEC.end
EPHEMERIS_TRUE_START_YEAR = _CAL_EPHEMERIS_SPEC.true_start_year
EPHEMERIS_TRUE_END_YEAR = _CAL_EPHEMERIS_SPEC.true_end_year


# Mean sidereal/orbital motion in degrees per day (approximate)
# Sources: standard planetary orbital periods; Moon uses ~27.321661 d (sidereal)
MEAN_DEG_PER_DAY: Dict[str, float] = {
    "sun": 360.0 / 365.2422,         # ~0.985647
    "moon": 360.0 / 27.321661,       # ~13.176358
    "mercury": 360.0 / 87.9691,      # ~4.092334
    "venus": 360.0 / 224.701,        # ~1.602130
    "mars": 360.0 / 686.980,         # ~0.524039
    "jupiter": 360.0 / 4332.589,     # ~0.083129
    "saturn": 360.0 / 10759.22,      # ~0.033497
    "uranus": 360.0 / 30688.5,       # ~0.011749
    "neptune": 360.0 / 60182.0,      # ~0.005981
    "pluto": 360.0 / 90560.0,        # ~0.003977
    "ascending_node": DRACONIC_RATE_DEG_PER_DAY,
    "descending_node": DRACONIC_RATE_DEG_PER_DAY,
}

DRACONIC_BODY_NAMES = ("ascending_node", "descending_node")
DRACONIC_ALIASES = {
    "ascending_node": "ascending_node",
    "ascending": "ascending_node",
    "north_node": "ascending_node",
    "rahu": "ascending_node",
    "dragon_head": "ascending_node",
    "descending_node": "descending_node",
    "descending": "descending_node",
    "south_node": "descending_node",
    "ketu": "descending_node",
    "dragon_tail": "descending_node",
}
ALIGNMENT_BODIES: Tuple[str, ...] = (
    "sun", "moon", "mercury", "venus", "mars",
    "jupiter", "saturn", "uranus", "neptune", "pluto",
    "ascending_node", "descending_node",
)

PLANET_ALIGNMENT_BODIES: Tuple[str, ...] = tuple(b for b in ALIGNMENT_BODIES if b not in DRACONIC_BODY_NAMES)

DRACONIC_ANCHOR_EPOCH = datetime(2000, 1, 1, 12, tzinfo=UTC)
DRACONIC_ANCHOR_ASC_LON = 125.044555  # Mean ascending node longitude @ J2000

planet_eph = {
    'jupiter': 5,
    'saturn': 6,
    'uranus': 7,
    'neptune': 8,
    'pluto': 9
}

PHASE_NAMES = [
    "New", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full", "Waning Gibbous", "Last Quarter", "Waning Crescent"
]

def _resolve_cal_path(path: str) -> Path:
    if path == 'AetherField':
        return path
    p = Path(path)
    if p.is_file():
        return p
    # also try alongside this file
    here = Path(__file__).resolve().parent
    p2 = here.parent.parent.parent / path  # repo root relative
    return p2 if p2.is_file() else Path(path)


def _ensure_utc_datetime(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _is_skyfield_time(value: Any) -> bool:
    return bool(
        hasattr(value, "tt")
        and hasattr(value, "ts")
        and callable(getattr(value, "utc_datetime", None))
    )


def is_skyfield_time(value: Any) -> bool:
    """Public helper to detect Skyfield Time objects."""
    return _is_skyfield_time(value)


def make_skyfield_time(
    ts,
    *,
    year: int,
    month: int = 1,
    day: int = 1,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
):
    """
    Create a Skyfield Time, supporting BCE via astronomical year numbering.
    """
    return ts.utc(year, month, day, hour, minute, second)


def _get_timescale():
    if not SKYFIELD_OK:
        raise RuntimeError("Skyfield not available for time conversions")
    global _SF_TS
    try:
        _SF_TS
    except NameError:
        _SF_TS = None  # type: ignore[var-annotated]
    if _SF_TS is None:
        _SF_TS = load.timescale()
    return _SF_TS


def _as_skyfield_time(ts, time_value: Any):
    if _is_skyfield_time(time_value):
        return time_value
    if isinstance(time_value, datetime):
        dt = time_value
    else:
        dt = _as_datetime(time_value)
    dt = _ensure_utc_datetime(dt)
    return ts.from_datetime(dt)


def _in_ephemeris_window(dt: Any) -> bool:
    if _is_skyfield_time(dt):
        if not SKYFIELD_OK:
            return False
        ts = getattr(dt, "ts", None) or _get_timescale()
        dt_tt = float(dt.tt)
        true_start = EPHEMERIS_TRUE_START_YEAR
        true_end = EPHEMERIS_TRUE_END_YEAR
        if true_start is not None and true_end is not None:
            if true_start < 1 or true_end > 9999:
                start_t = make_skyfield_time(ts, year=true_start, month=1, day=1)
                end_t = make_skyfield_time(ts, year=true_end, month=12, day=31, hour=23, minute=59, second=59)
                return float(start_t.tt) <= dt_tt <= float(end_t.tt)
        start_tt = float(ts.from_datetime(_ensure_utc_datetime(EPHEMERIS_START)).tt)
        end_tt = float(ts.from_datetime(_ensure_utc_datetime(EPHEMERIS_END)).tt)
        return start_tt <= dt_tt <= end_tt
    dt_utc = _ensure_utc_datetime(_as_datetime(dt))
    return EPHEMERIS_START <= dt_utc <= EPHEMERIS_END


def _in_de421(dt: Any) -> bool:
    return _in_ephemeris_window(dt)


def in_ephemeris_window(dt: Any) -> bool:
    """Public wrapper for ephemeris window checks."""
    return _in_ephemeris_window(dt)


def _as_datetime(dt_or_mt: Any) -> datetime:
    """Accept a datetime, Skyfield Time, or MoonTime-like object with to_datetime()."""
    if _is_skyfield_time(dt_or_mt):
        try:
            dt = dt_or_mt.utc_datetime()
        except Exception as exc:
            raise ValueError(
                "Skyfield Time is outside the supported datetime range"
            ) from exc
        return _ensure_utc_datetime(dt)
    if isinstance(dt_or_mt, datetime):
        return dt_or_mt
    to_dt = getattr(dt_or_mt, 'to_datetime', None)
    if callable(to_dt):
        dt = to_dt()
        if not isinstance(dt, datetime):
            raise TypeError("to_datetime() did not return a datetime")
        return dt
    # Non datetime, Moontime, or Skyfield object detected, falling back
    return datetime.now(UTC)
    #raise TypeError(
    #    "Expected datetime, Skyfield Time, or MoonTime-like object with to_datetime()"
    #)


def _body_key(eph, name: str):
    """Find a usable ephemeris key for a body name."""
    candidates = [
        name,
        name.lower(),
        name.capitalize(),
        f"{name} barycenter",
        f"{name.capitalize()} BARYCENTER",
    ]
    for c in candidates:
        if c in eph:
            return eph[c]
    # Fallback for numbered outer planets (de421 indexes)
    idx = {
        "jupiter": 5,
        "saturn": 6,
        "uranus": 7,
        "neptune": 8,
        "pluto": 9,
    }.get(name)
    if idx is not None:
        try:
            return eph[idx]
        except Exception:
            pass
    raise KeyError(f"Body key not found for: {name}")


def get_body_key(eph, name: str):
    """Public wrapper for ephemeris body key resolution."""
    return _body_key(eph, name)


def _get_ephemeris():
    if not SKYFIELD_OK:
        raise RuntimeError("Skyfield not available for anchor computation")
    global _SF_EPH, _SF_TS, _SF_EPH_PATH
    try:
        _SF_EPH
    except NameError:
        _SF_EPH = None  # type: ignore[var-annotated]
        _SF_TS = None   # type: ignore[var-annotated]
        _SF_EPH_PATH = None  # type: ignore[var-annotated]
    if _SF_EPH is None or _SF_TS is None or _SF_EPH_PATH != EPHEMERIS_PATH:
        _SF_EPH = load(EPHEMERIS_PATH)
        _SF_TS = _get_timescale()
        _SF_EPH_PATH = EPHEMERIS_PATH
    return _SF_EPH, _SF_TS


def _ecliptic_longitude_skyfield(dt: Any, body: str) -> float:
    if not SKYFIELD_OK:
        raise RuntimeError("Skyfield not available for anchor computation")     
    eph, ts = _get_ephemeris()
    earth = eph['earth']
    b = _body_key(eph, body)
    t = _as_skyfield_time(ts, dt)
    app = earth.at(t).observe(b).apparent()
    lat, lon, dist = app.frame_latlon(ecliptic_frame)
    return float(lon.degrees) % 360.0

def fetch_celestial_data(time=None, world='venus', home='earth'):
    canonical_world = _canonical_body(world)
    if canonical_world in DRACONIC_BODY_NAMES:
        dt = datetime.now(timezone.utc) if time is None else time
        if not isinstance(dt, datetime):
            dt = _as_datetime(dt)
        dt = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        return _get_draconic_longitudes(dt)[canonical_world]

    if not SKYFIELD_OK:
        raise RuntimeError("Skyfield not available for anchor computation")
    # Determines the alignment of world in the zodiac from home
    canonical_home = _canonical_body(home)

    eph, ts = _get_ephemeris()
    if time is None:
        t = ts.now()
    else:
        t = _as_skyfield_time(ts, time)
    if time is None:
        time = datetime.now(timezone.utc)

    earth = _body_key(eph, canonical_home)
    sun = _body_key(eph, canonical_world)

    astrometric_sun = earth.at(t).observe(sun)
    ra_sun, dec_sun, distance_sun = astrometric_sun.radec()
    ra_deg = ra_sun.hours * 15
    return ra_deg


def _days_between(a: Any, b: Any) -> float:
    if _is_skyfield_time(a) or _is_skyfield_time(b):
        if not SKYFIELD_OK:
            raise RuntimeError("Skyfield not available for time math")
        if _is_skyfield_time(a):
            t_a = a
            ts = getattr(t_a, "ts", None) or _get_timescale()
            t_b = _as_skyfield_time(ts, b)
        else:
            t_b = b
            ts = getattr(t_b, "ts", None) or _get_timescale()
            t_a = _as_skyfield_time(ts, a)
        return float(t_b.tt) - float(t_a.tt)
    dt_a = _ensure_utc_datetime(_as_datetime(a))
    dt_b = _ensure_utc_datetime(_as_datetime(b))
    return (dt_b - dt_a).total_seconds() / 86400.0


@dataclass
class DriftSegment:
    """Linearized drift segment derived from Skyfield samples."""
    start: datetime
    end: datetime
    lon0_unwrapped: float
    slope_deg_per_day: float


@dataclass
class AetherField:
    """
    Approximate celestial positions beyond ephemeris bounds.

    Strategy:
    - Within ephemeris window: prefer Skyfield (if available).
    - Beyond window: use anchor longitude at the nearest boundary and advance
      using a mean drift rate (deg/day). Optional: rates can be re-fitted from
      Skyfield across a window inside the valid range.
    """

    rates_deg_per_day: Dict[str, float] = None
    anchors_min: Dict[str, float] = None  # longitudes at window_start
    anchors_max: Dict[str, float] = None  # longitudes at window_end
    piecewise: Dict[str, List[DriftSegment]] = None  # per-body linear segments inside ephemeris window
    window_start: datetime = None
    window_end: datetime = None
    ephemeris_name: Optional[str] = None
    ephemeris_path: Optional[str] = None

    def __post_init__(self):
        if self.rates_deg_per_day is None:
            self.rates_deg_per_day = dict(MEAN_DEG_PER_DAY)
        self.anchors_min = self.anchors_min or {}
        self.anchors_max = self.anchors_max or {}
        self.piecewise = self.piecewise or {}
        if self.window_start is None:
            self.window_start = EPHEMERIS_START
        if self.window_end is None:
            self.window_end = EPHEMERIS_END
        if self.ephemeris_name is None:
            self.ephemeris_name = EPHEMERIS_NAME
        if self.ephemeris_path is None:
            self.ephemeris_path = EPHEMERIS_PATH

    def _ensure_anchor(self, body: str, use_skyfield: bool = False):
        body_key = _canonical_body(body)
        if body_key in self.anchors_min and body_key in self.anchors_max:       
            return
        start = self.window_start
        end = self.window_end
        if use_skyfield and SKYFIELD_OK:
            try:
                self.anchors_min.setdefault(body_key, fetch_celestial_data(start, body_key))
            except Exception:
                self.anchors_min.setdefault(body_key, 0.0)
            try:
                self.anchors_max.setdefault(body_key, fetch_celestial_data(end, body_key))
            except Exception:
                self.anchors_max.setdefault(body_key, self.anchors_min.get(body_key, 0.0))
            return
        if body_key in DRACONIC_BODY_NAMES:
            try:
                self.anchors_min.setdefault(body_key, _get_draconic_longitudes(start)[body_key])
            except Exception:
                self.anchors_min.setdefault(body_key, 0.0)
            try:
                self.anchors_max.setdefault(body_key, _get_draconic_longitudes(end)[body_key])
            except Exception:
                self.anchors_max.setdefault(body_key, self.anchors_min.get(body_key, 0.0))
            return
        # Runtime fallback: avoid Skyfield; default to zeros if missing
        self.anchors_min.setdefault(body_key, 0.0)
        self.anchors_max.setdefault(body_key, 0.0)

    def longitude(self, dt: Any, body: str) -> float:
        body_key = _canonical_body(body)
        if body_key in DRACONIC_BODY_NAMES:
            dt_value = _ensure_utc_datetime(_as_datetime(dt))
            return _get_draconic_longitudes(dt_value)[body_key]

        dt_value = dt if _is_skyfield_time(dt) else _as_datetime(dt)
        if not _is_skyfield_time(dt_value):
            dt_value = _ensure_utc_datetime(dt_value)
        # Runtime: do not depend on Skyfield; prefer piecewise when available   
        segs = self.piecewise.get(body_key) if self.piecewise else None
        if segs:
            return self.longitude_piecewise(dt_value, body_key)

        # Extrapolate from the nearest boundary
        self._ensure_anchor(body_key)
        rate = self.rates_deg_per_day.get(body_key)
        if rate is None:
            raise KeyError(f"No drift rate for body: {body_key}")

        days_from_start = _days_between(self.window_start, dt_value)
        if days_from_start < 0:
            days = -days_from_start
            # going backward in time -> subtract motion
            lon = (self.anchors_min[body_key] - rate * days) % 360.0
        else:
            days = _days_between(self.window_end, dt_value)
            lon = (self.anchors_max[body_key] + rate * days) % 360.0
        return lon

    # --- Piecewise drift support ---
    def fit_piecewise(self, step_days: int = 30, bodies: Optional[Tuple[str, ...]] = None) -> Dict[str, int]:
        """
        Build per-body linear drift segments across the ephemeris window by sampling
        Skyfield at a regular cadence. Each consecutive pair of samples defines
        a segment with a local slope (deg/day) and an unwrapped base longitude.

        Returns a dict mapping body -> number of segments created.
        """
        raw_bodies = bodies or tuple(self.rates_deg_per_day.keys())
        canonical_bodies = tuple(dict.fromkeys(_canonical_body(b) for b in raw_bodies if _canonical_body(b)))
        if not SKYFIELD_OK:
            return {b: 0 for b in canonical_bodies}

        start = self.window_start
        end = self.window_end
        step_days = max(1, int(step_days))

        # Build uniform sample grid inclusive of end
        ts: List[datetime] = []
        t = start
        while t < end:
            ts.append(t)
            t = t + timedelta(days=step_days)
        ts.append(end)

        created: Dict[str, int] = {}
        for b in canonical_bodies:
            # Gather longitudes and unwrap
            longs = [fetch_celestial_data(ti, b) for ti in ts]
            unwrapped = [longs[0]]
            for i in range(1, len(longs)):
                prev = unwrapped[-1]
                cur = longs[i]
                delta = (cur - prev + 540.0) % 360.0 - 180.0
                unwrapped.append(prev + delta)

            segs: List[DriftSegment] = []
            for i in range(len(ts) - 1):
                t0, t1 = ts[i], ts[i + 1]
                d_days = (t1 - t0).total_seconds() / 86400.0
                if d_days <= 0:
                    continue
                slope = (unwrapped[i + 1] - unwrapped[i]) / d_days
                segs.append(DriftSegment(start=t0, end=t1, lon0_unwrapped=unwrapped[i], slope_deg_per_day=slope))

            self.piecewise[b] = segs
            created[b] = len(segs)

        return created


    def longitude_piecewise(self, dt: Any, body: str, anchor_mode: str = 'end') -> float:
        """
        Estimate ecliptic longitude using piecewise linear drift if available.  
        - Inside ephemeris window: use the segment covering dt (linearized Skyfield).
        - Outside window: extend from the nearest boundary using the boundary segment slope.

        anchor_mode: 'start' | 'end' | 'nearest' - only used outside-range.     
        """
        body_key = _canonical_body(body)
        dt_value = dt if _is_skyfield_time(dt) else _as_datetime(dt)
        if not _is_skyfield_time(dt_value):
            dt_value = _ensure_utc_datetime(dt_value)
        segs = self.piecewise.get(body_key)
        if not segs:
            # No segments; fallback to simple model
            return self.longitude(dt_value, body_key)

        if _is_skyfield_time(dt_value):
            if not SKYFIELD_OK:
                raise RuntimeError("Skyfield not available for time math")
            ts = getattr(dt_value, "ts", None) or _get_timescale()
            dt_tt = float(dt_value.tt)
            win_start_tt = float(ts.from_datetime(_ensure_utc_datetime(self.window_start)).tt)
            win_end_tt = float(ts.from_datetime(_ensure_utc_datetime(self.window_end)).tt)

            # Inside range: choose segment spanning dt
            if win_start_tt <= dt_tt <= win_end_tt:
                for s in segs:
                    s_start_tt = float(ts.from_datetime(_ensure_utc_datetime(s.start)).tt)
                    s_end_tt = float(ts.from_datetime(_ensure_utc_datetime(s.end)).tt)
                    if s_start_tt <= dt_tt <= s_end_tt:
                        days = dt_tt - s_start_tt
                        return (s.lon0_unwrapped + s.slope_deg_per_day * days) % 360.0
                # Edge case: dt at exact end
                s = segs[-1]
                s_start_tt = float(ts.from_datetime(_ensure_utc_datetime(s.start)).tt)
                days = dt_tt - s_start_tt
                return (s.lon0_unwrapped + s.slope_deg_per_day * days) % 360.0

            # Outside range: pick boundary and extend with boundary slope
            if anchor_mode == 'nearest':
                d_start = abs(dt_tt - win_start_tt)
                d_end = abs(win_end_tt - dt_tt)
                anchor_mode = 'start' if d_start < d_end else 'end'

            if anchor_mode == 'start':
                s0 = next((s for s in segs if s.start == self.window_start), segs[0])
                s0_start_tt = float(ts.from_datetime(_ensure_utc_datetime(s0.start)).tt)
                days = dt_tt - s0_start_tt
                return (s0.lon0_unwrapped + s0.slope_deg_per_day * days) % 360.0

            s1 = next((s for s in segs if s.end == self.window_end), segs[-1])
            s1_start_tt = float(ts.from_datetime(_ensure_utc_datetime(s1.start)).tt)
            s1_end_tt = float(ts.from_datetime(_ensure_utc_datetime(s1.end)).tt)
            seg_days = s1_end_tt - s1_start_tt
            lon_end_unwrapped = s1.lon0_unwrapped + s1.slope_deg_per_day * seg_days
            days_after = dt_tt - s1_end_tt
            return (lon_end_unwrapped + s1.slope_deg_per_day * days_after) % 360.0

        # Inside range: choose segment spanning dt
        dt = dt_value
        if self.window_start <= dt <= self.window_end:
            for s in segs:
                if s.start <= dt <= s.end:
                    days = (dt - s.start).total_seconds() / 86400.0
                    return (s.lon0_unwrapped + s.slope_deg_per_day * days) % 360.0
            # Edge case: dt at exact end
            s = segs[-1]
            days = (dt - s.start).total_seconds() / 86400.0
            return (s.lon0_unwrapped + s.slope_deg_per_day * days) % 360.0

        # Outside range: pick boundary and extend with boundary slope
        if anchor_mode == 'nearest':
            d_start = abs((dt - self.window_start).total_seconds())
            d_end = abs((self.window_end - dt).total_seconds())
            anchor_mode = 'start' if d_start < d_end else 'end'

        if anchor_mode == 'start':
            s0 = next((s for s in segs if s.start == self.window_start), segs[0])
            days = _days_between(self.window_start, dt)
            return (s0.lon0_unwrapped + s0.slope_deg_per_day * days) % 360.0
        else:
            s1 = next((s for s in segs if s.end == self.window_end), segs[-1])
            days = _days_between(self.window_end, dt)
            return (s1.lon0_unwrapped + s1.slope_deg_per_day * days) % 360.0

    def sign(self, dt: Any, body: str) -> str:
        lon = self.longitude(dt, body)
        return get_zodiac_by_longitude_dt(lon, dt)

    def alignments(self, dt: Any, include_nodes: bool = True) -> Dict[str, str]:
        targets = ALIGNMENT_BODIES if include_nodes else PLANET_ALIGNMENT_BODIES
        return {b: self.sign(dt, b) for b in targets}

    def fit_rates(self, window_days: int = 365, step_days: int = 30) -> Dict[str, float]:
        """
        Re-estimate mean drift rates using Skyfield inside the valid range by
        sampling over a window and computing average slope.
        Returns the updated rates dict.
        """
        if not SKYFIELD_OK:
            return self.rates_deg_per_day

        start = max(self.window_start, datetime(2000, 1, 1, tzinfo=UTC))
        raw_bodies = list(self.rates_deg_per_day.keys())
        canonical_bodies = list(dict.fromkeys(_canonical_body(b) for b in raw_bodies if _canonical_body(b)))
        ts = [start + timedelta(days=i) for i in range(0, window_days + 1, max(1, step_days))]

        new_rates: Dict[str, float] = {}
        for b in canonical_bodies:
            try:
                longs = [fetch_celestial_data(t, b) for t in ts]
            except Exception:
                continue
            # Unwrap angles to avoid 360 jumps
            unwrapped = [longs[0]]
            for i in range(1, len(longs)):
                prev = unwrapped[-1]
                cur = longs[i]
                delta = (cur - prev + 540.0) % 360.0 - 180.0
                unwrapped.append(prev + delta)
            total_days = (ts[-1] - ts[0]).total_seconds() / 86400.0
            default_rate = self.rates_deg_per_day.get(b, DRACONIC_RATE_DEG_PER_DAY if b in DRACONIC_BODY_NAMES else 0.0)
            slope = (unwrapped[-1] - unwrapped[0]) / total_days if total_days else default_rate
            new_rates[b] = slope
        self.rates_deg_per_day.update(new_rates)
        return self.rates_deg_per_day


    # --- Calibration helpers ---
    def calibrate(self, window_days: int = 365, step_days: int = 30, bodies: Optional[Tuple[str, ...]] = None, piecewise: bool = False) -> Dict[str, Dict[str, float]]:
        """
        Learn from Skyfield within the ephemeris window by anchoring and re-fitting drift rates.

        - Ensures anchors at both window boundaries for the selected bodies.
        - Fits average drift rates using in-range Skyfield samples.

        Returns a summary dict with 'rates', 'anchors_min', 'anchors_max'.
        """
        raw_bodies = bodies or tuple(self.rates_deg_per_day.keys())
        canonical_bodies = tuple(dict.fromkeys(_canonical_body(b) for b in raw_bodies if _canonical_body(b)))
        for b in canonical_bodies:
            self._ensure_anchor(b, use_skyfield=True)
        self.fit_rates(window_days=window_days, step_days=step_days)
        if piecewise:
            self.fit_piecewise(step_days=step_days, bodies=canonical_bodies)
        return {
            'rates': dict(self.rates_deg_per_day),
            'anchors_min': dict(self.anchors_min),
            'anchors_max': dict(self.anchors_max),
        }


    def save_calibration(self, path: str) -> None:
        """Persist current rates, anchors, and piecewise segments to JSON."""
        pw = {}
        for b, segs in (self.piecewise or {}).items():
            pw[b] = [
                {
                    'start': s.start.isoformat(),
                    'end': s.end.isoformat(),
                    'lon0_unwrapped': s.lon0_unwrapped,
                    'slope_deg_per_day': s.slope_deg_per_day,
                }
                for s in segs
            ]
        ephemeris_name = self.ephemeris_name or EPHEMERIS_NAME
        ephemeris_path = self.ephemeris_path or EPHEMERIS_PATH
        spec = EPHEMERIS_SPECS.get((ephemeris_name or "").lower())
        payload = {
            'rates_deg_per_day': self.rates_deg_per_day,
            'anchors_min': self.anchors_min,
            'anchors_max': self.anchors_max,
            #'ephemeris_name': ephemeris_name,
            #'ephemeris_path': ephemeris_path,
            'ephemeris_start': self.window_start.isoformat(),
            'ephemeris_end': self.window_end.isoformat(),
            'ephemeris_true_start_year': spec.true_start_year if spec else None,
            'ephemeris_true_end_year': spec.true_end_year if spec else None,
            #'de421_start': self.window_start.isoformat(),
            #'de421_end': self.window_end.isoformat(),
            'piecewise': pw,
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, sort_keys=True)

    @classmethod
    def load_calibration(cls, path: str) -> 'AetherField':
        global data
        """Load rates, anchors, and piecewise segments from a JSON file."""     
        if path == 'AetherField':

            if not data:
            # 2. Remote fetch
                try:
                    import urllib.request

                    with urllib.request.urlopen(REMOTE_URL, timeout=10) as response:
                        data = json.load(response)

                    #return data
                except Exception:
                    return fallback

        else:
            
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        rates = data.get('rates_deg_per_day') or data.get('rates') or {}        
        anchors_min = data.get('anchors_min') or {}
        anchors_max = data.get('anchors_max') or {}
        def _parse_window_dt(value: Optional[str], fallback: datetime) -> datetime:
            if not value:
                return fallback
            try:
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return parsed.astimezone(UTC)
            except Exception:
                return fallback

        window_start = _parse_window_dt(
            data.get('ephemeris_start') or data.get('calibration_start') or data.get('de421_start'),
            EPHEMERIS_START,
        )
        window_end = _parse_window_dt(
            data.get('ephemeris_end') or data.get('calibration_end') or data.get('de421_end'),
            EPHEMERIS_END,
        )
        ephemeris_name = data.get('ephemeris_name')
        ephemeris_path = data.get('ephemeris_path')
        inst = cls(
            rates_deg_per_day=rates,
            anchors_min=anchors_min,
            anchors_max=anchors_max,
            window_start=window_start,
            window_end=window_end,
            ephemeris_name=ephemeris_name,
            ephemeris_path=ephemeris_path,
        )
        piecewise_data = data.get('piecewise') or {}
        pw: Dict[str, List[DriftSegment]] = {}
        for b, segs in piecewise_data.items():
            parsed: List[DriftSegment] = []
            for s in segs:
                try:
                    parsed.append(
                        DriftSegment(
                            start=datetime.fromisoformat(s['start']).astimezone(UTC),
                            end=datetime.fromisoformat(s['end']).astimezone(UTC),
                            lon0_unwrapped=float(s['lon0_unwrapped']),
                            slope_deg_per_day=float(s['slope_deg_per_day']),
                        )
                    )
                except Exception:
                    continue
            pw[b] = parsed
        inst.piecewise = pw
        return inst


# Convenience singleton
_GLOBAL_AETHER = AetherField()
_CAL_LOADED = False
if not _CAL_LOADED:
    # allow override via env var if you want
    cal_path = os.getenv("AETHER_CAL_FILE", 'AetherField')
    _GLOBAL_AETHER = AetherField.load_calibration(str(_resolve_cal_path(cal_path)))
    _CAL_LOADED = True

def aether_alignments(dt: Optional[Any] = None) -> Dict[str, str]:
    global _GLOBAL_AETHER, _CAL_LOADED
    if not _CAL_LOADED:
        # allow override via env var if you want
        cal_path = os.getenv('AETHER_CAL_FILE', 'AetherField')
        _GLOBAL_AETHER = AetherField.load_calibration(str(_resolve_cal_path(cal_path)))
        _CAL_LOADED = True

    if dt is None:
        dt = datetime.now(UTC)
    return _GLOBAL_AETHER.alignments(dt)


def aether_draconic_nodes(dt: Optional[Any] = None, include_altaz: bool = True) -> Dict[str, Dict[str, Any]]:
    """Return draconic node longitudes, signs, and optional alt/az snapshot."""
    if dt is None:
        dt_value = datetime.now(UTC)
    else:
        dt_value = _as_datetime(dt)
        dt_value = dt_value if dt_value.tzinfo else dt_value.replace(tzinfo=UTC)
    longs = _get_draconic_longitudes(dt_value)
    result: Dict[str, Dict[str, Any]] = {}
    for key, lon in longs.items():
        result[key] = {
            'longitude': lon,
            'sign': get_zodiac_by_longitude_dt(lon, dt),
        }

    if include_altaz and dt is None and SKYFIELD_OK:
        module = _import_skyfieldcomm()
        getter = getattr(module, 'get_draconic_nodes_alt_az', None) if module is not None else None
        if callable(getter):
            zone = os.getenv('TZ') or 'UTC'
            coords = os.getenv('DEFAULT_COORDS') or '0,0'
            try:
                altaz = getter(zone=zone, coords=coords)
            except Exception:
                altaz = None
            if isinstance(altaz, dict):
                for label, info in altaz.items():
                    canon = _canonical_body(label)
                    if canon in result:
                        try:
                            altitude = info.get('altitude')
                            azimuth = info.get('azimuth')
                            result[canon]['is_up'] = bool(info.get('is_up'))
                            result[canon]['altitude'] = float(altitude) if altitude is not None else None
                            result[canon]['azimuth'] = float(azimuth) if azimuth is not None else None
                        except Exception:
                            continue
    return result


def aether_longitude(dt: Any, body: str) -> float:
    global _GLOBAL_AETHER, _CAL_LOADED
    if not _CAL_LOADED:
        # allow override via env var if you want
        cal_path = os.getenv("AETHER_CAL_FILE", 'AetherField')
        _GLOBAL_AETHER = AetherField.load_calibration(str(_resolve_cal_path(cal_path)))
        _CAL_LOADED = True
        
    return _GLOBAL_AETHER.longitude(dt, body)


def aether_sign(dt: Any, body: str) -> str:
    global _GLOBAL_AETHER, _CAL_LOADED
    if not _CAL_LOADED:
        # allow override via env var if you want
        cal_path = os.getenv("AETHER_CAL_FILE", 'AetherField')
        _GLOBAL_AETHER = AetherField.load_calibration(str(_resolve_cal_path(cal_path)))
        _CAL_LOADED = True
        
    return _GLOBAL_AETHER.sign(dt, body)


# MoonTime-specific convenience wrappers (duck-typed; no hard dependency)
def aether_longitude_mt(mt: Any, body: str) -> float:
    return aether_longitude(mt, body)


def aether_sign_mt(mt: Any, body: str) -> str:
    return aether_sign(mt, body)


def aether_alignments_mt(mt: Any) -> Dict[str, str]:
    return aether_alignments(mt)

def aetherium_longitude_mt(mt: Any, body: str) -> float:
    global _GLOBAL_AETHER, _CAL_LOADED
    if _GLOBAL_AETHER is None:
        _GLOBAL_AETHER = AetherField()  # base instance

    if not _CAL_LOADED:
        # allow override via env var if you want
        cal_path = os.getenv("AETHER_CAL_FILE", 'AetherField')
        _GLOBAL_AETHER = AetherField.load_calibration(str(_resolve_cal_path(cal_path)))
        _CAL_LOADED = True

    return _GLOBAL_AETHER.longitude(mt, body)

def moon_phase(dt: Any):
    global _GLOBAL_AETHER, _CAL_LOADED

    """
    Returns:
      idx: int in [0..7] (0 = New, 4 = Full)
      info: dict with 'name', 'angle_deg', 'illum'
    """
    # normalize input -> timezone-aware UTC
    d = _as_datetime(dt)
    d = d if d.tzinfo else d.replace(tzinfo=UTC)
    if _GLOBAL_AETHER is None:
        _GLOBAL_AETHER = AetherField()  # base instance

    if not _CAL_LOADED:
        # allow override via env var if you want
        cal_path = os.getenv("AETHER_CAL_FILE", 'AetherField')
        _GLOBAL_AETHER = AetherField.load_calibration(str(_resolve_cal_path(cal_path)))
        _CAL_LOADED = True

    # use AetherField's longitudes (already calibrated / piecewise-capable)
    lon_moon = _GLOBAL_AETHER.longitude(d, "moon")
    lon_sun  = _GLOBAL_AETHER.longitude(d, "sun")

    # Moon-Sun elongation (0=new, 180=full)
    elong = (lon_moon - lon_sun) % 360.0

    # map to 8 bins centered every 45°
    idx = int(((elong + 22.5) % 360.0) // 45)

    # physical illumination (0..1), useful for UI
    illum = 0.5 * (1.0 - math.cos(math.radians(elong)))
    illum_pct = int(round(max(0.0, min(1.0, float(illum))) * 100))
    angle_deg = float(elong) % 360

    return idx, {
        "name": PHASE_NAMES[idx],
        "angle_deg": angle_deg,
        "illum": illum_pct,
    }


# --- Sunrise/Sunset estimation (no Skyfield) ---------------------------------
def _get_pytz_timezone(zone):
    try:
        if hasattr(zone, "localize") or hasattr(zone, "utcoffset"):
            return zone
        if isinstance(zone, str) and zone:
            if pytz:
                return pytz.timezone(zone)
            if ZoneInfo is not None:
                return ZoneInfo(zone)
    except Exception:
        pass
    return UTC


def sunrise_sunset(zone, coords: str, date=None, depression_deg: float = -0.833):
    """
    Estimate local sunrise and sunset using AetherField's solar longitude.

    Args:
      zone:     IANA tz string or pytz tzinfo
      coords:   "lat,lon" (degrees; east-positive longitude)
      date:     datetime.date (local) or None for today
      depression_deg: apparent altitude at sunrise/set (default -0.833°)

    Returns:
      (sunrise_dt, sunset_dt) as timezone-aware datetimes in `zone`.

    Notes:
      - Uses a simple equation-of-time approximation and ignores refraction dynamics
        beyond the altitude constant. Good as a Skyfield-free fallback.
    """
    tz = _get_pytz_timezone(zone)
    try:
        lat_str, lon_str = str(coords).replace(" ", "").split(",", 1)
        lat_deg = float(lat_str)
        lon_deg = float(lon_str)
    except Exception as exc:
        raise ValueError(f"Invalid coords format, expected 'lat,lon': {coords}") from exc

    # Local base day
    from datetime import date as _date
    if date is None:
        base_day = _date.today()
    else:
        base_day = date if isinstance(date, _date) else date.date()

    # Local solar noon estimate using Equation of Time (EoT)
    # Day of year
    n = int((_date(base_day.year, base_day.month, base_day.day) - _date(base_day.year, 1, 1)).days) + 1
    B = math.radians(360.0 * (n - 81) / 364.0)
    eot_min = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)

    # Timezone offset (hours) at local noon
    noon_dt = datetime(base_day.year, base_day.month, base_day.day, 12, 0, 0)
    if hasattr(tz, "localize"):
        local_noon_base = tz.localize(noon_dt)
    else:
        local_noon_base = noon_dt.replace(tzinfo=tz)
    tz_offset_hours = (local_noon_base.utcoffset() or timedelta(0)).total_seconds() / 3600.0
    lstm = 15.0 * tz_offset_hours
    offset_min = eot_min + 4.0 * (lon_deg - lstm)
    local_solar_noon = local_noon_base - timedelta(minutes=offset_min)

    # Solar declination from AetherField solar longitude (at solar noon)
    lam = aether_longitude(local_solar_noon, "sun")  # degrees
    # Convert to declination via obliquity
    _, dec = ecliptic_to_equatorial(lam, 0.0, OBLIQUITY_DEG)

    # Hour angle at apparent sunrise/sunset
    h0 = math.radians(depression_deg)
    phi = math.radians(lat_deg)
    sd = math.sin(math.radians(dec))
    cd = math.cos(math.radians(dec))
    cosH0 = (math.sin(h0) - math.sin(phi) * sd) / (math.cos(phi) * cd)
    # Handle polar day/night
    if cosH0 > 1.0:
        # Sun always below horizon
        return None, None
    if cosH0 < -1.0:
        # Sun always above horizon
        return None, None
    H0 = math.degrees(math.acos(max(-1.0, min(1.0, cosH0))))  # degrees
    daylen_hours = 2.0 * (H0 / 15.0)
    half = timedelta(hours=daylen_hours / 2.0)
    sunrise = local_solar_noon - half
    sunset = local_solar_noon + half
    return sunrise, sunset

def ae_is_up(dt, body: str, coords: (float, float) = None, method: str = "full", min_alt_deg: float = 0.0):
    global _GLOBAL_AETHER, _CAL_LOADED

    """
    Determine whether `body` is above the horizon at (lat, lon) at time `dt`.

    Args:
      dt:            datetime or MoonTime; timezone-naive treated as UTC.
      body:          'sun','moon','mars', etc. (uses your calibrated longitudes)
      lat_deg/lon_deg: observer geodetic latitude/longitude (east positive)
      method:        'clock' -> fast hemisphere test (no latitude), or 'full' -> altitude calc
      min_alt_deg:   require altitude > min_alt_deg (e.g. set 5.0 to ignore murky horizon)

    Returns:
      (up_bool, details_dict)
    """
    if not coords:
        coords, zone, tz = get_ip_data()
    d = _as_datetime(dt)
    d = d if d.tzinfo else d.replace(tzinfo=UTC)
    if _GLOBAL_AETHER is None:
        _GLOBAL_AETHER = AetherField()  # base instance

    if not _CAL_LOADED:
        # allow override via env var if you want
        cal_path = os.getenv("AETHER_CAL_FILE", 'AetherField')
        _GLOBAL_AETHER = AetherField.load_calibration(str(_resolve_cal_path(cal_path)))
        _CAL_LOADED = True
    lat_deg, lon_deg = map(float, coords.split(','))

    # Ecliptic longitudes from your model
    lon_body = _GLOBAL_AETHER.longitude(d, body)
    #lon_sun  = _GLOBAL_AETHER.longitude(d, "sun")

    # Approx equatorial coordinates (β≈0)
    ra_body, dec_body = ecliptic_to_equatorial(lon_body, 0.0)
    # (We compute RA_sun/Dec_sun only if you want it in details)
    #ra_sun,  dec_sun  = ecliptic_to_equatorial(lon_sun,  0.0)

    LST = _lst_deg(d, lon_deg)

    if method == "clock":
        # Object is considered up if within 6h of the local meridian.
        delta = abs(_angdiff_deg(ra_body, LST))
        up = (delta <= 90.0)
        return up, {
            "scheme": "clock",
            "lst_deg": LST,
            "ra_deg": ra_body,
            "dec_deg": dec_body,
            "delta_meridian_deg": delta,
        }

    # FULL altitude: sin a = sin φ sin δ + cos φ cos δ cos H
    phi = math.radians(lat_deg)
    dec_r = math.radians(dec_body)
    H = math.radians(_angdiff_deg(LST, ra_body))
    sin_alt = math.sin(phi)*math.sin(dec_r) + math.cos(phi)*math.cos(dec_r)*math.cos(H)
    alt_deg = math.degrees(math.asin(sin_alt))
    up = alt_deg > min_alt_deg
    return up, {
        "scheme": "full",
        "alt_deg": alt_deg,
        "hour_angle_deg": math.degrees(H),
        "lst_deg": LST,
        "ra_deg": ra_body,
        "dec_deg": dec_body,
        "min_alt_deg": min_alt_deg,
    }

def summarize_is_up(dt, bodies=bodies):
    out = {}
    for b in bodies:
        is_up, info = ae_is_up(dt, body=b)   # assume info has 'alt_deg' and 'lst_deg'
        alt = info.get('alt_deg', None)
        lst = info.get('lst_deg', None)
        altitude = alt if alt is not None else lst
        out[b.title()] = {"is_up": bool(is_up), "altitude": altitude}
    return out

def aetherfield():
    """Convenience function returning a AetherField for the given request."""
    return AetherField()