"""Offline sanity tests. Run from the project root:  python tests/test_backend.py

Uses a fixed TLE so results do not depend on the network or today's date.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from skyfield.api import EarthSatellite

import tracker
import server

NAME = 'ISS (ZARYA)'
L1 = '1 25544U 98067A   14020.93268519  .00009878  0000-0  18200-3 0  5082'
L2 = '2 25544  51.6498 109.4756 0003572  55.9686 274.8005 15.49815350868473'

iss = EarthSatellite(L1, L2, NAME, tracker.ts)
tracker._sats = {25544: iss}
tracker._loaded_at = time.time()

# 1. Angles are in legal ranges at 200 times across one day
t0 = tracker.ts.utc(2014, 1, 21, 0, 0, 0)
seen_above = 0
for i in range(200):
    t = tracker.ts.tt_jd(t0.tt + i * (1.0 / 200))
    s = tracker.get_state(iss, t)
    assert 0.0 <= s['az'] < 360.0, s
    assert -90.0 <= s['el'] <= 90.0, s
    assert 300 < s['range_km'] < 14000, s
    assert abs(s['az_rate']) < 5 and abs(s['el_rate']) < 5, s
    seen_above += s['above']
print('angle ranges OK; above horizon in', seen_above, 'of 200 samples')
assert 0 < seen_above < 200

# 2. Azimuth rate never shows a ~360 degree wrap jump
worst = max(abs(tracker.get_state(iss, tracker.ts.tt_jd(t0.tt + i / 2000.0))['az_rate'])
            for i in range(2000))
print('largest |az_rate| over a day:', worst, 'deg/s')
assert worst < 5

# 3. Flask endpoints
client = server.app.test_client()
r = client.get('/api/state?track=25544').get_json()
assert r['tracked']['norad'] == 25544 and 'targets' in r
r2 = client.get('/api/state').get_json()
assert r2['tracked'] is None
info = client.get('/api/info/25544').get_json()
assert info['wiki'] == 'International_Space_Station'
assert abs(info['inclination_deg'] - 51.65) < 0.01
assert 90 < info['period_min'] < 94
assert client.get('/api/info/99999').status_code == 404
assert client.get('/').status_code == 200
print('endpoints OK; info:', {k: info[k] for k in ('inclination_deg', 'period_min')})

# 4. A TLE too old to propagate must give null + error, never NaN (NaN breaks JSON.parse in the browser)
import json
raw = client.get('/api/state?track=25544').get_data(as_text=True)
assert 'NaN' not in raw, raw
now_state = json.loads(raw)['tracked']      # fixture TLE is ~12 years old, so this is a no-solution case
assert now_state['az'] is None and 'error' in now_state, now_state
print('stale-TLE handling OK')

# 5. SATCAT parsing (fixture follows CelesTrak's documented CSV columns)
import satcat
import tempfile

FIXTURE = (
    'OBJECT_NAME,OBJECT_ID,NORAD_CAT_ID,OBJECT_TYPE,OPS_STATUS_CODE,OWNER,LAUNCH_DATE,LAUNCH_SITE,'
    'DECAY_DATE,PERIOD,INCLINATION,APOGEE,PERIGEE,RCS,DATA_STATUS_CODE,ORBIT_CENTER,ORBIT_TYPE\n'
    'ISS (ZARYA),1998-067A,25544,PAY,+,ISS,1998-11-20,TTMTR,,92.9,51.6,420,418,LARGE,,EA,ORB\n'
    'CZ-4C R/B,2019-001B,99001,R/B,,PRC,2019-01-01,JSC,,100,98,800,780,LARGE,,EA,ORB\n'
    'BAD ROW,x,notanumber,PAY,,US,,,,,,,,,,,\n'
)
recs = {}
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, 'fixture.csv')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(FIXTURE)
    recs = satcat.parse(path)
    # A file with missing columns must not crash the parser
    with open(path, 'w', encoding='utf-8') as f:
        f.write('NORAD_CAT_ID\n12345\n')
    assert satcat.parse(path)[12345]['object_type'] == ''
assert set(recs) == {25544, 99001}, recs.keys()           # bad row skipped
assert recs[99001]['object_type_name'] == 'Rocket body'
assert recs[99001]['owner'] == "People's Republic of China"
assert recs[25544]['owner'].startswith('International Space Station')
assert server.classification_line(recs[99001]) == (
    "Rocket body. Owner: People's Republic of China. Launched 2019-01-01 from site code JSC.")
assert server.classification_line({}) is None
print('satcat parsing OK')

# 6. Minimum-elevation filter
satcat._records = recs
t_hi = None
for i in range(400):
    t = tracker.ts.tt_jd(t0.tt + i / 400.0)
    if tracker.get_state(iss, t)['el'] > 20:
        t_hi = t
        break
assert t_hi is not None
el_hi = tracker.get_state(iss, t_hi)['el']
assert len(tracker.overhead(t_hi, 10)) == 1
assert len(tracker.overhead(t_hi, 0)) == 1
assert len(tracker.overhead(t_hi, el_hi + 1)) == 0
print('min-elevation filter OK')

# 7. Server annotations: featured flag, type, min_el echo
orig_overhead = tracker.overhead
tracker.overhead = lambda t, min_el=None: [
    {'norad': 25544, 'name': 'ISS (ZARYA)', 'az': 1.0, 'el': 30.0, 'range_km': 500.0,
     'az_rate': 0.1, 'el_rate': 0.1, 'above': True},
    {'norad': 99001, 'name': 'CZ-4C R/B', 'az': 2.0, 'el': 40.0, 'range_km': 900.0,
     'az_rate': 0.1, 'el_rate': 0.1, 'above': True},
]
try:
    st = client.get('/api/state').get_json()
    assert st['min_el'] == tracker.MIN_ELEVATION_DEG
    by_id = {x['norad']: x for x in st['targets']}
    assert by_id[25544]['featured'] is True and by_id[25544]['type'] == 'PAY'
    assert by_id[99001]['featured'] is False and by_id[99001]['type'] == 'R/B'
    assert client.get('/api/state?min_el=25').get_json()['min_el'] == 25.0
finally:
    tracker.overhead = orig_overhead
print('state annotations OK')

# 8. /api/info merge: featured satellite vs. one with no write-up
tracker._sats[99001] = iss        # stand-in so the lookup succeeds
try:
    feat = client.get('/api/info/25544').get_json()
    assert feat['featured'] is True and feat['mission'] and feat['owner']
    plain = client.get('/api/info/99001').get_json()
    assert plain['featured'] is False and 'mission' not in plain
    assert plain['classification'].startswith('Rocket body.')
    assert plain['object_type_name'] == 'Rocket body'
finally:
    del tracker._sats[99001]
print('info merge OK')

# 9. Satellites with no SATCAT data still work (download blocked or file missing)
satcat._records = {}
bare = client.get('/api/info/25544').get_json()
assert bare['classification'] is None and bare['mission']
print('no-SATCAT fallback OK')
print('ALL NEW TESTS PASSED')
print('ALL TESTS PASSED')