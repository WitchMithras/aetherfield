"""AetherField staging package shim.

For now, re-export selected APIs from the host project's `aetherfield.py` to
allow downstream packages to begin switching imports to `aetherfield_pkg`.

In a full extraction, we will move the implementation here and keep this API
surface stable.
"""

from .core import (
    get_age_sign,
    get_zodiac_by_longitude_dt,
    rotated_zodiac,
    aether_longitude,
    aether_longitude_mt,
    aetherium_longitude_mt,
    aether_sign,
    ecliptic_to_equatorial,
    aether_alignments,
    aether_alignments_mt,
    moon_phase,
    sunrise_sunset,
    AetherField,
    EPHEMERIS_NAME,
    EPHEMERIS_PATH,
    EPHEMERIS_START,
    EPHEMERIS_END,
    in_ephemeris_window,
    is_skyfield_time,
    make_skyfield_time,
    DE421_START,
    DE421_END,
    get_body_key,
    ae_is_up,
    summarize_is_up,
    OBLIQUITY_DEG,
    aetherfield
)

__all__ = [
    "get_zodiac_by_longitude_dt",
    "get_age_sign",
    "rotated_zodiac",
    "OBLIQUITY_DEG",
    "aether_longitude",
    "aether_longitude_mt",
    "aetherium_longitude_mt",
    "aether_sign",
    "aether_alignments",
    "aether_alignments_mt",
    "moon_phase",
    "ecliptic_to_equatorial",
    "sunrise_sunset",
    "AetherField",
    "EPHEMERIS_NAME",
    "EPHEMERIS_PATH",
    "EPHEMERIS_START",
    "EPHEMERIS_END",
    "in_ephemeris_window",
    "is_skyfield_time",
    "make_skyfield_time",
    "DE421_START",
    "DE421_END",
    "get_body_key",
    "ae_is_up",
    "summarize_is_up",
    "aetherfield"
]
