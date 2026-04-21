import math
from dataclasses import dataclass
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple, List
from pathlib import Path
import os
from dotenv import load_dotenv
# --- aetherfield: is_up utilities -------------------------------------------
import math
from datetime import timezone
from .iplocal import get_ip_data


# Mean obliquity (degrees). You can make this tunable from your calibration file if you want.
OBLIQUITY_DEG = 23.43928

bodies = ['sun','moon','mercury','venus','mars','jupiter','saturn']


def _wrap_deg(x: float) -> float:
    return x % 360.0

def _angdiff_deg(a: float, b: float) -> float:
    """Signed smallest difference a-b in (-180, +180]."""
    return ((a - b + 180.0) % 360.0) - 180.0

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


load_dotenv()

import pytz

try:
    from skyfield.api import load
    from skyfield.framelib import ecliptic_frame
    SKYFIELD_OK = True
except Exception:
    SKYFIELD_OK = False

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


UTC = pytz.utc
DE421_START = datetime(1951, 1, 1, tzinfo=UTC)
DE421_END = datetime(2050, 12, 31, 23, 59, 59, tzinfo=UTC)


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
}

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
    p = Path(path)
    if p.is_file():
        return p
    # also try alongside this file
    here = Path(__file__).resolve().parent
    p2 = here.parent.parent.parent / path  # repo root relative
    return p2 if p2.is_file() else Path(path)


def _in_de421(dt: datetime) -> bool:
    dt_utc = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    dt_utc = dt_utc.astimezone(UTC)
    return DE421_START <= dt_utc <= DE421_END


def _as_datetime(dt_or_mt: Any) -> datetime:
    """Accept a datetime or a MoonTime-like object with to_datetime()."""
    if isinstance(dt_or_mt, datetime):
        return dt_or_mt
    to_dt = getattr(dt_or_mt, 'to_datetime', None)
    if callable(to_dt):
        dt = to_dt()
        if not isinstance(dt, datetime):
            raise TypeError("to_datetime() did not return a datetime")
        return dt
    raise TypeError("Expected datetime or MoonTime-like object with to_datetime()")


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


def _ecliptic_longitude_skyfield(dt: datetime, body: str) -> float:
    if not SKYFIELD_OK:
        raise RuntimeError("Skyfield not available for anchor computation")
    # Cache ephemeris and timescale to avoid reloading for every call
    global _SF_EPH, _SF_TS
    try:
        _SF_EPH
    except NameError:
        _SF_EPH = None  # type: ignore[var-annotated]
        _SF_TS = None   # type: ignore[var-annotated]
    if _SF_EPH is None or _SF_TS is None:
        _SF_EPH = load('de421.bsp')
        _SF_TS = load.timescale()
    eph = _SF_EPH
    ts = _SF_TS
    earth = eph['earth']
    b = _body_key(eph, body)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    t = ts.from_datetime(dt.astimezone(UTC))
    app = earth.at(t).observe(b).apparent()
    lon, lat, dist = app.frame_latlon(ecliptic_frame)
    return float(lon.degrees) % 360.0

def fetch_celestial_data(time=None, world='venus', home='earth'):
    if not SKYFIELD_OK:
        raise RuntimeError("Skyfield not available for anchor computation")
    # Determines the alignment of world in the zodiac from home
    world = planet_eph.get(world, world)
    home = planet_eph.get(home, home)

    ts = load.timescale()
    t = ts.now() if time is None else ts.from_datetime(time)
    sanitized_time = t.utc_datetime().strftime("%Y%m%d%H%M%S")
    if time is None:
        time = datetime.now(timezone.utc)

    coarse_model = 'de421.bsp'
    fine_model = 'de430t.bsp'
    planets = load(coarse_model)
    earth = planets[home]
    sun = planets[world]

    astrometric_sun = earth.at(t).observe(sun)
    ra_sun, dec_sun, distance_sun = astrometric_sun.radec()
    ra_deg = ra_sun.hours * 15
    return ra_deg


def _days_between(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 86400.0


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
    - Within de421 range: prefer Skyfield (if available).
    - Beyond range: use anchor longitude at the nearest boundary and advance
      using a mean drift rate (deg/day). Optional: rates can be re-fitted from
      Skyfield across a window inside the valid range.
    """

    rates_deg_per_day: Dict[str, float] = None
    anchors_min: Dict[str, float] = None  # longitudes at DE421_START
    anchors_max: Dict[str, float] = None  # longitudes at DE421_END
    piecewise: Dict[str, List[DriftSegment]] = None  # per-body linear segments inside de421

    def __post_init__(self):
        if self.rates_deg_per_day is None:
            self.rates_deg_per_day = dict(MEAN_DEG_PER_DAY)
        self.anchors_min = self.anchors_min or {}
        self.anchors_max = self.anchors_max or {}
        self.piecewise = self.piecewise or {}

    def _ensure_anchor(self, body: str, use_skyfield: bool = False):
        if body in self.anchors_min and body in self.anchors_max:
            return
        if use_skyfield and SKYFIELD_OK:
            try:
                self.anchors_min.setdefault(body, fetch_celestial_data(DE421_START, body))
            except Exception:
                self.anchors_min.setdefault(body, 0.0)
            try:
                self.anchors_max.setdefault(body, fetch_celestial_data(DE421_END, body))
            except Exception:
                self.anchors_max.setdefault(body, self.anchors_min.get(body, 0.0))
            return
        # Runtime fallback: avoid Skyfield; default to zeros if missing
        self.anchors_min.setdefault(body, 0.0)
        self.anchors_max.setdefault(body, 0.0)

    def longitude(self, dt: Any, body: str) -> float:
        dt = _as_datetime(dt)
        dt = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        # Runtime: do not depend on Skyfield; prefer piecewise when available
        segs = self.piecewise.get(body) if self.piecewise else None
        if segs:
            return self.longitude_piecewise(dt, body)

        # Extrapolate from the nearest boundary
        self._ensure_anchor(body)
        rate = self.rates_deg_per_day.get(body)
        if rate is None:
            raise KeyError(f"No drift rate for body: {body}")

        if dt < DE421_START:
            days = _days_between(dt, DE421_START)
            # going backward in time -> subtract motion
            lon = (self.anchors_min[body] - rate * days) % 360.0
        else:
            days = _days_between(DE421_END, dt)
            lon = (self.anchors_max[body] + rate * days) % 360.0
        return lon

    # --- Piecewise drift support ---
    def fit_piecewise(self, step_days: int = 30, bodies: Optional[Tuple[str, ...]] = None) -> Dict[str, int]:
        """
        Build per-body linear drift segments across the de421 window by sampling
        Skyfield at a regular cadence. Each consecutive pair of samples defines
        a segment with a local slope (deg/day) and an unwrapped base longitude.

        Returns a dict mapping body -> number of segments created.
        """
        if not SKYFIELD_OK:
            return {b: 0 for b in (bodies or tuple(self.rates_deg_per_day.keys()))}

        start = DE421_START
        end = DE421_END
        step_days = max(1, int(step_days))
        bodies = bodies or tuple(self.rates_deg_per_day.keys())

        # Build uniform sample grid inclusive of end
        ts: List[datetime] = []
        t = start
        while t < end:
            ts.append(t)
            t = t + timedelta(days=step_days)
        ts.append(end)

        created: Dict[str, int] = {}
        for b in bodies:
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
        - Inside de421: use the segment covering dt (linearized Skyfield).
        - Outside de421: extend from the nearest boundary using the boundary segment slope.

        anchor_mode: 'start' | 'end' | 'nearest' — only used outside-range.
        """
        dt = _as_datetime(dt)
        dt = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        segs = self.piecewise.get(body)
        if not segs:
            # No segments; fallback to simple model
            return self.longitude(dt, body)

        # Inside range: choose segment spanning dt
        if DE421_START <= dt <= DE421_END:
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
            d_start = abs((dt - DE421_START).total_seconds())
            d_end = abs((DE421_END - dt).total_seconds())
            anchor_mode = 'start' if d_start < d_end else 'end'

        if anchor_mode == 'start':
            s0 = next((s for s in segs if s.start == DE421_START), segs[0])
            days = _days_between(DE421_START, dt)
            return (s0.lon0_unwrapped + s0.slope_deg_per_day * days) % 360.0
        else:
            s1 = next((s for s in segs if s.end == DE421_END), segs[-1])
            days = _days_between(DE421_END, dt)
            return (s1.lon0_unwrapped + s1.slope_deg_per_day * days) % 360.0

    def sign(self, dt: Any, body: str) -> str:
        lon = self.longitude(dt, body)
        return get_zodiac_by_longitude(lon)

    def alignments(self, dt: Any) -> Dict[str, str]:
        bodies = [
            'sun', 'moon', 'mercury', 'venus', 'mars',
            'jupiter', 'saturn', 'uranus', 'neptune', 'pluto',
        ]
        return {b: self.sign(dt, b) for b in bodies}

    def fit_rates(self, window_days: int = 365, step_days: int = 30) -> Dict[str, float]:
        """
        Re-estimate mean drift rates using Skyfield inside the valid range by
        sampling over a window and computing average slope.
        Returns the updated rates dict.
        """
        if not SKYFIELD_OK:
            return self.rates_deg_per_day

        start = max(DE421_START, datetime(2000, 1, 1, tzinfo=UTC))
        bodies = list(self.rates_deg_per_day.keys())
        ts = [start + timedelta(days=i) for i in range(0, window_days + 1, max(1, step_days))]

        new_rates: Dict[str, float] = {}
        for b in bodies:
            # Use Skyfield samples directly for calibration
            longs = [fetch_celestial_data(t, b) for t in ts]
            # Unwrap angles to avoid 360 jumps
            unwrapped = [longs[0]]
            for i in range(1, len(longs)):
                prev = unwrapped[-1]
                cur = longs[i]
                delta = (cur - prev + 540.0) % 360.0 - 180.0
                unwrapped.append(prev + delta)
            total_days = (ts[-1] - ts[0]).total_seconds() / 86400.0
            slope = (unwrapped[-1] - unwrapped[0]) / total_days if total_days else self.rates_deg_per_day[b]
            new_rates[b] = slope
        self.rates_deg_per_day.update(new_rates)
        return self.rates_deg_per_day

    # --- Calibration helpers ---
    def calibrate(self, window_days: int = 365, step_days: int = 30, bodies: Optional[Tuple[str, ...]] = None, piecewise: bool = False) -> Dict[str, Dict[str, float]]:
        """
        Learn from Skyfield within de421 by anchoring and re-fitting drift rates.

        - Ensures anchors at both de421 boundaries for the selected bodies.
        - Fits average drift rates using in-range Skyfield samples.

        Returns a summary dict with 'rates', 'anchors_min', 'anchors_max'.
        """
        bodies = bodies or tuple(self.rates_deg_per_day.keys())
        for b in bodies:
            self._ensure_anchor(b, use_skyfield=True)
        self.fit_rates(window_days=window_days, step_days=step_days)
        if piecewise:
            self.fit_piecewise(step_days=step_days, bodies=bodies)
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
        payload = {
            'rates_deg_per_day': self.rates_deg_per_day,
            'anchors_min': self.anchors_min,
            'anchors_max': self.anchors_max,
            'de421_start': DE421_START.isoformat(),
            'de421_end': DE421_END.isoformat(),
            'piecewise': pw,
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, sort_keys=True)

    @classmethod
    def load_calibration(cls, path: str) -> 'AetherField':
        """Load rates, anchors, and piecewise segments from a JSON file."""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        rates = data.get('rates_deg_per_day') or data.get('rates') or {}
        anchors_min = data.get('anchors_min') or {}
        anchors_max = data.get('anchors_max') or {}
        inst = cls(rates_deg_per_day=rates, anchors_min=anchors_min, anchors_max=anchors_max)
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
    try:
        # allow override via env var if you want
        cal_path = os.getenv("AETHER_CAL_FILE", "aetherfield_calibration.json")
        _GLOBAL_AETHER = AetherField.load_calibration(str(_resolve_cal_path(cal_path)))
        _CAL_LOADED = True
    except Exception:
        pass

def aether_alignments(dt: Optional[Any] = None) -> Dict[str, str]:
    global _GLOBAL_AETHER, _CAL_LOADED
    if not _CAL_LOADED:
        try:

            # allow override via env var if you want
            cal_path = os.getenv("AETHER_CAL_FILE", "aetherfield_calibration.json")
            _GLOBAL_AETHER = AetherField.load_calibration(str(_resolve_cal_path(cal_path)))
            _CAL_LOADED = True
        except Exception:
            pass    
    if dt is None:
        dt = datetime.now(UTC)
    return _GLOBAL_AETHER.alignments(dt)


def aether_longitude(dt: Any, body: str) -> float:
    global _GLOBAL_AETHER, _CAL_LOADED
    if not _CAL_LOADED:
        try:
            # allow override via env var if you want
            cal_path = os.getenv("AETHER_CAL_FILE", "aetherfield_calibration.json")
            _GLOBAL_AETHER = AetherField.load_calibration(str(_resolve_cal_path(cal_path)))
            _CAL_LOADED = True
        except Exception:
            pass   
    return _GLOBAL_AETHER.longitude(dt, body)


def aether_sign(dt: Any, body: str) -> str:
    global _GLOBAL_AETHER, _CAL_LOADED
    if not _CAL_LOADED:
        try:
            # allow override via env var if you want
            cal_path = os.getenv("AETHER_CAL_FILE", "aetherfield_calibration.json")
            _GLOBAL_AETHER = AetherField.load_calibration(str(_resolve_cal_path(cal_path)))
            _CAL_LOADED = True
        except Exception:
            pass   
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
        try:
            # allow override via env var if you want
            cal_path = os.getenv("AETHER_CAL_FILE", "aetherfield_calibration.json")
            _GLOBAL_AETHER = AetherField.load_calibration(str(_resolve_cal_path(cal_path)))
            _CAL_LOADED = True
        except Exception:
            pass 

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
        cal_path = os.getenv("AETHER_CAL_FILE", "aetherfield_calibration.json")
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
        if hasattr(zone, "localize"):
            return zone
        if isinstance(zone, str) and zone:
            return pytz.timezone(zone)
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
    local_noon_base = tz.localize(datetime(base_day.year, base_day.month, base_day.day, 12, 0, 0))
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
        try:
            # allow override via env var if you want
            cal_path = os.getenv("AETHER_CAL_FILE", "aetherfield_calibration.json")
            _GLOBAL_AETHER = AetherField.load_calibration(str(_resolve_cal_path(cal_path)))
            _CAL_LOADED = True
        except Exception:
            pass 
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

