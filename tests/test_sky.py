"""Tests for astronomy mode, the Sun keep-out and the horizon mask.
Run from the project root:  python tests/test_sky.py

Needs data/de421.bsp for the astronomy parts. The server downloads it on first run.
If it is missing those parts are skipped (and say so). The cross-check against an
independent implementation runs only if pyephem is installed (pip install ephem).
"""
import datetime
import math
import os
import random
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

import horizon
import safety
import server
import sky
import targets
import tracker

horizon.DATA_FILE = os.path.join(tempfile.mkdtemp(), 'horizon.json')
horizon._points = None
client = server.app.test_client()

HAVE_EPH = sky.get_ephemeris() is not None
if not HAVE_EPH:
    print('NOTE: data/de421.bsp not available, skipping astronomy checks:', sky.ephemeris_error())


# ---- 1. Sun position against the JPL ephemeris -------------------------------------
if HAVE_EPH:
    eph = sky.get_ephemeris()
    obs = eph['earth'] + tracker.OBSERVER
    random.seed(7)
    worst = 0.0
    for _ in range(120):
        t = tracker.ts.tt_jd(2461041.5 + random.uniform(-3650, 3650))
        alt, az, _ = obs.at(t).observe(eph['sun']).apparent().altaz()
        a2, z2 = safety.sun_altaz(t)
        worst = max(worst, safety.separation(az.degrees, alt.degrees, z2, a2))
    assert worst < 0.1, worst
    print('analytic Sun matches JPL to %.3f deg OK' % worst)

# ---- 2. Sun keep-out logic (Sun position faked so the test is deterministic) --------
real_sun = safety.sun_altaz
safety.sun_altaz = lambda t=None: (30.0, 180.0)
assert safety.keepout_reason(180.0, 30.0) is not None            # right at the Sun
assert safety.keepout_reason(180.0, 44.0) is not None            # 14 degrees away
assert safety.keepout_reason(180.0, 50.0) is None                # 20 degrees away
assert safety.keepout_reason(0.0, 30.0) is None                  # opposite side of the sky
assert safety.path_reason((150.0, 30.0), (210.0, 30.0)) is not None    # slews across the Sun
assert safety.path_reason((0.0, 30.0), (60.0, 30.0)) is None
assert safety.path_reason((170.0, 80.0), (190.0, 80.0)) is None        # passes high overhead of it
safety.sun_altaz = lambda t=None: (-30.0, 0.0)                   # night
assert safety.keepout_reason(0.0, 5.0) is None and safety.path_reason((0, 0), (90, 40)) is None
safety.sun_altaz = lambda t=None: (-1.0, 90.0)                   # just below the horizon: still treated as up
assert safety.keepout_reason(90.0, 3.0) is not None
safety.sun_altaz = real_sun
assert safety.separation(0, 0, 180, 0) == 180.0 or abs(safety.separation(0, 0, 180, 0) - 180.0) < 1e-6
assert abs(safety.separation(10, 0, 10, 90) - 90.0) < 1e-6
print('Sun keep-out logic OK')

# ---- 3. Horizon mask ---------------------------------------------------------------
assert horizon.points() == [] and horizon.floor(123.0) == horizon.DEFAULT_FLOOR_DEG
assert horizon.DEFAULT_FLOOR_DEG == tracker.MIN_ELEVATION_DEG
horizon.set_points([(90, 20), (180, 40)])
assert abs(horizon.floor(135.0) - 30.0) < 1e-9
assert horizon.floor(90.0) == 20.0 and horizon.floor(180.0) == 40.0
assert abs(horizon.floor(315.0) - 30.0) < 1e-9                    # wraps: halfway from 40@180 round to 20@450
horizon.set_points([(10, 30), (350, 10)])
assert abs(horizon.floor(0.0) - 20.0) < 1e-9                      # wrap across north
horizon.set_points([(45, 25)])
assert horizon.floor(200.0) == 25.0                               # one point: flat
assert horizon.blocked(10.0, 24.0) and not horizon.blocked(10.0, 26.0)
for bad in ([(400, 10)], [(10, 95)], [(10, -1)], [('a', 1)], 'nope', [(float('nan'), 5)],
            [(i, 10) for i in range(361)]):
    try:
        horizon.validate(bad)
        raise AssertionError('should have rejected %r' % (bad,))
    except ValueError:
        pass
assert horizon.validate([(90, 10), (90, 30), (10, 5)]) == [(10.0, 5.0), (90.0, 30.0)]   # sorted, same az keeps higher
horizon.set_points([])
horizon.add_point(100.0, 20.0)
horizon.add_point(100.4, 35.0)                                    # within 1 degree: merged, higher wins
horizon.add_point(100.4, 10.0)
assert horizon.points() == [(100.4, 35.0)], horizon.points()
horizon.add_point(200.0, 15.0)
horizon._points = None                                            # force a reload from disk
assert sorted(horizon.points()) == [(100.4, 35.0), (200.0, 15.0)]
assert len(horizon.profile()) == 72
open(horizon.DATA_FILE, 'w').write('{ this is not json')
horizon._points = None
assert horizon.points() == []                                     # a corrupt file never crashes the app
horizon.set_points([])
print('horizon mask OK')

# ---- 4. Target ids -------------------------------------------------------------------
assert targets.normalize('25544') == 25544 and targets.normalize(25544) == 25544
assert targets.normalize('Jupiter') == 'jupiter' and targets.normalize('star:sirius') == 'star:sirius'
for bad in ('bogus', None, True, '', 'sun'):
    try:
        targets.normalize(bad)
        raise AssertionError('should have rejected %r' % (bad,))
    except ValueError:
        pass
assert 'sun' not in sky.OBJECTS
print('target ids OK (and there is no Sun in the catalog)')

# ---- 5. Catalog sanity -----------------------------------------------------------------
kinds = {}
for o in sky.OBJECTS.values():
    kinds[o['kind']] = kinds.get(o['kind'], 0) + 1
assert kinds['Planet'] == 7 and kinds['Moon'] == 1 and kinds['Star'] >= 50 and kinds['Galaxy'] >= 4
assert len({o['name'] for o in sky.OBJECTS.values()}) == len(sky.OBJECTS), 'duplicate names'
for o in sky.OBJECTS.values():
    if 'star' in o:
        assert -90 < o['star'].dec.degrees < 90 and 0 <= o['star'].ra.hours < 24, o['name']
print('catalog:', kinds)

if HAVE_EPH:
    # ---- 6. Cross-check against an independent implementation -------------------------
    try:
        import importlib
        ephem = importlib.import_module('ephem')
    except ImportError:
        ephem = None
        print('pyephem not installed: skipping independent cross-check (pip install ephem)')
    if ephem:
        def ephem_altaz(make, when):
            o = ephem.Observer()
            o.lat, o.lon, o.elevation, o.pressure = '30.1902', '-98.0867', 350, 0   # pressure 0: no refraction
            o.date = when
            b = make()
            b.compute(o)
            return math.degrees(b.alt), math.degrees(b.az)

        checks = [('moon', ephem.Moon), ('mars', ephem.Mars), ('jupiter', ephem.Jupiter),
                  ('saturn', ephem.Saturn), ('venus', ephem.Venus),
                  ('star:sirius', lambda: ephem.star('Sirius')), ('star:vega', lambda: ephem.star('Vega')),
                  ('star:arcturus', lambda: ephem.star('Arcturus')),
                  ('star:polaris', lambda: ephem.star('Polaris'))]
        worst = {}
        for hour in (0, 5, 10, 15, 20):
            when = datetime.datetime(2026, 11, 5, hour, 17, 0)
            t = tracker.ts.utc(2026, 11, 5, hour, 17, 0)
            for oid, make in checks:
                st = sky.state(oid, t)
                alt, az = ephem_altaz(make, when)
                d = safety.separation(st['az'], st['el'], az, alt)
                worst[oid] = max(worst.get(oid, 0.0), d)
        for oid, d in worst.items():
            assert d < 0.25, (oid, d)
        print('agrees with pyephem (worst per object, degrees):',
              {k: round(v, 3) for k, v in worst.items()})

    # ---- 7. State, visibility and info -------------------------------------------------
    t = tracker.ts.utc(2026, 11, 5, 3, 0, 0)
    for oid in sky.OBJECTS:
        st = sky.state(oid, t)
        assert 0.0 <= st['az'] < 360.0 and -90.0 <= st['el'] <= 90.0, (oid, st)
        assert abs(st['az_rate']) < 1.0 and abs(st['el_rate']) < 1.0, (oid, st)   # deg/s: the sky turns slowly
        i = sky.info(oid, t)
        assert i['constellation'] and i['name'] == sky.OBJECTS[oid]['name'], (oid, i)
    moon = sky.info('moon', t)
    assert 0.0 <= moon['illumination'] <= 100.0 and moon['phase'] and moon['distance'].endswith(' km')
    assert sky.info('jupiter', t)['distance'].endswith(' AU')
    assert sky.info('nonsense') is None and sky.state('nonsense') is None
    vis = sky.visible(t, 0.0)
    assert vis and all(o['el'] > 0 for o in vis)
    order = [sky.KIND_ORDER.index(o['kind']) for o in vis]
    assert order == sorted(order), 'list should be grouped by kind'
    assert sky.visible(t, 0.0) is vis, 'second call should hit the cache'
    print('states / info / visibility OK: %d of %d objects above the horizon' % (len(vis), len(sky.OBJECTS)))

    # ---- 8. Server routes -------------------------------------------------------------
    r = client.get('/api/sky/state?track=jupiter').get_json()
    assert r['ephemeris'] is True and isinstance(r['daylight'], bool) and 'sun' in r
    assert r['tracked']['id'] == 'jupiter' and 'blocked' in r['tracked']
    assert all('near_sun' in o for o in r['targets'])
    assert client.get('/api/sky/state').get_json()['tracked'] is None
    assert client.get('/api/sky/info/Jupiter').get_json()['kind'] == 'Planet'
    assert client.get('/api/sky/info/nope').status_code == 404
    flat = client.get('/api/sky/state?min_el=89').get_json()
    assert all(o['el'] > 89 for o in flat['targets'])
    horizon.set_points([(0, 85), (180, 85)])                          # a wall of trees
    walled = client.get('/api/sky/state').get_json()
    assert all(o['el'] > 85 for o in walled['targets'])
    horizon.set_points([])
    print('sky routes + mask filtering OK')

# ---- 9. Horizon routes -------------------------------------------------------------------
assert client.get('/api/horizon').get_json()['default_el'] == horizon.DEFAULT_FLOOR_DEG
assert client.put('/api/horizon', json={'points': [{'az': 400, 'el': 5}]}).status_code == 400
ok = client.put('/api/horizon', json={'points': [{'az': 90, 'el': 30}, {'az': 270, 'el': 12}]})
assert ok.status_code == 200 and len(ok.get_json()['profile']) == 72
assert horizon.floor(90.0) == 30.0
assert client.post('/api/horizon/sample').status_code == 409          # no mount connected
import gimbal
assert client.post('/api/gimbal/connect', json={'port': 'SIM'}).status_code == 200
end = time.time() + 5
while time.time() < end and not gimbal.gimbal.status()['pos']:
    time.sleep(0.05)
gimbal.gimbal._link.az, gimbal.gimbal._link.el = 123.0, 17.0
gimbal.gimbal._link._last_report = 0.0
time.sleep(0.8)
s = client.post('/api/horizon/sample')
assert s.status_code == 200, s.get_json()
assert any(abs(p['az'] - 123.0) < 1.0 and abs(p['el'] - 17.0) < 1.0 for p in s.get_json()['points']), s.get_json()['points']
client.post('/api/gimbal/disconnect')
horizon.set_points([])
print('horizon routes + sample-from-mount OK')
print('SKY TESTS PASSED')