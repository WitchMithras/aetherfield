from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean, median
from typing import Dict, List, Optional, Sequence

import pytz
import aetherfield as af


UTC = pytz.utc
DE421_START = af.DE421_START
DE421_END = af.DE421_END


def parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.endswith('Z'):
        s = s[:-1]
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=UTC)
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def wrap_delta_deg(a: float, b: float) -> float:
    return (a - b + 540.0) % 360.0 - 180.0


def _drift_longitude(a: af.AetherField, dt: datetime, body: str, anchor_mode: str = 'nearest') -> float:
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


def skyfield_longitudes(ts: Sequence[datetime], body: str) -> List[float]:
    from skyfield.api import load
    from skyfield.framelib import ecliptic_frame

    eph = load('de421.bsp')
    earth = eph['earth']
    key = af._body_key(eph, body)  # type: ignore[attr-defined]
    tscale = load.timescale()
    out: List[float] = []
    for dt in ts:
        t = tscale.from_datetime(dt.astimezone(UTC))
        app = earth.at(t).observe(key).apparent()
        lon, lat, dist = app.frame_latlon(ecliptic_frame)
        out.append(float(lon.degrees) % 360.0)
    return out


@dataclass
class BodyStats:
    n: int
    mae_mean: float
    mae_piece: float
    med_mean: float
    med_piece: float
    max_mean: float
    max_piece: float


def benchmark(
    bodies: Sequence[str],
    start: datetime,
    end: datetime,
    step_days: int,
    piecewise_step: int,
    build_piecewise: bool,
    fit_rates: bool,
    drift_anchor: str,
    load_cal: Optional[str],
    save_cal: Optional[str],
) -> Dict[str, BodyStats]:
    r0 = max(start, DE421_START)
    r1 = min(end, DE421_END)
    if r1 < r0:
        return {}
    tlist: List[datetime] = []
    step_days = max(1, int(step_days))
    t = r0
    while t <= r1:
        tlist.append(t)
        t = t + timedelta(days=step_days)

    if load_cal:
        a = af.AetherField.load_calibration(load_cal)
    else:
        a = af.AetherField()
    if fit_rates:
        try:
            a.fit_rates()
        except Exception:
            pass
    if build_piecewise:
        try:
            a.fit_piecewise(step_days=piecewise_step, bodies=tuple(bodies))
        except Exception:
            pass
    if save_cal:
        try:
            a.save_calibration(save_cal)
        except Exception:
            pass

    results: Dict[str, BodyStats] = {}
    for body in bodies:
        sky = skyfield_longitudes(tlist, body)
        mean_preds = [_drift_longitude(a, dt, body, anchor_mode=drift_anchor) for dt in tlist]
        if build_piecewise and (body in getattr(a, 'piecewise', {})):
            piece_preds = [a.longitude_piecewise(dt, body, anchor_mode=drift_anchor) for dt in tlist]
        else:
            piece_preds = [a.longitude(dt, body) for dt in tlist]

        mean_err = [abs(wrap_delta_deg(p, s)) for p, s in zip(mean_preds, sky)]
        piece_err = [abs(wrap_delta_deg(p, s)) for p, s in zip(piece_preds, sky)]

        stats = BodyStats(
            n=len(sky),
            mae_mean=mean(mean_err) if mean_err else float('nan'),
            mae_piece=mean(piece_err) if piece_err else float('nan'),
            med_mean=median(mean_err) if mean_err else float('nan'),
            med_piece=median(piece_err) if piece_err else float('nan'),
            max_mean=max(mean_err) if mean_err else float('nan'),
            max_piece=max(piece_err) if piece_err else float('nan'),
        )
        results[body] = stats

    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark AetherField mean drift vs piecewise against Skyfield/de421.")
    parser.add_argument('--bodies', default='sun,moon,mercury,venus,mars,jupiter,saturn,uranus,neptune,pluto', help='Comma-separated list of bodies to evaluate.')
    parser.add_argument('--start', required=True, help='Start datetime ISO8601 (e.g., 2001-01-01T00:00:00Z).')
    parser.add_argument('--end', required=True, help='End datetime ISO8601 (inclusive).')
    parser.add_argument('--step-days', type=int, default=5, help='Sampling step in days.')
    parser.add_argument('--drift-anchor', choices=['start', 'end', 'nearest'], default='nearest', help='Anchor used for mean-drift and extrapolation.')
    parser.add_argument('--piecewise', action='store_true', help='Build and use piecewise segments for evaluation.')
    parser.add_argument('--piecewise-step', type=int, default=10, help='Step in days for fitting piecewise segments.')
    parser.add_argument('--fit-rates', action='store_true', help='Fit mean drift rates from in-range samples before benchmarking.')
    parser.add_argument('--load-calibration', default=None, help='Path to load saved calibration (rates/anchors/piecewise).')
    parser.add_argument('--save-calibration', default=None, help='Path to save calibration after building.')
    parser.add_argument('--json', action='store_true', help='Emit JSON summary instead of text table.')

    args = parser.parse_args(argv)
    bodies = [b.strip().lower() for b in args.bodies.split(',') if b.strip()]

    start = parse_dt(args.start)
    end = parse_dt(args.end)
    stats = benchmark(
        bodies=bodies,
        start=start,
        end=end,
        step_days=args.step_days,
        piecewise_step=args.piecewise_step,
        build_piecewise=args.piecewise,
        fit_rates=args.fit_rates,
        drift_anchor=args.drift_anchor,
        load_cal=args.load_calibration,
        save_cal=args.save_calibration,
    )

    if args.json:
        import json
        print(json.dumps({k: vars(v) for k, v in stats.items()}, indent=2))
    else:
        for b, st in stats.items():
            print(f"{b:9s} N={st.n:4d}  MAE(mean)={st.mae_mean:6.3f}°  MAE(piece)={st.mae_piece:6.3f}°  "
                  f"MED(mean)={st.med_mean:6.3f}°  MED(piece)={st.med_piece:6.3f}°  "
                  f"MAX(mean)={st.max_mean:6.3f}°  MAX(piece)={st.max_piece:6.3f}°")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

