"""Subprocess defaults shared by GUI and worker scripts: no console windows."""
import os
import subprocess as _subprocess
from subprocess import *  # re-export standard constants and exceptions


def _options(kwargs):
    if os.name == 'nt':
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | _subprocess.CREATE_NO_WINDOW
    return kwargs


def Popen(*args, **kwargs):
    return _subprocess.Popen(*args, **_options(kwargs))


def run(*args, **kwargs):
    return _subprocess.run(*args, **_options(kwargs))
