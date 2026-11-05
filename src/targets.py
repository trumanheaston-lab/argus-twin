"""One way to ask "where is this target right now?" for both modes.

A target id is either an integer (a satellite's NORAD number) or a string such as
'moon', 'jupiter', 'star:sirius' or 'm31' (an astronomical object).
"""
import sky
import tracker


def normalize(target_id):
    """Digits mean a satellite. Anything else is a sky object id. Raises ValueError."""
    if isinstance(target_id, bool) or target_id is None:
        raise ValueError('bad target')
    if isinstance(target_id, int):
        return target_id
    text = str(target_id).strip()
    if text.isdigit():
        return int(text)
    if text.lower() in sky.OBJECTS:
        return text.lower()
    raise ValueError('unknown target')


def state(target_id, t=None):
    """Pointing state for a satellite or sky object, or None if unknown."""
    if isinstance(target_id, int):
        return tracker.tracked(target_id, t)
    return sky.state(target_id, t)