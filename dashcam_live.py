"""Explicit, opt-in stream inspection and recoverable PC recording.

No guessed camera endpoints or settings writes. User-started captures can opt
into bounded client reconnection while preserving previous segments.
"""
from __future__ import annotations

import datetime as dt
import json
import queue
from collections import deque
import os
import shutil
import dashcam_process as subprocess
import tempfile
import threading
import time
import uuid
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlsplit

from dashcam_downloader import get_json
from dashcam_stitch import find_ffmpeg

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
RESERVE_BYTES = 512 * 1024 * 1024


def media_tool(name: str) -> str:
    ffmpeg = Path(find_ffmpeg(None))
    tool = ffmpeg.with_name(name + (".exe" if os.name == "nt" else ""))
    if not tool.is_file():
        raise RuntimeError(f"{name} is missing beside FFmpeg. Install a complete FFmpeg build.")
    return str(tool)


def validate_stream(url: str) -> str:
    url = url.strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https", "rtsp"} or not parsed.hostname:
        raise ValueError("Enter a verified HTTP, HTTPS or RTSP live stream URL.")
    if parsed.username or parsed.password or any(c.isspace() for c in url):
        raise ValueError("Credentials and whitespace in stream URLs are not supported.")
    # The documented /app routes are commands or metadata, never verified media.
    if parsed.path.lower().startswith("/app/"):
        raise ValueError("Camera API commands are not live stream URLs.")
    return url


def input_options(url: str) -> list[str]:
    is_rtsp = urlsplit(url).scheme == "rtsp"
    # RTSP is a demuxer with its own socket timeout option. FFmpeg rejects
    # the generic protocol rw_timeout option after opening an RTSP input.
    options = ["-timeout" if is_rtsp else "-rw_timeout", "10000000", "-analyzeduration", "1000000", "-probesize", "500000"]
    if is_rtsp:
        options += ["-rtsp_transport", "tcp"]
    return options


def read_capabilities(base: str, *, check=lambda: None) -> dict:
    parsed = urlsplit(base.strip())
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use the camera HTTP address without credentials.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Use only the camera base address, without an API path.")
    base = base.rstrip("/")
    check()
    device = get_json(base + "/app/getdeviceattr", timeout=3)
    check()
    if device.get("result") != 0 or not isinstance(device.get("info"), dict):
        raise RuntimeError("Device identification was not recognized.")
    info = device["info"]
    result = {"firmware": str(info.get("softver", "Unknown")),
            "cameras": info.get("camnum", "Unknown"),
            "live_stream": "Unverified", "camera_controls": "Unverified"}
    # These read-only endpoints were observed on VSQ10 firmware. Do not infer
    # settings-write support, or turn the separate 'port' field into an RTSP port.
    for endpoint, key in (("getmediainfo", "media"), ("getparamitems?param=all", "items"),
                          ("getparamvalue?param=all", "values")):
        check()
        try:
            response = get_json(base + "/app/" + endpoint, timeout=3)
            if response.get("result") == 0:
                result[key] = response.get("info")
        except (OSError, RuntimeError):
            pass
    check()
    return result


def enable_live_stream(base: str) -> dict:
    """Explicit app-connect notification verified on the identified VSQ10 firmware.

    This is not an SD-recording toggle. No exitrecorder semantics are assumed.
    """
    capabilities = read_capabilities(base)
    if capabilities["firmware"] != "NEXPOW-VSQ10-20250418":
        raise RuntimeError("Live activation is not verified for this firmware.")
    response = get_json(base.rstrip("/") + "/app/enterrecorder", timeout=3)
    if response.get("result") != 0:
        raise RuntimeError("Camera did not enable live streaming.")
    return capabilities


def summarize_probe(data: dict) -> dict:
    streams = []
    packets = data.get("packets", [])
    for stream in data.get("streams", []):
        if stream.get("codec_type") not in {"video", "audio"}:
            continue
        selected = [p for p in packets if p.get("stream_index") == stream.get("index")]
        times = [float(p["pts_time"]) for p in selected if "pts_time" in p]
        span = max(times) - min(times) if len(times) > 1 else 0
        bitrate = round(sum(int(p.get("size", 0)) for p in selected) * 8 / span) if span else None
        rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
        try:
            fps = float(Fraction(rate)) if rate else None
        except (ValueError, ZeroDivisionError):
            fps = None
        streams.append({"type": stream.get("codec_type"), "codec": stream.get("codec_name", "unknown"),
                        "width": stream.get("width"), "height": stream.get("height"),
                        "fps": fps or None, "sample_bitrate_bps": bitrate,
                        "sample_seconds": round(span, 3), "channels": stream.get("channels"),
                        "sample_rate": stream.get("sample_rate")})
    if not any(s["type"] == "video" for s in streams):
        raise RuntimeError("No video stream was detected.")
    return {"streams": streams, "measured_at": dt.datetime.now(dt.timezone.utc).isoformat()}


class ProbeError(RuntimeError):
    """Actionable probe diagnostics without raw URLs, paths or device metadata."""


def probe_failure(stage, result):
    stderr = getattr(result, "stderr", b"") or b""
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    message = stderr.lower()
    if "option" in message and ("not found" in message or "unrecognized" in message):
        reason = "FFmpeg rejected a stream option. Update the desktop source and check the FFmpeg version."
    elif "no space left" in message:
        reason = "The temporary sample could not be saved: disk is full. Free space on the Windows temporary drive."
    elif "permission denied" in message or "access is denied" in message:
        reason = "Access was denied. Check camera access and that the Windows temporary folder is writable."
    elif "connection refused" in message:
        reason = "The live server refused the connection. Check camera Wi-Fi and retry Connect camera."
    elif "timed out" in message or "timeout" in message:
        reason = "The camera stopped responding. Check camera Wi-Fi, close other live viewers, and retry."
    elif "401 unauthorized" in message or "403 forbidden" in message:
        reason = "The camera refused access to its live stream."
    elif "404 not found" in message:
        reason = "The advertised live stream was not found. Reconnect the camera and retry."
    elif "sampling rate" in message or "invalid sample rate" in message:
        reason = "The camera advertised invalid audio metadata. The video-only sample also needs to succeed; microphone settings were unchanged."
    else:
        reason = "FFmpeg could not read the stream or write its temporary sample. Check camera Wi-Fi, other live viewers and temporary-disk space, then retry."
    return ProbeError(f"{stage} failed (exit {result.returncode}). {reason}")


def run_probe(runner, stage, command, **kwargs):
    try:
        return runner(command, **kwargs)
    except subprocess.TimeoutExpired:
        raise ProbeError(f"{stage} timed out. Check camera Wi-Fi, close other live viewers, and retry Connect camera.") from None


def inspect_stream(url: str, *, runner=None) -> dict:
    runner = runner or subprocess.run
    url = validate_stream(url)
    command = [media_tool("ffprobe"), "-v", "error", *input_options(url),
               "-read_intervals", "%+5", "-show_streams", "-show_packets",
               "-show_entries", "stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,channels,sample_rate:packet=stream_index,pts_time,size",
               "-of", "json", url]
    result = run_probe(runner, "Stream measurement", command, capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW)
    if not result.returncode:
        return summarize_probe(json.loads(result.stdout))
    if urlsplit(url).scheme != "rtsp":
        raise probe_failure("Stream measurement", result)
    # VSQ10 advertises invalid AAC configuration with its microphone off. FFprobe
    # refuses that input; FFmpeg can copy its video while retaining both RTSP
    # SETUP tracks. Filtering the RTSP negotiation to video alone stalls this unit.
    with tempfile.TemporaryDirectory(prefix="dashgo-probe-") as temp:
        sample = Path(temp) / "sample.mkv"
        copied = run_probe(runner, "Video-only measurement", [media_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-n",
                                 *input_options(url), "-fflags", "+genpts", "-i", url, "-t", "5",
                                 "-map", "0:v:0", "-an", "-c:v", "copy", str(sample)],
                                capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW)
        if copied.returncode:
            raise probe_failure("Video-only measurement", copied)
        local = run_probe(runner, "Saved sample inspection", [media_tool("ffprobe"), "-v", "error", "-show_streams", "-show_packets",
                                "-show_entries", "stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate:packet=stream_index,pts_time,size",
                                "-of", "json", str(sample)], capture_output=True, timeout=10,
                               creationflags=CREATE_NO_WINDOW)
        if local.returncode:
            raise probe_failure("Saved sample inspection", local)
        report = summarize_probe(json.loads(local.stdout))
        report["audio_note"] = "Audio unavailable: full-stream probe failed; video-only capture verified. Microphone unchanged."
        return report


def describe_probe(report: dict) -> str:
    lines = []
    for stream in report["streams"]:
        rate = stream["sample_bitrate_bps"]
        bitrate = f"{rate / 1000:.0f} kbit/s sampled" if rate else "bitrate unavailable"
        if stream["type"] == "video":
            fps = f"{stream['fps']:.2f} fps reported" if stream["fps"] else "frame rate unavailable"
            lines.append(f"Video: {stream['width']} × {stream['height']} · {stream['codec']} · {fps} · {bitrate}")
        else:
            lines.append(f"Audio: {stream['codec']} · {stream['channels']} channel(s) · {stream['sample_rate']} Hz · {bitrate}")
    if not any(s["type"] == "audio" for s in report["streams"]):
        lines.append(report.get("audio_note", "Audio: not detected in this sample"))
    return "\n".join(lines)


class CaptureSession:
    """One owned FFmpeg process; a new exclusive directory for every recording.

    Five minute Matroska segments limit interruption damage. Segment boundaries
    follow source keyframes. Raw stream bytes are copied without re-encoding.
    """
    def __init__(self, url: str, root: Path, report: dict, *, segment_seconds: int = 300, quality: int = 720, preview: bool = False, reconnect_attempts: int = 0):
        self.url = validate_stream(url)
        if not 1 <= segment_seconds <= 3600:
            raise ValueError("Segment duration must be 1–3600 seconds.")
        self.root, self.report, self.segment_seconds = Path(root), report, segment_seconds
        if quality not in (360, 480, 720):
            raise ValueError("Capture height must be 360, 480 or 720 pixels.")
        self.quality = quality
        self.with_preview = preview
        self.frames = queue.Queue(maxsize=1)
        self.reconnect_attempts = reconnect_attempts
        self.reconnects = 0
        self.diagnostics = deque(maxlen=20)
        self.process = None
        self.directory = None
        self.state = "idle"
        self.reason = ""
        self.started = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None

    def start(self) -> None:
        with self._lock:
            if self.state != "idle":
                raise RuntimeError("This recording session has already been used.")
            ffmpeg = media_tool("ffmpeg")
            self.root.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.root).free < RESERVE_BYTES:
                raise RuntimeError("Less than 512 MiB free. Choose another recording folder.")
            name = dt.datetime.now().strftime("Capture_%Y-%m-%d_%H-%M-%S_") + uuid.uuid4().hex[:12]
            self.directory = self.root / name
            self.directory.mkdir(exist_ok=False)
            self.state = "starting"
            self.started = time.monotonic()
            self._manifest()
            # PC capture is deliberately video-only. Camera microphone stays as
            # configured; a future render stage may add the user's music.
            audio = ["-an"]
            video = next((item for item in self.report.get("streams", []) if item.get("type") == "video"), {})
            height = video.get("height") or 720
            encoding = ["-c:v", "copy"] if height <= self.quality else [
                "-vf", f"scale=-2:{self.quality}", "-c:v", "libx264", "-threads", "2",
                "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-n", *input_options(self.url),
                       "-fflags", "+genpts", "-i", self.url, "-map", "0:v:0", *audio, *encoding,
                       "-f", "segment", "-segment_time", str(self.segment_seconds),
                       "-segment_format", "matroska", "-reset_timestamps", "1",
                       "-flush_packets", "1", str(self.directory / "part_%06d.mkv")]
            if self.with_preview:
                command += ["-map", "0:v:0", "-an", "-vf", "fps=8,scale=1280:720:force_original_aspect_ratio=decrease:flags=lanczos,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                            "-threads", "2", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
            self.command = command
            try:
                self._spawn()
                self.state = "recording"
                self._manifest()
                self._thread = threading.Thread(target=self._monitor, daemon=True)
                self._thread.start()
            except Exception:
                if self.process is not None:
                    self._finish_process()
                    self.process.stdin.close()
                self.state, self.reason = "failed", "Could not start recording or save its status."
                try:
                    self._manifest()
                except OSError:
                    pass
                raise

    def _spawn(self):
        command = list(self.command)
        count = len(list(self.directory.glob("part_*.mkv")))
        if count:
            position = command.index(str(self.directory / "part_%06d.mkv"))
            command[position:position] = ["-segment_start_number", str(count)]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE if self.with_preview else subprocess.DEVNULL,
                                        stderr=subprocess.PIPE if self.with_preview else subprocess.DEVNULL,
                                        creationflags=CREATE_NO_WINDOW)
        process = self.process
        if self.with_preview:
            def read_frames():
                try:
                    while True:
                        data = bytearray()
                        while len(data) < 1280 * 720 * 3:
                            chunk = process.stdout.read(1280 * 720 * 3 - len(data))
                            if not chunk:
                                return
                            data.extend(chunk)
                        if self.frames.empty():
                            self.frames.put(b"P6\n1280 720\n255\n" + data)
                finally:
                    process.stdout.close()
            def read_errors():
                try:
                    for line in iter(process.stderr.readline, b""):
                        # Store only a fixed-vocabulary classification, never raw URLs.
                        detail = str(probe_failure("Capture", type("Result", (), {"returncode": "pending", "stderr": line})()))
                        if not self.diagnostics or detail != self.diagnostics[-1]:
                            self.diagnostics.append(detail)
                finally:
                    process.stderr.close()
            threading.Thread(target=read_frames, daemon=True).start()
            threading.Thread(target=read_errors, daemon=True).start()

    def _manifest(self) -> None:
        data = {"version": 1, "state": self.state, "reason": self.reason,
                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "segment_seconds": self.segment_seconds, "stream": self.report,
                "capture_height_limit": self.quality, "reconnects": self.reconnects,
                "diagnostics": list(self.diagnostics)}
        temp = self.directory / "session.json.tmp"
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp.replace(self.directory / "session.json")

    def _monitor(self) -> None:
        previous_bytes, last_growth = 0, time.monotonic()
        try:
            while True:
                while self.process.poll() is None:
                    if self._stop.wait(0.5):
                        break
                    size = self.byte_count
                    if size > previous_bytes:
                        previous_bytes, last_growth = size, time.monotonic()
                    if shutil.disk_usage(self.directory).free < RESERVE_BYTES:
                        self.reason = "Stopped: less than 512 MiB free. Existing segments retained."
                        self._stop.set()
                    elif time.monotonic() - last_growth > 30:
                        self.reason = "Stream stalled for 30 seconds."
                        self._finish_process()
                        break
                if self.process.poll() is None:
                    self._finish_process()
                code = self.process.wait()
                if self._stop.is_set():
                    self.state = "stopped" if not self.reason else "interrupted"
                    break
                if self.reconnects < self.reconnect_attempts:
                    self.state = "reconnecting"
                    self.reconnects += 1
                    self.reason = f"Stream interrupted (exit {code}); reconnect {self.reconnects}/{self.reconnect_attempts}. A gap may be present."
                    self._manifest()
                    if self._stop.wait(min(2 ** self.reconnects, 8)):
                        self.state, self.reason = "stopped", ""
                        break
                    self.process.stdin.close()
                    self._spawn()
                    self.state, self.reason = "recording", ""
                    last_growth = time.monotonic()
                    continue
                self.state = "interrupted"
                self.reason = f"Stream ended (FFmpeg exit {code}). Segments retained; reconnect before starting a new capture."
                if self.diagnostics:
                    self.reason += " " + self.diagnostics[-1]
                break
        except Exception:
            self.reason = "Recording interrupted by an I/O error. Existing segments retained."
            self.state = "interrupted"
            self._finish_process()
        finally:
            if self.process.stdin:
                self.process.stdin.close()
            try:
                self._manifest()
            except OSError:
                self.reason += " Session status could not be saved."

    def _finish_process(self) -> None:
        try:
            self.process.stdin.write(b"q\n")
            self.process.stdin.flush()
            self.process.wait(timeout=5)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.reason = self.reason or "Forced stop after timeout; last segment may be incomplete."

    def stop(self) -> None:
        self._stop.set()

    def wait(self, timeout: float = 12) -> None:
        if self._thread:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise TimeoutError("Recording is still stopping.")

    @property
    def active(self) -> bool:
        return self.state in {"starting", "recording", "reconnecting"}

    @property
    def byte_count(self) -> int:
        try:
            return sum(p.stat().st_size for p in self.directory.glob("part_*.mkv")) if self.directory else 0
        except OSError:
            return 0
