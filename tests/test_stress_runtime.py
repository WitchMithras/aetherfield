from datetime import datetime, timedelta, timezone

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
