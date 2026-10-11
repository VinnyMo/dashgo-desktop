"""Confirmed deletion plans for selected media and provably owned leftovers.

Never follows manifest paths, sweeps the library, or permanently removes folders.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat

import dashcam_recycle as recycle_api
from dashcam_recycle import checked_path, snapshot, session_for

FINAL_SUPPORT = {'finalize.json', 'segments.ffconcat', 'progress.log', 'ffmpeg.log',
                 'cleanup.json', 'cleanup.json.tmp'}
RENDER_SUPPORT = {'render.json', 'render.json.tmp', '.capture.shuffled_playlist.m4a',
                  'channel.txt', 'route.txt'}
RAW = r'part_\d{6}\.mkv'
RENDER = r'part_\d{6}(?:\.partial)?\.mp4'
DRIVE = r'Drive_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:_(?:0\.5GB|1GB|2GB|4GB|8GB|1GBH|2GBH|4GBH|8GBH))?'
SOURCE = r'\d{4}-\d{2}-\d{2}_\d{2}_\d{2}_\d{2}_f\.ts'


@dataclass(frozen=True)
class Removal:
    path: Path
    kind: str
    fingerprint: tuple

    @property
    def file_count(self):
        return sum(stat.S_ISREG(row[3]) for row in self.fingerprint)

    @property
    def size(self):
        return sum(row[4] for row in self.fingerprint if stat.S_ISREG(row[3]))


@dataclass(frozen=True)
class DeletionPlan:
    items: tuple
    capture_root: Path
    sessions: tuple
    guards: tuple
    sources: tuple
    retained_folders: tuple


def _children(directory):
    if not os.path.lexists(directory):
        return []
    checked_path(directory)
    return list(directory.iterdir())


def _terminal(record):
    checked_path(record)
    value = json.loads(record.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('state') not in {'stopped', 'interrupted', 'finished', 'failed', 'cancelled'}:
        raise ValueError('Capture or export status is active or uncertain. No associated files were removed.')


def plan_deletion(capture_root, transfer_root, capture_paths=(), transfer_paths=(), *, drive_prefixes=()):
    """Include only sidecars belonging to scopes whose last media is selected.

    Library roots and unselected sibling exports remain. A directory becomes a
    single recoverable item only when every descendant is already in the plan.
    """
    capture_root, transfer_root = Path(capture_root), Path(transfer_root)
    files, folders, sessions, sources, guards = set(), set(), set(), set(), {}

    def add(path):
        path = checked_path(path)
        if not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError('Only ordinary, unlinked owned files can be recycled.')
        files.add(path)

    def support(directory, allowed):
        for path in _children(directory):
            if allowed(path.name):
                add(path)
        if os.path.lexists(directory):
            folders.add(directory)

    def final_scope(directory):
        children = _children(directory)
        if any(p.name in {'Capture.mp4', 'Capture.partial.mp4'} and p not in files for p in children):
            return
        support(directory, lambda name: name in FINAL_SUPPORT)

    for path in sorted(set(map(Path, capture_paths))):
        session = session_for(capture_root, path)
        sessions.add(session.name)
        if path == session:
            for child in _children(session):
                if re.fullmatch(RAW, child.name):
                    add(child)
                elif child.name == 'Rendered':
                    for part in _children(child):
                        if re.fullmatch(RENDER, part.name): add(part)
                elif child.name.startswith('Finalized_') and child.is_dir():
                    for part in _children(child):
                        if part.name in {'Capture.mp4', 'Capture.partial.mp4'}: add(part)
                    final_scope(child)
        else:
            add(path)
            # A partial with this exact output basename belongs to the same
            # render attempt. Selecting a partial alone never selects its final.
            companion = (path.with_name('Capture.partial.mp4') if path.name == 'Capture.mp4'
                         else path.with_name(path.stem+'.partial.mp4') if re.fullmatch(r'part_\d{6}\.mp4', path.name)
                         else None)
            if companion and os.path.lexists(companion): add(companion)

    for name in sessions:
        session = capture_root/name
        group = capture_root/'Exports'/name
        records = []
        if os.path.lexists(session):
            records.append(session/'session.json')
            records += [p for p in [session/'Rendered'/'render.json'] if os.path.lexists(p)]
        for parent in (session, group):
            for child in _children(parent):
                if child.name.startswith('Finalized_') and child.is_dir():
                    record = child/'finalize.json'
                    if os.path.lexists(record): records.append(record)
                    # Do not sweep historical sibling folders: selected media
                    # must actually belong to this export for it to qualify.
                    if any(p.parent == child for p in files): final_scope(child)
        for record in records:
            _terminal(record);guards[record] = snapshot(record)
        render = session/'Rendered'
        remaining_render = [p for p in _children(render) if re.fullmatch(RENDER, p.name) and p not in files]
        if not remaining_render:
            support(render, lambda n: n in RENDER_SUPPORT or bool(re.fullmatch(r'track-\d+\.txt', n)))
        remaining_raw = [p for p in _children(session) if re.fullmatch(RAW, p.name) and p not in files]
        remaining_legacy = [p for f in _children(session) if f.name.startswith('Finalized_') and f.is_dir()
                            for p in _children(f) if p.name in {'Capture.mp4', 'Capture.partial.mp4'} and p not in files]
        if not remaining_render and not remaining_raw and not remaining_legacy:
            support(session, lambda n: n in {'session.json', 'session.json.tmp'})
        if os.path.lexists(group): folders.add(group)
    if sessions and os.path.lexists(capture_root/'Exports'):
        folders.add(capture_root/'Exports')

    selected_transfers = set(map(Path, transfer_paths))
    drives = transfer_root/'Drives'
    for prefix in drive_prefixes:
        if not re.fullmatch(r'Drive_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}', prefix):
            raise ValueError('Invalid transferred-drive identity.')
        for path in _children(drives):
            if re.fullmatch(DRIVE+r'\.mp4(?:\.part\.mp4)?', path.name) and (path.name.startswith(prefix+'.') or path.name.startswith(prefix+'_')):
                selected_transfers.add(path)
    stems = set()
    for prefix in drive_prefixes:
        for path in _children(drives):
            match = re.fullmatch(r'\.('+DRIVE+r')\.\d+\.(?:drive\.ffconcat|shuffled_playlist\.m4a|track-\d+\.txt|channel\.txt|route\.txt)', path.name)
            if match and (match[1] == prefix or match[1].startswith(prefix+'_')):
                stems.add(match[1])
    for path in selected_transfers:
        path = checked_path(path)
        root = checked_path(transfer_root)
        if path.parent == root and re.fullmatch(SOURCE+r'(?:\.part)?', path.name):
            add(path)
            if path.name.endswith('.ts'):
                sources.add(path)
                partial = path.with_name(path.name+'.part')
                if os.path.lexists(partial): add(partial)
        elif path.parent == drives and re.fullmatch(DRIVE+r'\.mp4(?:\.part\.mp4)?', path.name):
            add(path);stems.add(path.name.split('.mp4')[0])
            if not path.name.endswith('.part.mp4'):
                partial = path.with_name(path.name+'.part.mp4')
                if os.path.lexists(partial): add(partial)
        else:
            raise ValueError('Selected file is not an owned transfer or drive output.')
    for stem in stems:
        media = [p for p in _children(drives) if p.name in {stem+'.mp4', stem+'.mp4.part.mp4'}]
        if any(p not in files for p in media): continue
        pattern = re.escape('.'+stem)+r'\.\d+\.(?:drive\.ffconcat|shuffled_playlist\.m4a|track-\d+\.txt|channel\.txt|route\.txt)'
        for path in _children(drives):
            if re.fullmatch(pattern, path.name): add(path)
    if selected_transfers and os.path.lexists(drives): folders.add(drives)

    # Collapse only completely covered owned directories. Unknown files and
    # unknown/empty subdirectories deliberately prevent parent removal.
    chosen = set(files)
    for folder in sorted(folders, key=lambda p: len(p.parts), reverse=True):
        if folder in (capture_root, transfer_root):
            continue  # A customized/nested library root is still shared.
        children = _children(folder)
        if all(p in chosen for p in children):
            checked_path(folder)
            chosen.difference_update(children);chosen.add(folder)
    if not chosen:
        raise ValueError('No selected media or owned associated files remain. Refresh the library.')
    items = tuple(Removal(p, 'Media and associated files' if p.is_dir() else 'Selected media / associated file', snapshot(p))
                  for p in sorted(chosen, key=lambda p: (len(p.parts), str(p))))
    retained = tuple(sorted(p for p in folders if not any(p == item or p.is_relative_to(item) for item in chosen)))
    return DeletionPlan(items, capture_root, tuple(sorted(sessions)), tuple(guards.items()), tuple(sorted(sources)), retained)


def recycle_deletion(plan, *, is_busy, recycle=None, source_removed=lambda path: None):
    recycle = recycle or recycle_api.recycle_windows
    moved, failures = [], []

    def covered(path):
        return any(path == p or path.is_relative_to(p) for p in moved)

    def validate(item):
        if is_busy(): raise ValueError('Media jobs are active or the app is closing. Remaining files were kept.')
        if any(os.path.lexists(path) for path in moved):
            raise ValueError('A removed item reappeared. Remaining files were kept.')
        for name in plan.sessions:
            session = plan.capture_root/name
            if os.path.lexists(session):
                if os.path.lexists(session/'.export.lock'):
                    raise ValueError('An export lock appeared. Remaining files were kept.')
                record = session/'session.json'
                if os.path.lexists(record): _terminal(record)
        for record, stamp in plan.guards:
            if not covered(record) and snapshot(record) != stamp:
                raise ValueError('Capture/export status changed. Remaining files were kept.')
        if snapshot(item.path) != item.fingerprint:
            raise ValueError('Selection or folder contents changed. Refresh and review the new scope.')

    try:
        for item in plan.items: validate(item)
    except (OSError, ValueError) as exc:
        return moved, [(plan.items[0].path, str(exc))]
    for item in plan.items:
        try:
            validate(item)
            recycle(item.path, lambda item=item: validate(item))
            if os.path.lexists(item.path): raise OSError('Windows did not recycle this item.')
            moved.append(item.path)
            for source in plan.sources:
                if source == item.path or source.is_relative_to(item.path): source_removed(source)
        except Exception as exc:
            failures.append((item.path, str(exc)));break
    return moved, failures
