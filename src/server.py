"""Flask backend for Argus-Twin.

Run from the project root:   python src/server.py
Then open:                   http://localhost:5000

The page in web/ is served by this same server, so the browser and the API
share one origin and no CORS setup is needed.
"""
import os

from flask import Flask, jsonify, request, send_from_directory

import gimbal  # pyright: ignore[reportMissingImports]
import satcat
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


@app.get('/')
def index():
    return send_from_directory(WEB_DIR, 'index.html')


@app.get('/api/state')
def api_state():
    """One call per second from the dashboard.

    targets: every satellite currently above the minimum elevation
    tracked: the satellite you picked, even if it has set (so the panel can say so)
    """
    t = tracker.ts.now()
    min_el = request.args.get('min_el', default=tracker.MIN_ELEVATION_DEG, type=float)
    targets = tracker.overhead(t, min_el)
    for target in targets:
        rec = satcat.get(target['norad'])
        target['featured'] = target['norad'] in CATALOG
        target['type'] = rec.get('object_type', '')
    payload = {
        'utc': t.utc_iso(),
        'min_el': min_el,
        'targets': targets,
        'tracked': None,
    }
    track = request.args.get('track', type=int)
    if track is not None:
        payload['tracked'] = tracker.tracked(track, t)
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


def _body():
    return request.get_json(silent=True) or {}


@app.get('/api/gimbal')
def gimbal_status():
    return jsonify(gimbal.gimbal.status())


@app.post('/api/gimbal/connect')
def gimbal_connect():
    port = str(_body().get('port', '')).strip()
    if not port:
        return jsonify({'ok': False, 'message': 'port required (SIM or e.g. COM5)'}), 400
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
    norad = _body().get('norad')
    try:
        if norad is None:
            gimbal.gimbal.release()
            return jsonify({'ok': True, 'message': 'tracking lock released'})
        norad = int(norad)
        if tracker.tracked(norad) is None:
            return jsonify({'ok': False, 'message': 'unknown satellite'}), 404
        gimbal.gimbal.track(norad)
    except RuntimeError as exc:
        return jsonify({'ok': False, 'message': str(exc)}), 409
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'message': 'bad norad'}), 400
    return jsonify({'ok': True, 'message': f'tracking NORAD {norad}'})


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


@app.post('/api/refresh')
def api_refresh():
    ok, message = tracker.force_refresh()
    return jsonify({'ok': ok, 'message': message}), (200 if ok else 429)


if __name__ == '__main__':
    tracker.load_satellites()
    satcat.load()
    app.run(host='127.0.0.1', port=5000, debug=False)
    