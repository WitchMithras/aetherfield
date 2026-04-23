# AetherField

*AetherField* is a lightweight, modular system for computing astrological positions, signs, and alignments across multiple time representations. This is meant to replace the frozen or outdated zodiac libraries, with a dynamic stellar gazing tool.

It is designed to sit cleanly on top of my own temporal layer `moontime` while remaining flexible enough to integrate with external systems such as Skyfield.

At its core, AetherField answers a simple question:

> *Given a moment in time, where are the bodies — and what do they mean?*

---

## ✨ Features

* 🌌 Compute zodiac signs for planetary bodies
* 🔭 Support for multiple time inputs:

  * `datetime`
  * `MoonTime`
  * Skyfield `Time`
* 🧭 Longitude calculations (tropical + draconic)
* 🧬 Calibration system:

  * No calibration (pure baseline)
  * Local calibration (user-defined)
  * Hosted calibration (auto-fetched)
* 🖥️ CLI interface with automatic calibration

---

## 📦 Installation

```bash
pip install aetherfield
```

---

## 🚀 Quick Example

```python
from aetherfield import AetherField

def example():
    from skyfield.api import load
    from datetime import datetime, timezone
    from moontime import MoonTime

    
    # Three different instances with different calibrations:

    a = AetherField()  # No calibration
    b = AetherField.load_calibration("my_calibration.json")  # Local calibration
    c = AetherField.load_calibration('AetherField')  # Hosted calibration

    # Works with dt
    dt = datetime.now(timezone.utc)

    print("No calibration:", a.sign(dt=dt, body="sun"))  # No calibration
    print("Local calibration:", b.sign(dt=dt, body="sun")) # Local calibration
    print("Hosted calibration:", c.sign(dt=dt, body="sun")) # Hosted calibration

    print("Full suite:", c.alignments(dt=dt))
    
    # Works with skyfield time
    ts = load.timescale()
    sf = ts.from_datetime(dt)

    print("From skyfield time:", c.sign(dt=sf, body="sun"))

    # Works with moontime
    mt = MoonTime.from_datetime(dt)

    print("From moontime:", c.sign(dt=mt, body="sun"))

    print("Longitude:", c.longitude(dt=mt, body="sun"))
    print("Draconic:", c.longitude(dt=mt, body="ascending_node"))

if __name__ == "__main__":
    example()
```

### Example Output

```
No calibration: Gemini
Local calibration: Aries
Hosted calibration: Aries

Full suite: {
  'sun': 'Aries',
  'moon': 'Gemini',
  'mercury': 'Pisces',
  'venus': 'Aries',
  'mars': 'Pisces',
  'jupiter': 'Gemini',
  'saturn': 'Pisces',
  'uranus': 'Aries',
  'neptune': 'Pisces',
  'pluto': 'Capricorn',
  'ascending_node': 'Aquarius',
  'descending_node': 'Leo'
}

From skyfield time: Aries
From moontime: Aries

Longitude: 30.42190333085091
Draconic: 336.2217926416203
```

---

## 🧭 Core Concepts

### AetherField Instance

```python
af = AetherField()
```

Creates a baseline field with no calibration applied.

---

### Calibration

Calibration adjusts how positions are interpreted.

```python
af = af.load_calibration("AetherField")
```

* **Hosted**: Pulled from my server

---

### Sign Lookup

```python
af.sign(dt, "sun")
```

Returns the zodiac sign for a given celestial body.

---

### Full Alignment

```python
af.alignments(dt)
```

Returns all tracked bodies in a single call.

---

### Longitude

```python
af.longitude(dt, "sun")
```

Returns the raw longitude in degrees.

Supports:

* Standard (tropical)
* Draconic (nodes-based)

---

## ⏳ Time Input Flexibility

AetherField accepts multiple time formats seamlessly:

### Python `datetime`

```python
af.sign(datetime.now(), "sun")
```

### MoonTime

```python
af.sign(MoonTime.now(), "sun")
```

### Skyfield

```python
ts = load.timescale()
sf = ts.from_datetime(dt)
af.sign(sf, "sun")
```

---

## 🖥️ CLI Usage

AetherField includes a command-line interface.

```bash
aetherfield --body sun
```

```bash
aetherfield --body moon --dt 2026-04-23T04:21:12
```

```bash
aetherfield --body uranus --mt mt:6739,01,12 --json
```

### Example Output

```
sun @ 2026-04-23T02:05:39.166446+00:00
  Aether:     30.398 deg  (Aries)
```

```
moon @ 2026-04-23T04:21:12+00:00
  Aether:    112.204 deg  (Gemini)
```

```
{
  "body": "uranus",
  "dt": "2026-04-23T11:19:24.019270+00:00",
  "lon": 86.42849018346915,
  "sign": "Taurus"
}
```

The CLI automatically pulls hosted calibration when available.

---

## 🧬 Design Philosophy

AetherField is built to be:

* **Composable** → Works with external time systems
* **Deterministic** → Same input, same output
* **Extensible** → Calibration layers evolve without breaking core logic
* **Decoupled** → Time, data, and interpretation remain separate

---

## 🌙 Ecosystem

AetherField pairs naturally with:

* `moontime` → temporal framework
* Skyfield → astronomical precision

---

## 🧪 Status

Early release. Core systems are stable, but APIs may evolve as calibration and data layers expand.

---

## 🕯️ Closing Note

AetherField doesn’t try to define meaning.

It provides structure — positions, alignments, relationships.

What you build on top of that… is entirely yours.
