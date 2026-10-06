"""Temporary Windows idle-sleep inhibition, owned by the GUI thread."""
import ctypes
import os
import threading

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class KeepAwake:
    def __init__(self, setter=None):
        self.owner = threading.get_ident()
        self.active = False
        self.reasons = frozenset()
        self.setter = setter
        if setter is None and os.name == 'nt':
            self.setter = ctypes.WinDLL('kernel32', use_last_error=True).SetThreadExecutionState
            self.setter.argtypes = [ctypes.c_uint32]
            self.setter.restype = ctypes.c_uint32

    def update(self, reasons):
        if threading.get_ident() != self.owner:
            raise RuntimeError('Keep-awake requests must stay on their owning thread.')
        reasons = frozenset(reasons)
        wanted = bool(reasons) and self.setter is not None
        if wanted != self.active:
            # Never request DISPLAY_REQUIRED or AWAYMODE; saved power settings
            # remain unchanged and the display can sleep normally.
            flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if wanted else 0)
            if not self.setter(flags):
                raise OSError('Windows did not accept the temporary keep-awake request.')
            self.active = wanted
        self.reasons = reasons

    def close(self):
        self.update(())
