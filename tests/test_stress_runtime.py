from datetime import datetime, timedelta, timezone
import json

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
    monkeypatch.setattr(core, "_HOSTED_CALIBRATION_CACHE", {})
    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

    af = AetherField.load_calibration("AetherField")

    assert isinstance(af, AetherField)
    assert af.rates_deg_per_day == core.MEAN_DEG_PER_DAY


def test_load_calibration_accepts_hosted_scope(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return json.dumps({
                "rates_deg_per_day": {"sun": 1.25},
                "anchors_min": {"sun": 10.0},
                "anchors_max": {"sun": 20.0},
            }).encode("utf-8")

    urls = []

    def fake_urlopen(url, timeout):
        urls.append((url, timeout))
        return FakeResponse()

    import urllib.request

    monkeypatch.setattr(core, "data", None)
    monkeypatch.setattr(core, "_HOSTED_CALIBRATION_CACHE", {})
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    af = AetherField.load_calibration("medium")
    cached = AetherField.load_calibration("medium")

    assert af.rates_deg_per_day["sun"] == 1.25
    assert cached.rates_deg_per_day["sun"] == 1.25
    assert urls == [(f"{core.REMOTE_URL}?scope=medium", 10)]


def test_load_calibration_small_scope_uses_default_hosted_url(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return b'{"rates": {"moon": 13.5}}'

    urls = []

    def fake_urlopen(url, timeout):
        urls.append((url, timeout))
        return FakeResponse()

    import urllib.request

    monkeypatch.setattr(core, "data", None)
    monkeypatch.setattr(core, "_HOSTED_CALIBRATION_CACHE", {})
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    af = AetherField.load_calibration("small")

    assert af.rates_deg_per_day["moon"] == 13.5
    assert urls == [(core.REMOTE_URL, 10)]
