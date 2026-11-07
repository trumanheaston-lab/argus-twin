"""Gimbal bridge tests, using the built-in simulator (no hardware needed).
Run from the project root:  python tests/test_gimbal.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

import tempfile

import gimbal
import horizon
import safety
import server
import tracker

# Keep the tests independent of the real clock and of any horizon mask you have saved.
horizon.DATA_FILE = os.path.join(tempfile.mkdtemp(), 'horizon.json')
horizon._points = None
safety.sun_altaz = lambda t=None: (-30.0, 0.0)          # night, Sun far below the horizon

gimbal.TICK_S = 0.2                      # speed the tests up
g = gimbal.gimbal
client = server.app.test_client()

FAKE = {'norad': 25544, 'name': 'FAKE', 'az': 30.0, 'el': 40.0, 'range_km': 500.0,
        'az_rate': 0.0, 'el_rate': 0.0, 'above': True}
tracker.tracked = lambda norad, t=None: dict(FAKE)


def wait_for(cond, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


# 1. Commands before connecting are refused cleanly
r = client.post('/api/gimbal/command', json={'cmd': 'HOME'})
assert r.status_code == 409, r.get_json()
r = client.post('/api/gimbal/track', json={'norad': 25544})
assert r.status_code == 409, r.get_json()
assert client.get('/api/gimbal').get_json()['connected'] is False
print('refuses commands when disconnected OK')

# 2. Connect to the simulator; unknown commands and missing port are rejected
assert client.post('/api/gimbal/connect', json={}).status_code == 400
assert client.post('/api/gimbal/connect', json={'port': 'SIM'}).status_code == 200
assert client.post('/api/gimbal/command', json={'cmd': 'FORMAT_DISK'}).status_code == 400
assert wait_for(lambda: g.status()['pos'] is not None), 'no position report from simulator'
print('connect + validation OK')

# 3. Tracking: the simulated gimbal slews to the target
g._link.slew = 200.0                     # fast, so the test is quick
assert client.post('/api/gimbal/track', json={'norad': 25544}).status_code == 200
assert wait_for(lambda: g.pos and abs(g.pos['az'] - 30.0) < 0.5 and abs(g.pos['el'] - 40.0) < 0.5), g.pos
assert g.status()['tracking'] == 25544
print('tracking reaches target OK:', g.pos)

# 4. Below the horizon: no target lines are sent, and the watchdog then stops motion
sent = []
orig_write = g._link.write_line
g._link.write_line = lambda line: (sent.append(line), orig_write(line))
FAKE['el'] = -5.0
time.sleep(0.8)
assert not [l for l in sent if l.startswith('T,')], sent
print('holds below horizon OK')
FAKE['el'] = 40.0
g._link.write_line = orig_write

# 5. Azimuth wrap: going from 359 to 1 degree must take the short way
g.release()
g.command('HOME')
g._link.az = 359.0
g._link.write_line('T,1.0,10.0,0.0,0.0')
time.sleep(0.15)
g._link.read_lines()
assert g._link.az > 359.0 or g._link.az < 3.0, g._link.az        # moving across 0, not back through 180
print('azimuth wrap shortest path OK')

# 6. PARK sends elevation to 90, and manual commands release the lock
FAKE['el'] = 40.0
client.post('/api/gimbal/track', json={'norad': 25544})
assert g.status()['tracking'] == 25544
assert client.post('/api/gimbal/command', json={'cmd': 'PARK'}).status_code == 200
assert g.status()['tracking'] is None
assert wait_for(lambda: g.pos and g.pos['el'] > 89.9 and g.state == 'PARKED'), (g.pos, g.state)
print('park + lock release OK')

# 7. Watchdog: if updates stop while tracking, the simulator stops itself
g._link.watchdog_s = 0.5
g._link.write_line('T,10.0,20.0,0.0,0.0')
assert wait_for(lambda: g.state == 'IDLE', 3.0), g.state
assert any('WATCHDOG' in e['text'] for e in g.status()['log'])
print('watchdog OK')

# 8. Malformed lines never crash the link
for bad in ('T,abc,1,2,3', 'T,1,2', 'BANANA', ''):
    g._link.write_line(bad)
time.sleep(0.3)
assert g.status()['connected']
print('malformed input OK')

# 9. Disconnect cleans up
assert client.post('/api/gimbal/disconnect').status_code == 200
st = client.get('/api/gimbal').get_json()
assert st['connected'] is False and st['tracking'] is None
print('disconnect OK')

# 10. Horizon mask: a target behind trees is never sent, and the reason is logged once
assert client.post('/api/gimbal/connect', json={'port': 'SIM'}).status_code == 200
assert wait_for(lambda: g.status()['pos'] is not None)
sent = []
orig_write = g._link.write_line
g._link.write_line = lambda line: (sent.append(line), orig_write(line))
horizon.set_points([(0, 60), (180, 60)])               # trees up to 60 degrees everywhere
FAKE.update(az=30.0, el=40.0)
g.track(25544)
time.sleep(1.0)
assert not [l for l in sent if l.startswith('T,')], sent
texts = [e['text'] for e in g.status()['log']]
assert sum('HORIZON MASK' in t for t in texts) == 1, texts      # logged once, not every second
horizon.set_points([])                                          # trees cut down
time.sleep(0.8)
assert [l for l in sent if l.startswith('T,')], 'should send once the mask is gone'
print('horizon mask blocks tracking OK')

# 11. Sun keep-out: never send a target near the Sun, and never slew across it
sent.clear()
g.release()
safety.sun_altaz = lambda t=None: (40.0, 33.0)                  # Sun right next to the target
g.track(25544)
time.sleep(1.0)
assert not [l for l in sent if l.startswith('T,')], sent
assert any('SUN KEEP-OUT' in e['text'] for e in g.status()['log'])
g.release()
sent.clear()
safety.sun_altaz = lambda t=None: (20.0, 15.0)                  # target is 24 deg away, but the path crosses
g._link.az, g._link.el = 0.0, 0.0
time.sleep(0.8)
g.track(25544)
time.sleep(1.0)
assert not [l for l in sent if l.startswith('T,')], sent
assert any('SLEW PATH' in e['text'] for e in g.status()['log'])
print('sun keep-out blocks target and slew path OK')

# 12. Sky objects flow through the same path (string target ids)
import sky
g.release()
sent.clear()
safety.sun_altaz = lambda t=None: (-30.0, 0.0)
orig_sky_state = sky.state
sky.state = lambda oid, t=None: dict(FAKE, id=oid, name='Fake planet', kind='Planet')
assert client.post('/api/gimbal/track', json={'target': 'jupiter'}).status_code == 200
assert g.status()['tracking'] == 'jupiter'
time.sleep(1.0)
assert [l for l in sent if l.startswith('T,')], sent
assert client.post('/api/gimbal/track', json={'target': 'definitely-not-real'}).status_code == 400
assert client.post('/api/gimbal/track', json={'norad': '25544'}).status_code == 200      # old key and string digits still work
assert g.status()['tracking'] == 25544
sky.state = orig_sky_state
client.post('/api/gimbal/disconnect')
print('sky targets through the gimbal OK')

# 13. Manual aim (arrow keys): moves while messages keep coming, stops by itself when they stop
assert client.post('/api/gimbal/jog', json={'az': 1, 'el': 0}).status_code == 409        # not connected
assert client.post('/api/gimbal/connect', json={'port': 'SIM'}).status_code == 200
assert wait_for(lambda: g.status()['pos'] is not None)
assert client.post('/api/gimbal/jog', json={'az': 1, 'el': 0, 'speed': 'warp'}).status_code == 400
g.command('HOME')
g.track(25544)
start = time.monotonic()
while time.monotonic() - start < 1.0:                       # hold the right arrow for 1 s at fast (2 deg/s)
    assert client.post('/api/gimbal/jog', json={'az': 1, 'el': 0, 'speed': 'fast'}).status_code == 200
    time.sleep(0.2)
assert g.status()['tracking'] is None                       # manual aim releases the lock
assert wait_for(lambda: g.pos and 1.0 < g.pos['az'] < 3.5), g.pos
held_az = None
assert wait_for(lambda: g.state == 'IDLE', 3.0), g.state     # key released: watchdog stops it
a1 = g.pos['az']; time.sleep(0.8)
assert abs(g.pos['az'] - a1) < 0.05, 'kept moving after the keys stopped'
# elevation cannot go below level
for _ in range(8):
    client.post('/api/gimbal/jog', json={'az': 0, 'el': -1, 'speed': 'fast'}); time.sleep(0.2)
assert g.pos['el'] >= 0.0, g.pos
# explicit zero stops at once
client.post('/api/gimbal/jog', json={'az': 0, 'el': 1, 'speed': 'fast'}); time.sleep(0.4)
client.post('/api/gimbal/jog', json={'az': 0, 'el': 0}); time.sleep(0.8)
e1 = g.pos['el']; time.sleep(0.6)
assert abs(g.pos['el'] - e1) < 0.05
# the Sun guard refuses manual motion that would enter the keep-out zone
g._link.az, g._link.el = 100.0, 30.0
time.sleep(0.8)
safety.sun_altaz = lambda t=None: (30.0, 120.0)
r = client.post('/api/gimbal/jog', json={'az': 1, 'el': 0, 'speed': 'fast'})
assert r.status_code == 409 and 'KEEP-OUT' in r.get_json()['message'].upper(), r.get_json()
safety.sun_altaz = lambda t=None: (-30.0, 0.0)
client.post('/api/gimbal/disconnect')
print('manual aim OK')

# 14. One-star alignment: the mount's reported position snaps to the target's true position
assert client.post('/api/gimbal/sync', json={'target': 25544}).status_code == 409           # not connected
assert client.post('/api/gimbal/connect', json={'port': 'SIM'}).status_code == 200
assert wait_for(lambda: g.status()['pos'] is not None)
g._link.az, g._link.el = 50.0, 20.0
FAKE.update(az=30.0, el=40.0)
assert client.post('/api/gimbal/sync', json={'target': 25544}).status_code == 200
assert wait_for(lambda: g.pos and abs(g.pos['az'] - 30.0) < 0.6 and abs(g.pos['el'] - 40.0) < 0.6), g.pos
FAKE['el'] = 2.0
assert client.post('/api/gimbal/sync', json={'target': 25544}).status_code == 409           # too low
FAKE['el'] = 40.0
safety.sun_altaz = lambda t=None: (40.0, 33.0)
assert client.post('/api/gimbal/sync', json={'target': 25544}).status_code == 409           # near the Sun
safety.sun_altaz = lambda t=None: (-30.0, 0.0)
assert client.post('/api/gimbal/sync', json={'target': 'nonsense'}).status_code == 400
client.post('/api/gimbal/disconnect')
print('one-star alignment OK')
print('GIMBAL TESTS PASSED')