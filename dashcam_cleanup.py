"""Recycle an exact export input snapshot after its final MP4 is verified.

No folder operations, manifest-supplied paths or permanent-delete fallback.
"""
import os
import re

from dashcam_recycle import checked_path, snapshot, recycle_windows


def generated_inputs(session, parts, playlist):
    session = checked_path(session)
    record = session / 'session.json'
    guards = {record: snapshot(record)}
    paths = list(parts)
    if playlist:
        render_record = session / 'Rendered' / 'render.json'
        guards[render_record] = snapshot(render_record)
        raw = sorted(session.glob('part_*.mkv'))
        if [p.stem for p in raw] != [p.stem for p in parts]:
            raise ValueError('Capture segments changed while preparing export.')
        paths += raw + [playlist]
    allowed = r'(part_\d{6}\.mkv|Rendered/part_\d{6}\.mp4|Rendered/\.capture\.shuffled_playlist\.m4a)'
    files = {}
    for path in paths:
        path = checked_path(path)
        if not path.is_file() or not path.is_relative_to(session) or not re.fullmatch(allowed, path.relative_to(session).as_posix()):
            raise ValueError('Export input is not a generated file inside this capture.')
        if path.stat().st_nlink != 1:
            raise ValueError('Hard-linked inputs must be retained; automatic cleanup is unavailable.')
        files[path] = snapshot(path)
    return files, guards


def recycle_inputs(session, files, guards, final, *, cancelled=lambda: False, recycle=None, audit=lambda result: None):
    """Final must already have passed media verification and atomic promotion."""
    recycle = recycle or recycle_windows
    session, final = checked_path(session), checked_path(final)
    final_stamp = snapshot(final)
    result = {'state': 'pending', 'planned': [p.relative_to(session).as_posix() for p in files],
              'recycled': [], 'reason': ''}
    def validate(path):
        if cancelled():
            raise ValueError('Cleanup cancelled. Remaining sources were retained.')
        if snapshot(final) != final_stamp or not final.stat().st_size:
            raise ValueError('Final export changed; sources were retained.')
        for guard, stamp in guards.items():
            if snapshot(guard) != stamp:
                raise ValueError('Capture or rendering status changed; sources were retained.')
        if path == final or not path.is_relative_to(session) or snapshot(path) != files[path]:
            raise ValueError('A generated input changed; sources were retained.')
    try:
        for path in files:
            validate(path)
        result['state'] = 'recycling'
        audit(result)
        for path in files:
            validate(path)
            recycle(path, lambda path=path: validate(path))
            if os.path.lexists(path):
                raise OSError('Windows did not recycle the input.')
            result['recycled'].append(path.relative_to(session).as_posix())
            audit(result)
        result['state'] = 'complete'
    except Exception as exc:
        result['state'], result['reason'] = 'incomplete', str(exc)
    audit(result)
    return result
