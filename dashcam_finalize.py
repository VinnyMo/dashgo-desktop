"""Explicit assembly of a completed rendered capture into a new MP4."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import dashcam_process as subprocess
import threading
import uuid
from pathlib import Path

from dashcam_live import CREATE_NO_WINDOW, RESERVE_BYTES, media_tool
from dashcam_stitch import ffconcat_quote, calculate_target_encoding, target_budget


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
        if result.returncode or duration <= 0 or (not raw and abs(start) > 0.05):
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
    def __init__(self, session: Path, *, recover=False, raw_only=False, target_size="original", output_root=None):
        self.recover = recover
        self.raw_only = raw_only
        self.target_size = target_size
        self.output_root = Path(output_root) if output_root else None
        self.session = Path(session).resolve()
        self.state = "idle"
        self.reason = ""
        self.output = None
        self.directory = None
        self.process = None
        self._thread = None
        self._stop = threading.Event()

    @property
    def active(self):
        return self.state in {"checking", "assembling", "verifying"}

    def start(self):
        if self.state != "idle":
            raise RuntimeError("This finalization job has already been used.")
        self.state = "checking"
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def wait(self, timeout=20):
        if self._thread:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise TimeoutError("Finalization is still stopping.")

    def _run(self):
        try:
            parts, playlist = validate_capture(self.session, recover=self.recover, raw_only=self.raw_only)
            signature, durations = None, []
            for part in parts:
                if self._stop.is_set():
                    self.state = "cancelled"
                    return
                info = read_rendered_video(part, raw=True) if self.raw_only else read_rendered_video(part)
                if signature is not None and info["signature"] != signature:
                    raise ValueError("Video parameters differ between rendered segments; no output was assembled.")
                signature = info["signature"]
                durations.append(info["duration"])
            duration = sum(durations)
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
            command = [media_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-n",
                       "-f", "concat", "-safe", "0", "-i", str(manifest)]
            if playlist:
                command += ["-stream_loop", "-1", "-i", str(playlist), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"]
            else:
                command += ["-map", "0:v:0", "-an"]
            command += [*video_options, "-threads", "2", "-t", f"{duration:.9f}", "-movflags", "+faststart", str(partial)]
            if self._stop.is_set():
                self.state = "cancelled"
                return
            self.state = "assembling"
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
            while self.process.poll() is None:
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
                raise RuntimeError("Assembly failed. Sources and any partial output were retained.")
            self.state = "verifying"
            measured = read_rendered_video(partial)
            if abs(measured["duration"] - duration) > max(0.1, len(parts) * 0.05):
                raise RuntimeError("Assembled duration differs from its segments. Partial output retained for inspection.")
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
            self.state = "finished"
        except Exception as exc:
            self.state, self.reason = "failed", str(exc)
        finally:
            if self.process:
                if self.process.poll() is None:
                    self._stop_process()
                self.process.stdin.close()
            if self.directory:
                try:
                    (self.directory / "finalize.json").write_text(json.dumps({
                        "state": self.state, "reason": self.reason,
                        "output": self.output.name if self.output else None,
                        "video": "stream copy", "audio": "continuous session playlist, AAC 192k"
                    }, indent=2), encoding="utf-8")
                except OSError:
                    self.reason += " Finalization status could not be saved."

    def _stop_process(self):
        try:
            self.process.stdin.write(b"q\n")
            self.process.stdin.flush()
            self.process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
