"""Frozen CLI dispatcher; only the three existing internal entry points."""
import runpy
import sys
from pathlib import Path

if __name__ == '__main__':
    args = sys.argv[1:]
    while args and args[0] in ('-u', '-B'):
        args.pop(0)
    name = Path(args[0]).stem if args else ''
    if name not in ('dashcam_worker', 'dashcam_downloader', 'dashcam_stitch'):
        raise SystemExit('Expected an internal DashGo worker module.')
    sys.argv = args
    runpy.run_module(name, run_name='__main__')
