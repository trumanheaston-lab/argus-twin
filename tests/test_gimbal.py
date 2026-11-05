"""Gimbal bridge tests, using the built-in simulator (no hardware needed).
Run from the project root:  python tests/test_gimbal.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

import gimbal
import server
import tracker

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
print('GIMBAL TESTS PASSED')