"""Opt-in: generated footage on localhost only. Never opens the physical camera."""
import http.server
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from dashcam_live import CaptureSession, inspect_stream, media_tool


@unittest.skipUnless(os.environ.get("DASHGO_MEDIA_TESTS") == "1", "Set DASHGO_MEDIA_TESTS=1 for FFmpeg integration")
class MediaIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        fixture = cls.root / "synthetic.ts"
        subprocess.run([media_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=12",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "30",
                        "-c:v", "libx264", "-preset", "ultrafast", "-g", "12", "-c:a", "aac",
                        "-f", "mpegts", str(fixture)], check=True, timeout=30)
        cls.data = fixture.read_bytes()
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "video/MP2T")
                self.end_headers()
                try:
                    for index in range(0, len(cls.data), 16384):
                        self.wfile.write(cls.data[index:index+16384])
                        self.wfile.flush()
                        time.sleep(0.04)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/synthetic.ts"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def test_probe_capture_stop_and_decode_segments(self):
        report = inspect_stream(self.url)
        video = next(s for s in report["streams"] if s["type"] == "video")
        self.assertEqual((video["width"], video["height"]), (320, 180))
        self.assertEqual(video["codec"], "h264")
        self.assertEqual(video["fps"], 12)
        self.assertGreater(video["sample_bitrate_bps"], 0)
        self.assertTrue(any(s["type"] == "audio" and s["codec"] == "aac" for s in report["streams"]))
        session = CaptureSession(self.url, self.root / "captures", report, segment_seconds=1)
        session.start()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and len(list(session.directory.glob("*.mkv"))) < 3:
            time.sleep(0.1)
        session.stop()
        session.wait()
        parts = sorted(session.directory.glob("*.mkv"))
        self.assertGreaterEqual(len(parts), 2)
        for part in parts:
            result = subprocess.run([media_tool("ffmpeg"), "-v", "error", "-i", str(part), "-f", "null", "-"], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((session.directory / "session.json").read_text())["state"], "stopped")

    def test_embedded_preview_receives_synthetic_frames_and_stops(self):
        import tkinter as tk
        from types import SimpleNamespace
        from dashcam_camera_ui import CameraPanel
        root = tk.Tk()
        root.geometry("1080x940")
        try:
            app = SimpleNamespace(camera=tk.StringVar(root), process=None, task_running=False)
            panel = CameraPanel(root, app)
            panel.pack(fill="both", expand=True)
            panel.stream.set(self.url)
            panel.report_url = self.url
            panel.report = {"streams": [{"type": "video"}]}
            panel._preview()
            deadline = time.monotonic() + 8
            while panel.image is None and time.monotonic() < deadline:
                root.update()
                time.sleep(0.05)
            self.assertIsNotNone(panel.image, "No frame reached the embedded preview")
            self.assertGreater(panel.image.width(), 0)
            self.assertEqual(panel.image.width() * 9, panel.image.height() * 16)
            process = panel.preview
            panel._stop_preview()
            self.assertIsNotNone(process.poll())
        finally:
            if 'panel' in locals():
                panel.shutdown()
            root.destroy()

    def test_preview_and_lower_quality_capture_share_one_process(self):
        fixture = self.root / "synthetic720.ts"
        subprocess.run([media_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=12",
                        "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-g", "12", "-f", "mpegts", str(fixture)], check=True, timeout=30)
        original = self.__class__.data
        self.__class__.data = fixture.read_bytes()
        session = CaptureSession(self.url, self.root / "preview-capture", {"streams": [{"type": "video", "height": 720}]},
                                 segment_seconds=1, quality=360, preview=True)
        try:
            session.start()
            frame = session.frames.get(timeout=10)
            self.assertTrue(frame.startswith(b"P6\n1280 720\n255\n"))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and len(list(session.directory.glob("*.mkv"))) < 2:
                time.sleep(0.1)
            session.stop()
            session.wait()
            self.assertIsNotNone(session.process.poll())
            part = sorted(session.directory.glob("*.mkv"))[0]
            result = subprocess.run([media_tool("ffprobe"), "-v", "error", "-show_entries", "stream=width,height", "-of", "json", str(part)], capture_output=True, timeout=10)
            stream = json.loads(result.stdout)["streams"][0]
            self.assertEqual(stream['height'], 360)
            from dashcam_finalize import CaptureFinalizer
            import hashlib
            parts = sorted(session.directory.glob('*.mkv'))
            hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in parts]
            finalizer = CaptureFinalizer(session.directory, raw_only=True, target_size='1gbh')
            finalizer.start()
            finalizer.wait(30)
            self.assertEqual(finalizer.state, 'finished', finalizer.reason)
            decoded = subprocess.run([media_tool('ffmpeg'), '-v', 'error', '-i', str(finalizer.output), '-f', 'null', '-'], capture_output=True, timeout=15)
            self.assertEqual(decoded.returncode, 0, decoded.stderr)
            self.assertEqual(decoded.stderr, b'')
            self.assertEqual(hashes, [hashlib.sha256(p.read_bytes()).hexdigest() for p in parts])
        finally:
            session.stop()
            session.wait()
            self.__class__.data = original

    def test_disconnect_reconnect_retains_prior_segment_and_stops(self):
        import hashlib
        session = CaptureSession(self.url, self.root / "reconnect", {"streams": []}, segment_seconds=1, reconnect_attempts=1)
        session.start()
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and session.reconnects == 0:
                time.sleep(.05)
            self.assertEqual(session.reconnects, 1)
            prior = sorted(session.directory.glob("part_*.mkv"))[0]
            digest = hashlib.sha256(prior.read_bytes()).hexdigest()
            first_count = len(list(session.directory.glob("part_*.mkv")))
            while time.monotonic() < deadline and len(list(session.directory.glob("part_*.mkv"))) <= first_count:
                time.sleep(.05)
            self.assertGreater(len(list(session.directory.glob("part_*.mkv"))), first_count)
            session.stop()
            session.wait()
            self.assertEqual(hashlib.sha256(prior.read_bytes()).hexdigest(), digest)
            self.assertIsNotNone(session.process.poll())
        finally:
            session.stop()
            session.wait()
