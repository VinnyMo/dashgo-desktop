"""Four-second synthetic packaged render; no camera or existing media."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile

package = Path(sys.argv[1]).resolve()
fixture = Path(tempfile.mkdtemp(prefix='dashgo-media-review-'))
env = os.environ.copy()
env['PATH'] = os.pathsep.join([str(Path(env['SystemRoot'])/'System32'), env['SystemRoot']])
for key in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QML_IMPORT_PATH'):
    env.pop(key, None)
for key in ('USERPROFILE', 'APPDATA', 'LOCALAPPDATA'):
    location = fixture/key
    location.mkdir()
    env[key] = str(location)
ffmpeg = package/'_internal/ffmpeg/bin/ffmpeg.exe'
ffprobe = ffmpeg.with_name('ffprobe.exe')
worker = package/'DashGoWorker.exe'
source = fixture/'transfers'
music = fixture/'music'
output = fixture/'output'
source.mkdir()
music.mkdir()

def run(args, **kwargs):
    result = subprocess.run([str(x) for x in args], cwd=fixture, env=env,
                            capture_output=True, text=True, timeout=90, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout

clip = source/'2026-01-01_12_00_00_f.ts'
run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=25',
     '-t', '4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-an', clip])
run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
     '-t', '6', music/'synthetic.wav'])
before = hashlib.file_digest(clip.open('rb'), 'sha256').hexdigest()
# No --ffmpeg argument: exercises packaged default discovery with no host fallback.
report = run([worker, '-u', '-B', 'dashcam_worker.py', worker, '-u', '-B',
              'dashcam_stitch.py', '--source', source, '--music-dir', music,
              '--output', output, '--stitch', '--video-encoder', 'libx264',
              '--end-card-seconds', '0.5', '--crossfade-seconds', '0.1'], input='GO\n')
videos = list(output.glob('*.mp4'))
assert len(videos) == 1, report
streams = json.loads(run([ffprobe, '-v', 'error', '-show_streams', '-of', 'json', videos[0]]))['streams']
assert {'h264', 'aac'} <= {stream['codec_name'] for stream in streams}
run([ffmpeg, '-v', 'error', '-xerror', '-i', videos[0], '-f', 'null', '-'])
assert before == hashlib.file_digest(clip.open('rb'), 'sha256').hexdigest()
print('PASS: bundled FFmpeg/ffprobe, gated worker, music/overlay H.264/AAC export, full short decode, source retained')
print('Windows-only PATH and isolated profile environment; not a clean-machine test.')
print(f'Disposable synthetic fixtures retained: {fixture}')
