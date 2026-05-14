from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Optional

from . import core


def _parse_dt(value: Optional[str]):
    if not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def build_source_field(source_calibration: Optional[str], use_hosted: bool) -> core.AetherField:
    if source_calibration:
        return core.AetherField.load_calibration(source_calibration)
    if use_hosted:
        return core.AetherField.load_calibration("AetherField")
    return core.AetherField()


def write_minimal_calibration(
    output: str,
    dt: Optional[str] = None,
    source_calibration: Optional[str] = None,
    use_hosted: bool = True,
):
    source = build_source_field(source_calibration, use_hosted)
    return core.save_minimal_calibration(output, dt=_parse_dt(dt), source=source)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a minimal AetherField calibration JSON from current alignments."
    )
    parser.add_argument(
        "--output",
        default="src/aetherfield/aetherfield_calibration.json",
        help="Path to write the generated calibration JSON.",
    )
    parser.add_argument(
        "--dt",
        default=None,
        help="Optional ISO 8601 timestamp. Defaults to the current UTC time.",
    )
    parser.add_argument(
        "--source-calibration",
        default=None,
        help="Optional calibration path to use as the alignment source.",
    )
    parser.add_argument(
        "--no-hosted",
        action="store_true",
        help="Use the baseline model instead of trying hosted calibration.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print the generated alignment summary.",
    )
    args = parser.parse_args(argv)

    payload = write_minimal_calibration(
        output=args.output,
        dt=args.dt,
        source_calibration=args.source_calibration,
        use_hosted=not args.no_hosted,
    )

    if not args.quiet:
        print(json.dumps({
            "output": args.output,
            "calibration_time": payload["calibration_time"],
            "alignments": payload["alignments"],
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
