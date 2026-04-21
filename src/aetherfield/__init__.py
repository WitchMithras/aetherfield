"""AetherField staging package shim.

For now, re-export selected APIs from the host project's `aetherfield.py` to
allow downstream packages to begin switching imports to `aetherfield_pkg`.

In a full extraction, we will move the implementation here and keep this API
surface stable.
"""

from .core import (
    aether_longitude,
    aether_sign,
    ecliptic_to_equatorial,
    aether_alignments,
    moon_phase,
    sunrise_sunset,
    AetherField,
    DE421_START,
    DE421_END,
    ae_is_up,
    summarize_is_up,
    OBLIQUITY_DEG
)

__all__ = [
    "OBLIQUITY_DEG",
    "aether_longitude",
    "aether_sign",
    "aether_alignments",
    "moon_phase",
    "ecliptic_to_equatorial",
    "sunrise_sunset",
    "AetherField",
    "DE421_START",
    "DE421_END",
    "ae_is_up",
    "summarize_is_up",
]
