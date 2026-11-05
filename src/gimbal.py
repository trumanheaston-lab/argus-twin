"""Link between the server and the gimbal controller (Arduino Nano).

Two interchangeable "links" speak the same line protocol (docs/PROTOCOL.md):
  - SimulatedLink  pretends to be the firmware, so you can test with no hardware
  - SerialLink     talks to the real board over USB

The Gimbal class owns the link and a background thread. While tracking is on,
the thread sends the chosen satellite's pointing data once a second, even if the
browser tab is closed.
"""
import collections
import threading
import time

import tracker

TICK_S = 1.0                      # how often a target line is sent
POLL_S = 0.1                      # how often we read replies from the link
COMMANDS = ('HOME', 'PARK', 'STOP')


def _wrap180(delta):
    return (delta + 180.0) % 360.0 - 180.0


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


class SimulatedLink:
    """Behaves like the firmware: slews toward targets at a limited speed,
    glides between updates using the rates, and stops if updates stop."""
    name = 'SIMULATOR'

    def __init__(self, slew_dps=10.0, watchdog_s=5.0):
        self.az = 0.0              # unbounded internally, reported mod 360
        self.el = 0.0
        self.slew = slew_dps
        self.watchdog_s = watchdog_s
        self._target = None        # (az, el, az_rate, el_rate, time_received)
        self._state = 'IDLE'
        self._out = collections.deque(['READY'])
        self._last = time.monotonic()
        self._last_report = 0.0

    def write_line(self, line):
        parts = line.strip().split(',')
        cmd, now = parts[0], time.monotonic()
        if cmd == 'T' and len(parts) == 5:
            try:
                az, el, azr, elr = (float(x) for x in parts[1:])
            except ValueError:
                self._out.append('ERR,BAD_NUMBER')
                return
            self._target = (az, el, azr, elr, now)
            self._state = 'TRACKING'
        elif cmd == 'HOME':
            self.az = self.el = 0.0
            self._target, self._state = None, 'IDLE'
            self._out.append('OK,HOME')
        elif cmd == 'PARK':
            self._target = (self.az % 360.0, 90.0, 0.0, 0.0, now)
            self._state = 'PARKING'
            self._out.append('OK,PARK')
        elif cmd == 'STOP':
            self._target, self._state = None, 'IDLE'
            self._out.append('OK,STOP')
        elif cmd == 'PING':
            self._out.append('PONG')
        else:
            self._out.append('ERR,UNKNOWN_COMMAND')

    def _advance(self):
        now = time.monotonic()
        dt, self._last = now - self._last, now
        if self._target is not None:
            az, el, azr, elr, t0 = self._target
            age = now - t0
            if self._state == 'TRACKING' and age > self.watchdog_s:
                self._target, self._state = None, 'IDLE'
                self._out.append('ERR,WATCHDOG')
            else:
                if self._state == 'TRACKING':
                    goal_az, goal_el = az + azr * age, el + elr * age
                else:
                    goal_az, goal_el = az, el
                goal_el = _clamp(goal_el, 0.0, 90.0)
                step = self.slew * dt
                self.az += _clamp(_wrap180(goal_az - self.az), -step, step)
                self.el += _clamp(goal_el - self.el, -step, step)
                if (self._state == 'PARKING' and abs(self.el - 90.0) < 0.01):
                    self._target, self._state = None, 'PARKED'
        if now - self._last_report >= 0.5:
            self._last_report = now
            self._out.append(f'POS,{self.az % 360.0:.2f},{self.el:.2f},{self._state}')

    def read_lines(self):
        self._advance()
        lines = list(self._out)
        self._out.clear()
        return lines

    def close(self):
        pass


class SerialLink:
    """Real board over USB serial, 115200 baud, one text line per message."""

    def __init__(self, port, baud=115200):
        from importlib import import_module
        serial = import_module('serial')   # pip install pyserial
        self.name = port
        self._ser = serial.Serial(port, baud, timeout=0)
        self._buf = b''

    def write_line(self, line):
        self._ser.write((line.strip() + '\n').encode('ascii'))

    def read_lines(self):
        self._buf += self._ser.read(self._ser.in_waiting or 0)
        *done, self._buf = self._buf.split(b'\n')
        return [l.decode('ascii', 'replace').strip() for l in done if l.strip()]

    def close(self):
        self._ser.close()


class NexStarLink:
    """Celestron NexStar alt-az mount (SLT and friends) over the hand controller's
    USB/serial port, 9600 baud. Speaks Celestron's published NexStar protocol, and
    presents the same line interface as the other links, so the rest of the server
    does not care which kind of mount is attached.

    How it tracks: the mount is told how fast to turn (variable-rate slew, the 'P'
    command) once every CONTROL_S seconds. The rate is the satellite's own angular
    rate plus a correction proportional to the pointing error. Large errors
    (more than GOTO_THRESHOLD_DEG) are handled with a normal GoTo slew first.

    Safety: the mount keeps turning at the last rate it was given, so this link
    stops motion if target updates stop (watchdog), if the error keeps growing
    (wrong direction or target too fast for the mount), and when closed.
    """
    MAX_RATE_DPS = 2.0          # cap on commanded speed, degrees per second
    GOTO_THRESHOLD_DEG = 3.0    # bigger errors use GoTo instead of rate control
    GOTO_DPS = 3.0              # assumed GoTo speed, only used to lead the target
    PARK_ALT_DEG = 0.0          # PARK points the tube level. Change if that hits your tripod.
    POLL_S = 0.5                # position read interval
    CONTROL_S = 0.5             # rate update interval
    GAIN = 1.0                  # per second: fix the whole error in about one second
    WATCHDOG_S = 5.0
    RUNAWAY_DPS = 0.5           # error steadily growing faster than this => stop

    def __init__(self, port=None, ser=None, baud=9600):
        if ser is None:
            import serial  # type: ignore[reportMissingModuleSource]  # pip install pyserial
            ser = serial.Serial(port, baud, timeout=0.05)
        self._ser = ser
        self.name = 'NEXSTAR ' + (port or 'TEST')
        self._out = collections.deque()
        self._az_off = 0.0                      # set by HOME: mount angle that means "north"
        self._alt_off = 0.0                     # set by HOME: mount angle that means "level"
        self._pos = None                        # (az, el) in OUR frame (offsets applied)
        self._target = None                     # (az, el, az_rate, el_rate, time_received)
        self._mode = 'IDLE'
        self._goto_active = False
        self._errs = collections.deque(maxlen=4)
        self._last_poll = 0.0
        self._last_ctrl = 0.0
        self._identify()

    # ---- low level ----
    def _xfer(self, data, timeout=3.5):
        """Send bytes, return the reply (without the trailing '#')."""
        self._ser.write(data)
        buf = b''
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            ch = self._ser.read(1)
            if ch:
                buf += ch
                if ch == b'#':
                    return buf[:-1]
            else:
                time.sleep(0.002)
        raise TimeoutError('no response from mount')

    @staticmethod
    def _hex(deg):
        """Degrees to the protocol's 32-bit fraction of a full turn, as 8 hex digits."""
        return b'%08X' % (int(round((deg % 360.0) / 360.0 * 4294967296.0)) & 0xFFFFFFFF)

    def _read_pos(self):
        """Raw mount position (az 0..360, alt -180..180) from 'z'."""
        r = self._xfer(b'z')
        az = int(r[0:8], 16) / 4294967296.0 * 360.0
        alt = int(r[9:17], 16) / 4294967296.0 * 360.0
        if alt > 180.0:
            alt -= 360.0
        return az, alt

    def _update_pos(self):
        az, alt = self._read_pos()
        self._pos = ((az - self._az_off) % 360.0, alt - self._alt_off)

    def _goto(self, az, el):
        """GoTo in OUR frame."""
        mount_az = (az + self._az_off) % 360.0
        mount_alt = el + self._alt_off
        self._xfer(b'b' + self._hex(mount_az) + b',' + self._hex(mount_alt))

    def _goto_done(self):
        return self._xfer(b'L').startswith(b'0')

    def _send_rate(self, axis, arcsec_per_s):
        """Variable-rate slew. axis 16 = azimuth, 17 = altitude. The protocol takes
        rate x 4 as a 16-bit number and a sign byte (6 = positive, 7 = negative)."""
        mag = min(int(round(abs(arcsec_per_s) * 4)), 65535)
        sign = 6 if arcsec_per_s >= 0 else 7
        self._xfer(b'P' + bytes([3, axis, sign, mag >> 8, mag & 0xFF, 0, 0]))

    def _rates(self, az_dps, el_dps):
        self._send_rate(16, az_dps * 3600.0)
        self._send_rate(17, el_dps * 3600.0)

    def _stop_motion(self):
        self._rates(0.0, 0.0)
        self._xfer(b'M')                        # cancel any GoTo in progress
        self._goto_active = False

    def _identify(self):
        try:
            v = self._xfer(b'V')
            if len(v) >= 2:
                self._out.append(f'INFO,VERSION,{v[0]}.{v[1]}')
            m = self._xfer(b'm')
            if m:
                self._out.append(f'INFO,MODEL,{m[0]}')
        except TimeoutError:
            raise TimeoutError('mount did not answer. Is it powered, and is this the right port?')
        self._xfer(b'T\x00')                    # sidereal tracking off: we steer it ourselves
        self._out.append('READY')

    # ---- same interface as the other links ----
    def write_line(self, line):
        parts = line.strip().split(',')
        cmd, now = parts[0], time.monotonic()
        if cmd == 'T' and len(parts) == 5:
            try:
                az, el, azr, elr = (float(x) for x in parts[1:])
            except ValueError:
                self._out.append('ERR,BAD_NUMBER')
                return
            if self._mode != 'TRACKING':
                self._goto_active = False
                self._errs.clear()
            self._target = (az, el, azr, elr, now)
            self._mode = 'TRACKING'
        elif cmd == 'HOME':
            # Declare the current pose to be north + level. Aim the tube first.
            self._stop_motion()
            self._az_off, self._alt_off = self._read_pos()
            self._pos = (0.0, 0.0)
            self._target, self._mode = None, 'IDLE'
            self._out.append('OK,HOME')
        elif cmd == 'PARK':
            self._stop_motion()
            if self._pos is None:
                self._update_pos()
            self._goto(self._pos[0], self.PARK_ALT_DEG)
            self._goto_active = True
            self._target, self._mode = None, 'PARKING'
            self._out.append('OK,PARK')
        elif cmd == 'STOP':
            self._stop_motion()
            self._target, self._mode = None, 'IDLE'
            self._out.append('OK,STOP')
        elif cmd == 'PING':
            if self._xfer(b'KA') == b'A':
                self._out.append('PONG')
        else:
            self._out.append('ERR,UNKNOWN_COMMAND')

    def read_lines(self):
        now = time.monotonic()
        if now - self._last_poll >= self.POLL_S:
            self._last_poll = now
            self._update_pos()
            state = 'SLEWING' if (self._mode == 'TRACKING' and self._goto_active) else \
                    ('PARKED' if self._mode == 'PARKED' else self._mode)
            self._out.append(f'POS,{self._pos[0] % 360.0:.2f},{self._pos[1]:.2f},{state}')
        if self._mode == 'TRACKING':
            if now - self._target[4] > self.WATCHDOG_S:
                self._stop_motion()
                self._target, self._mode = None, 'IDLE'
                self._out.append('ERR,WATCHDOG')
            elif now - self._last_ctrl >= self.CONTROL_S and self._pos is not None:
                self._last_ctrl = now
                self._control(now)
        elif self._mode == 'PARKING' and now - self._last_ctrl >= self.CONTROL_S:
            self._last_ctrl = now
            if self._goto_done():
                self._goto_active, self._mode = False, 'PARKED'
        lines = list(self._out)
        self._out.clear()
        return lines

    def _control(self, now):
        az_t, el_t, azr, elr, t0 = self._target
        age = now - t0
        goal_az = az_t + azr * age
        goal_el = max(el_t + elr * age, 0.0)
        err_az = _wrap180(goal_az - self._pos[0])
        err_el = goal_el - self._pos[1]
        worst = max(abs(err_az), abs(err_el))

        if self._goto_active:                   # wait for the GoTo to finish
            if self._goto_done():
                self._goto_active = False
                self._errs.clear()
            return
        # Runaway guard: if the error keeps growing while we are steering, something
        # is wrong (wrong direction, or the target is faster than the mount can go).
        # It runs before the GoTo decision so a GoTo cannot hide a mount that is
        # steering the wrong way.
        self._errs.append((now, worst))
        if len(self._errs) == self._errs.maxlen:
            vals = [e for _, e in self._errs]
            span = self._errs[-1][0] - self._errs[0][0]
            if (span > 0 and all(b > a for a, b in zip(vals, vals[1:]))
                    and (vals[-1] - vals[0]) / span > self.RUNAWAY_DPS):
                self._stop_motion()
                self._target, self._mode = None, 'IDLE'
                self._out.append('ERR,LOST_TRACK')
                return

        if worst > self.GOTO_THRESHOLD_DEG:
            lead = worst / self.GOTO_DPS + 1.0  # aim where it will be when we arrive
            self._rates(0.0, 0.0)
            self._goto(goal_az + azr * lead, max(goal_el + elr * lead, 0.0))
            self._goto_active = True
            self._errs.clear()
            return

        cap = self.MAX_RATE_DPS
        ra = max(-cap, min(cap, azr + self.GAIN * err_az))
        re = max(-cap, min(cap, elr + self.GAIN * err_el))
        self._rates(ra, re)

    def close(self):
        try:
            self._stop_motion()
        finally:
            self._ser.close()


class Gimbal:
    def __init__(self):
        self._lock = threading.RLock()
        self._link = None
        self._stop = threading.Event()
        self._thread = None
        self.tracking = None            # NORAD id being tracked, or None
        self.pos = None                 # {'az','el'} last reported by the controller
        self.state = 'DISCONNECTED'
        self.log = collections.deque(maxlen=60)
        self._seq = 0
        self._last_send = 0.0
        self._warned_horizon = False

    # ---- bookkeeping ----
    def _log(self, msg):
        self._seq += 1
        self.log.append({'seq': self._seq, 'text': msg})

    def _handle(self, line):
        parts = line.split(',')
        if parts[0] == 'POS' and len(parts) >= 4:
            try:
                self.pos = {'az': float(parts[1]), 'el': float(parts[2])}
                self.state = parts[3]
            except ValueError:
                self._log('BAD POS LINE: ' + line)
        else:
            self._log('DEVICE: ' + line)
            if parts[0] == 'ERR' and len(parts) > 1 and parts[1] == 'WATCHDOG':
                self.state = 'IDLE'

    # ---- connection ----
    def connect(self, port):
        with self._lock:
            self.disconnect()
            if port.upper() == 'SIM':
                self._link = SimulatedLink()
            elif port.upper().startswith('NEXSTAR:'):
                self._link = NexStarLink(port.split(':', 1)[1])
            else:
                self._link = SerialLink(port)
            self.state = 'CONNECTED'
            self._log(f'CONNECTED: {self._link.name}')
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def disconnect(self):
        with self._lock:
            if self._link is not None:
                try:
                    self._link.write_line('STOP')
                    self._link.close()
                except Exception:
                    pass
                self._log('DISCONNECTED')
            self._link, self.tracking, self.pos = None, None, None
            self.state = 'DISCONNECTED'
            self._stop.set()

    # ---- commands ----
    def send(self, line):
        with self._lock:
            if self._link is None:
                raise RuntimeError('gimbal not connected')
            self._link.write_line(line)

    def command(self, cmd):
        if cmd not in COMMANDS:
            raise ValueError('unknown command')
        if cmd in ('HOME', 'PARK', 'STOP'):
            self.tracking = None            # any manual command releases the lock
        self.send(cmd)

    def track(self, norad):
        with self._lock:
            if self._link is None:
                raise RuntimeError('gimbal not connected')
            self.tracking = int(norad)
            self._last_send = 0.0
            self._warned_horizon = False
            self._log(f'TRACKING LOCK ON: NORAD {self.tracking}')

    def release(self):
        with self._lock:
            if self.tracking is not None:
                self._log('TRACKING LOCK OFF')
            self.tracking = None
            if self._link is not None:
                self._link.write_line('STOP')

    # ---- background loop ----
    def _run(self):
        while not self._stop.wait(POLL_S):
            with self._lock:
                if self._link is None:
                    return
                try:
                    for line in self._link.read_lines():
                        self._handle(line)
                    self._maybe_send_target()
                except Exception as exc:         # serial unplugged, etc.
                    self._log(f'LINK ERROR: {exc}')
                    self.disconnect()
                    return

    def _maybe_send_target(self):
        if self.tracking is None or time.monotonic() - self._last_send < TICK_S:
            return
        self._last_send = time.monotonic()
        st = tracker.tracked(self.tracking)
        if st is None or st['az'] is None:
            self._log('NO SOLUTION FOR TARGET. NOT SENDING.')
            return
        if st['el'] < 0.0:
            if not self._warned_horizon:
                self._log('TARGET BELOW HORIZON. HOLDING POSITION.')
                self._warned_horizon = True
            return                       # firmware watchdog will stop motion
        self._warned_horizon = False
        self._link.write_line(
            f"T,{st['az']:.3f},{st['el']:.3f},{st['az_rate']:.4f},{st['el_rate']:.4f}")

    # ---- status for the dashboard ----
    def status(self):
        with self._lock:
            return {
                'connected': self._link is not None,
                'link': self._link.name if self._link else None,
                'state': self.state,
                'tracking': self.tracking,
                'pos': self.pos,
                'log': list(self.log)[-20:],
            }


gimbal = Gimbal()