"""A fake Celestron NexStar mount that behaves like a serial port.

It understands the same byte commands as the real hand controller (z, b, L, M, T,
P, V, m, K) and moves in real time, so NexStarLink can be tested with no hardware.
"""
import time


class FakeNexStar:
    def __init__(self, az=0.0, alt=0.0, goto_dps=60.0, invert_az=False):
        self.az, self.alt = az, alt
        self.rate_az = self.rate_alt = 0.0      # deg/s, set by 'P' commands
        self.goto_dps = goto_dps
        self.invert_az = invert_az              # simulate a mount whose az sign is flipped
        self.tracking_mode = None
        self.written = []                       # every write(), for byte-level checks
        self._goto = None
        self._rx = b''
        self._tx = b''
        self._last = time.monotonic()
        self.closed = False

    # ---- serial-port-like interface ----
    def write(self, data):
        self.written.append(bytes(data))
        self._rx += data
        self._parse()

    def read(self, n=1):
        self._step()
        out, self._tx = self._tx[:n], self._tx[n:]
        return out

    @property
    def in_waiting(self):
        return len(self._tx)

    def close(self):
        self.closed = True

    # ---- the mount ----
    @staticmethod
    def _enc(deg):
        return b'%08X' % (int(round((deg % 360.0) / 360.0 * 4294967296.0)) & 0xFFFFFFFF)

    @staticmethod
    def _dec(hexbytes):
        v = int(hexbytes, 16) / 4294967296.0 * 360.0
        return v

    def _step(self):
        now = time.monotonic()
        dt, self._last = now - self._last, now
        if self._goto is not None:
            taz, talt = self._goto
            daz = (taz - self.az + 180.0) % 360.0 - 180.0
            dalt = talt - self.alt
            step = self.goto_dps * dt
            self.az = (self.az + max(-step, min(step, daz))) % 360.0
            self.alt += max(-step, min(step, dalt))
            if abs(daz) < 0.01 and abs(dalt) < 0.01:
                self._goto = None
        else:
            sign = -1.0 if self.invert_az else 1.0
            self.az = (self.az + sign * self.rate_az * dt) % 360.0
            self.alt += self.rate_alt * dt

    def _parse(self):
        self._step()
        while self._rx:
            c = self._rx[0:1]
            if c == b'z':
                self._tx += self._enc(self.az) + b',' + self._enc(self.alt) + b'#'
                self._rx = self._rx[1:]
            elif c == b'b':
                if len(self._rx) < 18:
                    return
                cmd, self._rx = self._rx[:18], self._rx[18:]
                self._goto = (self._dec(cmd[1:9]), self._dec(cmd[10:18]))
                if self._goto[1] > 180.0:
                    self._goto = (self._goto[0], self._goto[1] - 360.0)
                self.rate_az = self.rate_alt = 0.0
                self._tx += b'#'
            elif c == b'L':
                self._tx += (b'1#' if self._goto is not None else b'0#')
                self._rx = self._rx[1:]
            elif c == b'M':
                self._goto = None
                self._tx += b'#'
                self._rx = self._rx[1:]
            elif c == b'T':
                if len(self._rx) < 2:
                    return
                self.tracking_mode = self._rx[1]
                self._rx = self._rx[2:]
                self._tx += b'#'
            elif c == b'P':
                if len(self._rx) < 8:
                    return
                cmd, self._rx = self._rx[:8], self._rx[8:]
                axis, sign, hi, lo = cmd[2], cmd[3], cmd[4], cmd[5]
                rate = ((hi << 8) | lo) / 4.0 / 3600.0          # arcsec/s x4 -> deg/s
                rate = -rate if sign == 7 else rate
                if axis == 16:
                    self.rate_az = rate
                elif axis == 17:
                    self.rate_alt = rate
                self._tx += b'#'
            elif c == b'V':
                self._tx += bytes([4, 13]) + b'#'
                self._rx = self._rx[1:]
            elif c == b'm':
                self._tx += bytes([1]) + b'#'
                self._rx = self._rx[1:]
            elif c == b'K':
                if len(self._rx) < 2:
                    return
                self._tx += self._rx[1:2] + b'#'
                self._rx = self._rx[2:]
            else:
                self._rx = self._rx[1:]