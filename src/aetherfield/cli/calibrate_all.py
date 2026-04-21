from __future__ import annotations

import argparse

import aetherfield as af


DEFAULT_OUT = 'aetherfield_calibration.json'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Calibrate AetherField and save piecewise segments for all bodies.')
    parser.add_argument('--out', default=DEFAULT_OUT, help='Output JSON path for calibration data.')
    args = parser.parse_args(argv)

    a = af.AetherField()

    bodies_all = ('sun','moon','mercury','venus','mars','jupiter','saturn','uranus','neptune','pluto')
    # Ensure anchors
    for b in bodies_all:
        a._ensure_anchor(b)  # type: ignore[attr-defined]

    # Fit mean drift from in-range samples (coarse global refinement)
    try:
        a.fit_rates()
    except Exception:
        pass

    # Piecewise segments with tuned steps per group
    groups = [
        (('moon',), 1),
        (('sun','mercury','venus'), 5),
        (('mars',), 10),
        (('jupiter','saturn'), 15),
        (('uranus','neptune','pluto'), 30),
    ]

    summary = {}
    for bodies, step in groups:
        try:
            created = a.fit_piecewise(step_days=step, bodies=bodies)
            summary.update(created)
        except Exception:
            for b in bodies:
                summary[b] = summary.get(b, 0)

    # Persist
    a.save_calibration(args.out)

    # Print a compact summary
    print(f"Saved calibration -> {args.out}")
    for b in bodies_all:
        n = summary.get(b, 0)
        print(f"  {b:9s} segments: {n}")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())

