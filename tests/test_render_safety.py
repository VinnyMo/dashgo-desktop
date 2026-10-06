import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dashcam_camera_ui import CameraPanel
from dashcam_render import BackgroundRenderer
from dashcam_stitch import Track, presentation_filter


class Process:
    def __init__(self):
        self.stdin = io.BytesIO()
        self.code = None
    def poll(self):
        return self.code
    def wait(self, timeout=None):
        self.code = 0
        return 0
    def kill(self):
        self.code = -1


class RenderSafety(unittest.TestCase):
    def test_missing_music_does_not_stop_raw_capture(self):
        with tempfile.TemporaryDirectory() as temp, patch("dashcam_render.media_tool", return_value="ffmpeg"):
            root = Path(temp)
            capture = SimpleNamespace(directory=root, active=True)
            renderer = BackgroundRenderer(capture, root / "missing", "Title")
            renderer.start()
            renderer.wait()
            self.assertEqual(renderer.state, "failed")
            self.assertTrue(capture.active)
            self.assertIn("music", renderer.reason.lower())

    def test_invalid_music_fails_without_touching_raw(self):
        with tempfile.TemporaryDirectory() as temp, patch("dashcam_render.media_tool", return_value="ffmpeg"), \
             patch("dashcam_stitch.probe_track", return_value=None):
            root = Path(temp)
            music = root / "music"
            music.mkdir()
            (music / "bad.wav").write_bytes(b"not audio")
            raw = root / "part_000000.mkv"
            raw.write_bytes(b"raw sentinel")
            capture = SimpleNamespace(directory=root, active=True)
            renderer = BackgroundRenderer(capture, music, "Title")
            renderer.start()
            renderer.wait()
            self.assertEqual(renderer.state, "failed")
            self.assertEqual(raw.read_bytes(), b"raw sentinel")
            self.assertTrue(capture.active)

    def test_existing_render_folder_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "Rendered").mkdir()
            existing = root / "Rendered" / "part_000000.mp4"
            existing.write_bytes(b"keep")
            renderer = BackgroundRenderer(SimpleNamespace(directory=root, active=True), root, "Title")
            with self.assertRaises(FileExistsError):
                renderer.start()
            self.assertEqual(existing.read_bytes(), b"keep")

    def test_disk_failure_stops_only_renderer_process(self):
        with tempfile.TemporaryDirectory() as temp, patch("dashcam_render.shutil.disk_usage", return_value=SimpleNamespace(free=0)):
            capture = SimpleNamespace(directory=Path(temp), active=True)
            renderer = BackgroundRenderer(capture, Path(temp), "Title")
            renderer.directory.mkdir()
            process = Process()
            with patch("dashcam_render.subprocess.Popen", return_value=process):
                renderer._execute(["fake"])
            self.assertTrue(capture.active)
            self.assertTrue(renderer._stop.is_set())
            self.assertIsNotNone(process.poll())
            self.assertTrue(process.stdin.closed)
            self.assertIsNone(renderer.process)

    def test_stop_waiting_renderer_leaves_raw_capture_running(self):
        with tempfile.TemporaryDirectory() as temp, patch("dashcam_render.media_tool", return_value="ffmpeg"):
            root = Path(temp)
            capture = SimpleNamespace(directory=root, active=True)
            renderer = BackgroundRenderer(capture, root, "Title")
            with patch("dashcam_render.build_music_playlist", return_value=(root / "playlist", [], 1, 8)):
                renderer.start()
                renderer.stop()
                renderer.wait()
            self.assertEqual(renderer.state, "stopped")
            self.assertTrue(capture.active)

    def test_close_stops_both_jobs_before_waiting(self):
        capture = SimpleNamespace(active=True, stop=Mock(), wait=Mock(side_effect=TimeoutError()))
        renderer = SimpleNamespace(active=True, stop=Mock(), wait=Mock())
        finalizer = SimpleNamespace(active=True, stop=Mock(), wait=Mock())
        panel = SimpleNamespace(capture=capture, renderer=renderer, finalizer=finalizer, _stop_preview=Mock())
        with self.assertRaises(TimeoutError):
            CameraPanel.shutdown(panel)
        capture.stop.assert_called_once()
        renderer.stop.assert_called_once()
        finalizer.stop.assert_called_once()

    def test_intro_only_first_segment_endcard_only_final(self):
        args = ([Track(Path("music"), 100, "Title", "Artist")], 3, 100, 30,
                [Path("track.txt")], None, Path("channel.txt"), 20)
        first = presentation_filter(*args, final_segment=False)
        middle = presentation_filter(*args, timeline_offset=30, final_segment=False)
        last = presentation_filter(*args, timeline_offset=60, final_segment=True)
        self.assertIn("between(t,0,3)+0", first)
        self.assertNotIn("fade=t=in", middle)
        self.assertIn("enable='0+0'", middle)
        self.assertIn("mod(t+30.000,100.000)", middle)
        self.assertIn("enable='0+gte(t,10.000)'", last)


if __name__ == "__main__":
    unittest.main()
