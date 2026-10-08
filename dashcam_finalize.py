"""Explicit assembly of a completed rendered capture into a new MP4."""
from __future__ import annotations

import datetime as dt
import json
import math
import queue
import shutil
import dashcam_process as subprocess
import threading
import time
import uuid
from pathlib import Path

from dashcam_live import CREATE_NO_WINDOW, RESERVE_BYTES, media_tool
from dashcam_stitch import ffconcat_quote, calculate_target_encoding, target_budget
from dashcam_recycle import checked_path
from dashcam_cleanup import generated_inputs, recycle_inputs


def read_rendered_video(path: Path, *, raw=False) -> dict:
    result = subprocess.run([media_tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
                             "-show_entries", "stream=codec_name,profile,level,width,height,pix_fmt,time_base,r_frame_rate,extradata,duration,start_time:format=duration",
                             "-show_data", "-of", "json", str(path)], capture_output=True, timeout=15,
                            creationflags=CREATE_NO_WINDOW)
    try:
        data = json.loads(result.stdout)
        stream = data["streams"][0]
        stream_duration = stream.pop("duration", None)
        duration = float(stream_duration if stream_duration is not None else data.get("format", {}).get("duration", 0))
        start = float(stream.pop("start_time", 0))
        # Matroska's format duration includes the initial encoder timestamp
        # offset (e.g. 80 ms for H.264 B-frames). The concat demuxer rebases
        # each input to zero; use its actual playback length for placement.
        if raw and stream_duration is None:
            duration -= start
        if result.returncode or not math.isfinite(duration) or not math.isfinite(start) or duration <= 0 or (not raw and abs(start) > 0.05):
            raise ValueError
        return {"duration": duration, "signature": stream}
    except (KeyError, IndexError, TypeError, ValueError):
        raise RuntimeError(f"Rendered segment is not a supported complete video: {path.name}") from None


def validate_capture(session: Path, *, recover=False, raw_only=False) -> tuple[list[Path], Path]:
    session = Path(session)
    try:
        capture = json.loads((session / "session.json").read_text(encoding="utf-8"))
        render = {} if raw_only else json.loads((session / "Rendered" / "render.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("Choose a capture folder with completed capture and render records.") from None
    if capture.get("state") != "stopped" and not (recover and capture.get("state") == "interrupted"):
        raise ValueError("Finalize only a normally stopped capture. Interrupted sessions need recovery first.")
    if raw_only:
        raw = sorted(session.glob("part_*.mkv"))
        if not raw or [p.stem for p in raw] != [f"part_{index:06d}" for index in range(len(raw))]:
            raise ValueError("Raw capture segments are missing or incomplete.")
        return raw, None
    if render.get("state") != "finished":
        raise ValueError("Wait for all background rendering to finish before finalizing.")
    count = render.get("completed_segments")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError("There are no completed rendered segments.")
    raw = sorted(session.glob("part_*.mkv"))
    parts = sorted((session / "Rendered").glob("part_*.mp4"))
    expected = [f"part_{index:06d}" for index in range(count)]
    if [p.stem for p in raw] != expected or [p.stem for p in parts] != expected:
        raise ValueError("Segments are missing, duplicated or incomplete; finalization was not started.")
    playlist = session / "Rendered" / ".capture.shuffled_playlist.m4a"
    if not playlist.is_file() or not playlist.stat().st_size:
        raise ValueError("The session's saved music playlist is missing.")
    return parts, playlist


class CaptureFinalizer:
    def __init__(self, session: Path, *, recover=False, raw_only=False, target_size="original", output_root=None, cleanup=False):
        self.recover = recover
        self.raw_only = raw_only
        self.target_size = target_size
        self.output_root = Path(output_root) if output_root else None
        self.session = Path(session).absolute()
        self.cleanup = cleanup
        self.cleanup_result = None
        self.message = 'Ready to export'
        self.percent = 0.0
        self.logs = queue.Queue()
        self.started = None
        self._last_progress = -1
        self.state = "idle"
        self.reason = ""
        self.output = None
        self.directory = None
        self.process = None
        self._thread = None
        self._stop = threading.Event()

    @property
    def active(self):
        return self.state in {"checking", "assembling", "verifying", "cleaning"} or bool(self._thread and self._thread.is_alive())

    def _report(self, message, *, log=True):
        self.message = message
        if log:
            self.logs.put(message)

    def _progress(self, path, duration):
        try:
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 8192))
                lines = stream.read().decode('utf-8', 'replace').splitlines()
            values = dict(line.split('=', 1) for line in lines if '=' in line)
            seconds = max(0, float(values.get('out_time_us', 0)) / 1000000)
            self.percent = min(98, seconds / duration * 98)
            speed = values.get('speed', '').strip()
            elapsed = int(time.monotonic() - self.started)
            self._report(f'Exporting {self.percent:.0f}% | {elapsed // 60}:{elapsed % 60:02} elapsed' + (f' | {speed}' if speed else ''), log=False)
            milestone = int(self.percent // 10)
            if milestone > self._last_progress:
                self.logs.put(self.message)
                self._last_progress = milestone
        except (OSError, ValueError):
            pass

    def start(self):
        if self.state != "idle":
            raise RuntimeError("This finalization job has already been used.")
        self.state = "checking"
        self.started = time.monotonic()
        self._report('Checking capture segments before export.')
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._report('Cancelling export; completed final files and remaining sources are kept.')

    def wait(self, timeout=20):
        if self._thread:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise TimeoutError("Finalization is still stopping.")

    def _run(self):
        progress_stream = errors = None
        video_method, audio_method = 'stream copy', 'none'
        lock = None
        try:
            checked_path(self.session)
            try:
                lock = (self.session / '.export.lock').open('x')
            except FileExistsError:
                raise RuntimeError('This capture already has an export lock. Wait for its export, or see the README for recovering a leftover lock after a crash.') from None
            parts, playlist = validate_capture(self.session, recover=self.recover, raw_only=self.raw_only)
            files, guards = generated_inputs(self.session, parts, playlist)
            signature, durations = None, []
            for index, part in enumerate(parts):
                if self._stop.is_set():
                    self.state = "cancelled"
                    return
                self._report(f'Checking segment {index + 1} of {len(parts)}.')
                info = read_rendered_video(part, raw=True) if self.raw_only else read_rendered_video(part)
                if signature is not None and info["signature"] != signature:
                    raise ValueError("Video parameters differ between rendered segments; no output was assembled.")
                signature = info["signature"]
                durations.append(info["duration"])
            duration = sum(durations)
            self._report(f'Export contains {len(parts)} segments, {duration:.1f} seconds.')
            if self.output_root:
                # Check existing ancestors before creating our new export directory.
                ancestor = self.output_root
                while not ancestor.exists():
                    ancestor = ancestor.parent
                checked_path(ancestor)
                self.output_root.mkdir(parents=True, exist_ok=True)
                checked_path(self.output_root)
            # Reserve enough space for another full copy of the rendered set,
            # continuous 192k AAC, and safety headroom. No source is removed.
            required = sum(p.stat().st_size for p in parts) + int(duration * 24000) + RESERVE_BYTES
            if shutil.disk_usage(self.output_root or self.session).free < required:
                raise OSError("Not enough free space for a new assembled MP4 and safety reserve.")
            name = "Finalized_" + dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S_") + uuid.uuid4().hex[:12]
            self.directory = (self.output_root or self.session) / name
            self.directory.mkdir(exist_ok=False)
            manifest = self.directory / "segments.ffconcat"
            with manifest.open("x", encoding="utf-8") as output:
                output.write("ffconcat version 1.0\n")
                for part, seconds in zip(parts, durations):
                    output.write(f"file {ffconcat_quote(part)}\nduration {seconds:.9f}\n")
            partial = self.directory / "Capture.partial.mp4"
            video_options = ["-c:v", "copy"]
            existing_target = None
            if playlist:
                try:
                    existing_target = json.loads((self.session / "Rendered" / "render.json").read_text()).get("target_size")
                except (OSError, ValueError):
                    pass
            if self.target_size != "original" and self.target_size != existing_target:
                limit = target_budget(self.target_size, duration)
                height, _, codec_options = calculate_target_encoding(duration, "libx264", int(limit))
                video_options = ["-c:v", "libx264", "-threads", "2", *codec_options]
                if height and height < signature["height"]:
                    video_options += ["-vf", f"scale=-2:{height}"]
                video_method = 'H.264 transcode'
            command = [media_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-n",
                       "-f", "concat", "-safe", "0", "-i", str(manifest)]
            if playlist:
                audio_method = 'continuous session playlist, AAC 192k'
                command += ["-stream_loop", "-1", "-i", str(playlist), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"]
            else:
                command += ["-map", "0:v:0", "-an"]
            command += [*video_options, "-threads", "2", "-t", f"{duration:.9f}", "-movflags", "+faststart", '-progress', 'pipe:1', '-nostats', str(partial)]
            if self._stop.is_set():
                self.state = "cancelled"
                return
            self.state = "assembling"
            self._report(f'Export started: {video_method}; audio: {audio_method}.')
            progress_path = self.directory / 'progress.log'
            progress_stream = progress_path.open('xb')
            errors = (self.directory / 'ffmpeg.log').open('xb')
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=progress_stream,
                                            stderr=errors, creationflags=CREATE_NO_WINDOW)
            while self.process.poll() is None:
                self._progress(progress_path, duration)
                if self._stop.wait(0.25):
                    self._stop_process()
                    break
                if shutil.disk_usage(self.directory).free < RESERVE_BYTES:
                    self.reason = "Finalization stopped because disk space is low. All source segments remain."
                    self._stop.set()
            code = self.process.wait()
            if self._stop.is_set():
                self.state = "cancelled"
                return
            if code or not partial.is_file():
                errors.flush()
                with (self.directory / 'ffmpeg.log').open('rb') as stream:
                    stream.seek(max(0, stream.seek(0, 2) - 4096))
                    detail = stream.read().decode('utf-8', 'replace').strip()
                raise RuntimeError(f"Assembly failed (exit {code}). Sources and partial output retained. {detail}")
            self.state = "verifying"
            self.percent = 98
            self._report('Verifying duration, streams and playback samples.')
            measured = read_rendered_video(partial)
            if abs(measured["duration"] - duration) > max(0.1, len(parts) * 0.05):
                raise RuntimeError("Assembled duration differs from its segments. Partial output retained for inspection.")
            verify_playback(partial, duration, bool(playlist), self._stop)
            if self._stop.is_set():
                self.state = "cancelled"
                return
            final = self.directory / "Capture.mp4"
            # Exclusive directory plus a Windows non-replacing rename protects
            # previous exports; no replace()/overwrite mode is used.
            if final.exists():
                raise FileExistsError("Refusing to overwrite an existing finalized video.")
            partial.rename(final)
            self.output = final
            self.percent = 100
            self._report(f'Final MP4 verified: {final}')
            if self.cleanup:
                self.state = 'cleaning'
                self._report('Final MP4 ready. Recycling generated source and rendered media.')
                def audit(result):
                    temporary = self.directory / 'cleanup.json.tmp'
                    temporary.write_text(json.dumps(result, indent=2), encoding='utf-8')
                    temporary.replace(self.directory / 'cleanup.json')
                self.cleanup_result = recycle_inputs(self.session, files, guards, final,
                    cancelled=self._stop.is_set, audit=audit)
                if self.cleanup_result['state'] != 'complete':
                    self.reason = 'Final MP4 ready; cleanup incomplete: ' + self.cleanup_result['reason']
                else:
                    self._report('Generated source and rendered media moved to the Recycle Bin.')
            self.state = "finished"
        except Exception as exc:
            if self.output:
                self.state, self.reason = 'finished', 'Final MP4 ready; cleanup incomplete: ' + str(exc)
            else:
                self.state, self.reason = "failed", str(exc)
        finally:
            if self.process:
                if self.process.poll() is None:
                    self._stop_process()
                self.process.stdin.close()
            for stream in (progress_stream, errors, lock):
                if stream:
                    stream.close()
            if lock:
                try:
                    (self.session / '.export.lock').unlink(missing_ok=True)
                except OSError:
                    self.reason += ' Export lock could not be removed; see the README before retrying.'
            if self.directory:
                try:
                    (self.directory / "finalize.json").write_text(json.dumps({
                        "state": self.state, "reason": self.reason,
                        "output": self.output.name if self.output else None,
                        "video": video_method, "audio": audio_method,
                        'cleanup': self.cleanup_result
                    }, indent=2), encoding="utf-8")
                except OSError:
                    self.reason += " Finalization status could not be saved."
            self._report(self.reason or (f'Final MP4 ready: {self.output}' if self.output else 'Export cancelled. Sources retained.'))

    def _stop_process(self):
        try:
            self.process.stdin.write(b"q\n")
            self.process.stdin.flush()
            self.process.wait(timeout=5)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()


def verify_playback(path, duration, audio_expected, cancelled):
    if cancelled.is_set():
        return
    if not path.stat().st_size:
        raise RuntimeError('Final video is empty. Sources retained.')
    probe = subprocess.run([media_tool('ffprobe'), '-v', 'error', '-show_streams', '-of', 'json', str(path)],
                           capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW)
    streams = json.loads(probe.stdout).get('streams', [])
    video = [s for s in streams if s.get('codec_type') == 'video' and s.get('width', 0) > 0 and s.get('height', 0) > 0]
    audio = [s for s in streams if s.get('codec_type') == 'audio' and int(s.get('sample_rate', 0)) > 0]
    if probe.returncode or len(video) != 1 or bool(audio) != audio_expected:
        raise RuntimeError('Final stream validation failed. Sources retained.')
    # Bounded samples catch unreadable output without decoding hours of video.
    for offset in sorted({0, max(0, duration / 2 - .5), max(0, duration - 1)}):
        if cancelled.is_set():
            return
        result = subprocess.run([media_tool('ffmpeg'), '-v', 'error', '-xerror', '-ss', f'{offset:.6f}',
            '-i', str(path), '-t', '1', '-map', '0:v:0', '-map', '0:a?', '-progress', 'pipe:1', '-f', 'null', '-'],
            capture_output=True, timeout=30, creationflags=CREATE_NO_WINDOW)
        values = dict(line.split('=', 1) for line in result.stdout.decode('utf-8', 'replace').splitlines() if '=' in line)
        if result.returncode or int(values.get('frame', 0)) < 1:
            raise RuntimeError('Final playback sample failed. Sources retained.')
