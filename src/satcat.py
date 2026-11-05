"""Official catalog facts for each satellite (owner, object type, launch date).

CelesTrak's SATCAT is a separate file from the TLEs. It does not change often,
so we cache it for a week. Everything here is optional: if the download fails
or the file is missing, the dashboard simply shows less. Nothing crashes.
"""
import csv
import os
import time
import urllib.request

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
SATCAT_URL = 'https://celestrak.org/satcat/records.php?GROUP=visual&FORMAT=CSV'
SATCAT_FILE = os.path.join(DATA_DIR, 'visual_satcat.csv')
MAX_AGE_SECONDS = 7 * 24 * 3600

# CelesTrak OBJECT_TYPE codes
TYPE_NAMES = {
    'PAY': 'Payload',
    'R/B': 'Rocket body',
    'DEB': 'Debris',
    'UNK': 'Unknown',
}

# Subset of CelesTrak's owner codes (full list: celestrak.org/satcat/sources.php).
# Anything not listed here is shown as the raw code, which is still true.
OWNER_NAMES = {
    'US': 'United States',
    'CIS': 'Former USSR / Russia',
    'PRC': "People's Republic of China",
    'JPN': 'Japan',
    'IND': 'India',
    'FR': 'France',
    'UK': 'United Kingdom',
    'ESA': 'European Space Agency',
    'GER': 'Germany',
    'IT': 'Italy',
    'CA': 'Canada',
    'ISS': 'International Space Station partners',
    'NATO': 'NATO',
    'ISRO': 'Indian Space Research Organisation',
}

_records = None   # {norad_id: dict}


def _download():
    os.makedirs(DATA_DIR, exist_ok=True)
    # CelesTrak asks automated clients to identify themselves. Generic name only.
    req = urllib.request.Request(SATCAT_URL, headers={'User-Agent': 'argus-twin-student-project'})
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read()
    tmp = SATCAT_FILE + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(body)
    os.replace(tmp, SATCAT_FILE)


def _is_stale():
    if not os.path.exists(SATCAT_FILE):
        return True
    return (time.time() - os.path.getmtime(SATCAT_FILE)) > MAX_AGE_SECONDS


def parse(path):
    """Read a SATCAT CSV into {norad_id: record}. Tolerates missing columns."""
    out = {}
    with open(path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            try:
                norad = int(row.get('NORAD_CAT_ID', '').strip())
            except ValueError:
                continue
            code = (row.get('OBJECT_TYPE') or '').strip()
            owner = (row.get('OWNER') or '').strip()
            out[norad] = {
                'object_type': code,
                'object_type_name': TYPE_NAMES.get(code, code or 'Unknown'),
                'owner_code': owner,
                'owner': OWNER_NAMES.get(owner, owner),
                'launch_date': (row.get('LAUNCH_DATE') or '').strip(),
                'launch_site': (row.get('LAUNCH_SITE') or '').strip(),
                'object_id': (row.get('OBJECT_ID') or '').strip(),
            }
    return out


def load():
    """Load (downloading if needed). Never raises: returns whatever it has."""
    global _records
    if _is_stale():
        try:
            _download()
        except Exception:
            pass   # keep an old file if we have one
    if os.path.exists(SATCAT_FILE):
        try:
            _records = parse(SATCAT_FILE)
            return _records
        except Exception:
            pass
    _records = {}
    return _records


def get(norad):
    """Record for one satellite, or {} if we have no catalog data."""
    if _records is None:
        load()
    return _records.get(int(norad), {})