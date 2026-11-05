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

## Gimbal

`src/gimbal.py` talks to the controller using the line protocol in `docs/PROTOCOL.md`. Click **Connect Simulator** on the dashboard to test the whole chain with no hardware: the simulator behaves like the firmware (limited slew speed, glides between updates, stops if updates stop). **Connect Serial Port** uses the real board over USB. `firmware/argus_gimbal/argus_gimbal.ino` is the Arduino Nano 33 BLE sketch (needs the AccelStepper library). Run `python tests/test_gimbal.py` for the bridge tests.

`Connect Celestron` drives a Celestron NexStar alt-az mount through the hand controller's USB port instead. See `docs/CELESTRON.md` for setup, first-test steps and safety notes. Tests: `python tests/test_nexstar.py`.

## Astronomy mode

The ASTRONOMY button switches the dashboard from satellites to the Moon, planets, 85 bright stars
and 24 Messier objects. Same panels, same tracking lock. Positions come from the NASA/JPL DE421
ephemeris (`data/de421.bsp`, about 17 MB, downloaded automatically the first time the server runs;
it needs internet once). The Messier coordinates and blurbs were entered by hand: spot-check them
against Stellarium before trusting them for a faint target.

## Horizon mask (buildings and trees)

`EDIT HORIZON MASK` takes one `azimuth, elevation` pair per line (0 = north, 90 = east). Anything below
the line joining the points is hidden from the lists and never tracked. Easiest way to build it: aim the
scope at the top of each tree or roofline with the hand controller and press `ADD MASK POINT FROM MOUNT`.
It is saved in `data/horizon.json`. With no mask the floor is a flat 10 degrees.

## Sun safety

Targets within 15 degrees of the Sun are blocked, and so is any slew whose straight path crosses that
zone. This is a software guard, not a substitute for a certified solar filter or for watching the scope.
It checks an approximate straight az/el path, not the mount's true motion.

## Known limits

- The firmware has not been run on real hardware yet.
- TLE accuracy degrades over days. Fine for a desktop turret, not for precision work.
- Pointing assumes a flat horizon at your location. Trees and buildings are not modeled.