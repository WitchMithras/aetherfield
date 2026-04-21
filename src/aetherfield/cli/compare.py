from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pytz

import aetherfield as af  # reuse host implementation during staging


UTC = pytz.utc
DE421_START = af.DE421_START
DE421_END = af.DE421_END

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


def wrap_delta_deg(a: float, b: float) -> float:
    d = (a - b + 540.0) % 360.0 - 180.0
    return d


def sf_ecliptic_longitude(dt: datetime, body: str) -> float:
    from skyfield.api import load
    from skyfield.framelib import ecliptic_frame

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)

    eph = load('de421.bsp')
    ts = load.timescale()
    t = ts.from_datetime(dt)
    earth = eph['earth']
    b = af._body_key(eph, body)  # type: ignore[attr-defined]
    app = earth.at(t).observe(b).apparent()
    lon, lat, dist = app.frame_latlon(ecliptic_frame)
    return float(lon.degrees) % 360.0


@dataclass
class CompareResult:
    body: str
    dt: datetime
    aether_lon: float
    skyfield_lon: Optional[float]
    delta_deg: Optional[float]
    aether_sign: str
    skyfield_sign: Optional[str]


def _drift_longitude(a: af.AetherField, dt: datetime, body: str, anchor_mode: str = 'end') -> float:
    a._ensure_anchor(body)  # type: ignore[attr-defined]
    rate = a.rates_deg_per_day.get(body)
    if rate is None:
        raise KeyError(f"No drift rate for body: {body}")
    dt = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    if anchor_mode == 'nearest':
        d_start = abs((dt - DE421_START).total_seconds())
        d_end = abs((DE421_END - dt).total_seconds())
        anchor_mode = 'start' if d_start < d_end else 'end'
    if anchor_mode == 'start':
        days = (dt - DE421_START).total_seconds() / 86400.0
        return (a.anchors_min[body] + rate * days) % 360.0  # type: ignore[attr-defined]
    else:
        days = (dt - DE421_END).total_seconds() / 86400.0
        return (a.anchors_max[body] + rate * days) % 360.0  # type: ignore[attr-defined]


def compare_once(body: str, dt: datetime, force_aether: bool = False, fit_rates: bool = False) -> CompareResult:
    a = af.AetherField()
    if fit_rates:
        try:
            a.fit_rates()
        except Exception:
            pass
    if force_aether:
        aether_lon = _drift_longitude(a, dt, body)
        aether_sign = af.get_zodiac_by_longitude(aether_lon)
    else:
        aether_lon = a.longitude(dt, body)
        aether_sign = a.sign(dt, body)
    sky_lon: Optional[float] = None
    sky_sign: Optional[str] = None
    if DE421_START <= dt <= DE421_END:
        try:
            sky_lon = sf_ecliptic_longitude(dt, body)
            sky_sign = af.get_zodiac_by_longitude(sky_lon)
        except Exception:
            pass
    delta = wrap_delta_deg(aether_lon, sky_lon) if sky_lon is not None else None
    return CompareResult(body, dt, aether_lon, sky_lon, delta, aether_sign, sky_sign)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Compare AetherField with Skyfield for a single timestamp.")
    p.add_argument('--body', required=True, help='Body (sun, moon, mercury, ... pluto)')
    p.add_argument('--dt', default=None, help='ISO8601 datetime (UTC).')
    p.add_argument('--moontime', default=None, help='MoonTime string (mt:...)')
    p.add_argument('--force-aether', action='store_true', help='Use AetherField-only (drift).')
    p.add_argument('--fit-rates', action='store_true', help='Fit mean drift from in-range samples.')
    p.add_argument('--calibrate', action='store_true', help='Ensure anchors and piecewise segments (no-ops if present).')
    p.add_argument('--save-calibration', default=None, help='Save calibration JSON path.')
    p.add_argument('--load-calibration', default=None, help='Load calibration JSON path.')
    p.add_argument('--drift-anchor', choices=['start','end','nearest'], default='end', help='Anchor for drift only mode.')
    p.add_argument('--piecewise', action='store_true', help='Use piecewise segments when forcing aether.')
    p.add_argument('--piecewise-step', type=int, default=30, help='Step in days for piecewise building.')
    p.add_argument('--json', action='store_true', help='Emit JSON instead of text.')
    args = p.parse_args(argv)

    body = args.body.strip().lower()
    dt = parse_moontime(args.moontime) or parse_dt(args.dt)

    if args.load_calibration:
        try:
            a = af.AetherField.load_calibration(args.load_calibration)
        except Exception:
            a = af.AetherField()
    else:
        a = af.AetherField()
    if args.fit_rates:
        try:
            a.fit_rates()
        except Exception:
            pass
    if args.calibrate:
        try:
            if args.piecewise:
                a.fit_piecewise(step_days=int(args.piecewise_step), bodies=(body,))
        except Exception:
            pass
    if args.save_calibration:
        try:
            a.save_calibration(args.save_calibration)
        except Exception:
            pass

    res = compare_once(body, dt, force_aether=args.force_aether, fit_rates=args.fit_rates)

    if args.json:
        import json
        print(json.dumps({
            'body': res.body,
            'dt': res.dt.isoformat(),
            'aether_lon': res.aether_lon,
            'skyfield_lon': res.skyfield_lon,
            'delta_deg': res.delta_deg,
            'aether_sign': res.aether_sign,
            'skyfield_sign': res.skyfield_sign,
        }, indent=2))
    else:
        print(f"{res.body} @ {res.dt.isoformat()}\n"
              f"  Aether:   {res.aether_lon:8.3f} deg  ({res.aether_sign})\n"
              f"  Skyfield: {'n/a' if res.skyfield_lon is None else f'{res.skyfield_lon:8.3f} deg  ('+str(res.skyfield_sign)+')'}\n"
              f"  Delta:    {'n/a' if res.delta_deg is None else f'{res.delta_deg:+.3f} deg'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
