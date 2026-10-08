"""Capture-only, confirmed-scope recycling. Never permanently deletes files."""
from dataclasses import dataclass
from pathlib import Path
import ctypes
import json
import os
import re
import stat
import uuid

ACTIVE = {'starting', 'recording', 'reconnecting', 'preparing', 'rendering', 'waiting',
          'checking', 'assembling', 'verifying', 'cleaning', 'recycling'}


def checked_path(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Capture paths must be absolute and cannot contain parent traversal.')
    for node in (*reversed(path.parents), path):
        info = node.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked folders, junctions and reparse points cannot be recycled here.')
    return path.resolve(strict=True)


def session_for(root, path):
    root, path = checked_path(root), checked_path(path)
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        raise ValueError('Selected item is outside the capture folder.') from None
    external_final = bool(parts and parts[0] == 'Exports')
    if external_final:
        # Only individual generated final files, never the export hierarchy.
        # The directory name maps to the original session; manifest paths are
        # intentionally ignored, even if a record has an "output" field.
        if (len(parts) != 4 or not re.fullmatch(r'Capture_[^/]+', parts[1])
                or not re.fullmatch(r'Finalized_[^/]+', parts[2])
                or parts[3] not in {'Capture.mp4', 'Capture.partial.mp4'}
                or not path.is_file()):
            raise ValueError('Select an individual final MP4, not an export folder.')
        session = root / parts[1]
    elif not parts or not parts[0].startswith('Capture_'):
        raise ValueError('Select capture sessions or their listed media files, not the library folder.')
    else:
        session = root / parts[0]
    # lstat distinguishes an absent source from a dangling link/junction.
    # Permission errors also propagate instead of being interpreted as absence.
    try:
        session.lstat()
    except FileNotFoundError:
        orphan = external_final
        if not orphan:
            raise ValueError('Capture session folder is missing.') from None
    else:
        checked_path(session)
        orphan = False
    records = []
    if orphan:
        record_path = checked_path(path.parent / 'finalize.json')
        record = json.loads(record_path.read_text(encoding='utf-8'))
        if not isinstance(record, dict) or record.get('state') not in {'finished', 'failed', 'cancelled'}:
            raise ValueError('This final needs a completed export status before it can be recycled.')
    else:
        if not session.is_dir():
            raise ValueError('Capture session folder is missing.')
        if os.path.lexists(session / '.export.lock'):
            raise ValueError('This capture has an export lock. Finish its export before recycling files.')
        record_path = session / 'session.json'
        checked_path(record_path)
        record = json.loads(record_path.read_text(encoding='utf-8'))
        if not isinstance(record, dict):
            raise ValueError('Capture status is not a valid record. No files were changed.')
        if record.get('state') in ACTIVE:
            raise ValueError('This session still reports an active capture. Finish its job first.')
        records = [session / 'Rendered' / 'render.json', *session.glob('Finalized_*/finalize.json')]
    export_group = root / 'Exports' / session.name
    if os.path.lexists(export_group):
        checked_path(export_group)
        records.extend(export_group.glob('Finalized_*/finalize.json'))
    for record_path in records:
        if record_path.exists() or record_path.is_symlink():
            checked_path(record_path)
            record = json.loads(record_path.read_text(encoding='utf-8'))
            if not isinstance(record, dict):
                raise ValueError('Render/export status is not a valid record. No files were changed.')
            if record.get('state') in ACTIVE:
                raise ValueError('This session still reports active rendering or export. Finish its job first.')
    if path != session and not external_final:
        relative = path.relative_to(session).as_posix()
        allowed = (r'part_\d{6}\.mkv', r'Rendered/part_\d{6}(?:\.partial)?\.mp4',
                   r'Finalized_[^/]+/Capture(?:\.partial)?\.mp4')
        if not path.is_file() or not any(re.fullmatch(pattern, relative) for pattern in allowed):
            raise ValueError('Only listed raw, rendered or final capture media can be recycled individually.')
    return session


def snapshot(path):
    rows = []
    pending = [path]
    while pending:
        node = pending.pop()
        checked_path(node)
        info = node.lstat()
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError('Unsupported file type in capture selection.')
        rows.append((str(node), info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns))
        if stat.S_ISDIR(info.st_mode):
            pending.extend(node.iterdir())
    return tuple(sorted(rows))


@dataclass(frozen=True)
class RecycleItem:
    path: Path
    session: Path
    kind: str
    fingerprint: tuple

    @property
    def file_count(self):
        return sum(stat.S_ISREG(row[3]) for row in self.fingerprint)

    @property
    def size(self):
        return sum(row[4] for row in self.fingerprint if stat.S_ISREG(row[3]))


def plan_recycle(root, paths):
    root = checked_path(root)
    unique = sorted({Path(path) for path in paths}, key=lambda path: (len(path.parts), str(path)))
    selected = []
    for path in unique:
        session = session_for(root, path)
        path = checked_path(path)
        if any(path.is_relative_to(item.path) for item in selected):
            continue  # A selected session already covers its selected children.
        kind = 'Entire session (all files)' if path == session else 'Raw segment' if path.suffix == '.mkv' else 'Rendered segment' if path.parent.name == 'Rendered' else 'Final export'
        selected.append(RecycleItem(path, session, kind, snapshot(path)))
    if not selected:
        raise ValueError('Select one or more capture sessions or capture media files first.')
    return tuple(selected)


def validate_item(root, item):
    if session_for(root, item.path) != item.session or snapshot(item.path) != item.fingerprint:
        raise ValueError('Selection changed after confirmation. Refresh the library and select it again.')


def recycle_plan(root, items, *, is_busy, recycle=None):
    recycle = recycle or recycle_windows
    if is_busy():
        raise ValueError('Media jobs are active. Finish them before recycling captures.')
    for item in items:
        validate_item(root, item)
    moved, failures = [], []
    for item in items:
        try:
            if is_busy():
                raise ValueError('A media job started. Remaining items were left in place.')
            validate_item(root, item)
            def validate_before_recycle():
                if is_busy():
                    raise ValueError('A media job started. Remaining items were left in place.')
                validate_item(root, item)
            recycle(item.path, validate_before_recycle)
            if os.path.lexists(item.path):
                raise OSError('Windows did not recycle this item.')
            moved.append(item.path)
        except (OSError, ValueError) as exc:
            failures.append((item.path, str(exc)))
            break  # Do not keep deleting after cancellation or an unexpected failure.
    return moved, failures


def recycle_windows(path, validate=lambda: None):
    if os.name != 'nt':
        raise OSError('Recycle Bin is only supported on Windows. No files were deleted.')
    if tuple(__import__('sys').getwindowsversion()[:2]) < (6, 2):
        raise OSError('Safe recycling requires Windows 8 or later.')
    path = checked_path(path)
    shell, ole = ctypes.WinDLL('shell32'), ctypes.WinDLL('ole32')
    void = ctypes.c_void_p
    HRESULT, DWORD = ctypes.c_long, ctypes.c_ulong
    GUID = ctypes.c_ubyte * 16
    guid = lambda value: GUID.from_buffer_copy(uuid.UUID(value).bytes_le)
    def check(code):
        if code < 0:
            raise OSError(f'Windows could not recycle the item (0x{code & 0xffffffff:08X}). No permanent-delete fallback was used.')
    def method(pointer, index, *types):
        address = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(void))).contents[index]
        return ctypes.WINFUNCTYPE(HRESULT, void, *types)(address)
    ole.CoInitializeEx.argtypes = [void, DWORD]
    ole.CoInitializeEx.restype = HRESULT
    init = ole.CoInitializeEx(None, 2)
    if init not in (0, 1, -2147417850):  # RPC_E_CHANGED_MODE: use the existing apartment.
        check(init)
    operation, item = void(), void()
    sink = _RecycleSink(validate)
    try:
        ole.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), void, DWORD, ctypes.POINTER(GUID), ctypes.POINTER(void)]
        ole.CoCreateInstance.restype = HRESULT
        check(ole.CoCreateInstance(guid('3ad05575-8857-4850-9277-11b85bdb8e09'), None, 1,
                                  guid('947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8'), ctypes.byref(operation)))
        # RECYCLEONDELETE + ADDUNDORECORD; fail rather than display error/skip UI.
        # PreDeleteItem additionally vetoes any non-recycling operation.
        flags = 0x00080000 | 0x20000000 | 0x00100000 | 0x0400 | 0x0010 | 0x0004 | 0x2000
        check(method(operation, 5, DWORD)(operation, flags))
        shell.SHCreateItemFromParsingName.argtypes = [ctypes.c_wchar_p, void, ctypes.POINTER(GUID), ctypes.POINTER(void)]
        shell.SHCreateItemFromParsingName.restype = HRESULT
        check(shell.SHCreateItemFromParsingName(str(path), None, guid('43826d1e-e718-42ee-bc55-a1e261c37bfe'), ctypes.byref(item)))
        check(method(operation, 18, void, void)(operation, item, ctypes.byref(sink.instance)))
        validate()
        code = method(operation, 21)(operation)
        if sink.error:
            raise OSError(sink.error)
        check(code)
        aborted = ctypes.c_int()
        check(method(operation, 22, ctypes.POINTER(ctypes.c_int))(operation, ctypes.byref(aborted)))
        if aborted.value:
            raise OSError('Recycling was cancelled or incomplete. Remaining items were kept.')
    finally:
        if item: method(item, 2)(item)
        if operation: method(operation, 2)(operation)
        if init in (0, 1): ole.CoUninitialize()


class _RecycleSink:
    """Native IFileOperationProgressSink that refuses permanent deletion."""
    def __init__(self, validate):
        void, uint, hr, wide = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long, ctypes.c_wchar_p
        self.error = ''
        self.references = 1
        sink_iid = uuid.UUID('04b0f1a7-9490-44bc-96e1-4296a31252e2').bytes_le
        unknown_iid = uuid.UUID('00000000-0000-0000-c000-000000000046').bytes_le
        def query(this, iid, output):
            if ctypes.string_at(iid, 16) not in (sink_iid, unknown_iid):
                output[0] = None
                return -2147467262
            output[0] = this
            self.references += 1
            return 0
        def addref(this):
            self.references += 1
            return self.references
        def release(this):
            self.references -= 1
            return self.references
        def predelete(this, flags, item):
            try:
                if not flags & 0x80:
                    raise OSError('Recycle Bin is unavailable for this item. Permanent deletion was blocked.')
                validate()
                return 0
            except Exception as exc:
                self.error = str(exc)
                return -2147467260  # E_ABORT, cancels all queued operations.
        signatures = [(void, ctypes.POINTER(void)), (), (), (), (hr,),
                      (uint, void, wide), (uint, void, wide, hr, void),
                      (uint, void, void, wide), (uint, void, void, wide, hr, void),
                      (uint, void, void, wide), (uint, void, void, wide, hr, void),
                      (uint, void), (uint, void, hr, void), (uint, void, wide),
                      (uint, void, wide, wide, uint, hr, void), (uint, uint), (), (), ()]
        functions = {0: query, 1: addref, 2: release, 11: predelete}
        self.callbacks = [ctypes.WINFUNCTYPE(hr, void, *args)(functions.get(index, lambda *args: 0))
                          for index, args in enumerate(signatures)]
        self.table = (void * len(self.callbacks))(*(ctypes.cast(callback, void).value for callback in self.callbacks))
        class Interface(ctypes.Structure):
            _fields_ = [('vtable', ctypes.POINTER(void))]
        self.instance = Interface(self.table)
