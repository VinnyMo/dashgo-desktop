"""Generated-media 720p overlay benchmark; no camera or personal media."""
import json
import os
import subprocess
import tempfile
import time
import unittest
import hashlib
import array
import math
from types import SimpleNamespace
from pathlib import Path

from dashcam_live import media_tool
from dashcam_stitch import Track, presentation_filter, probe_dimensions
from dashcam_render import BackgroundRenderer
from dashcam_finalize import CaptureFinalizer


@unittest.skipUnless(os.environ.get("DASHGO_MEDIA_TESTS") == "1", "Set DASHGO_MEDIA_TESTS=1 for FFmpeg integration")
class OverlayIntegration(unittest.TestCase):
    def test_background_renderer_waits_for_closed_segments_and_preserves_raw(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            music = root / "Music"
            music.mkdir()
            subprocess.run([media_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                            "-t", "6", str(music / "Test - Synthetic.wav")], check=True, timeout=15)
            for index in range(2):
                subprocess.run([media_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
                                "-t", "4", "-c:v", "libx264", "-preset", "ultrafast", "-threads", "2",
                                str(root / f"part_{index:06d}.mkv")], check=True, timeout=15)
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob("*.mkv")}
            capture = SimpleNamespace(directory=root, active=True)
            renderer = BackgroundRenderer(capture, music, "Demo", "Test route", 1)
            renderer.start()
            try:
                deadline = time.monotonic() + 20
                while renderer.completed < 1 and renderer.active and time.monotonic() < deadline:
                    time.sleep(0.1)
                self.assertEqual(renderer.completed, 1, renderer.reason)
                self.assertFalse((renderer.directory / "part_000001.mp4").exists())
                capture.active = False
                renderer.wait(20)
                self.assertEqual(renderer.state, "finished", renderer.reason)
                self.assertEqual(renderer.completed, 2)
                self.assertAlmostEqual(renderer.timeline, 8, places=1)
                manifest = json.loads((renderer.directory / "render.json").read_text())
                self.assertEqual(len(manifest["playlist_order"]), 1)
                for output in renderer.directory.glob("part_*.mp4"):
                    self.assertEqual(probe_dimensions(media_tool("ffmpeg"), output), (640, 360))
                    result = subprocess.run([media_tool("ffmpeg"), "-v", "error", "-i", str(output), "-f", "null", "-"], capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob("*.mkv")})
                (root / "session.json").write_text(json.dumps({"state": "stopped"}))
                segment_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in renderer.directory.glob("part_*.mp4")}
                finalizer = CaptureFinalizer(root)
                finalizer.start()
                finalizer.wait(25)
                self.assertEqual(finalizer.state, "finished", finalizer.reason)
                self.assertEqual(probe_dimensions(media_tool("ffmpeg"), finalizer.output), (640, 360))
                probe = subprocess.run([media_tool("ffprobe"), "-v", "error", "-count_frames", "-show_entries",
                                        "stream=codec_type,codec_name,nb_read_frames,duration", "-of", "json", str(finalizer.output)],
                                       capture_output=True, timeout=15, check=True)
                streams = json.loads(probe.stdout)["streams"]
                video = next(s for s in streams if s["codec_type"] == "video")
                self.assertEqual(int(video["nb_read_frames"]), 200)
                self.assertAlmostEqual(float(video["duration"]), 8, places=1)
                self.assertTrue(any(s["codec_type"] == "audio" and s["codec_name"] == "aac" for s in streams))
                audio = subprocess.run([media_tool("ffmpeg"), "-v", "error", "-i", str(finalizer.output),
                                        "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1"],
                                       capture_output=True, timeout=15, check=True)
                samples = array.array("f", audio.stdout)
                # The source playlist is a steady tone at the 4-second segment
                # boundary. Check ten 20ms windows for an inserted AAC seam.
                for tick in range(195, 205):
                    window = samples[tick*960:(tick+1)*960]
                    self.assertGreater(math.sqrt(sum(x*x for x in window) / len(window)), 0.02)
                container = finalizer.output.read_bytes()
                self.assertLess(container.find(b"moov"), container.find(b"mdat"))
                decoded = subprocess.run([media_tool("ffmpeg"), "-v", "error", "-i", str(finalizer.output), "-f", "null", "-"], capture_output=True, timeout=15)
                self.assertEqual(decoded.returncode, 0, decoded.stderr)
                original_final = hashlib.sha256(finalizer.output.read_bytes()).hexdigest()
                another = CaptureFinalizer(root)
                another.start()
                another.wait(25)
                self.assertEqual(another.state, "finished", another.reason)
                self.assertNotEqual(finalizer.output, another.output)
                self.assertEqual(hashlib.sha256(finalizer.output.read_bytes()).hexdigest(), original_final)
                self.assertEqual(segment_hashes, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in renderer.directory.glob("part_*.mp4")})
                self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob("*.mkv")})
            finally:
                renderer.stop()
                renderer.wait(10)

    def test_720p_overlay_renders_without_upscaling(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            channel, route, label = [root / name for name in ("channel.txt", "route.txt", "track.txt")]
            channel.write_text("Demo Drive", encoding="utf-8")
            route.write_text("Test route", encoding="utf-8")
            label.write_text("Synthetic track", encoding="utf-8")
            output = root / "rendered.mp4"
            graph = presentation_filter([Track(root / "synthetic.wav", 8, "Synthetic", "Test")],
                                        1, 8, 8, [label], route, channel, 2,
                                        source_dimensions=(1280, 720))
            started = time.monotonic()
            result = subprocess.run([media_tool("ffmpeg"), "-v", "error", "-n", "-filter_complex_threads", "2",
                                     "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25",
                                     "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                                     "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
                                     "-t", "8", "-c:v", "libx264", "-threads", "2", "-preset", "fast",
                                     "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", str(output)],
                                    capture_output=True, timeout=60)
            elapsed = time.monotonic() - started
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(probe_dimensions(media_tool("ffmpeg"), output), (1280, 720))
            decoded = subprocess.run([media_tool("ffmpeg"), "-v", "error", "-i", str(output), "-f", "null", "-"],
                                     capture_output=True, timeout=15)
            self.assertEqual(decoded.returncode, 0, decoded.stderr)
            print(f"\nSynthetic 720p overlay: 8s rendered in {elapsed:.2f}s ({8/elapsed:.2f}x realtime), two encoding threads.")


if __name__ == "__main__":
    unittest.main()
