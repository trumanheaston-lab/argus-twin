"""Astronomical objects: the Moon, the planets, bright stars and a set of showpiece
deep-sky objects (Messier). The Sun is deliberately NOT in this list. See safety.py.

Positions come from Skyfield and NASA/JPL's DE421 ephemeris (a one-time 17 MB
download into data/de421.bsp). If that download fails, this module reports no
objects instead of crashing, and satellite mode keeps working.

Every state dict has the same shape as a satellite's, so the dashboard and the
mount code can treat both the same way.
"""
import math
import re
import time

from skyfield import almanac
from skyfield.api import (Star, load_constellation_map, load_constellation_names,
                          position_of_radec)

import tracker
from stars_data import STARS

EPHEMERIS_FILE = 'de421.bsp'
RETRY_SECONDS = 600
CACHE_SECONDS = 2.0

_eph = None
_eph_error = None
_eph_tried = 0.0
_cmap = None
_cnames = None
_vis_cache = (None, None)


# ---- ephemeris --------------------------------------------------------------

def get_ephemeris():
    """The JPL ephemeris, or None if it cannot be loaded (retried every 10 minutes)."""
    global _eph, _eph_error, _eph_tried
    if _eph is not None:
        return _eph
    if _eph_error and time.time() - _eph_tried < RETRY_SECONDS:
        return None
    _eph_tried = time.time()
    try:
        _eph = tracker._loader(EPHEMERIS_FILE)
        _eph_error = None
    except Exception as exc:                    # no network, disk full, ...
        _eph_error = str(exc) or type(exc).__name__
    return _eph


def ephemeris_error():
    return _eph_error


# ---- the catalog -------------------------------------------------------------

def _hms(h, m, s):
    return h + m / 60.0 + s / 3600.0


def _dms(sign, d, m, s):
    return sign * (d + m / 60.0 + s / 3600.0)


OBJECTS = {}


def _add(obj_id, **fields):
    OBJECTS[obj_id] = dict(id=obj_id, **fields)


_add('moon', name='Moon', kind='Moon', bodies=['moon'], wiki='Moon',
     about="Earth's only natural satellite. Craters and the dark maria show well at any "
           "phase, and the best detail is along the terminator, the line between day and night.")
_add('mercury', name='Mercury', kind='Planet', bodies=['mercury', 'mercury barycenter'],
     wiki='Mercury_(planet)',
     about='The smallest planet and the closest to the Sun, so it is only ever seen low in '
           'twilight. Most of the time it is inside the Sun keep-out zone.')
_add('venus', name='Venus', kind='Planet', bodies=['venus', 'venus barycenter'], wiki='Venus',
     about='The brightest planet. A small telescope shows it as a crescent, half or gibbous '
           'disc, like a tiny Moon.')
_add('mars', name='Mars', kind='Planet', bodies=['mars barycenter'], wiki='Mars',
     about='The red planet. A small disc even in a good telescope, best around opposition '
           'every couple of years.')
_add('jupiter', name='Jupiter', kind='Planet', bodies=['jupiter barycenter'], wiki='Jupiter',
     about='The largest planet. A small telescope shows its cloud bands and the four bright '
           'Galilean moons lined up beside it.')
_add('saturn', name='Saturn', kind='Planet', bodies=['saturn barycenter'], wiki='Saturn',
     about='The ringed planet. Its rings are visible even in small telescopes.')
_add('uranus', name='Uranus', kind='Planet', bodies=['uranus barycenter'], wiki='Uranus',
     about='Faint and distant. It shows as a tiny blue-green disc in a telescope.')
_add('neptune', name='Neptune', kind='Planet', bodies=['neptune barycenter'], wiki='Neptune',
     about='The most distant planet. Very faint, a tiny blue dot in a small telescope.')

# Stars come from stars_data.py. A few names have an article title that differs.
_STAR_WIKI = {'Castor': 'Castor_(star)', 'Pollux': 'Pollux_(star)', 'Agena': 'Beta_Centauri',
              'Albereo': 'Albireo', 'Polaris': 'Polaris'}
for _name, _ra, _dec, _pmra, _pmdec, _mag in STARS:
    _add('star:' + re.sub(r'[^a-z0-9]+', '', _name.lower()), name=_name, kind='Star', mag=_mag,
         star=Star(ra_hours=_ra, dec_degrees=_dec, ra_mas_per_year=_pmra, dec_mas_per_year=_pmdec),
         wiki=_STAR_WIKI.get(_name, _name),
         about='A bright star. It stays a point of light even in a telescope, which makes it '
               'a good target for checking pointing and focus.')

# Showpiece Messier objects. Positions are catalog values rounded to about an arcminute
# (fine for a phone camera behind a 127 mm telescope). Descriptions are deliberately brief.
_MESSIER = [
    (1, 'Crab Nebula', 'Nebula', (5, 34, 31.9), (1, 22, 0, 52), 8.4, 'Crab_Nebula',
     'The remains of a supernova seen in the year 1054, roughly 6,500 light-years away.'),
    (3, 'Messier 3', 'Cluster', (13, 42, 11.6), (1, 28, 22, 38), 6.2, 'Messier_3',
     'A bright globular star cluster in Canes Venatici.'),
    (5, 'Messier 5', 'Cluster', (15, 18, 33.8), (1, 2, 4, 58), 5.7, 'Messier_5',
     'One of the finest globular clusters in the northern sky.'),
    (8, 'Lagoon Nebula', 'Nebula', (18, 3, 37.0), (-1, 24, 23, 12), 6.0, 'Lagoon_Nebula',
     'A large glowing cloud of gas in Sagittarius where stars are forming.'),
    (11, 'Wild Duck Cluster', 'Cluster', (18, 51, 5.0), (-1, 6, 16, 12), 6.3, 'Wild_Duck_Cluster',
     'A rich, dense open star cluster in Scutum.'),
    (13, 'Great Hercules Cluster', 'Cluster', (16, 41, 41.2), (1, 36, 27, 41), 5.8,
     'Messier_13', 'The best-known globular cluster of the northern sky, about 22,000 light-years away.'),
    (16, 'Eagle Nebula', 'Nebula', (18, 18, 48.0), (-1, 13, 49, 0), 6.0, 'Eagle_Nebula',
     'A star-forming region that contains the "Pillars of Creation".'),
    (17, 'Omega Nebula', 'Nebula', (18, 20, 26.0), (-1, 16, 10, 36), 6.0, 'Omega_Nebula',
     'A bright star-forming nebula in Sagittarius, also called the Swan Nebula.'),
    (20, 'Trifid Nebula', 'Nebula', (18, 2, 23.0), (-1, 23, 1, 48), 6.3, 'Trifid_Nebula',
     'A glowing nebula divided into three lobes by dark dust lanes.'),
    (22, 'Messier 22', 'Cluster', (18, 36, 23.9), (-1, 23, 54, 17), 5.1, 'Messier_22',
     'One of the brightest globular clusters, in Sagittarius.'),
    (27, 'Dumbbell Nebula', 'Nebula', (19, 59, 36.3), (1, 22, 43, 16), 7.5, 'Dumbbell_Nebula',
     'A planetary nebula, the shed outer layers of a dying star, about 1,200 light-years away.'),
    (31, 'Andromeda Galaxy', 'Galaxy', (0, 42, 44.3), (1, 41, 16, 9), 3.4, 'Andromeda_Galaxy',
     'The nearest large spiral galaxy, roughly 2.5 million light-years away.'),
    (33, 'Triangulum Galaxy', 'Galaxy', (1, 33, 50.9), (1, 30, 39, 37), 5.7, 'Triangulum_Galaxy',
     'A large, faint spiral galaxy that needs a dark sky.'),
    (42, 'Orion Nebula', 'Nebula', (5, 35, 17.3), (-1, 5, 23, 28), 4.0, 'Orion_Nebula',
     'A stellar nursery roughly 1,300 light-years away, visible to the naked eye as a fuzzy "star".'),
    (44, 'Beehive Cluster', 'Cluster', (8, 40, 24.0), (1, 19, 40, 0), 3.1, 'Beehive_Cluster',
     'A large open star cluster in Cancer. Best in binoculars or at low power.'),
    (45, 'Pleiades', 'Cluster', (3, 47, 24.0), (1, 24, 7, 0), 1.6, 'Pleiades',
     'The Seven Sisters, a bright open cluster about 440 light-years away. Too large for most '
     'telescopes to frame fully.'),
    (51, 'Whirlpool Galaxy', 'Galaxy', (13, 29, 52.7), (1, 47, 11, 43), 8.4, 'Whirlpool_Galaxy',
     'A spiral galaxy interacting with a smaller companion, roughly 23 million light-years away.'),
    (57, 'Ring Nebula', 'Nebula', (18, 53, 35.1), (1, 33, 1, 45), 8.8, 'Ring_Nebula',
     'A small planetary nebula in Lyra, a glowing ring of gas.'),
    (81, "Bode's Galaxy", 'Galaxy', (9, 55, 33.2), (1, 69, 3, 55), 6.9, 'Messier_81',
     'A bright spiral galaxy in Ursa Major, roughly 12 million light-years away.'),
    (82, 'Cigar Galaxy', 'Galaxy', (9, 55, 52.2), (1, 69, 40, 47), 8.4, 'Messier_82',
     'A starburst galaxy next to M81.'),
    (92, 'Messier 92', 'Cluster', (17, 17, 7.4), (1, 43, 8, 11), 6.4, 'Messier_92',
     'A bright globular cluster in Hercules.'),
    (97, 'Owl Nebula', 'Nebula', (11, 14, 47.7), (1, 55, 1, 9), 9.9, 'Owl_Nebula',
     'A faint planetary nebula that needs a dark sky.'),
    (101, 'Pinwheel Galaxy', 'Galaxy', (14, 3, 12.6), (1, 54, 20, 57), 7.9, 'Pinwheel_Galaxy',
     'A large face-on spiral galaxy with a low surface brightness.'),
    (104, 'Sombrero Galaxy', 'Galaxy', (12, 39, 59.4), (-1, 11, 37, 23), 8.0, 'Sombrero_Galaxy',
     'A spiral galaxy seen nearly edge-on, with a bright core and a dark dust lane.'),
]
for _n, _name, _kind, _ra, _dec, _mag, _wiki, _about in _MESSIER:
    _add(f'm{_n}', name=f'M{_n} {_name}' if not _name.startswith('Messier') else _name,
         kind=_kind, mag=_mag,
         star=Star(ra_hours=_hms(*_ra), dec_degrees=_dms(*_dec)),
         wiki=_wiki, about=_about)

KIND_ORDER = ['Moon', 'Planet', 'Star', 'Galaxy', 'Nebula', 'Cluster']


# ---- positions ---------------------------------------------------------------

def _body(eph, names):
    for name in names:
        try:
            return eph[name]
        except KeyError:
            continue
    raise KeyError(names[0])


def _observe(obj, t):
    """Astrometric position of obj from the observer at time t, or None."""
    eph = get_ephemeris()
    if eph is None:
        return None
    observer = eph['earth'] + tracker.OBSERVER
    target = _body(eph, obj['bodies']) if 'bodies' in obj else obj['star']
    return observer.at(t).observe(target)


def _altaz(astrometric):
    alt, az, dist = astrometric.apparent().altaz()
    return alt.degrees, az.degrees, dist


def _magnitude(obj, astrometric):
    if obj['kind'] == 'Planet':
        try:
            from skyfield.magnitudelib import planetary_magnitude
            return round(float(planetary_magnitude(astrometric)), 1)
        except Exception:
            return None
    return obj.get('mag')


def _constellation(astrometric):
    global _cmap, _cnames
    if _cmap is None:
        _cmap = load_constellation_map()
        _cnames = dict(load_constellation_names())
    ra, dec, _ = astrometric.radec()
    abbr = _cmap(position_of_radec(ra.hours, dec.degrees))
    return _cnames.get(abbr, abbr)


def state(obj_id, t=None):
    """Pointing data for one object, in the same shape as a satellite state."""
    obj = OBJECTS.get(obj_id)
    if obj is None:
        return None
    if t is None:
        t = tracker.ts.now()
    base = {'id': obj_id, 'name': obj['name'], 'kind': obj['kind']}
    a1 = _observe(obj, t)
    if a1 is None:
        return dict(base, az=None, el=None, range_km=None, az_rate=None, el_rate=None,
                    above=False, mag=None, error='ephemeris unavailable')
    el, az, dist = _altaz(a1)
    el, az = float(el), float(az)
    el2, az2, _ = _altaz(_observe(obj, tracker.ts.tt_jd(t.tt + 1.0 / 86400.0)))
    is_near = obj['kind'] in ('Moon', 'Planet')
    return dict(base,
                az=round(float(az), 3), el=round(float(el), 3),
                range_km=round(float(dist.km), 1) if is_near else None,
                az_rate=round(float(((az2 - az + 180.0) % 360.0) - 180.0), 4),
                el_rate=round(float(el2 - el), 4),
                above=bool(el > 0.0),
                mag=_magnitude(obj, a1))


def visible(t=None, min_el=0.0):
    """Every catalog object above min_el degrees, brightest first. Cached for a
    couple of seconds because computing the whole catalog is not free."""
    global _vis_cache
    if t is None:
        t = tracker.ts.now()
    key = (int(t.tt * 86400.0 / CACHE_SECONDS), min_el)
    if _vis_cache[0] == key:
        return _vis_cache[1]
    out = []
    if get_ephemeris() is not None:
        for obj in OBJECTS.values():
            a = _observe(obj, t)
            el, az, _ = _altaz(a)
            if el > min_el:
                out.append({'id': obj['id'], 'name': obj['name'], 'kind': obj['kind'],
                            'mag': _magnitude(obj, a), 'az': round(float(az), 2),
                            'el': round(float(el), 2)})
    out.sort(key=lambda o: (KIND_ORDER.index(o['kind']), o['mag'] if o['mag'] is not None else 99))
    _vis_cache = (key, out)
    return out


def moon_phase(t):
    """(illuminated percent, phase name)"""
    eph = get_ephemeris()
    deg = almanac.moon_phase(eph, t).degrees % 360.0
    percent = (1.0 - math.cos(math.radians(deg))) / 2.0 * 100.0
    if deg < 22.5 or deg >= 337.5:
        name = 'New Moon'
    elif deg < 67.5:
        name = 'Waxing crescent'
    elif deg < 112.5:
        name = 'First quarter'
    elif deg < 157.5:
        name = 'Waxing gibbous'
    elif deg < 202.5:
        name = 'Full Moon'
    elif deg < 247.5:
        name = 'Waning gibbous'
    elif deg < 292.5:
        name = 'Last quarter'
    else:
        name = 'Waning crescent'
    return round(percent, 1), name


def info(obj_id, t=None):
    obj = OBJECTS.get(obj_id)
    if obj is None:
        return None
    if t is None:
        t = tracker.ts.now()
    out = {'id': obj_id, 'name': obj['name'], 'kind': obj['kind'], 'about': obj.get('about'),
           'wiki': obj.get('wiki')}
    a = _observe(obj, t)
    if a is None:
        out['error'] = 'ephemeris unavailable'
        return out
    out['constellation'] = _constellation(a)
    out['mag'] = _magnitude(obj, a)
    if obj['kind'] in ('Moon', 'Planet'):
        dist = a.distance()
        out['distance'] = (f'{float(dist.km):,.0f} km' if obj['kind'] == 'Moon'
                           else f'{float(dist.au):.2f} AU')
    if obj['kind'] == 'Moon':
        out['illumination'], out['phase'] = moon_phase(t)
    return out