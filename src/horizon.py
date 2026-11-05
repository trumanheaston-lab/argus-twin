"""Horizon mask: buildings, trees and anything else that blocks your view.

The mask is a list of (azimuth, elevation) points going around the compass. For
any azimuth, the lowest usable elevation is found by drawing straight lines
between neighbouring points (wrapping from 359 back to 0). With no points the
mask is a flat DEFAULT_FLOOR_DEG everywhere.

To model a sharp edge such as the corner of a house, put two points close
together in azimuth. Targets below the mask are hidden from the lists and are
never sent to the mount.
"""
import json
import os
import threading

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'horizon.json')
DEFAULT_FLOOR_DEG = 10.0
MAX_POINTS = 360

_lock = threading.RLock()
_points = None                  # [(az, el), ...] sorted by az


def validate(raw):
    """Turn user input into a clean sorted list of (az, el). Raises ValueError."""
    if not isinstance(raw, (list, tuple)):
        raise ValueError('points must be a list')
    if len(raw) > MAX_POINTS:
        raise ValueError(f'at most {MAX_POINTS} points')
    best = {}
    for item in raw:
        try:
            if isinstance(item, dict):
                az, el = float(item['az']), float(item['el'])
            else:
                az, el = float(item[0]), float(item[1])
        except (KeyError, IndexError, TypeError, ValueError):
            raise ValueError(f'bad point: {item!r}')
        if az != az or el != el:
            raise ValueError('NaN is not allowed')
        if not 0.0 <= az <= 360.0:
            raise ValueError(f'azimuth {az} must be between 0 and 360')
        if not 0.0 <= el <= 89.0:
            raise ValueError(f'elevation {el} must be between 0 and 89')
        az = round(az % 360.0, 2)
        best[az] = max(el, best.get(az, 0.0))      # same azimuth twice: keep the higher obstacle
    return sorted((az, round(el, 2)) for az, el in best.items())


def load():
    global _points
    with _lock:
        try:
            with open(DATA_FILE, encoding='utf-8') as f:
                _points = validate(json.load(f)['points'])
        except (OSError, ValueError, KeyError, TypeError):
            _points = []
        return list(_points)


def points():
    with _lock:
        if _points is None:
            load()
        return list(_points)


def set_points(raw):
    """Validate, store and save. Returns the cleaned list."""
    global _points
    clean = validate(raw)
    with _lock:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        tmp = DATA_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'points': [[az, el] for az, el in clean]}, f, indent=1)
        os.replace(tmp, DATA_FILE)
        _points = clean
        return list(clean)


def add_point(az, el, merge_within_deg=1.0):
    """Add one point. A point already within merge_within_deg is replaced by the
    higher of the two, so repeated sampling of the same spot does not pile up."""
    az = az % 360.0

    def dist(a):
        d = abs(a - az)
        return min(d, 360.0 - d)

    near = [(a, e) for a, e in points() if dist(a) <= merge_within_deg]
    far = [(a, e) for a, e in points() if dist(a) > merge_within_deg]
    el = max([el] + [e for _, e in near])
    far.append((az, max(0.0, min(89.0, el))))
    return set_points(far)


def floor(az):
    """Lowest usable elevation at this azimuth."""
    pts = points()
    if not pts:
        return DEFAULT_FLOOR_DEG
    if len(pts) == 1:
        return pts[0][1]
    az = az % 360.0
    # neighbours on either side, wrapping around
    before = [p for p in pts if p[0] <= az]
    after = [p for p in pts if p[0] > az]
    a0, e0 = before[-1] if before else (pts[-1][0] - 360.0, pts[-1][1])
    a1, e1 = after[0] if after else (pts[0][0] + 360.0, pts[0][1])
    if a1 == a0:
        return e0
    return e0 + (e1 - e0) * (az - a0) / (a1 - a0)


def blocked(az, el):
    return el < floor(az)


def profile(step_deg=5):
    """The mask sampled around the compass, for drawing."""
    return [{'az': a, 'el': round(floor(a), 2)} for a in range(0, 360, step_deg)]