"""Verify packaged missing-FFmpeg diagnostics without touching media."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

package = Path(sys.argv[1]).resolve()
fixture = Path(tempfile.mkdtemp(prefix='dashgo-prerequisite-'))
source = fixture/'source'
source.mkdir()
# Filename alone is sufficient to reach prerequisite discovery; no media decode.
(source/'2026-01-01_12_00_00_f.ts').write_bytes(b'prerequisite-test')
env = os.environ.copy()
system = os.environ['SystemRoot']
env['PATH'] = os.pathsep.join([str(Path(system)/'System32'), system])
for key in ('USERPROFILE', 'APPDATA', 'LOCALAPPDATA'):
    folder = fixture/key
    folder.mkdir()
    env[key] = str(folder)
for key in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QML_IMPORT_PATH'):
    env.pop(key, None)
result = subprocess.run([str(package/'DashGoWorker.exe'), 'dashcam_stitch.py',
    '--source', str(source), '--output', str(fixture/'output'), '--stitch'],
    cwd=fixture, env=env, capture_output=True, text=True, timeout=20)
assert result.returncode == 1, result
assert 'FFmpeg is not installed or not on PATH' in result.stderr, result.stderr
assert 'winget install --id Gyan.FFmpeg --exact' in result.stderr, result.stderr
assert not (fixture/'output').exists()
assert not any(p.name.lower() in ('ffmpeg.exe', 'ffprobe.exe') for p in package.rglob('*'))
print('PASS: packaged missing-FFmpeg diagnostic, install instruction, no output created, no bundled media tools')
print(f'Disposable fixture retained: {fixture}')
