"""NexStar link tests against a fake mount (no hardware needed).
Run from the project root:  python tests/test_nexstar.py
"""
import os
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, '..', 'src'))
sys.path.insert(0, here)

from fake_nexstar import FakeNexStar
from gimbal import NexStarLink


def make(**kw):
    fake = FakeNexStar(**kw)
    link = NexStarLink(ser=fake)
    link.CONTROL_S = 0.1
    link.POLL_S = 0.1
    return fake, link


def run(link, seconds, send=None, every=0.5):
    """Pump the link like the Gimbal thread does. Returns all lines it produced."""
    lines, end, next_send = [], time.monotonic() + seconds, 0.0
    while time.monotonic() < end:
        if send and time.monotonic() >= next_send:
            link.write_line(send())
            next_send = time.monotonic() + every
        lines += link.read_lines()
        time.sleep(0.02)
    return lines


# 1. Byte-exact encoding against Celestron's documented examples
fake, link = make()
fake.written.clear()
link._send_rate(16, 150)                       # doc example: 150 arcsec/s -> high 2, low 88
assert fake.written[-1] == bytes([ord('P'), 3, 16, 6, 2, 88, 0, 0]), fake.written[-1]
link._send_rate(17, -150)                      # negative altitude uses sign byte 7
assert fake.written[-1] == bytes([ord('P'), 3, 17, 7, 2, 88, 0, 0]), fake.written[-1]
assert link._hex(90.0) == b'40000000' and link._hex(0.0) == b'00000000'
assert link._hex(-90.0) == b'C0000000'
assert abs(FakeNexStar._dec(b'12AB0500') - 26.26) < 0.01       # doc's sample position
print('protocol bytes match the Celestron document OK')

# 2. Startup talks to the mount and reports it
fake, link = make()
first = link.read_lines()
assert 'READY' in first and any(l.startswith('INFO,VERSION') for l in first), first
assert fake.tracking_mode == 0, 'sidereal tracking should be switched off'
print('identify + tracking off OK')

# 3. HOME defines north/level at the current pose, then GoTo works in our frame
fake, link = make(az=123.0, alt=17.0)
link.write_line('HOME')
assert link._pos == (0.0, 0.0)
link.write_line('T,10.0,5.0,0.0,0.0')
run(link, 1.5, send=lambda: 'T,10.0,5.0,0.0,0.0')
assert abs(fake.az - 133.0) < 1.5 and abs(fake.alt - 22.0) < 1.5, (fake.az, fake.alt)
print('HOME offsets + goto OK:', round(fake.az, 1), round(fake.alt, 1))

# 4. Smooth tracking of a moving target using rates
fake, link = make(az=0.0, alt=0.0)
link.write_line('HOME')                         # mount frame == our frame
t0 = time.monotonic()
target = lambda: 'T,%.3f,%.3f,0.6,0.1' % (20.0 + 0.6 * (time.monotonic() - t0), 20.0 + 0.1 * (time.monotonic() - t0))
lines = run(link, 8.0, send=target, every=1.0)
want_az = 20.0 + 0.6 * (time.monotonic() - t0)
want_el = 20.0 + 0.1 * (time.monotonic() - t0)
assert abs(fake.az - want_az) < 1.5, (fake.az, want_az)
assert abs(fake.alt - want_el) < 1.5, (fake.alt, want_el)
assert not any(l.startswith('ERR') for l in lines), lines
print('rate tracking OK: az %.2f (want %.2f), alt %.2f (want %.2f)' % (fake.az, want_az, fake.alt, want_el))

# 5. Azimuth wrap: tracking across north takes the short way
fake, link = make(az=358.0, alt=0.0)
link.write_line('HOME')
t0 = time.monotonic()
run(link, 3.0, send=lambda: 'T,%.3f,0.0,0.5,0.0' % ((0.5 * (time.monotonic() - t0)) % 360.0), every=0.5)
assert fake.az < 5.0 or fake.az > 355.0, fake.az           # still near north, did not swing around
print('azimuth wrap OK:', round(fake.az, 2))

# 6. Watchdog: updates stop, so the mount must stop turning
fake, link = make(az=0.0, alt=0.0)
link.write_line('HOME')
link.WATCHDOG_S = 1.0
t0 = time.monotonic()
run(link, 1.2, send=lambda: 'T,%.3f,0.0,0.5,0.0' % (0.5 * (time.monotonic() - t0)), every=0.4)
assert fake.rate_az != 0.0, 'should be moving while updates arrive'
lines = run(link, 2.0)                                      # no more updates
assert 'ERR,WATCHDOG' in lines and fake.rate_az == 0.0 and fake.rate_alt == 0.0, (lines, fake.rate_az)
print('watchdog stops motion OK')

# 7. Runaway guard: a mount that turns the wrong way gets stopped
fake, link = make(az=0.0, alt=0.0, invert_az=True)
link.write_line('HOME')
t0 = time.monotonic()
lines = run(link, 6.0, send=lambda: 'T,%.3f,0.0,0.0,0.0' % 2.5, every=0.4)
assert 'ERR,LOST_TRACK' in lines, lines
assert fake.rate_az == 0.0
print('wrong-direction guard OK')

# 8. PARK returns the tube to the park altitude and reports PARKED
fake, link = make(az=50.0, alt=0.0)
link.write_line('HOME')
fake.alt = 40.0                                 # someone tilts the tube up
link._update_pos()
assert abs(link._pos[1] - 40.0) < 0.1
link.write_line('PARK')
lines = run(link, 2.0)
assert any(l.endswith('PARKED') for l in lines), lines[-3:]
assert abs(fake.alt - link.PARK_ALT_DEG) < 1.0, fake.alt
print('park OK')

# 9. STOP, PING, bad input and close
fake, link = make()
link.write_line('T,1,2,0.5,0.5')
run(link, 0.4)
link.write_line('STOP')
assert fake.rate_az == 0.0 and fake.rate_alt == 0.0
link.write_line('PING')
assert 'PONG' in link.read_lines()
link.write_line('T,abc,2,3,4')
link.write_line('BANANA')
out = link.read_lines()
assert 'ERR,BAD_NUMBER' in out and 'ERR,UNKNOWN_COMMAND' in out
link.close()
assert fake.closed
print('stop / ping / bad input / close OK')

# 10. A silent mount raises a clear error instead of hanging forever
class Silent:
    def write(self, d): pass
    def read(self, n=1): return b''
    def close(self): pass

orig = NexStarLink._xfer
NexStarLink._xfer = lambda self, data, timeout=3.5: orig(self, data, timeout=0.2)
try:
    NexStarLink(ser=Silent())
    raise AssertionError('should have raised')
except TimeoutError as exc:
    assert 'powered' in str(exc)
finally:
    NexStarLink._xfer = orig
print('silent mount error OK')

# 11. Manual jog: moves at the requested rate, stops by itself, and respects the elevation floor
fake, link = make(az=10.0, alt=5.0)
link.write_line('J,1.000,0.000')
run(link, 1.0, send=lambda: 'J,1.000,0.000', every=0.2)
assert 10.7 < fake.az < 11.5 and abs(fake.alt - 5.0) < 0.05, (fake.az, fake.alt)
run(link, 1.0)                                              # no more messages: the watchdog stops it
assert fake.rate_az == 0.0 and link._mode == 'IDLE', (fake.rate_az, link._mode)
fake, link = make(az=0.0, alt=0.2)
link.write_line('STOP')
run(link, 0.3)
link.write_line('J,0.000,-2.000')
run(link, 1.5, send=lambda: 'J,0.000,-2.000', every=0.2)
assert fake.alt > -0.6, fake.alt                           # it ran into the floor and was held there
link.write_line('J,0,0')
assert fake.rate_alt == 0.0 and fake.rate_az == 0.0
print('manual jog OK')

# 12. One-star alignment: offsets on both axes, then GoTo lands in the corrected frame
fake, link = make(az=100.0, alt=10.0)
link.write_line('SYNC,30.000,40.000')
run(link, 0.3)
assert abs(link._pos[0] - 30.0) < 0.01 and abs(link._pos[1] - 40.0) < 0.01, link._pos
link._goto(35.0, 40.0)
run(link, 0.3)
time.sleep(0.2)
fake._step()
assert abs(fake.az - 105.0) < 0.1 and abs(fake.alt - 10.0) < 0.1, (fake.az, fake.alt)
print('one-star alignment OK')
print('NEXSTAR TESTS PASSED')