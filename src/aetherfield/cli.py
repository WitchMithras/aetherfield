from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import pytz

from . import core as af


UTC = pytz.utc
EPHEMERIS_START = af.EPHEMERIS_START
EPHEMERIS_END = af.EPHEMERIS_END
EPHEMERIS_PATH = af.EPHEMERIS_PATH

planet_eph = {
    'jupiter': 5,
    'saturn': 6,
    'uranus': 7,
    'neptune': 8,
    'pluto': 9
}


def parse_dt(dt_str: Optional[str]) -> datetime:
    if not dt_str:
        return datetime.now(UTC)
    s = dt_str.strip()
    if s.endswith('Z'):
        s = s[:-1]
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=UTC)
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_moontime(mt_str: Optional[str]) -> Optional[datetime]:
    if not mt_str:
        return None
    try:
        from moontime import MoonTime
        mt = MoonTime.fromisoformat(mt_str)
        return mt.to_datetime().astimezone(UTC)
    except Exception:
        return None


_SF_TIME_RE = re.compile(
    r"^\\s*(?P<year>-?\\d+)"
    r"(?:-(?P<month>\\d{1,2})"
    r"(?:-(?P<day>\\d{1,2})"
    r"(?:[T\\s](?P<hour>\\d{1,2})"
    r"(?::(?P<minute>\\d{1,2})"
    r"(?::(?P<second>\\d{1,2}))?"
    r")?"
    r")?"
    r")?"
    r")?"
    r"(?:\\s*(?P<tz>Z|[+-]\\d{2}:\\d{2}))?\\s*$",
    re.IGNORECASE,
)


def parse_sf_time(sf_str: Optional[str]):
    if not sf_str:
        return None
    s = sf_str.strip()
    if not s:
        return None

    if "," not in s:
        iso_candidate = s
        if iso_candidate.endswith(("Z", "z")):
            iso_candidate = iso_candidate[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(iso_candidate)
        except Exception:
            dt = None
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            else:
                dt = dt.astimezone(UTC)
            try:
                from skyfield.api import load
            except Exception as exc:
                raise ValueError("Skyfield is required for --sf") from exc
            ts = load.timescale()
            return ts.from_datetime(dt)

    offset_days = 0.0
    year = month = day = hour = minute = second = None
    if "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        if not 1 <= len(parts) <= 6:
            raise ValueError(
                "Invalid --sf value; expected YEAR[,MONTH[,DAY[,HOUR[,MINUTE[,SECOND]]]]]"
            )
        nums = [int(p) for p in parts]
        year = nums[0]
        month = nums[1] if len(nums) > 1 else 1
        day = nums[2] if len(nums) > 2 else 1
        hour = nums[3] if len(nums) > 3 else 0
        minute = nums[4] if len(nums) > 4 else 0
        second = nums[5] if len(nums) > 5 else 0
    else:
        match = _SF_TIME_RE.match(s)
        if not match:
            raise ValueError(
                "Invalid --sf value; expected ISO 8601 (YYYY-MM-DD[THH[:MM[:SS]][Z|+HH:MM]]) or YEAR,MONTH,DAY"
            )
        year = int(match.group("year"))
        month = int(match.group("month") or 1)
        day = int(match.group("day") or 1)
        hour = int(match.group("hour") or 0)
        minute = int(match.group("minute") or 0)
        second = int(match.group("second") or 0)
        tz = match.group("tz")
        if tz and tz.upper() != "Z":
            sign = 1 if tz[0] == "+" else -1
            offset_hours = int(tz[1:3])
            offset_minutes = int(tz[4:6])
            offset_days = sign * (offset_hours * 60 + offset_minutes) / 1440.0

    try:
        from skyfield.api import load
    except Exception as exc:
        raise ValueError("Skyfield is required for --sf") from exc

    ts = load.timescale()
    t = af.make_skyfield_time(
        ts,
        year=year,
        month=month,
        day=day,
        hour=hour,
        minute=minute,
        second=second,
    )
    if offset_days:
        t = t - offset_days
    return t


def _ensure_utc_datetime(dt_value: datetime) -> datetime:
    if dt_value.tzinfo is None:
        return dt_value.replace(tzinfo=UTC)
    return dt_value.astimezone(UTC)


def _days_between(start: datetime, end: Any) -> float:
    if af.is_skyfield_time(end):
        from skyfield.api import load

        ts = getattr(end, "ts", None) or load.timescale()
        start_t = ts.from_datetime(_ensure_utc_datetime(start))
        return float(end.tt) - float(start_t.tt)
    if not isinstance(end, datetime):
        to_dt = getattr(end, "to_datetime", None)
        if callable(to_dt):
            end = to_dt()
        else:
            raise TypeError("Expected datetime or Skyfield Time for comparison")
    start_dt = _ensure_utc_datetime(start)
    end_dt = _ensure_utc_datetime(end)
    return (end_dt - start_dt).total_seconds() / 86400.0


def format_time_label(value: Any) -> str:
    if af.is_skyfield_time(value):
        fmt = getattr(value, "utc_strftime", None)
        if callable(fmt):
            try:
                return fmt("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass
        jpl = getattr(value, "utc_jpl", None)
        if callable(jpl):
            try:
                return jpl()
            except Exception:
                pass
        return str(value)
    if isinstance(value, datetime):
        return _ensure_utc_datetime(value).isoformat()
    return str(value)


def wrap_delta_deg(a: float, b: float) -> float:
    d = (a - b + 540.0) % 360.0 - 180.0
    return d


def sf_ecliptic_longitude(dt: Any, body: str) -> float:
    from skyfield.api import load
    from skyfield.framelib import ecliptic_frame

    eph = load(EPHEMERIS_PATH)
    ts = load.timescale()
    if af.is_skyfield_time(dt):
        t = dt
    else:
        if not isinstance(dt, datetime):
            to_dt = getattr(dt, "to_datetime", None)
            if callable(to_dt):
                dt = to_dt()
            else:
                raise TypeError("Expected datetime or Skyfield Time")
        dt = _ensure_utc_datetime(dt)
        t = ts.from_datetime(dt)
    earth = eph['earth']
    b = af.get_body_key(eph, body)
    app = earth.at(t).observe(b).apparent()
    lat, lon, dist = app.frame_latlon(ecliptic_frame)
    return float(lon.degrees) % 360.0


@dataclass
class CompareResult:
    body: str
    dt: Any
    lon: float
    sign: str


def _drift_longitude(a: af.AetherField, dt: Any, body: str, anchor_mode: str = 'end') -> float:
    a._ensure_anchor(body)  # type: ignore[attr-defined]
    rate = a.rates_deg_per_day.get(body)
    if rate is None:
        raise KeyError(f"No drift rate for body: {body}")
    if anchor_mode == 'nearest':
        d_start = abs(_days_between(a.window_start, dt))
        d_end = abs(_days_between(a.window_end, dt))
        anchor_mode = 'start' if d_start < d_end else 'end'
    if anchor_mode == 'start':
        days = _days_between(a.window_start, dt)
        return (a.anchors_min[body] + rate * days) % 360.0  # type: ignore[attr-defined]
    else:
        days = _days_between(a.window_end, dt)
        return (a.anchors_max[body] + rate * days) % 360.0  # type: ignore[attr-defined]


def compare_once(a: af.AetherField, body: str, dt: Any, force_aether: bool = False, fit_rates: bool = False) -> CompareResult:
    if fit_rates:
        try:
            a.fit_rates()
        except Exception:
            pass
    sky_lon: Optional[float] = None
    sky_sign: Optional[str] = None
    aether_lon = a.longitude(dt, body)
    aether_sign = a.sign(dt, body)

    delta = wrap_delta_deg(aether_lon, sky_lon) if sky_lon is not None else None
    return CompareResult(body, dt, aether_lon, aether_sign)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Compare AetherField with Skyfield for a single timestamp.")
    p.add_argument('--body', required=True, help='Body (sun, moon, mercury, ... pluto)')
    p.add_argument('--dt', default=None, help='ISO8601 datetime (UTC).')
    p.add_argument('--mt', default=None, help='MoonTime string (mt:...)')
    p.add_argument('--sf', default=None, help='Skyfield time with astronomical year numbering (ISO 8601 YYYY-MM-DD[THH[:MM[:SS]][Z|+HH:MM]] or YEAR,MONTH,DAY). Overrides --dt/--moontime.')
    p.add_argument('--load-calibration', default=None, help='Load calibration JSON path.')
    p.add_argument('--drift-anchor', choices=['start','end','nearest'], default='end', help='Anchor for drift only mode.')
    p.add_argument('--json', action='store_true', help='Emit JSON instead of text.')
    args = p.parse_args(argv)

    body = args.body.strip().lower()
    if args.sf:
        try:
            dt = parse_sf_time(args.sf)
        except ValueError as exc:
            p.error(str(exc))
        if dt is None:
            p.error("Invalid --sf value")
    else:
        dt = parse_moontime(args.mt) or parse_dt(args.dt)

    if args.load_calibration:
        try:
            a = af.AetherField.load_calibration(args.load_calibration)
        except Exception:
            a = af.AetherField()
    else:
        # Load from server if available
        try:
            a = af.AetherField.load_calibration('AetherField')
        except Exception:
            # Fallback
            a = af.AetherField()

    res = compare_once(a, body, dt, force_aether=True)

    if args.json:
        import json
        print(json.dumps({
            'body': res.body,
            'dt': format_time_label(res.dt),
            'lon': res.lon,
            'sign': res.sign,
        }, indent=2))
    else:
        print(f"{res.body} @ {format_time_label(res.dt)}\n"
              f"  Aether:   {res.lon:8.3f} deg  ({res.sign})")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
