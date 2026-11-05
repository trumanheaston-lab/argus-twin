"""Flask backend for Argus-Twin.

Run from the project root:   python src/server.py
Then open:                   http://localhost:5000

The page in web/ is served by this same server, so the browser and the API
share one origin and no CORS setup is needed.
"""
import os

from flask import Flask, jsonify, request, send_from_directory

import gimbal
import horizon
import safety
import satcat
import sky
import targets
import tracker
from catalog import CATALOG

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'web')

app = Flask(__name__, static_folder=WEB_DIR, static_url_path='')


def classification_line(rec):
    """One true sentence built from SATCAT fields, for satellites with no
    hand-written write-up."""
    if not rec:
        return None
    parts = [rec.get('object_type_name') or 'Unknown object']
    if rec.get('owner'):
        parts.append('owner: ' + rec['owner'])
    line = '. '.join(p[0].upper() + p[1:] for p in parts) + '.'
    if rec.get('launch_date'):
        line += ' Launched ' + rec['launch_date']
        if rec.get('launch_site'):
            line += ' from site code ' + rec['launch_site']
        line += '.'
    return line


def _body():
    return request.get_json(silent=True) or {}


def _sun(t):
    alt, az = safety.sun_altaz(t)
    return {'alt': round(alt, 2), 'az': round(az, 2)}


def _blocked_by(st, t):
    """Why this target cannot be pointed at right now, or None if it can."""
    if st is None or st.get('az') is None or st['el'] < 0:
        return None
    if horizon.blocked(st['az'], st['el']):
        return f"HORIZON MASK ({horizon.floor(st['az']):.0f} deg here)"
    return safety.keepout_reason(st['az'], st['el'], t)


def _floor_from_request():
    """A ?min_el=NN override gives a flat floor. Otherwise the horizon mask is used."""
    override = request.args.get('min_el', type=float)
    return override, ((lambda az: override) if override is not None else horizon.floor)


@app.get('/')
def index():
    return send_from_directory(WEB_DIR, 'index.html')


# ---- satellites -----------------------------------------------------------------

@app.get('/api/state')
def api_state():
    """One call per second from the dashboard.

    targets: every satellite above the horizon mask
    tracked: the satellite you picked, even if it has set (so the panel can say so)
    """
    t = tracker.ts.now()
    override, floor = _floor_from_request()
    found = [s for s in tracker.overhead(t, 0.0)
             if s['az'] is not None and s['el'] > floor(s['az'])]
    for target in found:
        rec = satcat.get(target['norad'])
        target['featured'] = target['norad'] in CATALOG
        target['type'] = rec.get('object_type', '')
        target['near_sun'] = safety.keepout_reason(target['az'], target['el'], t) is not None
    payload = {
        'utc': t.utc_iso(),
        'min_el': override if override is not None else tracker.MIN_ELEVATION_DEG,
        'sun': _sun(t),
        'targets': found,
        'tracked': None,
    }
    track = request.args.get('track', type=int)
    if track is not None:
        st = tracker.tracked(track, t)
        if st is not None:
            st['blocked'] = _blocked_by(st, t)
        payload['tracked'] = st
    return jsonify(payload)


@app.get('/api/info/<int:norad>')
def api_info(norad):
    info = tracker.sat_info(norad)
    if info is None:
        return jsonify({'error': 'unknown satellite'}), 404
    rec = satcat.get(norad)
    info.update(rec)
    info['classification'] = classification_line(rec)
    info.update(CATALOG.get(norad, {}))
    info['featured'] = norad in CATALOG
    return jsonify(info)


@app.post('/api/refresh')
def api_refresh():
    ok, message = tracker.force_refresh()
    return jsonify({'ok': ok, 'message': message}), (200 if ok else 429)


# ---- astronomy ------------------------------------------------------------------

@app.get('/api/sky/state')
def sky_state():
    """Like /api/state, but for the Moon, planets, stars and deep-sky objects."""
    t = tracker.ts.now()
    override, floor = _floor_from_request()
    found = [o for o in sky.visible(t, 0.0) if o['el'] > floor(o['az'])]
    found = [dict(o, near_sun=safety.keepout_reason(o['az'], o['el'], t) is not None)
             for o in found]
    sun = _sun(t)
    payload = {
        'utc': t.utc_iso(),
        'sun': sun,
        'daylight': sun['alt'] > -6.0,         # brighter than civil twilight
        'ephemeris': sky.get_ephemeris() is not None,
        'ephemeris_error': sky.ephemeris_error(),
        'targets': found,
        'tracked': None,
    }
    track = request.args.get('track')
    if track:
        st = sky.state(track.lower(), t)
        if st is not None:
            st['blocked'] = _blocked_by(st, t)
        payload['tracked'] = st
    return jsonify(payload)


@app.get('/api/sky/info/<obj_id>')
def sky_info(obj_id):
    info = sky.info(obj_id.lower())
    if info is None:
        return jsonify({'error': 'unknown object'}), 404
    return jsonify(info)


# ---- horizon mask -----------------------------------------------------------------

def _horizon_payload():
    return {
        'points': [{'az': a, 'el': e} for a, e in horizon.points()],
        'default_el': horizon.DEFAULT_FLOOR_DEG,
        'profile': horizon.profile(),
    }


@app.get('/api/horizon')
def horizon_get():
    return jsonify(_horizon_payload())


@app.put('/api/horizon')
def horizon_put():
    try:
        horizon.set_points(_body().get('points', []))
    except ValueError as exc:
        return jsonify({'ok': False, 'message': str(exc)}), 400
    return jsonify(dict(_horizon_payload(), ok=True, message='horizon mask saved'))


@app.post('/api/horizon/sample')
def horizon_sample():
    """Add a point at wherever the mount is pointing right now. Point the scope at the
    top edge of a tree or roof with the hand controller, then call this."""
    status = gimbal.gimbal.status()
    if not status['connected'] or not status['pos']:
        return jsonify({'ok': False, 'message': 'connect the mount first'}), 409
    pos = status['pos']
    horizon.add_point(pos['az'], pos['el'])
    return jsonify(dict(_horizon_payload(), ok=True,
                        message=f"added point az {pos['az']:.1f}, el {pos['el']:.1f}"))


# ---- gimbal / mount ----------------------------------------------------------------

@app.get('/api/gimbal')
def gimbal_status():
    return jsonify(gimbal.gimbal.status())


@app.post('/api/gimbal/connect')
def gimbal_connect():
    port = str(_body().get('port', '')).strip()
    if not port:
        return jsonify({'ok': False, 'message': 'port required (SIM, COM5, or NEXSTAR:COM5)'}), 400
    try:
        gimbal.gimbal.connect(port)
    except Exception as exc:
        return jsonify({'ok': False, 'message': f'could not connect: {exc}'}), 500
    return jsonify({'ok': True, 'message': 'connected to ' + port})


@app.post('/api/gimbal/disconnect')
def gimbal_disconnect():
    gimbal.gimbal.disconnect()
    return jsonify({'ok': True, 'message': 'disconnected'})


@app.post('/api/gimbal/track')
def gimbal_track():
    body = _body()
    raw = body.get('target', body.get('norad'))
    if raw is None:
        gimbal.gimbal.release()
        return jsonify({'ok': True, 'message': 'tracking lock released'})
    try:
        target = targets.normalize(raw)
    except ValueError:
        return jsonify({'ok': False, 'message': 'unknown target'}), 400
    if targets.state(target) is None:
        return jsonify({'ok': False, 'message': 'unknown target'}), 404
    try:
        gimbal.gimbal.track(target)
    except RuntimeError as exc:
        return jsonify({'ok': False, 'message': str(exc)}), 409
    return jsonify({'ok': True, 'message': f'tracking {target}'})


@app.post('/api/gimbal/command')
def gimbal_command():
    cmd = str(_body().get('cmd', '')).upper()
    if cmd not in gimbal.COMMANDS:
        return jsonify({'ok': False, 'message': 'unknown command'}), 400
    try:
        gimbal.gimbal.command(cmd)
    except RuntimeError as exc:
        return jsonify({'ok': False, 'message': str(exc)}), 409
    return jsonify({'ok': True, 'message': cmd + ' sent'})


if __name__ == '__main__':
    tracker.load_satellites()
    satcat.load()
    sky.get_ephemeris()          # first run downloads data/de421.bsp (about 17 MB)
    app.run(host='127.0.0.1', port=5000, debug=False)