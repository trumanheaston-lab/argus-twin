# Argus-Twin

A ground-station dashboard that finds satellites above Dripping Springs, TX, computes where to point at them, and (next) drives a 3D-printed pan-tilt gimbal to follow the one you pick.

## Run it

From the project root, with the virtual environment active:

    pip install -r requirements.txt
    python src/server.py

Open http://localhost:5000. The first start downloads the CelesTrak "visual" TLE group into `data/visual.tle`.

Run the offline tests with `python tests/test_backend.py`.

## How the backend works

**`src/tracker.py` is the math.** Nothing in it knows about the web.

1. A TLE (two-line element set) describes one satellite's orbit. CelesTrak publishes them; we cache the file and re-download it only when it is more than 12 hours old.
2. Skyfield's SGP4 model turns a TLE plus a time into a position in space.
3. `satellite - observer` gives a vector from you to the satellite. `.altaz()` converts that vector into elevation (angle above the horizon), azimuth (compass heading, 0 = north) and range (km).
4. Rates: the same calculation one second later, subtracted from now, gives degrees per second. The gimbal firmware will use these to move smoothly between 1 Hz updates.
5. Azimuth wraps at 360. `_wrap180` makes sure 359.9 to 0.1 counts as +0.2 degrees, not -359.8.
6. If a TLE is too old to propagate, SGP4 returns NaN. We turn that into `null` plus an error message, because NaN is not valid JSON and would break the page.

**`src/server.py` is the web layer (Flask).**

| Route | What it does |
|---|---|
| `GET /api/state?track=<norad>` | Every satellite above the horizon, plus the one you picked even if it has set. Polled once per second. |
| `GET /api/info/<norad>` | Inclination, period and TLE age computed from the TLE, plus the write-up from `catalog.py` if there is one. |
| `POST /api/refresh` | Forces a new TLE download. Refuses if one happened in the last 10 minutes. |

**`src/catalog.py`** holds the hand-written descriptions and Wikipedia titles. Satellites not listed there still work; they just show orbit data and no image.

## Known limits

- The gimbal is not connected yet. Buttons log a message and send nothing.
- TLE accuracy degrades over days. Fine for a desktop turret, not for precision work.
- Pointing assumes a flat horizon at your location. Trees and buildings are not modeled.