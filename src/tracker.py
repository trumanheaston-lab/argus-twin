"""Orbital math for Argus-Twin. Pure Python, no web code in here.

Everything the dashboard and (later) the gimbal need comes from this file:
  - which satellites are above the horizon right now
  - where to point (azimuth / elevation), how far away, how fast the angles change
"""
import math
import os
import time

from skyfield.api import Loader, wgs84

# ---- Configuration ---------------------------------------------------------

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')

# CelesTrak "visual" group: ~100-150 bright, easy-to-spot satellites.
TLE_URL = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=visual&FORMAT=tle'
TLE_FILE = 'visual.tle'

# CelesTrak asks people not to download the same group more than about once
# every 2 hours. LEO TLEs drift roughly 1 km per day, which is fine for a
# desktop gimbal, so we refresh twice a day.
MAX_TLE_AGE_HOURS = 12
RELOAD_CHECK_SECONDS = 3600     # how often we re-check whether the file is stale
MIN_FORCED_REFRESH_SECONDS = 600  # the Refresh button cannot hammer the server

# Below this elevation, trees, rooftops and atmosphere make tracking unreliable,
# and the list fills with objects you could never actually point at.
MIN_ELEVATION_DEG = 10.0

# Dripping Springs, TX
OBSERVER = wgs84.latlon(30.1902, -98.0867, elevation_m=350)

_loader = Loader(DATA_DIR)
ts = _loader.timescale()

_sats = None            # {norad_id: EarthSatellite}
_loaded_at = 0.0        # when we last checked/loaded the TLE file
_last_download = 0.0    # when we last forced a network download


# ---- TLE loading -----------------------------------------------------------

def _tle_path():
    return os.path.join(DATA_DIR, TLE_FILE)


def _file_is_stale():
    path = _tle_path()
    if not os.path.exists(path):
        return True
    return (time.time() - os.path.getmtime(path)) > MAX_TLE_AGE_HOURS * 3600


def load_satellites(force=False):
    """Load satellites from the cached TLE file, downloading a fresh one only
    when the cache is missing or stale. If the download fails and an old file
    exists, we keep using the old file instead of crashing."""
    global _sats, _loaded_at, _last_download

    reload_file = force or _file_is_stale()
    try:
        sat_list = _loader.tle_file(TLE_URL, reload=reload_file, filename=TLE_FILE)
        if reload_file:
            _last_download = time.time()
    except Exception:
        if not os.path.exists(_tle_path()):
            raise
        sat_list = _loader.tle_file(TLE_URL, reload=False, filename=TLE_FILE)

    _sats = {sat.model.satnum: sat for sat in sat_list}
    _loaded_at = time.time()
    return _sats


def get_satellites():
    """Cached satellite table. Re-checks the file about once an hour."""
    if _sats is None or (time.time() - _loaded_at) > RELOAD_CHECK_SECONDS:
        load_satellites()
    return _sats


def force_refresh():
    """Called by the Refresh button. Returns (ok, message)."""
    wait = MIN_FORCED_REFRESH_SECONDS - (time.time() - _last_download)
    if wait > 0:
        return False, f'TLE downloaded recently. Try again in {int(wait)} s.'
    try:
        load_satellites(force=True)
    except Exception as exc:
        return False, f'Download failed: {exc}'
    return True, f'Loaded {len(_sats)} satellites.'


# ---- Pointing math ---------------------------------------------------------

def _altaz(sat, t):
    """Satellite minus observer gives a vector from you to the satellite.
    Skyfield turns that vector into elevation, azimuth and range."""
    alt, az, dist = (sat - OBSERVER).at(t).altaz()
    return alt.degrees, az.degrees, dist.km


def _wrap180(delta):
    """Smallest signed difference between two compass angles.
    Without this, 359.9 -> 0.1 looks like a jump of -359.8 degrees."""
    return (delta + 180.0) % 360.0 - 180.0


def get_state(sat, t):
    """Pointing data for one satellite at time t.

    az_rate / el_rate are in degrees per second. They come from comparing the
    position now with the position one second later."""
    el, az, rng = _altaz(sat, t)
    t_next = ts.tt_jd(t.tt + 1.0 / 86400.0)
    el2, az2, _ = _altaz(sat, t_next)
    # An old or decayed TLE can make SGP4 return NaN. NaN is not valid JSON and
    # would break the dashboard, so report "no solution" instead.
    if not all(math.isfinite(v) for v in (el, az, rng, el2, az2)):
        return {
            'norad': int(sat.model.satnum),
            'name': sat.name,
            'az': None, 'el': None, 'range_km': None,
            'az_rate': None, 'el_rate': None,
            'above': False,
            'error': 'no solution (TLE too old or satellite decayed)',
        }
    return {
        'norad': int(sat.model.satnum),
        'name': sat.name,
        'az': round(az, 3),
        'el': round(el, 3),
        'range_km': round(rng, 1),
        'az_rate': round(_wrap180(az2 - az), 4),
        'el_rate': round(el2 - el, 4),
        'above': bool(el > 0.0),
    }


def overhead(t=None, min_el=None):
    """Every satellite in the catalog above min_el degrees, sorted by name."""
    if t is None:
        t = ts.now()
    if min_el is None:
        min_el = MIN_ELEVATION_DEG
    out = []
    for sat in get_satellites().values():
        el, _, _ = _altaz(sat, t)
        if el > min_el:
            out.append(get_state(sat, t))
    out.sort(key=lambda s: s['name'])
    return out


def tracked(norad, t=None):
    """State for one satellite even if it is below the horizon, or None."""
    if t is None:
        t = ts.now()
    sat = get_satellites().get(int(norad))
    return get_state(sat, t) if sat else None


def sat_info(norad, t=None):
    """Orbit facts computed from the TLE itself (no hand-typed numbers)."""
    if t is None:
        t = ts.now()
    sat = get_satellites().get(int(norad))
    if sat is None:
        return None
    period_min = 2.0 * math.pi / sat.model.no_kozai
    return {
        'norad': int(sat.model.satnum),
        'name': sat.name,
        'inclination_deg': round(math.degrees(sat.model.inclo), 2),
        'period_min': round(period_min, 2),
        'tle_epoch': sat.epoch.utc_iso(),
        'tle_age_days': round(t.tt - sat.epoch.tt, 2),
    }