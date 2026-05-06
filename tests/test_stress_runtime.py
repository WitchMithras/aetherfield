from datetime import datetime, timedelta, timezone

from aetherfield import core
from aetherfield.core import AetherField


BODIES = [
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
    "ascending_node",
    "descending_node",
]


def test_stress_sign_and_longitude_stability():
    af = AetherField()
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    for hour in range(5_000):
        dt = start + timedelta(hours=hour)
        for body in BODIES:
            sign = af.sign(dt=dt, body=body)
            assert isinstance(sign, str)
            assert sign

            longitude = af.longitude(dt=dt, body=body)
            assert 0.0 <= longitude < 360.0


def test_load_calibration_falls_back_to_uncalibrated_on_hosted_failure(monkeypatch):
    def fail_urlopen(*_args, **_kwargs):
        raise OSError("calibration unavailable")

    import urllib.request

    monkeypatch.setattr(core, "data", None)
    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

    af = AetherField.load_calibration("AetherField")

    assert isinstance(af, AetherField)
    assert af.rates_deg_per_day == core.MEAN_DEG_PER_DAY
