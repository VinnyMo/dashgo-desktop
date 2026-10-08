"""Optional background rendering of closed PC-capture segments.

Raw capture owns its own process and files. Render errors never stop it.
"""
from __future__ import annotations

import json
import shutil
import dashcam_process as subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from dashcam_live import CREATE_NO_WINDOW, RESERVE_BYTES, media_tool
from dashcam_stitch import build_music_playlist, presentation_filter, probe_dimensions, probe_duration, calculate_target_encoding, target_budget


class BackgroundRenderer:
    def __init__(self, capture, music_dir: Path, channel_title: str, route_info: str = "", crossfade: float = 3, *, target_size="original"):
        self.target_size = target_size
        self.capture = capture
        self.music_dir = Path(music_dir)
        self.channel_title = channel_title
        self.route_info = route_info
        self.crossfade = crossfade
        self.state = "idle"
        self.reason = ""
        self.completed = 0
        self.timeline = 0.0
        self.directory = capture.directory / "Rendered"
        self._stop = threading.Event()
        self._thread = None
        self.process = None

    @property
    def active(self):
        return self.state in {"preparing", "rendering", "waiting"} or bool(self._thread and self._thread.is_alive())

    def start(self):
        if self.state != "idle":
            raise RuntimeError("Renderer already started.")
        self.directory.mkdir(exist_ok=False)
        self.state = "preparing"
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def wait(self, timeout=12):
        if self._thread:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise TimeoutError("Background rendering is still stopping.")

    def _status(self, order=None):
        data = {"state": self.state, "reason": self.reason, "completed_segments": self.completed,
                "rendered_seconds": self.timeline, "encoding_threads": 2, "target_size": self.target_size,
                "playlist_order": order or []}
        tmp = self.directory / "render.json.tmp"
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.directory / "render.json")

    def _execute(self, command):
        if self._stop.is_set():
            raise RuntimeError("Rendering cancelled.")
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        try:
            while self.process.poll() is None:
                if self._stop.wait(0.5):
                    try:
                        self.process.stdin.write(b"q\n")
                        self.process.stdin.flush()
                    except OSError:
                        pass
                    break
                if shutil.disk_usage(self.directory).free < RESERVE_BYTES:
                    self.reason = "Rendering stopped: disk space is low. Raw files retained."
                    self._stop.set()
            try:
                code = self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                code = self.process.wait()
            return SimpleNamespace(returncode=code)
        finally:
            self.process.stdin.close()
            if self.process.poll() is not None:
                self.process = None

    def _run(self):
        order = []
        try:
            ffmpeg = media_tool("ffmpeg")
            # The existing playlist builder makes one shuffle. That exact order
            # and its crossfades are reused for the whole capture session.
            playlist, tracks, fade, length = build_music_playlist(
                ffmpeg, self.music_dir, self.crossfade, self.directory, "capture", runner=self._execute)
            order = [f"{track.artist} - {track.title}" for track in tracks]
            labels = []
            for index, track in enumerate(tracks):
                path = self.directory / f"track-{index}.txt"
                path.write_text(f"{track.title} · {track.artist}", encoding="utf-8")
                labels.append(path)
            channel = self.directory / "channel.txt"
            channel.write_text(self.channel_title, encoding="utf-8")
            route = self.directory / "route.txt" if self.route_info else None
            if route:
                route.write_text(self.route_info, encoding="utf-8")
            while not self._stop.is_set():
                parts = sorted(self.capture.directory.glob("part_*.mkv"))
                # FFmpeg may still be writing the newest file. Never render it
                # until capture closes, or a following segment exists.
                ready = parts[:-1] if self.capture.active else parts
                if self.completed >= len(ready):
                    if not self.capture.active:
                        self.state = "finished"
                        break
                    self.state = "waiting"
                    self._status(order)
                    self._stop.wait(1)
                    continue
                source = ready[self.completed]
                duration = probe_duration(ffmpeg, source)
                if duration is None:
                    raise RuntimeError("A closed segment could not be read. Raw files were retained.")
                if shutil.disk_usage(self.directory).free < RESERVE_BYTES:
                    raise RuntimeError("Rendering stopped: less than 512 MiB free. Raw capture uses its own space checks.")
                final = not self.capture.active and self.completed == len(parts) - 1
                graph = presentation_filter(tracks, fade, length, duration, labels, route, channel,
                                            min(20, duration), source_dimensions=probe_dimensions(ffmpeg, source),
                                            timeline_offset=self.timeline, final_segment=final)
                output = self.directory / (source.stem + ".mp4")
                partial = self.directory / (source.stem + ".partial.mp4")
                if output.exists() or partial.exists():
                    raise RuntimeError("A render output already exists; refusing to overwrite it.")
                codec_options = ["-preset", "fast", "-crf", "19"]
                audio_kbps = 192
                if self.target_size != "original":
                    _, audio_kbps, codec_options = calculate_target_encoding(duration, "libx264", target_budget(self.target_size, duration))
                command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-n", "-filter_complex_threads", "2",
                           "-i", str(source), "-stream_loop", "-1", "-ss", f"{self.timeline % length:.6f}",
                           "-i", str(playlist), "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
                           "-t", f"{duration:.6f}", "-c:v", "libx264", "-threads", "2", *codec_options,
                           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", f"{audio_kbps}k",
                           "-movflags", "+faststart", str(partial)]
                self.state = "rendering"
                self._status(order)
                code = self._execute(command).returncode
                if self._stop.is_set():
                    break
                if code or not partial.is_file() or partial.stat().st_size == 0:
                    raise RuntimeError("Rendering failed. Raw segments and partial output retained.")
                partial.rename(output)
                self.completed += 1
                self.timeline += duration
            if self._stop.is_set():
                self.state = "stopped"
        except Exception as exc:
            self.state = "stopped" if self._stop.is_set() else "failed"
            self.reason = self.reason or str(exc)
        finally:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            try:
                self._status(order)
            except OSError:
                self.reason += " Render status could not be written."
