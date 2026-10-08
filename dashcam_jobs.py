"""Own a CLI and all descendants without enumerating unrelated processes."""
import ctypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading


class _WindowsJob:
    def __init__(self):
        from ctypes import wintypes as wt
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
        self.api.CreateJobObjectW.restype = wt.HANDLE
        self.api.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
        self.api.SetInformationJobObject.restype = wt.BOOL
        self.api.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
        self.api.AssignProcessToJobObject.restype = wt.BOOL
        self.api.CloseHandle.argtypes = [wt.HANDLE]
        self.api.CloseHandle.restype = wt.BOOL
        class BasicLimits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wt.DWORD), ('min_working_set', ctypes.c_size_t),
                        ('max_working_set', ctypes.c_size_t), ('active_process_limit', wt.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wt.DWORD), ('scheduling', wt.DWORD)]
        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic', BasicLimits), ('io', IoCounters),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            if not self.api.CloseHandle(self.handle):
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = None


class OwnedCommand:
    """Gated command tree. Always call close(), including after natural exit.

    ``process.stdout`` is UTF-8 text, with stderr merged. Use this object's
    cancel() rather than terminating process alone: process is a bootstrap.
    """
    def __init__(self, command):
        if not command or isinstance(command, (str, bytes)):
            raise ValueError('Command must be a nonempty argument sequence.')
        self.process = None
        self._job = None
        self._lock = threading.Lock()
        self._tree_closed = False
        self._watcher = None
        self._watch_error = None
        try:
            if os.name == 'nt':
                self._job = _WindowsJob()
            options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
            self.process = subprocess.Popen(
                [sys.executable, '-u', '-B', str(Path(__file__).with_name('dashcam_worker.py')), *map(str, command)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', **options)
            if self._job:
                self._job.assign(self.process)
            # Nothing in command can run before successful assignment.
            self.process.stdin.write('GO\n'); self.process.stdin.flush(); self.process.stdin.close()
            self._watcher = threading.Thread(target=self._watch, daemon=True)
            self._watcher.start()
        except BaseException:
            if self.process:
                if self.process.poll() is None:
                    self.process.terminate()
                self.process.wait(timeout=5)
                for stream in (self.process.stdin, self.process.stdout):
                    if stream and not stream.closed: stream.close()
            if self._job: self._job.close()
            raise

    def _close_tree(self):
        with self._lock:
            if self._tree_closed: return
            if self._job:
                self._job.close()
            elif self.process:
                try: os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            self._tree_closed = True

    def _watch(self):
        self.process.wait()
        try: self._close_tree()
        except OSError as exc: self._watch_error = exc

    def poll(self):
        return self.process.poll()

    def wait(self, timeout=None):
        code = self.process.wait(timeout=timeout)
        self._close_tree()
        if self._watch_error: raise self._watch_error
        return code

    def cancel(self):
        self._close_tree()

    def close(self):
        self.cancel()
        self.wait(timeout=5)
        if self._watcher: self._watcher.join(5)
        for stream in (self.process.stdin, self.process.stdout):
            if stream and not stream.closed: stream.close()

    def __enter__(self): return self

    def __exit__(self, *_): self.close()
