from datetime import datetime, timedelta, timezone
import json

from aetherfield import core
from aetherfield.deploy_calibration import write_minimal_calibration
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


def test_build_minimal_calibration_recreates_current_alignments(tmp_path):
    dt = datetime(2026, 5, 10, 12, 30, tzinfo=timezone.utc)
    source = AetherField()
    payload = core.build_minimal_calibration(dt=dt, source=source)

    assert payload["calibration_time"] == dt.isoformat()
    assert payload["piecewise"] == {}
    assert payload["alignments"] == source.alignments(dt)

    path = tmp_path / "minimal_calibration.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = AetherField.load_calibration(str(path))
    assert loaded.alignments(dt) == payload["alignments"]


def test_deploy_calibration_writer_outputs_minimal_file(tmp_path):
    output = tmp_path / "aetherfield_calibration.json"
    payload = write_minimal_calibration(
        str(output),
        dt="2026-05-10T12:30:00+00:00",
        use_hosted=False,
    )

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved == payload
    assert saved["schema_version"] == core.MINIMAL_CALIBRATION_VERSION
    assert set(saved["anchors_min"]) == set(saved["alignments"])
