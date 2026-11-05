"""Safety checks that apply to every tracking mode.

The big one is the Sun. Pointing a telescope (or a camera behind it) at the Sun
can blind a person and destroy the optics, and a satellite pass or a planet can
carry the scope straight across it. So no target, and no slew path, is allowed
inside SUN_KEEPOUT_DEG of the Sun while the Sun is up.

The Sun's position here comes from a short analytic formula (the low-precision
solar coordinates from the Astronomical Almanac, good to about 0.01 degrees), so
this safety check never depends on a downloaded ephemeris file.
"""
import math

import tracker

SUN_KEEPOUT_DEG = 15.0        # stay this far from the Sun
SUN_UP_ALT_DEG = -2.0         # the Sun counts as "up" above this altitude


def sun_altaz(t=None):
    """(altitude, azimuth) of the Sun in degrees for the observer. Azimuth: 0 = north."""
    if t is None:
        t = tracker.ts.now()
    d = t.ut1 - 2451545.0                                   # days since J2000
    mean_lon = (280.460 + 0.9856474 * d) % 360.0
    anomaly = math.radians((357.528 + 0.9856003 * d) % 360.0)
    lam = math.radians(mean_lon + 1.915 * math.sin(anomaly) + 0.020 * math.sin(2 * anomaly))
    eps = math.radians(23.439 - 0.0000004 * d)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))

    lat = math.radians(tracker.OBSERVER.latitude.degrees)
    lon = tracker.OBSERVER.longitude.degrees
    gmst = (280.46061837 + 360.98564736629 * d) % 360.0
    ha = math.radians(gmst + lon) - ra

    sin_alt = math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(ha)
    alt = math.asin(max(-1.0, min(1.0, sin_alt)))
    az = math.atan2(-math.cos(dec) * math.sin(ha),
                    math.sin(dec) * math.cos(lat) - math.cos(dec) * math.cos(ha) * math.sin(lat))
    return math.degrees(alt), math.degrees(az) % 360.0


def separation(az1, el1, az2, el2):
    """Angle in degrees between two directions given as azimuth/elevation."""
    a1, e1, a2, e2 = map(math.radians, (az1, el1, az2, el2))
    c = math.sin(e1) * math.sin(e2) + math.cos(e1) * math.cos(e2) * math.cos(a1 - a2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def sun_up(t=None):
    return sun_altaz(t)[0] > SUN_UP_ALT_DEG


def keepout_reason(az, el, t=None):
    """None if the direction is safe, otherwise a short reason string."""
    s_alt, s_az = sun_altaz(t)
    if s_alt <= SUN_UP_ALT_DEG:
        return None
    sep = separation(az, el, s_az, s_alt)
    if sep < SUN_KEEPOUT_DEG:
        return f'SUN KEEP-OUT ({sep:.0f} deg from the Sun)'
    return None


def path_reason(start, end, t=None, step_deg=2.0):
    """Check the straight az/el path of a slew. start and end are (az, el).
    Returns None if clear, otherwise the reason. Real mounts move both axes at
    once, so this is an approximation, and it is deliberately on the cautious side."""
    s_alt, s_az = sun_altaz(t)
    if s_alt <= SUN_UP_ALT_DEG:
        return None
    (az0, el0), (az1, el1) = start, end
    daz = (az1 - az0 + 180.0) % 360.0 - 180.0
    span = max(abs(daz), abs(el1 - el0))
    n = max(2, int(span / step_deg) + 1)
    for i in range(n + 1):
        f = i / n
        sep = separation(az0 + daz * f, el0 + (el1 - el0) * f, s_az, s_alt)
        if sep < SUN_KEEPOUT_DEG:
            return f'SUN KEEP-OUT ON SLEW PATH ({sep:.0f} deg from the Sun)'
    return None